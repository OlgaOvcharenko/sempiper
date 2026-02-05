import { useState, useCallback, useEffect, useRef } from "react";
import {
  compilePipeline,
  executePipelineStream,
  listPipelineScripts,
  getPipelineScriptContent,
  updateSempipesConfig,
  type CompileNode,
  type CompileEdge,
  type InputSummary,
  type PipelineScriptEntry,
  type SkrubGraphDict,
} from "../api/client";
import { InputEditor } from "./InputEditor";
import { GraphPanel, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

const DEFAULT_SCRIPT_ID = "simple";

/** Initial pipeline code (credit fraud + sem_fillna); matches pipeline_scripts/simple.py. */
const INITIAL_PIPELINE_CODE = `import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")

products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer the manufacturer from product attributes.",
    impute_with_existing_values_only=True,
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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
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
  const [isExecuting, setIsExecuting] = useState(false);
  const [llmName, setLlmName] = useState<string>("gemini/gemini-2.5-flash-lite");
  const [temperature, setTemperature] = useState<string>("0.0");
  const [temperatureError, setTemperatureError] = useState(false);
  const [temperatureShake, setTemperatureShake] = useState(false);
  const [expandedPanel, setExpandedPanel] = useState<'left' | 'middle' | 'right' | null>(null);
  const executeAbortRef = useRef<AbortController | null>(null);
  const compileAbortRef = useRef<AbortController | null>(null);

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
          if (event.graph) setSkrubGraph(event.graph);
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
    });
    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting, llmName, temperature, validateTemperature]);

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
    setCompileError(null);
  }, [pipelineCode]);

  useEffect(() => {
    const t = setTimeout(refreshCompileGraph, 400);
    return () => clearTimeout(t);
  }, [refreshCompileGraph]);

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
    if (selectedNodeId.startsWith("skrub_") && skrubGraph?.nodes) {
      const skid = selectedNodeId.slice(7);
      const skrubNode = skrubGraph.nodes.find((n) => n.id === skid);
      if (skrubNode) {
        const isOperator = Boolean(skrubGraph.sempipesNodeIds?.includes(skid));
        return {
          id: selectedNodeId,
          type: (isOperator ? "operator" : "input") as "input" | "operator",
          label: skrubNode.label,
        };
      }
    }
    return nodes.find((n) => n.id === selectedNodeId) ?? null;
  })();

  // Map compile node IDs (from editor) to skrub IDs for graph highlighting when skrub graph is shown
  const highlightedSkrubIds = (() => {
    if (!skrubGraph?.nodes?.length) return highlightedNodeIds;
    if (highlightedNodeIds.length === 0) return [];
    const result: string[] = [];
    for (const cid of highlightedNodeIds) {
      const compileNode = compileNodes.find((n) => n.id === cid);
      if (!compileNode) continue;
      for (const sn of skrubGraph.nodes) {
        if (sn.label === compileNode.label) result.push(`skrub_${sn.id}`);
      }
    }
    return [...new Set(result)];
  })();

  // Input summary for skrub-selected input node: map skrub_0 → compile node by label → inputSummaryByNode[compileNodeId]
  const inputSummaryForSelectedNode = (() => {
    if (!selectedNodeId?.startsWith("skrub_") || !skrubGraph?.nodes) return undefined;
    const skid = selectedNodeId.slice(7);
    const skrubNode = skrubGraph.nodes.find((n) => n.id === skid);
    if (!skrubNode) return undefined;
    const compileNode = compileNodes.find(
      (n) => n.label === skrubNode.label && (n.type ?? "").toLowerCase() === "input"
    );
    return compileNode ? inputSummaryByNode[compileNode.id] : undefined;
  })();

  const nodeIds = new Set(nodes.map((n) => n.id));
  const graphEdges = (compileEdges ?? []).filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );
  const runnableNodeIds = nodes.map((n) => n.id);

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
              onSelectNode={setSelectedNodeId}
              selectedNodeId={selectedNodeId}
              isExpanded={expandedPanel === 'left'}
            />
          </div>
        </div>

        {/* Middle: Computation graph — placeholder before run, skrub native graph after */}
        <div className="min-w-[200px] flex flex-col min-h-0 transition-all duration-300" style={{ width: middleWidth }}>
          <GraphPanel
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            nodes={nodes}
            edges={graphEdges}
            skrubGraph={skrubGraph}
            runnableNodeIds={runnableNodeIds}
            isLoading={isExecuting && !skrubGraph}
            highlightedNodeIds={highlightedSkrubIds}
            statusByNodeId={statusByNodeId}
            showGraph={isExecuting || !!skrubGraph}
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
