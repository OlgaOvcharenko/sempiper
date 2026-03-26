import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PipelineEditorPanel } from "../src/components/PipelineEditorPanel";

const DEFAULT_PROPS = {
  pipelineScripts: [
    { id: "simple", label: "Fraud simple", file: "simple.py" },
    { id: "medium", label: "Fraud medium", file: "medium.py" },
  ],
  loadedScriptId: "simple",
  onLoadScript: vi.fn(),
  onPipelineCodeChange: vi.fn(),
  isExecuting: false,
  onPlay: vi.fn(),
  onClearCache: vi.fn(),
  llmName: "gpt-5-mini",
  onLlmNameChange: vi.fn(),
  temperature: "0.0",
  onTemperatureChange: vi.fn(),
  pipelineCode: "# pipeline code",
  compileNodes: [],
  highlightedNodeIds: [],
  onHighlightNodes: vi.fn(),
  selectedNodeId: null,
  onSelectNode: vi.fn(),
  cursorFocusNodeId: null,
  onFocusApplied: vi.fn(),
  sempipesNodeIds: [],
  lastRunError: null,
};

describe("PipelineEditorPanel", () => {
  it("renders without crashing", () => {
    render(<PipelineEditorPanel {...DEFAULT_PROPS} />);
    // Should show the pipeline script dropdown
    expect(screen.getByText("Pipeline:")).toBeInTheDocument();
  });

  it("shows provided pipeline scripts in dropdown", () => {
    render(<PipelineEditorPanel {...DEFAULT_PROPS} />);
    expect(screen.getByText("Fraud simple")).toBeInTheDocument();
    expect(screen.getByText("Fraud medium")).toBeInTheDocument();
  });

  it("calls onPlay when run button is clicked", () => {
    const onPlay = vi.fn();
    render(<PipelineEditorPanel {...DEFAULT_PROPS} onPlay={onPlay} />);
    // The play button (triangle icon) should be clickable
    const playBtn = screen.getAllByRole("button").find(
      (b) => b.getAttribute("title") === "Run pipeline"
    );
    expect(playBtn).toBeTruthy();
    fireEvent.click(playBtn!);
    expect(onPlay).toHaveBeenCalledTimes(1);
  });

  it("shows LLM name in the model selector", () => {
    render(<PipelineEditorPanel {...DEFAULT_PROPS} llmName="gemini/gemini-2.5-flash" />);
    const select = screen.getByDisplayValue("gemini/gemini-2.5-flash");
    expect(select).toBeInTheDocument();
  });

  it("play button is disabled when isExecuting=true", () => {
    render(<PipelineEditorPanel {...DEFAULT_PROPS} isExecuting={true} />);
    const playBtn = screen.getAllByRole("button").find(
      (b) => b.getAttribute("title") === "Run pipeline"
    );
    expect(playBtn).toBeTruthy();
    expect(playBtn).toBeDisabled();
  });

  it("calls onLoadScript when a different script is selected", () => {
    const onLoadScript = vi.fn();
    render(<PipelineEditorPanel {...DEFAULT_PROPS} onLoadScript={onLoadScript} />);
    // The script selector contains the script labels; select by current value
    const select = screen.getByDisplayValue("Fraud simple");
    fireEvent.change(select, { target: { value: "medium" } });
    expect(onLoadScript).toHaveBeenCalledWith("medium");
  });

  it("play button shows disabled styling when isPlayDisabled=true", () => {
    render(<PipelineEditorPanel {...DEFAULT_PROPS} isPlayDisabled={true} />);
    const playBtn = screen.getAllByRole("button").find(
      (b) => b.title?.includes("benchmark") || b.title?.includes("cannot be executed")
    );
    expect(playBtn).toBeTruthy();
    expect(playBtn).toBeDisabled();
  });
});
