# Simple full pipeline: X/y from baskets → fill product gaps → features on basket products
# Run with: python this_script.py (requires skrub, sempipes)

import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)
baskets = baskets.skb.subsample(n=5000, how="random")

# 1) Define X and y from baskets
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets with product transactions")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Binary flag for fraudulent basket")

# 2) Fill product gaps (manufacturer)
products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer the manufacturer from product attributes.",
)

# 3) Use filled products in basket context and add a few features (closes the pipeline)
kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
kept_products = kept_products.sem_gen_features(
    nl_prompt="Add one or two useful product features for prediction.",
    how_many=2,
)
