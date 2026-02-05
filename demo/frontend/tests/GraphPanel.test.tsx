import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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
    expect(screen.getByText(/Run to see the skrub graph/)).toBeInTheDocument();
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
    expect(screen.getByText(/Run to see the skrub graph/)).toBeInTheDocument();
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

  it("uses only graph dict for visualization (no SVG); without dict shows placeholder", () => {
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
    expect(screen.getByText(/Run to see the skrub graph/)).toBeInTheDocument();
  });

  it("calls onSelectNode with skrub_<id> when clicking a node in skrub DAG (sempipes operator shows code)", () => {
    const onSelectNode = vi.fn();
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
        onSelectNode={onSelectNode}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    fireEvent.click(screen.getByLabelText(/Graph node sem_fillna \(sempipes operator\)/));
    expect(onSelectNode).toHaveBeenCalledWith("skrub_1");
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

  it("shows single interactive Skrub graph (no Skrub/Interactive toggle) when skrub dict is provided", () => {
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
    expect(screen.getByText(/Skrub graph \(from run\) · Click an operator to see generated code/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skrub" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Interactive" })).not.toBeInTheDocument();
  });

  it("clicking an input node in skrub DAG calls onSelectNode with skrub_<id>", () => {
    const onSelectNode = vi.fn();
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
        onSelectNode={onSelectNode}
        nodes={[]}
        edges={[]}
        skrubGraph={skrubGraph}
        showGraph={true}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Graph node as_X/ }));
    expect(onSelectNode).toHaveBeenCalledWith("skrub_0");
  });

  it("shows status badges when statusByNodeId is provided", () => {
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
    const doneBadges = screen.getAllByTestId("node-status-done");
    expect(doneBadges.length).toBe(2);
  });

  it("highlights nodes when highlightedNodeIds contains skrub IDs (code–graph mapping)", () => {
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    const { container } = render(
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
    const rects = container.querySelectorAll("rect");
    expect(rects.length).toBe(2);
    const asXRect = Array.from(rects).find((r) => r.closest("g")?.getAttribute("aria-label")?.includes("as_X"));
    expect(asXRect).toBeDefined();
    expect(asXRect?.getAttribute("stroke-width")).toBe("2");
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
    expect(screen.getByText(/Skrub graph \(from run\) · Click an operator to see generated code/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Graph node as_X/ })).toBeInTheDocument();
  });
});
