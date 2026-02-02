import os

os.environ.setdefault("SCIPY_ARRAY_API", "1")

import warnings

import pandas as pd
import skrub
from sklearn.ensemble import HistGradientBoostingClassifier

import sempipes
from sempipes import sem_choose

warnings.filterwarnings("ignore")

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0})
)

DATA_PATH = "data/met_10k.csv"
N_SAMPLES = 1000

full_df = pd.read_csv(DATA_PATH)

if len(full_df) >= N_SAMPLES:
    sample_df = full_df.sample(n=N_SAMPLES, random_state=912).copy()
else:
    sample_df = full_df.copy()


sample_df = sample_df.drop(columns=["department", "source_file", "image"], errors="ignore")
sample_df["object_name_raw"] = sample_df["object_name"]

artworks = skrub.var("artworks", sample_df)

culture_target = sempipes.as_y(
    artworks["culture"],
    "The cultural or geographic origin of the artwork",
)

artwork_data = sempipes.as_X(
    artworks[list(set(sample_df.columns) - {"culture"})],
    "Artwork metadata including date, description, medium, and object name",
)

artwork_data = artwork_data.sem_extract_features(
    nl_prompt="""
    Extract 4 columns from the 'date' string to handle centuries, ranges, and BCE flags.
    
    Handle 'century' (e.g., 5th century -> 400-499)
    Handle 'century pairs' (e.g., 3rd–4th century -> 200-399)
    Handle BCE centuries properly (e.g., 5th century b.c. -> 499-400)
    Handle BCE flags. This can appear as b.c, b.c.e, bc, or bce.
    Handle early, mid and late partitions.
    
    IMPORTANT: Return ONLY valid Python code inside a code block.
    DO NOT use transformers.
    CRITICAL: The 'date' column may contain NaNs (floats). You MUST check `if not isinstance(val, str): return ...` at the very start of your helper functions.
    """,
    name="extract_dates",
    input_columns=["date"],
    output_columns={
        "year_start": "What is the start year as a positive integer? If only one year is given, start=end.",
        "start_is_bce": "Is the start year BCE/BC? (True/False)",
        "year_end": "What is the end year as a positive integer?",
        "end_is_bce": "Is the end year BCE/BC? (True/False)",
    },
    generate_via_code=True,
)

artwork_data = artwork_data.sem_extract_features(
    nl_prompt="""
    Extract simple text features using REGEX only.
    - Check for presence of words like 'Greek', 'Roman', 'Latin' in description.
    - Check for specific historical figures if mentioned.
    - Keep it very simple and fast.
    CRITICAL: Do NOT use spacy, nltk or transformers. Use 're' module only.
    """,
    name="extract_desc_features",
    input_columns=["description"],
    output_columns={
        "historical_mythological_figures": "Extract names using simple regex patterns (capitalized words after 'King', 'Queen', etc).",
        "geographic_location": "Extract location names using simple regex (capitalized words after 'in', 'from').",
        "period_descriptors": "Extract period names if present (e.g. 'Renaissance', 'Baroque').",
        "contains_latin_words": "True if description contains common Latin words/roots.",
        "contains_greek_words": "True if description contains common Greek words/roots.",
        "fashion_jargon": "Extract fashion terms (e.g. 'silk', 'velvet', 'embroidery')."
    },
    generate_via_code=True,
)

artwork_data = artwork_data.sem_clean(
    nl_prompt="""
    Standardize the 'object_name' column.
    - Convert to lowercase.
    - Remove special characters, noise, and extra whitespace.
    - Group similar items (e.g., 'fragments', 'fragment' -> 'fragment') using simple string rules or regex.
    - Handle missing values.
    IMPORTANT: Do NOT hardcode large dictionaries for mapping. Use algorithmic cleaning only (regex).
    CRITICAL: DO NOT import any libraries other than pandas, numpy, and re. DO NOT import skrub.
    """,
    columns=["object_name"],
)

vectorizer = skrub.TableVectorizer()
vectorized_artworks = artwork_data.skb.apply(
    vectorizer,
    exclude_cols=["object_ID"],
)

hgb = HistGradientBoostingClassifier()

culture_classifier = vectorized_artworks.skb.apply_with_sem_choose(
    hgb,
    y=culture_target,
    choices=sem_choose(
        name="hgb_hyperparams",
        max_depth="Depth of trees for a high-cardinality classification task",
    ),
)

res = culture_classifier.skb.cross_validate(cv=5)

test_scores = res['test_score']
print(f"\nTest scores per fold: {test_scores}")
print(f"Mean accuracy: {test_scores.mean():.2%}")
print(f"Std deviation: {test_scores.std():.2%}")

print(sample_df["culture"].value_counts())

