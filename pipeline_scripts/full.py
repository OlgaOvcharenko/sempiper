import time
import sempipes

import skrub
from catboost import CatBoostClassifier

time_start = time.time()

dataset = skrub.datasets.fetch_credit_fraud()

products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)

# products = products.skb.subsample(n=1000, how="random")
baskets = baskets.skb.subsample(n=1000, how="random")

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
    nl_prompt="Infer the manufacturer from relevant product-related attributes like title or description. Please use only fast and efficient methods like regex or rules-based approaches to infer the manufacturer.",
    impute_with_existing_values_only=True,
)

unique_brands = products[["make"]].drop_duplicates().reset_index(drop=True)

brand_risk_info = unique_brands.sem_extract_features(
    nl_prompt="""
    Use your intrinsic knowledge about manufacturers/brands from column `make` to extract features that are useful for the fraudulent shopping baskets prediction. Please use only fast and efficient methods to extract the features, no pre-trained models.
    """,
    name="brand_risk_features",
    input_columns=["make"],
    generate_via_code=True,
)

products_enriched = products.merge(brand_risk_info, on="make", how="left")

kept_products = products_enriched[products_enriched["basket_ID"].isin(basket_ids["ID"])]

kept_products = kept_products.sem_gen_features(
    nl_prompt="""
    Generate additional brand- and manufacturer-related product features. Make sure that they can be efficiently computed on large datasets, and that they work across a large number of brands and manufacturers. Use your intrinsic knowledge about what products and brands fraudsters focus on to make sure that the new features are helpful for the prediction task at hand.
    """,
    name="brand_features",
    how_many=5,
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

catboost_regressor = CatBoostClassifier()

fraud_detector = augmented_baskets.skb.apply(
    catboost_regressor,
    y=fraud_flags
)

res = fraud_detector.skb.cross_validate(cv=2)
