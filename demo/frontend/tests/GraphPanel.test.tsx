import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { GraphPanel } from "../src/components/GraphPanel";

describe("GraphPanel", () => {
  it("renders compiled graph heading and hint", () => {
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
    expect(screen.getByText("Compiled graph")).toBeInTheDocument();
    expect(screen.getByText(/click a node or in code to select/i)).toBeInTheDocument();
  });

  it("renders node labels from nodes prop", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[
          { id: "as_X_1", type: "input", label: "as_X" },
          { id: "sem_fillna_2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[]}
      />
    );
    expect(screen.getByText("as_X")).toBeInTheDocument();
    expect(screen.getByText("sem_fillna")).toBeInTheDocument();
  });

  it("calls onSelectNode when a node is clicked", () => {
    const onSelectNode = vi.fn();
    const { container } = render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={onSelectNode}
        nodes={[
          { id: "n1", type: "input", label: "as_X" },
          { id: "n2", type: "operator", label: "sem_fillna" },
        ]}
        edges={[]}
      />
    );
    const rects = container.querySelectorAll("svg rect.cursor-pointer");
    expect(rects.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(rects[1]);
    expect(onSelectNode).toHaveBeenCalledWith("n2");
  });

  it("shows Compiling… when isLoading", () => {
    render(
      <GraphPanel
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        nodes={[]}
        isLoading={true}
      />
    );
    expect(screen.getByText("Compiling…")).toBeInTheDocument();
  });
});
