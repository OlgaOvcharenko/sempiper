"""Tests for the cache module.

All tests use isolated temp directories to avoid affecting production cache.
"""

import json
import threading

import pytest

from services.cache import CacheService, MemoryCache, make_cache_key


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_cache(tmp_path):
    """Isolated cache service for tests - does not affect production .cache/"""
    return CacheService(cache_dir=tmp_path / ".test_cache")


@pytest.fixture
def memory_cache():
    """Fresh memory cache for unit tests."""
    return MemoryCache()


# ============================================================================
# Cache Key Tests
# ============================================================================


class TestCacheKey:
    """Tests for cache key generation."""

    def test_make_cache_key_deterministic(self):
        """Same inputs always produce same hash."""
        script = "print('hello')"
        temp = 0.5
        model = "gpt-4"

        key1 = make_cache_key(script, temp, model)
        key2 = make_cache_key(script, temp, model)

        assert key1 == key2

    def test_make_cache_key_different_scripts(self):
        """Different scripts produce different hashes."""
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("print('world')", 0.5, "gpt-4")

        assert key1 != key2

    def test_make_cache_key_different_temperatures(self):
        """Different temperatures produce different hashes."""
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("print('hello')", 0.7, "gpt-4")

        assert key1 != key2

    def test_make_cache_key_different_models(self):
        """Different models produce different hashes."""
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("print('hello')", 0.5, "gpt-3.5")

        assert key1 != key2

    def test_make_cache_key_whitespace_normalization(self):
        """Scripts with trailing whitespace produce same hash as without."""
        # Leading whitespace is preserved (it's indentation in Python)
        # Trailing whitespace is stripped
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("print('hello')  ", 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_leading_whitespace_matters(self):
        """Leading whitespace (indentation) produces different hash."""
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("  print('hello')", 0.5, "gpt-4")

        # Leading whitespace is meaningful in Python (indentation)
        assert key1 != key2

    def test_make_cache_key_temperature_rounding(self):
        """Temperatures that round to same value produce same key."""
        key1 = make_cache_key("print('hello')", 0.001, "gpt-4")
        key2 = make_cache_key("print('hello')", 0.004, "gpt-4")

        # Both round to 0.00
        assert key1 == key2

    def test_make_cache_key_temperature_rounding_different(self):
        """Temperatures that round to different values produce different keys."""
        key1 = make_cache_key("print('hello')", 0.004, "gpt-4")
        key2 = make_cache_key("print('hello')", 0.006, "gpt-4")

        # 0.004 rounds to 0.00, 0.006 rounds to 0.01
        assert key1 != key2

    def test_make_cache_key_model_case_insensitive(self):
        """'GPT-4' and 'gpt-4' produce same hash."""
        key1 = make_cache_key("print('hello')", 0.5, "GPT-4")
        key2 = make_cache_key("print('hello')", 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_model_whitespace_normalization(self):
        """Model names with whitespace are normalized."""
        key1 = make_cache_key("print('hello')", 0.5, "gpt-4")
        key2 = make_cache_key("print('hello')", 0.5, "  gpt-4  ")

        assert key1 == key2

    def test_make_cache_key_hash_length(self):
        """Hash is exactly 16 characters."""
        key = make_cache_key("print('hello')", 0.5, "gpt-4")

        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_make_cache_key_blank_lines_ignored(self):
        """Scripts with blank lines produce same hash as without."""
        script1 = "x = 1\ny = 2"
        script2 = "x = 1\n\n\ny = 2"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_comments_ignored(self):
        """Scripts with comments produce same hash as without."""
        script1 = "x = 1\ny = 2"
        script2 = "x = 1  # set x\ny = 2  # set y"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_comment_only_lines_ignored(self):
        """Lines with only comments are ignored."""
        script1 = "x = 1\ny = 2"
        script2 = "# header comment\nx = 1\n# middle comment\ny = 2\n# footer"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_trailing_whitespace_ignored(self):
        """Trailing whitespace on lines is ignored."""
        script1 = "x = 1\ny = 2"
        script2 = "x = 1   \ny = 2   "

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_preserves_indentation(self):
        """Indentation is preserved (different indentation = different key)."""
        script1 = "if True:\n    x = 1"
        script2 = "if True:\n        x = 1"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 != key2

    def test_make_cache_key_hash_in_string_preserved(self):
        """Hash characters inside strings are not treated as comments."""
        script1 = 'x = "hello # world"'
        script2 = 'x = "hello # world"  # actual comment'

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_single_quote_string_preserved(self):
        """Hash characters inside single-quoted strings are preserved."""
        script1 = "x = 'hello # world'"
        script2 = "x = 'hello # world'  # comment"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 == key2

    def test_make_cache_key_significant_code_change_different(self):
        """Actual code changes produce different hash."""
        script1 = "x = 1"
        script2 = "x = 2"

        key1 = make_cache_key(script1, 0.5, "gpt-4")
        key2 = make_cache_key(script2, 0.5, "gpt-4")

        assert key1 != key2


# ============================================================================
# Memory Cache Tests
# ============================================================================


class TestMemoryCache:
    """Tests for the single-key memory cache."""

    def test_get_from_memory_instant(self, memory_cache):
        """Memory lookup returns stored data."""
        memory_cache.set("key1", "compile", {"result": "data"})

        result = memory_cache.get("key1", "compile")

        assert result == {"result": "data"}

    def test_set_populates_memory(self, memory_cache):
        """Set stores in memory for fast subsequent gets."""
        memory_cache.set("key1", "compile", {"data": 1})

        assert memory_cache.get("key1", "compile") == {"data": 1}
        assert memory_cache.current_key == "key1"

    def test_multiple_operations_same_key(self, memory_cache):
        """Can store compile and execute for same key."""
        memory_cache.set("key1", "compile", {"compile": "result"})
        memory_cache.set("key1", "execute", {"execute": "result"})

        assert memory_cache.get("key1", "compile") == {"compile": "result"}
        assert memory_cache.get("key1", "execute") == {"execute": "result"}

    def test_key_change_clears_all_operations(self, memory_cache):
        """Setting different key clears all previous operations."""
        memory_cache.set("key1", "compile", {"compile": "result"})
        memory_cache.set("key1", "execute", {"execute": "result"})

        # Switch to different key
        memory_cache.set("key2", "compile", {"new": "data"})

        # Old key operations should be gone
        assert memory_cache.get("key1", "compile") is None
        assert memory_cache.get("key1", "execute") is None
        # New key should work
        assert memory_cache.get("key2", "compile") == {"new": "data"}

    def test_get_different_key_returns_none(self, memory_cache):
        """Getting with different key returns None (no implicit switch)."""
        memory_cache.set("key1", "compile", {"data": 1})

        # Getting a different key should return None, not switch
        assert memory_cache.get("key2", "compile") is None
        # Original key should still work
        assert memory_cache.get("key1", "compile") == {"data": 1}

    def test_operations_isolated_within_key(self, memory_cache):
        """compile and execute are separate entries for same key."""
        memory_cache.set("key1", "compile", {"type": "compile"})
        memory_cache.set("key1", "execute", {"type": "execute"})

        assert memory_cache.get("key1", "compile") == {"type": "compile"}
        assert memory_cache.get("key1", "execute") == {"type": "execute"}
        assert memory_cache.get("key1", "other") is None

    def test_invalidate_removes_specific_operation(self, memory_cache):
        """Invalidate removes one operation, keeps others."""
        memory_cache.set("key1", "compile", {"compile": "data"})
        memory_cache.set("key1", "execute", {"execute": "data"})

        memory_cache.invalidate("key1", "compile")

        assert memory_cache.get("key1", "compile") is None
        assert memory_cache.get("key1", "execute") == {"execute": "data"}

    def test_invalidate_different_key_no_effect(self, memory_cache):
        """Invalidate with different key leaves entries intact."""
        memory_cache.set("key1", "compile", {"data": 1})

        memory_cache.invalidate("key2", "compile")

        assert memory_cache.get("key1", "compile") == {"data": 1}

    def test_clear_empties_all(self, memory_cache):
        """Clear removes current key and all operations."""
        memory_cache.set("key1", "compile", {"compile": "data"})
        memory_cache.set("key1", "execute", {"execute": "data"})

        memory_cache.clear()

        assert memory_cache.current_key is None
        assert memory_cache.get("key1", "compile") is None
        assert memory_cache.get("key1", "execute") is None

    def test_current_key_property(self, memory_cache):
        """current_key returns the active key for debugging."""
        assert memory_cache.current_key is None

        memory_cache.set("my_key", "compile", {"data": 1})

        assert memory_cache.current_key == "my_key"

    def test_has_operation(self, memory_cache):
        """has_operation checks if operation exists for current key."""
        memory_cache.set("key1", "compile", {"data": 1})

        assert memory_cache.has_operation("compile") is True
        assert memory_cache.has_operation("execute") is False


# ============================================================================
# Cache Service Core Tests
# ============================================================================


class TestCacheServiceCore:
    """Tests for the two-tier cache service."""

    def test_get_nonexistent_returns_none(self, test_cache):
        """Getting non-existent key returns None."""
        result = test_cache.get("nonexistent", "compile")

        assert result is None

    def test_set_and_get_roundtrip(self, test_cache):
        """Set data, then get returns same data."""
        data = {"nodes": [1, 2, 3], "edges": []}
        test_cache.set("key1", "compile", data)

        result = test_cache.get("key1", "compile")

        assert result == data

    def test_set_overwrites_existing(self, test_cache):
        """Setting same key twice overwrites previous value."""
        test_cache.set("key1", "compile", {"version": 1})
        test_cache.set("key1", "compile", {"version": 2})

        result = test_cache.get("key1", "compile")

        assert result == {"version": 2}

    def test_get_different_operations_isolated(self, test_cache):
        """Same key with 'compile' vs 'execute' are separate entries."""
        test_cache.set("key1", "compile", {"type": "compile"})
        test_cache.set("key1", "execute", {"type": "execute"})

        assert test_cache.get("key1", "compile") == {"type": "compile"}
        assert test_cache.get("key1", "execute") == {"type": "execute"}

    def test_invalidate_removes_entry(self, test_cache):
        """Invalidate removes specific key+operation."""
        test_cache.set("key1", "compile", {"data": 1})
        test_cache.set("key1", "execute", {"data": 2})

        test_cache.invalidate("key1", "compile")

        assert test_cache.get("key1", "compile") is None
        assert test_cache.get("key1", "execute") == {"data": 2}

    def test_invalidate_nonexistent_no_error(self, test_cache):
        """Invalidating non-existent key doesn't raise."""
        # Should not raise
        test_cache.invalidate("nonexistent", "compile")

    def test_clear_removes_all_entries(self, test_cache):
        """Clear removes all cached data."""
        test_cache.set("key1", "compile", {"data": 1})
        test_cache.set("key2", "execute", {"data": 2})

        test_cache.clear()

        assert test_cache.get("key1", "compile") is None
        assert test_cache.get("key2", "execute") is None

    def test_clear_empty_cache_no_error(self, test_cache):
        """Clearing empty cache doesn't raise."""
        # Should not raise
        test_cache.clear()

    def test_memory_populated_on_file_hit(self, test_cache):
        """File hit populates memory for subsequent access."""
        # Write to cache
        test_cache.set("key1", "compile", {"data": 1})

        # Clear memory only (simulates restart)
        test_cache.memory_cache.clear()

        # First get should read from file and populate memory
        result1 = test_cache.get("key1", "compile")
        assert result1 == {"data": 1}

        # Memory should now be populated
        assert test_cache.memory_cache.get("key1", "compile") == {"data": 1}


# ============================================================================
# Cache File Structure Tests
# ============================================================================


class TestCacheFileStructure:
    """Tests for file storage structure."""

    def test_creates_operation_subdirectories(self, test_cache):
        """Setting creates compile/ or execute/ subdirectory."""
        test_cache.set("key1", "compile", {"data": 1})
        test_cache.set("key2", "execute", {"data": 2})

        compile_dir = test_cache.cache_dir / "compile"
        execute_dir = test_cache.cache_dir / "execute"

        assert compile_dir.is_dir()
        assert execute_dir.is_dir()

    def test_cache_entry_is_valid_json(self, test_cache):
        """Stored file is valid JSON with expected structure."""
        test_cache.set("key1", "compile", {"test": "data"})

        file_path = test_cache.cache_dir / "compile" / "key1.json"
        assert file_path.is_file()

        with open(file_path, "r") as f:
            entry = json.load(f)

        assert "created_at" in entry
        assert "data" in entry
        assert entry["data"] == {"test": "data"}
        assert isinstance(entry["created_at"], float)

    def test_handles_special_characters_in_data(self, test_cache):
        """Can cache data with unicode, newlines, etc."""
        data = {
            "unicode": "Hello \u4e16\u754c",
            "newlines": "line1\nline2",
            "quotes": 'He said "hello"',
        }
        test_cache.set("key1", "compile", data)

        result = test_cache.get("key1", "compile")

        assert result == data


# ============================================================================
# Cache Error Handling Tests
# ============================================================================


class TestCacheErrorHandling:
    """Tests for error handling and graceful degradation."""

    def test_get_corrupted_file_returns_none(self, test_cache):
        """Corrupted JSON file returns None (graceful degradation)."""
        # Create a corrupted cache file
        compile_dir = test_cache.cache_dir / "compile"
        compile_dir.mkdir(parents=True, exist_ok=True)
        corrupted_file = compile_dir / "corrupted.json"
        corrupted_file.write_text("not valid json {{{")

        # Should return None, not raise
        result = test_cache.get("corrupted", "compile")

        assert result is None

    def test_set_readonly_dir_no_crash(self, test_cache, tmp_path):
        """Writing to readonly dir doesn't crash (logs warning)."""
        # Create a readonly cache
        readonly_dir = tmp_path / "readonly_cache"
        readonly_dir.mkdir()
        readonly_cache = CacheService(cache_dir=readonly_dir)

        # Make it readonly
        readonly_dir.chmod(0o444)

        try:
            # Should not crash, just log warning
            readonly_cache.set("key1", "compile", {"data": 1})
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_concurrent_writes_safe(self, test_cache):
        """Multiple threads writing same key doesn't corrupt."""
        errors = []

        def write_data(thread_id):
            try:
                for i in range(10):
                    test_cache.set(f"key_{thread_id}", "compile", {"thread": thread_id, "iteration": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_data, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # All keys should be readable
        for i in range(5):
            result = test_cache.get(f"key_{i}", "compile")
            assert result is not None
            assert result["thread"] == i
