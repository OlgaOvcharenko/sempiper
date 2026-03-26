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

import sempipes
from sempipes.optimisers import optimise_colopro, EvolutionarySearch

warnings.filterwarnings("ignore")


class FeatureTokenizer(nn.Module):
    """Embeds each scalar feature into a d_token-dimensional vector."""

    def __init__(self, n_features: int, d_token: int) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.empty(n_features, d_token))
        self.bias = nn.Parameter(torch.zeros(n_features, d_token))
        nn.init.kaiming_uniform_(self.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, n_features) → (batch, n_features, d_token)
        return x.unsqueeze(-1) * self.weight.unsqueeze(0) + self.bias.unsqueeze(0)


class FTTransformerModel(nn.Module):
    """Feature Tokenizer + Transformer (Gorishniy et al. 2021).
    Each input feature is projected into a d_token-dimensional token.
    A learnable [CLS] token is prepended and the sequence is processed
    by a standard transformer encoder. The CLS output is used for classification.
    """

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
    """Sklearn-compatible wrapper around FTTransformerModel."""

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
    """Fill NaN values in all columns so sem_refine validation passes."""
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].fillna("")
    for col in df.select_dtypes(include="number").columns:
        df[col] = df[col].fillna(0)
    for col in df.select_dtypes(include="bool").columns:
        df[col] = df[col].fillna(False)
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
        nl_prompt="""
        Convert the date strings into precise integer intervals. Currently, the `date` column contains a mix of formats. Your task is to rework it into a structured format with the following columns:  `year_start`, `start_is_bce`, `year_end`, and `end_is_bce`. If any information is missing or cannot be parsed, leave the corresponding fields empty. Try to parse as much information as possible, even from vague descriptions. For example, "5th century BCE" should be parsed as `year_start` = 500, `start_is_bce` = True, `year_end` = 401, `end_is_bce` = True. If the date is a single year like "1500", it should be parsed as `year_start` = 1500, `start_is_bce` = False, and the end fields should be empty.
        """,
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
        nl_prompt="""
        Help me create additional features that could be useful for predicting the culture of an artwork. Remove any features that are not relevant or could introduce noise.
        """,
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

    ft_transformer = FTTransformerClassifier(n_epochs=5)
    pred = artwork_data.skb.apply(ft_transformer, y=culture_target)

    return pred

# Get data
data_path = "experiments/data/met_10k.csv"
n_samples = 100

museum_objects = pd.read_csv(data_path)
museum_objects = museum_objects.drop(columns=["department", "source_file", "image"], errors="ignore")
museum_objects["object_name_raw"] = museum_objects["object_name"]

museum_objects = museum_objects.sample(n=n_samples, random_state=42).copy()
train_museum_objects, test_museum_objects = train_test_split(museum_objects, test_size=0.25, random_state=42)

# Run pipeline
pipeline = sempipes_pipeline()

outcomes = optimise_colopro(
    dag_sink=pipeline,
    operator_name="generate_additional_features",
    num_trials=5,
    scoring="f1_weighted",
    cv=3,
    search=EvolutionarySearch(population_size=6),
    run_name="optimise_museums",
    additional_env_variables={
        "artworks": train_museum_objects
    },
    n_jobs_for_evaluation=1,
)

best_outcome = max(outcomes, key=lambda x: x.score)
print(f"\\\\nBest Score: {best_outcome.score:.4f}")
print(f"Best Trial: {best_outcome.search_node.trial}")
