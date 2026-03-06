"""Graph compilation tests for house_prices- and museums-style pipelines.

Scripts are embedded in full so tests do not depend on pipeline_scripts/.
Tests use smaller parts of the pipelines and permutations (variable names,
quotes, formatting) to ensure the parser is flexible.
"""

import pytest
from services.compile_parse import extract_nodes_with_ranges
from services.graph_api import compile_script_to_graph


def _labels(nodes):
    return {n.label for n in nodes}


def _node_count_by_label(nodes, label):
    return sum(1 for n in nodes if n.label == label)


def _connected_component_count(nodes, edges):
    """Number of connected components (undirected)."""
    id_to_idx = {n.id: i for i, n in enumerate(nodes)}
    n_nodes = len(nodes)
    parent = list(range(n_nodes))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for e in edges:
        if e.source in id_to_idx and e.target in id_to_idx:
            union(id_to_idx[e.source], id_to_idx[e.target])

    return sum(1 for i in range(n_nodes) if find(i) == i)


# ---------------------------------------------------------------------------
# House prices – full pipeline body (embedded copy, no dependency on disk)
# ---------------------------------------------------------------------------

HOUSE_PRICES_PIPELINE_BODY = '''
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

    house_data = house_data.sem_clean(
        nl_prompt="Clean the numeric housing data.",
        columns=["sqft"]
    )

    house_data = house_data.assign(
        sqft_log=house_data["sqft"].apply(lambda x: 1.0),
    )

    house_data = house_data.sem_extract_features(
        nl_prompt="Extract features.",
        name="extract_visuals",
        input_columns=["image_path"],
        generate_via_code=True
    )

    house_data = house_data.sem_gen_features(
        nl_prompt="Generate features.",
        name="generated_features",
        how_many=5,
    )

    vectorizer = skrub.TableVectorizer()
    vectorized_houses = house_data.skb.apply(
        vectorizer,
        exclude_cols=["image_id", "image_path"]
    )

    tabpfn = TabPFNRegressor.create_default_for_version(ModelVersion.V2)
    predictions = vectorized_houses.skb.apply(tabpfn, y=price)

    def analyze_house_prices(preds, houses):
        return
    predictions.skb.apply_func(analyze_house_prices, houses=houses)

    return predictions
'''


# ---------------------------------------------------------------------------
# House prices – smaller snippets (embedded)
# ---------------------------------------------------------------------------

# Snippet: three vars + merge + as_y + as_X (and drop inside as_X)
HOUSE_PRICES_VARS_AS_X_AS_Y = '''
def sempipes_pipeline():
    houses_facts = skrub.var("facts")
    houses_cities = skrub.var("cities")
    house_images = skrub.var("images")
    houses = houses_facts.merge(houses_cities, on="city_id").merge(house_images, on="image_id")
    price = sempipes.as_y(houses["price"], "Price in USD")
    house_data = sempipes.as_X(houses.drop(columns=["price"]), "House data.")
    return house_data
'''


# Same pattern, different variable names
HOUSE_PRICES_VARS_AS_X_AS_Y_ALT_NAMES = '''
def sempipes_pipeline():
    f = skrub.var("facts")
    c = skrub.var("cities")
    im = skrub.var("images")
    merged = f.merge(c, on="city_id").merge(im, on="image_id")
    y = sempipes.as_y(merged["price"], "Target")
    x = sempipes.as_X(merged.drop(columns=["price"]), "Features")
    return x
'''


# Snippet: as_X, sem_clean, sem_extract_features, sem_gen_features
HOUSE_PRICES_SEM_OPS = '''
def sempipes_pipeline():
    houses_facts = skrub.var("facts")
    house_data = sempipes.as_X(houses_facts.drop(columns=["price"]), "Data.")
    house_data = house_data.sem_clean(nl_prompt="Clean.", columns=["sqft"])
    house_data = house_data.sem_extract_features(
        nl_prompt="Extract.", name="extract_visuals", input_columns=["img"], generate_via_code=True
    )
    house_data = house_data.sem_gen_features(nl_prompt="Gen.", name="gen", how_many=5)
    return house_data
'''


