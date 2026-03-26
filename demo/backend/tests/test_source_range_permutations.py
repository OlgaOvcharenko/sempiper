"""Permutation / property tests for extract_nodes_with_ranges.

Verifies parser correctness under systematic script mutations using *relative*
assertions (mutated_position == base_position + expected_delta), so tests do
not depend on pre-computed absolute column numbers.

Scenarios:
  1. Prepend N blank lines  → every start_line shifts by +N, columns unchanged
  2. Insert N blank lines mid-script → only nodes *after* insertion point shift
  3. Rename a variable      → operator columns shift by len(new) - len(old)
  4. Extra indentation      → all columns inside function body shift by N spaces
  5. Inline comments        → ranges are unchanged
  6. Dead code between ops  → node count and labels are unchanged
  7. Variable name containing a sempipes keyword → no spurious nodes
  8. Appending non-pipeline code → node count unchanged, new code not matched
"""

import pytest

from services.compile_parse import extract_nodes_with_ranges


# ===========================================================================
# Base scripts
# ===========================================================================

# 7-node minimal pipeline — all labels unique, easy to mutate.
# Short variable names keep lines compact so column arithmetic is transparent.
BASE_SCRIPT = """\
import skrub
import sempipes


def sempipes_pipeline():
    v = skrub.var("v")
    y = sempipes.as_y(v["label"], "Label")
    X = sempipes.as_X(v.drop(columns=["label"]), "Features")
    X = X.sem_fillna(target_column="col_a", nl_prompt="Fill")
    X = X.sem_gen_features(nl_prompt="Gen", name="g")
    out = X.skb.apply(skrub.TableVectorizer())
    return out
"""
# Expected nodes (1-indexed lines):
#  L6   <Var 'v'>         skrub.var(
#  L7   as_y              sempipes.as_y(
#  L8   as_X              sempipes.as_X(
#  L8   drop              v.drop(   inside as_X arg
#  L9   sem_fillna        X.sem_fillna(
#  L10  sem_gen_features  X.sem_gen_features(
#  L11  skb.apply         X.skb.apply(

# 2-node pipeline for clean variable-rename tests.
# _XVAR_ is a unique placeholder that won't appear anywhere else in the script.
RENAME_BASE = """\
import skrub
import sempipes


def sempipes_pipeline():
    _XVAR_ = skrub.var("data")
    result = _XVAR_.sem_fillna(target_column="col", nl_prompt="Fill it")
    return result
"""
# Nodes:
#  L6  <Var 'data'>   skrub.var(    position depends on len("_XVAR_")
#  L7  sem_fillna     _XVAR_.sem_fillna(

_OLD_VAR = "_XVAR_"


# ===========================================================================
# Helpers
# ===========================================================================

def _nodes(script):
    nodes, _ = extract_nodes_with_ranges(script)
    return nodes


def _sorted_positions(nodes):
    """Return (label, line, start_col, end_col) sorted by (line, col)."""
    return sorted(
        [
            (
                n.label,
                n.source_range.start_line,
                n.source_range.start_column,
                n.source_range.end_column,
            )
            for n in nodes
            if n.source_range
        ],
        key=lambda t: (t[1], t[2]),
    )


def _by_label(nodes):
    """Return {label: node}; raises if any label is duplicated."""
    result = {}
    for n in nodes:
        if n.label in result:
            raise AssertionError(
                f"Duplicate label {n.label!r} — use a script with unique labels"
            )
        result[n.label] = n
    return result


# ===========================================================================
# 1. Prepend N blank lines → all line numbers shift by +N
# ===========================================================================

