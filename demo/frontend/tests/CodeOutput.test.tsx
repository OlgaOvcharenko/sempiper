import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Unmock CodeOutput for these specific tests
vi.unmock("../src/components/CodeOutput");
import { CodeOutput } from "../src/components/CodeOutput";

describe("CodeOutput", () => {
  it("uses 11px font size to match InputEditor", async () => {
    const code = "def hello():\n    print('Hello, world!')";
    const { container } = render(<CodeOutput code={code} language="python" />);
    
    // Wait for the code to be rendered with syntax highlighting
    await waitFor(() => {
      const codeElement = container.querySelector(".font-mono");
      expect(codeElement).not.toBeNull();
    });
    
    const codeElement = container.querySelector(".font-mono");
    // Get computed style to verify font size is 11px (matching InputEditor)
    const style = window.getComputedStyle(codeElement!);
    expect(style.fontSize).toBe("11px");
  });

  it("renders loading state", () => {
    render(<CodeOutput code="" language="python" isLoading={true} />);
    expect(screen.getByText("Generating...")).toBeInTheDocument();
  });

  it("renders empty state when no code provided", () => {
    render(<CodeOutput code="" language="python" isLoading={false} />);
    expect(screen.getByText("Generated code will appear here")).toBeInTheDocument();
  });

  it("renders code with monospace font class", async () => {
    const code = "def test():\n    pass";
    const { container } = render(<CodeOutput code={code} language="python" />);
    
    // Wait for rendering and verify font-mono class is present
    await waitFor(() => {
      const codeElement = container.querySelector(".font-mono");
      expect(codeElement).not.toBeNull();
      expect(codeElement!.classList.contains("font-mono")).toBe(true);
    });
  });
});
