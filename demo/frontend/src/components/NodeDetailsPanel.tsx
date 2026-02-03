/**
 * Right panel: contextual content for the selected graph node.
 * - Input nodes: data summary (schema, sample, stats).
 * - Sempipes/operator nodes: generated code, LLM prompt stats, etc.
 */
import type { InputSummary } from "../api/client";
import type { GraphNode } from "./GraphPanel";
import { CodeOutput } from "./CodeOutput";

function InputSummaryView({ summary }: { summary: InputSummary }) {
  const { schema, sample, row_count } = summary;
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs text-zinc-500 mb-1">Rows: {row_count.toLocaleString()}</p>
      </div>
      <div>
        <p className="text-xs font-medium text-zinc-600 mb-1">Schema</p>
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-xs text-zinc-700">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left py-1.5 px-2 font-medium">Column</th>
                <th className="text-left py-1.5 px-2 font-medium">dtype</th>
              </tr>
            </thead>
            <tbody>
              {schema.map((col) => (
                <tr key={col.name} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5 px-2 font-mono">{col.name}</td>
                  <td className="py-1.5 px-2 text-zinc-500">{col.dtype}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <p className="text-xs font-medium text-zinc-600 mb-1">Sample (first {sample.length} rows)</p>
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-xs text-zinc-700">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                {schema.map((col) => (
                  <th key={col.name} className="text-left py-1.5 px-2 font-medium">
                    {col.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sample.map((row, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  {schema.map((col) => (
                    <td key={col.name} className="py-1.5 px-2 font-mono">
                      {String(row[col.name] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

interface NodeDetailsPanelProps {
  selectedNodeId: string | null;
  selectedNode: GraphNode | null;
  /** When we have backend: generated code for operator nodes. */
  generatedCode?: string | null;
  /** Live-updating generated code per node during/after execution (node_id → code). */
  liveGeneratedCodeByNode?: Record<string, string> | null;
  /** Per-node retries from last run (node_id → retry count). */
  liveRetriesByNode?: Record<string, number> | null;
  /** Per-node fallback flag: true when backend used placeholder (LLM unavailable or failed). */
  liveFallbackByNode?: Record<string, boolean> | null;
  /** Per-node LLM cost in USD from last run (node_id → cost). */
  liveCostUsdByNode?: Record<string, number> | null;
  /** Per-node input summary (schema, sample, row_count) from last run (node_id → summary). */
  inputSummaryByNode?: Record<string, InputSummary> | null;
  /** Whether pipeline is currently executing (so we show "Generating..." until code arrives). */
  isExecuting?: boolean;
  /** When we have backend: metadata / LLM stats for the node. */
  nodeMetadata?: Record<string, unknown> | null;
  /** Optional expand button element to render in the header. */
  expandButton?: React.ReactNode;
  /** Whether the panel is expanded (controls word wrap). */
  isExpanded?: boolean;
}

export function NodeDetailsPanel({
  selectedNodeId,
  selectedNode,
  generatedCode = null,
  liveGeneratedCodeByNode,
  liveRetriesByNode,
  liveFallbackByNode = null,
  liveCostUsdByNode,
  inputSummaryByNode,
  isExecuting = false,
  nodeMetadata = null,
  expandButton = null,
  isExpanded = false,
}: NodeDetailsPanelProps) {
  const liveMap = liveGeneratedCodeByNode ?? {};
  const liveCodeForNode =
    selectedNodeId && typeof liveMap[selectedNodeId] === "string"
      ? liveMap[selectedNodeId]
      : undefined;
  const effectiveCode =
    liveCodeForNode !== undefined ? liveCodeForNode : (!isExecuting ? generatedCode ?? null : null);
  const isLive = liveCodeForNode !== undefined;
  const waitingForCode = isExecuting && selectedNode?.type === "operator" && liveCodeForNode === undefined;
  const hasCodeToShow = (effectiveCode != null && effectiveCode !== "") || waitingForCode;
  if (!selectedNodeId || !selectedNode) {
    return (
      <div className="h-full flex flex-col rounded-lg border border-slate-300 bg-white overflow-hidden shadow-md">
        <div className="shrink-0 px-3 py-2 border-b border-slate-300 bg-slate-100 flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-700">Node details</h2>
          {expandButton}
        </div>
        <div className="flex-1 flex items-center justify-center p-6 text-zinc-500 text-sm text-center">
          Select a node in the graph to see its data summary, generated code, or LLM stats.
        </div>
      </div>
    );
  }

  const isInput = selectedNode.type === "input";

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-300 bg-white overflow-hidden shadow-md">
      <div className="shrink-0 px-3 py-2 border-b border-slate-300 bg-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-zinc-700">Node details</h2>
          <p className="text-xs text-zinc-500 mt-0.5">
            {selectedNode.label} <span className="text-zinc-500">({selectedNode.type})</span>
          </p>
        </div>
        {expandButton}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
        {isInput ? (
          <>
            <section>
              <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Data summary</h3>
              {selectedNodeId && inputSummaryByNode?.[selectedNodeId] ? (
                <InputSummaryView summary={inputSummaryByNode[selectedNodeId]} />
              ) : isExecuting ? (
                <p className="text-sm text-zinc-500 italic py-3">
                  Running pipeline… data summary will appear when this input is processed.
                </p>
              ) : (
                <p className="text-sm text-zinc-500 italic py-3">
                  Run the pipeline to see schema, sample rows, and row count for this input.
                </p>
              )}
            </section>
          </>
        ) : (
          <>
            <section key={`generated-code-${selectedNodeId}`}>
              <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                Generated code
                {isLive && <span className="ml-2 text-emerald-600 font-normal">(live)</span>}
              </h3>
              {waitingForCode ? (
                <CodeOutput code="" language="python" isLoading={true} isExpanded={isExpanded} />
              ) : hasCodeToShow ? (
                <CodeOutput code={effectiveCode || ""} language="python" isLoading={false} isExpanded={isExpanded} />
              ) : (
                <p className="text-sm text-zinc-500 italic py-3">
                  No generated code for this node. Run the pipeline to generate.
                </p>
              )}
            </section>
            <section>
              <h3 className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
                LLM / prompt stats
              </h3>
              {liveFallbackByNode?.[selectedNodeId] === true && (
                <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-2">
                  Placeholder code shown above (LLM unavailable or failed). Configure sempipes with an API key for real generated code.
                </p>
              )}
              {(liveRetriesByNode?.[selectedNodeId] != null ||
                (liveCostUsdByNode?.[selectedNodeId] != null &&
                  liveCostUsdByNode[selectedNodeId] > 0)) && (
                <div className="flex flex-wrap gap-3 text-sm text-zinc-600 mb-2">
                  {liveRetriesByNode?.[selectedNodeId] != null && (
                    <span title={liveFallbackByNode?.[selectedNodeId] ? "Attempts before falling back to placeholder" : "Number of retries used for this node"}>
                      Retries: {liveRetriesByNode[selectedNodeId]}
                      {liveFallbackByNode?.[selectedNodeId] && " (LLM failed, placeholder shown)"}
                    </span>
                  )}
                  {liveCostUsdByNode?.[selectedNodeId] != null &&
                    liveCostUsdByNode[selectedNodeId] > 0 && (
                      <span title="LLM cost for this node (USD)">
                        Cost: ${liveCostUsdByNode[selectedNodeId].toFixed(6)}
                      </span>
                    )}
                </div>
              )}
              {liveFallbackByNode?.[selectedNodeId] !== true && (
                <p className="text-sm text-zinc-600">
                  Prompt statistics and node-specific metadata will appear here when available.
                </p>
              )}
              {nodeMetadata && Object.keys(nodeMetadata).length > 0 && (
                <pre className="text-xs bg-slate-100 rounded p-3 mt-2 overflow-x-auto text-zinc-700 font-mono border border-slate-200">
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
