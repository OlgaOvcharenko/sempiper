/**
 * Middle panel: interactive graph from the pipeline run (skrub only).
 * Uses only the graph dictionary (nodes, parents, children from _Graph().run) — no SVG.
 * Renders interactive DAG: click nodes to select and inspect. Loading icon while pipeline runs.
 */
import type { SkrubGraphDict } from "../api/client";
import { toSkrubId } from "../utils/graphCodeSync";

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
  /** True when showing compile preview (before Run); final graph is always skrub. */
  isPreview?: boolean;
  /** True when pipeline is executing (show "Running pipeline…" in subtitle). */
  isExecuting?: boolean;
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

/**
 * Order nodes within each level to match skrub SVG flow (e.g. baskets branch left, products branch right).
 * Roots: sort by min child index (branch used first in flow goes left).
 * Other levels: sort by median parent position (children under same branch stay grouped).
 */
function orderNodesByFlow(
  graph: SkrubGraphDict,
  levels: Map<string, number>,
  sortedLevels: number[]
): Map<number, typeof graph.nodes> {
  const { nodes, parents, children } = graph;
  const levelToNodes = new Map<number, typeof graph.nodes>();
  nodes.forEach((n) => {
    const lvl = levels.get(n.id) ?? 0;
    if (!levelToNodes.has(lvl)) levelToNodes.set(lvl, []);
    levelToNodes.get(lvl)!.push(n);
  });

  const nodeIndex = new Map<string, number>();
  nodes.forEach((n, i) => nodeIndex.set(n.id, i));

  const orderedLevelToNodes = new Map<number, typeof graph.nodes>();
  for (const lvl of sortedLevels) {
    const rowNodes = levelToNodes.get(lvl) ?? [];
    let sorted: typeof graph.nodes;
    if (lvl === 0) {
      sorted = [...rowNodes].sort((a, b) => {
        const aChildren = children[a.id] ?? [];
        const bChildren = children[b.id] ?? [];
        const aMin = aChildren.length > 0 ? Math.min(...aChildren.map((c) => nodeIndex.get(c) ?? 999)) : 999;
        const bMin = bChildren.length > 0 ? Math.min(...bChildren.map((c) => nodeIndex.get(c) ?? 999)) : 999;
        return aMin - bMin;
      });
    } else {
      sorted = [...rowNodes].sort((a, b) => {
        const aPreds = parents[a.id] ?? [];
        const bPreds = parents[b.id] ?? [];
        const parentPos = (nid: string): number => {
          const predLevel = levels.get(nid) ?? 0;
          const predRow = orderedLevelToNodes.get(predLevel) ?? [];
          const idx = predRow.findIndex((n) => n.id === nid);
          return idx >= 0 ? idx : 0;
        };
        const aMed = aPreds.length > 0
          ? aPreds.reduce((s, p) => s + parentPos(p), 0) / aPreds.length
          : 0;
        const bMed = bPreds.length > 0
          ? bPreds.reduce((s, p) => s + parentPos(p), 0) / bPreds.length
          : 0;
        return aMed - bMed;
      });
    }
    orderedLevelToNodes.set(lvl, sorted);
  }
  return orderedLevelToNodes;
}

/** Single clickable node in the skrub DAG. Uses pointer-events: bounding-box for reliable clicks. */
function SkrubGraphNode({
  node,
  position,
  skrubNodeId,
  isSelected,
  isHighlighted,
  isSempipesSemantic,
  status,
  onSelect,
}: {
  node: { id: string; label: string };
  position: { x: number; y: number };
  skrubNodeId: string;
  isSelected: boolean;
  isHighlighted: boolean;
  isSempipesSemantic: boolean;
  status: "idle" | "running" | "done" | "error";
  onSelect: () => void;
}) {
  const isActive = isSelected || isHighlighted;
  const fill = isActive ? "rgb(254, 249, 195)" : "white";
  const stroke = isActive ? "rgb(245, 158, 11)" : "black";

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect();
  };

  return (
    <g
      key={node.id}
      data-testid={`graph-node-${node.id}`}
      transform={`translate(${position.x}, ${position.y})`}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          onSelect();
        }
      }}
      style={{ cursor: "pointer", pointerEvents: "bounding-box" }}
      role="button"
      tabIndex={0}
      aria-label={`Graph node ${node.label}${isSempipesSemantic ? " (sempipes operator)" : ""}`}
    >
      <rect
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={6}
        ry={6}
        fill={fill}
        stroke={stroke}
        strokeWidth={isActive ? 3 : 1}
        strokeDasharray={isSempipesSemantic ? "5,4" : "none"}
        onClick={handleClick}
      />
      <text
        x={NODE_WIDTH / 2}
        y={NODE_HEIGHT / 2 + 4}
        textAnchor="middle"
        fontSize={EDITOR_FONT_SIZE}
        fill="rgb(24, 24, 27)"
        style={{ pointerEvents: "none" }}
      >
        {node.label}
      </text>
      {status === "running" && (
        <circle cx={NODE_WIDTH - 10} cy={10} r={4} fill="rgb(59, 130, 246)" className="animate-pulse" />
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
      {node.label === "as_y" && (
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
}

export function GraphPanel({
  selectedNodeId,
  onSelectNode,
  nodes: _nodes = MOCK_NODES,
  edges: _edges = [],
  skrubGraph = null,
  runnableNodeIds: _runnableNodeIds = [],
  isLoading = false,
  highlightedNodeIds = [],
  statusByNodeId = {},
  showGraph: _showGraph = false,
  isPreview = false,
  isExecuting = false,
  expandButton = null,
}: GraphPanelProps) {
  const hasSkrubDict = Boolean(skrubGraph?.nodes?.length);
  const shouldShowSkrubDict = hasSkrubDict;

  // Layout for skrub DAG (when skrubGraph dict is present)
  const skrubNodePositions = new Map<string, { x: number; y: number }>();
  let skrubSvgWidth = PADDING * 2 + NODE_WIDTH;
  let skrubSvgHeight = 200;
  if (skrubGraph && shouldShowSkrubDict) {
    const levels = skrubLevels(skrubGraph);
    const sortedLevels = Array.from(new Set(skrubGraph.nodes.map((n) => levels.get(n.id) ?? 0))).sort((a, b) => a - b);
    const levelToNodes = orderNodesByFlow(skrubGraph, levels, sortedLevels);
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
              {isLoading || (isExecuting && shouldShowSkrubDict)
                ? "Running pipeline…"
                : shouldShowSkrubDict
                  ? "Computation graph (from code) · Click an operator to see generated code"
                  : "Edit code to see computation graph"}
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
            {skrubGraph.nodes.map((n) => (
              <SkrubGraphNode
                key={n.id}
                node={n}
                position={skrubNodePositions.get(n.id) ?? { x: PADDING, y: PADDING }}
                skrubNodeId={toSkrubId(n.id)}
                isSelected={selectedNodeId === toSkrubId(n.id)}
                isHighlighted={highlightedNodeIds.includes(toSkrubId(n.id))}
                isSempipesSemantic={skrubGraph.sempipesNodeIds?.includes(n.id) ?? n.is_sempipes_semantic ?? false}
                status={statusByNodeId[toSkrubId(n.id)] ?? "idle"}
                onSelect={() => onSelectNode(toSkrubId(n.id))}
              />
            ))}
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
              Edit pipeline code to see the computation graph.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
