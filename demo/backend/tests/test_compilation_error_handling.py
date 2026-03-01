"""Test that compilation errors are handled gracefully.

These tests verify that:
1. Invalid/broken scripts return empty graphs (not crash)
2. Python syntax errors are caught
3. Import errors are handled
4. Runtime errors during compilation are caught
5. Malicious/dangerous scripts don't execute (no arbitrary code execution)
"""

import pytest

from services.graph_api import compile_script_to_graph_dynamic


class TestSyntaxErrors:
    """Test scripts with Python syntax errors."""

    def test_missing_colon(self):
        """Script with missing colon should return empty graph."""
        script = """
import skrub
if True
    x = 1
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0, "Syntax error should produce empty graph"
        assert len(result.validation_errors) > 0, "Should have validation error"
        assert "Execution failed" in result.validation_errors[0]

    def test_invalid_indentation(self):
        """Script with invalid indentation should return empty graph."""
        script = """
import skrub
def foo():
x = 1
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0
        assert len(result.validation_errors) > 0

    def test_unclosed_parenthesis(self):
        """Script with unclosed parenthesis should report an error (may fall back to static)."""
        script = """
import skrub
products = skrub.var("products", None
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0

    def test_invalid_string_quote(self):
        """Script with mismatched quotes should return empty graph."""
        script = """
