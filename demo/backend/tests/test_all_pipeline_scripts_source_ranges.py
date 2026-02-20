"""Test source ranges for all pipeline scripts in pipeline_scripts/ folder.

This test verifies that:
1. All nodes have valid source_range information
2. Source ranges point to actual text in the script
3. Nodes generally follow document order (accounting for multiline)
"""

from pathlib import Path

import pytest

from services.graph_api import compile_script_to_graph_dynamic


def find_all_pipeline_scripts():
    """Find all .py files in pipeline_scripts/ folder."""
    # Go up from backend/tests to repo root, then into pipeline_scripts
    repo_root = Path(__file__).parents[3]
    pipeline_scripts_dir = repo_root / "pipeline_scripts"

    if not pipeline_scripts_dir.exists():
        pytest.skip(f"pipeline_scripts directory not found at {pipeline_scripts_dir}")

    scripts = list(pipeline_scripts_dir.glob("*.py"))
    if not scripts:
        pytest.skip(f"No .py files found in {pipeline_scripts_dir}")

    return [(script.name, script.read_text()) for script in scripts]


# Parametrize test with all pipeline scripts
pipeline_scripts = find_all_pipeline_scripts()


@pytest.mark.parametrize("script_name,script_content", pipeline_scripts, ids=[name for name, _ in pipeline_scripts])
def test_script_nodes_have_valid_source_ranges(script_name, script_content):
    """All nodes should have valid source_range that points to actual code."""
    result = compile_script_to_graph_dynamic(script_content)

    # Skip if compilation failed
    if len(result.validation_errors) > 0:
        pytest.skip(f"Script {script_name} has validation errors: {result.validation_errors}")

    if len(result.nodes) == 0:
        pytest.skip(f"Script {script_name} produced empty graph")

    script_lines = script_content.splitlines()
    max_line = len(script_lines)

    nodes_without_ranges = []
    nodes_with_invalid_ranges = []

    for node in result.nodes:
        if node.source_range is None:
            nodes_without_ranges.append(node.label)
            continue

        sr = node.source_range

        # Check line numbers are valid
        if not (1 <= sr.start_line <= max_line):
            nodes_with_invalid_ranges.append({
                "label": node.label,
                "reason": f"start_line {sr.start_line} out of range [1, {max_line}]"
            })
            continue

        if not (1 <= sr.end_line <= max_line):
            nodes_with_invalid_ranges.append({
                "label": node.label,
                "reason": f"end_line {sr.end_line} out of range [1, {max_line}]"
            })
            continue

        # Check that the range makes sense (start <= end)
        if sr.start_line > sr.end_line:
            nodes_with_invalid_ranges.append({
                "label": node.label,
                "reason": f"start_line {sr.start_line} > end_line {sr.end_line}"
            })
            continue

        # Check that text actually exists at the specified position
        # (Column numbers should be within the line length)
        start_line_text = script_lines[sr.start_line - 1]  # 0-indexed
        if sr.start_column > len(start_line_text) + 1:  # +1 for end-of-line position
            nodes_with_invalid_ranges.append({
                "label": node.label,
                "reason": f"start_column {sr.start_column} > line length {len(start_line_text)} at line {sr.start_line}"
            })
            continue

        end_line_text = script_lines[sr.end_line - 1]  # 0-indexed
        if sr.end_column > len(end_line_text) + 1:  # +1 for end-of-line position
            nodes_with_invalid_ranges.append({
                "label": node.label,
                "reason": f"end_column {sr.end_column} > line length {len(end_line_text)} at line {sr.end_line}"
            })
            continue

    # Report findings
    errors = []

    # Some nodes may not have source ranges (intermediate operations), which is acceptable
    # But important nodes (semantic operators, inputs) should have them
    # Note: Generic <Apply ...> nodes are intermediate and don't need source ranges
    important_nodes_without_ranges = [
        label for label in nodes_without_ranges
        if any(marker in label.lower() for marker in [
            "sem_",  # Semantic operators
            "apply_with_sem_choose",  # Semantic apply
            "<var",  # Input variables
            "subsample",  # Data sampling
            "groupby",  # Pandas operations
            "merge"  # Pandas operations
        ]) and not label.startswith("<Apply ")  # Exclude generic Apply nodes
    ]

    if important_nodes_without_ranges:
        errors.append(
            f"Important nodes without source_range: {important_nodes_without_ranges}"
        )

    if nodes_with_invalid_ranges:
        invalid_details = "\n  ".join([
            f"- {item['label']}: {item['reason']}"
            for item in nodes_with_invalid_ranges
        ])
        errors.append(
            f"Nodes with invalid source_range:\n  {invalid_details}"
        )

    if errors:
        pytest.fail(f"Script {script_name} has source range issues:\n" + "\n".join(errors))


