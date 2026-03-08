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


# ---------------------------------------------------------------------------
# Helpers for precise edge and source-range tests
# ---------------------------------------------------------------------------

def _edges(nodes, edges):
    """Return {(source_id, target_id)} set for quick membership checks."""
    return {(e.source, e.target) for e in edges}


def _node(nodes, label):
    """Return first node with given label (raises if not found)."""
    for n in nodes:
        if n.label == label:
            return n
    raise AssertionError(f"No node with label {label!r}. Labels: {_labels(nodes)}")


def _nodes_with_label(nodes, label):
    return [n for n in nodes if n.label == label]


def _highlight(body: str, node) -> str:
    """Extract the source text that would be highlighted for this node."""
    lines = body.split("\n")
    line = lines[node.source_range.start_line - 1]
    sc = node.source_range.start_column - 1   # 0-indexed start
    ec = node.source_range.end_column - 1     # 0-indexed exclusive end
    return line[sc:ec]


# ---------------------------------------------------------------------------
# Inline-drop edge correctness (regression tests for the three-bug fix)
# ---------------------------------------------------------------------------

class TestInlineDropEdges:
    """
    Regression tests for inline `df.drop(...)` inside as_X / as_y.

    Three bugs were fixed:
    1. Redundant direct edge: producer → as_X when producer → drop → as_X already exists.
    2. Spurious drop → as_y edge triggered by a nearby as_X(df.drop(...)) in context.
    3. Inline drop stealing `produces` from as_X when both are on the same line.
    """

    # --- single-line as_X(df.drop(...)) next to as_y ---

    SINGLE_LINE_SNIPPET = '''
def sempipes_pipeline():
    facts = skrub.var("facts")
    cities = skrub.var("cities")
    m = facts.merge(cities, on="id")
    y = sempipes.as_y(m["price"], "Target")
    x = sempipes.as_X(m.drop(columns=["price"]), "Features")
    return x
'''

    def test_single_line_no_redundant_merge_to_as_x(self):
        """merge → as_X must NOT exist when as_X(df.drop(...)) is on one line."""
        nodes, edges = extract_nodes_with_ranges(self.SINGLE_LINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        merge_id = _node(nodes, "merge").id
        as_x_id = _node(nodes, "as_X").id
        assert (merge_id, as_x_id) not in ep, "Redundant merge→as_X edge present"

    def test_single_line_merge_to_drop_to_as_x_chain(self):
        """Correct chain: merge → drop → as_X (both edges must exist)."""
        nodes, edges = extract_nodes_with_ranges(self.SINGLE_LINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        merge_id = _node(nodes, "merge").id
        drop_id = _node(nodes, "drop").id
        as_x_id = _node(nodes, "as_X").id
        assert (merge_id, drop_id) in ep, "merge→drop edge missing"
        assert (drop_id, as_x_id) in ep, "drop→as_X edge missing"

    def test_single_line_no_spurious_drop_to_as_y(self):
        """drop must NOT get a spurious edge to as_y (as_y uses subscript, not drop)."""
        nodes, edges = extract_nodes_with_ranges(self.SINGLE_LINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        drop_id = _node(nodes, "drop").id
        as_y_id = _node(nodes, "as_y").id
        assert (drop_id, as_y_id) not in ep, "Spurious drop→as_y edge present"

    def test_single_line_merge_feeds_as_y_directly(self):
        """as_y(m[...]) directly consumes merge output (subscript, not chained method)."""
        nodes, edges = extract_nodes_with_ranges(self.SINGLE_LINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        merge_id = _node(nodes, "merge").id
        as_y_id = _node(nodes, "as_y").id
        assert (merge_id, as_y_id) in ep, "merge→as_y edge missing"

    # --- multiline as_X with inline drop on next line ---

    MULTILINE_SNIPPET = '''
def sempipes_pipeline():
    facts = skrub.var("facts")
    cities = skrub.var("cities")
    m = facts.merge(cities, on="id")
    y = sempipes.as_y(m["price"], "Target")
    x = sempipes.as_X(
        m.drop(columns=["price"]),
        "Features",
    )
    return x
'''

    def test_multiline_no_redundant_merge_to_as_x(self):
        """Multi-line as_X(\\n    df.drop(...)): merge → as_X must NOT exist."""
        nodes, edges = extract_nodes_with_ranges(self.MULTILINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        merge_id = _node(nodes, "merge").id
        as_x_id = _node(nodes, "as_X").id
        assert (merge_id, as_x_id) not in ep, "Redundant merge→as_X edge present"

    def test_multiline_merge_to_drop_to_as_x_chain(self):
        """Multi-line: correct merge → drop → as_X chain."""
        nodes, edges = extract_nodes_with_ranges(self.MULTILINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        merge_id = _node(nodes, "merge").id
        drop_id = _node(nodes, "drop").id
        as_x_id = _node(nodes, "as_X").id
        assert (merge_id, drop_id) in ep
        assert (drop_id, as_x_id) in ep

    def test_multiline_no_spurious_drop_to_as_y(self):
        """Multi-line: as_y on a prior line must NOT get a drop→as_y edge."""
        nodes, edges = extract_nodes_with_ranges(self.MULTILINE_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        drop_id = _node(nodes, "drop").id
        as_y_id = _node(nodes, "as_y").id
        assert (drop_id, as_y_id) not in ep, "Spurious drop→as_y edge present"

    # --- as_X followed immediately by sem_clean ---

    SEM_CHAIN_SNIPPET = '''
def sempipes_pipeline():
    df = skrub.var("data")
    x = sempipes.as_X(df.drop(columns=["target"]), "X")
    x = x.sem_clean(nl_prompt="Clean.", columns=["col"])
    return x
'''

    def test_as_x_feeds_sem_clean_not_drop(self):
        """as_X must feed sem_clean; drop must NOT bypass as_X to reach sem_clean."""
        nodes, edges = extract_nodes_with_ranges(self.SEM_CHAIN_SNIPPET, prune=False)
        ep = _edges(nodes, edges)
        as_x_id = _node(nodes, "as_X").id
        drop_id = _node(nodes, "drop").id
        sem_clean_id = _node(nodes, "sem_clean").id
        assert (as_x_id, sem_clean_id) in ep, "as_X→sem_clean edge missing"
        assert (drop_id, sem_clean_id) not in ep, "Spurious drop→sem_clean edge present"


# ---------------------------------------------------------------------------
# House prices – exact edge graph
# ---------------------------------------------------------------------------

class TestHousePricesExactGraph:
    """Precise edge-set and source-range checks for the house_prices pipeline."""

    def test_exact_edges_pruned(self):
        """Full HOUSE_PRICES_PIPELINE_BODY (prune=True): exact edge set."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY)
        ep = _edges(nodes, edges)
        # Input nodes feed merge
        assert ("var_facts_3", "merge_7") in ep
        assert ("var_cities_4", "merge_7") in ep
        assert ("var_images_5", "merge_7") in ep
        # merge feeds as_y and drop (inline drop of as_X)
        assert ("merge_7", "as_y_9") in ep
        assert ("merge_7", "drop_15") in ep
        # NO direct merge → as_X (drop is the intermediary)
        assert ("merge_7", "as_X_14") not in ep, "Redundant merge→as_X present"
        # Inline drop feeds as_X
        assert ("drop_15", "as_X_14") in ep
        # Semantic chain
        assert ("as_X_14", "sem_clean_19") in ep
        assert ("sem_clean_19", "sem_extract_features_28") in ep
        assert ("sem_extract_features_28", "sem_gen_features_35") in ep
        assert ("sem_gen_features_35", "skb_apply_42") in ep
        # TableVectorizer apply
        assert ("skb_apply_42", "skb_apply_48") in ep
        # as_y feeds final apply (y=price)
        assert ("as_y_9", "skb_apply_48") in ep
        # Total: 12 edges (apply_func_52 is pruned as dead-end)
        assert len(edges) == 12, f"Expected 12 edges, got {len(edges)}: {ep}"

    def test_no_redundant_merge_to_as_x(self):
        """Dedicated regression: merge must not bypass drop to reach as_X."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        ep = _edges(nodes, edges)
        assert ("merge_7", "as_X_14") not in ep

    def test_drop_is_only_intermediary_to_as_x(self):
        """drop_15 is the only parent of as_X_14."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        parents_of_as_x = {e.source for e in edges if e.target == "as_X_14"}
        assert parents_of_as_x == {"drop_15"}, f"Unexpected parents of as_X: {parents_of_as_x}"

    def test_source_range_var_facts(self):
        """<Var 'facts'> source range covers 'skrub.var' on line 3."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "<Var 'facts'>")
        assert n.source_range.start_line == 3
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "skrub.var"

    def test_source_range_merge(self):
        """merge source range covers 'merge' on line 7 (first of chained pair)."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "merge")
        assert n.source_range.start_line == 7
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "merge"

    def test_source_range_as_y(self):
        """as_y source range covers 'as_y' on line 9."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "as_y")
        assert n.source_range.start_line == 9
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "as_y"

    def test_source_range_as_x(self):
        """as_X source range covers 'as_X' on line 14."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "as_X")
        assert n.source_range.start_line == 14
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "as_X"

    def test_source_range_inline_drop(self):
        """Inline drop source range covers 'drop' on line 15 (inside as_X args)."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        drop_nodes = _nodes_with_label(nodes, "drop")
        drop_15 = next((n for n in drop_nodes if n.source_range.start_line == 15), None)
        assert drop_15 is not None, "drop node on line 15 not found"
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, drop_15) == "drop"

    def test_source_range_sem_clean(self):
        """sem_clean source range covers 'sem_clean' on line 19."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "sem_clean")
        assert n.source_range.start_line == 19
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "sem_clean"

    def test_source_range_sem_extract_features(self):
        """sem_extract_features source range covers the operator name on line 28."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "sem_extract_features")
        assert n.source_range.start_line == 28
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "sem_extract_features"

    def test_source_range_sem_gen_features(self):
        """sem_gen_features source range covers the operator name on line 35."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        n = _node(nodes, "sem_gen_features")
        assert n.source_range.start_line == 35
        assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "sem_gen_features"

    def test_source_range_skb_apply_nodes(self):
        """Two skb.apply nodes are on lines 42 and 48; both highlight 'skb.apply'."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        apply_nodes = _nodes_with_label(nodes, "skb.apply")
        assert len(apply_nodes) >= 2
        for n in apply_nodes:
            assert _highlight(HOUSE_PRICES_PIPELINE_BODY, n) == "skb.apply"
        lines = {n.source_range.start_line for n in apply_nodes}
        assert 42 in lines and 48 in lines

    def test_column_ranges_no_leading_dot(self):
        """Method-style operators must not include a leading dot in their column range."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        for n in nodes:
            highlighted = _highlight(HOUSE_PRICES_PIPELINE_BODY, n)
            assert not highlighted.startswith("."), (
                f"Node {n.id!r} highlight starts with dot: {highlighted!r}"
            )

    def test_column_ranges_no_trailing_paren(self):
        """Operator column ranges must not include the trailing '('."""
        nodes, _ = extract_nodes_with_ranges(HOUSE_PRICES_PIPELINE_BODY, prune=False)
        for n in nodes:
            highlighted = _highlight(HOUSE_PRICES_PIPELINE_BODY, n)
            assert not highlighted.endswith("("), (
                f"Node {n.id!r} highlight ends with '(': {highlighted!r}"
            )


# ---------------------------------------------------------------------------
# Museums – exact edge graph
# ---------------------------------------------------------------------------

class TestMuseumsExactGraph:
    """Precise edge-set and source-range checks for the museums pipeline."""

    def test_exact_edges_pruned(self):
        """Full MUSEUMS_PIPELINE_BODY (prune=True): exact edge set."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY)
        ep = _edges(nodes, edges)
        # Input node feeds apply_func (spaCy)
        assert ("var_artworks_3", "skb_apply_func_4") in ep
        # apply_func feeds as_y and drop (inline drop of as_X)
        assert ("skb_apply_func_4", "as_y_6") in ep
        assert ("skb_apply_func_4", "drop_12") in ep
        # NO direct apply_func → as_X (drop is the intermediary)
        assert ("skb_apply_func_4", "as_X_11") not in ep, "Redundant apply_func→as_X present"
        # Inline drop feeds as_X
        assert ("drop_12", "as_X_11") in ep
        # Semantic chain through artwork_data
        assert ("as_X_11", "sem_extract_features_16") in ep
        assert ("sem_extract_features_16", "sem_gen_features_24") in ep
        assert ("sem_gen_features_24", "skb_apply_func_29") in ep
        assert ("skb_apply_func_29", "sem_refine_31") in ep
        assert ("sem_refine_31", "drop_37") in ep
        assert ("drop_37", "skb_apply_39") in ep
        assert ("skb_apply_39", "skb_apply_42") in ep
        # as_y feeds final apply (y=culture_target)
        assert ("as_y_6", "skb_apply_42") in ep
        # Total: 12 edges
        assert len(edges) == 12, f"Expected 12 edges, got {len(edges)}: {ep}"

    def test_no_redundant_apply_func_to_as_x(self):
        """Dedicated regression: skb.apply_func must not bypass drop to reach as_X."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        ep = _edges(nodes, edges)
        assert ("skb_apply_func_4", "as_X_11") not in ep

    def test_drop_is_only_intermediary_to_as_x(self):
        """drop_12 is the only parent of as_X_11."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        parents_of_as_x = {e.source for e in edges if e.target == "as_X_11"}
        assert parents_of_as_x == {"drop_12"}, f"Unexpected parents of as_X: {parents_of_as_x}"

    def test_standalone_drop_not_confused_with_inline_drop(self):
        """The standalone drop_37 (drop columns) must not connect to as_X."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        ep = _edges(nodes, edges)
        assert ("drop_37", "as_X_11") not in ep

    def test_source_range_var_artworks(self):
        """<Var 'artworks'> source range covers 'skrub.var' on line 3."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        n = _node(nodes, "<Var 'artworks'>")
        assert n.source_range.start_line == 3
        assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "skrub.var"

    def test_source_range_first_apply_func(self):
        """First skb.apply_func (spaCy) is on line 4; highlighted text is 'skb.apply_func'."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        apply_funcs = _nodes_with_label(nodes, "skb.apply_func")
        n4 = next((n for n in apply_funcs if n.source_range.start_line == 4), None)
        assert n4 is not None
        assert _highlight(MUSEUMS_PIPELINE_BODY, n4) == "skb.apply_func"

    def test_source_range_as_y(self):
        """as_y source range covers 'as_y' on line 6."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        n = _node(nodes, "as_y")
        assert n.source_range.start_line == 6
        assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "as_y"

    def test_source_range_as_x(self):
        """as_X source range covers 'as_X' on line 11."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        n = _node(nodes, "as_X")
        assert n.source_range.start_line == 11
        assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "as_X"

    def test_source_range_inline_drop(self):
        """Inline drop (inside as_X args) source range covers 'drop' on line 12."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        drop_nodes = _nodes_with_label(nodes, "drop")
        drop_12 = next((n for n in drop_nodes if n.source_range.start_line == 12), None)
        assert drop_12 is not None, "drop node on line 12 not found"
        assert _highlight(MUSEUMS_PIPELINE_BODY, drop_12) == "drop"

    def test_source_range_sem_extract_features(self):
        """sem_extract_features source range covers the operator name on line 16."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        n = _node(nodes, "sem_extract_features")
        assert n.source_range.start_line == 16
        assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "sem_extract_features"

    def test_source_range_sem_refine(self):
        """sem_refine source range covers 'sem_refine' on line 31."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        n = _node(nodes, "sem_refine")
        assert n.source_range.start_line == 31
        assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "sem_refine"

    def test_source_range_standalone_drop(self):
        """Standalone drop_37 source range covers 'drop' on line 37."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        drop_nodes = _nodes_with_label(nodes, "drop")
        drop_37 = next((n for n in drop_nodes if n.source_range.start_line == 37), None)
        assert drop_37 is not None, "drop node on line 37 not found"
        assert _highlight(MUSEUMS_PIPELINE_BODY, drop_37) == "drop"

    def test_source_range_two_skb_apply_nodes(self):
        """Both skb.apply nodes (lines 39, 42) highlight 'skb.apply'."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        apply_nodes = _nodes_with_label(nodes, "skb.apply")
        assert len(apply_nodes) >= 2
        for n in apply_nodes:
            assert _highlight(MUSEUMS_PIPELINE_BODY, n) == "skb.apply"
        lines_seen = {n.source_range.start_line for n in apply_nodes}
        assert 39 in lines_seen and 42 in lines_seen

    def test_column_ranges_no_leading_dot(self):
        """No operator highlight in the museums pipeline starts with a dot."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        for n in nodes:
            highlighted = _highlight(MUSEUMS_PIPELINE_BODY, n)
            assert not highlighted.startswith("."), (
                f"Node {n.id!r} highlight starts with dot: {highlighted!r}"
            )

    def test_column_ranges_no_trailing_paren(self):
        """No operator highlight ends with '('."""
        nodes, _ = extract_nodes_with_ranges(MUSEUMS_PIPELINE_BODY, prune=False)
        for n in nodes:
            highlighted = _highlight(MUSEUMS_PIPELINE_BODY, n)
            assert not highlighted.endswith("("), (
                f"Node {n.id!r} highlight ends with '(': {highlighted!r}"
            )
