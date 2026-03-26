"""Exact source-range tests for fraud.py, house_prices.py, and museums.py.

The pipeline script texts are embedded verbatim so tests remain valid even
if the files on disk change later.  All line/column numbers were verified
with extract_nodes_with_ranges at the time these tests were written.

Column convention (same as the rest of the test-suite):
  • 1-indexed
  • start_column: first character of the matched token
  • end_column: exclusive (one past the last character)
  → line[start_column-1 : end_column-1] == highlighted_text
"""

import pytest
from services.compile_parse import extract_nodes_with_ranges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nodes_with_label(nodes, label: str):
    return [n for n in nodes if n.label == label]


def _nodes_containing(nodes, substring: str):
    return [n for n in nodes if substring.lower() in n.label.lower()]


def _highlighted(code: str, node) -> str:
    """Return the text highlighted by a node's source range."""
    sr = node.source_range
    assert sr is not None, f"Node {node.label!r} has no source_range"
    line = code.splitlines()[sr.start_line - 1]
    return line[sr.start_column - 1 : sr.end_column - 1]


# ---------------------------------------------------------------------------
# Embedded scripts (verbatim copies at time of writing)
# ---------------------------------------------------------------------------

FRAUD_SCRIPT = """\
import time
import sempipes

import warnings
warnings.filterwarnings("ignore")

import skrub
from catboost import CatBoostClassifier

# 3rd party libraries for diverse processing
import nltk
from nltk.tokenize import word_tokenize
import numpy as np
import pandas as pd
from scipy import stats
from unidecode import unidecode

from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
import skrub.selectors as s
from scipy.stats import shapiro

# Download NLTK data if needed
for resource, path in [('punkt_tab', 'tokenizers/punkt_tab'), ('stopwords', 'corpora/stopwords')]:
    try:
        nltk.data.find(path)
    except LookupError:
        nltk.download(resource, quiet=True)

# Materialize as a plain frozenset — NLTK's LazyCorpusLoader is not picklable,
# which causes a RecursionError when skrub/cloudpickle serializes the learner.
from nltk.corpus import stopwords as _nltk_stopwords
ENGLISH_STOP_WORDS = frozenset(_nltk_stopwords.words('english'))

sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0})
)

def shapiro_test(df):
    for col in df.columns[:-1]:
        stat, p = shapiro(df[col])
        print(col, p)


def sempipes_pipeline():
    products = skrub.var("products")
    baskets = skrub.var("baskets")

    fraud_flags = sempipes.as_y(
        baskets["fraud_flag"],
        "A binary flag indicating a fraudulent shopping basket",
    )

    basket_ids = sempipes.as_X(
        baskets[["ID"]],
        "Shopping baskets with product transactions",
    )

    products = products.sem_fillna(
        target_column="make",
        nl_prompt="Infer the manufacturer from relevant product attributes like title or description.",
        impute_with_existing_values_only=True,
    )

    # Add text features
    products = products.assign(
        normalized_name=lambda x: x["make"].apply(lambda x: unidecode(str(x)).lower()),
        word_count=lambda x: x["make"].apply(lambda x: len(word_tokenize(unidecode(str(x)).lower()))),
        has_stopwords=lambda x: x["make"].apply(lambda x: any(t in ENGLISH_STOP_WORDS for t in word_tokenize(unidecode(str(x)).lower()))),
        avg_word_length=lambda x: x["make"].apply(lambda x: np.mean([len(t) for t in word_tokenize(unidecode(str(x)).lower())]) if word_tokenize(unidecode(str(x)).lower()) else 0)
    )

    # Add price statistics
    analysis = products.groupby('make')['cash_price'].agg([
        ('price_mean', 'mean'),
        ('price_std', 'std'),
        ('price_skew', lambda x: stats.skew(x) if len(x) > 2 else 0),
        ('price_kurtosis', lambda x: stats.kurtosis(x) if len(x) > 3 else 0)
    ]).reset_index()
    print(analysis)

    unique_brands = products[["make"]].drop_duplicates().reset_index(drop=True)

    brand_risk_info = unique_brands.sem_extract_features(
        nl_prompt=\"\"\"
        Extract fraud-relevant features from the `make` column using your knowledge.
        Generate features like: is_luxury_brand, is_known_brand, brand_risk_score.
        \"\"\",
        name="brand_risk_features",
        input_columns=["make"],
        generate_via_code=True,
    )

    products_enriched = products.merge(brand_risk_info, on="make", how="left")

    kept_products = products_enriched[products_enriched["basket_ID"].isin(basket_ids["ID"])]

    kept_products = kept_products.sem_gen_features(
        nl_prompt=\"\"\"
        Generate brand-related features useful for fraud prediction. Focus on efficiency and broad applicability across brands. Remove unnecessary features.
        \"\"\",
        name="brand_features",
        how_many=3,
    )

    products.skb.apply_func(shapiro_test)

    vectorizer = skrub.TableVectorizer()
    vectorized_products = kept_products.skb.apply(
        vectorizer,
        exclude_cols=["basket_ID"],
    )

    augmented_baskets = basket_ids.sem_agg_features(
        vectorized_products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt=\"\"\"
        Aggregate the product features by basket ID.
        \"\"\",
        name="basket_features",
        how_many=1,
    )

    augmented_baskets = augmented_baskets.skb.drop(cols=["ID"])


    catboost_classifier = CatBoostClassifier(verbose=0, iterations=100)
    fraud_detector = augmented_baskets.skb.apply(
        catboost_classifier,
        y=fraud_flags
    )

    return fraud_detector


# Load dataset
dataset = skrub.datasets.fetch_credit_fraud()
baskets_df = dataset.baskets.sample(n=1000, random_state=42)
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
"""