# Snippet: skb.apply (two calls)
HOUSE_PRICES_SKB_APPLY = '''
def sempipes_pipeline():
    x = skrub.var("facts")
    x = sempipes.as_X(x, "X")
    x = x.sem_gen_features(nl_prompt="Gen.", how_many=2)
    vec = skrub.TableVectorizer()
    x = x.skb.apply(vec, exclude_cols=["id"])
    model = SomeModel()
    out = x.skb.apply(model, y=price)
    return out
'''


# ---------------------------------------------------------------------------
# Museums – full pipeline body (embedded copy)
# ---------------------------------------------------------------------------

MUSEUMS_PIPELINE_BODY = '''
def sempipes_pipeline():
    artworks = skrub.var("artworks")
    artworks = artworks.skb.apply_func(apply_spacy_features)

    culture_target = sempipes.as_y(
        artworks["culture"],
        "The cultural or geographic origin of the artwork.",
    )

    artwork_data = sempipes.as_X(
        artworks.drop(columns=["culture"]),
        "Artwork metadata.",
    )

    artwork_data = artwork_data.sem_extract_features(
        nl_prompt="Convert date strings.",
        name="extract_dates",
        input_columns=["date"],
        output_columns={"year_start": "Start year"},
        generate_via_code=True,
    )

    artwork_data = artwork_data.sem_gen_features(
        nl_prompt="Create additional features.",
        name="generate_additional_features",
    )

    artwork_data = artwork_data.skb.apply_func(fill_missing_values)

    artwork_data = artwork_data.sem_refine(
        nl_prompt="Standardize object_name.",
        target_column="object_name",
        refine_with_existing_values_only=False,
    )

    artwork_data = artwork_data.drop(columns=["object_name_raw", "object_ID"], errors="ignore")

    artwork_data = artwork_data.skb.apply(skrub.TableVectorizer())

    ft_transformer = FTTransformerClassifier()
    pred = artwork_data.skb.apply(ft_transformer, y=culture_target)

    return pred
'''


# ---------------------------------------------------------------------------
# Museums – smaller snippets
# ---------------------------------------------------------------------------

# var + skb.apply_func + as_y + as_X + drop
MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y = '''
def sempipes_pipeline():
    artworks = skrub.var("artworks")
    artworks = artworks.skb.apply_func(apply_spacy_features)
    culture_target = sempipes.as_y(artworks["culture"], "Target.")
    artwork_data = sempipes.as_X(artworks.drop(columns=["culture"]), "Features.")
    return artwork_data
'''


# Same with different variable names
MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y_ALT = '''
def sempipes_pipeline():
    items = skrub.var('artworks')
    items = items.skb.apply_func(apply_spacy_features)
    y = sempipes.as_y(items["culture"], "Target.")
    x = sempipes.as_X(items.drop(columns=["culture"]), "Features.")
    return x
'''


# sem_extract_features + sem_gen_features + skb.apply_func + sem_refine
MUSEUMS_SEM_OPS = '''
def sempipes_pipeline():
    data = skrub.var("artworks")
    data = sempipes.as_X(data, "X")
    data = data.sem_extract_features(
        nl_prompt="Dates.", name="extract_dates", input_columns=["date"], generate_via_code=True
    )
    data = data.sem_gen_features(nl_prompt="Gen.")
    data = data.skb.apply_func(fill_missing_values)
    data = data.sem_refine(nl_prompt="Refine.", target_column="object_name")
    data = data.drop(columns=["object_name_raw"], errors="ignore")
    data = data.skb.apply(skrub.TableVectorizer())
    out = data.skb.apply(FTTransformerClassifier(), y=target)
    return out
'''


# ---------------------------------------------------------------------------
# House prices – graph construction tests
# ---------------------------------------------------------------------------

