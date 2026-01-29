/**
 * Right panel: contextual content for the selected graph node.
 * - Input nodes: data summary (schema, sample, stats).
 * - Sempipes/operator nodes: generated code, LLM prompt stats, etc.
 */
import type { GraphNode } from "./GraphPanel";

interface NodeDetailsPanelProps {
  selectedNodeId: string | null;
  selectedNode: GraphNode | null;
  /** When we have backend: generated code for operator nodes. */
  generatedCode?: string | null;
  /** When we have backend: metadata / LLM stats for the node. */
  nodeMetadata?: Record<string, unknown> | null;
}

export function NodeDetailsPanel({
  selectedNodeId,
  selectedNode,
  generatedCode = null,
  nodeMetadata = null,
}: NodeDetailsPanelProps) {
  if (!selectedNodeId || !selectedNode) {
    return (
      <div className="h-full flex flex-col rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
        <div className="shrink-0 px-3 py-2 border-b border-zinc-800">
          <h2 className="text-sm font-medium text-zinc-300">Node details</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-6 text-zinc-500 text-sm text-center">
          Select a node in the graph to see its data summary, generated code, or LLM stats.
        </div>
      </div>
    );
  }

  const isInput = selectedNode.type === "input";

  return (
    <div className="h-full flex flex-col rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-300">Node details</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          {selectedNode.label} <span className="text-zinc-600">({selectedNode.type})</span>
        </p>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
        {isInput ? (
          <>
            <section>
              <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Data summary</h3>
              <p className="text-sm text-zinc-400">
                Schema, sample rows, and stats for this input will appear here once wired to the
                backend.
              </p>
            </section>
          </>
        ) : (
          <>
            {generatedCode && (
              <section>
                <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                  Generated code
                </h3>
                <pre className="text-xs bg-zinc-800 rounded p-3 overflow-x-auto text-zinc-300 font-mono whitespace-pre-wrap border border-zinc-700/50">
                  {generatedCode}
                </pre>
              </section>
            )}
            <section>
              <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                LLM / prompt stats
              </h3>
              <p className="text-sm text-zinc-400">
                Prompt statistics and node-specific metadata will appear here when available.
              </p>
              {nodeMetadata && Object.keys(nodeMetadata).length > 0 && (
                <pre className="text-xs bg-zinc-800 rounded p-3 mt-2 overflow-x-auto text-zinc-300 font-mono border border-zinc-700/50">
                  {JSON.stringify(nodeMetadata, null, 2)}
                </pre>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