HOUSE_PRICES_SCRIPT = """\
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
        nl_prompt=\"\"\"Clean the numeric housing data. Handle outliers in sqft (square footage) using IQR capping. Remove clearly erroneous values.\"\"\",
        columns=["sqft"]
    )

    house_data = house_data.assign(
        sqft_log=house_data["sqft"].apply(lambda x: np.log1p(float(x))),
        bed_bath_ratio=house_data.bed / house_data.bath,
        sqft_per_bed=house_data.sqft / house_data.bed,
    )


    # Feature extraction from images
    house_data = house_data.sem_extract_features(
        nl_prompt=\"\"\"Use your intrinsic knowledge about houses and their location in California to extract features that are useful for house price prediction.\"\"\",
        name="extract_visuals",
        input_columns=["image_path"],
        generate_via_code=True
    )

    # Feature generation
    house_data = house_data.sem_gen_features(
        nl_prompt=\"\"\"Generate additional features useful for California house price prediction. Consider location, property characteristics, and market indicators.\"\"\",
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
        analysis = con.execute(\"\"\"
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
        \"\"\").df()
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
"""

MUSEUMS_SCRIPT = """\
import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import warnings
import numpy as np
import pandas as pd
import skrub
import spacy
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from skrub import selectors as s

import sempipes

warnings.filterwarnings("ignore")


class FeatureTokenizer(nn.Module):
    \"\"\"Embeds each scalar feature into a d_token-dimensional vector.\"\"\"

    def __init__(self, n_features: int, d_token: int) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.empty(n_features, d_token))
        self.bias = nn.Parameter(torch.zeros(n_features, d_token))
        nn.init.kaiming_uniform_(self.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, n_features) → (batch, n_features, d_token)
        return x.unsqueeze(-1) * self.weight.unsqueeze(0) + self.bias.unsqueeze(0)


class FTTransformerModel(nn.Module):
    \"\"\"Feature Tokenizer + Transformer (Gorishniy et al. 2021).

    Each input feature is projected into a d_token-dimensional token.
    A learnable [CLS] token is prepended and the sequence is processed
    by a standard transformer encoder. The CLS output is used for classification.
    \"\"\"

    def __init__(self, n_features: int, n_classes: int, d_token: int = 64,
                 n_heads: int = 8, n_layers: int = 3, dropout: float = 0.1) -> None:
        super().__init__()
        self.tokenizer = FeatureTokenizer(n_features, d_token)
        self.cls_token = nn.Parameter(torch.empty(1, 1, d_token))
        nn.init.normal_(self.cls_token, std=0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_token,
            nhead=n_heads,
            dim_feedforward=d_token * 4,
            dropout=dropout,
            batch_first=True,
            norm_first=True,  # Pre-LayerNorm for stable training
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(d_token)
        self.head = nn.Linear(d_token, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        tokens = self.tokenizer(x)                              # (B, n_features, d_token)
        cls = self.cls_token.expand(x.size(0), -1, -1)         # (B, 1, d_token)
        tokens = torch.cat([cls, tokens], dim=1)                # (B, n_features+1, d_token)
        out = self.transformer(tokens)                          # (B, n_features+1, d_token)
        cls_out = self.norm(out[:, 0])                          # (B, d_token)
        return self.head(cls_out)                               # (B, n_classes)


class FTTransformerClassifier(BaseEstimator, ClassifierMixin):
    \"\"\"Sklearn-compatible wrapper around FTTransformerModel.\"\"\"

    def __init__(self, d_token: int = 64, n_heads: int = 8, n_layers: int = 3,
                 dropout: float = 0.1, lr: float = 1e-4,
                 n_epochs: int = 50, batch_size: int = 64) -> None:
        self.d_token = d_token
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.dropout = dropout
        self.lr = lr
        self.n_epochs = n_epochs
        self.batch_size = batch_size

    def fit(self, X, y):
        self.label_encoder_ = LabelEncoder()
        y_enc = self.label_encoder_.fit_transform(y)
        n_classes = len(self.label_encoder_.classes_)

        self.imputer_ = SimpleImputer(strategy="mean")
        self.scaler_ = StandardScaler()
        X_proc = self.scaler_.fit_transform(self.imputer_.fit_transform(X))

        n_features = X_proc.shape[1]
        self.model_ = FTTransformerModel(n_features, n_classes, self.d_token,
                                         self.n_heads, self.n_layers, self.dropout)
        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        criterion = nn.CrossEntropyLoss()

        X_t = torch.tensor(X_proc, dtype=torch.float32)
        y_t = torch.tensor(y_enc, dtype=torch.long)
        loader = DataLoader(TensorDataset(X_t, y_t), batch_size=self.batch_size, shuffle=True)

        self.model_.train()
        for _ in range(self.n_epochs):
            for xb, yb in loader:
                optimizer.zero_grad()
                criterion(self.model_(xb), yb).backward()
                nn.utils.clip_grad_norm_(self.model_.parameters(), max_norm=1.0)
                optimizer.step()
        return self

    def _preprocess(self, X) -> torch.Tensor:
        X_proc = self.scaler_.transform(self.imputer_.transform(X))
        return torch.tensor(X_proc, dtype=torch.float32)

    def predict(self, X):
        self.model_.eval()
        with torch.no_grad():
            logits = self.model_(self._preprocess(X))
        indices = logits.argmax(dim=1).numpy()
        return self.label_encoder_.inverse_transform(indices)

    def predict_proba(self, X):
        self.model_.eval()
        with torch.no_grad():
            logits = self.model_(self._preprocess(X))
        return torch.softmax(logits, dim=1).numpy()

def fill_missing_values(df):
    \"\"\"Fill NaN values in all columns so sem_refine validation passes.\"\"\"
    df[s.select(df, s.string()).columns] = s.select(df, s.string()).fillna("")
    df[s.select(df, s.numeric()).columns] = s.select(df, s.numeric()).fillna(0)
    df[s.select(df, s.boolean()).columns] = s.select(df, s.boolean()).fillna(False)
    return df


def apply_spacy_features(df):
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        from spacy.cli import download
        download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")

    print("Running spaCy extraction (Entities + Linguistic Features)...")

    ent_norp = []
    ent_person = []
    ent_loc = []
    ent_date = []

    noun_phrases = []
    adj_density = []
    docs = list(nlp.pipe(df['description'].fillna("").astype(str)))

    for doc in docs:
        ent_norp.append(", ".join({e.text for e in doc.ents if e.label_ == "NORP"}))
        ent_person.append(", ".join({e.text for e in doc.ents if e.label_ == "PERSON"}))
        ent_loc.append(", ".join({e.text for e in doc.ents if e.label_ in ("GPE", "LOC")}))
        ent_date.append(", ".join({e.text for e in doc.ents if e.label_ == "DATE"}))

        chunks = [chunk.text for chunk in doc.noun_chunks if len(chunk.text.split()) > 1]
        noun_phrases.append(", ".join(chunks))

        n_adj = len([t for t in doc if t.pos_ == "ADJ"])
        n_words = len(doc)
        adj_density.append((n_adj / n_words) if n_words > 0 else 0.0)

    df["ent_cultural_group"] = ent_norp
    df["ent_people"] = ent_person
    df["ent_location"] = ent_loc
    df["ent_period"] = ent_date
    df["desc_noun_phrases"] = noun_phrases
    df["desc_adjective_density"] = adj_density

    return df


sempipes.update_config(
    llm_for_code_generation=sempipes.LLM("gemini/gemini-2.5-flash", {"temperature": 0.0})
)


def sempipes_pipeline():
    artworks = skrub.var("artworks")
    artworks = artworks.skb.apply_func(apply_spacy_features)

    culture_target = sempipes.as_y(
        artworks["culture"],
        "The cultural or geographic origin of the artwork.",
    )

    artwork_data = sempipes.as_X(
        artworks.drop(columns=["culture"]),
        "Artwork metadata including date, description, and extracted features.",
    )

    artwork_data = artwork_data.sem_extract_features(
        nl_prompt=\"\"\"
        Convert the date strings into precise integer intervals. Currently, the `date` column contains a mix of formats. Your task is to rework it into a structured format with the following columns:  `year_start`, `start_is_bce`, `year_end`, and `end_is_bce`. If any information is missing or cannot be parsed, leave the corresponding fields empty. Try to parse as much information as possible, even from vague descriptions. For example, "5th century BCE" should be parsed as `year_start` = 500, `start_is_bce` = True, `year_end` = 401, `end_is_bce` = True. If the date is a single year like "1500", it should be parsed as `year_start` = 1500, `start_is_bce` = False, and the end fields should be empty.
        \"\"\",
        name="extract_dates",
        input_columns=["date"],
        output_columns={
            "year_start": "Start year",
            "start_is_bce": "Is starting year BCE?",
            "year_end": "End year",
            "end_is_bce": "Is end year BCE?",
        },
        generate_via_code=True,
    )

    artwork_data = artwork_data.sem_gen_features(
        nl_prompt=\"\"\"
        Help me create additional features that could be useful for predicting the culture of an artwork. Remove any features that are not relevant or could introduce noise.
        \"\"\",
        name="generate_additional_features",
    )

    artwork_data = artwork_data.skb.apply_func(fill_missing_values)

    artwork_data = artwork_data.sem_refine(
        nl_prompt="Standardize the `object_name` column that contains raw museum object names.",
        target_column="object_name",
        refine_with_existing_values_only=False,
    )

    artwork_data = artwork_data.drop(columns=["object_name_raw", "object_ID"], errors="ignore")

    artwork_data = artwork_data.skb.apply(skrub.TableVectorizer())

    ft_transformer = FTTransformerClassifier()
    pred = artwork_data.skb.apply(ft_transformer, y=culture_target)

    return pred


# Get data
data_path = "demo_scripts/met_10k.csv"
n_samples = 100

museum_objects = pd.read_csv(data_path)
museum_objects = museum_objects.drop(columns=["department", "source_file", "image"], errors="ignore")
museum_objects["object_name_raw"] = museum_objects["object_name"]

museum_objects = museum_objects.sample(n=n_samples, random_state=42).copy()
train_museum_objects, test_museum_objects = train_test_split(museum_objects, test_size=0.25, random_state=42)


# Run pipeline
pipeline = sempipes_pipeline()
learner = pipeline.skb.make_learner(fitted=False, keep_subsampling=False)

# Create environment for training and testing
env_train = pipeline.skb.get_data()
env_train["artworks"] = train_museum_objects
env_test = pipeline.skb.get_data()
env_test["artworks"] = test_museum_objects

learner.fit(env_train)
y_pred = learner.predict(env_test)
f1 = f1_score(test_museum_objects["culture"], y_pred, average="weighted")
print(f"F1 Score: {f1}")
"""


