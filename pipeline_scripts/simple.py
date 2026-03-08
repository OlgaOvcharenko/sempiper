import skrub
from sklearn.ensemble import HistGradientBoostingClassifier
import sempipes


def sempipes_pipeline():
    products = skrub.var("products")
    baskets = skrub.var("baskets")

    fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")
    basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")

    kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
    kept_products = kept_products.sem_gen_features(
        nl_prompt="Generate useful features for product analysis.",
        name="product_features",
        how_many=2,
    )

    augmented_baskets = basket_ids.sem_agg_features(
        kept_products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt="Aggregate product features per basket for fraud detection.",
        name="basket_features",
        how_many=1,
    )

    hgb = HistGradientBoostingClassifier()
    fraud_detector = augmented_baskets.skb.apply(hgb, y=fraud_flags)

    return fraud_detector


# Load dataset
dataset = skrub.datasets.fetch_credit_fraud()
baskets = dataset.baskets.sample(n=50, random_state=42)

# Run pipeline
pipeline = sempipes_pipeline()
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

env = pipeline.skb.get_data()
env["products"] = dataset.products
env["baskets"] = baskets

learner.fit(env)
y_pred = learner.predict(env)
print(f"Accuracy: {(y_pred == baskets['fraud_flag'].values).mean():.2%}")
