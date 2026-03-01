import os

from sklearn.metrics import mean_squared_error
from sklearn.feature_selection import VarianceThreshold

import sempipes
import skrub

import numpy as np
import pandas as pd
import duckdb

from tabpfn import TabPFNRegressor
from tabpfn.constants import ModelVersion
from sklearn.model_selection import train_test_split


sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0}),
    llm_for_batch_processing=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.0})
)


def sempipes_pipeline():
    houses_facts = skrub.var("facts")
    houses_cities = skrub.var("cities")
    house_images = skrub.var("images")

    houses = houses_facts.merge(houses_cities, on="city_id").merge(house_images, on="image_id")

    price = sempipes.as_y(
        houses["price"],
        "The selling price of the house in USD"
    )

    house_data = sempipes.as_X(
        houses.drop(columns=["price"]),
        "Data describing house and its location."
    )

    # Data cleaning
    house_data = house_data.sem_clean(
        nl_prompt="""Clean the numeric housing data. Handle outliers in sqft (square footage) using IQR capping. Remove clearly erroneous values.""",
        columns=["sqft"]
    )

    house_data = house_data.assign(
        sqft_log=house_data["sqft"].apply(lambda x: np.log1p(float(x))),
        bed_bath_ratio=house_data.bed / house_data.bath,
        sqft_per_bed=house_data.sqft / house_data.bed,
    )


    # Feature extraction from images
    house_data = house_data.sem_extract_features(
        nl_prompt="""Use your intrinsic knowledge about houses and their location in California to extract features that are useful for house price prediction.""",
        name="extract_visuals",
        input_columns=["image_path"],
        generate_via_code=True
    )

    # Feature generation
    house_data = house_data.sem_gen_features(
        nl_prompt="""Generate additional features useful for California house price prediction. Consider location, property characteristics, and market indicators.""",
        name="generated_features",
        how_many=5,
    )

    # Vectorization with skrub TableVectorizer
    vectorizer = skrub.TableVectorizer()
    vectorized_houses = house_data.skb.apply(
        vectorizer,
        exclude_cols=["image_id", "image_path"]
    )

    # # Drop near-constant columns before TabPFN
    # selector = VarianceThreshold(threshold=0.01)
    # vectorized_houses = vectorized_houses.skb.drop(cols=["image_id", "image_path"]).skb.apply(selector)

    # Train and evaluate with TabPFN
    tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2)
    predictions = vectorized_houses.skb.apply(tabpfn, y=price)

    def analyze_house_prices(predictions, houses):
        # Nothing during fit, analyze only during predict
        if not isinstance(predictions, (np.ndarray, pd.Series)):
            return

        #  Combine predictions with houses
        houses["predicted_price"] = predictions

        # Analyze house prices
        con = duckdb.connect()
        analysis = con.execute("""
            WITH price_segments AS (
                SELECT
                    *,
                    NTILE(4) OVER (ORDER BY price) AS price_quartile,
                    price / sqft AS price_per_sqft
                FROM houses
            ),
            city_analysis AS (
                SELECT
                    city_name,
                    COUNT(*) AS num_houses,
                    ROUND(AVG(price), 0) AS avg_price,
                    ROUND(MEDIAN(price), 0) AS median_price,
                    ROUND(AVG(sqft), 0) AS avg_sqft,
                    ROUND(AVG(price_per_sqft), 0) AS avg_price_per_sqft,
                    ROUND(AVG(bed), 1) AS avg_bed,
                    ROUND(AVG(bath), 1) AS avg_bath,
                    ROUND(AVG(predicted_price), 0) AS avg_predicted_price
                FROM price_segments
                GROUP BY city_name
            )
            SELECT *, RANK() OVER (ORDER BY avg_price DESC) AS price_rank
            FROM city_analysis
            ORDER BY avg_price DESC
        """).df()
        con.close()

        print(analysis)

        return

    predictions.skb.apply_func(analyze_house_prices, houses=houses)

    return predictions

# Load dataset
data_dir = os.path.join(os.path.dirname(__file__), "house_prices_normalized")
fact_houses = pd.read_csv(os.path.join(data_dir, "fact_houses.csv"))
dim_cities = pd.read_csv(os.path.join(data_dir, "dim_cities.csv"))
dim_images = pd.read_csv(os.path.join(data_dir, "dim_images.csv"))

print(fact_houses)

# Run pipeline
fact_houses = fact_houses.sample(50, random_state=42)
pipeline = sempipes_pipeline()

train_houses, test_houses = train_test_split(fact_houses, test_size=0.25, random_state=42)
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

# Create environment for training and testing
env_train = pipeline.skb.get_data()
env_train["facts"] = train_houses
env_train["cities"] = dim_cities
env_train["images"] = dim_images

print(train_houses)

env_test = pipeline.skb.get_data()
env_test["facts"] = test_houses
env_test["cities"] = dim_cities
env_test["images"] = dim_images

learner.fit(env_train)
y_pred = learner.predict(env_test)

mse = mean_squared_error(test_houses["price"], y_pred)
print(f"MSE: {mse}")
