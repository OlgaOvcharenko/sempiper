import warnings

import numpy as np
import pandas as pd
import skrub
from sklearn.ensemble import HistGradientBoostingClassifier
from skrub import DataOp, TableVectorizer

warnings.filterwarnings("ignore")

_OP_BASKETS = "op_baskets_features"
_OP_PRODUCTS = "op_product_features"
_OP_AGG = "op_agg_features"


def _pipeline() -> DataOp:
    products = skrub.var("products")
    baskets = skrub.var("data")
    labels = skrub.var("labels")

    baskets = baskets.skb.mark_as_X().skb.set_description(
        "Potentially fraudulent shopping baskets of products"
    )
    labels = labels.skb.mark_as_y().skb.set_description(
        "Flag indicating whether the basket is fraudulent (1) or not (0)"
    )

    baskets_copy = baskets.copy(deep=True)
    baskets_copy = baskets_copy.assign(
        random_col1=lambda df: np.random.rand(len(df)),
        random_col2=lambda df: np.random.choice(["A", "B", "C"], size=len(df)),
    )
    baskets_copy = baskets_copy.skb.set_description(
        "Potentially fraudulent shopping baskets of products"
    )

    baskets_copy = baskets_copy.sem_gen_features(
        nl_prompt=(
            "Generate features that are indicative of potentially fraudulent "
            "baskets, make it easy to distinguish anomalous baskets from regular ones."
        ),
        name=_OP_BASKETS,
        how_many=5,
    )

    products = products.sem_gen_features(
        nl_prompt=(
            "Generate product features that are indicative of potentially fraudulent baskets."
        ),
        name=_OP_PRODUCTS,
        how_many=5,
    )

    aggregated = baskets.sem_agg_features(
        products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt=(
            "Generate product features that are indicative of potentially fraudulent "
            "baskets, make it easy to distinguish anomalous baskets from regular ones! "
            "It might be helpful to combine different product statistics."
        ),
        name=_OP_AGG,
        how_many=1,
    )

    aggregated = aggregated.merge(baskets_copy, on="ID")
    encoded = aggregated.skb.apply(TableVectorizer())
    return encoded.skb.apply(HistGradientBoostingClassifier(random_state=0), y=labels)


dataset = skrub.datasets.fetch_credit_fraud()
all_baskets = dataset["baskets"]
nonfraudulent_baskets = all_baskets[all_baskets.fraud_flag == 0]
fraudulent_baskets = all_baskets[all_baskets.fraud_flag == 1]
baskets = pd.concat([nonfraudulent_baskets.iloc[:4000], fraudulent_baskets.iloc[:1000]])

# This script is used to display/replay precomputed optimizer trajectories in the UI.
data = baskets[["ID"]]
labels = baskets["fraud_flag"]
products = dataset["products"]

pipeline = _pipeline()
