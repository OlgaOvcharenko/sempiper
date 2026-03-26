/**
 * Pure utility functions and constants for Cytoscape graph layout and element construction.
 * Extracted so they can be unit-tested independently of the DOM/Cytoscape runtime.
 *
 * Layout strategy: custom Sugiyama-style hierarchical layout (preset positions).
 *   1. Assign nodes to layers using the longest-path algorithm.
 *   2. Minimise edge crossings within each layer using the barycenter heuristic.
 *   3. Assign {x, y} coordinates based on layer and intra-layer position.
 *   4. Pass positions to Cytoscape as a "preset" layout.
 *
 * This gives deterministic, crossing-minimal layouts without relying on dagre's
 * internal node-ordering heuristics.
 */

import { toSkrubId } from "./graphCodeSync";
import type { SkrubGraphDict } from "../api/client";

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

/** Horizontal pixel gap between adjacent node centres in the same layer. */
export const NODE_SEP = 240;

/** Vertical pixel gap between layer centres. */
export const RANK_SEP = 60;

/**
 * Cytoscape layout config for the preset layout.
 * Node {x,y} positions are computed by computePresetPositions() and
 * attached directly to each element before Cytoscape is initialised.
 */
export const PRESET_LAYOUT_CONFIG = {
  name: "preset",
  fit: true,
  padding: 30,
} as const;

/**
 * Edge curve style. "straight" draws direct lines between nodes.
 */
export const EDGE_CURVE_STYLE = "straight" as const;

// ---------------------------------------------------------------------------
// Node helpers
// ---------------------------------------------------------------------------

/**
 * Calculate the pixel width of a node based on its label length.
 * Ensures a minimum width so short labels are still readable.
 */
export function calculateNodeWidth(label: string): number {
  const minWidth = 70;
  const charWidth = 7;
  const padding = 24;
  return Math.max(minWidth, label.length * charWidth + padding);
}

/**
 * Infer the visual node type from its label.
 * Nodes whose label contains "var" are data-input nodes (blue); everything
 * else is an operator node (white / green for sempipes).
 */
export function inferNodeType(label: string): "input" | "operator" {
  if (!label) return "operator";
  return label.toLowerCase().includes("var") ? "input" : "operator";
}

// ---------------------------------------------------------------------------
// Sugiyama-style hierarchical layout
// ---------------------------------------------------------------------------

export interface LayoutPosition {
  x: number;
  y: number;
}

/**
 * Assign each node to a layer using the longest-path algorithm.
 *
 * Source nodes (no parents) receive layer 0; every other node receives
 * layer = max(parent.layer) + 1.
 *
 * Returns a map of raw node ID → layer index.
 */
export function assignLayers(skrubGraph: SkrubGraphDict): Map<string, number> {
  const parents = skrubGraph.parents ?? {};
  const layers = new Map<string, number>();
  const visited = new Set<string>();

  const visit = (nodeId: string) => {
    if (visited.has(nodeId)) return;
    visited.add(nodeId);
    for (const parentId of parents[nodeId] ?? []) {
      visit(parentId);
    }
    const parentLayers = (parents[nodeId] ?? []).map((p) => layers.get(p) ?? 0);
    layers.set(nodeId, parentLayers.length > 0 ? Math.max(...parentLayers) + 1 : 0);
  };

  for (const node of skrubGraph.nodes) {
    visit(node.id);
  }

  return layers;
}

/**
 * Minimise edge crossings using the barycenter heuristic.
 *
 * Alternates between top-down passes (sort each layer by average position of
 * parents) and bottom-up passes (sort by average position of children).
 * Multiple passes converge to a near-optimal ordering for tree-like DAGs.
 *
 * Returns a map of raw node ID → intra-layer position index (0-based).
 */
