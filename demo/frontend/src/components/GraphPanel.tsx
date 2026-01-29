/**
 * Middle panel: interactive graph from the scrub-compiled pipeline.
 * Renders nodes and edges as a DAG; nodes are clickable; selection drives the right panel.
 */
export interface GraphNode {
  id: string;
  type: "input" | "operator";
  label: string;
}

export interface GraphEdge {
  source: string;
  target: string;
}

interface GraphPanelProps {
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  isLoading?: boolean;
  highlightedNodeIds?: string[];
}

const MOCK_NODES: GraphNode[] = [
  { id: "input", type: "input", label: "Input" },
  { id: "op1", type: "operator", label: "Op" },
];

const NODE_WIDTH = 130;
const NODE_HEIGHT = 40;
const GAP = 28;

export function GraphPanel({
  selectedNodeId,
  onSelectNode,
  nodes = MOCK_NODES,
  edges = [],
  isLoading = false,
  highlightedNodeIds = [],
}: GraphPanelProps) {
  const highlightedSet = new Set(highlightedNodeIds);

  // Layout: vertical flow, centered. Edges connect bottom of source to top of target.
  const getNodePosition = (index: number) => ({
    x: 0.5, // fraction of width; we'll use % in SVG
    y: 24 + index * (NODE_HEIGHT + GAP),
  });

  const nodePositions = new Map<string | undefined, { x: number; y: number }>();
  nodes.forEach((n, i) => nodePositions.set(n.id, getNodePosition(i)));

  const svgHeight = Math.max(200, 48 + nodes.length * (NODE_HEIGHT + GAP) - GAP);

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b border-slate-200">
        <h2 className="text-sm font-medium text-zinc-700">Compiled graph</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Click a node or in code to select; hover in code to highlight
        </p>
      </div>
      <div className="flex-1 min-h-0 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-zinc-500 text-sm p-4">
            Compiling…
          </div>
        ) : (
          <svg
            className="w-full min-h-full"
            preserveAspectRatio="xMidYMin meet"
            viewBox={`0 0 200 ${svgHeight}`}
            style={{ minHeight: svgHeight }}
          >
            <defs>
              <marker
                id="arrow"
                markerWidth="8"
                markerHeight="8"
                refX="6"
                refY="4"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M0,0 L8,4 L0,8 Z" fill="rgb(148, 163, 184)" />
              </marker>
            </defs>
            {/* Edges */}
            {edges.map((e, i) => {
              const srcPos = nodePositions.get(e.source);
              const tgtPos = nodePositions.get(e.target);
              if (!srcPos || !tgtPos) return null;
              const x = 100;
              const y1 = srcPos.y + NODE_HEIGHT;
              const y2 = tgtPos.y;
              return (
                <line
                  key={`${e.source}-${e.target}-${i}`}
                  x1={x}
                  y1={y1}
                  x2={x}
                  y2={y2}
                  stroke="rgb(148, 163, 184)"
                  strokeWidth="1.5"
                  markerEnd="url(#arrow)"
                />
              );
            })}
            {/* Nodes */}
            {nodes.map((node, index) => {
              const pos = nodePositions.get(node.id);
              if (!pos) return null;
              const isSelected = selectedNodeId === node.id;
              const isHighlighted = highlightedSet.has(node.id);
              const x = 100 - NODE_WIDTH / 2;
              const y = pos.y;
              return (
                <g key={node.id}>
                  <rect
                    x={x}
                    y={y}
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={6}
                    ry={6}
                    fill={
                      isSelected
                        ? "rgb(209, 250, 229)"
                        : isHighlighted
                          ? "rgb(236, 253, 245)"
                          : "rgb(248, 250, 252)"
                    }
                    stroke={
                      isSelected
                        ? "rgb(16, 185, 129)"
                        : isHighlighted
                          ? "rgb(52, 211, 153)"
                          : "rgb(226, 232, 240)"
                    }
                    strokeWidth={isSelected ? 2.5 : 1.5}
                    className="cursor-pointer"
                    onClick={() => onSelectNode(isSelected ? null : node.id)}
                  />
                  <text
                    x={100}
                    y={y + NODE_HEIGHT / 2 - 6}
                    textAnchor="middle"
                    fill="rgb(113, 113, 122)"
                    style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}
                    pointerEvents="none"
                  >
                    {node.type}
                  </text>
                  <text
                    x={100}
                    y={y + NODE_HEIGHT / 2 + 6}
                    textAnchor="middle"
                    fill="rgb(39, 39, 42)"
                    style={{ fontSize: 12, fontWeight: 500 }}
                    pointerEvents="none"
                  >
                    {node.label.length > 14 ? node.label.slice(0, 12) + "…" : node.label}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
    </div>
  );
}
