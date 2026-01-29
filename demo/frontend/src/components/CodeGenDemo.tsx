import { useState, useCallback, useEffect } from "react";
import { useCodeGen } from "../hooks/useCodeGen";
import { compilePipeline, type CompileNode } from "../api/client";
import { InputEditor } from "./InputEditor";
import { GraphPanel, type GraphNode } from "./GraphPanel";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

const defaultPipelineCode = `# Declarative pipeline using sempipes
# Edit and click Compile to update the graph

from sempipes import pipeline, source, op

p = pipeline(
  source("input"),
  op("transform"),
)
`;

export function CodeGenDemo() {
  const [pipelineCode, setPipelineCode] = useState(defaultPipelineCode);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);

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
    } catch {
      setCompileNodes([]);
    }
  }, [pipelineCode]);

  useEffect(() => {
    const t = setTimeout(refreshCompileGraph, 400);
    return () => clearTimeout(t);
  }, [refreshCompileGraph]);

  const nodes: GraphNode[] =
    compileNodes.length > 0
      ? compileNodes
          .filter((n) => n.type === "input" || n.type === "operator")
          .map((n) => ({ id: n.id, type: n.type as "input" | "operator", label: n.label }))
      : [
          { id: "input", type: "input", label: "Input" },
          { id: "op1", type: "operator", label: "Op" },
        ];
  const selectedNode = selectedNodeId ? nodes.find((n) => n.id === selectedNodeId) ?? null : null;

  return (
    <div className="flex flex-col h-screen bg-slate-50 text-zinc-900 font-sans min-w-[1280px]">
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-white shrink-0">
        <h1 className="text-lg font-medium text-zinc-800">Sempipes pipeline demo</h1>
        <button
          type="button"
          onClick={handleCompile}
          disabled={isPending}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
        >
          {isPending ? "Compiling…" : "Compile"}
        </button>
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
            />
          </div>
        </div>

        {/* Middle: Interactive graph */}
        <div className="w-[34%] min-w-[200px] flex flex-col min-h-0">
          <GraphPanel
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            nodes={nodes}
            isLoading={isPending}
            highlightedNodeIds={highlightedNodeIds}
          />
        </div>

        {/* Right: Node details / results */}
        <div className="w-[33%] min-w-[280px] flex flex-col min-h-0">
          <NodeDetailsPanel
            selectedNodeId={selectedNodeId}
            selectedNode={selectedNode}
            generatedCode={selectedNode?.type === "operator" ? data?.generated_code ?? null : null}
            nodeMetadata={data?.metadata ?? null}
          />
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-4 px-4 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm shrink-0">
          {error.message}
        </div>
      )}
    </div>
  );
}
