import { useState, useCallback, useEffect, useRef } from "react";
import {
  compilePipeline,
  executePipelineStream,
  listPipelineScripts,
  getPipelineScriptContent,
  type CompileNode,
  type CompileEdge,
  type InputSummary,
  type PipelineScriptEntry,
} from "../api/client";
import { InputEditor } from "./InputEditor";
import { GraphPanel, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

const DEFAULT_SCRIPT_ID = "simple";

export function CodeGenDemo() {
  const [pipelineScripts, setPipelineScripts] = useState<PipelineScriptEntry[]>([]);
  const [pipelineCode, setPipelineCode] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);
  const [compileEdges, setCompileEdges] = useState<CompileEdge[]>([]);
  const [executionLog, setExecutionLog] = useState<string[]>([]);
  const [liveNodeCode, setLiveNodeCode] = useState<Record<string, string>>({});
  const [liveNodeRetries, setLiveNodeRetries] = useState<Record<string, number>>({});
  const [liveNodeCostUsd, setLiveNodeCostUsd] = useState<Record<string, number>>({});
  const [inputSummaryByNode, setInputSummaryByNode] = useState<Record<string, InputSummary>>({});
  const [lastRunCostUsd, setLastRunCostUsd] = useState<number | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const executeAbortRef = useRef<AbortController | null>(null);
  const compileAbortRef = useRef<AbortController | null>(null);

  const refreshCompileGraph = useCallback(async () => {
    if (compileAbortRef.current) compileAbortRef.current.abort();
    const controller = new AbortController();
    compileAbortRef.current = controller;
    try {
      const res = await compilePipeline(pipelineCode, { signal: controller.signal });
      setCompileNodes(res.nodes);
      setCompileEdges(res.edges ?? []);
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      setCompileNodes([]);
      setCompileEdges([]);
    } finally {
      if (compileAbortRef.current === controller) compileAbortRef.current = null;
    }
  }, [pipelineCode]);

  const handleLoadForkJoinDemo = useCallback(() => {
    setPipelineCode("# fork-join\n");
  }, []);

  const handleLoadScript = useCallback(async (id: string) => {
    try {
      const { content } = await getPipelineScriptContent(id);
      setPipelineCode(content);
    } catch {
      setPipelineCode("# Failed to load script: " + id + "\n");
    }
  }, []);

  const handlePlay = useCallback(() => {
    if (isExecuting && executeAbortRef.current) {
      executeAbortRef.current.abort();
      return;
    }
    setExecutionLog([]);
    setLiveNodeCode({});
    setLiveNodeRetries({});
    setLiveNodeCostUsd({});
    setInputSummaryByNode({});
    setLastRunCostUsd(null);
    setIsExecuting(true);
    const controller = executePipelineStream(pipelineCode, (event) => {
      if (event.type === "terminal") {
        setExecutionLog((prev) => [...prev, event.line]);
      } else if (event.type === "input_summary") {
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
        if (event.retries != null) {
          setLiveNodeRetries((prev) => ({ ...prev, [event.node_id]: event.retries }));
        }
        if (event.cost_usd != null) {
          setLiveNodeCostUsd((prev) => ({ ...prev, [event.node_id]: event.cost_usd }));
        }
      } else if (event.type === "cost") {
        setLastRunCostUsd(event.total_usd);
      } else if (event.type === "done") {
        if (event.total_cost_usd != null) setLastRunCostUsd(event.total_cost_usd);
        setIsExecuting(false);
        executeAbortRef.current = null;
      }
    });
    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting]);

  useEffect(() => {
    let cancelled = false;
    listPipelineScripts()
      .then(({ scripts }) => {
        if (cancelled) return;
        setPipelineScripts(scripts ?? []);
        const defaultId = scripts.some((s) => s.id === DEFAULT_SCRIPT_ID)
          ? DEFAULT_SCRIPT_ID
          : scripts[0]?.id;
        if (defaultId) {
          return getPipelineScriptContent(defaultId).then(({ content }) => {
            if (!cancelled) setPipelineCode(content);
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
    setInputSummaryByNode({});
    setLastRunCostUsd(null);
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
  const selectedNode = selectedNodeId ? (nodes.find((n) => n.id === selectedNodeId) ?? null) : null;

  const nodeIds = new Set(nodes.map((n) => n.id));
  const graphEdges = (compileEdges ?? []).filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );

  return (
    <div className="flex flex-col h-screen bg-slate-50 text-zinc-900 font-sans min-w-[1280px]">
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-white shrink-0">
        <h1 className="text-lg font-medium text-zinc-800">Sempipes pipeline demo</h1>
        {lastRunCostUsd != null && lastRunCostUsd > 0 && (
          <span className="text-sm text-zinc-500" title="LLM cost from last run">
            Cost: ${lastRunCostUsd.toFixed(6)}
          </span>
        )}
      </header>

      <div className="flex flex-1 min-h-0 gap-4 p-4">
        {/* Left: Pipeline editor (notebook-cell style) with Run in corner */}
        <div className="w-[33%] min-w-[280px] flex flex-col min-h-0 rounded-lg border border-slate-200 bg-white overflow-hidden shadow-sm">
          <div className="shrink-0 flex flex-col gap-2 px-3 py-2 border-b border-slate-200 bg-slate-50/80">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-zinc-500 font-mono" aria-hidden>
                [ ]
              </span>
              <span className="text-sm text-zinc-600 flex-1 truncate">Pipeline (Python / sempipes)</span>
              <button
              type="button"
              onClick={handlePlay}
              disabled={isExecuting}
              className="shrink-0 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center gap-1.5"
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
            </div>
          </div>
          <div className="flex-1 min-h-0">
            <InputEditor
              value={pipelineCode}
              onChange={setPipelineCode}
              disabled={isExecuting}
              nodeRanges={compileNodes.filter((n) => n.source_range != null)}
              onHighlightNodes={setHighlightedNodeIds}
              onSelectNode={setSelectedNodeId}
              selectedNodeId={selectedNodeId}
            />
          </div>
        </div>

        {/* Middle: Interactive graph */}
        <div className="w-[34%] min-w-[200px] flex flex-col min-h-0">
          <GraphPanel
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            nodes={nodes}
            edges={graphEdges}
            isLoading={false}
            highlightedNodeIds={highlightedNodeIds}
            onLoadForkJoinDemo={handleLoadForkJoinDemo}
          />
        </div>

        {/* Right: Node details / results (live-updating during execution) */}
        <div className="w-[33%] min-w-[280px] flex flex-col min-h-0">
          <NodeDetailsPanel
            selectedNodeId={selectedNodeId}
            selectedNode={selectedNode}
            generatedCode={null}
            liveGeneratedCodeByNode={liveNodeCode}
            liveRetriesByNode={liveNodeRetries}
            liveCostUsdByNode={liveNodeCostUsd}
            inputSummaryByNode={inputSummaryByNode}
            isExecuting={isExecuting}
            nodeMetadata={null}
          />
        </div>
      </div>
    </div>
  );
}
