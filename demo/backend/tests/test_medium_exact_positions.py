"""Test exact character positions for medium script nodes."""

from pathlib import Path

import pytest

from services.graph_api import compile_script_to_graph_dynamic


@pytest.fixture
def medium_script():
    """Load the medium.py script content."""
    script_path = Path(__file__).parents[3] / "pipeline_scripts" / "medium.py"
    return script_path.read_text()


def test_print_all_getitem_nodes_with_exact_positions(medium_script):
    """Print all GetItem nodes with their exact source positions."""
    result = compile_script_to_graph_dynamic(medium_script)

    print("\n\n=== ALL GETITEM NODES ===")
    getitem_nodes = [n for n in result.nodes if n.label.startswith("<GetItem")]

    for i, node in enumerate(getitem_nodes):
        print(f"\n{i+1}. {node.label}")
        print(f"   ID: {node.id}")
        if node.source_range:
            sr = node.source_range
            print(f"   Source: Line {sr.start_line}:{sr.start_column}-{sr.end_line}:{sr.end_column}")

            # Extract the actual text at this position
            lines = medium_script.splitlines()
            if sr.start_line <= len(lines):
                line = lines[sr.start_line - 1]
                text = line[sr.start_column - 1:sr.end_column]
                print(f"   Text at position: '{text}'")
                print(f"   Full line: {line}")
        else:
            print(f"   Source: NO SOURCE_RANGE")


def test_print_groupby_agg_reset_index_positions(medium_script):
    """Print exact positions of groupby, agg, reset_index nodes."""
    result = compile_script_to_graph_dynamic(medium_script)

    print("\n\n=== GROUPBY/AGG/RESET_INDEX NODES ===")

    for label_pattern in ["groupby", "agg", "reset_index"]:
        nodes = [n for n in result.nodes if label_pattern in n.label.lower()]
        for node in nodes:
            print(f"\n{node.label}")
            print(f"   ID: {node.id}")
            if node.source_range:
                sr = node.source_range
                print(f"   Source: Line {sr.start_line}:{sr.start_column}-{sr.end_line}:{sr.end_column}")

                # Extract the actual text at this position
                lines = medium_script.splitlines()
                if sr.start_line <= len(lines):
                    line = lines[sr.start_line - 1]
                    text = line[sr.start_column - 1:sr.end_column]
                    print(f"   Text at position: '{text}'")
                    print(f"   Full line: {line}")
            else:
                print(f"   Source: NO SOURCE_RANGE")


def test_verify_as_y_getitem_mapping(medium_script):
    """Verify that GetItem 'fraud_flag' maps to line 19, not GetItem 'basket_ID'."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Find the GetItem nodes
    basket_id_nodes = [n for n in result.nodes if "<GetItem" in n.label and "basket_ID" in n.label]
    fraud_flag_nodes = [n for n in result.nodes if "<GetItem" in n.label and "fraud_flag" in n.label]

    print("\n\n=== VERIFYING AS_Y MAPPING ===")

    if basket_id_nodes:
        node = basket_id_nodes[0]
        print(f"\nGetItem 'basket_ID': {node.label}")
        if node.source_range:
            print(f"   Line {node.source_range.start_line}")
            lines = medium_script.splitlines()
            print(f"   Full line: {lines[node.source_range.start_line - 1]}")
            assert node.source_range.start_line != 19, \
                f"ERROR: GetItem 'basket_ID' should NOT map to line 19 (as_y line)"
        else:
            print(f"   NO SOURCE_RANGE (expected - this is from line 27 filter)")

    if fraud_flag_nodes:
        node = fraud_flag_nodes[0]
        print(f"\nGetItem 'fraud_flag': {node.label}")
        if node.source_range:
            print(f"   Line {node.source_range.start_line}")
            lines = medium_script.splitlines()
            print(f"   Full line: {lines[node.source_range.start_line - 1]}")
            assert node.source_range.start_line == 19, \
                f"GetItem 'fraud_flag' should map to line 19 (as_y), got {node.source_range.start_line}"
        else:
            pytest.fail("ERROR: GetItem 'fraud_flag' should have source_range pointing to line 19")


def test_check_line_27_getitem_nodes(medium_script):
    """Check what nodes appear on line 27 (the isin filter line)."""
    result = compile_script_to_graph_dynamic(medium_script)

    print("\n\n=== LINE 27 ANALYSIS ===")
    lines = medium_script.splitlines()
    print(f"Line 27: {lines[26]}")  # 0-indexed

    # Find nodes that should map to line 27
    basket_id_nodes = [n for n in result.nodes if "basket_ID" in n.label and n.label.startswith("<GetItem")]

    print(f"\nFound {len(basket_id_nodes)} GetItem nodes with 'basket_ID':")
    for node in basket_id_nodes:
        print(f"  {node.label}")
        if node.source_range:
            print(f"    Line: {node.source_range.start_line}")
        else:
            print(f"    NO SOURCE_RANGE")

    # The GetItem 'basket_ID' from line 27 should either:
    # 1. Have source_range pointing to line 27, OR
    # 2. Have no source_range (acceptable for intermediate nodes)
    # It should NOT have source_range pointing to line 19!
    for node in basket_id_nodes:
        if node.source_range:
            assert node.source_range.start_line != 19, \
                f"GetItem 'basket_ID' has wrong source_range (line 19 instead of 27 or None)"
