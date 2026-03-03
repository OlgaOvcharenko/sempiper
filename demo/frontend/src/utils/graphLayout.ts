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
 * Edge curve style. "bezier" produces smooth natural curves.
 * Combined with the deterministic preset layout this avoids crossings without
 * the visual noise of orthogonal (taxi) routing.
 */
export const EDGE_CURVE_STYLE = "bezier" as const;

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
// Element construction
// ---------------------------------------------------------------------------

/**
 * Maximum horizontal endpoint offset as a percentage of node half-width.
 * tanh(dx/NODE_SEP) * MAX_ENDPOINT_OFFSET gives the x% used in
 * "x% 50%" / "x% -50%" source/target-endpoint style strings.
 * Capped at 38% so the endpoint always stays within the node boundary.
 */
export const MAX_ENDPOINT_OFFSET = 38;

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
    /** "x% 50%"  — exit point on the source node's bottom edge. */
    sourceEndpoint: string;
    /** "x% -50%" — entry point on the target node's top edge. */
    targetEndpoint: string;
  };
}

/**
 * Build the Cytoscape element arrays (nodes + edges) from a SkrubGraphDict.
 *
 * @param skrubGraph  The graph structure.
 * @param positions   Optional map of raw node ID → {x, y}. When provided,
 *                    each CyNode receives a `position` field so that
 *                    Cytoscape's "preset" layout places nodes exactly.
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

    const cyNode: CyNode = {
      data: {
        id: nodeId,
        label: node.label,
        isSempipesSemantic: isSempipesSemantic ? "true" : "false",
        nodeType: inferNodeType(node.label),
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

      // Compute directional exit/entry points so the edge leaves the source
      // from the side closest to the target and enters the target similarly.
      // tanh saturates smoothly: dx=0 → center, dx≫0 → near right edge.
      let sourceEndpoint = "0% 50%";
      let targetEndpoint = "0% -50%";
      if (positions) {
        const srcPos = positions.get(parentId);
        const tgtPos = positions.get(nodeId);
        if (srcPos && tgtPos) {
          const offset = Math.round(
            Math.tanh((tgtPos.x - srcPos.x) / NODE_SEP) * MAX_ENDPOINT_OFFSET,
          );
          sourceEndpoint = `${offset}% 50%`;
          targetEndpoint = `${-offset}% -50%`;
        }
      }

      cyEdges.push({
        data: {
          id: `${sourceId}-${targetId}`,
          source: sourceId,
          target: targetId,
          sourceEndpoint,
          targetEndpoint,
        },
      });
    }
  }

  return { cyNodes, cyEdges };
}
