import { useState, useCallback, useEffect, useRef, useMemo } from "react";
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
    skrubIdToRaw,
} from "../utils/graphCodeSync";
import { GraphPanel } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";
import { OptimizerPanel } from "./OptimizerPanel";
import { OptimizerDetailsPanel } from "./OptimizerDetailsPanel";
import { PipelineEditorPanel } from "./PipelineEditorPanel";
import { fetchOptimizerStatus } from "../api/client";

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

const NEW_PIPELINE_ID = "new";

interface OptimizerDemoProps {
    layoutMode: 'toggled' | 'left-split';
    setLayoutMode: (mode: 'toggled' | 'left-split') => void;
    isDark: boolean;
}

export function OptimizerDemo({ layoutMode, isDark }: OptimizerDemoProps) {
    const [viewMode, setViewMode] = useState<'graph' | 'optimizer'>('optimizer');
    const [isGraphExpanded, setIsGraphExpanded] = useState(false);
    const [pipelineScripts, setPipelineScripts] = useState<PipelineScriptEntry[]>([]);
    const [pipelineCode, setPipelineCode] = useState(INITIAL_PIPELINE_CODE);
    const [loadedScriptId, setLoadedScriptId] = useState<string | null>(DEFAULT_SCRIPT_ID);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [selectedOptimizerTrial, setSelectedOptimizerTrial] = useState<any | null>(null);
    const [optimizerOperatorName, setOptimizerOperatorName] = useState<string | undefined>(undefined);
    const [activeOperatorName, setActiveOperatorName] = useState<string | undefined>(undefined);
    const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
    const [cursorFocusNodeId, setCursorFocusNodeId] = useState<string | null>(null);
    const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);
    const [compileEdges, setCompileEdges] = useState<CompileEdge[]>([]);
    const [, setCompileError] = useState<string | null>(null);
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
    const [temperature, setTemperature] = useState<string>("0.1");
    const [temperatureError, setTemperatureError] = useState(false);
    const [temperatureShake, setTemperatureShake] = useState(false);
    const [expandedPanel, setExpandedPanel] = useState<'left' | 'middle' | 'right' | null>(null);
    const [isOptimizerAvailable, setIsOptimizerAvailable] = useState(false);
    const [replayTrigger, setReplayTrigger] = useState(0);

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
    }, [pipelineCode, llmName, temperature, loadedScriptId]);

    const handleLoadScript = useCallback(async (id: string) => {
        setLoadedScriptId(id);
        if (id === NEW_PIPELINE_ID) {
            setSelectedOptimizerTrial(null);
            setPipelineCode(INITIAL_PIPELINE_CODE);
            return;
        }
        try {
            const res = await getPipelineScriptContent(id, "optimizer");
            setPipelineCode(res.content);
        } catch (err) {
            console.error("Failed to load script:", err);
            setPipelineCode(`# Failed to load script: ${id}`);
        }
    }, []);

    const validateTemperature = useCallback((value: string): boolean => {
        if (value.trim() === "") return false;
        const num = parseFloat(value);
        if (isNaN(num)) return false;
        return num >= 0 && num <= 2;
    }, []);

    const handleTemperatureChange = useCallback((value: string) => {
        setTemperature(value);
        const isInvalid = value.trim() !== "" && !validateTemperature(value);

        if (isInvalid) {
            setTemperatureError(true);
            setTemperatureShake(true);
            setTimeout(() => setTemperatureShake(false), 820);
        } else {
            setTemperatureError(false);
            setTemperatureShake(false);
        }
    }, [validateTemperature]);

    const handlePlay = useCallback(async () => {
        if (isExecuting && executeAbortRef.current) {
            executeAbortRef.current.abort();
            return;
        }

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

        const isSimulation = loadedScriptId && (
            loadedScriptId.includes('optimise_house') ||
            loadedScriptId.includes('optimise_fraud') ||
            loadedScriptId.includes('optimise_museums') ||
            loadedScriptId.includes('optimise_medium') ||
            loadedScriptId.includes('optimise_simple')
        );

        if (isSimulation) {
            setViewMode('optimizer');
            setSelectedOptimizerTrial(null);
            setReplayTrigger(prev => prev + 1);
            return;
        }

        setIsExecuting(true);

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
            scriptId: loadedScriptId && loadedScriptId !== NEW_PIPELINE_ID ? loadedScriptId : undefined,
            llmName,
            temperature: parseFloat(temperature),
            useCache: true,
        });
        executeAbortRef.current = controller;
    }, [pipelineCode, isExecuting, llmName, temperature, validateTemperature, loadedScriptId]);

    const handleClearCache = useCallback(async () => {
        if (isExecuting) return;
        try {
            await clearCache();
            setLastRunError("✓ Cache cleared");
            setTimeout(() => setLastRunError(null), 2000);
        } catch (e) {
            setLastRunError(`Failed to clear cache: ${e instanceof Error ? e.message : String(e)}`);
        }
    }, [isExecuting]);

    useEffect(() => {
        let cancelled = false;
        listPipelineScripts("optimizer")
            .then((res) => {
                if (cancelled) return;
                const scripts = res.scripts ?? [];

                // Always add "New" at the top
                const withNew: PipelineScriptEntry[] = [
                    { id: NEW_PIPELINE_ID, label: "— New Editable Pipeline —" },
                    ...scripts
                ];
                setPipelineScripts(withNew);

                // Try to load default if it exists in scripts, otherwise load New
                const defaultId = scripts.some(s => s.id === DEFAULT_SCRIPT_ID)
                    ? DEFAULT_SCRIPT_ID
                    : (scripts.length > 0 ? scripts[0].id : NEW_PIPELINE_ID);

                if (defaultId) {
                    setLoadedScriptId(defaultId);
                    if (defaultId === NEW_PIPELINE_ID) {
                        setPipelineCode(INITIAL_PIPELINE_CODE);
                    } else {
                        getPipelineScriptContent(defaultId, "optimizer")
                            .then((res) => {
                                if (!cancelled) setPipelineCode(res.content);
                            })
                            .catch(() => {
                                if (!cancelled) setPipelineCode(`# Failed to load script: ${defaultId}`);
                            });
                    }
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setPipelineScripts([{ id: NEW_PIPELINE_ID, label: "— New Editable Pipeline —" }]);
                    setLoadedScriptId(NEW_PIPELINE_ID);
                    setPipelineCode(INITIAL_PIPELINE_CODE);
                }
            });
        return () => { cancelled = true; };
    }, []);

    // Auto-trigger animation for simulated scripts when selected
    useEffect(() => {
        const isSimulation = loadedScriptId && (
            loadedScriptId.includes('optimise_house') ||
            loadedScriptId.includes('optimise_fraud') ||
            loadedScriptId.includes('optimise_museums') ||
            loadedScriptId.includes('optimise_medium') ||
            loadedScriptId.includes('optimise_simple')
        );

        if (isSimulation) {
            setViewMode('optimizer');
            setSelectedOptimizerTrial(null);
            // Small delay to ensure panel has mounted and trajectory is fetched
            const t = setTimeout(() => {
                setReplayTrigger(prev => prev + 1);
            }, 500);
            return () => clearTimeout(t);
        }
    }, [loadedScriptId]);

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
    }, [pipelineCode]);

    useEffect(() => {
        const t = setTimeout(refreshCompileGraph, 400);
        return () => clearTimeout(t);
    }, [refreshCompileGraph]);

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

    // The compile graph is always the canonical display graph.
    // Running the pipeline must NOT change the graph — only editing pipeline code does.
    const compilePreviewGraph = compileToSkrubGraph(compileNodes, compileEdges ?? []);
    const displayGraph = compilePreviewGraph;
    const isPreviewGraph = !!compilePreviewGraph?.nodes?.length;

    const nodes = useMemo(() => compileNodes.map((n) => ({
        id: n.id,
        type: (n.type?.toLowerCase() === "input" ? "input" : "operator") as "input" | "operator",
        label: n.label || n.id,
        color: n.id === activeOperatorName ? "#10b981" : undefined
    })), [compileNodes, activeOperatorName]);

    const runnableNodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);

    const graphEdges = useMemo(() => compileEdges.map((e) => ({
        source: e.source,
        target: e.target,
    })), [compileEdges]);

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
        [displayGraph?.nodes, compileNodes, skrubToCompileId, runnableNodeIds]
    );

    const getWidths = () => {
        const wL = expandedPanel === 'left' ? '80%' : expandedPanel === null ? '33.33%' : '10%';
        const wM = expandedPanel === 'middle' ? '80%' : expandedPanel === null ? '33.34%' : '10%';
        const wR = expandedPanel === 'right' ? '80%' : expandedPanel === null ? '33.33%' : '10%';
        return { w1: wL, w2: wM, w3: wR };
    };

    const { w1, w2, w3 } = getWidths();

    const selectedNode = selectedNodeId && !selectedNodeId.startsWith("skrub_")
        ? compileNodes.find((n) => n.id === selectedNodeId)
        : null;

    const inputSummaryForSelectedNode = selectedNodeId
        ? inputSummaryByNode[selectedNodeId] || nodeDataByNode[selectedNodeId]
        : undefined;

    const highlightedSkrubIds = useMemo(() => {
        return highlightedNodeIds
            .map((hid) => {
                const match = Object.entries(skrubToCompileId).find(([, cid]) => cid === hid);
                return match ? match[0] : hid;
            })
            .map((id) => (id.startsWith("skrub_") ? id : `skrub_${id}`));
    }, [highlightedNodeIds, skrubToCompileId]);

    const graphToggleButtons = isOptimizerAvailable ? (
        <div className="flex p-0.5 bg-slate-200 dark:bg-zinc-700 rounded-md border border-slate-300 dark:border-zinc-700">
            <button
                onClick={() => { setViewMode('graph'); setSelectedOptimizerTrial(null); }}
                className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-all ${viewMode === 'graph' ? 'bg-white dark:bg-zinc-900 text-emerald-600 shadow-sm' : 'text-zinc-500 dark:text-zinc-400'}`}
            >
                Graph
            </button>
            <button
                onClick={() => setViewMode('optimizer')}
                className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-all ${viewMode === 'optimizer' ? 'bg-white dark:bg-zinc-900 text-emerald-600 shadow-sm' : 'text-zinc-500 dark:text-zinc-400'}`}
            >
                Optimizer
            </button>
        </div>
    ) : null;

    function ExpandBtn({ panel }: { panel: 'left' | 'middle' | 'right' }) {
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
                <div className={`min-w-[280px] flex flex-col min-h-0 transition-all duration-300 ${layoutMode === 'left-split' ? 'gap-0' : 'gap-4'}`} style={{ width: w1 }}>
                    <PipelineEditorPanel
                        isExpanded={expandedPanel === 'left'}
                        onToggleExpand={() => setExpandedPanel(expandedPanel === 'left' ? null : 'left')}
                        isDark={isDark}
                        pipelineScripts={pipelineScripts}
                        loadedScriptId={loadedScriptId}
                        onLoadScript={handleLoadScript}
                        onPipelineCodeChange={setPipelineCode}
                        isExecuting={isExecuting}
                        onPlay={handlePlay}
                        onClearCache={handleClearCache}
                        llmName={llmName}
                        onLlmNameChange={setLlmName}
                        temperature={temperature}
                        onTemperatureChange={handleTemperatureChange}
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
                                    ? displayGraph.nodes.find((n) => (n.label ?? "") === (compileNode.label ?? "") || n.id === nodeId)
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
                        lastRunError={lastRunError}
                        lastRunDurationMs={lastRunDurationMs}
                        lastRunCostUsd={lastRunCostUsd}
                        isReadOnly={loadedScriptId !== NEW_PIPELINE_ID}
                        className={`${layoutMode === 'left-split' && isGraphExpanded ? 'flex-1 rounded-t-lg rounded-b-none shadow-none border-b-0' : 'flex-1'}`}
                    />
                    {layoutMode === 'left-split' && (
                        <div className={`transition-all duration-300 flex flex-col min-h-0 ${isGraphExpanded ? 'flex-1 min-h-[50%]' : 'h-[var(--header-height)] shrink-0'}`}>
                            <div
                                onClick={() => setIsGraphExpanded(!isGraphExpanded)}
                                className={`shrink-0 h-[var(--header-height)] px-4 border border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between cursor-pointer hover:bg-slate-200 dark:hover:bg-zinc-700 transition-colors ${isGraphExpanded ? 'rounded-b-lg rounded-t-none border-t shadow-none' : 'rounded-lg shadow-sm'}`}
                            >
                                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-300">Computational Graph</span>
                                <span className="text-zinc-400">
                                    {isGraphExpanded ? "▲" : "▼"}
                                </span>
                            </div>
                            {isGraphExpanded && (
                                <div className="flex-1 min-h-0 overflow-hidden">
                                    <GraphPanel
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

                <div className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4" style={{ width: w2 }}>
                    <div className="flex-1 min-h-0">
                        {viewMode === 'graph' && layoutMode === 'toggled' ? (
                            <GraphPanel
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
                                viewToggle={layoutMode === 'toggled' ? graphToggleButtons : null}
                            />
                        ) : (
                            <OptimizerPanel
                                scriptId={loadedScriptId && loadedScriptId !== NEW_PIPELINE_ID ? loadedScriptId : null}
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
                                viewToggle={layoutMode === 'toggled' ? graphToggleButtons : null}
                            />
                        )}
                    </div>
                </div>

                <div className="min-w-[280px] flex flex-col min-h-0 transition-all duration-300 gap-4" style={{ width: w3 }}>
                    <div className="flex flex-col min-h-0 overflow-hidden rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-md transition-all duration-300 flex-1">
                        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                            {viewMode === 'optimizer' || layoutMode !== 'toggled' ? (
                                <OptimizerDetailsPanel
                                    selectedTrial={selectedOptimizerTrial}
                                    operatorName={optimizerOperatorName}
                                    activeOperatorName={activeOperatorName}
                                    isDark={isDark}
                                    onOperatorClick={(name) => {
                                        setActiveOperatorName(name);
                                        const match = compileNodes.find(n => n.label?.toLowerCase() === name.toLowerCase());
                                        if (match) {
                                            setHighlightedNodeIds([match.id]);
                                            setCursorFocusNodeId(match.id);
                                        }
                                    }}
                                    isExpanded={expandedPanel === 'right'}
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
                                    liveFallbackByNode={liveFallbackByNode}
                                    liveCostUsdByNode={liveNodeCostUsd}
                                    inputSummaryByNode={inputSummaryByNode}
                                    inputSummaryForSelectedNode={inputSummaryForSelectedNode}
                                    nodeDataByNode={nodeDataByNode}
                                    isExecuting={isExecuting}
                                    skrubToCompileId={skrubToCompileId}
                                    isExpanded={expandedPanel === 'right'}
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
