/**
 * Middle panel: interactive graph from the pipeline run (skrub only).
 * Uses Cytoscape.js for graph visualization instead of SVG.
 * Renders interactive DAG: click nodes to select and inspect. Loading icon while pipeline runs.
 */
import { useEffect, useRef } from "react";
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
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

interface GraphPanelProps {
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  /** Skrub DAG from _Graph().run(dag): nodes, parents, children — only source for visualization. */
  skrubGraph?: SkrubGraphDict | null;
  /** Ordered compile node ids to map skrub node index -> compile node id for selection. */
  runnableNodeIds?: string[];
  isLoading?: boolean;
  highlightedNodeIds?: string[];
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

// Calculate node width based on label length (approx 8px per character + padding)
const calculateNodeWidth = (label: string): number => {
  const minWidth = 70;
  const charWidth = 7;
  const padding = 24;
  const calculatedWidth = label.length * charWidth + padding;
  return Math.max(minWidth, calculatedWidth);
};

export function GraphPanel({
  selectedNodeId,
  onSelectNode,
  nodes: _nodes = MOCK_NODES,
  edges: _edges = [],
  skrubGraph = null,
  runnableNodeIds: _runnableNodeIds = [],
  isLoading = false,
  highlightedNodeIds = [],
  showGraph: _showGraph = false,
  isPreview: _isPreview = false,
  isExecuting = false,
  expandButton = null,
}: GraphPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const hasSkrubDict = Boolean(skrubGraph?.nodes?.length);
  const shouldShowSkrubDict = hasSkrubDict;

  // Helper to infer node type from label
  // "input" nodes (with "var" in label) get blue color
  // "operator" nodes get white (non-sempipes) or green (sempipes) based on isSempipesSemantic
  const inferNodeType = (label: string): "input" | "operator" => {
    if (!label) return "operator";
    const low = label.toLowerCase();

    // Nodes with "var" in label are input/data initialization nodes (blue)
    if (low.includes("var")) return "input";

    // Everything else is an operator (white for non-sempipes, green for sempipes)
    return "operator";
  };

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current || !shouldShowSkrubDict || !skrubGraph) {
      return;
    }

    // Destroy existing instance
    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    // Prepare nodes with computed width
    const cyNodes = skrubGraph.nodes.map((node) => {
      const nodeId = toSkrubId(node.id);
      const isSempipesSemantic =
        skrubGraph.sempipesNodeIds?.includes(node.id) ?? node.is_sempipes_semantic ?? false;
      const nodeType = inferNodeType(node.label);
      const nodeWidth = calculateNodeWidth(node.label);

      return {
        data: {
          id: nodeId,
          label: node.label,
          isSempipesSemantic: isSempipesSemantic ? "true" : "false", // Use string for selector
          nodeType, // Use nodeType to avoid conflict with Cytoscape's internal 'type'
          nodeWidth,
        },
      };
    });

    // Prepare edges (from parents dict)
    const cyEdges: Array<{ data: { id: string; source: string; target: string } }> = [];
    for (const [nodeId, parentIds] of Object.entries(skrubGraph.parents)) {
      const targetId = toSkrubId(nodeId);
      for (const parentId of parentIds) {
        const sourceId = toSkrubId(parentId);
        cyEdges.push({
          data: {
            id: `${sourceId}-${targetId}`,
            source: sourceId,
            target: targetId,
          },
        });
      }
    }

