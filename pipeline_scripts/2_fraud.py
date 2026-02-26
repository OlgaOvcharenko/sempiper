import time
import sempipes

import warnings
warnings.filterwarnings("ignore")

import skrub
from catboost import CatBoostClassifier

# 3rd party libraries for diverse processing
import nltk
from nltk.tokenize import word_tokenize
import numpy as np
import pandas as pd
from scipy import stats
from unidecode import unidecode

from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

# Download NLTK data if needed
for resource, path in [('punkt_tab', 'tokenizers/punkt_tab'), ('stopwords', 'corpora/stopwords')]:
    try:
        nltk.data.find(path)
    except LookupError:
        nltk.download(resource, quiet=True)

# Materialize as a plain frozenset — NLTK's LazyCorpusLoader is not picklable,
# which causes a RecursionError when skrub/cloudpickle serializes the learner.
from nltk.corpus import stopwords as _nltk_stopwords
ENGLISH_STOP_WORDS = frozenset(_nltk_stopwords.words('english'))

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0})
)

def extract_text_features(text):
    """Extract text features using nltk and unidecode."""
    if pd.isna(text) or text == "":
        return pd.Series({
            'normalized_name': '',
            'word_count': 0,
            'has_stopwords': False,
            'avg_word_length': 0
        })
    normalized = unidecode(str(text)).lower()
    tokens = word_tokenize(normalized)
    has_stopwords = any(t in ENGLISH_STOP_WORDS for t in tokens)
    avg_word_len = np.mean([len(t) for t in tokens]) if tokens else 0
    return pd.Series({
        'normalized_name': normalized,
        'word_count': len(tokens),
        'has_stopwords': has_stopwords,
        'avg_word_length': avg_word_len
    })


def add_text_features(df):
    text_features = df['make'].apply(extract_text_features)
    return pd.concat([df.reset_index(drop=True), text_features.reset_index(drop=True)], axis=1)


def add_price_stats(df):
    price_stats = df.groupby('make')['cash_price'].agg([
        ('price_mean', 'mean'),
        ('price_std', 'std'),
        ('price_skew', lambda x: stats.skew(x) if len(x) > 2 else 0),
        ('price_kurtosis', lambda x: stats.kurtosis(x) if len(x) > 3 else 0)
    ]).reset_index()
    return df.merge(price_stats, on='make', how='left')


def sempipes_pipeline():
    products = skrub.var("products")
    baskets = skrub.var("baskets")

    fraud_flags = sempipes.as_y(
        baskets["fraud_flag"],
        "A binary flag indicating a fraudulent shopping basket",
    )

    basket_ids = sempipes.as_X(
        baskets[["ID"]],
        "Shopping baskets with product transactions",
    )

    products = products.sem_fillna(
        target_column="make",
        nl_prompt="Infer the manufacturer from relevant product attributes like title or description.",
        impute_with_existing_values_only=True,
    )

    products = products.skb.apply_func(add_text_features)
    products = products.skb.apply_func(add_price_stats)

    unique_brands = products[["make"]].drop_duplicates().reset_index(drop=True)

    brand_risk_info = unique_brands.sem_extract_features(
        nl_prompt="""
        Extract fraud-relevant features from the `make` column using your knowledge.
        Generate features like: is_luxury_brand, is_known_brand, brand_risk_score.
        """,
        name="brand_risk_features",
        input_columns=["make"],
        generate_via_code=True,
    )

    products_enriched = products.merge(brand_risk_info, on="make", how="left")

    kept_products = products_enriched[products_enriched["basket_ID"].isin(basket_ids["ID"])]

    kept_products = kept_products.sem_gen_features(
        nl_prompt="""
        Generate brand-related features useful for fraud prediction. Focus on efficiency and broad applicability across brands. Remove unnecessary features.
        """,
        name="brand_features",
        how_many=3,
    )

    vectorizer = skrub.TableVectorizer()
    vectorized_products = kept_products.skb.apply(
        vectorizer,
        exclude_cols=["basket_ID"],
    )

    aggregated_products = vectorized_products.groupby("basket_ID").agg("mean").reset_index()

    augmented_baskets = basket_ids.merge(
        aggregated_products,
        left_on="ID",
        right_on="basket_ID",
        how="left"
    ).drop(columns=["ID", "basket_ID"])

    catboost_classifier = CatBoostClassifier(verbose=0, iterations=100)
    fraud_detector = augmented_baskets.skb.apply(
        catboost_classifier,
        y=fraud_flags
    )

    return fraud_detector


# Load dataset
print("\n> Loading Credit Fraud Data...")
dataset = skrub.datasets.fetch_credit_fraud()
baskets_df = dataset.baskets.sample(n=1000, random_state=42)
train_baskets, test_baskets = train_test_split(baskets_df, test_size=0.25, random_state=42)

# Run pipeline
pipeline = sempipes_pipeline()
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

env_train = pipeline.skb.get_data()
env_train["products"] = dataset.products
env_train["baskets"] = train_baskets

env_test = pipeline.skb.get_data()
env_test["products"] = dataset.products
env_test["baskets"] = test_baskets

learner.fit(env_train)
y_pred = learner.predict(env_test)

accuracy = accuracy_score(test_baskets["fraud_flag"], y_pred)
print(f"Accuracy: {accuracy:.2%}")