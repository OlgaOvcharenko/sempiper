import pytest


def test_semantic_label_detects_apply_with_sem_choose_estimator():
    from services.skrub_graph_runner import _apply_label_to_sempipes_operator, _is_sempipes_semantic_label

    runtime_label = "<Apply HistGradientBoostingClassifier>"
    assert _is_sempipes_semantic_label(runtime_label) is True
    assert _apply_label_to_sempipes_operator(runtime_label) == "apply_with_sem_choose"


def test_semantic_label_does_not_treat_store_sem_choices_as_extra_slot():
    """
    `compile_script_to_graph_dynamic(medium.py)` fuses `sem_choose` into
    `apply_with_sem_choose` (so we expect only one semantic slot for that part).
    The runtime node `<Call 'store_sem_choices'>` should not become a separate
    semantic slot; otherwise we risk semantic-slot/code-capture count mismatch.
    """
    from services.skrub_graph_runner import _is_sempipes_semantic_label

    runtime_label = "<Call 'store_sem_choices'>"
    assert _is_sempipes_semantic_label(runtime_label) is False

