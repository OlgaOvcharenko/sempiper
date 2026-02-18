# Demo inspired by sempipes notebooks

**Always apply this rule**

Our web demo is inspired by the sempipes notebook demos (read-only reference).

The **sempipes** repository (linked via `sempipes/` in this project) contains **notebook demos** that run real pipelines:

- **`sempipes/demo.ipynb`** — main demo: skrub datasets, `sempipes.as_X` / `as_y`, `sem_fillna`, `sem_gen_features`, `skb.apply`, `skb.apply_with_sem_choose`, `sem_choose`. Output shows a **computation graph** ("Show graph") and **result on a subsample**.
- **`sempipes/demo__sem_fillna.ipynb`**, **`demo__sem_select.ipynb`**, **`demo__optimise_semantic_operator.ipynb`**, **`demo_sem_augment.ipynb`**, etc. — other demos for specific semantic operators.

## How we use this (read-only)

- **Do not edit** anything under `sempipes/` (see `no-edit-sempipes.md`).
- Use these notebooks as **inspiration** for the **web demo** in `demo/`:
  - **Pipeline vocabulary**: prefer notebook-style APIs in default examples and in compile parsing — e.g. `as_X`, `as_y`, `sem_fillna`, `sem_gen_features`, `skb.apply`, `apply_with_sem_choose`, `sem_choose`.
  - **Graph semantics**: the middle panel's "compiled graph" should reflect the same kind of steps as the notebook's computation graph (inputs, semantic operators, apply steps).
  - **Right panel**: node details can mirror what the notebook shows per step (data summary, generated code, LLM/prompt stats).

When adding or changing demo behaviour, consider how the sempipes notebooks structure pipelines and display results, and align the web demo experience with that where it makes sense.
