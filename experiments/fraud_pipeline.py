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

print("\n> Loading Credit Fraud Data...")
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)

baskets = baskets.skb.subsample(n=5000, how="random")

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
    nl_prompt="Infer the manufacturer from relevant product-related attributes like title or description.",
    impute_with_existing_values_only=True,
)

unique_brands = products[["make"]].skb.apply_func(
    lambda df: df.groupby("make").size().reset_index(name="frequency")
)

brand_risk_info = unique_brands.sem_extract_features(
    nl_prompt="""
    Analyze this manufacturer/brand based on its name and transaction frequency.
    Estimate its luxury status and potential for black market resale (fencing).
    Return float values between 0.0 and 1.0.
    """,
    name="brand_risk_features",
    input_columns=["make", "frequency"],
    output_columns={
        "luxury_score": "How high-end or luxury is this brand? (0-1 score based on name patterns)",
        "fencing_risk": "How easily can items from this brand be resold? (0-1 score based on frequency and name)",
    },
    generate_via_code=True,
)

products_enriched = products.merge(brand_risk_info, on="make", how="left")

kept_products = products_enriched[products_enriched["basket_ID"].isin(basket_ids["ID"])]

kept_products = kept_products.sem_gen_features(
    nl_prompt="""
    Generate additional brand- and manufacturer-related product features. Make sure that they can be efficiently computed
    on large datasets, and that they work across a large number of brands and manufacturers. Use your intrinsic knowledge 
    about what products and brands fraudsters focus on to make sure that the new features are helpful for the prediction task 
    at hand.
    """,
    name="brand_features",
    how_many=5,
)

print("\n> Vectorizing and Aggregating Basket Data...")
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
).drop(columns=["ID", "basket_ID"])

print("\n> Building and Optimizing Fraud Detector...")
hgb = HistGradientBoostingClassifier()

fraud_detector = augmented_baskets.skb.apply_with_sem_choose(
    hgb,
    y=fraud_flags,
    choices=sem_choose(
        name="hgb_choices", 
        max_depth="Common range of values for the maximum depth of the learned trees"
    ),
)

# Evaluate with cross-validation
res = fraud_detector.skb.cross_validate(cv=5)

test_scores = res["test_score"]
print(f"\nTest scores per fold: {test_scores}")
print(f"Mean accuracy: {test_scores.mean():.2%}")
print(f"Std deviation: {test_scores.std():.2%}")