@pytest.mark.parametrize("script_name,script_content", pipeline_scripts, ids=[name for name, _ in pipeline_scripts])
def test_script_nodes_follow_document_order(script_name, script_content):
    """Nodes should generally follow document order (with tolerance for multiline)."""
    result = compile_script_to_graph_dynamic(script_content)

    # Skip if compilation failed
    if len(result.validation_errors) > 0:
        pytest.skip(f"Script {script_name} has validation errors: {result.validation_errors}")

    if len(result.nodes) == 0:
        pytest.skip(f"Script {script_name} produced empty graph")

    # Build adjacency map from edges (source -> target means source produces data for target)
    # In data flow, target depends on source, so source should appear before target in code
    predecessors = {}  # node_id -> list of predecessor node_ids
    for edge in result.edges:
        if edge.target not in predecessors:
            predecessors[edge.target] = []
        predecessors[edge.target].append(edge.source)

    # Build node lookup
    node_by_id = {n.id: n for n in result.nodes}

    violations = []

    for node in result.nodes:
        if node.source_range is None:
            continue

        # Get all predecessors (nodes that this node depends on)
        pred_ids = predecessors.get(node.id, [])

        for pred_id in pred_ids:
            pred_node = node_by_id.get(pred_id)
            if pred_node is None or pred_node.source_range is None:
                continue

            # Check if predecessor appears before or at the same line as current node
            # We use start_line for comparison
            # Allow some tolerance: predecessor can be up to 5 lines AFTER current node
            # (to handle cases where multiline operations have their components in different orders)
            pred_line = pred_node.source_range.start_line
            curr_line = node.source_range.start_line

            # Violation: predecessor appears significantly AFTER current node
            # (more than 5 lines after is suspicious)
            if pred_line > curr_line + 5:
                violations.append({
                    "node": node.label,
                    "node_line": curr_line,
                    "predecessor": pred_node.label,
                    "predecessor_line": pred_line,
                    "diff": pred_line - curr_line
                })

    # Allow a small number of violations (e.g., 10% of edges) due to complex multiline operations
    # But if more than 10% of edges violate order, something is wrong
    if violations:
        total_edges_with_ranges = sum(
            1 for node in result.nodes
            if node.source_range and predecessors.get(node.id)
        )
        violation_rate = len(violations) / max(total_edges_with_ranges, 1)

        if violation_rate > 0.1:  # More than 10% violations
            violation_details = "\n  ".join([
                f"- {v['node']} (line {v['node_line']}) depends on {v['predecessor']} (line {v['predecessor_line']}, +{v['diff']} lines)"
                for v in violations[:5]  # Show first 5
            ])

            pytest.fail(
                f"Script {script_name}: {len(violations)} nodes ({violation_rate:.1%}) violate document order:\n"
                f"  {violation_details}\n"
                f"  ... and {len(violations) - 5} more" if len(violations) > 5 else ""
            )