export function minimizeCrossings(
  skrubGraph: SkrubGraphDict,
  layers: Map<string, number>,
): Map<string, number> {
  const parents = skrubGraph.parents ?? {};
  const children = skrubGraph.children ?? {};

  // Group nodes by layer in their original (declaration) order
  const maxLayer = layers.size > 0 ? Math.max(...layers.values()) : 0;
  const nodesByLayer: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const node of skrubGraph.nodes) {
    nodesByLayer[layers.get(node.id) ?? 0].push(node.id);
  }

  // Initial intra-layer order
  const order = new Map<string, number>();
  for (const layer of nodesByLayer) {
    layer.forEach((n, i) => order.set(n, i));
  }

  const barycenter = (nodeId: string, neighbors: string[]): number => {
    if (neighbors.length === 0) return order.get(nodeId) ?? 0;
    const sum = neighbors.reduce((acc, n) => acc + (order.get(n) ?? 0), 0);
    return sum / neighbors.length;
  };

  for (let pass = 0; pass < 24; pass++) {
    if (pass % 2 === 0) {
      // Top-down: sort each layer by barycenter of its parents
      for (let k = 1; k < nodesByLayer.length; k++) {
        nodesByLayer[k].sort(
          (a, b) =>
            barycenter(a, parents[a] ?? []) - barycenter(b, parents[b] ?? []),
        );
        nodesByLayer[k].forEach((n, i) => order.set(n, i));
      }
    } else {
      // Bottom-up: sort each layer by barycenter of its children
      for (let k = nodesByLayer.length - 2; k >= 0; k--) {
        nodesByLayer[k].sort(
          (a, b) =>
            barycenter(a, children[a] ?? []) - barycenter(b, children[b] ?? []),
        );
        nodesByLayer[k].forEach((n, i) => order.set(n, i));
      }
    }
  }

  return order;
}

/**
 * Compute absolute {x, y} positions for all nodes using the Sugiyama approach:
 * longest-path layer assignment + barycenter crossing minimisation.
 *
 * Shorter layers are centred horizontally relative to the widest layer so that
 * parent-to-child edges remain as close to vertical as possible.
 *
 * Returns a map of raw node ID → {x, y}.
 */
export function computePresetPositions(
  skrubGraph: SkrubGraphDict,
  options: { nodeSep?: number; rankSep?: number } = {},
): Map<string, LayoutPosition> {
  const nodeSep = options.nodeSep ?? NODE_SEP;
  const rankSep = options.rankSep ?? RANK_SEP;

  const layers = assignLayers(skrubGraph);
  const order = minimizeCrossings(skrubGraph, layers);

  // Rebuild sorted layers from the ordering
  const maxLayer = layers.size > 0 ? Math.max(...layers.values()) : 0;
  const nodesByLayer: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const node of skrubGraph.nodes) {
    nodesByLayer[layers.get(node.id) ?? 0].push(node.id);
  }
  for (const layer of nodesByLayer) {
    layer.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
  }

  const maxNodesInAnyLayer = Math.max(...nodesByLayer.map((l) => l.length), 1);

  const positions = new Map<string, LayoutPosition>();
  for (let k = 0; k < nodesByLayer.length; k++) {
    const layer = nodesByLayer[k];
    // Centre shorter layers relative to the widest layer
    const layerOffset = ((maxNodesInAnyLayer - layer.length) / 2) * nodeSep;
    for (let i = 0; i < layer.length; i++) {
      positions.set(layer[i], {
        x: layerOffset + i * nodeSep + nodeSep / 2,
        y: k * rankSep + rankSep / 2,
      });
    }
  }

  return positions;
}

/**
 * Count the number of edge crossings between adjacent layers, given positions.
 *
 * Two edges (s1→t1) and (s2→t2) cross when:
 *  - Their source nodes are in the same layer (same y) AND
 *  - Their target nodes are in the same layer (same y) AND
 *  - The horizontal ordering of sources is the REVERSE of the ordering of targets.
 *
 * Used in tests to verify that the layout produces crossing-free graphs.
 */
