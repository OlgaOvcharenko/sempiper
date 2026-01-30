import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CodeGenDemo } from "../src/components/CodeGenDemo";

const wrapper = () => {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

const DEFAULT_SCRIPTS = {
  scripts: [
    { id: "simple", label: "Simple" },
    { id: "medium", label: "Medium" },
    { id: "full", label: "Full (notebook)" },
  ],
};
const DEFAULT_SCRIPT_CONTENT = {
  id: "simple",
  label: "Simple",
  content: "# Simple pipeline\nimport sempipes\n\nbasket_ids = sempipes.as_X(baskets[[\"ID\"]], \"X\")\nfraud_flags = sempipes.as_y(baskets[\"fraud_flag\"], \"y\")\nproducts = products.sem_fillna(target_column=\"make\", nl_prompt=\"Infer.\")\n",
};

function mockFetchDefault(
  overrides: { list?: unknown; simple?: unknown } = {}
) {
  vi.mocked(fetch).mockImplementation((url: string | URL) => {
    const u = String(url);
    if (u.endsWith("/api/scripts") || u === "/api/scripts") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.list ?? DEFAULT_SCRIPTS),
      } as Response);
    }
    const match = u.match(/\/api\/scripts\/([^/]+)$/);
    if (match) {
      const name = decodeURIComponent(match[1]);
      const content = name === "simple" ? (overrides.simple ?? DEFAULT_SCRIPT_CONTENT) : { id: name, label: name, content: "# " + name + "\n" };
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(content),
      } as Response);
    }
    return Promise.resolve({ ok: false } as Response);
  });
}