@pytest.mark.parametrize("script_name,script_content", pipeline_scripts, ids=[name for name, _ in pipeline_scripts])
def test_script_source_ranges_point_to_relevant_code(script_name, script_content):
    """Source ranges should point to text that seems related to the node label."""
    result = compile_script_to_graph_dynamic(script_content)

    # Skip if compilation failed
    if len(result.validation_errors) > 0:
        pytest.skip(f"Script {script_name} has validation errors: {result.validation_errors}")

    if len(result.nodes) == 0:
        pytest.skip(f"Script {script_name} produced empty graph")

    script_lines = script_content.splitlines()
    mismatches = []

    for node in result.nodes:
        if node.source_range is None:
            continue

        sr = node.source_range

        # Extract the text at the source range
        if sr.start_line == sr.end_line:
            # Single line
            line_text = script_lines[sr.start_line - 1]
            # Column numbers are 1-indexed, so adjust for 0-indexed slicing
            extracted_text = line_text[sr.start_column - 1:sr.end_column]
        else:
            # Multiline - just check the first line for simplicity
            line_text = script_lines[sr.start_line - 1]
            extracted_text = line_text[sr.start_column - 1:]

        # Check if the extracted text seems relevant to the node label
        # For semantic operators, check if the operator name appears in the text or nearby
        label_lower = node.label.lower()

        # Extract key terms from label
        key_terms = []
        if label_lower.startswith("sem_"):
            # Semantic operators: sem_fillna, sem_gen_features, etc.
            key_terms.append(label_lower.split("sem_")[1] if "sem_" in label_lower else "")
        elif "apply_with_sem_choose" in label_lower:
            key_terms.append("apply_with_sem_choose")
        elif "<var" in label_lower:
            # Extract var name: <Var 'products'> -> 'products'
            if "'" in label_lower:
                var_name = label_lower.split("'")[1] if len(label_lower.split("'")) > 1 else ""
                key_terms.append(var_name)
        elif "getitem" in label_lower:
            # GetItem operations
            key_terms.append("[")  # Should contain bracket notation
        elif "groupby" in label_lower:
            key_terms.append("groupby")
        elif "merge" in label_lower:
            key_terms.append("merge")
        elif "apply" in label_lower:
            key_terms.append("apply")

        # Check if any key term appears in the extracted text or nearby context
        # (check 3 lines around the source range)
        context_lines = []
        for line_num in range(max(1, sr.start_line - 1), min(len(script_lines) + 1, sr.start_line + 3)):
            if 1 <= line_num <= len(script_lines):
                context_lines.append(script_lines[line_num - 1])
        context_text = "\n".join(context_lines).lower()

        # Check if the code seems relevant
        if key_terms:
            found_any = any(term and term in context_text for term in key_terms)
            if not found_any:
                mismatches.append({
                    "label": node.label,
                    "line": sr.start_line,
                    "extracted": extracted_text[:50],  # First 50 chars
                    "key_terms": key_terms,
                    "context": context_text[:100]  # First 100 chars of context
                })

    # Allow some mismatches (intermediate nodes, fused nodes, etc.)
    # But if more than 20% don't match, something might be wrong
    nodes_with_ranges = sum(1 for n in result.nodes if n.source_range)
    if mismatches and nodes_with_ranges > 0:
        mismatch_rate = len(mismatches) / nodes_with_ranges

        if mismatch_rate > 0.2:  # More than 20% mismatches
            mismatch_details = "\n  ".join([
                f"- {m['label']} (line {m['line']}): looking for {m['key_terms']}, found '{m['extracted']}'"
                for m in mismatches[:3]  # Show first 3
            ])

            pytest.fail(
                f"Script {script_name}: {len(mismatches)} nodes ({mismatch_rate:.1%}) don't seem to match their source ranges:\n"
                f"  {mismatch_details}\n"
                f"  ... and {len(mismatches) - 3} more" if len(mismatches) > 3 else ""
            )


def test_all_pipeline_scripts_found():
    """Sanity check that we found some pipeline scripts to test."""
    scripts = find_all_pipeline_scripts()
    assert len(scripts) > 0, "No pipeline scripts found in pipeline_scripts/"

    # Print what we found for debugging
    script_names = [name for name, _ in scripts]
    print(f"\nFound {len(scripts)} pipeline scripts: {script_names}")
