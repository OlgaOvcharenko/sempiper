import { describe, it, expect } from "vitest";
import {
  NODE_SEP,
  RANK_SEP,
  NODE_HEIGHT,
  WAYPOINT_CLEARANCE,
  MAX_ENDPOINT_OFFSET,
  PRESET_LAYOUT_CONFIG,
  EDGE_CURVE_STYLE,
  calculateNodeWidth,
  inferNodeType,
  assignLayers,
  minimizeCrossings,
  computePresetPositions,
  countEdgeCrossings,
  buildCyElements,
  detectEdgeNodeOverlaps,
  computeLayoutWithWaypoints,
} from "../../src/utils/graphLayout";
import type { SkrubGraphDict, } from "../../src/api/client";
import type { LayoutPosition } from "../../src/utils/graphLayout";

// ---------------------------------------------------------------------------
// Spacing constants — overlap-prevention constraints
// ---------------------------------------------------------------------------

describe("NODE_SEP / RANK_SEP — spacing constraints", () => {
  it("NODE_SEP >= 200 so nodes in the same layer have a generous horizontal gap", () => {
    expect(NODE_SEP).toBeGreaterThanOrEqual(200);
  });

  it("RANK_SEP >= 50 so edges have enough vertical room between layers", () => {
    expect(RANK_SEP).toBeGreaterThanOrEqual(50);
  });
});

// ---------------------------------------------------------------------------
// Preset layout config
// ---------------------------------------------------------------------------

describe("PRESET_LAYOUT_CONFIG", () => {
  it("uses preset layout (not dagre)", () => {
    expect(PRESET_LAYOUT_CONFIG.name).toBe("preset");
  });

  it("fits the graph to the viewport", () => {
    expect(PRESET_LAYOUT_CONFIG.fit).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Edge routing style
// ---------------------------------------------------------------------------

describe("EDGE_CURVE_STYLE", () => {
  it("is 'bezier' for smooth natural curves", () => {
    expect(EDGE_CURVE_STYLE).toBe("bezier");
  });
});

// ---------------------------------------------------------------------------
// calculateNodeWidth
// ---------------------------------------------------------------------------

describe("calculateNodeWidth", () => {
  it("returns minimum width 70 for empty label", () => {
    expect(calculateNodeWidth("")).toBe(70);
  });

  it("returns minimum width 70 for very short labels", () => {
    expect(calculateNodeWidth("X")).toBe(70);
  });

  it("grows proportionally for longer labels", () => {
    expect(calculateNodeWidth("very_long_label_name")).toBeGreaterThan(
      calculateNodeWidth("foo"),
    );
  });

  it("never returns less than 70", () => {
    for (const label of ["", "a", "ab", "abc"]) {
      expect(calculateNodeWidth(label)).toBeGreaterThanOrEqual(70);
    }
  });
});

// ---------------------------------------------------------------------------
// inferNodeType
// ---------------------------------------------------------------------------

describe("inferNodeType", () => {
  it("classifies nodes whose label contains 'var' as input (case-insensitive)", () => {
    expect(inferNodeType("var_products")).toBe("input");
    expect(inferNodeType("products_var")).toBe("input");
    expect(inferNodeType("VAR_baskets")).toBe("input");
  });

  it("classifies all other nodes as operator", () => {
    expect(inferNodeType("as_X")).toBe("operator");
    expect(inferNodeType("sem_fillna")).toBe("operator");
    expect(inferNodeType("skb.subsample")).toBe("operator");
    expect(inferNodeType("")).toBe("operator");
  });
});

// ---------------------------------------------------------------------------
// assignLayers
// ---------------------------------------------------------------------------

describe("assignLayers", () => {
  it("assigns layer 0 to source nodes (no parents)", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }],
      parents: { a: [], b: [] },
      children: { a: [], b: [] },
    };
    const layers = assignLayers(g);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("b")).toBe(0);
  });

  it("assigns layer 1 to direct children of layer-0 nodes", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }],
      parents: { a: [], b: ["a"] },
      children: { a: ["b"], b: [] },
    };
    const layers = assignLayers(g);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("b")).toBe(1);
  });

  it("uses longest-path: a node with two parents goes in the deeper layer", () => {
    // a(0) --> c(2)
    // b(1) --> c(2)
    // b's layer depends on a, so c should be at layer 2
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
      ],
      parents: { a: [], b: ["a"], c: ["a", "b"] },
      children: { a: ["b", "c"], b: ["c"], c: [] },
    };
    const layers = assignLayers(g);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("b")).toBe(1);
    expect(layers.get("c")).toBe(2);
  });

  it("handles a linear chain correctly", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "n0", label: "n0" },
        { id: "n1", label: "n1" },
        { id: "n2", label: "n2" },
        { id: "n3", label: "n3" },
      ],
      parents: { n0: [], n1: ["n0"], n2: ["n1"], n3: ["n2"] },
      children: { n0: ["n1"], n1: ["n2"], n2: ["n3"], n3: [] },
    };
    const layers = assignLayers(g);
    expect(layers.get("n0")).toBe(0);
    expect(layers.get("n1")).toBe(1);
    expect(layers.get("n2")).toBe(2);
    expect(layers.get("n3")).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// minimizeCrossings
