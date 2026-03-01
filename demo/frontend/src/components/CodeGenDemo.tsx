import { useState, useCallback, useEffect, useRef } from "react";
import {
  compilePipeline,
  executePipelineStream,
  listPipelineScripts,
  getPipelineScriptContent,
  updateSempipesConfig,
  compileToSkrubGraph,
  clearCache,
  type CompileNode,
  type CompileEdge,
  type InputSummary,
  type PipelineScriptEntry,
} from "../api/client";
import {
  graphNodeToCompileIds,
  compileIdsToSkrubIds,
  skrubIdToRaw,
} from "../utils/graphCodeSync";
// No theme import here anymore
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

/** Format duration in milliseconds to human-readable string. */
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
  const [mode] = useState<'normal' | 'optimizer'>('normal');
  const [normalScripts, setNormalScripts] = useState<PipelineScriptEntry[]>([]);
  const [optimizerScripts, setOptimizerScripts] = useState<PipelineScriptEntry[]>([]);
  const pipelineScripts = mode === 'normal' ? normalScripts : optimizerScripts;

  const [normalCode, setNormalCode] = useState(INITIAL_PIPELINE_CODE);
  const [optimizerCode, setOptimizerCode] = useState("");
  const pipelineCode = mode === 'normal' ? normalCode : optimizerCode;

  const [normalLoadedScriptId, setNormalLoadedScriptId] = useState<string | null>(DEFAULT_SCRIPT_ID);
  const [optimizerLoadedScriptId, setOptimizerLoadedScriptId] = useState<string | null>(null);
  const loadedScriptId = mode === 'normal' ? normalLoadedScriptId : optimizerLoadedScriptId;

  // We use the prop handed down from App.tsx
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
  const [inputSummaryByNode, setInputSummaryByNode] = useState<Record<string, InputSummary>>({});
  /** Intermediate data for operator nodes (from .skb.preview()). */
  const [nodeDataByNode, setNodeDataByNode] = useState<Record<string, InputSummary>>({});
  const [lastRunCostUsd, setLastRunCostUsd] = useState<number | null>(null);
  const [lastRunDurationMs, setLastRunDurationMs] = useState<number | null>(null);
  const [lastRunError, setLastRunError] = useState<string | null>(null);
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  compileNodesRef.current = compileNodes;

  const refreshCompileGraph = useCallback(async () => {
    if (compileAbortRef.current) compileAbortRef.current.abort();
    const controller = new AbortController();
    compileAbortRef.current = controller;
    setCompileError(null);
    try {
      const tempValue = parseFloat(temperature);
      const res = await compilePipeline(pipelineCode, {
        signal: controller.signal,
        scriptId: loadedScriptId,
        llmName,
        temperature: isNaN(tempValue) ? undefined : tempValue,
      });
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
  }, [pipelineCode, llmName, temperature]);

  const handleLoadScript = useCallback(async (id: string) => {
    if (mode === 'normal') setNormalLoadedScriptId(id); else setOptimizerLoadedScriptId(id);
    try {
      const { content } = await getPipelineScriptContent(id);
      if (mode === 'normal') setNormalCode(content); else setOptimizerCode(content);
    } catch {
      if (mode === 'normal') setNormalCode("# Failed to load script: " + id + "\n"); else setOptimizerCode("# Failed to load script: " + id + "\n");
    }
  }, [mode]);

  const handleFileUpload = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result;
      if (typeof content === "string") {
        if (mode === 'normal') {
          setNormalCode(content);
          setNormalLoadedScriptId(null);
        } else {
          setOptimizerCode(content);
          setOptimizerLoadedScriptId(null);
        }
      }
    };
    reader.readAsText(file);
    // Reset input so the same file can be uploaded again
    event.target.value = "";
  }, [mode]);

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
    setInputSummaryByNode({});
    setNodeDataByNode({});
    setLastRunCostUsd(null);
    setSkrubToCompileId({});
    setLastRunDurationMs(null);
    setLastRunError(null);
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
        } else if (event.type === "node_data") {
          // Intermediate data for operator nodes (from .skb.preview())
          setNodeDataByNode((prev) => ({
            ...prev,
            [event.node_id]: {
              node_id: event.node_id,
              schema: event.schema,
              sample: event.sample,
              row_count: event.row_count,
            },
          }));
        } else if (event.type === "node_code") {
          // Store code under both the raw ID and skrub-prefixed ID for graph lookup.
          // Graph display uses skrub_<compile_id> format, backend emits compile IDs.
          const nodeId = event.node_id;
          const skrubId = nodeId.startsWith("skrub_") ? nodeId : `skrub_${nodeId}`;
          setLiveNodeCode((prev) => ({
            ...prev,
            [nodeId]: event.generated_code,
            [skrubId]: event.generated_code,
          }));
          if (event.retries != null) {
            const retries = event.retries;
            setLiveNodeRetries((prev) => ({
              ...prev,
              [nodeId]: retries,
              [skrubId]: retries,
            }));
          }
          if (event.is_fallback != null) {
            const isFallback = event.is_fallback;
            setLiveFallbackByNode((prev) => ({
              ...prev,
              [nodeId]: isFallback,
              [skrubId]: isFallback,
            }));
          }
          if (event.cost_usd != null) {
            const cost = event.cost_usd;
            setLiveNodeCostUsd((prev) => ({
              ...prev,
              [nodeId]: cost,
              [skrubId]: cost,
            }));
          }
        } else if (event.type === "error") {
          setLastRunError(event.message);
        } else if (event.type === "cost") {
          setLastRunCostUsd(event.total_usd);
        } else if (event.type === "skrub_graph") {
          // Keep the skrub→compile ID mapping for node selection fallback,
          // but do NOT replace the display graph — the compile graph is canonical.
          if (event.skrubToCompileId) {
            setSkrubToCompileId(event.skrubToCompileId);
          }
        } else if (event.type === "done") {
          if (event.total_cost_usd != null) setLastRunCostUsd(event.total_cost_usd);
          if (event.duration_ms != null) setLastRunDurationMs(event.duration_ms);
          setIsExecuting(false);
          executeAbortRef.current = null;
        }
      } catch (e) {
        setLastRunError(e instanceof Error ? e.message : String(e));
        setIsExecuting(false);
        executeAbortRef.current = null;
      }
    }, {
      scriptId: loadedScriptId,
      llmName,
      temperature: parseFloat(temperature),
    });
    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting, llmName, temperature, validateTemperature, loadedScriptId]);

  const handleClearCache = useCallback(async () => {
    if (isExecuting) return;
    try {
      await clearCache();
      setLastRunError(null);
      // Show brief success message
      setLastRunError("✓ Cache cleared");
      setTimeout(() => {
        if (!isExecuting) setLastRunError(null);
      }, 2000);
    } catch (e) {
      setLastRunError(`Failed to clear cache: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [isExecuting]);

  useEffect(() => {
    let cancelled = false;

    // Load normal mode scripts
    listPipelineScripts('normal')
      .then(({ scripts }) => {
        if (cancelled) return;
        setNormalScripts(scripts ?? []);
        const defaultId = scripts?.some((s) => s.id === DEFAULT_SCRIPT_ID)
          ? DEFAULT_SCRIPT_ID
          : scripts?.[0]?.id;
        if (defaultId) {
          if (!cancelled) setNormalLoadedScriptId(defaultId);
          return getPipelineScriptContent(defaultId, 'normal')
            .then(({ content }) => {
              if (!cancelled) setNormalCode(content);
            })
            .catch(() => {
              if (!cancelled) setNormalCode("# Failed to load script: " + defaultId + "\n");
            });
        }
      })
      .catch((err) => {
        if (!cancelled) setNormalCode("# Failed to load scripts. Is the backend running?\n" + err);
      });

    // Load optimizer mode scripts
    listPipelineScripts('optimizer')
      .then(({ scripts }) => {
        if (cancelled) return;
        setOptimizerScripts(scripts ?? []);
        const defaultId = scripts?.[0]?.id;
        if (defaultId) {
          if (!cancelled) setOptimizerLoadedScriptId(defaultId);
          return getPipelineScriptContent(defaultId, 'optimizer')
            .then(({ content }) => {
              if (!cancelled) setOptimizerCode(content);
            })
            .catch(() => { });
        }
      })
      .catch(() => { });

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
    setInputSummaryByNode({});
    setNodeDataByNode({});
    setLastRunCostUsd(null);
    setLastRunDurationMs(null);
    setSkrubToCompileId({});
    setCompileError(null);
  }, [pipelineCode]);

  useEffect(() => {
    const t = setTimeout(refreshCompileGraph, 400);
    return () => clearTimeout(t);
  }, [refreshCompileGraph]);

  // The compile graph is always the canonical display graph.
  // Running the pipeline must NOT change the graph — only editing the pipeline code does.
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
        // Determine node type from compile nodes (not just sempipesNodeIds).
        // sempipesNodeIds only contains sem_* operators, but we want to show
        // generated code for ALL operators (skb.apply, skb.eval, etc.)
        // Use skrubToCompileId mapping to find the correct compile node
        const compileNodeId = skrubToCompileId[nid];
        const compileNode = compileNodeId ? compileNodes.find((n) => n.id === compileNodeId) : undefined;
        const compileType = (compileNode?.type ?? "").toLowerCase();
        const isOperator = compileType === "operator" || compileType === "pipeline" ||
          Boolean(displayGraph.sempipesNodeIds?.includes(nid));
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
    false  // always use compile graph; compile ids = graph ids in preview mode
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
    <div className="flex flex-col h-full bg-slate-200 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 font-sans min-w-[1280px]">
      <div className="flex flex-1 min-h-0 gap-4 px-4 pb-4 pt-4">
        {/* Left: Pipeline editor */}
        <div className="min-w-[280px] flex flex-col min-h-0 rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md transition-all duration-300" style={{ width: leftWidth }}>
          <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex flex-col justify-center gap-1">
            {/* Primary row: Script + Run */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <span className="text-xs text-zinc-500 dark:text-zinc-400">Pipeline:</span>
                <select
                  value={loadedScriptId ?? ""}
                  onChange={(e) => handleLoadScript(e.target.value)}
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
                  ref={fileInputRef}
                  type="file"
                  accept=".py,.txt"
                  onChange={handleFileUpload}
                  className="hidden"
                  data-testid="file-upload-input"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isExecuting}
                  className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-500 dark:text-zinc-400"
                  title="Upload script from file"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </button>
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
                <button
                  type="button"
                  onClick={handlePlay}
                  disabled={!isExecuting}
                  className={`p-1.5 rounded border transition-colors ${isExecuting
                    ? "border-red-600 bg-red-600 hover:bg-red-500 hover:border-red-500 text-white"
                    : "border-slate-300 dark:border-zinc-600 bg-slate-100 dark:bg-zinc-800 text-slate-300 dark:text-zinc-600 cursor-not-allowed"
                    }`}
                  title="Stop execution"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="6" width="12" height="12" />
                  </svg>
                </button>
                <button
                  type="button"
                  onClick={handleClearCache}
                  disabled={isExecuting}
                  className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed text-zinc-600 dark:text-zinc-400"
                  title="Clear all cache"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
              <button
                type="button"
                onClick={() => setExpandedPanel(expandedPanel === 'left' ? null : 'left')}
                className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                title={expandedPanel === 'left' ? "Restore panel size" : "Expand panel"}
                aria-label={expandedPanel === 'left' ? "Restore panel size" : "Expand panel"}
                data-testid="expand-left-panel"
              >
                {expandedPanel === 'left' ? '⤡' : '⤢'}
              </button>
            </div>
            {/* Secondary row: Model settings */}
            <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
              <div className="flex items-center gap-1.5">
                <span>Model:</span>
                <select
                  value={llmName}
                  onChange={(e) => setLlmName(e.target.value)}
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
                  onChange={(e) => handleTemperatureChange(e.target.value)}
                  disabled={isExecuting}
                  className={`text-xs px-1.5 py-0.5 rounded border disabled:opacity-50 w-12 transition-colors ${temperatureError
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
            {/* Error messages */}
            {lastRunError != null && (
              <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded px-2 py-1" role="alert">
                {lastRunError}
              </p>
            )}
            {compileError != null && (
              <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded px-2 py-1" role="alert">
                {compileError}
              </p>
            )}
          </div>
          <div className="flex-1 min-h-0">
            <InputEditor
              value={pipelineCode}
              onChange={mode === 'normal' ? setNormalCode : setOptimizerCode}
              disabled={isExecuting}
              isDark={isDark}
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
              sempipesNodeIds={compileNodes.filter((n) => (n.type ?? "").toLowerCase() === "operator" && (n.label ?? "").toLowerCase().startsWith("sem_")).map((n) => n.id)}
            />
          </div>
          {/* Stats panel - appears after execution */}
          {!isExecuting && lastRunDurationMs != null && (
            <div className="shrink-0 px-3 py-2 border-t border-slate-300 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 flex items-center gap-3 text-xs">
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
          )}
        </div>

        {/* Middle: Computation graph */}
        <div className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4" style={{ width: middleWidth }}>
          <div className="flex-1 min-h-0">
            {mode === 'normal' ? (
              <GraphPanel
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
                    onClick={() => setExpandedPanel(expandedPanel === 'middle' ? null : 'middle')}
                    className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                    title={expandedPanel === 'middle' ? "Restore panel size" : "Expand panel"}
                    aria-label={expandedPanel === 'middle' ? "Restore panel size" : "Expand panel"}
                    data-testid="expand-middle-panel"
                  >
                    {expandedPanel === 'middle' ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="4 14 10 14 10 20" />
                        <polyline points="20 10 14 10 14 4" />
                        <line x1="14" y1="10" x2="21" y2="3" />
                        <line x1="3" y1="21" x2="10" y2="14" />
                      </svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="15 3 21 3 21 9" />
                        <polyline points="9 21 3 21 3 15" />
                        <line x1="21" y1="3" x2="14" y2="10" />
                        <line x1="3" y1="21" x2="10" y2="14" />
                      </svg>
                    )}
                  </button>
                }
              />
            ) : (
              <div className="flex flex-col h-full rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-md overflow-hidden">
                <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
                  <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">Optimizer View</span>
                </div>
                <div className="flex-1 flex items-center justify-center p-6">
                  <div className="text-center space-y-3">
                    <div className="w-12 h-12 mx-auto rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-violet-500">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
                      </svg>
                    </div>
                    <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Optimizer Graph</p>
                    <p className="text-xs text-zinc-400 dark:text-zinc-500">Coming soon</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Node details / results (live-updating during execution) */}
        <div className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300" style={{ width: rightWidth }}>
          {mode === 'normal' ? (
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
              isExpanded={expandedPanel === 'right'}
              expandButton={
                <button
                  type="button"
                  onClick={() => setExpandedPanel(expandedPanel === 'right' ? null : 'right')}
                  className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl transition-colors"
                  title={expandedPanel === 'right' ? "Restore panel size" : "Expand panel"}
                  aria-label={expandedPanel === 'right' ? "Restore panel size" : "Expand panel"}
                  data-testid="expand-right-panel"
                >
                  {expandedPanel === 'right' ? (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="4 14 10 14 10 20" />
                      <polyline points="20 10 14 10 14 4" />
                      <line x1="14" y1="10" x2="21" y2="3" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="15 3 21 3 21 9" />
                      <polyline points="9 21 3 21 3 15" />
                      <line x1="21" y1="3" x2="14" y2="10" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  )}
                </button>
              }
            />
          ) : (
            <div className="flex flex-col h-full rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-md overflow-hidden">
              <div className="shrink-0 px-3 py-2 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">Optimizer Details</span>
              </div>
              <div className="flex-1 flex items-center justify-center p-6">
                <div className="text-center space-y-3">
                  <div className="w-12 h-12 mx-auto rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-violet-500">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                      <polyline points="10 9 9 9 8 9" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Optimizer Details</p>
                  <p className="text-xs text-zinc-400 dark:text-zinc-500">Coming soon</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