export function countEdgeCrossings(
  positions: Map<string, LayoutPosition>,
  edges: Array<{ source: string; target: string }>,
): number {
  let crossings = 0;
  const EPSILON = 0.5;

  for (let i = 0; i < edges.length; i++) {
    for (let j = i + 1; j < edges.length; j++) {
      const s1 = positions.get(edges[i].source);
      const t1 = positions.get(edges[i].target);
      const s2 = positions.get(edges[j].source);
      const t2 = positions.get(edges[j].target);
      if (!s1 || !t1 || !s2 || !t2) continue;

      // Only compare edges whose endpoints lie in the same pair of layers
      if (
        Math.abs(s1.y - s2.y) > EPSILON ||
        Math.abs(t1.y - t2.y) > EPSILON
      )
        continue;

      // Crossing: source ordering is reversed relative to target ordering
      if ((s1.x - s2.x) * (t1.x - t2.x) < -EPSILON) {
        crossings++;
      }
    }
  }

  return crossings;
}

// ---------------------------------------------------------------------------
// Overlap detection
// ---------------------------------------------------------------------------

/** Pixel height of a node bounding box (matches GraphPanel height: 32). */
export const NODE_HEIGHT = 32;

/**
 * Detect edges whose visual path (linearly approximated) passes through the
 * bounding box of a node that is neither the edge's source nor its target.
 *
 * This catches "long edges" — edges spanning multiple layers — that Cytoscape
 * draws as a bezier curve passing straight through intermediate nodes.
 *
 * Positions and node IDs use the **raw** (non-skrub_-prefixed) node IDs, i.e.
 * the same keys used in SkrubGraphDict.parents.
 *
 * @param positions   Raw node ID → {x, y} from computePresetPositions.
 * @param nodeWidths  Raw node ID → pixel width (from calculateNodeWidth).
 * @param edges       Edges to check, using raw source/target IDs.
 * @returns List of {edge, overlappingNode} pairs.
 */
export function detectEdgeNodeOverlaps(
  positions: Map<string, LayoutPosition>,
  nodeWidths: Map<string, number>,
  edges: Array<{ source: string; target: string }>,
): Array<{ edge: { source: string; target: string }; overlappingNode: string }> {
  const result: Array<{
    edge: { source: string; target: string };
    overlappingNode: string;
  }> = [];
  const nodeIds = Array.from(positions.keys());
  const HALF_H = NODE_HEIGHT / 2;
  const SAMPLES = 30;

  for (const edge of edges) {
    const srcPos = positions.get(edge.source);
    const tgtPos = positions.get(edge.target);
    if (!srcPos || !tgtPos) continue;

    const reported = new Set<string>();

    for (let i = 1; i < SAMPLES; i++) {
      const t = i / SAMPLES;
      // Linear interpolation — accurate for mostly-vertical bezier curves
      const sampleX = srcPos.x + (tgtPos.x - srcPos.x) * t;
      const sampleY = srcPos.y + (tgtPos.y - srcPos.y) * t;

      for (const nodeId of nodeIds) {
        if (nodeId === edge.source || nodeId === edge.target) continue;
        if (reported.has(nodeId)) continue;

        const nodePos = positions.get(nodeId)!;
        const halfW = (nodeWidths.get(nodeId) ?? 70) / 2;

        if (
          sampleX >= nodePos.x - halfW &&
          sampleX <= nodePos.x + halfW &&
          sampleY >= nodePos.y - HALF_H &&
          sampleY <= nodePos.y + HALF_H
        ) {
          result.push({ edge, overlappingNode: nodeId });
          reported.add(nodeId);
        }
      }
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Post-layout waypoint routing for long edges
// ---------------------------------------------------------------------------

/**
 * Minimum pixel clearance between a waypoint x-position and any node's
 * horizontal bounding-box edge. Keeps the routed edge visually separated
 * from nodes it passes beside.
 */
export const WAYPOINT_CLEARANCE = 20;

/**
 * Find the x coordinate closest to `idealX` that is outside every padded
 * node bounding box at a given layer.
 *
 * When `idealX` is already clear, it is returned unchanged (no deviation).
 * When blocked, returns the nearest edge of the blocking merged interval
 * (left or right, whichever is closer to `idealX`).
 */
function findClearXPosition(
  idealX: number,
  layerNodeIds: string[],
  positions: Map<string, LayoutPosition>,
  nodeWidths: Map<string, number>,
): number {
  if (layerNodeIds.length === 0) return idealX;

  const obstacles: Array<[number, number]> = [];
  for (const id of layerNodeIds) {
    const pos = positions.get(id);
    if (!pos) continue;
    const halfW = (nodeWidths.get(id) ?? 70) / 2 + WAYPOINT_CLEARANCE;
    obstacles.push([pos.x - halfW, pos.x + halfW]);
  }

  // Fast path: idealX is already clear
  if (!obstacles.some(([l, r]) => idealX >= l && idealX <= r)) return idealX;

  // Merge overlapping intervals then find the interval containing idealX
  obstacles.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const [l, r] of obstacles) {
    if (merged.length === 0 || l > merged[merged.length - 1][1]) {
      merged.push([l, r]);
    } else {
      merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], r);
    }
  }

  for (const [l, r] of merged) {
    if (idealX >= l && idealX <= r) {
      // Return the nearest free edge of this merged blocked interval
      return (idealX - l) <= (r - idealX) ? l : r;
    }
  }

  return idealX; // fallback (shouldn't reach here)
}

