/**
 * Right panel: contextual content for the selected graph node.
 * - Input nodes: data summary (schema, sample, stats).
 * - Sempipes/operator nodes: generated code, LLM prompt stats, etc.
 * - From compile: code location, data flow (upstream/downstream), validation, timings.
 */
import type { CompileNode, InputSummary } from "../api/client";
import type { GraphNode } from "./GraphPanel";
import { CodeOutput } from "./CodeOutput";

function InputSummaryView({ summary }: { summary: InputSummary }) {
  const { schema, sample, row_count } = summary;
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">Rows: {row_count.toLocaleString()}</p>
      </div>
      <div>
        <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Schema</p>
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-zinc-700">
          <table className="min-w-full text-xs text-zinc-700 dark:text-zinc-300">
            <thead>
              <tr className="bg-slate-50 dark:bg-zinc-800 border-b border-slate-200 dark:border-zinc-700">
                <th className="text-left py-1.5 px-2 font-medium">Column</th>
                <th className="text-left py-1.5 px-2 font-medium">dtype</th>
              </tr>
            </thead>
            <tbody>
              {schema.map((col) => (
                <tr key={col.name} className="border-b border-slate-100 dark:border-zinc-700 last:border-0">
                  <td className="py-1.5 px-2 font-mono">{col.name}</td>
                  <td className="py-1.5 px-2 text-zinc-500 dark:text-zinc-400">{col.dtype}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Sample (first {sample.length} rows)</p>
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-zinc-700">
          <table className="min-w-full text-xs text-zinc-700 dark:text-zinc-300">
            <thead>
              <tr className="bg-slate-50 dark:bg-zinc-800 border-b border-slate-200 dark:border-zinc-700">
                {schema.map((col) => (
                  <th key={col.name} className="text-left py-1.5 px-2 font-medium">
                    {col.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sample.map((row, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-zinc-700 last:border-0">
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
  /** Per-node LLM attempts from last run (node_id → attempt count). */
  liveRetriesByNode?: Record<string, number> | null;
  /** Per-node fallback flag: true when backend used placeholder (LLM unavailable or failed). */
  liveFallbackByNode?: Record<string, boolean> | null;
  /** Per-node LLM cost in USD from last run (node_id → cost). */
  liveCostUsdByNode?: Record<string, number> | null;
  /** Per-node input summary (schema, sample, row_count) from last run (node_id → summary). */
  inputSummaryByNode?: Record<string, InputSummary> | null;
  /** Resolved input summary for selected node (used when selected is skrub input; CodeGenDemo maps skrub_0 → compile node → summary). */
  inputSummaryForSelectedNode?: InputSummary | null;
  /** Per-node intermediate data (schema, sample, row_count) from .skb.preview() (node_id → data). */
  nodeDataByNode?: Record<string, InputSummary> | null;
  /** Whether pipeline is currently executing (so we show "Generating..." until code arrives). */
  isExecuting?: boolean;
  /** When we have backend: metadata / LLM stats for the node. */
  nodeMetadata?: Record<string, unknown> | null;
  /** Optional expand button element to render in the header. */
  expandButton?: React.ReactNode;
  /** Whether the panel is expanded (controls word wrap). */
  isExpanded?: boolean;
  /** Mapping from skrub runtime IDs to compile IDs (for dynamic compilation). */
  skrubToCompileId?: Record<string, string>;
  /** Dark mode flag */
  isDark?: boolean;
  /** Compile node for the selected graph node (id, type, label, source_range). */
  compileNode?: CompileNode | null;
  /** Labels of nodes that feed into this one (upstream / depends on). */
  upstreamNodeLabels?: string[];
  /** Labels of nodes this one feeds into (downstream). */
  downstreamNodeLabels?: string[];
  /** Graph validation errors from the last compile. */
  compileValidationErrors?: string[];
  /** Compile timing breakdown (ms) when available. */
  compileTimingsMs?: Record<string, number> | null;
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
  inputSummaryForSelectedNode,
  nodeDataByNode,
  isExecuting = false,
  nodeMetadata = null,
  expandButton = null,
  isExpanded = false,
  skrubToCompileId = {},
  compileNode = null,
  upstreamNodeLabels = [],
  downstreamNodeLabels = [],
  compileValidationErrors = [],
  compileTimingsMs = null,
}: NodeDetailsPanelProps) {
  if (!selectedNodeId || !selectedNode) {
    return (
      <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
        <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Node details</h2>
          {expandButton}
        </div>
        <div className="flex-1 flex items-center justify-center p-6 text-zinc-500 dark:text-zinc-400 text-sm text-center">
          Select a node in the graph to see its data summary, generated code, or LLM stats.
        </div>
      </div>
    );
  }

  // Graph node id = compile node id (display graph is from compile). Use that for run-data lookups.
  const rawNodeId = selectedNodeId.startsWith("skrub_") ? selectedNodeId.slice(6) : selectedNodeId;
  const compileId = compileNode?.id ?? (rawNodeId ? skrubToCompileId[rawNodeId] : undefined) ?? rawNodeId;

  // Direct lookups trying all ID formats
  const liveMap = liveGeneratedCodeByNode ?? {};
  const liveCodeForNode = liveMap[selectedNodeId] ||
    liveMap[rawNodeId] ||
    (compileId && liveMap[compileId]) ||
    (compileId && liveMap[`skrub_${compileId}`]) ||
    undefined;
  const effectiveCode =
    liveCodeForNode !== undefined ? liveCodeForNode : (!isExecuting ? generatedCode ?? null : null);
  const isLive = liveCodeForNode !== undefined;
  const hasGeneratedCodeSectionFlag = compileNode?.is_sempipes_semantic === true;
  const labelLooksSempipes =
    (compileNode?.label ?? selectedNode?.label ?? "").toLowerCase().match(/^sem_|^apply_with_sem_choose$|^sem_choose$/);
  const isInput = (compileNode?.type ?? selectedNode.type) === "input";
  // Show generated code for sempipes semantic operators: backend flag, or operator with sempipes-style label
  const hasGeneratedCodeSection =
    hasGeneratedCodeSectionFlag ||
    (selectedNode.type === "operator" && (compileNode == null || !!labelLooksSempipes));
  const waitingForCode = isExecuting && hasGeneratedCodeSection && liveCodeForNode === undefined;
  const hasCodeToShow = (effectiveCode != null && effectiveCode !== "") || waitingForCode;

  // Look up other per-node data using all ID formats (including compile ID from mapping)
  const retriesMap = liveRetriesByNode ?? {};
  const nodeRetries = retriesMap[selectedNodeId] ?? retriesMap[rawNodeId] ??
    (compileId && retriesMap[compileId]) ??
    (compileId && retriesMap[`skrub_${compileId}`]) ?? undefined;

  const fallbackMap = liveFallbackByNode ?? {};
  const nodeFallback = fallbackMap[selectedNodeId] ?? fallbackMap[rawNodeId] ??
    (compileId && fallbackMap[compileId]) ??
    (compileId && fallbackMap[`skrub_${compileId}`]) ?? undefined;

  const costMap = liveCostUsdByNode ?? {};
  const nodeCostUsd = costMap[selectedNodeId] ?? costMap[rawNodeId] ??
    (compileId && costMap[compileId]) ??
    (compileId && costMap[`skrub_${compileId}`]) ?? undefined;

  const dataMap = nodeDataByNode ?? {};
  // Reverse lookup: data may be stored under skrub_X where mapping[X] === compileId (e.g. cache replay or event order)
  const nodeDataFromReverse =
    compileId && skrubToCompileId && Object.keys(skrubToCompileId).length > 0
      ? (() => {
          for (const key of Object.keys(dataMap)) {
            if (key.startsWith("skrub_")) {
              const skid = key.slice(6);
              if (skrubToCompileId[skid] === compileId) return dataMap[key];
            }
          }
          return undefined;
        })()
      : undefined;
  const nodeData =
    dataMap[selectedNodeId] ||
    dataMap[rawNodeId] ||
    (compileId && dataMap[compileId]) ||
    (compileId && dataMap[`skrub_${compileId}`]) ||
    nodeDataFromReverse ||
    undefined;

  const summaryMap = inputSummaryByNode ?? {};
  const inputSummary = inputSummaryForSelectedNode ??
    summaryMap[selectedNodeId] ?? summaryMap[rawNodeId] ??
    (compileId && summaryMap[compileId]) ??
    (compileId && summaryMap[`skrub_${compileId}`]) ?? undefined;
  // For "Output data (preview)", prefer node_data; fall back to input_summary so input nodes and nodes with summary show data
  const outputPreviewData = nodeData ?? inputSummary;

  const hasCompileDetails =
    compileNode != null ||
    (compileNode?.source_range != null) ||
    upstreamNodeLabels.length > 0 ||
    downstreamNodeLabels.length > 0 ||
    compileValidationErrors.length > 0 ||
    (compileTimingsMs != null && Object.keys(compileTimingsMs).length > 0);

  const hasIdMapping =
    selectedNodeId != null &&
    selectedNodeId.startsWith("skrub_") &&
    compileId != null &&
    rawNodeId !== compileId;

  const formatSourceRange = (r: NonNullable<CompileNode["source_range"]>) => {
    if (r.start_line === r.end_line) {
      return r.start_column === r.end_column
        ? `Line ${r.start_line}`
        : `Line ${r.start_line}, columns ${r.start_column}–${r.end_column}`;
    }
    return `Lines ${r.start_line}–${r.end_line}`;
  };

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
      <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Node details</h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            {selectedNode.label} <span className="text-zinc-500 dark:text-zinc-400">({selectedNode.type})</span>
          </p>
        </div>
        {expandButton}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
        {isInput ? (
          <>
            <section>
              <h3 className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">Data summary</h3>
              {inputSummary ? (
                <InputSummaryView summary={inputSummary} />
              ) : isExecuting ? (
                <p className="text-sm text-zinc-500 dark:text-zinc-400 italic py-3">
                  Running pipeline… data summary will appear when this input is processed.
                </p>
              ) : (
                <p className="text-sm text-zinc-500 dark:text-zinc-400 italic py-3">
                  Run the pipeline to see schema, sample rows, and row count for this input.
                </p>
              )}
            </section>
          </>
        ) : (
          <>
            {hasGeneratedCodeSection && (
              <>
                <section key={`generated-code-${selectedNodeId}`}>
                  <h3 className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
                    Generated code
                    {isLive && <span className="ml-2 text-emerald-600 dark:text-emerald-400 font-normal">(live)</span>}
                  </h3>
                  {waitingForCode ? (
                    <CodeOutput code="" language="python" isLoading={true} isExpanded={isExpanded} />
                  ) : hasCodeToShow ? (
                    <CodeOutput code={effectiveCode || ""} language="python" isLoading={false} isExpanded={isExpanded} />
                  ) : (
                    <p className="text-sm text-zinc-500 dark:text-zinc-400 italic py-3">
                      No generated code for this sempipes operator. Run the pipeline to generate code for each operator.
                    </p>
                  )}
                </section>
                <section>
                  <h3 className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
                    LLM / prompt stats
                  </h3>
                  {nodeFallback === true && (
                    <p className="text-sm text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 rounded px-3 py-2 mb-2">
                      Placeholder code shown above (LLM unavailable or failed). Configure sempipes with an API key for real generated code.
                    </p>
                  )}
                  {(nodeRetries != null || (nodeCostUsd != null && nodeCostUsd > 0)) && (
                    <div className="flex flex-wrap gap-3 text-sm text-zinc-600 dark:text-zinc-300 mb-2">
                      {nodeRetries != null && (
                        <span title={nodeFallback ? "Attempts before falling back to placeholder" : "Number of LLM calls for this node"}>
                          Attempts: {nodeRetries}
                          {nodeFallback && " (LLM failed, placeholder shown)"}
                        </span>
                      )}
                      {nodeCostUsd != null && nodeCostUsd > 0 && (
                        <span title="LLM cost for this node (USD)">
                          Cost: ${nodeCostUsd.toFixed(6)}
                        </span>
                      )}
                    </div>
                  )}
                  {nodeFallback !== true && (
                    <p className="text-sm text-zinc-600 dark:text-zinc-300">
                      Prompt statistics and node-specific metadata will appear here when available.
                    </p>
                  )}
                  {nodeMetadata && Object.keys(nodeMetadata).length > 0 && (
                    <pre className="text-xs bg-slate-100 dark:bg-zinc-800 rounded p-3 mt-2 overflow-x-auto text-zinc-700 dark:text-zinc-300 font-mono border border-slate-200 dark:border-zinc-700">
                      {JSON.stringify(nodeMetadata, null, 2)}
                    </pre>
                  )}
                </section>
              </>
            )}
            <section>
              <h3 className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
                Output data (preview)
              </h3>
              {outputPreviewData ? (
                <InputSummaryView summary={outputPreviewData} />
              ) : isExecuting ? (
                <p className="text-sm text-zinc-500 dark:text-zinc-400 italic py-3">
                  Running pipeline… output data will appear here when this node is processed.
                </p>
              ) : (
                <p className="text-sm text-zinc-500 dark:text-zinc-400 italic py-3">
                  Run the pipeline to see the output data for this node.
                </p>
              )}
            </section>
          </>
        )}
        {hasCompileDetails && (
          <section>
            <h3 className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">From compile</h3>
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-0.5">ID</p>
                <div className="space-y-0.5 text-zinc-700 dark:text-zinc-300 font-mono text-xs">
                  <p>Graph: {selectedNodeId}</p>
                  {compileNode?.id != null && (
                    <p className="text-zinc-600 dark:text-zinc-400">Compile: {compileNode.id}</p>
                  )}
                </div>
              </div>
              {hasIdMapping && (
                <div>
                  <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-0.5">ID mapping</p>
                  <p className="text-zinc-700 dark:text-zinc-300 font-mono text-xs">
                    {selectedNodeId} → {compileId}
                  </p>
                  <p className="text-zinc-500 dark:text-zinc-400 text-[10px] mt-0.5">
                    Graph/skrub ID maps to compile node ID for lookups.
                  </p>
                </div>
              )}
              {compileNode?.source_range != null && (
                <div>
                  <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-0.5">Code location</p>
                  <p className="text-zinc-700 dark:text-zinc-300 font-mono text-xs">
                    {formatSourceRange(compileNode.source_range)}
                  </p>
                </div>
              )}
              {(upstreamNodeLabels.length > 0 || downstreamNodeLabels.length > 0) && (
                <div>
                  <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Data flow</p>
                  <div className="space-y-1 text-zinc-700 dark:text-zinc-300">
                    {upstreamNodeLabels.length > 0 && (
                      <p>
                        <span className="text-zinc-500 dark:text-zinc-400">Depends on:</span>{" "}
                        {upstreamNodeLabels.join(", ")}
                      </p>
                    )}
                    {downstreamNodeLabels.length > 0 && (
                      <p>
                        <span className="text-zinc-500 dark:text-zinc-400">Feeds into:</span>{" "}
                        {downstreamNodeLabels.join(", ")}
                      </p>
                    )}
                  </div>
                </div>
              )}
              {compileValidationErrors.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-amber-700 dark:text-amber-400 mb-0.5">Validation errors</p>
                  <ul className="list-disc list-inside text-amber-700 dark:text-amber-300 text-xs space-y-0.5">
                    {compileValidationErrors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
              {compileTimingsMs != null && Object.keys(compileTimingsMs).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-0.5">Compile timings (ms)</p>
                  <div className="rounded border border-slate-200 dark:border-zinc-700 overflow-hidden">
                    <table className="min-w-full text-xs text-zinc-700 dark:text-zinc-300">
                      <tbody>
                        {Object.entries(compileTimingsMs).map(([key, ms]) => (
                          <tr key={key} className="border-b border-slate-100 dark:border-zinc-700 last:border-0">
                            <td className="py-1 px-2 font-medium">{key}</td>
                            <td className="py-1 px-2 font-mono text-right">{ms.toFixed(1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
