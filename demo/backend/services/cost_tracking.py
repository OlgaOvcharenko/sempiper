"""
Track LLM costs from litellm completion and batch_completion calls.
Uses the same monkey-patching approach as sempipes/experiments/feature_extraction
(audio_env50/sempipes_audio_extraction_llm.py, text_legal/sempipes_text_extraction.py).
"""
from contextlib import contextmanager
from typing import Generator


@contextmanager
def track_llm_cost() -> Generator[list[float], None, None]:
    """
    Context manager to track costs from litellm completion and batch_completion
    during pipeline execution. Patches sempipes.llm.llm so all LLM calls accumulate cost.
    Yields a list that is appended to on each call (batch_completion: one value per batch;
    completion: one value per call).
    """
    costs: list[float] = []

    try:
        from litellm import completion_cost
    except ImportError:
        yield costs
        return

    try:
        import sempipes.llm.llm as llm_module
    except ImportError:
        yield costs
        return

    from litellm import batch_completion as original_batch_completion
    from litellm import completion as original_completion

    def tracked_completion(*args, **kwargs):
        response = original_completion(*args, **kwargs)
        try:
            c = completion_cost(completion_response=response)
            if c is not None:
                costs.append(float(c))
        except Exception:
            pass
        return response

    def tracked_batch_completion(*args, **kwargs):
        responses = original_batch_completion(*args, **kwargs)
        try:
            batch_total = 0.0
            for resp in responses:
                c = completion_cost(completion_response=resp)
                if c is not None:
                    batch_total += float(c)
            if batch_total > 0:
                costs.append(batch_total)
        except Exception:
            pass
        return responses

    orig_completion = llm_module.completion
    orig_batch = llm_module.batch_completion
    llm_module.completion = tracked_completion
    llm_module.batch_completion = tracked_batch_completion
    try:
        yield costs
    finally:
        llm_module.completion = orig_completion
        llm_module.batch_completion = orig_batch
