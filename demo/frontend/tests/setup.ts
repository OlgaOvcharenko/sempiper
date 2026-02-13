import "@testing-library/jest-dom";
import { vi } from "vitest";
import React from "react";

// Mock CodeOutput to render plain text for testing
vi.mock("../src/components/CodeOutput", () => ({
  CodeOutput: ({ code, isLoading }: { code: string; language: string; isLoading?: boolean }) => {
    if (isLoading) {
      return React.createElement("div", null, "Generating code for this node…");
    }
    if (!code) {
      return React.createElement("div", null, "Generated code will appear here");
    }
    return React.createElement("pre", null, code);
  },
}));

// Mock Cytoscape to avoid Canvas errors in JSDOM
vi.mock("cytoscape", () => {
  const mockCy = {
    nodes: vi.fn(() => ({
      forEach: vi.fn(),
      removeClass: vi.fn().mockReturnThis(),
      addClass: vi.fn().mockReturnThis(),
      length: 0,
    })),
    edges: vi.fn(() => ({
      forEach: vi.fn(),
    })),
    getElementById: vi.fn((id: string) => ({
      length: 1,
      addClass: vi.fn().mockReturnThis(),
      removeClass: vi.fn().mockReturnThis(),
      data: vi.fn(),
    })),
    on: vi.fn(),
    destroy: vi.fn(),
    layout: vi.fn(() => ({
      run: vi.fn(),
    })),
  };

  return {
    default: vi.fn(() => mockCy),
  };
});