// ---------------------------------------------------------------------------

describe("minimizeCrossings", () => {
  it("returns a position for every node", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }, { id: "c", label: "c" }],
      parents: { a: [], b: ["a"], c: ["a"] },
      children: { a: ["b", "c"], b: [], c: [] },
    };
    const layers = assignLayers(g);
    const order = minimizeCrossings(g, layers);
    expect(order.has("a")).toBe(true);
    expect(order.has("b")).toBe(true);
    expect(order.has("c")).toBe(true);
  });

  it("positions within each layer are unique (no ties)", () => {
    const mediumGraph: SkrubGraphDict = {
      nodes: [
        { id: "var_products_13", label: "products", is_sempipes_semantic: false },
        { id: "var_baskets_14", label: "baskets", is_sempipes_semantic: false },
        { id: "subsample_15", label: "skb.subsample", is_sempipes_semantic: false },
        { id: "as_X_18", label: "as_X", is_sempipes_semantic: false },
        { id: "as_y_19", label: "as_y", is_sempipes_semantic: false },
        { id: "sem_fillna_22", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: {
        var_products_13: [],
        var_baskets_14: [],
        subsample_15: ["var_baskets_14"],
        as_X_18: ["subsample_15"],
        as_y_19: ["subsample_15"],
        sem_fillna_22: ["var_products_13"],
      },
      children: {
        var_products_13: ["sem_fillna_22"],
        var_baskets_14: ["subsample_15"],
        subsample_15: ["as_X_18", "as_y_19"],
        as_X_18: [],
        as_y_19: [],
        sem_fillna_22: [],
      },
      sempipesNodeIds: ["sem_fillna_22"],
    };
    const layers = assignLayers(mediumGraph);
    const order = minimizeCrossings(mediumGraph, layers);

    // Group by layer and check uniqueness
    const byLayer = new Map<number, number[]>();
    for (const [nodeId, pos] of order) {
      const layer = layers.get(nodeId)!;
      if (!byLayer.has(layer)) byLayer.set(layer, []);
      byLayer.get(layer)!.push(pos);
    }
    for (const [, positions] of byLayer) {
      const unique = new Set(positions);
      expect(unique.size).toBe(positions.length);
    }
  });
});

// ---------------------------------------------------------------------------
// computePresetPositions — structure
// ---------------------------------------------------------------------------

describe("computePresetPositions — structure", () => {
  const linearGraph: SkrubGraphDict = {
    nodes: [
      { id: "a", label: "a" },
      { id: "b", label: "b" },
      { id: "c", label: "c" },
    ],
    parents: { a: [], b: ["a"], c: ["b"] },
    children: { a: ["b"], b: ["c"], c: [] },
  };

  it("returns a position for every node", () => {
    const positions = computePresetPositions(linearGraph);
    for (const node of linearGraph.nodes) {
      expect(positions.has(node.id)).toBe(true);
    }
  });

  it("child nodes have strictly greater y than their parents", () => {
    const positions = computePresetPositions(linearGraph);
    expect(positions.get("b")!.y).toBeGreaterThan(positions.get("a")!.y);
    expect(positions.get("c")!.y).toBeGreaterThan(positions.get("b")!.y);
  });

  it("nodes in the same layer share the same y coordinate", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "left", label: "left" },
        { id: "right", label: "right" },
      ],
      parents: { root: [], left: ["root"], right: ["root"] },
      children: { root: ["left", "right"], left: [], right: [] },
    };
    const positions = computePresetPositions(g);
    expect(positions.get("left")!.y).toBe(positions.get("right")!.y);
  });

  it("respects custom rankSep option", () => {
    const positions = computePresetPositions(linearGraph, { rankSep: 100 });
    const yA = positions.get("a")!.y;
    const yB = positions.get("b")!.y;
    expect(yB - yA).toBeCloseTo(100);
  });
});

// ---------------------------------------------------------------------------
// countEdgeCrossings + zero-crossing guarantee for pipeline graphs
// ---------------------------------------------------------------------------

