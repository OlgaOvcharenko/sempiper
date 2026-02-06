import { useState, useCallback, useEffect, useRef } from "react";
import {
  compilePipeline,
  executePipelineStream,
  listPipelineScripts,
  getPipelineScriptContent,
  updateSempipesConfig,
  compileToSkrubGraph,
  type CompileNode,
  type CompileEdge,
  type InputSummary,
  type PipelineScriptEntry,
  type SkrubGraphDict,
} from "../api/client";
import {
  graphNodeToCompileIds,
  compileIdsToSkrubIds,
  skrubIdToRaw,
} from "../utils/graphCodeSync";
import { InputEditor } from "./InputEditor";
import { GraphPanel, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

const DEFAULT_SCRIPT_ID = "simple";

/** Initial pipeline code (credit fraud + sem_gen_features); matches pipeline_scripts/simple.py. */
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

export function CodeGenDemo() {
  const [pipelineScripts, setPipelineScripts] = useState<PipelineScriptEntry[]>([]);
  const [pipelineCode, setPipelineCode] = useState(INITIAL_PIPELINE_CODE);
  const [loadedScriptId, setLoadedScriptId] = useState<string | null>(DEFAULT_SCRIPT_ID);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [cursorFocusNodeId, setCursorFocusNodeId] = useState<string | null>(null);
  const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);
  const [compileEdges, setCompileEdges] = useState<CompileEdge[]>([]);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [liveNodeCode, setLiveNodeCode] = useState<Record<string, string>>({});
  const [liveNodeRetries, setLiveNodeRetries] = useState<Record<string, number>>({});
  const [liveFallbackByNode, setLiveFallbackByNode] = useState<Record<string, boolean>>({});
  const [liveNodeCostUsd, setLiveNodeCostUsd] = useState<Record<string, number>>({});
  const [statusByNodeId, setStatusByNodeId] = useState<Record<string, "idle" | "running" | "done" | "error">>({});
  const [inputSummaryByNode, setInputSummaryByNode] = useState<Record<string, InputSummary>>({});
  const [lastRunCostUsd, setLastRunCostUsd] = useState<number | null>(null);
  const [lastRunError, setLastRunError] = useState<string | null>(null);
  const [skrubGraph, setSkrubGraph] = useState<SkrubGraphDict | null>(null);
  const [skrubToCompileId, setSkrubToCompileId] = useState<Record<string, string>>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const [llmName, setLlmName] = useState<string>("gemini/gemini-2.5-flash-lite");
  const [temperature, setTemperature] = useState<string>("0.0");
  const [temperatureError, setTemperatureError] = useState(false);
  const [temperatureShake, setTemperatureShake] = useState(false);
  const [expandedPanel, setExpandedPanel] = useState<'left' | 'middle' | 'right' | null>(null);
  const executeAbortRef = useRef<AbortController | null>(null);
  const compileAbortRef = useRef<AbortController | null>(null);
  const compileNodesRef = useRef<CompileNode[]>([]);
  compileNodesRef.current = compileNodes;

  const refreshCompileGraph = useCallback(async () => {
    if (compileAbortRef.current) compileAbortRef.current.abort();
    const controller = new AbortController();
    compileAbortRef.current = controller;
    setCompileError(null);
    try {
      const res = await compilePipeline(pipelineCode, { signal: controller.signal });
      if (compileAbortRef.current !== controller) return;
      setCompileNodes(res.nodes);
      setCompileEdges(res.edges ?? []);
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      setCompileNodes([]);
      setCompileEdges([]);
      setCompileError(err instanceof Error ? err.message : String(err));
    } finally {
      if (compileAbortRef.current === controller) compileAbortRef.current = null;
    }
  }, [pipelineCode]);

  const handleLoadScript = useCallback(async (id: string) => {
    setLoadedScriptId(id);
    try {
      const { content } = await getPipelineScriptContent(id);
      setPipelineCode(content);
    } catch {
      setPipelineCode("# Failed to load script: " + id + "\n");
    }
  }, []);

  const validateTemperature = useCallback((value: string): boolean => {
    if (value.trim() === "") return false;
    const num = parseFloat(value);
    if (isNaN(num)) return false;
    // Both OpenAI and Gemini support temperature range 0 to 2
    return num >= 0 && num <= 2;
  }, []);

  const handleTemperatureChange = useCallback((value: string) => {
    setTemperature(value);
    const isInvalid = value.trim() !== "" && !validateTemperature(value);
    
    if (isInvalid) {
      // Keep error state true
      setTemperatureError(true);
      // Trigger shake animation
      setTemperatureShake(true);
      // Clear shake animation after it completes
      setTimeout(() => setTemperatureShake(false), 820);
    } else {
      // Clear error when valid
      setTemperatureError(false);
      setTemperatureShake(false);
    }
  }, [validateTemperature]);

  const handlePlay = useCallback(async () => {
    if (isExecuting && executeAbortRef.current) {
      executeAbortRef.current.abort();
      return;
    }

    // Validate temperature before running
    if (!validateTemperature(temperature)) {
      setTemperatureError(true);
      setTemperatureShake(true);
      setLastRunError("Invalid temperature. Please enter a value between 0 and 2.");
      setTimeout(() => setTemperatureShake(false), 820);
      return;
    }
    setLiveNodeCode({});
    setLiveNodeRetries({});
    setLiveFallbackByNode({});
    setLiveNodeCostUsd({});
    setStatusByNodeId({});
    setInputSummaryByNode({});
    setLastRunCostUsd(null);
    setLastRunError(null);
    setSkrubGraph(null);
    setSkrubToCompileId({});
    setIsExecuting(true);

    // Update sempipes config before execution
    try {
      const tempValue = parseFloat(temperature);
      if (!isNaN(tempValue)) {
        await updateSempipesConfig({ llm_name: llmName, temperature: tempValue });
      }
    } catch (e) {
      setLastRunError(`Config update failed: ${e instanceof Error ? e.message : String(e)}`);
      setIsExecuting(false);
      return;
    }

    const controller = executePipelineStream(pipelineCode, (event) => {
      try {
        if (event.type === "input_summary") {
          setInputSummaryByNode((prev) => ({
            ...prev,
            [event.node_id]: {
              node_id: event.node_id,
              schema: event.schema,
              sample: event.sample,
              row_count: event.row_count,
            },
          }));
        } else if (event.type === "node_code") {
          setLiveNodeCode((prev) => ({ ...prev, [event.node_id]: event.generated_code }));
          setStatusByNodeId((prev) => ({
            ...prev,
            [event.node_id]: event.is_fallback ? "error" : "done",
          }));
          if (event.retries != null) {
            const retries = event.retries;
            setLiveNodeRetries((prev) => ({ ...prev, [event.node_id]: retries }));
          }
          if (event.is_fallback != null) {
            const isFallback = event.is_fallback;
            setLiveFallbackByNode((prev) => ({ ...prev, [event.node_id]: isFallback }));
          }
          if (event.cost_usd != null) {
            const cost = event.cost_usd;
            setLiveNodeCostUsd((prev) => ({ ...prev, [event.node_id]: cost }));
          }
        } else if (event.type === "error") {
          setLastRunError(event.message);
        } else if (event.type === "cost") {
          setLastRunCostUsd(event.total_usd);
        } else if (event.type === "skrub_graph") {
          // Only show graph from dictionary (nodes, parents, children); no SVG.
          if (event.graph) {
            setSkrubGraph(event.graph);
            setSkrubToCompileId(event.skrubToCompileId ?? {});
            // Copy input summaries to skrub node ids so selecting skrub_0 shows data when backend
            // emitted input_summary with compile node id (e.g. as_X_1).
            setInputSummaryByNode((prev) => {
              const nodes = event.graph?.nodes ?? [];
              const runnable = compileNodesRef.current.filter(
                (n) => (n.type ?? "").toLowerCase() === "input" || (n.type ?? "").toLowerCase() === "operator"
              );
              let next = { ...prev };
              for (const sn of nodes) {
                if (sn.is_sempipes_semantic) continue;
                const compileNode = runnable.find(
                  (n) => (n.label ?? "") === (sn.label ?? "") && (n.type ?? "").toLowerCase() === "input"
                );
                if (compileNode && prev[compileNode.id]) {
                  next[`skrub_${sn.id}`] = prev[compileNode.id];
                }
              }
              return next;
            });
          }
        } else if (event.type === "done") {
          if (event.total_cost_usd != null) setLastRunCostUsd(event.total_cost_usd);
          setIsExecuting(false);
          executeAbortRef.current = null;
        }
      } catch (e) {
        setLastRunError(e instanceof Error ? e.message : String(e));
        setIsExecuting(false);
        executeAbortRef.current = null;
      }
    }, loadedScriptId);
    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting, llmName, temperature, validateTemperature, loadedScriptId]);

  useEffect(() => {
    let cancelled = false;
    listPipelineScripts()
      .then(({ scripts }) => {
        if (cancelled) return;
        setPipelineScripts(scripts ?? []);
        const defaultId = scripts?.some((s) => s.id === DEFAULT_SCRIPT_ID)
          ? DEFAULT_SCRIPT_ID
          : scripts?.[0]?.id;
        if (defaultId) {
          if (!cancelled) setLoadedScriptId(defaultId);
          return getPipelineScriptContent(defaultId)
            .then(({ content }) => {
              if (!cancelled) setPipelineCode(content);
            })
            .catch(() => {
              if (!cancelled) setPipelineCode("# Failed to load script: " + defaultId + "\n");
            });
        }
      })
      .catch(() => {
        if (!cancelled) setPipelineCode("# Failed to load scripts. Is the backend running?\n");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // When pipeline code changes: clear selection and live run data so graph and details stay in sync.
  useEffect(() => {
    setSelectedNodeId(null);
    setHighlightedNodeIds([]);
    setLiveNodeCode({});
    setLiveNodeRetries({});
    setLiveNodeCostUsd({});
    setStatusByNodeId({});
    setInputSummaryByNode({});
    setLastRunCostUsd(null);
    setSkrubGraph(null);
    setSkrubToCompileId({});
    setCompileError(null);
  }, [pipelineCode]);

  useEffect(() => {
    const t = setTimeout(refreshCompileGraph, 400);
    return () => clearTimeout(t);
  }, [refreshCompileGraph]);

  // Always use compile graph (same flow as skrub, from code only). Do not replace with skrub graph after run.
  const compilePreviewGraph = compileToSkrubGraph(compileNodes, compileEdges ?? []);
  const displayGraph = compilePreviewGraph;
  const isPreviewGraph = !!compilePreviewGraph?.nodes?.length;

  const nodes: GraphNode[] =
    compileNodes.length > 0
      ? compileNodes
          .filter(
            (n) =>
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
  const selectedNode = (() => {
    if (!selectedNodeId) return null;
    if (selectedNodeId.startsWith("skrub_") && displayGraph?.nodes) {
      const nid = skrubIdToRaw(selectedNodeId);
      const graphNode = displayGraph.nodes.find((n) => n.id === nid);
      if (graphNode) {
        const isOperator = Boolean(displayGraph.sempipesNodeIds?.includes(nid));
        return {
          id: selectedNodeId,
          type: (isOperator ? "operator" : "input") as "input" | "operator",
          label: graphNode.label,
        };
      }
    }
    return nodes.find((n) => n.id === selectedNodeId) ?? null;
  })();

  // Map compile node IDs (from editor) → skrub display IDs for graph highlighting
  const highlightedSkrubIds = compileIdsToSkrubIds(
    highlightedNodeIds,
    displayGraph?.nodes ?? [],
    compileNodes,
    false
  );

  // Input summary for selected input node: map skrub_X → compile node by id or label → inputSummaryByNode
  const inputSummaryForSelectedNode = (() => {
    if (!selectedNodeId?.startsWith("skrub_") || !displayGraph?.nodes) return undefined;
    const nid = skrubIdToRaw(selectedNodeId);
    const graphNode = displayGraph.nodes.find((n) => n.id === nid);
    if (!graphNode) return undefined;
    const compileNode = compileNodes.find(
      (n) => n.id === nid || (n.label === graphNode.label && (n.type ?? "").toLowerCase() === "input")
    );
    return compileNode ? inputSummaryByNode[compileNode.id] : undefined;
  })();

  const nodeIds = new Set(nodes.map((n) => n.id));
  const graphEdges = (compileEdges ?? []).filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );
  const runnableNodeIds = nodes.map((n) => n.id);

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
        skrubToCompileId,
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
    [
      displayGraph?.nodes,
      compileNodes,
      skrubToCompileId,
      runnableNodeIds,
    ]
  );

  // Compute panel widths based on expanded state
  const leftWidth = expandedPanel === 'left' ? '80%' : expandedPanel === null ? '33%' : '10%';
  const middleWidth = expandedPanel === 'middle' ? '80%' : expandedPanel === null ? '34%' : '10%';
  const rightWidth = expandedPanel === 'right' ? '80%' : expandedPanel === null ? '33%' : '10%';

  return (
    <div className="flex flex-col h-screen bg-slate-200 text-zinc-900 font-sans min-w-[1280px]">
      <div className="flex flex-1 min-h-0 gap-4 p-4">
        {/* Left: Pipeline editor (notebook-cell style) with Run in corner */}
        <div className="min-w-[280px] flex flex-col min-h-0 rounded-lg border border-slate-300 bg-white overflow-hidden shadow-md transition-all duration-300" style={{ width: leftWidth }}>
          <div className="shrink-0 px-3 py-2 border-b border-slate-300 bg-slate-100">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex flex-col gap-2 flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-zinc-500">LLM:</span>
                  <select
                    value={llmName}
                    onChange={(e) => setLlmName(e.target.value)}
                    disabled={isExecuting}
                    className="text-xs px-2 py-1 rounded border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-50 text-zinc-700"
                    title="Select LLM model"
                  >
                    {AVAILABLE_LLMS.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <span className="text-xs text-zinc-500 ml-2">Temperature:</span>
                  <div className="flex flex-col gap-0.5">
                    <input
                      type="text"
                      value={temperature}
                      onChange={(e) => handleTemperatureChange(e.target.value)}
                      disabled={isExecuting}
                      className={`text-xs px-2 py-1 rounded border bg-white hover:bg-slate-100 disabled:opacity-50 w-16 transition-colors ${
                        temperatureError
                          ? "border-red-500 bg-red-50 text-red-900"
                          : "border-slate-300 text-zinc-700"
                      } ${temperatureShake ? "animate-shake" : ""}`}
                      placeholder="0.0"
                      title="LLM temperature (0-2)"
                    />
                    {temperatureError && (
                      <span className="text-[10px] text-red-600 whitespace-nowrap">
                        Must be 0-2
                      </span>
                    )}
                  </div>
                  {lastRunCostUsd != null && lastRunCostUsd > 0 && (
                    <span className="text-xs text-zinc-500 ml-2" title="LLM cost from last run">
                      ${lastRunCostUsd.toFixed(6)}
                    </span>
                  )}
                  {lastRunError && (
                    <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 border border-red-300 ml-2" title={lastRunError}>
                      ⚠ Failed
                    </span>
                  )}
                  {!isExecuting && !lastRunError && lastRunCostUsd != null && (
                    <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-300 ml-2" title="Pipeline executed successfully">
                      ✓ Success
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-zinc-500">Load script:</span>
                  {(pipelineScripts ?? []).map(({ id, label }) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => handleLoadScript(id)}
                      disabled={isExecuting}
                      className="text-xs px-2 py-1 rounded border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-50 text-zinc-700"
                    >
                      {label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={handlePlay}
                    disabled={isExecuting}
                    className="shrink-0 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center gap-1.5 ml-2"
                    title={isExecuting ? "Stop execution" : "Run pipeline"}
                  >
                    {isExecuting ? (
                      <>Stop</>
                    ) : (
                      <>
                        <span aria-hidden>▶</span> Run
                      </>
                    )}
                  </button>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === 'left' ? null : 'left')}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 text-zinc-600 text-2xl transition-colors"
                title={expandedPanel === 'left' ? "Restore panel size" : "Expand panel"}
                aria-label={expandedPanel === 'left' ? "Restore panel size" : "Expand panel"}
                data-testid="expand-left-panel"
              >
                {expandedPanel === 'left' ? '⤡' : '⤢'}
              </button>
            </div>
            {lastRunError != null && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5" role="alert">
                Run error: {lastRunError}
              </p>
            )}
            {compileError != null && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5" role="alert">
                Compile error: {compileError}
              </p>
            )}
          </div>
          <div className="flex-1 min-h-0">
            <InputEditor
              value={pipelineCode}
              onChange={setPipelineCode}
              disabled={isExecuting}
              nodeRanges={compileNodes.filter((n): n is CompileNode & { source_range: NonNullable<CompileNode["source_range"]> } => n.source_range != null)}
              onHighlightNodes={setHighlightedNodeIds}
              onSelectNode={(nodeId) => {
                setHighlightedNodeIds(nodeId ? [nodeId] : []);
                // When selecting from code (compile ID) and we have a graph, use display ID
                // so graph shows selection; NodeDetailsPanel resolves both
                if (nodeId && !nodeId.startsWith("skrub_") && displayGraph?.nodes) {
                  const compileNode = compileNodes.find((n) => n.id === nodeId);
                  const graphNode = compileNode
                    ? displayGraph.nodes.find((n) => (n.label ?? "") === (compileNode.label ?? "") || n.id === nodeId)
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
              isExpanded={expandedPanel === 'left'}
            />
          </div>
        </div>

        {/* Middle: Computation graph — placeholder before run, skrub native graph after */}
        <div className="min-w-[200px] flex flex-col min-h-0 transition-all duration-300" style={{ width: middleWidth }}>
          <GraphPanel
            selectedNodeId={selectedNodeId}
            onSelectNode={handleGraphNodeSelect}
            nodes={nodes}
            edges={graphEdges}
            skrubGraph={displayGraph}
            runnableNodeIds={runnableNodeIds}
            isLoading={isExecuting && !displayGraph}
            highlightedNodeIds={highlightedSkrubIds}
            statusByNodeId={statusByNodeId}
            showGraph={isExecuting || !!displayGraph}
            isPreview={isPreviewGraph}
            isExecuting={isExecuting}
            expandButton={
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === 'middle' ? null : 'middle')}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 text-zinc-600 text-2xl transition-colors"
                title={expandedPanel === 'middle' ? "Restore panel size" : "Expand panel"}
                aria-label={expandedPanel === 'middle' ? "Restore panel size" : "Expand panel"}
                data-testid="expand-middle-panel"
              >
                {expandedPanel === 'middle' ? '⤡' : '⤢'}
              </button>
            }
          />
        </div>

        {/* Right: Node details / results (live-updating during execution) */}
        <div className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300" style={{ width: rightWidth }}>
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
            isExecuting={isExecuting}
            nodeMetadata={null}
            isExpanded={expandedPanel === 'right'}
            expandButton={
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === 'right' ? null : 'right')}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 text-zinc-600 text-2xl transition-colors"
                title={expandedPanel === 'right' ? "Restore panel size" : "Expand panel"}
                aria-label={expandedPanel === 'right' ? "Restore panel size" : "Expand panel"}
                data-testid="expand-right-panel"
              >
                {expandedPanel === 'right' ? '⤡' : '⤢'}
              </button>
            }
          />
        </div>
      </div>
    </div>
  );
}
