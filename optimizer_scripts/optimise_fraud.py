import os
import warnings
import sempipes
import skrub
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from catboost import CatBoostClassifier
from sempipes.optimisers import optimise_colopro, MonteCarloTreeSearch

warnings.filterwarnings("ignore")

# Unified config to match demo defaults
sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.1}),
    llm_for_batch_processing=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.0})
)

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

    # Simplified products pipeline for speed during optimization
    unique_brands = products[["make"]].drop_duplicates().reset_index(drop=True)

    brand_risk_info = unique_brands.sem_extract_features(
        nl_prompt="Extract fraud-relevant features from the make column.",
        name="brand_risk_features",
        input_columns=["make"],
        generate_via_code=True,
    )

    products_enriched = products.merge(brand_risk_info, on="make", how="left")
    kept_products = products_enriched[products_enriched["basket_ID"].isin(basket_ids["ID"])]

    kept_products = kept_products.sem_gen_features(
        nl_prompt="Generate brand-related features useful for fraud prediction.",
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
print("\n> Loading Credit Fraud Data for Optimization...")
dataset = skrub.datasets.fetch_credit_fraud()
baskets_df = dataset.baskets.sample(n=1000, random_state=42)
train_baskets, _ = train_test_split(baskets_df, test_size=0.25, random_state=42)

pipeline = sempipes_pipeline()

outcomes = optimise_colopro(
    dag_sink=pipeline,
    operator_name="brand_features",
    num_trials=5,
    scoring="roc_auc",
    cv=3,
    search=MonteCarloTreeSearch(),
    run_name="optimise_fraud",
    additional_env_variables={
        "products": dataset.products,
        "baskets": train_baskets
    },
    n_jobs_for_evaluation=1,
)

best_outcome = max(outcomes, key=lambda x: x.score)
print(f"\nBest Score: {best_outcome.score:.4f}")
print(f"Best Trial: {best_outcome.search_node.trial}")