class TestHousePricesCompile:
    """Graph compilation for house_prices-style pipelines (embedded scripts)."""

    def test_full_house_prices_body_compiles_with_expected_nodes(self):
        """Full house_prices pipeline body produces expected node types."""
        result = compile_script_to_graph(HOUSE_PRICES_PIPELINE_BODY)
        assert result.is_valid, result.validation_errors
        labels = _labels(result.nodes)
        assert "<Var 'facts'>" in labels
        assert "<Var 'cities'>" in labels
        assert "<Var 'images'>" in labels
        assert "merge" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert "sem_clean" in labels
        assert "sem_extract_features" in labels
        assert "sem_gen_features" in labels
        assert "skb.apply" in labels
        assert len([n for n in result.nodes if n.label == "skb.apply"]) >= 2

    def test_house_prices_vars_as_x_as_y_snippet(self):
        """Minimal snippet: 3 vars, merge, as_y, as_X, drop → all node types detected (prune=False)."""
        # Use prune=False so as_y is still present (it's a dead branch when return is only house_data)
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_VARS_AS_X_AS_Y, prune=False)
        labels = _labels(nodes)
        assert "<Var 'facts'>" in labels
        assert "<Var 'cities'>" in labels
        assert "<Var 'images'>" in labels
        assert "merge" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert len(nodes) >= 7
        assert len(edges) >= 6
        # With default prune=True, graph is still one connected component
        nodes_pruned, edges_pruned = extract_nodes_with_ranges(HOUSE_PRICES_VARS_AS_X_AS_Y)
        assert _connected_component_count(nodes_pruned, edges_pruned) == 1

    def test_house_prices_vars_as_x_as_y_alt_variable_names(self):
        """Same pipeline with different variable names (f, c, im, merged, y, x) still parses."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_VARS_AS_X_AS_Y_ALT_NAMES, prune=False)
        labels = _labels(nodes)
        assert "<Var 'facts'>" in labels
        assert "<Var 'cities'>" in labels
        assert "<Var 'images'>" in labels
        assert "merge" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert len(nodes) >= 7
        nodes_pruned, edges_pruned = extract_nodes_with_ranges(HOUSE_PRICES_VARS_AS_X_AS_Y_ALT_NAMES)
        assert _connected_component_count(nodes_pruned, edges_pruned) == 1

    def test_house_prices_sem_ops_snippet(self):
        """Snippet with sem_clean, sem_extract_features, sem_gen_features; as_X detected with prune=False."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_SEM_OPS, prune=False)
        labels = _labels(nodes)
        assert "sem_clean" in labels
        assert "sem_extract_features" in labels
        assert "sem_gen_features" in labels
        assert "<Var 'facts'>" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert len(nodes) >= 6  # var, drop, as_X, sem_clean, sem_extract_features, sem_gen_features
        nodes_pruned, edges_pruned = extract_nodes_with_ranges(HOUSE_PRICES_SEM_OPS)
        assert _connected_component_count(nodes_pruned, edges_pruned) == 1

    def test_house_prices_skb_apply_snippet(self):
        """Snippet with two skb.apply calls produces two skb.apply nodes."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_SKB_APPLY)
        apply_count = _node_count_by_label(nodes, "skb.apply")
        assert apply_count >= 2
        assert "sem_gen_features" in _labels(nodes)
        assert "as_X" in _labels(nodes)
        assert _connected_component_count(nodes, edges) == 1

    def test_house_prices_full_body_no_isolated_nodes(self):
        """Full house_prices body: no isolated nodes (every node in some edge)."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY)
        assert len(nodes) > 0
        node_ids = {n.id for n in nodes}
        involved = set()
        for e in edges:
            involved.add(e.source)
            involved.add(e.target)
        isolated = node_ids - involved
        assert isolated == set(), f"Isolated node ids: {isolated}"

    def test_house_prices_full_body_single_component(self):
        """Full house_prices body: graph is one connected component."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY)
        assert _connected_component_count(nodes, edges) == 1


# ---------------------------------------------------------------------------
# Museums – graph construction tests
# ---------------------------------------------------------------------------

class TestMuseumsCompile:
    """Graph compilation for museums-style pipelines (embedded scripts)."""

    def test_full_museums_body_compiles_with_expected_nodes(self):
        """Full museums pipeline body produces expected node types."""
        result = compile_script_to_graph(MUSEUMS_PIPELINE_BODY)
        assert result.is_valid, result.validation_errors
        labels = _labels(result.nodes)
        assert "<Var 'artworks'>" in labels
        assert "skb.apply_func" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert "sem_extract_features" in labels
        assert "sem_gen_features" in labels
        assert "sem_refine" in labels
        assert "skb.apply" in labels
        assert _node_count_by_label(result.nodes, "skb.apply_func") >= 2
        assert _node_count_by_label(result.nodes, "skb.apply") >= 2

    def test_museums_var_apply_func_as_x_as_y_snippet(self):
        """Minimal snippet: var, skb.apply_func, as_y, as_X, drop (prune=False to see as_y/as_X)."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y, prune=False)
        labels = _labels(nodes)
        assert "<Var 'artworks'>" in labels
        assert "skb.apply_func" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert len(nodes) >= 5
        nodes_pruned, edges_pruned = extract_nodes_with_ranges(MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y)
        assert _connected_component_count(nodes_pruned, edges_pruned) == 1

    def test_museums_var_apply_func_alt_names_and_single_quotes(self):
        """Same pipeline with items/x/y and single-quoted var name."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y_ALT, prune=False)
        labels = _labels(nodes)
        assert "<Var 'artworks'>" in labels
        assert "skb.apply_func" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels
        assert len(nodes) >= 5
        nodes_pruned, edges_pruned = extract_nodes_with_ranges(MUSEUMS_VAR_APPLY_FUNC_AS_X_AS_Y_ALT)
        assert _connected_component_count(nodes_pruned, edges_pruned) == 1

    def test_museums_sem_ops_snippet(self):
        """Snippet with sem_extract_features, sem_gen_features, sem_refine, skb.apply_func, skb.apply."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_SEM_OPS)
        labels = _labels(nodes)
        assert "sem_extract_features" in labels
        assert "sem_gen_features" in labels
        assert "sem_refine" in labels
        assert "skb.apply_func" in labels
        assert "skb.apply" in labels
        assert "drop" in labels
        assert len(nodes) >= 8
        assert _connected_component_count(nodes, edges) == 1

    def test_museums_full_body_no_isolated_nodes(self):
        """Full museums body: no isolated nodes."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY)
        assert len(nodes) > 0
        node_ids = {n.id for n in nodes}
        involved = set()
        for e in edges:
            involved.add(e.source)
            involved.add(e.target)
        isolated = node_ids - involved
        assert isolated == set(), f"Isolated node ids: {isolated}"

    def test_museums_full_body_single_component(self):
        """Full museums body: graph is one connected component."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY)
        assert _connected_component_count(nodes, edges) == 1