/**
 * Post-layout waypoint computation for long edges (edges spanning > 1 layer).
 *
 * Operates on already-computed node positions. For each intermediate layer
 * between a long edge's source and target:
 *   1. Computes the ideal x by linear interpolation (straight-line path).
 *   2. If the ideal x is clear of all nodes at that layer, uses it as-is.
 *   3. If blocked, deviates to the nearest free x (minimum lateral offset).
 *
 * This is strictly post-layout: real node positions are never changed.
 * Waypoints only deviate from the straight path when an actual obstacle
 * forces them to, so edges are as straight as possible.
 *
 * @returns Map of "sourceId_targetId" → waypoint positions.
 */
function computeWaypointsForLongEdges(
  skrubGraph: SkrubGraphDict,
  positions: Map<string, LayoutPosition>,
  nodeWidths: Map<string, number>,
  rankSep: number,
): Map<string, LayoutPosition[]> {
  const layers = assignLayers(skrubGraph);

  // Group nodes by layer for O(1) obstacle lookup per layer
  const nodesByLayer = new Map<number, string[]>();
  for (const node of skrubGraph.nodes) {
    const layer = layers.get(node.id) ?? 0;
    if (!nodesByLayer.has(layer)) nodesByLayer.set(layer, []);
    nodesByLayer.get(layer)!.push(node.id);
  }

  const edgeWaypoints = new Map<string, LayoutPosition[]>();

  for (const [nodeId, parentIds] of Object.entries(skrubGraph.parents ?? {})) {
    for (const parentId of parentIds) {
      const srcLayer = layers.get(parentId) ?? 0;
      const tgtLayer = layers.get(nodeId) ?? 0;
      if (tgtLayer - srcLayer <= 1) continue; // short edge — no waypoints

      const srcPos = positions.get(parentId);
      const tgtPos = positions.get(nodeId);
      if (!srcPos || !tgtPos) continue;

      const waypoints: LayoutPosition[] = [];

      for (let k = srcLayer + 1; k < tgtLayer; k++) {
        const t = (k - srcLayer) / (tgtLayer - srcLayer);
        const idealX = srcPos.x + (tgtPos.x - srcPos.x) * t;
        // y is determined by the layer grid, not by linear interpolation
        const layerY = k * rankSep + rankSep / 2;

        const layerNodes = nodesByLayer.get(k) ?? [];
        const clearX = findClearXPosition(idealX, layerNodes, positions, nodeWidths);
        waypoints.push({ x: clearX, y: layerY });
      }

      edgeWaypoints.set(`${parentId}_${nodeId}`, waypoints);
    }
  }

  return edgeWaypoints;
}

