import os

from sklearn.metrics import mean_squared_error

import sempipes
import skrub

import pandas as pd
import duckdb

from tabpfn import TabPFNRegressor
from tabpfn.constants import ModelVersion
from sklearn.model_selection import train_test_split

from sempipes.optimisers import optimise_colopro, MonteCarloTreeSearch

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0}),
    llm_for_batch_processing=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.0})
)

def sempipes_pipeline(houses_columns):

    houses = skrub.var("houses")

    price = sempipes.as_y(
        houses["price"],
        "The selling price of the house in USD"
    )

    house_data = sempipes.as_X(
        houses[list(set(houses_columns) - {"price"})],
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

# Subsample for faster optimization loop
houses_df = houses_df.sample(50, random_state=42)

# Run pipeline
pipeline = sempipes_pipeline(houses_columns=houses_df.columns)

train_houses, test_houses = train_test_split(houses_df, test_size=0.25, random_state=42)

outcomes = optimise_colopro(
    dag_sink=pipeline,
    operator_name="generated_features",
    num_trials=5,
    scoring="neg_root_mean_squared_error",
    cv=3,
    search=MonteCarloTreeSearch(c=0.5),
    run_name="optimise_house",
    additional_env_variables={
        "houses": train_houses
    },
    n_jobs_for_evaluation=1,
)

best_outcome = max(outcomes, key=lambda x: x.score)
print(f"\\\\nBest Score: {best_outcome.score:.4f}")
print(f"Best Trial: {best_outcome.search_node.trial}")
