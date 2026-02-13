import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeDetailsPanel } from "../src/components/NodeDetailsPanel";

describe("NodeDetailsPanel", () => {
  it("shows placeholder when no node selected", () => {
    render(
      <NodeDetailsPanel selectedNodeId={null} selectedNode={null} />
    );
    expect(screen.getByText("Node details")).toBeInTheDocument();
    expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
  });

  it("shows Data summary for input node (placeholder when no run)", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="as_X_1"
        selectedNode={{ id: "as_X_1", type: "input", label: "as_X" }}
      />
    );
    expect(screen.getByText("Node details")).toBeInTheDocument();
    expect(screen.getByText("Data summary")).toBeInTheDocument();
    expect(screen.getByText(/run the pipeline to see schema/i)).toBeInTheDocument();
  });

  it("shows schema, sample and row count when input node has inputSummaryByNode", () => {
    const inputSummaryByNode = {
      as_X_1: {
        node_id: "as_X_1",
        schema: [{ name: "ID", dtype: "int64" }],
        sample: [{ ID: 1 }, { ID: 2 }, { ID: 3 }],
        row_count: 5000,
      },
    };
    render(
      <NodeDetailsPanel
        selectedNodeId="as_X_1"
        selectedNode={{ id: "as_X_1", type: "input", label: "as_X" }}
        inputSummaryByNode={inputSummaryByNode}
      />
    );
    expect(screen.getByText("Data summary")).toBeInTheDocument();
    expect(screen.getByText(/Rows: 5,000/)).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
    expect(screen.getByText("Column")).toBeInTheDocument();
    expect(screen.getByText("dtype")).toBeInTheDocument();
    expect(screen.getByText("int64")).toBeInTheDocument();
    expect(screen.getByText(/Sample \(first 3 rows\)/)).toBeInTheDocument();
    expect(screen.getAllByText("ID").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows Generated code for operator node when code provided", async () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        generatedCode="def step(): pass"
      />
    );
    expect(screen.getByText("Generated code")).toBeInTheDocument();
    // Code is rendered with syntax highlighting via dangerouslySetInnerHTML
    expect(screen.getByText("LLM / prompt stats")).toBeInTheDocument();
  });

  it("shows (live) when operator has live generated code", async () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        liveGeneratedCodeByNode={{ sem_fillna_2: "# live code" }}
      />
    );
    expect(screen.getByText("Generated code")).toBeInTheDocument();
    expect(screen.getByText("(live)")).toBeInTheDocument();
    // Code is rendered with syntax highlighting via dangerouslySetInnerHTML
  });

  it("shows Generating code for this node… when executing and no code yet", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        isExecuting={true}
      />
    );
    expect(screen.getByText("Generated code")).toBeInTheDocument();
    expect(screen.getByText(/generating code for this node/i)).toBeInTheDocument();
  });

  it("shows Attempts and Cost for operator when live retries/cost provided", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        liveGeneratedCodeByNode={{ sem_fillna_2: "# code" }}
        liveRetriesByNode={{ sem_fillna_2: 2 }}
        liveCostUsdByNode={{ sem_fillna_2: 0.001234 }}
      />
    );
    expect(screen.getByText("Attempts: 2")).toBeInTheDocument();
    expect(screen.getByText(/Cost: \$0\.001234/)).toBeInTheDocument();
  });

  it("shows data summary for skrub-selected input node via inputSummaryForSelectedNode (label mapping)", () => {
    const inputSummary = {
      node_id: "as_X_12",
      schema: [{ name: "ID", dtype: "int64" }],
      sample: [{ ID: 1 }, { ID: 2 }],
      row_count: 5000,
    };
    render(
      <NodeDetailsPanel
        selectedNodeId="skrub_0"
        selectedNode={{ id: "skrub_0", type: "input", label: "as_X" }}
        inputSummaryByNode={{ as_X_12: inputSummary }}
        inputSummaryForSelectedNode={inputSummary}
      />
    );
    expect(screen.getByText("Data summary")).toBeInTheDocument();
    expect(screen.getByText(/Rows: 5,000/)).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
    expect(screen.getByText("int64")).toBeInTheDocument();
  });

  it("shows data summary when input node selected and inputSummaryByNode has skrub_0 key (from execute stream)", () => {
    const inputSummary = {
      node_id: "skrub_0",
      schema: [{ name: "ID", dtype: "int64" }],
      sample: [{ ID: 1 }, { ID: 2 }, { ID: 3 }],
      row_count: 5000,
    };
    render(
      <NodeDetailsPanel
        selectedNodeId="skrub_0"
        selectedNode={{ id: "skrub_0", type: "input", label: "as_X" }}
        inputSummaryByNode={{ skrub_0: inputSummary }}
      />
    );
    expect(screen.getByText("Data summary")).toBeInTheDocument();
    expect(screen.getByText(/Rows: 5,000/)).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
    expect(screen.getByText("int64")).toBeInTheDocument();
    expect(screen.getByText(/Sample \(first 3 rows\)/)).toBeInTheDocument();
  });
});
