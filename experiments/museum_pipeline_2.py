import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import warnings
import pandas as pd
import skrub
import spacy

from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion

import sempipes


warnings.filterwarnings("ignore")

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0}),
    llm_for_batch_processing=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.0})
)

DATA_PATH = "experiments/data/met_10k.csv"
N_SAMPLES = 100

full_df = pd.read_csv(DATA_PATH)

if len(full_df) >= N_SAMPLES:
    sample_df = full_df.sample(n=N_SAMPLES, random_state=912).copy()
else:
    sample_df = full_df.copy()

sample_df = sample_df.drop(columns=["department", "source_file", "image"], errors="ignore")
sample_df["object_name_raw"] = sample_df["object_name"]

def apply_spacy_features(df):
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        from spacy.cli import download
        download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")

    print("Running spaCy extraction (Cultural Group + People)...")
    
    ent_norp = [] 
    ent_person = [] 
    
    docs = list(nlp.pipe(df['title'].fillna("").astype(str)))

    for doc in docs:
        ent_norp.append(", ".join({e.text for e in doc.ents if e.label_ == "NORP"}))
        ent_person.append(", ".join({e.text for e in doc.ents if e.label_ == "PERSON"}))

    df["ent_cultural_group"] = ent_norp
    df["ent_people"] = ent_person
    
    return df

sample_df = apply_spacy_features(sample_df)

artworks = skrub.var("artworks", sample_df)

culture_target = sempipes.as_y(
    artworks["culture"],
    "The cultural or geographic origin of the artwork",
)

artwork_data = sempipes.as_X(
    artworks[list(set(sample_df.columns) - {"culture"})],
    "Artwork metadata including date, description, medium, and other features",
)

artwork_data = artwork_data.sem_extract_features(
    nl_prompt="""
    Extract useful keywords related to cultural origin, demonyms, religions, locations, or famous people.
    """,
    name="extract_desc_features",
    input_columns=["description"],
    generate_via_code=True,
)

artwork_data = artwork_data.sem_clean(
    nl_prompt="Standardize the 'object_name' column.",
    columns=["object_name"],
)


vectorizer = skrub.TableVectorizer()
vectorized_artworks = artwork_data.skb.apply(
    vectorizer,
    exclude_cols=["object_ID"],
)

tabpfn = TabPFNClassifier.create_default_for_version(ModelVersion.V2, device='cpu')

pred_pipeline = vectorized_artworks.skb.apply(tabpfn, y=culture_target)

res = pred_pipeline.skb.cross_validate(cv=2)

test_scores = res['test_score']
print(f"\nTest scores per fold: {test_scores}")
print(f"Mean accuracy: {test_scores.mean():.2%}")

print("\nTarget Distribution:")
print(sample_df["culture"].value_counts())