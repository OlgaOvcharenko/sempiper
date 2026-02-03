/**
 * Middle panel: interactive graph from the scrub-compiled pipeline.
 * Graph follows skrub DAG: document order = data flow (see skrub DataOps describe_steps / draw_graph).
 * Renders nodes and edges; nodes are clickable; selection drives the right panel.
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
  /** When set (after Run), show skrub's DataOp.skb.draw_graph() SVG instead of static DAG. */
  skrubGraphSvg?: string | null;
  isLoading?: boolean;
  highlightedNodeIds?: string[];
  /** Optional expand button element to render in the header. */
  expandButton?: React.ReactNode;
}

const MOCK_NODES: GraphNode[] = [
  { id: "input", type: "input", label: "Input" },
  { id: "op1", type: "operator", label: "Op" },
];

// Skrub-style DAG: cascade downwards. Fixed sizes — nodes must not scale (see .cursor/rules).
const EDITOR_FONT_SIZE = 12;
const NODE_WIDTH = 100;
const NODE_HEIGHT = 36;
const GAP = 20;
const PADDING = 20;

/** Compute DAG levels from edges (0 = roots, then 1 + max predecessor level). */
function computeLevels(
  nodeIds: string[],
  edges: GraphEdge[]
): Map<string, number> {
  const idSet = new Set(nodeIds);
  const predecessors = new Map<string, string[]>();
  nodeIds.forEach((id) => predecessors.set(id, []));
  edges.forEach((e) => {
    if (idSet.has(e.source) && idSet.has(e.target)) {
      predecessors.get(e.target)!.push(e.source);
    }
  });
  const levels = new Map<string, number>();
  nodeIds.forEach((id) => levels.set(id, 0));
  let changed = true;
  while (changed) {
    changed = false;
    for (const id of nodeIds) {
      const preds = predecessors.get(id) ?? [];
      if (preds.length === 0) continue;
      const newLevel = 1 + Math.max(...preds.map((p) => levels.get(p) ?? 0));
      if (newLevel > (levels.get(id) ?? 0)) {
        levels.set(id, newLevel);
        changed = true;
      }
    }
  }
  return levels;
}

