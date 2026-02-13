import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphPanel } from "../src/components/GraphPanel";

describe("GraphPanel", () => {
  it("renders graph heading and placeholder before Run", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "n1", type: "input", label: "as_X" },
          { id: "n2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[{ source: "n1", target: "n2" }]}
      />
    );
    expect(screen.getByText("Computation graph")).toBeInTheDocument();
    expect(screen.getByText(/Edit pipeline code to see the computation graph/)).toBeInTheDocument();
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
  });

  it("when showGraph is true but no skrub graph, shows placeholder (no fake/compiled graph)", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "as_X_1", type: "input", label: "as_X" },
          { id: "sem_fillna_2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[]}
        showGraph={true}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.getByText(/Edit pipeline code to see the computation graph/)).toBeInTheDocument();
  });

  it("shows loading placeholder when isLoading and graph not shown", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        isLoading={true}
      />
    );
    expect(screen.getByText(/Generating graph/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Graph loading spinner/)).toBeInTheDocument();
  });

  it("uses only graph dict for visualization; without dict shows placeholder", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[{ id: "n1", type: "input", label: "as_X" }]}
        edges={[]}
        showGraph={true}
      />
    );
    expect(screen.getByText("Computation graph")).toBeInTheDocument();
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.getByText(/Edit pipeline code to see the computation graph/)).toBeInTheDocument();
  });

  it("renders Cytoscape container when skrub graph is provided", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("shows placeholder when showGraph is false", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "n1", type: "input", label: "as_X" },
          { id: "n2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[{ source: "n1", target: "n2" }]}
        showGraph={false}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
  });

  it("renders Cytoscape graph with medium-like graph data", () => {
    const skrubGraph = {
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
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("renders Cytoscape graph with simple branching structure", () => {
    const skrubGraph = {
      nodes: [
        { id: "var_baskets_14", label: "baskets", is_sempipes_semantic: false },
        { id: "subsample_15", label: "skb.subsample", is_sempipes_semantic: false },
        { id: "as_X_18", label: "as_X", is_sempipes_semantic: false },
      ],
      parents: { var_baskets_14: [], subsample_15: ["var_baskets_14"], as_X_18: ["subsample_15"] },
      children: { var_baskets_14: ["subsample_15"], subsample_15: ["as_X_18"], as_X_18: [] },
      sempipesNodeIds: [] as string[],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("shows single interactive graph (no toggle) when skrub dict is provided", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByText(/Computation graph \(from code\) · Click an operator to see generated code/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skrub" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Interactive" })).not.toBeInTheDocument();
  });

  it("renders Cytoscape container for input nodes", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("renders Cytoscape container with status badges", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
        statusByNodeId={{ skrub_0: "done", skrub_1: "done" }}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("renders Cytoscape container with highlighted nodes", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
        highlightedNodeIds={["skrub_0"]}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("renders Cytoscape container with multiple highlighted nodes", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
        highlightedNodeIds={["skrub_0", "skrub_1"]}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("renders Cytoscape container with selected and highlighted nodes", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    render(
      <GraphPanel
        selectedNodeId="skrub_1"
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
        highlightedNodeIds={["skrub_1"]}
      />
    );
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("shows interactive DAG from graph dict (nodes, parents, children)", () => {
    const skrubGraph = {
      nodes: [{ id: "0", label: "as_X", is_sempipes_semantic: false }],
      parents: { "0": [] },
      children: { "0": [] },
      sempipesNodeIds: [],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    expect(screen.getByText(/Computation graph \(from code\) · Click an operator to see generated code/)).toBeInTheDocument();
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("shows 'No computation graph yet' when skrubGraph is null", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={null}
        showGraph={true}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.getByText(/Edit pipeline code to see the computation graph/)).toBeInTheDocument();
    expect(screen.queryByTestId("cytoscape-graph")).not.toBeInTheDocument();
  });

  it("shows 'No computation graph yet' when skrubGraph has empty nodes array", () => {
    const emptyGraph = {
      nodes: [],
      parents: {},
      children: {},
      sempipesNodeIds: [],
    };
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={emptyGraph}
        showGraph={true}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.getByText(/Edit pipeline code to see the computation graph/)).toBeInTheDocument();
    expect(screen.queryByTestId("cytoscape-graph")).not.toBeInTheDocument();
  });

  it("shows 'No computation graph yet' when skrubGraph is undefined", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        edges={[]}
        skrubGraph={undefined}
        showGraph={true}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.queryByTestId("cytoscape-graph")).not.toBeInTheDocument();
  });
});