@pytest.mark.parametrize("n", [1, 3, 7, 15])
def test_prepend_blank_lines_shifts_all_line_numbers_by_n(n):
    """Prepending N blank lines shifts every node's start_line by +N; columns unchanged."""
    base = _nodes(BASE_SCRIPT)
    mutated = _nodes("\n" * n + BASE_SCRIPT)

    assert len(base) == len(mutated), (
        f"Node count changed: {len(base)} → {len(mutated)}"
    )

    for (bl, bline, bcol, bend), (ml, mline, mcol, mend) in zip(
        _sorted_positions(base), _sorted_positions(mutated)
    ):
        assert bl == ml, f"Label mismatch: {bl!r} vs {ml!r}"
        assert mline == bline + n, (
            f"Node {bl!r}: expected line {bline + n} (base {bline} + {n}), got {mline}"
        )
        assert mcol == bcol, (
            f"Node {bl!r}: start_column must not change ({bcol} → {mcol})"
        )
        assert mend == bend, (
            f"Node {bl!r}: end_column must not change ({bend} → {mend})"
        )


# ===========================================================================
# 2. Insert N blank lines mid-script → only nodes after the insertion shift
# ===========================================================================

@pytest.mark.parametrize("n", [1, 5, 10])
def test_insert_blank_lines_before_sem_fillna_shifts_only_later_nodes(n):
    """Inserting N blank lines between as_X (line 8) and sem_fillna (line 9)
    shifts sem_fillna, sem_gen_features, and skb.apply by +N; earlier nodes unchanged."""
    AFTER_LINE = 8  # 1-indexed; nodes at original line > 8 should shift

    lines = BASE_SCRIPT.splitlines()
    mutated_script = "\n".join(lines[:AFTER_LINE] + [""] * n + lines[AFTER_LINE:])

    base = _by_label(_nodes(BASE_SCRIPT))
    mutated = _by_label(_nodes(mutated_script))

    assert set(base) == set(mutated), (
        f"Label sets differ: {set(base)} vs {set(mutated)}"
    )

    for label, base_node in base.items():
        mut_node = mutated[label]
        base_line = base_node.source_range.start_line
        mut_line = mut_node.source_range.start_line

        if base_line > AFTER_LINE:
            assert mut_line == base_line + n, (
                f"Node {label!r} (orig line {base_line}): expected line "
                f"{base_line + n} after inserting {n} blanks after line "
                f"{AFTER_LINE}, got {mut_line}"
            )
        else:
            assert mut_line == base_line, (
                f"Node {label!r} (orig line {base_line}): should NOT shift "
                f"when blanks are inserted after line {AFTER_LINE}, got {mut_line}"
            )

        # Columns must be unchanged regardless of position
        assert mut_node.source_range.start_column == base_node.source_range.start_column, (
            f"Node {label!r}: start_column must not change"
        )
        assert mut_node.source_range.end_column == base_node.source_range.end_column, (
            f"Node {label!r}: end_column must not change"
        )


@pytest.mark.parametrize("n", [1, 4, 9])
def test_insert_blank_lines_at_very_top_of_pipeline_body_shifts_all_nodes(n):
    """Inserting blank lines at the very start of the function body (before line 6)
    shifts every node by +N."""
    AFTER_LINE = 5  # insert after 'def sempipes_pipeline():' line

    lines = BASE_SCRIPT.splitlines()
    mutated_script = "\n".join(lines[:AFTER_LINE] + [""] * n + lines[AFTER_LINE:])

    base = _by_label(_nodes(BASE_SCRIPT))
    mutated = _by_label(_nodes(mutated_script))

    assert set(base) == set(mutated)

    for label, base_node in base.items():
        mut_node = mutated[label]
        base_line = base_node.source_range.start_line
        mut_line = mut_node.source_range.start_line

        # All pipeline nodes are inside the function body (line > 5), so all shift
        assert mut_line == base_line + n, (
            f"Node {label!r}: expected line {base_line + n}, got {mut_line}"
        )
        assert mut_node.source_range.start_column == base_node.source_range.start_column
        assert mut_node.source_range.end_column == base_node.source_range.end_column


# ===========================================================================
# 3. Variable renaming → operator columns shift by len(new) - len(old)
# ===========================================================================

