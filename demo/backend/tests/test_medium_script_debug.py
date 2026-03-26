"""Debug test to see what nodes are actually in the medium script graph."""

from pathlib import Path

import pytest

from services.graph_api import compile_script_to_graph_dynamic


@pytest.fixture
def medium_script():
    """Load the medium.py script content."""
    script_path = Path(__file__).parents[3] / "pipeline_scripts" / "medium.py"
    return script_path.read_text()


def test_print_all_nodes_in_medium_script(medium_script):
    """Print all nodes in the compiled medium script graph for debugging."""
    result = compile_script_to_graph_dynamic(medium_script)

    print("\n\n=== ALL NODES IN MEDIUM SCRIPT GRAPH ===")
    print(f"Total nodes: {len(result.nodes)}\n")

    for i, node in enumerate(result.nodes):
        source_info = "NO SOURCE_RANGE"
        if node.source_range:
            source_info = f"Line {node.source_range.start_line}:{node.source_range.start_column}-{node.source_range.end_line}:{node.source_range.end_column}"

        print(f"{i+1}. [{node.type}] {node.label}")
        print(f"   ID: {node.id}")
        print(f"   Source: {source_info}")
        print()

    # Also print nodes without source ranges
    print("\n=== NODES WITHOUT SOURCE RANGES ===")
    nodes_without_ranges = [n for n in result.nodes if n.source_range is None]
    for node in nodes_without_ranges:
        print(f"- [{node.type}] {node.label} (ID: {node.id})")

    print(f"\nTotal without ranges: {len(nodes_without_ranges)}/{len(result.nodes)}")
