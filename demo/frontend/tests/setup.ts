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
    getElementById: vi.fn((_id: string) => ({
      length: 1,
      addClass: vi.fn().mockReturnThis(),
      removeClass: vi.fn().mockReturnThis(),
      data: vi.fn(),
    })),
    on: vi.fn(),
    one: vi.fn(),
    destroy: vi.fn(),
    layout: vi.fn(() => ({
      run: vi.fn(),
    })),
  };

  const cyCtor = vi.fn(() => mockCy);
  // @ts-ignore
  cyCtor.use = vi.fn();
  return {
    default: cyCtor,
  };
});

// Mock localStorage for theme toggle tests
const localStorageMock = (function() {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value.toString();
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    })
  };
})();

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock
});