    // Initialize Cytoscape with proper selectors
    const cy = cytoscape({
      container: containerRef.current,
      elements: [...cyNodes, ...cyEdges],
      style: [
        // Base node style - transparent background
        {
          selector: "node",
          style: {
            "background-color": "#ffffff",
            "background-opacity": 0.3,
            "border-color": "#64748b",
            "border-width": 1.5,
            "border-style": "solid",
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 12,
            "font-family": "ui-sans-serif, system-ui, -apple-system, sans-serif",
            color: "#18181b",
            width: "data(nodeWidth)",
            height: 32,
            shape: "round-rectangle",
            "text-wrap": "none",
          },
        },
        // Input nodes - light blue background, solid border
        {
          selector: "node[nodeType = 'input']",
          style: {
            "background-color": "#dbeafe", // Light blue (tailwind blue-100)
            "background-opacity": 0.6,
            "border-style": "solid",
            "border-color": "#3b82f6", // Blue (tailwind blue-500)
            "border-width": 1.5,
          },
        },
        // Skrub operator nodes (non-sempipes) - white/transparent, dashed border
        {
          selector: "node[nodeType = 'operator'][isSempipesSemantic = 'false']",
          style: {
            "background-color": "#ffffff",
            "background-opacity": 0.9,
            "border-style": "dashed",
            "border-color": "#94a3b8",
            "border-width": 1.5,
          },
        },
        // Sempipes semantic operators - green background and border (matches code editor)
        {
          selector: "node[isSempipesSemantic = 'true']",
          style: {
            "background-color": "#dcfce7", // Light green (tailwind green-100)
            "background-opacity": 0.7,
            "border-color": "#22c55e", // Green (tailwind green-500)
            "border-width": 2,
            "border-style": "dashed",
          },
        },
        // Selected sempipes node - light pink
        {
          selector: "node.selected[isSempipesSemantic = 'true']",
          style: {
            "background-color": "#fce7f3", // Light pink (tailwind pink-100)
            "background-opacity": 1,
            "border-color": "#ec4899", // Pink (tailwind pink-500)
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Selected non-sempipes node - keep yellow
        {
          selector: "node.selected[isSempipesSemantic = 'false']",
          style: {
            "background-color": "#fef9c3", // Yellow (tailwind yellow-100)
            "background-opacity": 1,
            "border-color": "#f59e0b", // Amber (tailwind amber-500)
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Highlighted sempipes node (from code hover) - light pink
        {
          selector: "node.highlighted[isSempipesSemantic = 'true']",
          style: {
            "background-color": "#fce7f3", // Light pink (tailwind pink-100)
            "background-opacity": 1,
            "border-color": "#ec4899", // Pink (tailwind pink-500)
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Highlighted non-sempipes node (from code hover) - yellow
        {
          selector: "node.highlighted[isSempipesSemantic = 'false']",
          style: {
            "background-color": "#fef9c3", // Yellow (tailwind yellow-100)
            "background-opacity": 1,
            "border-color": "#f59e0b", // Amber (tailwind amber-500)
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Edge style
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#64748b",
            "target-arrow-color": "#64748b",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.8,
          },
        },
      ],
      layout: {
        name: "breadthfirst",
        directed: true,
        spacingFactor: 1.3,
        avoidOverlap: true,
        nodeDimensionsIncludeLabels: true,
      },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      minZoom: 0.4, // Minimum and aximum zoom
      maxZoom: 3,
    });

    // Node click handler
    cy.on("tap", "node", (evt) => {
      const node = evt.target as NodeSingular;
      const nodeId = node.data("id") as string;
      onSelectNode(nodeId);
    });

    // Click on background to deselect
    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        onSelectNode(null);
      }
    });

    // Limit panning to keep graph always in view
    cy.on("viewport", () => {
      const zoom = cy.zoom();
      const pan = cy.pan();
      const width = cy.width();
      const height = cy.height();
      const bb = cy.elements().boundingBox();

      const graphWidth = bb.w * zoom;
      const graphHeight = bb.h * zoom;

      const graphX = bb.x1 * zoom + pan.x;
      const graphY = bb.y1 * zoom + pan.y;

      const minVisible = 200;

      let newPanX = pan.x;
      let newPanY = pan.y;

      if (graphX + graphWidth < minVisible) {
        newPanX = minVisible - graphWidth - bb.x1 * zoom;
      }
      if (graphX > width - minVisible) {
        newPanX = width - minVisible - bb.x1 * zoom;
      }

      if (graphY + graphHeight < minVisible) {
        newPanY = minVisible - graphHeight - bb.y1 * zoom;
      }
      if (graphY > height - minVisible) {
        newPanY = height - minVisible - bb.y1 * zoom;
      }

      if (newPanX !== pan.x || newPanY !== pan.y) {
        cy.pan({ x: newPanX, y: newPanY });
      }
    });

    cyRef.current = cy;

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, [shouldShowSkrubDict, skrubGraph, onSelectNode]);

  // Update selection and highlighting
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Remove all selection/highlight classes
    cy.nodes().removeClass("selected highlighted");

    // Add selected class
    if (selectedNodeId) {
      const node = cy.getElementById(selectedNodeId);
      if (node.length > 0) {
        node.addClass("selected");
      }
    }

    // Add highlighted class
    for (const nodeId of highlightedNodeIds) {
      const node = cy.getElementById(nodeId);
      if (node.length > 0) {
        node.addClass("highlighted");
      }
    }
  }, [selectedNodeId, highlightedNodeIds]);

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
          <div className="flex items-center gap-2">{expandButton}</div>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden p-2">
        {shouldShowSkrubDict && skrubGraph ? (
          <div
            ref={containerRef}
            className="w-full h-full"
            data-testid="cytoscape-graph"
            style={{ backgroundColor: "#fafafa" }}
          />
        ) : isLoading ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div
              className="w-10 h-10 rounded-full border-2 border-slate-300 border-t-emerald-500 animate-spin"
              aria-label="Graph loading spinner"
            />
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
