import os

from sklearn.metrics import r2_score

import sempipes
import skrub

import numpy as np
import pandas as pd
import duckdb

from tabpfn import TabPFNRegressor
from tabpfn.constants import ModelVersion
from sklearn.model_selection import train_test_split

from sempipes.optimisers import MonteCarloTreeSearch, optimise_colopro


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
        bed_bath_ratio=((house_data.bed) / (house_data.bath + 1)),
        sqft_per_bed=((house_data.sqft) / (house_data.bed + 1)),
    )

    house_data = house_data.skb.apply_func(lambda df: df.reset_index(drop=True))

    
    # Feature extraction from images 
    house_data = house_data.sem_extract_features(
        nl_prompt="""Use your intrinsic knowledge about houses and their location in California to extract features that are useful for house price prediction. Ensure that extracted features are not null or empty.""",
        name="extract_visuals",
        input_columns=["image_path"],
        generate_via_code=True
    )

    # Feature generation
    house_data = house_data.sem_gen_features(
        nl_prompt="""Generate additional features useful for California house price prediction. Consider location, property characteristics, and market indicators. Ensure that generated features are not null or empty. Take into account that number of bedrooms and bathrooms can be 0 and produce divide by 0 errors.""",
        name="generated_features",
        how_many=5,
    )

    # Vectorization with skrub TableVectorizer
    vectorizer = skrub.TableVectorizer()
    vectorized_houses = house_data.skb.apply(
        vectorizer,
        exclude_cols=["image_id", "image_path"]
    )

    # Drop near-constant columns before TabPFN
    vectorized_houses = vectorized_houses.skb.drop(cols=["image_id", "image_path"])

    # Train and evaluate with TabPFN
    tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2)
    predictions = vectorized_houses.skb.apply(tabpfn, y=price)

    def analyze_house_prices(predictions, houses):
        # Nothing during fit, analyze only during predict
        if not isinstance(predictions, (np.ndarray, pd.Series)):
            return

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


def _create_env(facts, cities, images, operator_name, operator_name2, state):
    """Create environment dictionary for learner."""
    return {
        "facts": facts,
        "cities": cities,
        "images": images,
        f"sempipes_memory__{operator_name}": None,
        f"sempipes_pipeline_summary__{operator_name}": None,
        f"sempipes_prefitted_state__{operator_name}": state,
        f"sempipes_inspirations__{operator_name}": None,

        f"sempipes_memory__{operator_name2}": None,
        f"sempipes_pipeline_summary__{operator_name2}": None,
        f"sempipes_prefitted_state__{operator_name2}": None,
        f"sempipes_inspirations__{operator_name2}": None,
    }


# Load dataset
data_dir = os.path.join(os.path.dirname(__file__), "house_prices_normalized")
fact_houses = pd.read_csv(os.path.join(data_dir, "fact_houses.csv"))
dim_cities = pd.read_csv(os.path.join(data_dir, "dim_cities.csv"))
dim_images = pd.read_csv(os.path.join(data_dir, "dim_images.csv"))

# Run pipeline
fact_houses = fact_houses.sample(10000, random_state=42)
optimizable_operator = "extract_visuals"
nonoptimizable_operator2 = "generated_features"
pipeline = sempipes_pipeline()

train_houses, test_houses = train_test_split(fact_houses, test_size=0.25, random_state=42)
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

# Optimize pipeline
outcomes = optimise_colopro(
    pipeline,
    operator_name=optimizable_operator,
    scoring="r2",
    cv=2,
    num_trials=10,
    search=MonteCarloTreeSearch(),
    num_hpo_iterations_per_trial=10,
    additional_env_variables={"facts": train_houses, "cities": dim_cities, "images": dim_images},
    run_name="house_prices_optimizable",
)

best_outcome = max(outcomes, key=lambda x: (x.score, -x.search_node.trial))

learner_optimized = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)
learner_optimized.fit(
    _create_env(
        train_houses,
        dim_cities,
        dim_images,
        optimizable_operator,
        nonoptimizable_operator2,
        best_outcome.state,
    )
)

optimized_results = learner_optimized.predict(
    _create_env(
        test_houses,
        dim_cities,
        dim_images,
        optimizable_operator,
        nonoptimizable_operator2,
        best_outcome.state,
    )
)

r2 = r2_score(test_houses["price"], optimized_results)
print(f"R2: {r2}")
