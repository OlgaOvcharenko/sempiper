/**
 * Middle panel: interactive graph from the pipeline run (skrub only).
 * Uses Cytoscape.js for graph visualization instead of SVG.
 * Renders interactive DAG: click nodes to select and inspect. Loading icon while pipeline runs.
 */
import { useEffect, useRef, Component, type ReactNode } from "react";
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import type { SkrubGraphDict } from "../api/client";
import {
  buildCyElements,
  computePresetPositions,
  PRESET_LAYOUT_CONFIG,
  EDGE_CURVE_STYLE,
} from "../utils/graphLayout";

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
  isDark?: boolean;
  viewToggle?: React.ReactNode;
  hideHeader?: boolean;
}

const MOCK_NODES: GraphNode[] = [
  { id: "input", type: "input", label: "Input" },
  { id: "op1", type: "operator", label: "Op" },
];


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
  isDark = false,
  viewToggle = null,
  hideHeader = false,
}: GraphPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const hasSkrubDict = Boolean(skrubGraph?.nodes?.length);
  const shouldShowSkrubDict = hasSkrubDict;

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current || !shouldShowSkrubDict || !skrubGraph) {
      return;
    }

    // Destroy existing instance
    if (cyRef.current) {
      try {
        cyRef.current.destroy();
      } catch {
        // Container may already be detached from the DOM
      }
      cyRef.current = null;
    }

    const positions = computePresetPositions(skrubGraph);
    const { cyNodes, cyEdges } = buildCyElements(skrubGraph, positions);

    // Theme-aware colors
    const colors = isDark
      ? {
        nodeBg: "#27272a",         // zinc-800
        nodeBorder: "#52525b",     // zinc-600
        nodeText: "#f4f4f5",       // zinc-100
        canvasBg: "#09090b",       // zinc-950
        inputBg: "#1e3a5f",        // dark blue
        inputBorder: "#60a5fa",    // blue-400
        operatorBg: "#27272a",     // zinc-800
        operatorBorder: "#52525b", // zinc-600
        semBg: "#14532d",          // dark green
        semBorder: "#4ade80",      // green-400
        selSemBg: "#831843",       // dark pink
        selSemBorder: "#f472b6",   // pink-400
        selBg: "#78350f",          // dark amber
        selBorder: "#fbbf24",      // amber-400
        edgeColor: "#94a3b8",      // slate-400
      }
      : {
        nodeBg: "#ffffff",
        nodeBorder: "#64748b",
        nodeText: "#18181b",
        canvasBg: "#fafafa",
        inputBg: "#dbeafe",        // blue-100
        inputBorder: "#3b82f6",    // blue-500
        operatorBg: "#ffffff",
        operatorBorder: "#94a3b8", // slate-400
        semBg: "#dcfce7",          // green-100
        semBorder: "#22c55e",      // green-500
        selSemBg: "#fce7f3",       // pink-100
        selSemBorder: "#ec4899",   // pink-500
        selBg: "#fef9c3",          // yellow-100
        selBorder: "#f59e0b",      // amber-500
        edgeColor: "#64748b",      // slate-500
      };

    // Initialize Cytoscape with proper selectors
    const cy = cytoscape({
      container: containerRef.current,
      elements: [...cyNodes, ...cyEdges],
      style: [
        // Base node style
        {
          selector: "node",
          style: {
            "background-color": colors.nodeBg,
            "background-opacity": 0.3,
            "border-color": colors.nodeBorder,
            "border-width": 1.5,
            "border-style": "solid",
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 12,
            "font-family": "ui-sans-serif, system-ui, -apple-system, sans-serif",
            color: colors.nodeText,
            width: "data(nodeWidth)",
            height: 32,
            shape: "round-rectangle",
            "text-wrap": "none",
          },
        },
        // Input nodes - blue background, solid border
        {
          selector: "node[nodeType = 'input']",
          style: {
            "background-color": colors.inputBg,
            "background-opacity": 0.6,
            "border-style": "solid",
            "border-color": colors.inputBorder,
            "border-width": 1.5,
          },
        },
        // Skrub operator nodes (non-sempipes) - dashed border
        {
          selector: "node[nodeType = 'operator'][isSempipesSemantic = 'false']",
          style: {
            "background-color": colors.operatorBg,
            "background-opacity": 0.9,
            "border-style": "dashed",
            "border-color": colors.operatorBorder,
            "border-width": 1.5,
          },
        },
        // Sempipes semantic operators - green background and border
        {
          selector: "node[isSempipesSemantic = 'true']",
          style: {
            "background-color": colors.semBg,
            "background-opacity": 0.7,
            "border-color": colors.semBorder,
            "border-width": 2,
            "border-style": "dashed",
          },
        },
        // Selected sempipes node - pink
        {
          selector: "node.selected[isSempipesSemantic = 'true']",
          style: {
            "background-color": colors.selSemBg,
            "background-opacity": 1,
            "border-color": colors.selSemBorder,
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Selected non-sempipes node - amber
        {
          selector: "node.selected[isSempipesSemantic = 'false']",
          style: {
            "background-color": colors.selBg,
            "background-opacity": 1,
            "border-color": colors.selBorder,
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Highlighted sempipes node (from code hover) - pink
        {
          selector: "node.highlighted[isSempipesSemantic = 'true']",
          style: {
            "background-color": colors.selSemBg,
            "background-opacity": 1,
            "border-color": colors.selSemBorder,
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Highlighted non-sempipes node (from code hover) - amber
        {
          selector: "node.highlighted[isSempipesSemantic = 'false']",
          style: {
            "background-color": colors.selBg,
            "background-opacity": 1,
            "border-color": colors.selBorder,
            "border-width": 3,
            "border-style": "solid",
          },
        },
        // Edge style — bezier curves; endpoints are offset toward the target
        // so edges exit/enter from the side of the node facing the connection
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": colors.edgeColor,
            "target-arrow-color": colors.edgeColor,
            "target-arrow-shape": "triangle",
            "curve-style": EDGE_CURVE_STYLE,
            "source-endpoint": "data(sourceEndpoint)",
            "target-endpoint": "data(targetEndpoint)",
            "arrow-scale": 0.8,
          },
        },
      ],
      layout: PRESET_LAYOUT_CONFIG as import("cytoscape").LayoutOptions,
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
      if (cy.elements().length === 0) return;
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
        try {
          cyRef.current.destroy();
        } catch {
          // Container may already be detached from the DOM
        }
        cyRef.current = null;
      }
    };
  }, [shouldShowSkrubDict, skrubGraph, onSelectNode, isDark]);

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
    <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
      {!hideHeader && (
        <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex flex-col justify-center gap-0.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex-1">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Computational graph</h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                {isLoading || (isExecuting && shouldShowSkrubDict)
                  ? "Running pipeline…"
                  : shouldShowSkrubDict
                    ? "Computational graph (from code) · Click an operator to see generated code"
                    : "Edit code to see computational graph"}
              </p>
            </div>
            <div className="flex items-center gap-4">
              {viewToggle}
              {expandButton}
            </div>
          </div>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-hidden p-2">
        {shouldShowSkrubDict && skrubGraph ? (
          <div
            ref={containerRef}
            className="w-full h-full"
            data-testid="cytoscape-graph"
            style={{ backgroundColor: isDark ? "#09090b" : "#fafafa" }}
          />
        ) : isLoading ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div
              className="w-10 h-10 rounded-full border-2 border-slate-300 dark:border-zinc-600 border-t-emerald-500 animate-spin"
              aria-label="Graph loading spinner"
            />
            <div className="text-sm text-zinc-500 dark:text-zinc-400 font-medium">Generating graph…</div>
            <div className="text-xs text-zinc-400 dark:text-zinc-500 max-w-xs">
              The pipeline is running. The graph will appear when compilation completes.
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div className="text-6xl text-zinc-300 dark:text-zinc-600">📊</div>
            <div className="text-sm text-zinc-500 dark:text-zinc-400 font-medium">No computational graph yet</div>
            <div className="text-xs text-zinc-400 dark:text-zinc-500 max-w-xs">
              Edit pipeline code to see the computational graph.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

class GraphPanelErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
          <div className="flex-1 flex flex-col items-center justify-center h-full text-center px-8 gap-3">
            <div className="text-sm text-zinc-500 dark:text-zinc-400 font-medium">Graph unavailable</div>
            <div className="text-xs text-zinc-400 dark:text-zinc-500 max-w-xs">
              An error occurred while rendering the graph. Edit the pipeline code to reload.
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function GraphPanelWithErrorBoundary(props: GraphPanelProps) {
  return (
    <GraphPanelErrorBoundary>
      <GraphPanel {...props} />
    </GraphPanelErrorBoundary>
  );
}