# ---------------------------------------------------------------------------
# Permutations and syntax flexibility
# ---------------------------------------------------------------------------

class TestHousePricesMuseumsPermutations:
    """Permutations (variable names, quotes, spacing) still produce valid graphs."""

    def test_as_x_as_y_double_quotes(self):
        """as_y and as_X are found; with prune=True only path to return is kept."""
        script = '''
def sempipes_pipeline():
    df = skrub.var("data")
    y = sempipes.as_y(df["target"], "Target column")
    x = sempipes.as_X(df.drop(columns=["target"]), "Features")
    return x
'''
        result = compile_script_to_graph(script)
        assert result.is_valid
        # With pruning, as_y may be removed (dead branch); verify at least var, drop, as_X path
        labels = _labels(result.nodes)
        assert "<Var 'data'>" in labels
        assert "drop" in labels
        # Unpruned: as_y and as_X both present
        nodes_all, _ = extract_nodes_with_ranges(script, prune=False)
        labels_all = _labels(nodes_all)
        assert labels_all >= {"<Var 'data'>", "as_y", "as_X", "drop"}
        assert _connected_component_count(result.nodes, result.edges) == 1

    def test_as_x_as_y_single_quotes(self):
        """Single-quoted var and column names still parse (prune=False to see as_y/as_X)."""
        script = '''
def sempipes_pipeline():
    df = skrub.var('data')
    y = sempipes.as_y(df['target'], 'Target')
    x = sempipes.as_X(df.drop(columns=['target']), 'Features')
    return x
'''
        result = compile_script_to_graph(script)
        assert result.is_valid
        nodes_all, _ = extract_nodes_with_ranges(script, prune=False)
        labels_all = _labels(nodes_all)
        assert "<Var 'data'>" in labels_all
        assert "as_y" in labels_all
        assert "as_X" in labels_all

    def test_sem_ops_multiline_prompt(self):
        script = '''
def sempipes_pipeline():
    a = skrub.var("x")
    a = sempipes.as_X(a, "X")
    a = a.sem_gen_features(
        nl_prompt="Generate features for the model.",
        name="gf",
        how_many=3,
    )
    return a
'''
        result = compile_script_to_graph(script)
        assert result.is_valid
        assert "sem_gen_features" in _labels(result.nodes)
        assert _connected_component_count(result.nodes, result.edges) == 1

    def test_merge_chained_same_line(self):
        script = '''
def sempipes_pipeline():
    a = skrub.var("a")
    b = skrub.var("b")
    c = skrub.var("c")
    m = a.merge(b, on="id").merge(c, on="id")
    out = sempipes.as_X(m, "X")
    return out
'''
        nodes, edges = extract_nodes_with_ranges(script)
        labels = _labels(nodes)
        assert "<Var 'a'>" in labels
        assert "<Var 'b'>" in labels
        assert "<Var 'c'>" in labels
        assert "merge" in labels
        assert "as_X" in labels
        assert _connected_component_count(nodes, edges) == 1

    def test_house_prices_skb_apply_func_detected_with_prune_false(self):
        """skb.apply_func is detected when using prune=False (dead-end in minimal snippet)."""
        script = '''
def sempipes_pipeline():
    x = skrub.var("data")
    x = sempipes.as_X(x, "X")
    x = x.skb.apply_func(some_analyzer)
    return x
'''
        nodes, _ = extract_nodes_with_ranges(script, prune=False)
        labels = _labels(nodes)
        assert "skb.apply_func" in labels
        assert "as_X" in labels
        assert "<Var 'data'>" in labels

    def test_museums_sem_refine_detected(self):
        """sem_refine node is detected in museums-style pipeline."""
        script = '''
def sempipes_pipeline():
    data = skrub.var("artworks")
    data = sempipes.as_X(data, "X")
    data = data.sem_refine(nl_prompt="Standardize.", target_column="name")
    return data
'''
        result = compile_script_to_graph(script)
        assert result.is_valid
        assert "sem_refine" in _labels(result.nodes)
        assert "as_X" in _labels(result.nodes)

    def test_syntax_permutation_extra_spaces(self):
        """Extra spaces around parentheses still parse."""
        script = '''
def sempipes_pipeline():
    df = skrub.var( "data" )
    y  = sempipes.as_y( df["t"], "T" )
    x  = sempipes.as_X( df.drop( columns=["t"] ), "X" )
    return x
'''
        nodes, _ = extract_nodes_with_ranges(script, prune=False)
        labels = _labels(nodes)
        assert "<Var 'data'>" in labels
        assert "as_y" in labels
        assert "as_X" in labels
        assert "drop" in labels

    def test_sem_extract_features_with_output_columns(self):
        """sem_extract_features with output_columns dict (museums-style) parses."""
        script = '''
def sempipes_pipeline():
    d = skrub.var("artworks")
    d = sempipes.as_X(d, "X")
    d = d.sem_extract_features(
        nl_prompt="Parse dates.",
        name="dates",
        input_columns=["date"],
        output_columns={"year_start": "Start", "year_end": "End"},
        generate_via_code=True,
    )
    return d
'''
        result = compile_script_to_graph(script)
        assert result.is_valid
        assert "sem_extract_features" in _labels(result.nodes)
        assert _connected_component_count(result.nodes, result.edges) == 1