@pytest.mark.parametrize("new_name", [
    "X",                        # 1 char  → delta = 1 - 6 = -5 (shorter)
    "v",                        # 1 char  → delta = -5
    "df",                       # 2 chars → delta = -4
    _OLD_VAR,                   # 6 chars → delta =  0 (no-op rename)
    "features",                 # 8 chars → delta = +2
    "feature_matrix",           # 14 chars → delta = +8
    "my_very_long_variable_nm", # 24 chars → delta = +18
])
def test_rename_placeholder_variable_shifts_columns_by_length_delta(new_name):
    """Renaming _XVAR_ to new_name shifts every operator's start/end column by
    len(new_name) - len('_XVAR_'), leaving line numbers unchanged.

    Both affected nodes (<Var 'data'> and sem_fillna) see the same delta because
    _XVAR_ appears exactly once per line in each:
      Line 6:  `    _XVAR_ = skrub.var("data")`       → col of skrub.var(
      Line 7:  `    result = _XVAR_.sem_fillna(...)`   → col of .sem_fillna(
    """
    delta = len(new_name) - len(_OLD_VAR)
    mutated_script = RENAME_BASE.replace(_OLD_VAR, new_name)

    base_nodes = _by_label(_nodes(RENAME_BASE))
    mut_nodes = _by_label(_nodes(mutated_script))

    assert set(base_nodes) == set(mut_nodes), (
        f"Label sets must match: base={set(base_nodes)}, mutated={set(mut_nodes)}"
    )

    for label in ["<Var 'data'>", "sem_fillna"]:
        base_sr = base_nodes[label].source_range
        mut_sr = mut_nodes[label].source_range

        assert mut_sr.start_line == base_sr.start_line, (
            f"Node {label!r}: line must not change on rename"
        )
        assert mut_sr.start_column == base_sr.start_column + delta, (
            f"Node {label!r}: expected start_col {base_sr.start_column + delta} "
            f"(base {base_sr.start_column} + delta {delta}), got {mut_sr.start_column}"
        )
        assert mut_sr.end_column == base_sr.end_column + delta, (
            f"Node {label!r}: expected end_col {base_sr.end_column + delta}, "
            f"got {mut_sr.end_column}"
        )


def test_rename_zero_delta_produces_identical_positions():
    """Renaming a variable to itself (delta=0) must produce identical positions."""
    base_nodes = _nodes(RENAME_BASE)
    same_nodes = _nodes(RENAME_BASE.replace(_OLD_VAR, _OLD_VAR))

    assert _sorted_positions(base_nodes) == _sorted_positions(same_nodes)


# ===========================================================================
# 4. Extra indentation → all columns inside function body shift by extra spaces
# ===========================================================================

@pytest.mark.parametrize("extra", [2, 4, 8])
def test_extra_indentation_inside_function_body_shifts_all_columns(extra):
    """Adding `extra` spaces to every indented line shifts every node's column by
    +extra; line numbers are unchanged."""
    lines = BASE_SCRIPT.splitlines()
    mutated_lines = [
        " " * extra + line if line.startswith("    ") else line
        for line in lines
    ]
    mutated_script = "\n".join(mutated_lines)

    base = _by_label(_nodes(BASE_SCRIPT))
    mutated = _by_label(_nodes(mutated_script))

    assert set(base) == set(mutated)

    for label, base_node in base.items():
        mut_node = mutated[label]
        base_sr = base_node.source_range
        mut_sr = mut_node.source_range

        assert mut_sr.start_line == base_sr.start_line, (
            f"Node {label!r}: line changed unexpectedly"
        )
        assert mut_sr.start_column == base_sr.start_column + extra, (
            f"Node {label!r}: expected start_col {base_sr.start_column + extra} "
            f"(+{extra}), got {mut_sr.start_column}"
        )
        assert mut_sr.end_column == base_sr.end_column + extra, (
            f"Node {label!r}: expected end_col {base_sr.end_column + extra}, "
            f"got {mut_sr.end_column}"
        )


