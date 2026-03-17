import { useState, useCallback, useRef } from "react";
import { clearCache, compileToSkrubGraph, type CompileNode } from "../api/client";
import {
  graphNodeToCompileIds,
  compileIdsToSkrubIds,
  skrubIdToRaw,
} from "../utils/graphCodeSync";
import { useLlmConfig } from "../hooks/useLlmConfig";
import { useScriptManager } from "../hooks/useScriptManager";
import { useCompile } from "../hooks/useCompile";
import { useExecution } from "../hooks/useExecution";
import { InputEditor } from "./InputEditor";
import { GraphPanelWithErrorBoundary, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

/** Initial pipeline code shown before any script is loaded from the backend. */
const INITIAL_PIPELINE_CODE = `import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")

products = products.sem_gen_features(
    nl_prompt="Generate useful features for product analysis.",
    name="product_features",
    how_many=3,
)

result = products.skb.eval()
`;

const AVAILABLE_LLMS = [
  "gpt-5-mini",
  "gpt-4.1-mini",
  "gemini/gemini-2.5-flash",
  "gemini/gemini-2.5-flash-lite",
  "gemini/gemini-2.5-pro",
  "gemini/gemini-3-flash",
  "gemini/gemini-3-flash-lite",
  "gemini/gemini-3-pro",
];

const formatDuration = (ms: number): string => {
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
};

interface CodeGenDemoProps {
  isDark?: boolean;
}

export function CodeGenDemo({ isDark = false }: CodeGenDemoProps) {
  // ── UI-only state ─────────────────────────────────────────────────────────
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [cursorFocusNodeId, setCursorFocusNodeId] = useState<string | null>(null);
  const [expandedPanel, setExpandedPanel] = useState<"left" | "middle" | "right" | null>(null);

  // ── Domain hooks ──────────────────────────────────────────────────────────
  const scriptLoadInProgressRef = useRef(false);
  const scripts = useScriptManager({
    mode: "normal",
    initialCode: INITIAL_PIPELINE_CODE,
    defaultScriptId: "simple",
    scriptLoadInProgressRef,
  });
  const { pipelineCode, loadedScriptId, pipelineScripts } = scripts;

  const llm = useLlmConfig({ initialTemperature: "0.0" });
  const { llmName, temperature, temperatureError, temperatureShake } = llm;

  const execution = useExecution({
    pipelineCode,
    llmName,
    temperature,
    loadedScriptId,
    validateTemperature: llm.validateTemperature,
    onTemperatureInvalid: llm.markTemperatureInvalid,
  });
  const {
    isExecuting,
    liveNodeCode,
    liveNodeRetries,
    liveFallbackByNode,
    liveNodeCostUsd,
    inputSummaryByNode,
    nodeDataByNode,
    lastRunCostUsd,
    lastRunDurationMs,
    lastRunError,
    lastRunProfile,
    skrubToCompileId,
    handlePlay,
    resetLiveState,
  } = execution;

  const compile = useCompile({
    pipelineCode,
    llmName,
    temperature,
    loadedScriptId,
    onCodeChange: resetLiveState,
    scriptLoadInProgressRef,
  });
  const {
    compileNodes,
    compileEdges,
    compileError,
    compileValidationErrors,
    compileTimingsMs,
    refreshCompileGraph,
  } = compile;

  // ── Cache clear ───────────────────────────────────────────────────────────
  const handleClearCache = useCallback(async () => {
    if (isExecuting) return;
    try {
      await clearCache({ script: pipelineCode, temperature, llmName });
    } catch {
      // Silently ignore — cache clear is best-effort
    }
    await refreshCompileGraph();
  }, [isExecuting, pipelineCode, temperature, llmName, refreshCompileGraph]);

  // ── Derived graph display values ──────────────────────────────────────────
  // Compile graph is always canonical — never replaced by the runtime skrub graph.
  const compilePreviewGraph = compileToSkrubGraph(compileNodes, compileEdges ?? []);
  const displayGraph = compilePreviewGraph;
  const isPreviewGraph = !!compilePreviewGraph?.nodes?.length;

  const nodes: GraphNode[] =
    compileNodes.length > 0
      ? compileNodes
          .filter((n) =>
            ["input", "operator", "pipeline"].includes(
              typeof n.type === "string" ? n.type.toLowerCase() : ""
            )
          )
          .map((n) => {
            const t = (n.type ?? "").toLowerCase();
            return {
              id: n.id,
              type: (t === "input" ? "input" : "operator") as "input" | "operator",
              label: n.label,
            };
          })
      : [
          { id: "input", type: "input", label: "Input" },
          { id: "op1", type: "operator", label: "Op" },
        ];

  const nodeIds = new Set(nodes.map((n) => n.id));
  const graphEdges = (compileEdges ?? []).filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );
  const runnableNodeIds = nodes.map((n) => n.id);

  const selectedNode = (() => {
    if (!selectedNodeId) return null;
    if (selectedNodeId.startsWith("skrub_") && displayGraph?.nodes) {
      const nid = skrubIdToRaw(selectedNodeId);
      const graphNode = displayGraph.nodes.find((n) => n.id === nid);
      if (graphNode) {
        const compileNode = compileNodes.find((n) => n.id === nid);
        const compileType = (compileNode?.type ?? graphNode.type ?? "").toLowerCase();
        const isOperator =
          compileType === "operator" ||
          compileType === "pipeline" ||
          Boolean(displayGraph.sempipesNodeIds?.includes(nid));
        const nodeType = graphNode.type === "input" || graphNode.type === "operator"
          ? graphNode.type
          : (isOperator ? "operator" : "input");
        return {
          id: selectedNodeId,
          type: nodeType as "input" | "operator",
          label: graphNode.label,
        };
      }
    }
    return nodes.find((n) => n.id === selectedNodeId) ?? null;
  })();

  const highlightedSkrubIds = compileIdsToSkrubIds(
    highlightedNodeIds,
    displayGraph?.nodes ?? [],
    compileNodes,
    false // compile graph is canonical; compile IDs === graph IDs in preview mode
  );

  const inputSummaryForSelectedNode = (() => {
    if (!selectedNodeId?.startsWith("skrub_") || !displayGraph?.nodes) return undefined;
    const nid = skrubIdToRaw(selectedNodeId);
    const graphNode = displayGraph.nodes.find((n) => n.id === nid);
    if (!graphNode) return undefined;
    const compileNode = compileNodes.find(
      (n) =>
        n.id === nid ||
        (n.label === graphNode.label && (n.type ?? "").toLowerCase() === "input")
    );
    return compileNode ? inputSummaryByNode[compileNode.id] : undefined;
  })();

  // Graph node id = compile node id (display graph is from compile; run must not change this)
  const selectedCompileNodeId = selectedNodeId
    ? selectedNodeId.startsWith("skrub_")
      ? skrubIdToRaw(selectedNodeId)
      : selectedNodeId
    : null;
  const selectedCompileNode =
    selectedCompileNodeId != null
      ? compileNodes.find((n) => n.id === selectedCompileNodeId) ?? null
      : null;
  const idToLabel = new Map(compileNodes.map((n) => [n.id, n.label]));
  const edges = compileEdges ?? [];
  const upstreamNodeLabels =
    selectedCompileNodeId != null
      ? [...new Set(edges.filter((e) => e.target === selectedCompileNodeId).map((e) => e.source))]
          .map((id) => idToLabel.get(id) ?? id)
      : [];
  const downstreamNodeLabels =
    selectedCompileNodeId != null
      ? [...new Set(edges.filter((e) => e.source === selectedCompileNodeId).map((e) => e.target))]
          .map((id) => idToLabel.get(id) ?? id)
      : [];

  // ── Graph ↔ editor sync ───────────────────────────────────────────────────
  const handleGraphNodeSelect = useCallback(
    (nodeId: string | null) => {
      setSelectedNodeId(nodeId);
      if (!nodeId) {
        setHighlightedNodeIds([]);
        return;
      }
      if (!nodeId.startsWith("skrub_") || !displayGraph?.nodes) return;

      const graphNodeId = skrubIdToRaw(nodeId);
      const graphNode = displayGraph.nodes.find((n) => n.id === graphNodeId);
      if (!graphNode) return;

      const matchingIds = graphNodeToCompileIds(graphNodeId, graphNode, compileNodes, {
        runnableNodeIds,
      });
      if (matchingIds.length > 0) {
        setHighlightedNodeIds(matchingIds);
        const withRange = compileNodes.find(
          (n) => n.id === matchingIds[0] && n.source_range != null
        );
        if (withRange) setCursorFocusNodeId(withRange.id);
      }
    },
    [displayGraph?.nodes, compileNodes, runnableNodeIds]
  );

  // ── Panel widths ──────────────────────────────────────────────────────────
  const leftWidth = expandedPanel === "left" ? "80%" : expandedPanel === null ? "33%" : "10%";
  const middleWidth =
    expandedPanel === "middle" ? "80%" : expandedPanel === null ? "34%" : "10%";
  const rightWidth = expandedPanel === "right" ? "80%" : expandedPanel === null ? "33%" : "10%";

  return (
    <div className="flex flex-col h-full bg-slate-200 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 font-sans min-w-[1280px]">
      <div className="flex flex-1 min-h-0 gap-4 px-4 pb-4 pt-4">
        {/* ── Left: Pipeline editor ────────────────────────────────────────── */}
        <div
          className="min-w-[280px] flex flex-col min-h-0 rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md transition-all duration-300"
          style={{ width: leftWidth }}
        >
          <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex flex-col justify-center gap-1">
            {/* Primary row: Script selector + run controls */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <span className="text-xs text-zinc-500 dark:text-zinc-400">Pipeline:</span>
                <select
                  value={loadedScriptId ?? ""}
                  onChange={(e) => scripts.handleLoadScript(e.target.value)}
                  disabled={isExecuting}
                  className="text-xs px-2 py-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-700 dark:text-zinc-200 min-w-[140px]"
                  title="Select pipeline script"
                >
                  {(pipelineScripts ?? []).length === 0 ? (
                    <option value="">No pipelines — is the backend running?</option>
                  ) : null}
                  {(pipelineScripts ?? []).map(({ id, label }) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
                <input
                  type="file"
                  accept=".py,.txt"
                  onChange={scripts.handleFileUpload}
                  className="hidden"
                  data-testid="file-upload-input"
                  id="file-upload-input"
                />
                <button
                  type="button"
                  onClick={() => document.getElementById("file-upload-input")?.click()}
                  disabled={isExecuting}
                  className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-500 dark:text-zinc-400"
                  title="Upload script from file"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </button>
                {/* Play */}
                <button
                  type="button"
                  onClick={handlePlay}
                  disabled={isExecuting}
                  className="p-1.5 rounded border border-emerald-600 bg-emerald-600 hover:bg-emerald-500 hover:border-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
                  title="Run pipeline"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5,3 19,12 5,21" />
                  </svg>
                </button>
                {/* Stop */}
                <button
                  type="button"
                  onClick={handlePlay}
                  disabled={!isExecuting}
                  className={`p-1.5 rounded border transition-colors ${
                    isExecuting
                      ? "border-red-600 bg-red-600 hover:bg-red-500 hover:border-red-500 text-white"
                      : "border-slate-300 dark:border-zinc-600 bg-slate-100 dark:bg-zinc-800 text-slate-300 dark:text-zinc-600 cursor-not-allowed"
                  }`}
                  title="Stop execution"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="6" width="12" height="12" />
                  </svg>
                </button>
                {/* Clear cache */}
                <button
                  type="button"
                  onClick={handleClearCache}
                  disabled={isExecuting}
                  className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed text-zinc-600 dark:text-zinc-400"
                  title="Clear all cache"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === "left" ? null : "left")}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                title={expandedPanel === "left" ? "Restore panel size" : "Expand panel"}
                aria-label={expandedPanel === "left" ? "Restore panel size" : "Expand panel"}
                data-testid="expand-left-panel"
              >
                {expandedPanel === "left" ? "⤡" : "⤢"}
              </button>
            </div>

            {/* Secondary row: LLM settings */}
            <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
              <div className="flex items-center gap-1.5">
                <span>Model:</span>
                <select
                  value={llmName}
                  onChange={(e) => llm.setLlmName(e.target.value)}
                  disabled={isExecuting}
                  className="text-xs px-1.5 py-0.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-600 dark:text-zinc-300"
                  title="Select LLM model"
                >
                  {AVAILABLE_LLMS.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-1.5">
                <span>Temperature:</span>
                <input
                  type="text"
                  value={temperature}
                  onChange={(e) => llm.handleTemperatureChange(e.target.value)}
                  disabled={isExecuting}
                  className={`text-xs px-1.5 py-0.5 rounded border disabled:opacity-50 w-12 transition-colors ${
                    temperatureError
                      ? "border-red-500 bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-400"
                      : "border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
                  } ${temperatureShake ? "animate-shake" : ""}`}
                  placeholder="0.0"
                  title="LLM temperature (0-2)"
                />
                {temperatureError && (
                  <span className="text-[10px] text-red-600">0-2</span>
                )}
              </div>
            </div>

            {compileError != null && (
              <p
                className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded px-2 py-1"
                role="alert"
              >
                {compileError}
              </p>
            )}
          </div>

          <div className="flex-1 min-h-0">
            <InputEditor
              value={pipelineCode}
              onChange={scripts.setPipelineCode}
              disabled={isExecuting}
              isDark={isDark}
              nodeRanges={compileNodes.filter(
                (n): n is CompileNode & {
                  source_range: NonNullable<CompileNode["source_range"]>;
                } => n.source_range != null
              )}
              onHighlightNodes={setHighlightedNodeIds}
              onSelectNode={(nodeId) => {
                setHighlightedNodeIds(nodeId ? [nodeId] : []);
                if (nodeId && !nodeId.startsWith("skrub_") && displayGraph?.nodes) {
                  const compileNode = compileNodes.find((n) => n.id === nodeId);
                  const graphNode = compileNode
                    ? displayGraph.nodes.find(
                        (n) =>
                          (n.label ?? "") === (compileNode.label ?? "") || n.id === nodeId
                      )
                    : null;
                  setSelectedNodeId(graphNode ? `skrub_${graphNode.id}` : nodeId);
                } else {
                  setSelectedNodeId(nodeId);
                }
              }}
              selectedNodeId={selectedNodeId}
              highlightedNodeIds={highlightedNodeIds}
              focusNodeId={cursorFocusNodeId}
              onFocusApplied={() => setCursorFocusNodeId(null)}
              isExpanded={expandedPanel === "left"}
              sempipesNodeIds={compileNodes
                .filter(
                  (n) =>
                    (n.type ?? "").toLowerCase() === "operator" &&
                    (n.label ?? "").toLowerCase().startsWith("sem_")
                )
                .map((n) => n.id)}
            />
          </div>

          {/* Stats footer — shown after a completed run */}
          {!isExecuting && lastRunDurationMs != null && (
            <div className="shrink-0 px-3 py-2 border-t border-slate-300 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 flex flex-col gap-2">
              {lastRunError && (
                <p
                  className="text-xs font-bold text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded px-2 py-1"
                  role="alert"
                >
                  {lastRunError}
                </p>
              )}
              <div className="flex items-center gap-3 text-xs">
                {lastRunError ? (
                  <span className="text-red-600 flex items-center gap-1">
                    <span>✗</span> Failed
                  </span>
                ) : (
                  <span className="text-emerald-600 flex items-center gap-1">
                    <span>✓</span> Completed
                  </span>
                )}
                <span className="text-zinc-400 dark:text-zinc-500">·</span>
                <span className="text-zinc-600 dark:text-zinc-300" title="Execution time">
                  {formatDuration(lastRunDurationMs)}
                </span>
                {lastRunCostUsd != null && lastRunCostUsd > 0 && (
                  <>
                    <span className="text-zinc-400 dark:text-zinc-500">·</span>
                    <span className="text-zinc-600 dark:text-zinc-300" title="LLM cost">
                      ${lastRunCostUsd.toFixed(6)}
                    </span>
                  </>
                )}
              </div>
              {lastRunProfile && Object.keys(lastRunProfile).length > 0 && (
                <table className="text-[10px] text-zinc-600 dark:text-zinc-400 w-full border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-zinc-600">
                      <th className="text-left py-0.5 pr-2 font-medium">Phase</th>
                      <th className="text-right py-0.5 font-medium">Time (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lastRunProfile.prepare_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Backend: prepare (cache + compile)</td>
                        <td className="text-right tabular-nums">{lastRunProfile.prepare_ms}</td>
                      </tr>
                    )}
                    {lastRunProfile.runner_startup_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Runner: startup (imports)</td>
                        <td className="text-right tabular-nums">{lastRunProfile.runner_startup_ms}</td>
                      </tr>
                    )}
                    {lastRunProfile.runner_exec_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Runner: pipeline execution (data + LLM + fit)</td>
                        <td className="text-right tabular-nums">{lastRunProfile.runner_exec_ms}</td>
                      </tr>
                    )}
                    {lastRunProfile.runner_post_exec_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Runner: post-exec (graph, summaries)</td>
                        <td className="text-right tabular-nums">{lastRunProfile.runner_post_exec_ms}</td>
                      </tr>
                    )}
                    {lastRunProfile.subprocess_wall_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Backend: subprocess wall</td>
                        <td className="text-right tabular-nums">{lastRunProfile.subprocess_wall_ms}</td>
                      </tr>
                    )}
                    {lastRunProfile.emit_ms != null && (
                      <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                        <td className="py-0.5 pr-2">Backend: emit events</td>
                        <td className="text-right tabular-nums">{lastRunProfile.emit_ms}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

        {/* ── Middle: Computational graph ────────────────────────────────────── */}
        <div
          className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4"
          style={{ width: middleWidth }}
        >
          <div className="flex-1 min-h-0">
            <GraphPanelWithErrorBoundary
              key={compileNodes.map((n) => n.id).join("|")}
              selectedNodeId={selectedNodeId}
              onSelectNode={handleGraphNodeSelect}
              isDark={isDark}
              nodes={nodes}
              edges={graphEdges}
              skrubGraph={displayGraph}
              runnableNodeIds={runnableNodeIds}
              isLoading={isExecuting && !displayGraph}
              highlightedNodeIds={highlightedSkrubIds}
              showGraph={isExecuting || !!displayGraph}
              isPreview={isPreviewGraph}
              isExecuting={isExecuting}
              expandButton={
                <button
                  type="button"
                  onClick={() =>
                    setExpandedPanel(expandedPanel === "middle" ? null : "middle")
                  }
                  className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                  title={
                    expandedPanel === "middle" ? "Restore panel size" : "Expand panel"
                  }
                  aria-label={
                    expandedPanel === "middle" ? "Restore panel size" : "Expand panel"
                  }
                  data-testid="expand-middle-panel"
                >
                  {expandedPanel === "middle" ? (
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="4 14 10 14 10 20" />
                      <polyline points="20 10 14 10 14 4" />
                      <line x1="14" y1="10" x2="21" y2="3" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  ) : (
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="15 3 21 3 21 9" />
                      <polyline points="9 21 3 21 3 15" />
                      <line x1="21" y1="3" x2="14" y2="10" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  )}
                </button>
              }
            />
          </div>
        </div>

        {/* ── Right: Node details / results ────────────────────────────────── */}
        <div
          className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300"
          style={{ width: rightWidth }}
        >
          <NodeDetailsPanel
            selectedNodeId={selectedNodeId}
            selectedNode={selectedNode}
            generatedCode={null}
            liveGeneratedCodeByNode={liveNodeCode}
            liveRetriesByNode={liveNodeRetries}
            liveFallbackByNode={liveFallbackByNode}
            liveCostUsdByNode={liveNodeCostUsd}
            inputSummaryByNode={inputSummaryByNode}
            inputSummaryForSelectedNode={inputSummaryForSelectedNode}
            nodeDataByNode={nodeDataByNode}
            isExecuting={isExecuting}
            nodeMetadata={null}
            skrubToCompileId={skrubToCompileId}
            compileNode={selectedCompileNode}
            upstreamNodeLabels={upstreamNodeLabels}
            downstreamNodeLabels={downstreamNodeLabels}
            compileValidationErrors={compileValidationErrors}
            compileTimingsMs={compileTimingsMs}
            isExpanded={expandedPanel === "right"}
            expandButton={
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === "right" ? null : "right")}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                title={expandedPanel === "right" ? "Restore panel size" : "Expand panel"}
                aria-label={
                  expandedPanel === "right" ? "Restore panel size" : "Expand panel"
                }
                data-testid="expand-right-panel"
              >
                {expandedPanel === "right" ? (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="4 14 10 14 10 20" />
                    <polyline points="20 10 14 10 14 4" />
                    <line x1="14" y1="10" x2="21" y2="3" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                ) : (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                )}
              </button>
            }
          />
        </div>
      </div>
    </div>
  );
}
