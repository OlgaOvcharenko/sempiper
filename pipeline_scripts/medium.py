# Medium full pipeline: X/y → fillna → gen_features → vectorize → aggregate → train (sem_choose)
# Run with: python this_script.py (requires skrub, sempipes, sklearn)

import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
from sklearn.ensemble import HistGradientBoostingClassifier
import sempipes
from sempipes import sem_choose

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)
baskets = baskets.skb.subsample(n=5000, how="random")

# 1) X and y from baskets
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")

# 2) Fill product gaps, then features on basket products
products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer manufacturer from product attributes.",
    impute_with_existing_values_only=True,
)
kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
kept_products = kept_products.sem_gen_features(
    nl_prompt="Generate brand- and manufacturer-related features.",
    name="brand_features",
    how_many=5,
)

# 3) Vectorize and aggregate per basket, then merge with X
vectorizer = skrub.TableVectorizer()
vectorized_products = kept_products.skb.apply(vectorizer, exclude_cols="basket_ID")
aggregated_products = vectorized_products.groupby("basket_ID").agg("mean").reset_index()
augmented_baskets = basket_ids.merge(aggregated_products, left_on="ID", right_on="basket_ID").drop(
    columns=["ID", "basket_ID"]
)

# 4) Train classifier with sem_choose (hyperparameters)
hgb = HistGradientBoostingClassifier()
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(
    hgb,
    y=fraud_flags,
    choices=sem_choose(name="hgb_choices", max_depth="Common range for tree depth"),
)