def test_two_space_indent_instead_of_four_shifts_columns_by_minus_two():
    """Switching from 4-space to 2-space indentation shifts columns by -2."""
    lines = BASE_SCRIPT.splitlines()
    mutated_lines = [
        line[2:] if line.startswith("    ") else line
        for line in lines
    ]
    mutated_script = "\n".join(mutated_lines)

    base = _by_label(_nodes(BASE_SCRIPT))
    mutated = _by_label(_nodes(mutated_script))

    assert set(base) == set(mutated)

    for label, base_node in base.items():
        mut_node = mutated[label]
        assert mut_node.source_range.start_column == base_node.source_range.start_column - 2
        assert mut_node.source_range.end_column == base_node.source_range.end_column - 2
        assert mut_node.source_range.start_line == base_node.source_range.start_line


# ===========================================================================
# 5. Inline comments → ranges unchanged
# ===========================================================================

def test_inline_comments_after_calls_do_not_change_source_ranges():
    """# comments appended after every call must not affect start_line, start_column,
    or end_column of any node."""
    commented_script = """\
import skrub
import sempipes


def sempipes_pipeline():
    v = skrub.var("v")  # input variable
    y = sempipes.as_y(v["label"], "Label")  # target
    X = sempipes.as_X(v.drop(columns=["label"]), "Features")  # features
    X = X.sem_fillna(target_column="col_a", nl_prompt="Fill")  # fill NaN
    X = X.sem_gen_features(nl_prompt="Gen", name="g")  # generated feats
    out = X.skb.apply(skrub.TableVectorizer())  # vectorize
    return out
"""
    base = _by_label(_nodes(BASE_SCRIPT))
    commented = _by_label(_nodes(commented_script))

    assert set(base) == set(commented)

    for label in base:
        b = base[label].source_range
        c = commented[label].source_range
        assert c.start_line == b.start_line, f"Node {label!r}: line changed"
        assert c.start_column == b.start_column, f"Node {label!r}: start_col changed"
        assert c.end_column == b.end_column, f"Node {label!r}: end_col changed"


# ===========================================================================
# 6. Dead code between operators → node count and labels unchanged
# ===========================================================================

def test_dead_code_between_operators_does_not_produce_extra_nodes():
    """Plain Python assignments, dicts, and loops between pipeline calls must not
    be detected as extra nodes."""
    script_with_dead_code = """\
import skrub
import sempipes


def sempipes_pipeline():
    v = skrub.var("v")
    # Intermediate computation — no sempipes calls
    tmp = {"a": 1, "b": 2}
    count = 42
    values = [i * 2 for i in range(10)]
    y = sempipes.as_y(v["label"], "Label")
    X = sempipes.as_X(v.drop(columns=["label"]), "Features")
    # More dead code
    flag = True
    name = "hello"
    X = X.sem_fillna(target_column="col_a", nl_prompt="Fill")
    X = X.sem_gen_features(nl_prompt="Gen", name="g")
    out = X.skb.apply(skrub.TableVectorizer())
    return out
"""
    base = _nodes(BASE_SCRIPT)
    with_dead = _nodes(script_with_dead_code)

    assert len(base) == len(with_dead), (
        f"Dead code changed node count {len(base)} → {len(with_dead)}. "
        f"Extra nodes: {sorted(set(n.label for n in with_dead) - set(n.label for n in base))}"
    )
    assert sorted(n.label for n in base) == sorted(n.label for n in with_dead), (
        "Dead code changed the set of detected node labels"
    )


def test_appending_non_pipeline_code_at_end_does_not_add_nodes():
    """Code appended after the pipeline function (e.g. a main block) must not
    produce extra nodes unless it contains recognised sempipes/skrub patterns."""
    extra_code = """

# Post-pipeline code — no sempipes calls
import time
if __name__ == "__main__":
    result = None
    t0 = time.time()
    print(f"done in {time.time() - t0:.2f}s")
"""
    base_count = len(_nodes(BASE_SCRIPT))
    extended_count = len(_nodes(BASE_SCRIPT + extra_code))
    assert extended_count == base_count, (
        f"Appending plain code changed node count {base_count} → {extended_count}"
    )


