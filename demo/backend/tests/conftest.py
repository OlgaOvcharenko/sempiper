"""
Pytest configuration and fixtures for the demo backend.

Test strategy: keep tests close to sempipes (e.g. call sempipes code paths)
but NEVER call real LLMs. We simulate correct behaviour via mocks so tests
run fast and without API keys or network.

- This conftest patches litellm.completion / batch_completion when available
  so any code path that reaches litellm gets a fake response.
- Tests that invoke the execute stream (POST /api/execute) explicitly mock
  the code-generation entry point so we never call sempipes LLM; see
  test_codegen.py (patch of execute_stream._generate_code_via_sempipes).
- Tests that use sempipes code generation directly (e.g. test_sempipes_code_
  generation_uses_mock_no_llm_call) patch sempipes.llm.llm._generate_code_
  from_messages so the LLM returns fixed code without hitting the network.
"""

import pytest


def _mock_completion(*args, **kwargs):
    """Fake litellm.completion response so no real LLM is called."""

    class Choice:
        class Message:
            content = "def __mock__(): pass"

        message = Message()

    class Response:
        choices = [Choice()]

    return Response()


def _mock_batch_completion(*args, messages=None, **kwargs):
    """Fake litellm.batch_completion response so no real LLM is called."""
    n = len(messages) if messages else 1

    class Choice:
        class Message:
            content = "{}"

        message = Message()

    return [type("Response", (), {"choices": [Choice()]})() for _ in range(n)]


@pytest.fixture(autouse=True)
def mock_litellm_if_available(monkeypatch):
    """
    If litellm is importable, patch completion and batch_completion so no
    real LLM is called. Tests that use sempipes code generation should also
    patch sempipes.llm.llm._generate_code_from_messages (see test_codegen).
    """
    try:
        import litellm

        monkeypatch.setattr(litellm, "completion", _mock_completion)
        monkeypatch.setattr(litellm, "batch_completion", _mock_batch_completion)
    except ImportError:
        pass
    yield
