import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(
    n=100, how="random")

products = products.sem_gen_features(
    nl_prompt="Generate useful features for product analysis.",
    name="product_features",
    how_many=3,
)

result = products.skb.eval()