# ===========================================================================
# fraud.py tests
# ===========================================================================

class TestFraudScriptSourceRanges:
    """Exact source-range assertions for the fraud pipeline script.

    Line/column numbers are 1-indexed.  The pipeline lives inside
    `def sempipes_pipeline():` which starts at line 45.
    """

    def setup_method(self):
        self.nodes, _ = extract_nodes_with_ranges(FRAUD_SCRIPT)

    def test_compiles_to_non_empty_graph(self):
        assert len(self.nodes) > 0, "fraud script should produce nodes"

    def test_exact_node_count(self):
        """Parser must return exactly 12 nodes for the fraud script.

        The 12 nodes are: 2 vars, as_y, as_X, sem_fillna,
        sem_extract_features, merge, sem_gen_features,
        2x skb.apply, sem_agg_features, drop.
        groupby (dead-end branch) and skb.apply_func (no-LHS side-effect)
        are pruned by _prune_dead_branches.
        """
        assert len(self.nodes) == 12, (
            f"Expected 12 nodes, got {len(self.nodes)}: "
            f"{[n.label for n in self.nodes]}"
        )

    # --- var nodes -----------------------------------------------------------

    def test_products_var_line_and_column(self):
        """products = skrub.var("products")  →  line 46, cols 16-25"""
        nodes = _nodes_with_label(self.nodes, "<Var 'products'>")
        assert len(nodes) == 1, f"Expected 1 <Var 'products'> node, got {len(nodes)}"
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 46, f"Expected line 46, got {sr.start_line}"
        assert sr.start_column == 16, f"Expected start_col 16, got {sr.start_column}"
        assert sr.end_column == 25, f"Expected end_col 25, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "skrub.var"

    def test_baskets_var_line_and_column(self):
        """baskets = skrub.var("baskets")  →  line 47, cols 15-24"""
        nodes = _nodes_with_label(self.nodes, "<Var 'baskets'>")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 47, f"Expected line 47, got {sr.start_line}"
        assert sr.start_column == 15, f"Expected start_col 15, got {sr.start_column}"
        assert sr.end_column == 24, f"Expected end_col 24, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "skrub.var"

    def test_var_nodes_on_different_lines(self):
        """products and baskets vars must be on consecutive distinct lines."""
        products = _nodes_with_label(self.nodes, "<Var 'products'>")[0]
        baskets = _nodes_with_label(self.nodes, "<Var 'baskets'>")[0]
        assert products.source_range.start_line != baskets.source_range.start_line

    # --- as_y / as_X ---------------------------------------------------------

    def test_as_y_line_and_column(self):
        """fraud_flags = sempipes.as_y(  →  line 49, cols 28-32"""
        nodes = _nodes_with_label(self.nodes, "as_y")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 49, f"Expected line 49, got {sr.start_line}"
        assert sr.start_column == 28, f"Expected start_col 28, got {sr.start_column}"
        assert sr.end_column == 32, f"Expected end_col 32, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "as_y"

    def test_as_x_line_and_column(self):
        """basket_ids = sempipes.as_X(  →  line 54, cols 27-31"""
        nodes = _nodes_with_label(self.nodes, "as_X")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 54, f"Expected line 54, got {sr.start_line}"
        assert sr.start_column == 27, f"Expected start_col 27, got {sr.start_column}"
        assert sr.end_column == 31, f"Expected end_col 31, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "as_X"

    # --- semantic operators --------------------------------------------------

    def test_sem_fillna_line_and_column(self):
        """products = products.sem_fillna(  →  line 59, cols 25-35"""
        nodes = _nodes_with_label(self.nodes, "sem_fillna")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 59, f"Expected line 59, got {sr.start_line}"
        assert sr.start_column == 25, f"Expected start_col 25, got {sr.start_column}"
        assert sr.end_column == 35, f"Expected end_col 35, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "sem_fillna"

    def test_sem_extract_features_line_and_column(self):
        """unique_brands.sem_extract_features(  →  line 84, cols 37-57"""
        nodes = _nodes_with_label(self.nodes, "sem_extract_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 84, f"Expected line 84, got {sr.start_line}"
        assert sr.start_column == 37, f"Expected start_col 37, got {sr.start_column}"
        assert sr.end_column == 57, f"Expected end_col 57, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "sem_extract_features"

    def test_sem_gen_features_line_and_column(self):
        """kept_products.sem_gen_features(  →  line 98, cols 35-51"""
        nodes = _nodes_with_label(self.nodes, "sem_gen_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 98, f"Expected line 98, got {sr.start_line}"
        assert sr.start_column == 35, f"Expected start_col 35, got {sr.start_column}"
        assert sr.end_column == 51, f"Expected end_col 51, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "sem_gen_features"

    def test_sem_agg_features_line_and_column(self):
        """basket_ids.sem_agg_features(  →  line 114, cols 36-52"""
        nodes = _nodes_with_label(self.nodes, "sem_agg_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 114, f"Expected line 114, got {sr.start_line}"
        assert sr.start_column == 36, f"Expected start_col 36, got {sr.start_column}"
        assert sr.end_column == 52, f"Expected end_col 52, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, nodes[0]) == "sem_agg_features"

    def test_skb_apply_func_line_and_column(self):
        """products.skb.apply_func(shapiro_test) is a dead-end side-effect — pruned."""
        func_nodes = _nodes_with_label(self.nodes, "skb.apply_func")
        assert len(func_nodes) == 0, (
            f"Expected 0 skb.apply_func nodes (pruned dead end), got {len(func_nodes)}"
        )

    # --- pandas / skb operations --------------------------------------------

    def test_groupby_line_and_column(self):
        """products.groupby('make') feeds only print() — dead-end branch, pruned."""
        nodes = _nodes_containing(self.nodes, "groupby")
        assert len(nodes) == 0, (
            f"Expected 0 groupby nodes (pruned dead end), got {len(nodes)}"
        )

    def test_merge_line_and_column(self):
        """products.merge(brand_risk_info, ...)  →  line 94, cols 34-39"""
        nodes = _nodes_containing(self.nodes, "merge")
        assert len(nodes) >= 1
        node = next(n for n in nodes if n.source_range and n.source_range.start_line == 94)
        sr = node.source_range
        assert sr.start_column == 34, f"Expected start_col 34, got {sr.start_column}"
        assert sr.end_column == 39, f"Expected end_col 39, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, node) == "merge"

    def test_skb_apply_vectorizer_line_and_column(self):
        """kept_products.skb.apply(vectorizer, ...)  →  line 109, cols 41-50"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 109)
        sr = node.source_range
        assert sr.start_column == 41, f"Expected start_col 41, got {sr.start_column}"
        assert sr.end_column == 50, f"Expected end_col 50, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, node) == "skb.apply"

    def test_skb_apply_catboost_line_and_column(self):
        """augmented_baskets.skb.apply(catboost_classifier, ...)  →  line 129, cols 40-49"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 129)
        sr = node.source_range
        assert sr.start_column == 40, f"Expected start_col 40, got {sr.start_column}"
        assert sr.end_column == 49, f"Expected end_col 49, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, node) == "skb.apply"

    def test_two_skb_apply_nodes_on_different_lines(self):
        """The two skb.apply calls must be on different lines (vectorizer vs catboost)."""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        assert len(apply_nodes) == 2, f"Expected 2 skb.apply nodes, got {len(apply_nodes)}"
        lines = sorted(n.source_range.start_line for n in apply_nodes if n.source_range)
        assert lines[0] != lines[1], "The two skb.apply nodes should be on different lines"
        assert lines == [109, 129], f"Expected lines [109, 129], got {lines}"

    def test_skb_drop_line_and_column(self):
        """augmented_baskets.skb.drop(cols=["ID"])  →  line 125, cols 47-51"""
        drop_nodes = _nodes_with_label(self.nodes, "drop")
        node = next(n for n in drop_nodes if n.source_range and n.source_range.start_line == 125)
        sr = node.source_range
        assert sr.start_column == 47, f"Expected start_col 47, got {sr.start_column}"
        assert sr.end_column == 51, f"Expected end_col 51, got {sr.end_column}"
        assert _highlighted(FRAUD_SCRIPT, node) == "drop"

    # --- document order sanity -----------------------------------------------

    def test_pipeline_nodes_in_document_order(self):
        """Semantic operators must appear in strict document order."""
        ordered_labels = [
            ("<Var 'products'>", 46),
            ("<Var 'baskets'>", 47),
            ("as_y", 49),
            ("as_X", 54),
            ("sem_fillna", 59),
            ("sem_extract_features", 84),
            ("sem_gen_features", 98),
            ("sem_agg_features", 114),
        ]
        for label, expected_line in ordered_labels:
            nodes = _nodes_with_label(self.nodes, label)
            assert len(nodes) >= 1, f"Node {label!r} not found"
            actual = nodes[0].source_range.start_line
            assert actual == expected_line, (
                f"Node {label!r}: expected line {expected_line}, got {actual}"
            )

    def test_all_source_ranges_within_script(self):
        """Every source range must fall within the script's line count."""
        max_line = len(FRAUD_SCRIPT.splitlines())
        for node in self.nodes:
            if node.source_range:
                sr = node.source_range
                assert 1 <= sr.start_line <= max_line, (
                    f"Node {node.label!r}: start_line {sr.start_line} out of range"
                )
                assert 1 <= sr.end_line <= max_line, (
                    f"Node {node.label!r}: end_line {sr.end_line} out of range"
                )


# ===========================================================================
# house_prices.py tests
# ===========================================================================

class TestHousePricesScriptSourceRanges:
    """Exact source-range assertions for the house_prices pipeline script.

    The pipeline lives inside `def sempipes_pipeline():` at line 24.
    """

    def setup_method(self):
        self.nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_SCRIPT)

    def test_compiles_to_non_empty_graph(self):
        assert len(self.nodes) > 0, "house_prices script should produce nodes"

    def test_exact_node_count(self):
        """Parser must return exactly 12 nodes for the house_prices script.

        The 12 nodes are: 3 vars, merge, as_y, as_X, drop, sem_clean,
        sem_extract_features, sem_gen_features, 2x skb.apply.
        skb.apply_func (no-LHS dead-end side-effect) is pruned by _prune_dead_branches.
        """
        assert len(self.nodes) == 12, (
            f"Expected 12 nodes, got {len(self.nodes)}: "
            f"{[n.label for n in self.nodes]}"
        )

    # --- var nodes -----------------------------------------------------------

    def test_facts_var_line_and_column(self):
        """houses_facts = skrub.var("facts")  →  line 25, cols 20-29"""
        nodes = _nodes_with_label(self.nodes, "<Var 'facts'>")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 25, f"Expected line 25, got {sr.start_line}"
        assert sr.start_column == 20, f"Expected start_col 20, got {sr.start_column}"
        assert sr.end_column == 29, f"Expected end_col 29, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "skrub.var"

    def test_cities_var_line_and_column(self):
        """houses_cities = skrub.var("cities")  →  line 26, cols 21-30"""
        nodes = _nodes_with_label(self.nodes, "<Var 'cities'>")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 26, f"Expected line 26, got {sr.start_line}"
        assert sr.start_column == 21, f"Expected start_col 21, got {sr.start_column}"
        assert sr.end_column == 30, f"Expected end_col 30, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "skrub.var"

    def test_images_var_line_and_column(self):
        """house_images = skrub.var("images")  →  line 27, cols 20-29"""
        nodes = _nodes_with_label(self.nodes, "<Var 'images'>")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 27, f"Expected line 27, got {sr.start_line}"
        assert sr.start_column == 20, f"Expected start_col 20, got {sr.start_column}"
        assert sr.end_column == 29, f"Expected end_col 29, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "skrub.var"

    def test_three_var_nodes_on_consecutive_lines(self):
        """facts/cities/images vars must be on lines 25, 26, 27."""
        lines = sorted(
            n.source_range.start_line
            for n in self.nodes
            if n.label in ("<Var 'facts'>", "<Var 'cities'>", "<Var 'images'>")
            and n.source_range
        )
        assert lines == [25, 26, 27], f"Expected [25,26,27], got {lines}"

    # --- merge (joins the three tables) -------------------------------------

    def test_merge_line_and_column(self):
        """houses_facts.merge(houses_cities, ...)  →  line 29, cols 27-32"""
        nodes = _nodes_containing(self.nodes, "merge")
        assert len(nodes) >= 1
        node = next(n for n in nodes if n.source_range and n.source_range.start_line == 29)
        sr = node.source_range
        assert sr.start_column == 27, f"Expected start_col 27, got {sr.start_column}"
        assert sr.end_column == 32, f"Expected end_col 32, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, node) == "merge"

    # --- as_y / as_X ---------------------------------------------------------

    def test_as_y_line_and_column(self):
        """price = sempipes.as_y(  →  line 31, cols 22-26"""
        nodes = _nodes_with_label(self.nodes, "as_y")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 31, f"Expected line 31, got {sr.start_line}"
        assert sr.start_column == 22, f"Expected start_col 22, got {sr.start_column}"
        assert sr.end_column == 26, f"Expected end_col 26, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "as_y"

    def test_as_x_line_and_column(self):
        """house_data = sempipes.as_X(  →  line 36, cols 27-31"""
        nodes = _nodes_with_label(self.nodes, "as_X")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 36, f"Expected line 36, got {sr.start_line}"
        assert sr.start_column == 27, f"Expected start_col 27, got {sr.start_column}"
        assert sr.end_column == 31, f"Expected end_col 31, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "as_X"

    def test_drop_inside_as_x_line_and_column(self):
        """houses.drop(columns=["price"]) inside as_X(...)  →  line 37, cols 16-20"""
        drop_nodes = _nodes_with_label(self.nodes, "drop")
        node = next(n for n in drop_nodes if n.source_range and n.source_range.start_line == 37)
        sr = node.source_range
        assert sr.start_column == 16, f"Expected start_col 16, got {sr.start_column}"
        assert sr.end_column == 20, f"Expected end_col 20, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, node) == "drop"

    # --- semantic operators --------------------------------------------------

    def test_sem_clean_line_and_column(self):
        """house_data.sem_clean(  →  line 42, cols 29-38"""
        nodes = _nodes_with_label(self.nodes, "sem_clean")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 42, f"Expected line 42, got {sr.start_line}"
        assert sr.start_column == 29, f"Expected start_col 29, got {sr.start_column}"
        assert sr.end_column == 38, f"Expected end_col 38, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "sem_clean"

    def test_sem_extract_features_line_and_column(self):
        """house_data.sem_extract_features(  →  line 55, cols 29-49"""
        nodes = _nodes_with_label(self.nodes, "sem_extract_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 55, f"Expected line 55, got {sr.start_line}"
        assert sr.start_column == 29, f"Expected start_col 29, got {sr.start_column}"
        assert sr.end_column == 49, f"Expected end_col 49, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "sem_extract_features"

    def test_sem_gen_features_line_and_column(self):
        """house_data.sem_gen_features(  →  line 63, cols 29-45"""
        nodes = _nodes_with_label(self.nodes, "sem_gen_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 63, f"Expected line 63, got {sr.start_line}"
        assert sr.start_column == 29, f"Expected start_col 29, got {sr.start_column}"
        assert sr.end_column == 45, f"Expected end_col 45, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, nodes[0]) == "sem_gen_features"

    # --- skb.apply nodes -----------------------------------------------------

    def test_skb_apply_vectorizer_line_and_column(self):
        """house_data.skb.apply(vectorizer, ...)  →  line 71, cols 36-45"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 71)
        sr = node.source_range
        assert sr.start_column == 36, f"Expected start_col 36, got {sr.start_column}"
        assert sr.end_column == 45, f"Expected end_col 45, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, node) == "skb.apply"

    def test_skb_apply_tabpfn_line_and_column(self):
        """vectorized_houses.skb.apply(tabpfn, ...)  →  line 82, cols 37-46"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 82)
        sr = node.source_range
        assert sr.start_column == 37, f"Expected start_col 37, got {sr.start_column}"
        assert sr.end_column == 46, f"Expected end_col 46, got {sr.end_column}"
        assert _highlighted(HOUSE_PRICES_SCRIPT, node) == "skb.apply"

    def test_two_skb_apply_nodes_on_different_lines(self):
        """The two skb.apply calls must be on lines 71 and 82."""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        assert len(apply_nodes) == 2, f"Expected 2 skb.apply nodes, got {len(apply_nodes)}"
        lines = sorted(n.source_range.start_line for n in apply_nodes if n.source_range)
        assert lines == [71, 82], f"Expected lines [71, 82], got {lines}"

    def test_skb_apply_func_line_and_column(self):
        """predictions.skb.apply_func(analyze_house_prices) is a dead-end side-effect — pruned."""
        func_nodes = _nodes_with_label(self.nodes, "skb.apply_func")
        assert len(func_nodes) == 0, (
            f"Expected 0 skb.apply_func nodes (pruned dead end), got {len(func_nodes)}"
        )

    # --- document order sanity -----------------------------------------------

    def test_pipeline_nodes_in_document_order(self):
        """All major nodes must appear in strict document order."""
        ordered = [
            ("<Var 'facts'>", 25),
            ("<Var 'cities'>", 26),
            ("<Var 'images'>", 27),
            ("as_y", 31),
            ("as_X", 36),
            ("sem_clean", 42),
            ("sem_extract_features", 55),
            ("sem_gen_features", 63),
        ]
        for label, expected_line in ordered:
            nodes = _nodes_with_label(self.nodes, label)
            assert len(nodes) >= 1, f"Node {label!r} not found"
            actual = nodes[0].source_range.start_line
            assert actual == expected_line, (
                f"Node {label!r}: expected line {expected_line}, got {actual}"
            )

    def test_all_source_ranges_within_script(self):
        max_line = len(HOUSE_PRICES_SCRIPT.splitlines())
        for node in self.nodes:
            if node.source_range:
                sr = node.source_range
                assert 1 <= sr.start_line <= max_line
                assert 1 <= sr.end_line <= max_line


# ===========================================================================
# museums.py tests
# ===========================================================================

class TestMuseumsScriptSourceRanges:
    """Exact source-range assertions for the museums pipeline script.

    The pipeline lives inside `def sempipes_pipeline():` at line 189.
    Lines 1-188 are helper class definitions and utility functions.
    """

    def setup_method(self):
        self.nodes, _ = extract_nodes_with_ranges(MUSEUMS_SCRIPT)

    def test_compiles_to_non_empty_graph(self):
        assert len(self.nodes) > 0, "museums script should produce nodes"

    def test_exact_node_count(self):
        """Parser must return exactly 12 nodes for the museums script.

        The 12 nodes are: artworks var, 2x skb.apply_func (lines 191 & 225),
        as_y, as_X, drop (inline in as_X), sem_extract_features,
        sem_gen_features, sem_refine, drop (inner), 2x skb.apply.
        The data-prep drop at line 248 (museum_objects.drop(...)) is outside
        sempipes_pipeline() and must NOT appear in the graph (see
        test_drop_data_prep_outside_pipeline_excluded).
        """
        assert len(self.nodes) == 12, (
            f"Expected 12 nodes, got {len(self.nodes)}: "
            f"{[n.label for n in self.nodes]}"
        )

    # --- var node ------------------------------------------------------------

    def test_artworks_var_line_and_column(self):
        """artworks = skrub.var("artworks")  →  line 190, cols 16-25"""
        nodes = _nodes_with_label(self.nodes, "<Var 'artworks'>")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 190, f"Expected line 190, got {sr.start_line}"
        assert sr.start_column == 16, f"Expected start_col 16, got {sr.start_column}"
        assert sr.end_column == 25, f"Expected end_col 25, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "skrub.var"

    # --- skb.apply_func nodes ------------------------------------------------

    def test_skb_apply_func_first_line_and_column(self):
        """artworks = artworks.skb.apply_func(apply_spacy_features)  →  line 191, cols 25-39"""
        func_nodes = _nodes_with_label(self.nodes, "skb.apply_func")
        node = next(
            (n for n in func_nodes if n.source_range and n.source_range.start_line == 191),
            None,
        )
        assert node is not None, "Expected skb.apply_func node at line 191"
        sr = node.source_range
        assert sr.start_column == 25, f"Expected start_col 25, got {sr.start_column}"
        assert sr.end_column == 39, f"Expected end_col 39, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "skb.apply_func"

    def test_skb_apply_func_second_line_and_column(self):
        """artwork_data = artwork_data.skb.apply_func(fill_missing_values)  →  line 225, cols 33-47"""
        func_nodes = _nodes_with_label(self.nodes, "skb.apply_func")
        node = next(
            (n for n in func_nodes if n.source_range and n.source_range.start_line == 225),
            None,
        )
        assert node is not None, "Expected skb.apply_func node at line 225"
        sr = node.source_range
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 47, f"Expected end_col 47, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "skb.apply_func"

    def test_two_skb_apply_func_nodes_on_lines_191_and_225(self):
        """The two skb.apply_func calls must be on lines 191 and 225."""
        func_nodes = _nodes_with_label(self.nodes, "skb.apply_func")
        assert len(func_nodes) == 2, f"Expected 2 skb.apply_func nodes, got {len(func_nodes)}"
        lines = sorted(n.source_range.start_line for n in func_nodes if n.source_range)
        assert lines == [191, 225], f"Expected lines [191, 225], got {lines}"

    # --- as_y / as_X ---------------------------------------------------------

    def test_as_y_line_and_column(self):
        """culture_target = sempipes.as_y(  →  line 193, cols 31-35"""
        nodes = _nodes_with_label(self.nodes, "as_y")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 193, f"Expected line 193, got {sr.start_line}"
        assert sr.start_column == 31, f"Expected start_col 31, got {sr.start_column}"
        assert sr.end_column == 35, f"Expected end_col 35, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "as_y"

    def test_as_x_line_and_column(self):
        """artwork_data = sempipes.as_X(  →  line 198, cols 29-33"""
        nodes = _nodes_with_label(self.nodes, "as_X")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 198, f"Expected line 198, got {sr.start_line}"
        assert sr.start_column == 29, f"Expected start_col 29, got {sr.start_column}"
        assert sr.end_column == 33, f"Expected end_col 33, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "as_X"

    def test_drop_inside_as_x_line_and_column(self):
        """artworks.drop(columns=["culture"]) inside as_X(...)  →  line 199, cols 18-22"""
        drop_nodes = _nodes_with_label(self.nodes, "drop")
        node = next(n for n in drop_nodes if n.source_range and n.source_range.start_line == 199)
        sr = node.source_range
        assert sr.start_column == 18, f"Expected start_col 18, got {sr.start_column}"
        assert sr.end_column == 22, f"Expected end_col 22, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "drop"

    # --- semantic operators --------------------------------------------------

    def test_sem_extract_features_line_and_column(self):
        """artwork_data.sem_extract_features(  →  line 203, cols 33-53"""
        nodes = _nodes_with_label(self.nodes, "sem_extract_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 203, f"Expected line 203, got {sr.start_line}"
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 53, f"Expected end_col 53, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "sem_extract_features"

    def test_sem_gen_features_line_and_column(self):
        """artwork_data.sem_gen_features(  →  line 218, cols 33-49"""
        nodes = _nodes_with_label(self.nodes, "sem_gen_features")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 218, f"Expected line 218, got {sr.start_line}"
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 49, f"Expected end_col 49, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "sem_gen_features"

    def test_sem_refine_line_and_column(self):
        """artwork_data.sem_refine(  →  line 227, cols 33-43"""
        nodes = _nodes_with_label(self.nodes, "sem_refine")
        assert len(nodes) == 1
        sr = nodes[0].source_range
        assert sr is not None
        assert sr.start_line == 227, f"Expected line 227, got {sr.start_line}"
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 43, f"Expected end_col 43, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, nodes[0]) == "sem_refine"

    def test_sem_extract_before_sem_gen_before_sem_refine(self):
        """sem_extract_features < sem_gen_features < sem_refine in document order."""
        ext = _nodes_with_label(self.nodes, "sem_extract_features")[0].source_range.start_line
        gen = _nodes_with_label(self.nodes, "sem_gen_features")[0].source_range.start_line
        ref = _nodes_with_label(self.nodes, "sem_refine")[0].source_range.start_line
        assert ext < gen < ref, f"Expected {ext} < {gen} < {ref}"

    # --- drop nodes inside the pipeline function -----------------------------

    def test_drop_pipeline_inner_line_and_column(self):
        """artwork_data.drop(columns=["object_name_raw", ...])  →  line 233, cols 33-37"""
        drop_nodes = _nodes_with_label(self.nodes, "drop")
        node = next(n for n in drop_nodes if n.source_range and n.source_range.start_line == 233)
        sr = node.source_range
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 37, f"Expected end_col 37, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "drop"

    # --- skb.apply nodes -----------------------------------------------------

    def test_skb_apply_vectorizer_line_and_column(self):
        """artwork_data.skb.apply(skrub.TableVectorizer())  →  line 235, cols 33-42"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 235)
        sr = node.source_range
        assert sr.start_column == 33, f"Expected start_col 33, got {sr.start_column}"
        assert sr.end_column == 42, f"Expected end_col 42, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "skb.apply"

    def test_skb_apply_ft_transformer_line_and_column(self):
        """pred = artwork_data.skb.apply(ft_transformer, ...)  →  line 238, cols 25-34"""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        node = next(n for n in apply_nodes if n.source_range and n.source_range.start_line == 238)
        sr = node.source_range
        assert sr.start_column == 25, f"Expected start_col 25, got {sr.start_column}"
        assert sr.end_column == 34, f"Expected end_col 34, got {sr.end_column}"
        assert _highlighted(MUSEUMS_SCRIPT, node) == "skb.apply"

    def test_two_pipeline_skb_apply_nodes_on_different_lines(self):
        """The two pipeline skb.apply calls must be on lines 235 and 238."""
        apply_nodes = _nodes_with_label(self.nodes, "skb.apply")
        pipeline_apply = [
            n for n in apply_nodes
            if n.source_range and n.source_range.start_line in (235, 238)
        ]
        assert len(pipeline_apply) == 2, (
            f"Expected 2 pipeline skb.apply nodes (lines 235 and 238), "
            f"got {[n.source_range.start_line for n in pipeline_apply]}"
        )

    # --- data-prep drop (outside pipeline function) --------------------------

    def test_drop_data_prep_outside_pipeline_excluded(self):
        """museum_objects.drop(...) at line 248 must NOT appear in the graph.

        That .drop() is data-preparation code outside sempipes_pipeline().
        The scope-aware parser must exclude it so the graph has no isolated nodes
        and forms a single connected component.
        """
        drop_nodes = _nodes_with_label(self.nodes, "drop")
        node = next(
            (n for n in drop_nodes if n.source_range and n.source_range.start_line == 248),
            None,
        )
        assert node is None, (
            "Out-of-scope drop at line 248 must not appear in graph; "
            f"got node: {node}"
        )

    # --- document order sanity -----------------------------------------------

    def test_pipeline_nodes_in_document_order(self):
        """All major pipeline nodes must appear in strict document order."""
        ordered = [
            ("<Var 'artworks'>", 190),
            ("as_y", 193),
            ("as_X", 198),
            ("sem_extract_features", 203),
            ("sem_gen_features", 218),
            ("sem_refine", 227),
        ]
        for label, expected_line in ordered:
            nodes = _nodes_with_label(self.nodes, label)
            assert len(nodes) >= 1, f"Node {label!r} not found"
            actual = nodes[0].source_range.start_line
            assert actual == expected_line, (
                f"Node {label!r}: expected line {expected_line}, got {actual}"
            )

    def test_all_source_ranges_within_script(self):
        max_line = len(MUSEUMS_SCRIPT.splitlines())
        for node in self.nodes:
            if node.source_range:
                sr = node.source_range
                assert 1 <= sr.start_line <= max_line
                assert 1 <= sr.end_line <= max_line


# ===========================================================================
# Rule invariant tests — verified across all three embedded scripts
# ===========================================================================
#
# Rules for source range matching (enforced by compile_parse.py):
#   Rule 1: No leading dot   — highlighted text never starts with "."
#   Rule 2: No trailing "("  — highlighted text never ends with "("
#   Rule 3: (subscripts)     — closing "]" is included when applicable
#
# These tests verify the invariants hold for every node in every script.
# They are intentionally script-agnostic so they catch any new operator
# that might be added later.

_ALL_SCRIPTS = [
    ("FRAUD_SCRIPT", FRAUD_SCRIPT),
    ("HOUSE_PRICES_SCRIPT", HOUSE_PRICES_SCRIPT),
    ("MUSEUMS_SCRIPT", MUSEUMS_SCRIPT),
]


class TestSourceRangeRuleInvariants:
    """Verify the three source-range matching rules hold for every node in every script."""

    def _all_highlights(self, script_name, script):
        """Return (node_label, highlighted_text) for every node that has a source range."""
        nodes, _ = extract_nodes_with_ranges(script)
        result = []
        for node in nodes:
            if node.source_range is None:
                continue
            sr = node.source_range
            lines = script.splitlines()
            if 1 <= sr.start_line <= len(lines):
                line = lines[sr.start_line - 1]
                text = line[sr.start_column - 1: sr.end_column - 1]
                result.append((node.label, text))
        return result

    def test_rule1_no_leading_dot(self):
        """Rule 1: highlighted text must never start with '.'."""
        violations = []
        for script_name, script in _ALL_SCRIPTS:
            for label, text in self._all_highlights(script_name, script):
                if text.startswith("."):
                    violations.append(f"{script_name} / {label!r}: highlighted {text!r} starts with '.'")
        assert not violations, "Rule 1 violated:\n" + "\n".join(violations)

    def test_rule2_no_trailing_open_paren(self):
        """Rule 2: highlighted text must never end with '('."""
        violations = []
        for script_name, script in _ALL_SCRIPTS:
            for label, text in self._all_highlights(script_name, script):
                if text.endswith("("):
                    violations.append(f"{script_name} / {label!r}: highlighted {text!r} ends with '('")
        assert not violations, "Rule 2 violated:\n" + "\n".join(violations)

    def test_highlighted_text_is_non_empty(self):
        """Every node with a source range must produce a non-empty highlighted span."""
        violations = []
        for script_name, script in _ALL_SCRIPTS:
            for label, text in self._all_highlights(script_name, script):
                if not text:
                    violations.append(f"{script_name} / {label!r}: highlighted text is empty")
        assert not violations, "Empty highlights:\n" + "\n".join(violations)

    def test_highlighted_text_matches_node_label_keyword(self):
        """Highlighted text should contain the key identifier from the node label.

        For method-call nodes (sem_*, skb.apply*, merge, drop, etc.) the highlighted
        text should be exactly the method name (no dot, no paren). For var nodes the
        text should be 'skrub.var'. For as_X / as_y nodes the text should be the
        function name itself.
        """
        # Map from label → expected highlighted text
        exact_cases = [
            ("sem_fillna",           "sem_fillna"),
            ("sem_gen_features",     "sem_gen_features"),
            ("sem_extract_features", "sem_extract_features"),
            ("sem_agg_features",     "sem_agg_features"),
            ("sem_clean",            "sem_clean"),
            ("sem_refine",           "sem_refine"),
            ("skb.apply",            "skb.apply"),
            ("skb.apply_func",       "skb.apply_func"),
            ("merge",                "merge"),
            ("drop",                 "drop"),
            ("as_X",                 "as_X"),
            ("as_y",                 "as_y"),
        ]
        failures = []
        for script_name, script in _ALL_SCRIPTS:
            nodes, _ = extract_nodes_with_ranges(script)
            node_map = {n.label: n for n in nodes if n.source_range}
            for label, expected_text in exact_cases:
                if label not in node_map:
                    continue
                actual = _highlighted(script, node_map[label])
                if actual != expected_text:
                    failures.append(
                        f"{script_name} / {label!r}: expected {expected_text!r}, got {actual!r}"
                    )
        assert not failures, "Label↔highlight mismatches:\n" + "\n".join(failures)

    def test_var_nodes_highlighted_as_skrub_var(self):
        """All <Var ...> nodes must highlight 'skrub.var' (not 'skrub.var(')."""
        failures = []
        for script_name, script in _ALL_SCRIPTS:
            for label, text in self._all_highlights(script_name, script):
                if label.startswith("<Var "):
                    if text != "skrub.var":
                        failures.append(
                            f"{script_name} / {label!r}: expected 'skrub.var', got {text!r}"
                        )
        assert not failures, "Var node highlight mismatches:\n" + "\n".join(failures)
