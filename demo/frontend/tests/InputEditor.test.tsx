import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InputEditor } from "../src/components/InputEditor";

describe("InputEditor", () => {
  it("shows data-highlighted when highlightedNodeIds is set (for graph-to-code sync)", () => {
    render(
      <InputEditor
        value="x = sempipes.as_X(df)"
        onChange={() => {}}
        nodeRanges={[
          {
            id: "as_X_1",
            type: "input",
            source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 22 },
          },
        ]}
        highlightedNodeIds={["as_X_1"]}
      />
    );
    const editor = screen.getByTestId("input-editor");
    expect(editor.getAttribute("data-highlighted")).toBe("as_X_1");
  });

  it("shows empty data-highlighted when highlightedNodeIds is empty", () => {
    render(
      <InputEditor
        value="x = 1"
        onChange={() => {}}
        highlightedNodeIds={[]}
      />
    );
    const editor = screen.getByTestId("input-editor");
    expect(editor.getAttribute("data-highlighted")).toBeFalsy();
  });

  it("shows comma-separated data-highlighted when multiple nodes highlighted (graph-to-code)", () => {
    render(
      <InputEditor
        value="as_X = sempipes.as_X(df)\nas_X.sem_fillna()"
        onChange={() => {}}
        nodeRanges={[
          {
            id: "as_X_1",
            type: "input",
            source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 22 },
          },
          {
            id: "sem_fillna_2",
            type: "operator",
            source_range: { start_line: 2, start_column: 1, end_line: 2, end_column: 20 },
          },
        ]}
        highlightedNodeIds={["as_X_1", "sem_fillna_2"]}
      />
    );
    const editor = screen.getByTestId("input-editor");
    expect(editor.getAttribute("data-highlighted")).toBe("as_X_1,sem_fillna_2");
  });

  it("renders with selectedNodeId and highlightedNodeIds for code-graph sync", () => {
    render(
      <InputEditor
        value="x = sempipes.as_X(df)"
        onChange={() => {}}
        nodeRanges={[
          {
            id: "as_X_1",
            type: "input",
            source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 22 },
          },
        ]}
        selectedNodeId="as_X_1"
        highlightedNodeIds={["as_X_1"]}
      />
    );
    const editor = screen.getByTestId("input-editor");
    expect(editor.getAttribute("data-highlighted")).toBe("as_X_1");
  });
});
