import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { clearCache, compileToSkrubGraph, type CompileNode } from "../api/client";
import { graphNodeToCompileIds, skrubIdToRaw } from "../utils/graphCodeSync";
import { fetchOptimizerStatus } from "../api/client";
import { useLlmConfig } from "../hooks/useLlmConfig";
import { useScriptManager } from "../hooks/useScriptManager";
import { useCompile } from "../hooks/useCompile";
import { useExecution } from "../hooks/useExecution";
import { GraphPanelWithErrorBoundary } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";
import { OptimizerPanel } from "./OptimizerPanel";
import { OptimizerDetailsPanel } from "./OptimizerDetailsPanel";
import { PipelineEditorPanel } from "./PipelineEditorPanel";

const NEW_PIPELINE_ID = "new";
const DEFAULT_SCRIPT_ID = "optimise_house";

/**
 * New-pipeline boilerplate: clean user-facing script using plain MonteCarloTreeSearch.
 * The backend auto-injects streaming/trajectory-saving logic at runtime.
 */
const INITIAL_PIPELINE_CODE = `import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import sempipes
import skrub
from sklearn.ensemble import HistGradientBoostingClassifier

from sempipes.optimisers import MonteCarloTreeSearch, optimise_colopro

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=1000, how="random")
baskets = skrub.var("baskets", dataset.baskets)

products = products.sem_gen_features(
    nl_prompt="Generate useful features for product analysis.",
    name="product_features",
    how_many=3,
)

merged = products.merge(baskets, left_on="basket_ID", right_on="ID")
target = merged["fraud_flag"].skb.set_name("fraud_flag").skb.mark_as_y()
data = merged.drop(["fraud_flag", "ID", "basket_ID"], axis=1).skb.mark_as_X()

pipeline = data.skb.apply(skrub.TableVectorizer()).skb.apply(
    HistGradientBoostingClassifier(), y=target
)

outcomes = optimise_colopro(
    dag_sink=pipeline,
    operator_name="product_features",
    num_trials=5,
    scoring="roc_auc",
    cv=3,
    search=MonteCarloTreeSearch(),
)
`;

const SIMULATED_SCRIPT_PREFIXES = [
  "optimise_house",
  "optimise_fraud",
  "optimise_museums",
  "optimise_medium",
  "optimise_simple",
];

function isSimulatedScript(scriptId: string | null): boolean {
  return !!scriptId && SIMULATED_SCRIPT_PREFIXES.some((p) => scriptId.includes(p));
}

interface OptimizerDemoProps {
  layoutMode: "toggled" | "left-split";
  setLayoutMode: (mode: "toggled" | "left-split") => void;
  isDark: boolean;
}

