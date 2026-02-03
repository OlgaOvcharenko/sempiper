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
