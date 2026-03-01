import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
from sklearn.ensemble import HistGradientBoostingClassifier
import sempipes
from sempipes import sem_choose
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


def sempipes_pipeline():
    products = skrub.var("products")
    baskets = skrub.var("baskets")

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
    vectorized_products = kept_products.skb\
        .apply(vectorizer, exclude_cols=["basket_ID"])
    aggregated_products = vectorized_products\
        .groupby("basket_ID").agg("mean").reset_index()
    augmented_baskets = basket_ids\
        .merge(aggregated_products, left_on="ID", right_on="basket_ID")\
        .drop(columns=["ID", "basket_ID"])

    # 4) Train classifier with sem_choose (hyperparameters)
    hgb = HistGradientBoostingClassifier()
    fraud_detector = augmented_baskets.skb.apply_with_sem_choose(
        hgb,
        y=fraud_flags,
        choices=sem_choose(name="hgb_choices", max_depth="Common range for tree depth"),
    )

    return fraud_detector


# Load dataset
dataset = skrub.datasets.fetch_credit_fraud()
baskets_df = dataset.baskets.sample(n=50, random_state=42)
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
