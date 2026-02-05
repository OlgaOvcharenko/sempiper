/**
 * Middle panel: interactive graph from the pipeline run (skrub only).
 * Uses only the graph dictionary (nodes, parents, children from _Graph().run) — no SVG.
 * Renders interactive DAG: click nodes to select and inspect. Loading icon while pipeline runs.
 */
import type { SkrubGraphDict } from "../api/client";

export interface GraphNode {
  id: string;
  type: "input" | "operator";
  label: string;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export type NodeStatus = "idle" | "running" | "done" | "error";

interface GraphPanelProps {
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  /** Skrub DAG from _Graph().run(dag): nodes, parents, children — only source for visualization (no SVG). */
  skrubGraph?: SkrubGraphDict | null;
  /** Ordered compile node ids to map skrub node index -> compile node id for selection. */
  runnableNodeIds?: string[];
  isLoading?: boolean;
  highlightedNodeIds?: string[];
  /** Per-node status for badges (idle | running | done | error). */
  statusByNodeId?: Record<string, NodeStatus>;
  showGraph?: boolean;
  expandButton?: React.ReactNode;
}

const MOCK_NODES: GraphNode[] = [
  { id: "input", type: "input", label: "Input" },
  { id: "op1", type: "operator", label: "Op" },
];

// Graph layout constants
const EDITOR_FONT_SIZE = 12;
const NODE_WIDTH = 100;
const NODE_HEIGHT = 36;
const GAP = 20;
const PADDING = 20;

/** Compute DAG levels from skrub parents (0 = roots). */
function skrubLevels(graph: SkrubGraphDict): Map<string, number> {
  const { nodes, parents } = graph;
  const levels = new Map<string, number>();
  nodes.forEach((n) => levels.set(n.id, 0));
  let changed = true;
  while (changed) {
    changed = false;
    for (const n of nodes) {
      const preds = parents[n.id] ?? [];
      if (preds.length === 0) continue;
      const newLevel = 1 + Math.max(...preds.map((p) => levels.get(p) ?? 0));
      if (newLevel > (levels.get(n.id) ?? 0)) {
        levels.set(n.id, newLevel);
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
  skrubGraph = null,
  runnableNodeIds = [],
  isLoading = false,
  highlightedNodeIds = [],
  statusByNodeId = {},
  showGraph = false,
  expandButton = null,
}: GraphPanelProps) {
  const hasSkrubDict = Boolean(skrubGraph?.nodes?.length);
  const shouldShowSkrubDict = hasSkrubDict;

  const nodeFill = (isSelected: boolean, isHighlighted: boolean) => {
    if (isSelected) return "rgb(248, 250, 252)";
    if (isHighlighted) return "rgb(250, 250, 252)";
    return "white";
  };
  const nodeStroke = (_node: GraphNode, isSelected: boolean, isHighlighted: boolean) => {
    if (isSelected || isHighlighted) return "rgb(30, 30, 30)";
    return "black";
  };

  // Layout for skrub DAG (when skrubGraph dict is present)
  const skrubNodePositions = new Map<string, { x: number; y: number }>();
  let skrubSvgWidth = PADDING * 2 + NODE_WIDTH;
  let skrubSvgHeight = 200;
  if (skrubGraph && shouldShowSkrubDict) {
    const levels = skrubLevels(skrubGraph);
    const levelToNodes = new Map<number, typeof skrubGraph.nodes>();
    skrubGraph.nodes.forEach((n) => {
      const lvl = levels.get(n.id) ?? 0;
      if (!levelToNodes.has(lvl)) levelToNodes.set(lvl, []);
      levelToNodes.get(lvl)!.push(n);
    });
    const sortedLevels = Array.from(levelToNodes.keys()).sort((a, b) => a - b);
    sortedLevels.forEach((lvl, levelIndex) => {
      const rowNodes = levelToNodes.get(lvl) ?? [];
      const rowWidth = rowNodes.length * NODE_WIDTH + (rowNodes.length - 1) * GAP;
      if (rowWidth + 2 * PADDING > skrubSvgWidth) skrubSvgWidth = rowWidth + 2 * PADDING;
      const y = PADDING + levelIndex * (NODE_HEIGHT + GAP);
      rowNodes.forEach((n, i) => {
        const x = PADDING + i * (NODE_WIDTH + GAP);
        skrubNodePositions.set(n.id, { x, y });
      });
    });
    skrubSvgHeight = Math.max(
      200,
      sortedLevels.length > 0
        ? PADDING * 2 + sortedLevels.length * (NODE_HEIGHT + GAP) - GAP
        : PADDING * 2 + NODE_HEIGHT
    );
  }

  return (
    <div className="h-full flex flex-col rounded-lg border border-slate-300 bg-white overflow-hidden shadow-md">
      <div className="shrink-0 px-3 py-2 border-b border-slate-300 bg-slate-100">
        <div className="flex items-center justify-between gap-2">
          <div className="flex-1">
            <h2 className="text-sm font-medium text-zinc-700">Computation graph</h2>
            <p className="text-xs text-zinc-500 mt-0.5">
              {isLoading
                ? "Running pipeline…"
                : shouldShowSkrubDict
                  ? "Skrub graph (from run) · Click an operator to see generated code"
                  : "Run to see the skrub graph (nodes, parents, children from pipeline run)"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {expandButton}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2 flex justify-center">
        {shouldShowSkrubDict && skrubGraph ? (
          <svg
            width={skrubSvgWidth}
            height={skrubSvgHeight}
            viewBox={`0 0 ${skrubSvgWidth} ${skrubSvgHeight}`}
            className="shrink-0"
            role="img"
            aria-label="Computation graph (skrub DAG)"
            onClick={(e) => {
              if (e.target === e.currentTarget) onSelectNode(null);
            }}
          >
            <defs>
              <marker
                id="skrub-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="6"
                refY="4"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M0,0 L8,4 L0,8 Z" fill="rgb(55, 65, 81)" />
              </marker>
            </defs>
            {skrubGraph.nodes.flatMap((n) =>
              (skrubGraph.parents[n.id] ?? []).map((pid) => {
                const src = skrubNodePositions.get(pid);
                const tgt = skrubNodePositions.get(n.id);
                if (!src || !tgt) return [];
                const x1 = src.x + NODE_WIDTH / 2;
                const y1 = src.y + NODE_HEIGHT;
                const x2 = tgt.x + NODE_WIDTH / 2;
                const y2 = tgt.y;
                return [
                  <path
                    key={`${pid}->${n.id}`}
                    d={`M ${x1} ${y1} L ${x2} ${y2}`}
                    stroke="rgb(55, 65, 81)"
                    strokeWidth={1.2}
                    fill="none"
                    markerEnd="url(#skrub-arrow)"
                  />,
                ];
              })
            )}
            {skrubGraph.nodes.map((n) => {
              const pos = skrubNodePositions.get(n.id) ?? { x: PADDING, y: PADDING };
              const skrubNodeId = `skrub_${n.id}`;
              const isSempipesSemantic = skrubGraph.sempipesNodeIds?.includes(n.id) ?? n.is_sempipes_semantic ?? false;
              const isSelected = selectedNodeId === skrubNodeId;
              const isHighlighted = highlightedNodeIds.includes(skrubNodeId);
              const status = statusByNodeId[skrubNodeId] ?? "idle";
              return (
                <g
                  key={n.id}
                  transform={`translate(${pos.x}, ${pos.y})`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectNode(skrubNodeId);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelectNode(skrubNodeId);
                    }
                  }}
                  style={{ cursor: "pointer" }}
                  role="button"
                  tabIndex={0}
                  aria-label={`Graph node ${n.label}${isSempipesSemantic ? " (sempipes operator)" : ""}`}
                >
                  <rect
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={6}
                    ry={6}
                    fill={nodeFill(isSelected, isHighlighted)}
                    stroke={nodeStroke(n as GraphNode, isSelected, isHighlighted)}
                    strokeWidth={isSelected || isHighlighted ? 2 : 1}
                    strokeDasharray={isSempipesSemantic ? "5,4" : "none"}
                  />
                  <text
                    x={NODE_WIDTH / 2}
                    y={NODE_HEIGHT / 2 + 4}
                    textAnchor="middle"
                    fontSize={EDITOR_FONT_SIZE}
                    fill="rgb(24, 24, 27)"
                  >
                    {n.label}
                  </text>
                  {status === "running" && (
                    <circle
                      cx={NODE_WIDTH - 10}
                      cy={10}
                      r={4}
                      fill="rgb(59, 130, 246)"
                      className="animate-pulse"
                    />
                  )}
                  {status === "done" && (
                    <text x={NODE_WIDTH - 8} y={12} textAnchor="end" fontSize={10} fill="rgb(34, 197, 94)" data-testid="node-status-done">
                      ✓
                    </text>
                  )}
                  {status === "error" && (
                    <text x={NODE_WIDTH - 8} y={12} textAnchor="end" fontSize={10} fill="rgb(239, 68, 68)" data-testid="node-status-error">
                      ✗
                    </text>
                  )}
                  {n.label === "as_y" && (
                    <text
                      x={NODE_WIDTH - 8}
                      y={status !== "idle" ? NODE_HEIGHT - 4 : 12}
                      textAnchor="end"
                      fontSize={10}
                      fill="rgb(220, 38, 38)"
                    >
                      y
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        ) : isLoading ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div className="w-10 h-10 rounded-full border-2 border-slate-300 border-t-emerald-500 animate-spin" aria-label="Graph loading spinner" />
            <div className="text-sm text-zinc-500 font-medium">Generating graph…</div>
            <div className="text-xs text-zinc-400 max-w-xs">
              The pipeline is running. The graph will appear when compilation completes.
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div className="text-6xl text-zinc-300">📊</div>
            <div className="text-sm text-zinc-500 font-medium">No computation graph yet</div>
            <div className="text-xs text-zinc-400 max-w-xs">
              Click <span className="font-semibold text-emerald-600">Run</span> to execute the pipeline and see skrub&apos;s computation graph (DataOp.skb.draw_graph).
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
