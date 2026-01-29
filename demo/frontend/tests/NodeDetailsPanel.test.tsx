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

  it("shows Data summary for input node", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="as_X_1"
        selectedNode={{ id: "as_X_1", type: "input", label: "as_X" }}
      />
    );
    expect(screen.getByText("Node details")).toBeInTheDocument();
    expect(screen.getByText("Data summary")).toBeInTheDocument();
    expect(screen.getByText(/schema, sample rows/i)).toBeInTheDocument();
  });

  it("shows Generated code for operator node when code provided", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        generatedCode="def step(): pass"
      />
    );
    expect(screen.getByText("Generated code")).toBeInTheDocument();
    expect(screen.getByText("def step(): pass")).toBeInTheDocument();
    expect(screen.getByText("LLM / prompt stats")).toBeInTheDocument();
  });

  it("shows (live) when operator has live generated code", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_fillna_2"
        selectedNode={{ id: "sem_fillna_2", type: "operator", label: "sem_fillna" }}
        liveGeneratedCodeByNode={{ sem_fillna_2: "# live code" }}
      />
    );
    expect(screen.getByText("Generated code")).toBeInTheDocument();
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.getByText("# live code")).toBeInTheDocument();
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
});