describe("countEdgeCrossings", () => {
  it("returns 0 for a linear chain (trivially no crossings)", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
      ],
      parents: { a: [], b: ["a"], c: ["b"] },
      children: { a: ["b"], b: ["c"], c: [] },
    };
    const positions = computePresetPositions(g);
    const edges = [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
    ];
    expect(countEdgeCrossings(positions, edges)).toBe(0);
  });

  it("detects crossings in a deliberately bad layout", () => {
    // Two nodes in layer 0 with swapped targets in layer 1 → 1 crossing
    const positions = new Map([
      ["a", { x: 0, y: 0 }],
      ["b", { x: 100, y: 0 }],
      ["c", { x: 0, y: 100 }],   // c is directly below a
      ["d", { x: 100, y: 100 }], // d is directly below b
    ]);
    // But edges go a→d and b→c, i.e. cross
    const edges = [
      { source: "a", target: "d" },
      { source: "b", target: "c" },
    ];
    expect(countEdgeCrossings(positions, edges)).toBe(1);
  });

  it("returns 0 for two parallel edges (no crossing)", () => {
    const positions = new Map([
      ["a", { x: 0, y: 0 }],
      ["b", { x: 100, y: 0 }],
      ["c", { x: 0, y: 100 }],
      ["d", { x: 100, y: 100 }],
    ]);
    const edges = [
      { source: "a", target: "c" },
      { source: "b", target: "d" },
    ];
    expect(countEdgeCrossings(positions, edges)).toBe(0);
  });

  it("returns 0 for the medium pipeline graph (Sugiyama layout)", () => {
    const mediumGraph: SkrubGraphDict = {
      nodes: [
        { id: "var_products_13", label: "products", is_sempipes_semantic: false },
        { id: "var_baskets_14", label: "baskets", is_sempipes_semantic: false },
        { id: "subsample_15", label: "skb.subsample", is_sempipes_semantic: false },
        { id: "as_X_18", label: "as_X", is_sempipes_semantic: false },
        { id: "as_y_19", label: "as_y", is_sempipes_semantic: false },
        { id: "sem_fillna_22", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: {
        var_products_13: [],
        var_baskets_14: [],
        subsample_15: ["var_baskets_14"],
        as_X_18: ["subsample_15"],
        as_y_19: ["subsample_15"],
        sem_fillna_22: ["var_products_13"],
      },
      children: {
        var_products_13: ["sem_fillna_22"],
        var_baskets_14: ["subsample_15"],
        subsample_15: ["as_X_18", "as_y_19"],
        as_X_18: [],
        as_y_19: [],
        sem_fillna_22: [],
      },
      sempipesNodeIds: ["sem_fillna_22"],
    };
    const positions = computePresetPositions(mediumGraph);
    const edges = Object.entries(mediumGraph.parents).flatMap(([target, sources]) =>
      sources.map((source) => ({ source, target })),
    );
    expect(countEdgeCrossings(positions, edges)).toBe(0);
  });

  it("returns 0 for a diamond DAG", () => {
    const diamond: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "left", label: "left" },
        { id: "right", label: "right" },
        { id: "sink", label: "sink" },
      ],
      parents: { root: [], left: ["root"], right: ["root"], sink: ["left", "right"] },
      children: { root: ["left", "right"], left: ["sink"], right: ["sink"], sink: [] },
    };
    const positions = computePresetPositions(diamond);
    const edges = [
      { source: "root", target: "left" },
      { source: "root", target: "right" },
      { source: "left", target: "sink" },
      { source: "right", target: "sink" },
    ];
    expect(countEdgeCrossings(positions, edges)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// buildCyElements — edge endpoint offsets
// ---------------------------------------------------------------------------

describe("buildCyElements — edge endpoints", () => {
  it("MAX_ENDPOINT_OFFSET is within node boundary (< 50%)", () => {
    expect(MAX_ENDPOINT_OFFSET).toBeLessThan(50);
    expect(MAX_ENDPOINT_OFFSET).toBeGreaterThan(0);
  });

  it("straight-down edge (dx=0) gets center endpoints '0% 50%' / '0% -50%'", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }],
      parents: { a: [], b: ["a"] },
      children: { a: ["b"], b: [] },
    };
    const positions = computePresetPositions(g); // a and b are in the same column
    const { cyEdges } = buildCyElements(g, positions);
    expect(cyEdges[0].data.sourceEndpoint).toBe("0% 50%");
    expect(cyEdges[0].data.targetEndpoint).toBe("0% -50%");
  });

  it("target to the right → positive source x%, negative target x% (exits bottom-right, enters top-left)", () => {
    // Two roots side by side, each with a child below — but we manually check
    // an edge where target is explicitly to the right of source
    const g: SkrubGraphDict = {
      nodes: [
        { id: "left", label: "left" },
        { id: "right", label: "right" },
        { id: "sink", label: "sink" },
      ],
      parents: { left: [], right: [], sink: ["left"] },
      children: { left: ["sink"], right: [], sink: [] },
    };
    // Place left at x=0 and sink at x=NODE_SEP (force positions)
    const positions = new Map([
      ["left", { x: 0, y: 0 }],
      ["right", { x: NODE_SEP, y: 0 }],
      ["sink", { x: NODE_SEP, y: 75 }], // sink is to the right of left
    ]);
    const { cyEdges } = buildCyElements(g, positions);
    const edge = cyEdges.find((e) => e.data.source === "skrub_left")!;
    const srcOffset = parseInt(edge.data.sourceEndpoint); // "15% 50%" → 15
    const tgtOffset = parseInt(edge.data.targetEndpoint); // "-15% -50%" → -15
    expect(srcOffset).toBeGreaterThan(0);  // exits from right side of source
    expect(tgtOffset).toBeLessThan(0);     // enters from left side of target (mirrored)
    expect(srcOffset).toBe(-tgtOffset);    // offsets are exact mirrors
  });

  it("target to the left → negative x% (edge exits bottom-left, enters top-left)", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "src", label: "src" }, { id: "tgt", label: "tgt" }],
      parents: { src: [], tgt: ["src"] },
      children: { src: ["tgt"], tgt: [] },
    };
    const positions = new Map([
      ["src", { x: NODE_SEP, y: 0 }],  // src is to the right
      ["tgt", { x: 0, y: 75 }],         // tgt is to the left → dx negative
    ]);
    const { cyEdges } = buildCyElements(g, positions);
    const xOffset = parseInt(cyEdges[0].data.sourceEndpoint);
    expect(xOffset).toBeLessThan(0); // exits from left side of source
  });

  it("endpoint offset magnitude is bounded by MAX_ENDPOINT_OFFSET", () => {
    // Even for very large dx (many nodes apart), offset should not exceed max
    const g: SkrubGraphDict = {
      nodes: [{ id: "src", label: "src" }, { id: "tgt", label: "tgt" }],
      parents: { src: [], tgt: ["src"] },
      children: { src: ["tgt"], tgt: [] },
    };
    const farPositions = new Map([
      ["src", { x: 0, y: 0 }],
      ["tgt", { x: NODE_SEP * 100, y: 75 }], // absurdly far to the right
    ]);
    const { cyEdges } = buildCyElements(g, farPositions);
    const xOffset = Math.abs(parseInt(cyEdges[0].data.sourceEndpoint));
    expect(xOffset).toBeLessThanOrEqual(MAX_ENDPOINT_OFFSET);
  });

  it("edges without positions fall back to center endpoints", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }],
      parents: { a: [], b: ["a"] },
      children: { a: ["b"], b: [] },
    };
    const { cyEdges } = buildCyElements(g); // no positions
    expect(cyEdges[0].data.sourceEndpoint).toBe("0% 50%");
    expect(cyEdges[0].data.targetEndpoint).toBe("0% -50%");
  });
});

