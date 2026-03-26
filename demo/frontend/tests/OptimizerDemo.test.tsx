import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OptimizerDemo } from "../src/components/OptimizerDemo";

function wrapper() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function urlFromRequest(input: RequestInfo | URL): string {
  return typeof input === "string"
    ? input
    : input instanceof URL
      ? input.href
      : (input as Request).url;
}

const OPTIMIZER_SCRIPTS = {
  scripts: [
    { id: "optimise_house", label: "Optimizer (1 house)", file: "optimise_house.py" },
    { id: "optimise_fraud", label: "Optimizer (2 fraud)", file: "optimise_fraud.py" },
  ],
};

const SAMPLE_SCRIPT_CONTENT = {
  id: "optimise_house",
  label: "Optimizer (1 house)",
  content: "# optimise_house\noutcomes = optimise_colopro(dag_sink=pipeline, num_trials=5)\n",
};

const SAMPLE_TRAJECTORY = {
  run_id: "optimise_house_simulated.json",
  optimizer_args: { scoring: "roc_auc" },
  outcomes: [
    { search_node: { trial: 0, parent_trial: null }, score: 0.75, state: { generated_code: "x = 1" } },
    { search_node: { trial: 1, parent_trial: 0 }, score: 0.82, state: { generated_code: "x = 2" } },
  ],
};

function mockFetchWithOptimizer(opts: { optimizerActive?: boolean } = {}) {
  const { optimizerActive = true } = opts;
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
    const u = urlFromRequest(input);

    if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(OPTIMIZER_SCRIPTS),
      } as Response);
    }
    const scriptMatch = u.match(/\/api\/scripts\/([^/?]+)/);
    if (scriptMatch) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(SAMPLE_SCRIPT_CONTENT),
      } as Response);
    }
    if (u.includes("/api/optimizer/status")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ active: optimizerActive }),
      } as Response);
    }
    if (u.includes("/api/optimizer/options")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    }
    if (u.includes("/api/optimizer/final-code")) {
      return Promise.resolve({ ok: false, status: 404, statusText: "Not Found" } as Response);
    }
    if (u.includes("/api/optimizer/by-script") || u.includes("/api/optimizer/latest")) {
      if (optimizerActive) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(SAMPLE_TRAJECTORY),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, statusText: "Not Found" } as Response);
    }
    if (u.includes("/api/compile")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ nodes: [], edges: [] }),
      } as Response);
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
  });
}

describe("OptimizerDemo", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("renders without crashing", () => {
    mockFetchWithOptimizer();
    render(
      <OptimizerDemo layoutMode="toggled" setLayoutMode={vi.fn()} isDark={false} />,
      { wrapper: wrapper() }
    );
    // Component should mount without throwing
    expect(document.body).toBeTruthy();
  });

  it("fetches pipeline scripts list on mount", async () => {
    mockFetchWithOptimizer();
    render(
      <OptimizerDemo layoutMode="toggled" setLayoutMode={vi.fn()} isDark={false} />,
      { wrapper: wrapper() }
    );
    await waitFor(
      () => {
        const calls = vi.mocked(fetch).mock.calls.map(([input]) => urlFromRequest(input as RequestInfo));
        return calls.some((u) => u.includes("/api/scripts"));
      },
      { timeout: 2000 }
    );
    const scriptCalls = vi.mocked(fetch).mock.calls
      .map(([input]) => urlFromRequest(input as RequestInfo))
      .filter((u) => u.includes("/api/scripts"));
    expect(scriptCalls.length).toBeGreaterThan(0);
  });

  it("fetches optimizer status on mount", async () => {
    mockFetchWithOptimizer({ optimizerActive: true });
    render(
      <OptimizerDemo layoutMode="toggled" setLayoutMode={vi.fn()} isDark={false} />,
      { wrapper: wrapper() }
    );
    await waitFor(
      () => {
        const calls = vi.mocked(fetch).mock.calls.map(([input]) => urlFromRequest(input as RequestInfo));
        return calls.some((u) => u.includes("/api/optimizer/status"));
      },
      { timeout: 2000 }
    );
    const statusCalls = vi.mocked(fetch).mock.calls
      .map(([input]) => urlFromRequest(input as RequestInfo))
      .filter((u) => u.includes("/api/optimizer/status"));
    expect(statusCalls.length).toBeGreaterThan(0);
  });

  it("handles 404 from optimizer trajectory endpoint gracefully", async () => {
    mockFetchWithOptimizer({ optimizerActive: false });
    render(
      <OptimizerDemo layoutMode="toggled" setLayoutMode={vi.fn()} isDark={false} />,
      { wrapper: wrapper() }
    );
    // Component should not crash even when trajectory is unavailable
    await new Promise((r) => setTimeout(r, 300));
    expect(document.body).toBeTruthy();
  });
});