export function OptimizerDemo({ layoutMode, isDark }: OptimizerDemoProps) {
  // ── Optimizer-specific UI state ───────────────────────────────────────────
  const [viewMode, setViewMode] = useState<"graph" | "optimizer">("optimizer");
  const [isGraphExpanded, setIsGraphExpanded] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedOptimizerTrial, setSelectedOptimizerTrial] = useState<any | null>(null);
  const [optimizerOperatorName, setOptimizerOperatorName] = useState<string | undefined>(
    undefined
  );
  const [activeOperatorName, setActiveOperatorName] = useState<string | undefined>(undefined);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [cursorFocusNodeId, setCursorFocusNodeId] = useState<string | null>(null);
  const [expandedPanel, setExpandedPanel] = useState<"left" | "middle" | "right" | null>(null);
  const [isOptimizerAvailable, setIsOptimizerAvailable] = useState(false);
  const [replayTrigger, setReplayTrigger] = useState(0);

  // ── Domain hooks ──────────────────────────────────────────────────────────
  const scriptLoadInProgressRef = useRef(false);
  const scripts = useScriptManager({
    mode: "optimizer",
    initialCode: INITIAL_PIPELINE_CODE,
    defaultScriptId: DEFAULT_SCRIPT_ID,
    prependEntries: [{ id: NEW_PIPELINE_ID, label: "— New Editable Pipeline —" }],
    syntheticNewId: NEW_PIPELINE_ID,
    scriptLoadInProgressRef,
  });
  const { pipelineCode, loadedScriptId, pipelineScripts } = scripts;

  const llm = useLlmConfig({ initialTemperature: "0.1" });
  const { llmName, temperature, temperatureError, temperatureShake } = llm;

  const execution = useExecution({
    pipelineCode,
    llmName,
    temperature,
    loadedScriptId,
    validateTemperature: llm.validateTemperature,
    onTemperatureInvalid: llm.markTemperatureInvalid,
    useCache: true,
    newPipelineId: NEW_PIPELINE_ID,
    // Simulated scripts replay stored trajectories — skip the real SSE stream.
    onBeforeExecute: () => {
      if (isSimulatedScript(loadedScriptId)) {
        setViewMode("optimizer");
        setSelectedOptimizerTrial(null);
        setReplayTrigger((prev) => prev + 1);
        return true; // handled — no SSE
      }
      return false; // proceed normally
    },
  });
  const {
    isExecuting,
    liveNodeCode,
    liveNodeRetries,
    liveDebugInfoByNode,
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
    compileValidationErrors,
    compileTimingsMs,
    refreshCompileGraph,
  } = compile;

  // ── Wrap handleLoadScript to clear optimizer trial on script change ────────
  const handleLoadScript = useCallback(
    async (id: string) => {
      setSelectedOptimizerTrial(null);
      await scripts.handleLoadScript(id);
    },
    [scripts]
  );

  // ── Cache clear ───────────────────────────────────────────────────────────
  const handleClearCache = useCallback(async () => {
    if (isExecuting) return;
    try {
      await clearCache({ script: pipelineCode, temperature, llmName });
    } catch {
      // Best-effort
    }
    await refreshCompileGraph();
  }, [isExecuting, pipelineCode, temperature, llmName, refreshCompileGraph]);

  // ── Optimizer status polling ──────────────────────────────────────────────
  useEffect(() => {
    const checkStatus = () => {
      fetchOptimizerStatus()
        .then((status) => setIsOptimizerAvailable(status.active))
        .catch(() => setIsOptimizerAvailable(false));
    };
    checkStatus();
    const intervalId = setInterval(checkStatus, 2000);
    return () => clearInterval(intervalId);
  }, []);

  // ── Auto-trigger animation for simulated scripts ──────────────────────────
  useEffect(() => {
    if (!isSimulatedScript(loadedScriptId)) return;
    setViewMode("optimizer");
    setSelectedOptimizerTrial(null);
    const t = setTimeout(() => setReplayTrigger((prev) => prev + 1), 500);
    return () => clearTimeout(t);
  }, [loadedScriptId]);

  // ── Derived graph display values ──────────────────────────────────────────
  // Compile graph is always canonical — never replaced by the runtime skrub graph.
  const compilePreviewGraph = compileToSkrubGraph(compileNodes, compileEdges ?? []);
  const displayGraph = compilePreviewGraph;
  const isPreviewGraph = !!compilePreviewGraph?.nodes?.length;

  const nodes = useMemo(
    () =>
      compileNodes.map((n) => ({
        id: n.id,
        type: (n.type?.toLowerCase() === "input" ? "input" : "operator") as
          | "input"
          | "operator",
        label: n.label || n.id,
        color: n.id === activeOperatorName ? "#10b981" : undefined,
      })),
    [compileNodes, activeOperatorName]
  );

  const runnableNodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);

  const graphEdges = useMemo(
    () => compileEdges.map((e) => ({ source: e.source, target: e.target })),
    [compileEdges]
  );

  const highlightedSkrubIds = useMemo(() => {
    return highlightedNodeIds.map((id) => (id.startsWith("skrub_") ? id : `skrub_${id}`));
  }, [highlightedNodeIds]);

  const selectedNode = selectedNodeId && !selectedNodeId.startsWith("skrub_")
    ? compileNodes.find((n) => n.id === selectedNodeId)
    : null;

  const inputSummaryForSelectedNode = selectedNodeId
    ? inputSummaryByNode[selectedNodeId] || nodeDataByNode[selectedNodeId]
    : undefined;

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
  const w1 = expandedPanel === "left" ? "80%" : expandedPanel === null ? "33.33%" : "10%";
  const w2 = expandedPanel === "middle" ? "80%" : expandedPanel === null ? "33.34%" : "10%";
  const w3 = expandedPanel === "right" ? "80%" : expandedPanel === null ? "33.33%" : "10%";

  // ── Graph/Optimizer toggle buttons ────────────────────────────────────────
  const graphToggleButtons = isOptimizerAvailable ? (
    <div className="flex p-0.5 bg-slate-200 dark:bg-zinc-700 rounded-md border border-slate-300 dark:border-zinc-700">
      <button
        onClick={() => {
          setViewMode("graph");
          setSelectedOptimizerTrial(null);
        }}
        className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-all ${
          viewMode === "graph"
            ? "bg-white dark:bg-zinc-900 text-emerald-600 shadow-sm"
            : "text-zinc-500 dark:text-zinc-400"
        }`}
      >
        Graph
      </button>
      <button
        onClick={() => {
          setViewMode("optimizer");
          setReplayTrigger((prev) => prev + 1);
        }}
        className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-all ${
          viewMode === "optimizer"
            ? "bg-white dark:bg-zinc-900 text-emerald-600 shadow-sm"
            : "text-zinc-500 dark:text-zinc-400"
        }`}
      >
        Optimizer
      </button>
    </div>
  ) : null;

  function ExpandBtn({ panel }: { panel: "left" | "middle" | "right" }) {
    const isExpanded = expandedPanel === panel;
    return (
      <button
        type="button"
        onClick={() => setExpandedPanel(isExpanded ? null : panel)}
        className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
      >
        {isExpanded ? "⤡" : "⤢"}
      </button>
    );
  }

  return (
    <div className="flex flex-col h-full bg-slate-200 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 font-sans min-w-[1280px]">
      <div className="flex flex-1 min-h-0 gap-4 px-4 pb-4 pt-4">
        {/* ── Left: Pipeline editor ────────────────────────────────────────── */}
        <div
          className={`min-w-[280px] flex flex-col min-h-0 transition-all duration-300 ${
            layoutMode === "left-split" ? "gap-0" : "gap-4"
          }`}
          style={{ width: w1 }}
        >
          <PipelineEditorPanel
            isExpanded={expandedPanel === "left"}
            onToggleExpand={() => setExpandedPanel(expandedPanel === "left" ? null : "left")}
            isDark={isDark}
            pipelineScripts={pipelineScripts}
            loadedScriptId={loadedScriptId}
            onLoadScript={handleLoadScript}
            onPipelineCodeChange={scripts.setPipelineCode}
            isExecuting={isExecuting}
            onPlay={handlePlay}
            onClearCache={handleClearCache}
            llmName={llmName}
            onLlmNameChange={llm.setLlmName}
            temperature={temperature}
            onTemperatureChange={llm.handleTemperatureChange}
            temperatureError={temperatureError}
            temperatureShake={temperatureShake}
            pipelineCode={pipelineCode}
            compileNodes={compileNodes}
            highlightedNodeIds={highlightedNodeIds}
            onHighlightNodes={setHighlightedNodeIds}
            selectedNodeId={selectedNodeId}
            onSelectNode={(nodeId: string | null) => {
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
            cursorFocusNodeId={cursorFocusNodeId}
            onFocusApplied={() => setCursorFocusNodeId(null)}
            sempipesNodeIds={displayGraph?.sempipesNodeIds ?? []}
            activeOperatorName={activeOperatorName}
            lastRunDurationMs={lastRunDurationMs}
            lastRunCostUsd={lastRunCostUsd}
            lastRunProfile={lastRunProfile}
            isReadOnly={loadedScriptId !== NEW_PIPELINE_ID}
            className={`${
              layoutMode === "left-split" && isGraphExpanded
                ? "flex-1 rounded-t-lg rounded-b-none shadow-none border-b-0"
                : "flex-1"
            }`}
          />
          {layoutMode === "left-split" && (
            <div
              className={`transition-all duration-300 flex flex-col min-h-0 ${
                isGraphExpanded
                  ? "flex-1 min-h-[50%]"
                  : "h-[var(--header-height)] shrink-0"
              }`}
            >
              <div
                onClick={() => setIsGraphExpanded(!isGraphExpanded)}
                className={`shrink-0 h-[var(--header-height)] px-4 border border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between cursor-pointer hover:bg-slate-200 dark:hover:bg-zinc-700 transition-colors ${
                  isGraphExpanded
                    ? "rounded-b-lg rounded-t-none border-t shadow-none"
                    : "rounded-lg shadow-sm"
                }`}
              >
                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-300">
                  Computational Graph
                </span>
                <span className="text-zinc-400">{isGraphExpanded ? "▲" : "▼"}</span>
              </div>
              {isGraphExpanded && (
                <div className="flex-1 min-h-0 overflow-hidden">
                  <GraphPanelWithErrorBoundary
                    key={compileNodes.map((n) => n.id).join("|")}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={handleGraphNodeSelect}
                    nodes={nodes}
                    edges={graphEdges}
                    skrubGraph={displayGraph}
                    runnableNodeIds={runnableNodeIds}
                    isLoading={isExecuting && !displayGraph}
                    highlightedNodeIds={highlightedSkrubIds}
                    showGraph={isExecuting || !!displayGraph}
                    isPreview={isPreviewGraph}
                    isExecuting={isExecuting}
                    hideHeader
                    isDark={isDark}
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Middle: Graph or Optimizer panel ────────────────────────────── */}
        <div
          className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4"
          style={{ width: w2 }}
        >
          <div className="flex-1 min-h-0">
            {viewMode === "graph" && layoutMode === "toggled" ? (
              <GraphPanelWithErrorBoundary
                key={compileNodes.map((n) => n.id).join("|")}
                selectedNodeId={selectedNodeId}
                onSelectNode={handleGraphNodeSelect}
                nodes={nodes}
                edges={graphEdges}
                skrubGraph={displayGraph}
                runnableNodeIds={runnableNodeIds}
                isLoading={isExecuting && !displayGraph}
                highlightedNodeIds={highlightedSkrubIds}
                showGraph={isExecuting || !!displayGraph}
                isPreview={isPreviewGraph}
                isExecuting={isExecuting}
                isDark={isDark}
                expandButton={<ExpandBtn panel="middle" />}
                viewToggle={layoutMode === "toggled" ? graphToggleButtons : null}
              />
            ) : (
              <OptimizerPanel
                scriptId={
                  loadedScriptId && loadedScriptId !== NEW_PIPELINE_ID
                    ? loadedScriptId
                    : null
                }
                onTrialSelect={(trial) => {
                  setSelectedOptimizerTrial(trial);
                  setActiveOperatorName(undefined);
                }}
                selectedTrialId={selectedOptimizerTrial?.search_node.trial ?? null}
                isExecuting={isExecuting}
                isDark={isDark}
                hasFirstLiveNode={Object.keys(liveNodeCode).length > 0}
                expandButton={<ExpandBtn panel="middle" />}
                replayTrigger={replayTrigger}
                onMetaUpdate={(meta) => {
                  if (meta.operatorName) setOptimizerOperatorName(meta.operatorName);
                }}
                viewToggle={layoutMode === "toggled" ? graphToggleButtons : null}
              />
            )}
          </div>
        </div>

        {/* ── Right: Optimizer details or node details ─────────────────────── */}
        <div
          className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4"
          style={{ width: w3 }}
        >
          <div className="flex flex-col min-h-0 overflow-hidden rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-md transition-all duration-300 flex-1">
            <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
              {viewMode === "optimizer" || layoutMode !== "toggled" ? (
                <OptimizerDetailsPanel
                  selectedTrial={selectedOptimizerTrial}
                  operatorName={optimizerOperatorName}
                  activeOperatorName={activeOperatorName}
                  isDark={isDark}
                  onOperatorClick={(name) => {
                    setActiveOperatorName(name);
                    const match = compileNodes.find(
                      (n) => n.label?.toLowerCase() === name.toLowerCase()
                    );
                    if (match) {
                      setHighlightedNodeIds([match.id]);
                      setCursorFocusNodeId(match.id);
                    }
                  }}
                  isExpanded={expandedPanel === "right"}
                  expandButton={<ExpandBtn panel="right" />}
                />
              ) : (
                <NodeDetailsPanel
                  selectedNodeId={selectedNodeId}
                  selectedNode={selectedNode as any}
                  isDark={isDark}
                  generatedCode={null}
                  liveGeneratedCodeByNode={liveNodeCode}
                  liveRetriesByNode={liveNodeRetries}
                  liveDebugInfoByNode={liveDebugInfoByNode}
                  liveCostUsdByNode={liveNodeCostUsd}
                  inputSummaryByNode={inputSummaryByNode}
                  inputSummaryForSelectedNode={inputSummaryForSelectedNode}
                  nodeDataByNode={nodeDataByNode}
                  isExecuting={isExecuting}
                  skrubToCompileId={skrubToCompileId}
                  compileNode={selectedCompileNode}
                  upstreamNodeLabels={upstreamNodeLabels}
                  downstreamNodeLabels={downstreamNodeLabels}
                  compileValidationErrors={compileValidationErrors}
                  compileTimingsMs={compileTimingsMs}
                  isExpanded={expandedPanel === "right"}
                  expandButton={<ExpandBtn panel="right" />}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