/**
 * Compute node positions (same as computePresetPositions) plus smooth
 * obstacle-avoiding waypoints for every long edge.
 *
 * Positions are computed by the standard Sugiyama pipeline (no dummy nodes).
 * Waypoints are computed post-layout: each long edge follows the straight
 * source→target path and deviates only when an intermediate node blocks it.
 *
 * @returns positions  — raw node ID → {x, y} (same as computePresetPositions)
 * @returns edgeWaypoints — "sourceId_targetId" → waypoint positions for
 *          long edges; used by buildCyElements to set unbundled-bezier params.
 */
export function computeLayoutWithWaypoints(
  skrubGraph: SkrubGraphDict,
  options: { nodeSep?: number; rankSep?: number } = {},
): {
  positions: Map<string, LayoutPosition>;
  edgeWaypoints: Map<string, LayoutPosition[]>;
} {
  const nodeSep = options.nodeSep ?? NODE_SEP;
  const rankSep = options.rankSep ?? RANK_SEP;

  // Regular Sugiyama layout — no dummy nodes
  const positions = computePresetPositions(skrubGraph, { nodeSep, rankSep });

  const nodeWidths = new Map<string, number>();
  for (const node of skrubGraph.nodes) {
    nodeWidths.set(node.id, calculateNodeWidth(node.label));
  }

  const edgeWaypoints = computeWaypointsForLongEdges(
    skrubGraph,
    positions,
    nodeWidths,
    rankSep,
  );

  return { positions, edgeWaypoints };
}

// ---------------------------------------------------------------------------
// Element construction
// ---------------------------------------------------------------------------

export interface CyNode {
  data: {
    id: string;
    label: string;
    isSempipesSemantic: "true" | "false";
    nodeType: "input" | "operator";
    nodeWidth: number;
  };
  position?: LayoutPosition;
}

export interface CyEdge {
  data: {
    id: string;
    source: string;
    target: string;
  };
}

/**
 * Build the Cytoscape element arrays (nodes + edges) from a SkrubGraphDict.
 *
 * @param skrubGraph The graph structure.
 * @param positions  Optional map of raw node ID → {x, y}. When provided,
 *                   each CyNode receives a `position` field so that
 *                   Cytoscape's "preset" layout places nodes exactly.
 */
export function buildCyElements(
  skrubGraph: SkrubGraphDict,
  positions?: Map<string, LayoutPosition>,
): {
  cyNodes: CyNode[];
  cyEdges: CyEdge[];
} {
  const cyNodes: CyNode[] = skrubGraph.nodes.map((node) => {
    const nodeId = toSkrubId(node.id);
    const isSempipesSemantic =
      skrubGraph.sempipesNodeIds?.includes(node.id) ??
      node.is_sempipes_semantic ??
      false;
    // Use backend-provided type when present; otherwise infer from label for legacy data
    const nodeType: "input" | "operator" =
      node.type === "input" ? "input" : node.type === "operator" || node.type === "pipeline" ? "operator" : inferNodeType(node.label);

    const cyNode: CyNode = {
      data: {
        id: nodeId,
        label: node.label,
        isSempipesSemantic: isSempipesSemantic ? "true" : "false",
        nodeType,
        nodeWidth: calculateNodeWidth(node.label),
      },
    };

    if (positions) {
      const pos = positions.get(node.id); // raw ID (before skrub_ prefix)
      if (pos) cyNode.position = pos;
    }

    return cyNode;
  });

  const cyEdges: CyEdge[] = [];
  for (const [nodeId, parentIds] of Object.entries(skrubGraph.parents)) {
    const targetId = toSkrubId(nodeId);
    for (const parentId of parentIds) {
      const sourceId = toSkrubId(parentId);

      cyEdges.push({ data: { id: `${sourceId}-${targetId}`, source: sourceId, target: targetId } });
    }
  }

  return { cyNodes, cyEdges };
}