describe("CodeGenDemo", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    mockFetchDefault();
  });

  it("renders title and Run button only (in first pane)", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Sempipes pipeline demo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /compile/i })).not.toBeInTheDocument();
  });

  it("renders Run button (execute pipeline) in first pane", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
  });

  it("renders middle panel as computation graph", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Computation graph")).toBeInTheDocument();
  });

  it("renders node details placeholder when no node selected", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
  });

  it("calls execute API when Run is clicked", async () => {
    const mockFetch = vi.mocked(fetch).mockResolvedValue({
      ok: true,
      body: null,
      headers: new Headers({ "content-type": "text/event-stream" }),
    } as Response);
    (mockFetch as unknown as { body: ReadableStream | null }).body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"terminal","line":"Starting..."}\n\n')
        );
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"node_code","node_id":"n1","generated_code":"# code"}\n\n')
        );
        controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
        controller.close();
      },
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => {
      const calls = mockFetch.mock.calls.filter(
        (c) => String(c[0]).includes("/api/execute")
      );
      expect(calls.length).toBeGreaterThanOrEqual(1);
      const body = JSON.parse((calls[0][1] as RequestInit)?.body as string);
      expect(body.input_code).toBeDefined();
      expect(typeof body.input_code).toBe("string");
    });
  });

  it("when GET /api/scripts fails, no script buttons are shown", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      statusText: "Internal Server Error",
    } as Response);

    render(<CodeGenDemo />, { wrapper: wrapper() });

    await waitFor(
      () => {
        expect(fetch).toHaveBeenCalledWith("/api/scripts");
      },
      { timeout: 1000 }
    );
    expect(screen.getByText("Load script:")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Simple" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Medium" })).not.toBeInTheDocument();
  });

  it("shows Load script buttons (Simple, Medium, Full) and they are clickable", async () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(
      () => {
        expect(screen.getByText("Load script:")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Simple" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Medium" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Full (notebook)" })).toBeInTheDocument();
      },
      { timeout: 2000 }
    );

    fireEvent.click(screen.getByRole("button", { name: "Simple" }));
    fireEvent.click(screen.getByRole("button", { name: "Medium" }));
    fireEvent.click(screen.getByRole("button", { name: "Full (notebook)" }));
  });

  it("fetches script content by id when Load script button is clicked", async () => {
    const fullContent = { id: "full", label: "Full (notebook)", content: "# Full pipeline\nimport sempipes\n# ..." };
    vi.mocked(fetch).mockImplementation((url: string | URL) => {
      const u = String(url);
      if (u.endsWith("/api/scripts") || u === "/api/scripts") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.endsWith("/api/scripts/full")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(fullContent) } as Response);
      }
      if (u.match(/\/api\/scripts\//)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByRole("button", { name: "Full (notebook)" })).toBeInTheDocument(), { timeout: 2000 });

    fireEvent.click(screen.getByRole("button", { name: "Full (notebook)" }));

    await waitFor(() => {
      const scriptCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
        (c) => String(c[0]).includes("/api/scripts/") && !String(c[0]).endsWith("/api/scripts")
      );
      const fullCall = scriptCalls.find((c) => String(c[0]).includes("/api/scripts/full"));
      expect(fullCall).toBeDefined();
    });
  });

  it("calls compile API on load and shows graph nodes when compile returns nodes", async () => {
    const compileResponse = {
      nodes: [
        {
          id: "as_X_1",
          type: "input",
          label: "as_X",
          source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 20 },
        },
        {
          id: "sem_fillna_2",
          type: "operator",
          label: "sem_fillna",
          source_range: { start_line: 2, start_column: 1, end_line: 2, end_column: 25 },
        },
      ],
      edges: [{ source: "as_X_1", target: "sem_fillna_2" }],
    };
    vi.mocked(fetch).mockImplementation((url: string | URL) => {
      const u = String(url);
      if (u.endsWith("/api/scripts") || u === "/api/scripts") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.match(/\/api\/scripts\//)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(
      () => {
        expect(screen.getByText("as_X")).toBeInTheDocument();
        expect(screen.getByText("sem_fillna")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });

  it("when switching script, compile is called with new code and graph shows new nodes", async () => {
    const simpleNodes = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "as_y_2", type: "input", label: "as_y", source_range: null },
        { id: "sem_fillna_6", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [
        { source: "as_X_1", target: "as_y_2" },
        { source: "as_y_2", target: "sem_fillna_6" },
      ],
    };
    const mediumNodes = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_9", type: "operator", label: "sem_fillna", source_range: null },
        { id: "sem_gen_13", type: "operator", label: "sem_gen_features", source_range: null },
      ],
      edges: [
        { source: "as_X_1", target: "sem_fillna_9" },
        { source: "sem_fillna_9", target: "sem_gen_13" },
      ],
    };

    const mediumScriptContent = { id: "medium", label: "Medium", content: "# Medium pipeline\n# no Simple pipeline here\n" };
    vi.mocked(fetch).mockImplementation((url, init) => {
      const urlStr = String(url);
      if (urlStr.endsWith("/api/scripts") || urlStr === "/api/scripts") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (urlStr.endsWith("/api/scripts/medium")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mediumScriptContent) } as Response);
      }
      if (urlStr.match(/\/api\/scripts\//)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (urlStr.includes("/api/compile")) {
        const body = JSON.parse((init?.body as string) ?? "{}");
        const code = body.input_code ?? "";
        const nodes = code.includes("Simple pipeline") ? simpleNodes : mediumNodes;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(nodes),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes: [], edges: [] }) } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });

    await waitFor(
      () => {
        expect(screen.getByText("as_X")).toBeInTheDocument();
        expect(screen.getByText("as_y")).toBeInTheDocument();
        expect(screen.getByText("sem_fillna")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
    expect(screen.queryByText(/sem_gen_fe/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Medium" }));

    await waitFor(
      () => {
        const compileCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter((c) =>
          String(c[0]).includes("/api/compile")
        );
        const withMediumCode = compileCalls.some((c) => {
          const body = (c[1] as RequestInit)?.body;
          if (typeof body !== "string") return false;
          try {
            const parsed = JSON.parse(body);
            return (parsed.input_code ?? "").includes("Medium pipeline");
          } catch {
            return false;
          }
        });
        expect(withMediumCode).toBe(true);
      },
      { timeout: 2000 }
    );

    fireEvent.click(screen.getByRole("button", { name: "Simple" }));

    await waitFor(
      () => {
        const compileCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter((c) =>
          String(c[0]).includes("/api/compile")
        );
        const withSimpleCode = compileCalls.some((c) => {
          const body = (c[1] as RequestInit)?.body;
          if (typeof body !== "string") return false;
          try {
            const parsed = JSON.parse(body);
            return (parsed.input_code ?? "").includes("Simple pipeline");
          } catch {
            return false;
          }
        });
        expect(withSimpleCode).toBe(true);
      },
      { timeout: 2000 }
    );
    expect(screen.getByText("as_X")).toBeInTheDocument();
    expect(screen.getByText("as_y")).toBeInTheDocument();
    expect(screen.getByText("sem_fillna")).toBeInTheDocument();
  });

  it("when switching script, selection is cleared and node details show placeholder", async () => {
    const compileResponse = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_2", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [{ source: "as_X_1", target: "sem_fillna_2" }],
    };
    vi.mocked(fetch).mockImplementation((url: string | URL) => {
      const u = String(url);
      if (u.endsWith("/api/scripts") || u === "/api/scripts") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.match(/\/api\/scripts\//)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("as_X")).toBeInTheDocument(), { timeout: 2000 });

    fireEvent.click(screen.getByTestId("graph-node-sem_fillna_2"));
    await waitFor(() => {
      expect(screen.queryByText(/select a node in the graph/i)).not.toBeInTheDocument();
      expect(screen.getByText("Node details")).toBeInTheDocument();
    });

    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ nodes: [{ id: "op1", type: "operator", label: "Op", source_range: null }], edges: [] }),
    } as Response);
    fireEvent.click(screen.getByRole("button", { name: "Medium" }));

    await waitFor(() => {
      expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
    });
  });
});
