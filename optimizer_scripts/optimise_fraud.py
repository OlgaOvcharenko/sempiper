import sempipes
from sempipes.optimisers import TreeSearch, optimise_colopro
import skrub
from catboost import CatBoostClassifier
import nltk
from nltk.tokenize import word_tokenize
import numpy as np
import pandas as pd
from scipy import stats
from unidecode import unidecode

from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
import skrub.selectors as s
from scipy.stats import shapiro
from nltk.corpus import stopwords as _nltk_stopwords

# Download NLTK data if needed
for resource, path in [('punkt_tab', 'tokenizers/punkt_tab'), ('stopwords', 'corpora/stopwords')]:
    try:
        nltk.data.find(path)
    except LookupError:
        nltk.download(resource, quiet=True)
ENGLISH_STOP_WORDS = frozenset(_nltk_stopwords.words('english'))


def shapiro_test(df):
    for col in df.columns[:-1]:
        _, p = shapiro(df[col])
        print(col, p)


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

    # Add text features
    products = products.assign(
        normalized_name=lambda x: x["make"].apply(lambda x: unidecode(str(x)).lower()),
        word_count=lambda x: x["make"].apply(lambda x: len(word_tokenize(unidecode(str(x)).lower()))),
        has_stopwords=lambda x: x["make"].apply(lambda x: any(t in ENGLISH_STOP_WORDS for t in word_tokenize(unidecode(str(x)).lower()))),
        avg_word_length=lambda x: x["make"].apply(lambda x: np.mean([len(t) for t in word_tokenize(unidecode(str(x)).lower())]) if word_tokenize(unidecode(str(x)).lower()) else 0)
    )

    # Add price statistics
    analysis = products.groupby('make')['cash_price'].agg([
        ('price_mean', 'mean'),
        ('price_std', 'std'),
        ('price_skew', lambda x: stats.skew(x) if len(x) > 2 else 0),
        ('price_kurtosis', lambda x: stats.kurtosis(x) if len(x) > 3 else 0)
    ]).reset_index()
    print(analysis)
        
    unique_brands = products[["make"]].drop_duplicates().reset_index(drop=True)

    brand_risk_info = unique_brands.sem_extract_features(
        nl_prompt="""
        Extract fraud-relevant features from brand names. Modify df in place and return it; do NOT return df unchanged. Generate features like: is_luxury_brand, is_known_brand, brand_risk_score. Focus on your internal knowledge about existing brands and their risk scores.
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

    products.skb.apply_func(shapiro_test)

    # Aggregate product features per basket 
    augmented_baskets = basket_ids.sem_agg_features(
        kept_products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt="""
        Aggregate the product features by basket ID. For numeric columns use mean,
        sum, and count. For categorical columns use mode. Use simple pandas groupby
        with a dict of aggregation functions — do not use tuple-kwargs syntax.
        """,
        name="basket_aggregated_features",
        how_many=1,
    )

    augmented_baskets = augmented_baskets.skb.drop(cols=["ID"])

    vectorizer = skrub.TableVectorizer()
    vectorized_baskets = augmented_baskets.skb.apply(vectorizer)

    catboost_classifier = CatBoostClassifier(verbose=0, iterations=100)
    fraud_detector = vectorized_baskets.skb.apply(
        catboost_classifier,
        y=fraud_flags
    )

    return fraud_detector


def _create_env(products, baskets, operator_name, operator_name2, operator_name3, state):
    """Create environment dictionary for learner."""
    return {
        "products": products,
        "baskets": baskets,
        f"sempipes_memory__{operator_name}": None,
        f"sempipes_pipeline_summary__{operator_name}": None,
        f"sempipes_prefitted_state__{operator_name}": state,
        f"sempipes_inspirations__{operator_name}": None,

        f"sempipes_memory__{operator_name2}": None,
        f"sempipes_pipeline_summary__{operator_name2}": None,
        f"sempipes_prefitted_state__{operator_name2}": None,
        f"sempipes_inspirations__{operator_name2}": None,

        f"sempipes_memory__{operator_name3}": None,
        f"sempipes_pipeline_summary__{operator_name3}": None,
        f"sempipes_prefitted_state__{operator_name3}": None,
        f"sempipes_inspirations__{operator_name3}": None,
    }


# Load dataset
dataset = skrub.datasets.fetch_credit_fraud()
baskets_df = dataset.baskets
train_baskets, test_baskets = train_test_split(baskets_df, test_size=0.25, random_state=42)

# Run pipeline
optimizable_operator = "brand_risk_features"
nonoptimizable_operator2 = "brand_features"
nonoptimizable_operator3 = "basket_aggregated_features"
pipeline = sempipes_pipeline()
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

# Optimize pipeline
outcomes = optimise_colopro(
    pipeline,
    operator_name=optimizable_operator,
    scoring="f1",
    cv=3,
    num_trials=10,
    search=TreeSearch(min_num_drafts=2),
    num_hpo_iterations_per_trial=10,
    additional_env_variables={"products": dataset.products, "baskets": train_baskets},
    run_name="fraud",
)

best_outcome = max(outcomes, key=lambda x: (x.score, -x.search_node.trial))
print(best_outcome.state["generated_code"])

learner_optimized = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)
learner_optimized.fit(_create_env(dataset.products, train_baskets, optimizable_operator, nonoptimizable_operator2, nonoptimizable_operator3, best_outcome.state))
optimized_results = learner_optimized.predict(_create_env(dataset.products, test_baskets, optimizable_operator, nonoptimizable_operator2, nonoptimizable_operator3, best_outcome.state))


f1 = f1_score(test_baskets["fraud_flag"], optimized_results, average="macro")
print(f"F1 Score: {f1:.2%}")