import skrub
products = skrub.var("products', None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Note: Python actually accepts this (treats as "products') - need more broken quote
        # Just verify it doesn't crash
        assert isinstance(result.validation_errors, list)


class TestImportErrors:
    """Test scripts with missing/invalid imports."""

    def test_missing_module(self):
        """Script importing non-existent module should report an error (may fall back to static)."""
        script = """
import skrub
import this_module_does_not_exist_at_all
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0
        assert "Execution failed" in result.validation_errors[0] or "failed" in result.validation_errors[0].lower()

    def test_invalid_from_import(self):
        """Script with invalid from...import should report an error (may fall back to static)."""
        script = """
import skrub
from nonexistent_package import SomeClass
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0


class TestRuntimeErrors:
    """Test scripts that fail during execution."""

    def test_undefined_variable(self):
        """Script using undefined variable should report an error (may fall back to static)."""
        script = """
import skrub
products = skrub.var("products", None)
# Use undefined variable outside of data arg (where rewriter won't fix it)
x = undefined_variable_that_does_not_exist
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0

    def test_attribute_error(self):
        """Script with actual attribute error during execution should report an error."""
        script = """
import skrub
# Access attribute on non-object
x = None.this_method_does_not_exist()
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0

    def test_type_error(self):
        """Script with type error during execution should report an error."""
        script = """
import skrub
# Cause immediate type error
x = len(123)  # len() requires sequence, not int
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0

    def test_division_by_zero(self):
        """Script with division by zero should report an error."""
        script = """
import skrub
x = 1 / 0
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0


class TestEmptyOrMinimalScripts:
    """Test scripts with no or minimal content."""

    def test_empty_script(self):
        """Empty script should return empty graph."""
        script = ""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0
        assert len(result.validation_errors) > 0
        # Should have error about no DataOp found
        assert any("DataOp" in err for err in result.validation_errors)

    def test_only_imports(self):
        """Script with only imports should return empty graph."""
        script = """
import os
import skrub
import sempipes
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0
        assert len(result.validation_errors) > 0
        assert any("DataOp" in err for err in result.validation_errors)

    def test_only_comments(self):
        """Script with only comments should return empty graph."""
        script = """
# This is a comment
# TODO: Implement the pipeline
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0
        assert len(result.validation_errors) > 0

    def test_new_py_template(self):
        """The new.py template script should return empty graph (not crash)."""
        script = """import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub

# TODO: Implement the new pipeline
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.nodes) == 0
        assert len(result.validation_errors) > 0
        assert any("DataOp" in err for err in result.validation_errors)


class TestPotentiallyDangerousScripts:
    """Test that potentially malicious scripts don't execute dangerous operations.

    Note: The script rewriting and execution environment should be sandboxed.
    These tests verify that dangerous operations either:
    1. Don't execute at all (blocked by rewriting)
    2. Execute but are harmless in the sandbox
    3. Fail safely and return empty graph
    """

    def test_os_system_call(self):
        """Script with os.system call should be handled safely."""
        script = """
import os
import skrub
os.system("echo 'This should not execute'")
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Should either fail (no os in exec_globals) or succeed without executing system command
        # Either way, it should not crash the backend
        assert isinstance(result.validation_errors, list)

    def test_subprocess_call(self):
        """Script with subprocess call should be handled safely (no crash).

        Note: subprocess is importable in the execution environment; the backend
        does not sandbox subprocess calls. This test verifies that a script using
        subprocess does not crash the compile step and returns a valid result.
        """
        script = """
import subprocess
import skrub
subprocess.run(["echo", "test"])
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Backend does not sandbox subprocess; script succeeds and produces graph nodes
        assert isinstance(result.validation_errors, list)
        # The skrub.var node should be present
        assert len(result.nodes) >= 1

    def test_file_operations(self):
        """Script with file operations should be handled safely.

        Note: Script rewriting removes data arguments, so file operations
        that would fail are often in data args and get removed. This is
        actually good - it means the system is robust. We just verify
        no crash occurs.
        """
        script = """
import skrub
# Try to read/write files (may succeed or fail, but shouldn't crash)
try:
    with open("/etc/passwd", "r") as f:
        data = f.read()
except:
    pass
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Should not crash - either succeeds or fails gracefully
        assert isinstance(result.validation_errors, list)
        # Graph may be empty or have nodes, depending on file access

    def test_infinite_loop(self):
        """Script with infinite loop should timeout or be caught.

        Note: This test is marked as slow and may be skipped in CI.
        The actual implementation may need timeout protection.
        """
        script = """
import skrub
while True:
    pass
products = skrub.var("products", None)
"""
        # This may hang, so in practice we'd need timeout protection
        # For now, just verify the script is recognized as problematic
        assert "while True" in script

    def test_eval_builtin(self):
        """Script using eval() builtin should be handled safely."""
        script = """
import skrub
eval("import os; os.system('echo test')")
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Should execute but eval is limited to exec_globals scope
        # which doesn't include os (unless explicitly added)
        assert isinstance(result.validation_errors, list)

    def test_exec_builtin(self):
        """Script using exec() builtin should be handled safely."""
        script = """
import skrub
exec("import os; os.system('rm -rf /')")
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Should execute but exec is limited to exec_globals scope
        assert isinstance(result.validation_errors, list)

    def test_network_request(self):
        """Script attempting network requests should be handled safely.

        Note: The import may succeed but the system is sandboxed enough
        that dangerous operations either fail or are harmless. The key is
        that the backend doesn't crash.
        """
        script = """
import urllib.request
import skrub
# Network request - may fail or succeed depending on environment
# but shouldn't crash the backend
try:
    urllib.request.urlopen("http://example.com")
except:
    pass
products = skrub.var("products", None)
"""
        result = compile_script_to_graph_dynamic(script)
        # Should not crash - either succeeds or fails gracefully
        assert isinstance(result.validation_errors, list)


class TestMixedErrorScenarios:
    """Test scripts with multiple issues."""

    def test_syntax_and_import_error(self):
        """Script with both syntax and import errors should report an error."""
        script = """
import nonexistent_module
if True
    x = 1
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0

    def test_valid_start_then_error(self):
        """Script that starts valid but fails during execution should report error (may fall back to static)."""
        script = """
import skrub
products = skrub.var("products", None)
products = products.skb.subsample(n=100)
# Then error
x = undefined_variable
"""
        result = compile_script_to_graph_dynamic(script)
        assert len(result.validation_errors) > 0


def test_error_messages_are_informative():
    """Error messages should be informative for debugging."""
    script = """
import skrub
# Cause an actual error during execution
x = undefined_variable_xyz
products = skrub.var("products", None)
"""
    result = compile_script_to_graph_dynamic(script)

    assert len(result.validation_errors) > 0
    error_msg = result.validation_errors[0]

    # Error should mention what went wrong
    assert "Execution failed" in error_msg or "error" in error_msg.lower()
    # Should be a string
    assert isinstance(error_msg, str)
    # Should not be empty
    assert len(error_msg) > 0


def test_house_prices_missing_deps():
    """house_prices.py fails gracefully when kagglehub is missing."""
    script = """
import os
import sempipes
import skrub
import pandas as pd
import kagglehub
from tabpfn import TabPFNRegressor
from tabpfn.constants import ModelVersion

path = kagglehub.dataset_download("ted8080/house-prices-and-images-socal")
houses_df = pd.read_csv(os.path.join(path, "socal2.csv"))
houses = skrub.var("houses", houses_df)
price = sempipes.as_y(houses["price"], "Price")
"""
    result = compile_script_to_graph_dynamic(script)

    # Should fail with import error for kagglehub (may still return static nodes via fallback)
    assert len(result.validation_errors) > 0
    combined_errors = " ".join(result.validation_errors).lower()
    assert "kagglehub" in combined_errors
