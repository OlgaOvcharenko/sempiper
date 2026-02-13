import os

import sempipes
import skrub

import pandas as pd

import kagglehub

from tabpfn import TabPFNRegressor
from tabpfn.constants import ModelVersion

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0}),
    llm_for_batch_processing=sempipes.LLM("gemini/gemini-2.5-flash-lite", {"temperature": 0.0})
)

# Download latest version
path = kagglehub.dataset_download("ted8080/house-prices-and-images-socal")
print("Path to dataset files:", path)

# Turn image id into path 
houses_df = pd.read_csv(os.path.join(path, "socal2.csv"))
houses_df["image_path"] = os.path.join(path, "socal2", "socal_pics") + "/" + houses_df["image_id"].astype(str) + ".jpg"
houses_df = houses_df.sample(500, random_state=42)

# TODO JOIN: Denormalize data and split big datasets

# Set X and y
houses = skrub.var("houses", houses_df)

price = sempipes.as_y(
    houses["price"], 
    "The selling price of the house in USD"
)

house_data = sempipes.as_X(
    houses[list(set(houses_df.columns) - {"price"})],
    "Data describing house and its location."
)

house_data = house_data.sem_extract_features(
    nl_prompt=f"""Use your intrinsic knowledge about houses and their location in California to extract features that are useful for the house price detection.""",
    name="extract_visuals",
    input_columns=["image_path"],
    generate_via_code=True
)

# Combine all features, aka feature generation and selection
house_data = house_data.sem_gen_features(
    nl_prompt=f"""Generate additional features useful for the house price detection. Use your intrinsic knowledge about house pricing in California to generate useful features.""",
    name="brand_features",
    how_many=5,
)

vectorizer = skrub.TableVectorizer()
vectorized_houses = house_data.skb.apply(
    vectorizer, 
    exclude_cols=["image_id", "image_path"] 
).drop(columns=["image_id", "image_path"])

tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2) # TODO Maybe use a different model? Like TabICL

pred = vectorized_houses.skb.apply(tabpfn, y=price)
res = pred.skb.cross_validate(cv=2)

# TODO JOIN: OLAP SQL query O_O