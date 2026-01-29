import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TerminalPanel } from "../src/components/TerminalPanel";

describe("TerminalPanel", () => {
  it("shows Terminal heading and placeholder when empty and not running", () => {
    render(<TerminalPanel lines={[]} isRunning={false} />);
    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(
      screen.getByText(/output will appear here when you run the pipeline/i)
    ).toBeInTheDocument();
  });

  it("shows Running… when isRunning is true", () => {
    render(<TerminalPanel lines={[]} isRunning={true} />);
    expect(screen.getByText("Running…")).toBeInTheDocument();
  });

  it("shows terminal lines when provided", () => {
    render(
      <TerminalPanel
        lines={["Starting pipeline execution...", "Running sem_fillna (sem_fillna_10)..."]}
        isRunning={false}
      />
    );
    expect(screen.getByText("Starting pipeline execution...")).toBeInTheDocument();
    expect(screen.getByText("Running sem_fillna (sem_fillna_10)...")).toBeInTheDocument();
  });
});