// ---------------------------------------------------------------------------
// buildCyElements — node construction
// ---------------------------------------------------------------------------

const simpleGraph: SkrubGraphDict = {
  nodes: [
    { id: "0", label: "as_X", is_sempipes_semantic: false },
    { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
  ],
  parents: { "0": [], "1": ["0"] },
  children: { "0": ["1"], "1": [] },
  sempipesNodeIds: ["1"],
};

describe("buildCyElements — node construction", () => {
  it("prefixes all node IDs with 'skrub_'", () => {
    const { cyNodes } = buildCyElements(simpleGraph);
    for (const node of cyNodes) {
      expect(node.data.id).toMatch(/^skrub_/);
    }
  });

  it("preserves original node labels", () => {
    const { cyNodes } = buildCyElements(simpleGraph);
    expect(cyNodes[0].data.label).toBe("as_X");
    expect(cyNodes[1].data.label).toBe("sem_fillna");
  });

  it("marks sempipes nodes as isSempipesSemantic='true'", () => {
    const { cyNodes } = buildCyElements(simpleGraph);
    const sem = cyNodes.find((n) => n.data.id === "skrub_1")!;
    expect(sem.data.isSempipesSemantic).toBe("true");
  });

  it("marks non-sempipes nodes as isSempipesSemantic='false'", () => {
    const { cyNodes } = buildCyElements(simpleGraph);
    const nonSem = cyNodes.find((n) => n.data.id === "skrub_0")!;
    expect(nonSem.data.isSempipesSemantic).toBe("false");
  });

  it("falls back to is_sempipes_semantic field when sempipesNodeIds is absent", () => {
    const graph: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "sem_fillna", is_sempipes_semantic: true },
        { id: "b", label: "as_X", is_sempipes_semantic: false },
      ],
      parents: { a: [], b: [] },
      children: { a: [], b: [] },
    };
    const { cyNodes } = buildCyElements(graph);
    expect(cyNodes[0].data.isSempipesSemantic).toBe("true");
    expect(cyNodes[1].data.isSempipesSemantic).toBe("false");
  });

  it("classifies var-label nodes as nodeType='input'", () => {
    const graph: SkrubGraphDict = {
      nodes: [{ id: "v", label: "var_products" }],
      parents: { v: [] },
      children: { v: [] },
    };
    const { cyNodes } = buildCyElements(graph);
    expect(cyNodes[0].data.nodeType).toBe("input");
  });

  it("assigns wider nodes to longer labels", () => {
    const graph: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "X" },
        { id: "b", label: "very_long_operator_name_here" },
      ],
      parents: { a: [], b: [] },
      children: { a: [], b: [] },
    };
    const { cyNodes } = buildCyElements(graph);
    const widthA = cyNodes.find((n) => n.data.id === "skrub_a")!.data.nodeWidth;
    const widthB = cyNodes.find((n) => n.data.id === "skrub_b")!.data.nodeWidth;
    expect(widthB).toBeGreaterThan(widthA);
  });

  it("attaches positions when a positions map is provided", () => {
    const positions = computePresetPositions(simpleGraph);
    const { cyNodes } = buildCyElements(simpleGraph, positions);
    for (const node of cyNodes) {
      expect(node.position).toBeDefined();
      expect(typeof node.position!.x).toBe("number");
      expect(typeof node.position!.y).toBe("number");
    }
  });

  it("leaves position undefined when no positions map is provided", () => {
    const { cyNodes } = buildCyElements(simpleGraph);
    for (const node of cyNodes) {
      expect(node.position).toBeUndefined();
    }
  });
});