# ===========================================================================
# 7. Variable names containing sempipes keywords → no spurious nodes
# ===========================================================================

def test_variable_named_with_sem_fillna_prefix_is_not_confused():
    """A variable named 'sem_fillna_result' contains the substring 'sem_fillna'.
    The parser must match only actual .sem_fillna( method calls, not bare
    variable names that happen to start with a keyword."""
    confusing_script = """\
import skrub
import sempipes


def sempipes_pipeline():
    sem_fillna_result = skrub.var("data")
    y = sempipes.as_y(sem_fillna_result["label"], "Label")
    X = sempipes.as_X(sem_fillna_result.drop(columns=["label"]), "Features")
    X = X.sem_fillna(target_column="col_a", nl_prompt="Fill")
    return X
"""
    all_nodes = _nodes(confusing_script)
    sem_fillna_nodes = [n for n in all_nodes if n.label == "sem_fillna"]
    assert len(sem_fillna_nodes) == 1, (
        f"Expected exactly 1 sem_fillna node, found {len(sem_fillna_nodes)}: "
        f"{[(n.label, n.source_range.start_line) for n in sem_fillna_nodes]}"
    )


def test_variable_named_with_skrub_var_substring_is_not_confused():
    """A variable named 'skrub_var_data' should not produce an extra <Var ...> node."""
    confusing_script = """\
import skrub
import sempipes


def sempipes_pipeline():
    skrub_var_data = 42        # just a regular variable, NOT a skrub.var call
    v = skrub.var("v")         # this IS a skrub.var call
    y = sempipes.as_y(v["label"], "Label")
    X = sempipes.as_X(v.drop(columns=["label"]), "Features")
    return X
"""
    all_nodes = _nodes(confusing_script)
    var_nodes = [n for n in all_nodes if n.label.startswith("<Var ")]
    assert len(var_nodes) == 1, (
        f"Expected exactly 1 <Var ...> node, found {len(var_nodes)}: "
        f"{[n.label for n in var_nodes]}"
    )
    assert var_nodes[0].label == "<Var 'v'>", (
        f"Expected <Var 'v'>, got {var_nodes[0].label!r}"
    )


# ===========================================================================
# 8. Combined: blank lines + rename together
# ===========================================================================

@pytest.mark.parametrize("n_blanks,new_name", [
    (3,  "X"),
    (5,  "feature_matrix"),
    (10, "df"),
])
def test_combined_blank_lines_and_rename_produce_additive_deltas(n_blanks, new_name):
    """Prepending N blank lines AND renaming the variable should produce additive
    effects: line_delta = +N, col_delta = len(new_name) - len(_XVAR_)."""
    col_delta = len(new_name) - len(_OLD_VAR)

    # Apply both mutations
    mutated_script = "\n" * n_blanks + RENAME_BASE.replace(_OLD_VAR, new_name)

    base_nodes = _by_label(_nodes(RENAME_BASE))
    mut_nodes = _by_label(_nodes(mutated_script))

    assert set(base_nodes) == set(mut_nodes)

    for label in ["<Var 'data'>", "sem_fillna"]:
        base_sr = base_nodes[label].source_range
        mut_sr = mut_nodes[label].source_range

        assert mut_sr.start_line == base_sr.start_line + n_blanks, (
            f"Node {label!r}: expected line {base_sr.start_line + n_blanks}, "
            f"got {mut_sr.start_line}"
        )
        assert mut_sr.start_column == base_sr.start_column + col_delta, (
            f"Node {label!r}: expected start_col {base_sr.start_column + col_delta}, "
            f"got {mut_sr.start_column}"
        )
        assert mut_sr.end_column == base_sr.end_column + col_delta, (
            f"Node {label!r}: expected end_col {base_sr.end_column + col_delta}, "
            f"got {mut_sr.end_column}"
        )
