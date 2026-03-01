# Compile Graph is Canonical — Never Replace with Runtime Skrub Graph

**Always apply this rule**

The middle panel shows the **compile-time graph** (from `/api/compile`). This graph must
**never** be replaced or overwritten by data received during or after pipeline execution.

## Rule

- The **compile graph** (`compileNodes` / `compileEdges`) is the single source of truth for
  the graph visualisation.
- **Execution must not change the graph.** The graph only updates when the **pipeline code
  changes** (which triggers a new compile).
- `skrubGraphFromRun` (the runtime skrub DAG returned in the `skrub_graph` SSE event) must
  **not** be used as `displayGraph`. It was removed from both `CodeGenDemo.tsx` and
  `OptimizerDemo.tsx`. Do not re-introduce it.

## Correct pattern (both CodeGenDemo and OptimizerDemo)

```ts
// ✅ Always use the compile graph
const compilePreviewGraph = compileToSkrubGraph(compileNodes, compileEdges ?? []);
const displayGraph = compilePreviewGraph;
const isPreviewGraph = !!compilePreviewGraph?.nodes?.length;
```

## Wrong pattern — do not use

```ts
// ❌ This replaces the compile graph with the runtime skrub graph after execution
const displayGraph = skrubGraphFromRun ?? compilePreviewGraph;
```

## What the `skrub_graph` SSE event is allowed to do

The `skrub_graph` event arrives during execution and contains:
- `graph` — the runtime skrub DAG (integer node IDs: `"0"`, `"1"`, …) — **ignore for display**
- `skrubToCompileId` — mapping from skrub integer IDs to compile IDs — **store for node
  selection fallback** via `setSkrubToCompileId`

The handler must **only** update `skrubToCompileId`, never call `setSkrubGraphFromRun` or
use the runtime graph as a display graph.

## Node ID convention

In the compile preview graph (from `compileToSkrubGraph`), graph node IDs equal compile node
IDs (e.g. `"as_X_1"`, `"sem_fillna_2"`). The display layer prefixes them with `skrub_` for
Cytoscape (e.g. `"skrub_as_X_1"`). This means `graphNodeToCompileIds` step 2 (direct ID
match) always resolves graph-node → compile-node without needing `skrubToCompileId`, and
`compileIdsToSkrubIds` must be called with `isPostRun = false`.

## Files

| File | Key lines |
|------|-----------|
| `demo/frontend/src/components/CodeGenDemo.tsx` | `displayGraph = compilePreviewGraph` |
| `demo/frontend/src/components/OptimizerDemo.tsx` | `displayGraph = compilePreviewGraph` |
| `demo/frontend/src/api/client.ts` | `compileToSkrubGraph()` converter |
| `demo/frontend/src/utils/graphCodeSync.ts` | `compileIdsToSkrubIds(…, false)` |