// ---------------------------------------------------------------------------
// buildCyElements — edge construction
// ---------------------------------------------------------------------------

describe("buildCyElements — edge construction", () => {
  it("creates one edge per parent relationship", () => {
    const { cyEdges } = buildCyElements(simpleGraph);
    expect(cyEdges).toHaveLength(1);
  });

  it("sets source to parent ID and target to child ID (both skrub_-prefixed)", () => {
    const { cyEdges } = buildCyElements(simpleGraph);
    expect(cyEdges[0].data.source).toBe("skrub_0");
    expect(cyEdges[0].data.target).toBe("skrub_1");
  });

  it("produces no edges when all nodes have no parents", () => {
    const isolated: SkrubGraphDict = {
      nodes: [{ id: "a", label: "A" }, { id: "b", label: "B" }],
      parents: { a: [], b: [] },
      children: { a: [], b: [] },
    };
    expect(buildCyElements(isolated).cyEdges).toHaveLength(0);
  });

  it("handles a diamond DAG: sink gets two incoming edges", () => {
    const diamond: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "left", label: "left" },
        { id: "right", label: "right" },
        { id: "sink", label: "sink" },
      ],
      parents: { root: [], left: ["root"], right: ["root"], sink: ["left", "right"] },
      children: { root: ["left", "right"], left: ["sink"], right: ["sink"], sink: [] },
    };
    const { cyEdges } = buildCyElements(diamond);
    expect(cyEdges).toHaveLength(4);
    expect(cyEdges.filter((e) => e.data.target === "skrub_sink")).toHaveLength(2);
  });

  it("produces unique edge IDs", () => {
    const diamond: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "left", label: "left" },
        { id: "right", label: "right" },
        { id: "sink", label: "sink" },
      ],
      parents: { root: [], left: ["root"], right: ["root"], sink: ["left", "right"] },
      children: { root: ["left", "right"], left: ["sink"], right: ["sink"], sink: [] },
    };
    const { cyEdges } = buildCyElements(diamond);
    const ids = cyEdges.map((e) => e.data.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// ---------------------------------------------------------------------------
// computePresetPositions — no overlapping node positions
// ---------------------------------------------------------------------------

function allPositionsUnique(positions: Map<string, LayoutPosition>): boolean {
  const seen = new Set<string>();
  for (const [, pos] of positions) {
    const key = `${pos.x},${pos.y}`;
    if (seen.has(key)) return false;
    seen.add(key);
  }
  return true;
}

describe("computePresetPositions — no overlapping node positions", () => {
  it("linear chain: all nodes get distinct (x, y) positions", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
        { id: "d", label: "d" },
      ],
      parents: { a: [], b: ["a"], c: ["b"], d: ["c"] },
      children: { a: ["b"], b: ["c"], c: ["d"], d: [] },
    };
    expect(allPositionsUnique(computePresetPositions(g))).toBe(true);
  });

  it("diamond DAG: all four nodes get distinct (x, y) positions", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "left", label: "left" },
        { id: "right", label: "right" },
        { id: "sink", label: "sink" },
      ],
      parents: { root: [], left: ["root"], right: ["root"], sink: ["left", "right"] },
      children: { root: ["left", "right"], left: ["sink"], right: ["sink"], sink: [] },
    };
    expect(allPositionsUnique(computePresetPositions(g))).toBe(true);
  });

  it("simple-pipeline topology (7 nodes): all nodes get distinct (x, y) positions", () => {
    // Mirrors simple.py structure:
    //   var_products(0) ────────────────────────► sem_gen(2) ──► sem_agg(3) ──► skb_apply(4)
    //   var_baskets(0) ──► as_y(1) ─────────────────────────────────────────► skb_apply(4)
    //                   ──► as_X(1) ────────────► sem_gen(2),  sem_agg(3)
    const g: SkrubGraphDict = {
      nodes: [
        { id: "var_products", label: "<Var 'products'>" },
        { id: "var_baskets", label: "<Var 'baskets'>" },
        { id: "as_y", label: "as_y" },
        { id: "as_X", label: "as_X" },
        { id: "sem_gen_features", label: "sem_gen_features" },
        { id: "sem_agg_features", label: "sem_agg_features" },
        { id: "skb_apply", label: "skb.apply" },
      ],
      parents: {
        var_products: [],
        var_baskets: [],
        as_y: ["var_baskets"],
        as_X: ["var_baskets"],
        sem_gen_features: ["var_products", "as_X"],
        sem_agg_features: ["as_X", "sem_gen_features"],
        skb_apply: ["as_y", "sem_agg_features"],
      },
      children: {
        var_products: ["sem_gen_features"],
        var_baskets: ["as_y", "as_X"],
        as_y: ["skb_apply"],
        as_X: ["sem_gen_features", "sem_agg_features"],
        sem_gen_features: ["sem_agg_features"],
        sem_agg_features: ["skb_apply"],
        skb_apply: [],
      },
    };
    const positions = computePresetPositions(g);
    expect(positions.size).toBe(7);
    expect(allPositionsUnique(positions)).toBe(true);
  });

  it("three sibling source nodes each get a different position", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
        { id: "sink", label: "sink" },
      ],
      parents: { a: [], b: [], c: [], sink: ["a", "b", "c"] },
      children: { a: ["sink"], b: ["sink"], c: ["sink"], sink: [] },
    };
    expect(allPositionsUnique(computePresetPositions(g))).toBe(true);
  });

  it("nodes in the same layer all have different x values", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "root", label: "root" },
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
      ],
      parents: { root: [], a: ["root"], b: ["root"], c: ["root"] },
      children: { root: ["a", "b", "c"], a: [], b: [], c: [] },
    };
    const positions = computePresetPositions(g);
    const layer1Xs = (["a", "b", "c"] as const).map((id) => positions.get(id)!.x);
    expect(new Set(layer1Xs).size).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// NODE_HEIGHT constant
