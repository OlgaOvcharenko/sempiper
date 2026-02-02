import os

os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
from sklearn.ensemble import HistGradientBoostingClassifier

import sempipes
from sempipes import sem_choose
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

# FIXME get random features that LLM suggests
# TODO try w/o these features first 
house_data = house_data.sem_extract_features(
    nl_prompt=f"""Extract features useful for the house price detection. I have already extracted the following features: {list(set(houses_df.columns) - {"image_path", "image_id"})},I am interested in up to 10 additional useful features like surrounding area, number of rooms, house size, house appearance, pool and garage availability, and so on.""",
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
)


# FIXME Model
tabpfn = TabPFNRegressor()
# tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2)

pred = house_data.skb.apply(tabpfn, y=price)
pred.skb.cross_validate(cv=2)['test_score']