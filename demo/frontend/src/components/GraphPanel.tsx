/**
 * Middle panel: interactive graph from the scrub-compiled pipeline.
 * Nodes are clickable; selection drives the right-panel content.
 * TODO: Replace mock graph with real compiled graph from backend.
 */
export interface GraphNode {
  id: string;
  type: "input" | "operator";
  label: string;
}

interface GraphPanelProps {
  /** Currently selected node id (from graph click). */
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  /** Compiled graph nodes; when backend provides graph, pass here. */
  nodes?: GraphNode[];
  /** Whether pipeline is compiling / graph is loading. */
  isLoading?: boolean;
  /** Node ids to highlight (from code cursor/click in left panel). */
  highlightedNodeIds?: string[];
}

const MOCK_NODES: GraphNode[] = [
  { id: "input", type: "input", label: "Input" },
  { id: "op1", type: "operator", label: "Op" },
];

export function GraphPanel({
  selectedNodeId,
  onSelectNode,
  nodes = MOCK_NODES,
  isLoading = false,
  highlightedNodeIds = [],
}: GraphPanelProps) {
  const highlightedSet = new Set(highlightedNodeIds);

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b border-slate-200">
        <h2 className="text-sm font-medium text-zinc-700">Compiled graph</h2>
        <p className="text-xs text-zinc-500 mt-0.5">Click a node or move cursor in code to highlight</p>
      </div>
      <div className="flex-1 min-h-0 p-4 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-zinc-500 text-sm">
            Compiling…
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {nodes.map((node) => {
              const isSelected = selectedNodeId === node.id;
              const isHighlighted = highlightedSet.has(node.id);
              return (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => onSelectNode(isSelected ? null : node.id)}
                  className={`
                    w-full text-left px-3 py-2 rounded-lg border transition-colors
                    ${isSelected
                      ? "border-emerald-500 bg-emerald-500/15 text-zinc-900"
                      : isHighlighted
                        ? "border-emerald-400 bg-emerald-50 text-zinc-800 ring-1 ring-emerald-200"
                        : "border-slate-200 bg-slate-50/80 text-zinc-700 hover:border-slate-300 hover:bg-slate-100"
                    }
                  `}
                >
                  <span className="text-xs text-zinc-500 uppercase tracking-wider">{node.type}</span>
                  <span className="block font-medium">{node.label}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