// ---------------------------------------------------------------------------

describe("NODE_HEIGHT", () => {
  it("equals 32 (matches GraphPanel node height style)", () => {
    expect(NODE_HEIGHT).toBe(32);
  });
});

// ---------------------------------------------------------------------------
// detectEdgeNodeOverlaps
// ---------------------------------------------------------------------------

describe("detectEdgeNodeOverlaps", () => {
  it("returns empty for a short edge (adjacent layers, no intermediate nodes)", () => {
    // Two nodes stacked vertically, one edge — no other nodes to overlap
    const positions = new Map<string, LayoutPosition>([
      ["a", { x: 120, y: 30 }],
      ["b", { x: 120, y: 90 }],
    ]);
    const widths = new Map([["a", 70], ["b", 70]]);
    const edges = [{ source: "a", target: "b" }];
    expect(detectEdgeNodeOverlaps(positions, widths, edges)).toHaveLength(0);
  });

  it("returns empty when the long edge passes to the side of intermediate nodes", () => {
    // Edge goes straight down the left column; middle node is far to the right
    const positions = new Map<string, LayoutPosition>([
      ["src", { x: 120, y: 30 }],
      ["mid", { x: 600, y: 90 }],   // far right — not in the path
      ["tgt", { x: 120, y: 150 }],
    ]);
    const widths = new Map([["src", 70], ["mid", 70], ["tgt", 70]]);
    const edges = [{ source: "src", target: "tgt" }];
    expect(detectEdgeNodeOverlaps(positions, widths, edges)).toHaveLength(0);
  });

  it("detects overlap when a long edge passes directly through an intermediate node", () => {
    // src at layer 0 (x=120,y=30), tgt at layer 2 (x=120,y=150),
    // intermediate node exactly on the straight-line path (x=120, y=90)
    const positions = new Map<string, LayoutPosition>([
      ["src", { x: 120, y: 30 }],
      ["mid", { x: 120, y: 90 }],
      ["tgt", { x: 120, y: 150 }],
    ]);
    const widths = new Map([["src", 70], ["mid", 70], ["tgt", 70]]);
    const edges = [{ source: "src", target: "tgt" }];
    const overlaps = detectEdgeNodeOverlaps(positions, widths, edges);
    expect(overlaps).toHaveLength(1);
    expect(overlaps[0].overlappingNode).toBe("mid");
    expect(overlaps[0].edge).toEqual({ source: "src", target: "tgt" });
  });

  it("does not report the edge source or target as overlapping nodes", () => {
    const positions = new Map<string, LayoutPosition>([
      ["a", { x: 120, y: 30 }],
      ["b", { x: 120, y: 90 }],
    ]);
    const widths = new Map([["a", 70], ["b", 70]]);
    // Edge from a to b — neither endpoint should appear as an overlap
    const overlaps = detectEdgeNodeOverlaps(
      positions,
      widths,
      [{ source: "a", target: "b" }],
    );
    expect(overlaps.every((o) => o.overlappingNode !== "a")).toBe(true);
    expect(overlaps.every((o) => o.overlappingNode !== "b")).toBe(true);
  });

  it("reports at most one entry per (edge, node) pair", () => {
    // Long edge passing through the same node multiple times (wide node)
    const positions = new Map<string, LayoutPosition>([
      ["src", { x: 120, y: 30 }],
      ["mid", { x: 120, y: 90 }],
      ["tgt", { x: 120, y: 330 }], // spans 5 layers
    ]);
    const widths = new Map([["src", 70], ["mid", 200], ["tgt", 70]]);
    const overlaps = detectEdgeNodeOverlaps(
      positions,
      widths,
      [{ source: "src", target: "tgt" }],
    );
    const mid_reports = overlaps.filter((o) => o.overlappingNode === "mid");
    expect(mid_reports).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// computeLayoutWithWaypoints — basic contract
// ---------------------------------------------------------------------------

describe("computeLayoutWithWaypoints — basic contract", () => {
  it("returns positions for all nodes in the graph", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }, { id: "c", label: "c" }],
      parents: { a: [], b: ["a"], c: ["b"] },
      children: { a: ["b"], b: ["c"], c: [] },
    };
    const { positions } = computeLayoutWithWaypoints(g);
    for (const node of g.nodes) {
      expect(positions.has(node.id)).toBe(true);
    }
  });

  it("returns no waypoints for a linear chain (no long edges)", () => {
    const g: SkrubGraphDict = {
      nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }, { id: "c", label: "c" }],
      parents: { a: [], b: ["a"], c: ["b"] },
      children: { a: ["b"], b: ["c"], c: [] },
    };
    const { edgeWaypoints } = computeLayoutWithWaypoints(g);
    expect(edgeWaypoints.size).toBe(0);
  });

  it("returns waypoints for an edge that spans multiple layers", () => {
    // a (layer 0) → d (layer 3) is a long edge spanning 3 layers
    // b (layer 1) → c (layer 2) → d is the chain that forces d to layer 3
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
        { id: "d", label: "d" },
      ],
      parents: { a: [], b: ["a"], c: ["b"], d: ["a", "c"] },
      children: { a: ["b", "d"], b: ["c"], c: ["d"], d: [] },
    };
    const { edgeWaypoints } = computeLayoutWithWaypoints(g);
    // Edge a→d spans layers 0→3: should have 2 dummy waypoints (layers 1, 2)
    expect(edgeWaypoints.has("a_d")).toBe(true);
    expect(edgeWaypoints.get("a_d")!).toHaveLength(2);
  });

  it("child nodes still have greater y than parents after waypoint layout", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
        { id: "d", label: "d" },
      ],
      parents: { a: [], b: ["a"], c: ["b"], d: ["a", "c"] },
      children: { a: ["b", "d"], b: ["c"], c: ["d"], d: [] },
    };
    const { positions } = computeLayoutWithWaypoints(g);
    expect(positions.get("b")!.y).toBeGreaterThan(positions.get("a")!.y);
    expect(positions.get("c")!.y).toBeGreaterThan(positions.get("b")!.y);
    expect(positions.get("d")!.y).toBeGreaterThan(positions.get("c")!.y);
  });
});