export function GraphPanel({
  selectedNodeId,
  onSelectNode,
  nodes = MOCK_NODES,
  edges = [],
  skrubGraphSvg = null,
  isLoading = false,
  highlightedNodeIds = [],
  expandButton = null,
}: GraphPanelProps) {
  const highlightedSet = new Set(highlightedNodeIds);
  const showSkrubSvg = Boolean(skrubGraphSvg?.trim());

  // DAG layout: group by level, distribute nodes per level horizontally
  const levels = computeLevels(nodes.map((n) => n.id), edges);
  const levelToNodes = new Map<number, GraphNode[]>();
  nodes.forEach((n) => {
    const lvl = levels.get(n.id) ?? 0;
    if (!levelToNodes.has(lvl)) levelToNodes.set(lvl, []);
    levelToNodes.get(lvl)!.push(n);
  });
  const sortedLevels = Array.from(levelToNodes.keys()).sort((a, b) => a - b);
  const nodePositions = new Map<string, { x: number; y: number }>();
  let svgWidth = PADDING * 2 + NODE_WIDTH;
  sortedLevels.forEach((lvl, levelIndex) => {
    const rowNodes = levelToNodes.get(lvl) ?? [];
    const rowWidth = rowNodes.length * NODE_WIDTH + (rowNodes.length - 1) * GAP;
    if (rowWidth + 2 * PADDING > svgWidth) svgWidth = rowWidth + 2 * PADDING;
    const y = PADDING + levelIndex * (NODE_HEIGHT + GAP);
    rowNodes.forEach((n, i) => {
      const x = PADDING + i * (NODE_WIDTH + GAP);
      nodePositions.set(n.id, { x, y });
    });
  });
  const svgHeight = Math.max(
    200,
    sortedLevels.length > 0
      ? PADDING * 2 + sortedLevels.length * (NODE_HEIGHT + GAP) - GAP
      : PADDING * 2 + NODE_HEIGHT
  );

  // Reference style: white nodes, solid black = data/conventional ops, dashed black = synthesized (sem_*) operators.
  const isSynthesizedOperator = (node: GraphNode) =>
    node.type === "operator" &&
    (node.label.startsWith("sem_") || node.label === "apply_with_sem_choose" || node.label === "sem_choose");
  const nodeFill = (isSelected: boolean, isHighlighted: boolean) => {
    if (isSelected) return "rgb(248, 250, 252)";
    if (isHighlighted) return "rgb(250, 250, 252)";
    return "white";
  };
  const nodeStroke = (node: GraphNode, isSelected: boolean, isHighlighted: boolean) => {
    if (isSelected || isHighlighted) return "rgb(30, 30, 30)";
    return "black";
  };
  const nodeStrokeDasharray = (node: GraphNode) => (isSynthesizedOperator(node) ? "5,4" : "none");
  const isTargetLabel = (node: GraphNode) => node.type === "input" && node.label === "as_y";

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-300 bg-white overflow-hidden shadow-md">
      <div className="shrink-0 px-3 py-2 border-b border-slate-300 bg-slate-100">
        <div className="flex items-center justify-between gap-2">
          <div className="flex-1">
            <h2 className="text-sm font-medium text-zinc-700">
              Computation graph{showSkrubSvg ? " (skrub native)" : ""}
            </h2>
            <p className="text-xs text-zinc-500 mt-0.5" title={showSkrubSvg ? "Skrub's native DataOp graph from execution" : "Static graph from code parsing. Run to see skrub's native graph."}>
              {showSkrubSvg
                ? "DataOp graph from execution · Shows all operations and data flow"
                : "Static preview · Run to see full skrub graph with all operations"}
            </p>
          </div>
          {expandButton}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2 flex justify-center">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-zinc-500 text-sm">Loading…</div>
        ) : showSkrubSvg ? (
          <div
            className="min-w-0 w-full h-full flex items-start justify-center skrub-graph-container"
            aria-label="Computation graph (skrub)"
            dangerouslySetInnerHTML={{ __html: skrubGraphSvg ?? "" }}
          />
        ) : (
          <svg
            width={svgWidth}
            height={svgHeight}
            className="shrink-0"
            style={{ minWidth: svgWidth, minHeight: svgHeight }}
            aria-label="Computation graph"
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
                <path d="M0,0 L8,4 L0,8 Z" fill="black" />
              </marker>
            </defs>
            {/* Edges: from bottom-center of source to top-center of target (black arrows) */}
            {edges.map((e, i) => {
              const srcPos = nodePositions.get(e.source);
              const tgtPos = nodePositions.get(e.target);
              if (!srcPos || !tgtPos) return null;
              const x1 = srcPos.x + NODE_WIDTH / 2;
              const y1 = srcPos.y + NODE_HEIGHT;
              const x2 = tgtPos.x + NODE_WIDTH / 2;
              const y2 = tgtPos.y;
              return (
                <line
                  key={`${e.source}-${e.target}-${i}`}
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="black"
                  strokeWidth="1.5"
                  markerEnd="url(#arrow)"
                />
              );
            })}
            {/* Nodes */}
            {nodes.map((node) => {
              const pos = nodePositions.get(node.id);
              if (!pos) return null;
              const isSelected = selectedNodeId === node.id;
              const isHighlighted = highlightedSet.has(node.id);
              return (
                <g key={node.id}>
                  <rect
                    x={pos.x}
                    y={pos.y}
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={6}
                    ry={6}
                    fill={nodeFill(isSelected, isHighlighted)}
                    stroke={nodeStroke(node, isSelected, isHighlighted)}
                    strokeWidth={isSelected || isHighlighted ? 2.5 : 1.5}
                    strokeDasharray={nodeStrokeDasharray(node)}
                    className="cursor-pointer"
                    data-testid={`graph-node-${node.id}`}
                    onClick={() => onSelectNode(isSelected ? null : node.id)}
                  />
                  <text
                    x={pos.x + NODE_WIDTH / 2}
                    y={pos.y + NODE_HEIGHT / 2 + EDITOR_FONT_SIZE / 2 - 2}
                    textAnchor="middle"
                    fill={isTargetLabel(node) ? "rgb(185, 28, 28)" : "black"}
                    style={{ fontSize: EDITOR_FONT_SIZE, fontWeight: 500 }}
                    pointerEvents="none"
                  >
                    {node.label.length > 12 ? node.label.slice(0, 10) + "…" : node.label}
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
