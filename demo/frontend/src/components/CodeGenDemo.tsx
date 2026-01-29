import { useState, useCallback, useEffect, useRef } from "react";
import { useCodeGen } from "../hooks/useCodeGen";
import { compilePipeline, executePipelineStream, type CompileNode, type CompileEdge } from "../api/client";
import { InputEditor } from "./InputEditor";
import { GraphPanel, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";
import { TerminalPanel } from "./TerminalPanel";

const defaultPipelineCode = `# Pipeline inspired by sempipes/demo.ipynb
# Edit and click Compile to update the graph

import sempipes
from sempipes import sem_choose

basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets with product transactions")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Binary flag for fraudulent basket")

products = products.sem_fillna(
  target_column="make",
  nl_prompt="Infer the manufacturer from product attributes.",
)

kept = kept_products.sem_gen_features(
  nl_prompt="Generate brand- and manufacturer-related features.",
  how_many=5,
)

fraud_detector = augmented_baskets.skb.apply_with_sem_choose(
  hgb,
  y=fraud_flags,
  choices=sem_choose(name="hgb_choices", max_depth="Common range for tree depth"),
)
`;

export function CodeGenDemo() {
  const [pipelineCode, setPipelineCode] = useState(defaultPipelineCode);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);
  const [compileEdges, setCompileEdges] = useState<CompileEdge[]>([]);
  const [executionLog, setExecutionLog] = useState<string[]>([]);
  const [liveNodeCode, setLiveNodeCode] = useState<Record<string, string>>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const executeAbortRef = useRef<AbortController | null>(null);

  const { mutateAsync: generate, isPending, data, error } = useCodeGen();

  const handleCompile = useCallback(() => {
    generate({
      input_code: pipelineCode,
      options: { optimization_level: 2, target: "cpp" },
    });
  }, [pipelineCode, generate]);

  const refreshCompileGraph = useCallback(async () => {
    try {
      const res = await compilePipeline(pipelineCode);
      setCompileNodes(res.nodes);
      setCompileEdges(res.edges ?? []);
    } catch {
      setCompileNodes([]);
      setCompileEdges([]);
    }
  }, [pipelineCode]);

  const handlePlay = useCallback(() => {
    if (isExecuting && executeAbortRef.current) {
      executeAbortRef.current.abort();
      return;
    }
    setExecutionLog([]);
    setLiveNodeCode({});
    setIsExecuting(true);
    const controller = executePipelineStream(pipelineCode, (event) => {
      if (event.type === "terminal") {
        setExecutionLog((prev) => [...prev, event.line]);
      } else if (event.type === "node_code") {
        setLiveNodeCode((prev) => ({ ...prev, [event.node_id]: event.generated_code }));
      } else if (event.type === "done") {
        setIsExecuting(false);
        executeAbortRef.current = null;
      }
    });
    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting]);

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePlay}
            disabled={isPending}
            className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors flex items-center gap-2"
          >
            {isExecuting ? (
              <>Stop</>
            ) : (
              <>
                <span aria-hidden>▶</span> Play
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleCompile}
            disabled={isPending || isExecuting}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
          >
            {isPending ? "Compiling…" : "Compile"}
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0 gap-4 p-4">
        {/* Left: Pipeline editor */}
        <div className="w-[33%] min-w-[280px] flex flex-col min-h-0 gap-2">
          <label className="text-sm text-zinc-600">Pipeline (Python / sempipes)</label>
          <div className="flex-1 min-h-0">
            <InputEditor
              value={pipelineCode}
              onChange={setPipelineCode}
              disabled={isPending}
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
            isLoading={isPending}
            highlightedNodeIds={highlightedNodeIds}
          />
        </div>

        {/* Right: Node details / results (live-updating during execution) */}
        <div className="w-[33%] min-w-[280px] flex flex-col min-h-0">
          <NodeDetailsPanel
            selectedNodeId={selectedNodeId}
            selectedNode={selectedNode}
            generatedCode={
              selectedNode?.type === "operator" ? (data?.generated_code ?? null) : null
            }
            liveGeneratedCodeByNode={
              isExecuting || Object.keys(liveNodeCode).length > 0 ? liveNodeCode : null
            }
            isExecuting={isExecuting}
            nodeMetadata={data?.metadata ?? null}
          />
        </div>
      </div>

      {/* Terminal output during execution */}
      <div className="shrink-0 px-4 pb-4">
        <TerminalPanel lines={executionLog} isRunning={isExecuting} />
      </div>

      {error && (
        <div className="mx-4 mb-4 px-4 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm shrink-0">
          {error.message}
        </div>
      )}
    </div>
  );
}
