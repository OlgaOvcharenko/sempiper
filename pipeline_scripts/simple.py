import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")

products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer the manufacturer from product attributes.",
    impute_with_existing_values_only=True,
)

result = products.skb.eval()
