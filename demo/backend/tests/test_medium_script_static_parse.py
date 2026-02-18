"""Debug test to see what static parse produces for medium script."""

from pathlib import Path

import pytest

from services.compile_parse import extract_nodes_with_ranges


@pytest.fixture
def medium_script():
    """Load the medium.py script content."""
    script_path = Path(__file__).parents[3] / "pipeline_scripts" / "medium.py"
    return script_path.read_text()


def test_print_static_parse_nodes(medium_script):
    """Print all nodes from static parse for comparison."""
    nodes, edges = extract_nodes_with_ranges(medium_script)

    print("\n\n=== STATIC PARSE NODES ===")
    print(f"Total nodes: {len(nodes)}\n")

    for i, node in enumerate(nodes):
        source_info = f"Line {node.source_range.start_line}:{node.source_range.start_column}-{node.source_range.end_line}:{node.source_range.end_column}"
        print(f"{i+1}. [{node.type}] {node.label}")
        print(f"   ID: {node.id}")
        print(f"   Source: {source_info}")
        print()
