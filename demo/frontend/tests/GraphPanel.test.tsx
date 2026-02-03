import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { GraphPanel } from "../src/components/GraphPanel";

describe("GraphPanel", () => {
  it("renders graph heading and placeholder before execution", () => {
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
    expect(screen.getByText("Computation graph")).toBeInTheDocument();
    expect(screen.getByText(/Run pipeline to visualize graph/)).toBeInTheDocument();
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
  });

  it("shows placeholder when showGraph is false", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "as_X_1", type: "input", label: "as_X" },
          { id: "sem_fillna_2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[]}
        showGraph={false}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeInTheDocument();
    expect(screen.getByText(/to execute the pipeline/)).toBeInTheDocument();
  });

  it("shows graph nodes when showGraph is true", () => {
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
    expect(screen.getByText("as_X")).toBeInTheDocument();
    expect(screen.getByText("sem_fillna")).toBeInTheDocument();
  });

  it("shows Loading… when isLoading", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        isLoading={true}
      />
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders skrub SVG when skrubGraphSvg is provided", () => {
    const skrubSvg = "<svg xmlns='http://www.w3.org/2000/svg'><text>skrub graph</text></svg>";
    const { container } = render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[{ id: "n1", type: "input", label: "as_X" }]}
        edges={[]}
        skrubGraphSvg={skrubSvg}
        showGraph={true}
      />
    );
    expect(screen.getByText("skrub graph")).toBeInTheDocument();
    expect(container.querySelector("svg text")).toHaveTextContent("skrub graph");
    expect(screen.getByText("Computation graph")).toBeInTheDocument();
    expect(screen.getByText(/Skrub native DataOp graph/)).toBeInTheDocument();
  });

  it("shows placeholder when skrubGraphSvg is empty and showGraph is false", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "n1", type: "input", label: "as_X" },
          { id: "n2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[{ source: "n1", target: "n2" }]}
        skrubGraphSvg=""
        showGraph={false}
      />
    );
    expect(screen.getByText(/No computation graph yet/)).toBeInTheDocument();
  });
});