// ---------------------------------------------------------------------------
// computeLayoutWithWaypoints — no edge-node overlaps after routing
// ---------------------------------------------------------------------------

describe("computeLayoutWithWaypoints — no edge-node overlaps after routing", () => {
  /** Build a nodeWidths map from a SkrubGraphDict (uses calculateNodeWidth). */
  function buildNodeWidths(g: SkrubGraphDict): Map<string, number> {
    const m = new Map<string, number>();
    for (const node of g.nodes) {
      m.set(node.id, calculateNodeWidth(node.label));
    }
    return m;
  }

  it("fraud-like topology: long getItem edge gets waypoints that avoid intermediate nodes", () => {
    // Mirrors the simple fraud pipeline:
    //   var_data (layer 0)
    //   ├── getItem_fraud_flag (layer 1) ──────────────────────────────► skb_apply (layer 4)
    //   └── as_X (layer 1) → sem_fillna (layer 2) → sem_gen (layer 3) → skb_apply (layer 4)
    const g: SkrubGraphDict = {
      nodes: [
        { id: "var_data", label: "var_data" },
        { id: "getItem_fraud_flag", label: "getItem('fraud_flag')" },
        { id: "as_X", label: "as_X" },
        { id: "sem_fillna", label: "sem_fillna" },
        { id: "sem_gen", label: "sem_gen_features" },
        { id: "skb_apply", label: "skb.apply" },
      ],
      parents: {
        var_data: [],
        getItem_fraud_flag: ["var_data"],
        as_X: ["var_data"],
        sem_fillna: ["as_X"],
        sem_gen: ["as_X", "sem_fillna"],
        skb_apply: ["getItem_fraud_flag", "sem_gen"],
      },
      children: {
        var_data: ["getItem_fraud_flag", "as_X"],
        getItem_fraud_flag: ["skb_apply"],
        as_X: ["sem_fillna", "sem_gen"],
        sem_fillna: ["sem_gen"],
        sem_gen: ["skb_apply"],
        skb_apply: [],
      },
    };

    const { positions, edgeWaypoints } = computeLayoutWithWaypoints(g);
    const nodeWidths = buildNodeWidths(g);

    // The long edge (spanning layers 1 → 4) must have waypoints
    expect(edgeWaypoints.has("getItem_fraud_flag_skb_apply")).toBe(true);
    const waypoints = edgeWaypoints.get("getItem_fraud_flag_skb_apply")!;
    expect(waypoints).toHaveLength(2); // intermediate layers 2 and 3

    // Each waypoint must not overlap (with clearance) any node at the same y
    for (const wp of waypoints) {
      for (const node of g.nodes) {
        const nodePos = positions.get(node.id);
        if (!nodePos) continue;
        if (Math.abs(nodePos.y - wp.y) > 1) continue; // different layer — skip
        const halfW = (nodeWidths.get(node.id) ?? 70) / 2 + WAYPOINT_CLEARANCE;
        // Waypoint x must be outside the node's padded bounding box
        expect(Math.abs(wp.x - nodePos.x)).toBeGreaterThan(halfW - 1);
      }
    }
  });

  it("buildCyElements marks long edges as segmented when waypoints are provided", () => {
    const g: SkrubGraphDict = {
      nodes: [
        { id: "a", label: "a" },
        { id: "b", label: "b" },
        { id: "c", label: "c" },
        { id: "d", label: "d" },
      ],
      parents: { a: [], b: ["a"], c: ["b"], d: ["a", "c"] },
      children: { a: ["b", "d"], b: ["c"], c: ["d"], d: [] },
    };
    const { positions, edgeWaypoints } = computeLayoutWithWaypoints(g);
    const { cyEdges } = buildCyElements(g, positions, edgeWaypoints);

    // Edge a→d is long (layers 0→3) — must have waypoints (unbundled-bezier)
    const longEdge = cyEdges.find(
      (e) => e.data.source === "skrub_a" && e.data.target === "skrub_d",
    );
    expect(longEdge).toBeDefined();
    expect(longEdge!.data.hasWaypoints).toBe("true");
    expect(longEdge!.data.controlPointDistances).toBeDefined();
    expect(longEdge!.data.controlPointWeights).toBeDefined();

    // Edge b→c is short (layers 1→2) — must NOT have waypoints
    const shortEdge = cyEdges.find(
      (e) => e.data.source === "skrub_b" && e.data.target === "skrub_c",
    );
    expect(shortEdge).toBeDefined();
    expect(shortEdge!.data.hasWaypoints).toBeUndefined();
  });
});
