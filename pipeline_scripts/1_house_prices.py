import os

from sklearn.metrics import mean_squared_error

import sempipes
import skrub

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

    houses = skrub.var("houses")

    price = sempipes.as_y(
        houses["price"],
        "The selling price of the house in USD"
    )

    house_data = sempipes.as_X(
        houses[list(set(houses_df.columns) - {"price"})],
        "Data describing house and its location."
    )

    # Data cleaning with sem_clean (showcases LLM-generated cleaning code)
    house_data = house_data.sem_clean(
        nl_prompt="""Clean the numeric housing data. Handle outliers in sqft (square footage) using IQR capping. Ensure bath and bed are valid integers. Remove clearly erroneous values.""",
        columns=["sqft", "bath", "bed"]
    )

    # Feature extraction from images (showcases multimodal capability)
    house_data = house_data.sem_extract_features(
        nl_prompt="""Use your intrinsic knowledge about houses and their location in California to extract features that are useful for house price prediction.""",
        name="extract_visuals",
        input_columns=["image_path"],
        generate_via_code=True
    )

    # Feature generation (showcases domain-specific feature engineering)
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

    # Train and evaluate with TabPFN
    tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2)
    predictions = vectorized_houses.skb.apply(tabpfn, y=price)

    return predictions

# Load dataset
data_dir = os.path.join(os.path.dirname(__file__), "house_prices_normalized")
fact_houses = pd.read_csv(os.path.join(data_dir, "fact_houses.csv"))
dim_cities = pd.read_csv(os.path.join(data_dir, "dim_cities.csv"))
dim_images = pd.read_csv(os.path.join(data_dir, "dim_images.csv"))

# Join dataset with DuckDB to create denormalized dataset
con = duckdb.connect()
houses_df = con.execute("""
    SELECT
        f.image_id,
        f.price,
        f.bath,
        f.bed,
        f.sqft,
        i.image_path,
        c.city_name
    FROM fact_houses f
    JOIN dim_cities c ON f.city_id = c.city_id
    JOIN dim_images i ON f.image_id = i.image_id
""").df()
con.close()

# Run pipeline
houses_df = houses_df.sample(50, random_state=42)
pipeline = sempipes_pipeline()

train_houses, test_houses = train_test_split(houses_df, test_size=0.25, random_state=42)
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

# Create environment for training and testing
env_train = pipeline.skb.get_data()
env_train["houses"] = train_houses
env_test = pipeline.skb.get_data()
env_test["houses"] = test_houses

learner.fit(env_train)
y_pred = learner.predict(env_test)
mse = mean_squared_error(test_houses["price"], y_pred)
print(f"MSE: {mse}")


# Append predictions to test_houses
test_houses["predicted_price"] = y_pred

# Exploring house price insights for test_houses
con = duckdb.connect()
analysis = con.execute("""
    WITH price_segments AS (
        SELECT
            *,
            NTILE(4) OVER (ORDER BY price) AS price_quartile,
            price / sqft AS price_per_sqft
        FROM test_houses
    ),
    city_analysis AS (
        SELECT
            city_name,
            COUNT(*) AS num_houses,
            ROUND(AVG(price), 0) AS avg_price,
            ROUND(MEDIAN(price), 0) AS median_price,
            ROUND(MIN(price), 0) AS min_price,
            ROUND(MAX(price), 0) AS max_price,
            ROUND(AVG(sqft), 0) AS avg_sqft,
            ROUND(AVG(price_per_sqft), 0) AS avg_price_per_sqft,
            ROUND(AVG(bed), 1) AS avg_bed,
            ROUND(AVG(bath), 1) AS avg_bath,
            ROUND(STDDEV(price), 0) AS price_stddev
        FROM price_segments
        GROUP BY city_name
    ),
    market_position AS (
        SELECT
            *,
            RANK() OVER (ORDER BY avg_price DESC) AS price_rank,
            RANK() OVER (ORDER BY avg_price_per_sqft DESC) AS value_rank,
            RANK() OVER (ORDER BY num_houses DESC) AS volume_rank,
            ROUND(100.0 * (avg_price - MIN(avg_price) OVER ()) /
                  NULLIF(MAX(avg_price) OVER () - MIN(avg_price) OVER (), 0), 1) AS price_percentile
        FROM city_analysis
    )
    SELECT
        city_name,
        num_houses,
        avg_price,
        median_price,
        avg_sqft,
        avg_price_per_sqft AS price_sqft,
        avg_bed AS beds,
        avg_bath AS baths,
        price_rank,
        price_percentile AS price_pctl
    FROM market_position
    ORDER BY avg_price DESC
""").df()
con.close()

print("\n=== House Price Market Analysis by City ===")
print(analysis.to_string(index=False))