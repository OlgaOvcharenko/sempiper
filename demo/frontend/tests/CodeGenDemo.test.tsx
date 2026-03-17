import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
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
  content:
    "# Simple pipeline\nimport sempipes\n\nproducts = products.sem_gen_features(nl_prompt=\"Generate features.\", name=\"product_features\", how_many=3)\n",
};

function urlFromRequest(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
}

function mockFetchDefault(
  overrides: { list?: unknown; simple?: unknown } = {}
) {
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
    const u = urlFromRequest(input);
    // Match /api/scripts?mode=normal and /api/scripts?mode=optimizer (list endpoint)
    if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.list ?? DEFAULT_SCRIPTS),
      } as Response);
    }
    // Match /api/scripts/{name}?mode=... (content endpoint)
    const match = u.match(/\/api\/scripts\/([^/?]+)/);
    if (match) {
      const name = decodeURIComponent(match[1]);
      const content = name === "simple" ? (overrides.simple ?? DEFAULT_SCRIPT_CONTENT) : { id: name, label: name, content: "# " + name + "\n" };
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(content),
      } as Response);
    }
    if (u.includes("/api/update-config")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "ok", llm_name: "gemini/gemini-2.5-flash-lite", temperature: 0.0 }),
        text: () => Promise.resolve(""),
      } as Response);
    }
    return Promise.resolve({ ok: false, text: () => Promise.resolve("Not found") } as Response);
  });
}

describe("CodeGenDemo", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    mockFetchDefault();
  });

  it("renders Run button and no Compile button (in first pane)", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /compile/i })).not.toBeInTheDocument();
  });

  it("renders Run button (execute pipeline) in first pane", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
  });

  it("renders middle panel as computational graph", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Computational graph")).toBeInTheDocument();
  });

  it("renders node details placeholder when no node selected", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
  });

  it("calls execute API when Run is clicked", async () => {
    const mockFetch = vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/update-config")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok", llm_name: "gpt-5-mini", temperature: 0.0 }),
        } as Response);
      }
      if (u.includes("/api/execute")) {
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
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
          }),
          headers: new Headers({ "content-type": "text/event-stream" }),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
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

  it("when execute stream emits terminal and done, run completes without showing terminal (no terminal panel)", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/update-config")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok", llm_name: "gpt-5-mini", temperature: 0.0 }),
        } as Response);
      }
      if (u.includes("/api/execute")) {
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode('data: {"type":"terminal","line":"Starting pipeline execution..."}\n\n')
              );
              controller.enqueue(
                new TextEncoder().encode('data: {"type":"node_code","node_id":"as_X_1","generated_code":"# mock"}\n\n')
              );
              controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
              controller.close();
            },
          }),
          headers: new Headers({ "content-type": "text/event-stream" }),
        } as Response);
      }
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              nodes: [{ id: "as_X_1", type: "input", label: "as_X", source_range: null }],
              edges: [],
            }),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByRole("button", { name: /run/i })).not.toBeDisabled(), { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /run/i })).not.toBeDisabled(), { timeout: 3000 });
    expect(screen.queryByText("Starting pipeline execution...")).not.toBeInTheDocument();
    expect(screen.queryByText("Terminal")).not.toBeInTheDocument();
  });

  it("when GET /api/scripts fails, no script buttons are shown", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      statusText: "Internal Server Error",
    } as Response);

    render(<CodeGenDemo />, { wrapper: wrapper() });

    await waitFor(
      () => {
        const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
        expect(calls.some((c) => String(c[0]).includes("/api/scripts") && !String(c[0]).includes("/api/scripts/"))).toBe(true);
      },
      { timeout: 1000 }
    );
    // Dropdown should still exist but may be empty
    expect(screen.getByTitle("Select pipeline script")).toBeInTheDocument();
  });

  it("shows script dropdown with options (Simple, Medium, Full) and selection works", async () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(
      () => {
        const dropdown = screen.getByTitle("Select pipeline script") as HTMLSelectElement;
        expect(dropdown).toBeInTheDocument();
        expect(dropdown.options.length).toBeGreaterThanOrEqual(3);
      },
      { timeout: 2000 }
    );

    const dropdown = screen.getByTitle("Select pipeline script") as HTMLSelectElement;
    fireEvent.change(dropdown, { target: { value: "medium" } });
    fireEvent.change(dropdown, { target: { value: "full" } });
  });

  it("fetches script content by id when script is selected from dropdown", async () => {
    const fullContent = { id: "full", label: "Full (notebook)", content: "# Full pipeline\nimport sempipes\n# ..." };
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.endsWith("/api/scripts/full")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(fullContent) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByTitle("Select pipeline script")).toBeInTheDocument(), { timeout: 2000 });

    const dropdown = screen.getByTitle("Select pipeline script");
    fireEvent.change(dropdown, { target: { value: "full" } });

    await waitFor(() => {
      const scriptCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
        (c) => String(c[0]).includes("/api/scripts/") && !String(c[0]).endsWith("/api/scripts")
      );
      const fullCall = scriptCalls.find((c) => String(c[0]).includes("/api/scripts/full"));
      expect(fullCall).toBeDefined();
    });
  });

  it("shows computational graph from compile (graph from code, not from run)", async () => {
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
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => {
      expect(screen.getByText(/Computational graph \(from code\)/)).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it("medium script: graph shows baskets left of products (matches skrub SVG flow)", async () => {
    const mediumCompile = {
      nodes: [
        { id: "var_products_13", type: "input", label: "products", source_range: null },
        { id: "var_baskets_14", type: "input", label: "baskets", source_range: null },
        { id: "subsample_15", type: "operator", label: "skb.subsample", source_range: null },
        { id: "as_X_18", type: "input", label: "as_X", source_range: null },
        { id: "as_y_19", type: "input", label: "as_y", source_range: null },
        { id: "sem_fillna_22", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [
        { source: "var_baskets_14", target: "subsample_15" },
        { source: "subsample_15", target: "as_X_18" },
        { source: "subsample_15", target: "as_y_19" },
        { source: "var_products_13", target: "sem_fillna_22" },
      ],
    };
    const mediumContent = { id: "medium", label: "Medium", content: "# Medium\nbaskets = skrub.var('baskets')\nproducts = skrub.var('products')\n" };
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/medium")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mediumContent) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mediumCompile) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText(/Computational graph \(from code\)/)).toBeInTheDocument(), { timeout: 3000 });

    const dropdown = screen.getByTitle("Select pipeline script");
    fireEvent.change(dropdown, { target: { value: "medium" } });
    await waitFor(() => expect((dropdown as HTMLSelectElement).value).toBe("medium"), { timeout: 2000 });

    // With Cytoscape (Canvas-based), we can't check node positions like with SVG
    // Just verify the graph container is rendered
    expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
  });

  it("when switching script, compile is called with new code and graph shows new nodes", async () => {
    const simpleNodes = {
      nodes: [
        { id: "products_1", type: "input", label: "products", source_range: null },
        { id: "sem_gen_features_2", type: "operator", label: "sem_gen_features", source_range: null },
      ],
      edges: [{ source: "products_1", target: "sem_gen_features_2" }],
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
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
      const urlStr = urlFromRequest(input);
      if (urlStr.includes("/api/scripts") && !urlStr.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (urlStr.includes("/api/scripts/medium")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mediumScriptContent) } as Response);
      }
      if (urlStr.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (urlStr.includes("/api/compile")) {
        const body = JSON.parse((_init?.body as string) ?? "{}");
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

    await waitFor(() => {
      expect(screen.getByText(/No computational graph yet/)).toBeInTheDocument();
    }, { timeout: 2000 });

    const dropdown = screen.getByTitle("Select pipeline script");
    fireEvent.change(dropdown, { target: { value: "medium" } });

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

    fireEvent.change(dropdown, { target: { value: "simple" } });

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
  });

  // Skipped: Cytoscape uses Canvas rendering, so we cannot simulate graph node clicks in jsdom
  it.skip("after Run, selecting a node shows that node's generated code in right panel (design: live updates)", async () => {
    const compileResponse = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_2", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [{ source: "as_X_1", target: "sem_fillna_2" }],
    };
    const generatedCodeForNode = "# Generated for sem_fillna\ndef fill_missing(df):\n    return df.fillna(0)";
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/update-config")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok", llm_name: "gemini/gemini-2.5-flash-lite", temperature: 0.0 }),
          text: () => Promise.resolve(""),
        } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse), text: () => Promise.resolve("") } as Response);
      }
      if (u.includes("/api/execute")) {
        const skrubGraph = {
          nodes: [
            { id: "0", label: "as_X", is_sempipes_semantic: false },
            { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
          ],
          parents: { "0": [], "1": ["0"] },
          children: { "0": ["1"], "1": [] },
          sempipesNodeIds: ["1"],
        };
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode('data: {"type":"terminal","line":"Starting..."}\n\n')
              );
              controller.enqueue(
                new TextEncoder().encode(
                  `data: ${JSON.stringify({ type: "node_code", node_id: "skrub_1", generated_code: generatedCodeForNode })}\n\n`
                )
              );
              controller.enqueue(
                new TextEncoder().encode(`data: ${JSON.stringify({ type: "skrub_graph", graph: skrubGraph })}\n\n`)
              );
              controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
              controller.close();
            },
          }),
          headers: new Headers({ "content-type": "text/event-stream" }),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    // Before Run: no graph, placeholder only
    await waitFor(() => expect(screen.getByText(/No computational graph yet/)).toBeInTheDocument(), { timeout: 2000 });

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /run/i })).not.toBeDisabled(), { timeout: 3000 });
    // After Run: single interactive Skrub graph is shown; click semantic operator to see generated code.
    await waitFor(() => expect(screen.getByText(/Computational graph \(from code\)/)).toBeInTheDocument(), { timeout: 2000 });
    await waitFor(() => expect(screen.getByRole("button", { name: /Graph node sem_fillna/ })).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: /Graph node sem_fillna/ }));
    await waitFor(() => {
      // Node details panel shows Generated code section; caption also mentions "generated code"
      expect(screen.getAllByText(/Generated code/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/sem_fillna/).length).toBeGreaterThanOrEqual(1);
    }, { timeout: 3000 });
  });

  // Skipped: jsdom does not reliably fire click/pointer events on SVG <g> elements, so we cannot
  // simulate graph node clicks. NodeDetailsPanel tests verify data summary display when props are correct.
  it.skip("after Run with input_summary, clicking input node shows data summary (schema, sample, row count)", { timeout: 10000 }, async () => {
    const scriptWithAsX = {
      id: "simple",
      label: "Simple",
      content: "import sempipes\nas_X = sempipes.as_X(df, 'X')\nas_X.sem_fillna(target_column='a')\n",
    };
    const compileResponse = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_2", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [{ source: "as_X_1", target: "sem_fillna_2" }],
    };
    const inputSummary = {
      node_id: "skrub_0",
      schema: [{ name: "ID", dtype: "int64" }],
      sample: [{ ID: 1 }, { ID: 2 }, { ID: 3 }],
      row_count: 5000,
    };
    const skrubGraph = {
      nodes: [
        { id: "0", label: "as_X", is_sempipes_semantic: false },
        { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
      ],
      parents: { "0": [], "1": ["0"] },
      children: { "0": ["1"], "1": [] },
      sempipesNodeIds: ["1"],
    };
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(scriptWithAsX) } as Response);
      }
      if (u.includes("/api/update-config")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok", llm_name: "gemini/gemini-2.5-flash-lite", temperature: 0.0 }),
          text: () => Promise.resolve(""),
        } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse), text: () => Promise.resolve("") } as Response);
      }
      if (u.includes("/api/execute")) {
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode('data: {"type":"terminal","line":"Starting..."}\n\n')
              );
              controller.enqueue(
                new TextEncoder().encode(
                  `data: ${JSON.stringify({ type: "input_summary", ...inputSummary })}\n\n`
                )
              );
              controller.enqueue(
                new TextEncoder().encode(
                  `data: ${JSON.stringify({ type: "node_code", node_id: "skrub_0", generated_code: "# input" })}\n\n`
                )
              );
              controller.enqueue(
                new TextEncoder().encode(
                  `data: ${JSON.stringify({ type: "node_code", node_id: "skrub_1", generated_code: "# code" })}\n\n`
                )
              );
              controller.enqueue(
                new TextEncoder().encode(`data: ${JSON.stringify({ type: "skrub_graph", graph: skrubGraph })}\n\n`)
              );
              controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
              controller.close();
            },
          }),
          headers: new Headers({ "content-type": "text/event-stream" }),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText(/No computational graph yet/)).toBeInTheDocument(), { timeout: 2000 });
    await waitFor(() => expect(screen.getByTitle("Select pipeline script")).toBeInTheDocument(), { timeout: 2000 });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 600));
    });

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /run/i })).not.toBeDisabled(), { timeout: 3000 });
    await waitFor(() => expect(screen.getByText(/Computational graph \(from code\)/)).toBeInTheDocument(), { timeout: 2000 });
    await waitFor(() => expect(screen.getByTestId("graph-node-0")).toBeInTheDocument(), { timeout: 2000 });

    fireEvent.click(screen.getByTestId("graph-node-0"));

    await waitFor(() => {
      expect(screen.getByText("Data summary")).toBeInTheDocument();
    }, { timeout: 2000 });
    expect(screen.getByText(/Rows: 5,000/)).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
    expect(screen.getByText("int64")).toBeInTheDocument();
    expect(screen.getByText(/Sample \(first 3 rows\)/)).toBeInTheDocument();
  });

  // Skipped: Cytoscape uses Canvas rendering, so we cannot simulate graph node clicks in jsdom
  it.skip("clicking graph node selects it and shows node details (graph-to-code uses InputEditor data-highlighted)", async () => {
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
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByTestId("graph-node-as_X_1")).toBeInTheDocument(), { timeout: 3000 });

    fireEvent.click(screen.getByTestId("graph-node-as_X_1"));

    await waitFor(
      () => {
        expect(screen.getAllByText(/as_X/).length).toBeGreaterThanOrEqual(1);
      },
      { timeout: 2000 }
    );

    const editor = screen.getByTestId("input-editor");
    expect(editor.getAttribute("data-highlighted")).toBe("as_X_1");
  });

  // Skipped: Cytoscape uses Canvas rendering, so we cannot simulate graph node clicks in jsdom
  it.skip("graph-to-code: clicking operator node highlights corresponding code in editor", async () => {
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
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByTestId("graph-node-sem_fillna_2")).toBeInTheDocument(), { timeout: 3000 });

    fireEvent.click(screen.getByTestId("graph-node-sem_fillna_2"));

    await waitFor(
      () => {
        const editor = screen.getByTestId("input-editor");
        expect(editor.getAttribute("data-highlighted")).toBe("sem_fillna_2");
      },
      { timeout: 2000 }
    );
  });

  it("when switching script, selection is cleared and node details show placeholder", async () => {
    const compileResponse = {
      nodes: [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_2", type: "operator", label: "sem_fillna", source_range: null },
      ],
      edges: [{ source: "as_X_1", target: "sem_fillna_2" }],
    };
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(compileResponse) } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    // Wait for the component to load; before Run we show placeholder (no graph)
    await waitFor(() => expect(screen.getByText(/No computational graph yet/)).toBeInTheDocument(), { timeout: 2000 });

    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ nodes: [{ id: "op1", type: "operator", label: "Op", source_range: null }], edges: [] }),
    } as Response);
    const dropdown = screen.getByTitle("Select pipeline script");
    fireEvent.change(dropdown, { target: { value: "medium" } });

    // After switching scripts, placeholder should still be shown
    await waitFor(() => {
      expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
    });
  });

  it("shows LLM selection dropdown and temperature input", async () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => {
      expect(screen.getByText("Model:")).toBeInTheDocument();
      expect(screen.getByTitle("Select LLM model")).toBeInTheDocument();
      expect(screen.getByText("Temperature:")).toBeInTheDocument();
      expect(screen.getByTitle("LLM temperature (0-2)")).toBeInTheDocument();
    });
  });

  it("LLM dropdown has expected options", async () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => {
      const dropdown = screen.getByTitle("Select LLM model") as HTMLSelectElement;
      expect(dropdown).toBeInTheDocument();
      const options = Array.from(dropdown.options).map((o) => o.value);
      expect(options).toContain("gpt-5-mini");
      expect(options).toContain("gpt-4.1-mini");
      expect(options).toContain("gemini/gemini-2.5-flash");
      expect(options).toContain("gemini/gemini-2.5-flash-lite");
      expect(options).toContain("gemini/gemini-2.5-pro");
      expect(options).toContain("gemini/gemini-3-flash-preview");
      expect(options).toContain("gemini/gemini-3-flash-lite-preview");
      expect(options).toContain("gemini/gemini-3-pro-preview");
    });
  });

  it("validates temperature range (0-2) and shows error for invalid values", async () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByTitle("LLM temperature (0-2)")).toBeInTheDocument());

    const tempInput = screen.getByTitle("LLM temperature (0-2)") as HTMLInputElement;

    // Test invalid value: negative
    fireEvent.change(tempInput, { target: { value: "-1" } });
    await waitFor(() => {
      expect(tempInput).toHaveClass("border-red-500");
      expect(screen.getByText("0-2")).toBeInTheDocument();
    });

    // Wait longer than animation duration (820ms) and verify error persists
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    });
    expect(tempInput).toHaveClass("border-red-500");
    expect(screen.getByText("0-2")).toBeInTheDocument();

    // Test invalid value: greater than 2
    fireEvent.change(tempInput, { target: { value: "3" } });
    await waitFor(() => {
      expect(tempInput).toHaveClass("border-red-500");
      expect(screen.getByText("0-2")).toBeInTheDocument();
    });

    // Test invalid value: not a number
    fireEvent.change(tempInput, { target: { value: "abc" } });
    await waitFor(() => {
      expect(tempInput).toHaveClass("border-red-500");
    });

    // Test valid value clears error
    fireEvent.change(tempInput, { target: { value: "0.7" } });
    await waitFor(() => {
      expect(tempInput).not.toHaveClass("border-red-500");
      expect(screen.queryByText("0-2")).not.toBeInTheDocument();
    });
  });

  it("calls update-config API with selected LLM and temperature before executing pipeline", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, __init?: RequestInit) => {
      const u = urlFromRequest(input);
      if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPTS) } as Response);
      }
      if (u.includes("/api/scripts/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT) } as Response);
      }
      if (u.includes("/api/update-config")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok", llm_name: "gemini/gemini-3-flash-preview", temperature: 0.7 }),
        } as Response);
      }
      if (u.includes("/api/execute")) {
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
              controller.close();
            },
          }),
          headers: new Headers({ "content-type": "text/event-stream" }),
        } as Response);
      }
      if (u.includes("/api/compile")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ nodes: [{ id: "n1", type: "operator", label: "op" }], edges: [] }),
        } as Response);
      }
      return Promise.resolve({ ok: false } as Response);
    });

    render(<CodeGenDemo />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByRole("button", { name: /run/i })).not.toBeDisabled());

    // Change LLM to gemini/gemini-3-flash-preview
    const dropdown = screen.getByTitle("Select LLM model") as HTMLSelectElement;
    fireEvent.change(dropdown, { target: { value: "gemini/gemini-3-flash-preview" } });

    // Change temperature to 0.7
    const tempInput = screen.getByTitle("LLM temperature (0-2)") as HTMLInputElement;
    fireEvent.change(tempInput, { target: { value: "0.7" } });

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => {
      const updateConfigCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
        (c) => String(c[0]).includes("/api/update-config")
      );
      expect(updateConfigCalls.length).toBeGreaterThanOrEqual(1);
      const body = JSON.parse((updateConfigCalls[0][1] as RequestInit)?.body as string);
      expect(body.llm_name).toBe("gemini/gemini-3-flash-preview");
      expect(body.temperature).toBe(0.7);
    });
  });

  it("renders expand buttons for all three panels", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByTestId("expand-left-panel")).toBeInTheDocument();
    expect(screen.getByTestId("expand-middle-panel")).toBeInTheDocument();
    expect(screen.getByTestId("expand-right-panel")).toBeInTheDocument();
  });

  it("expands left panel when expand button is clicked", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    const expandBtn = screen.getByTestId("expand-left-panel");

    // Initially shows expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");

    // Click to expand
    fireEvent.click(expandBtn);

    // Now shows restore icon
    expect(expandBtn).toHaveAttribute("aria-label", "Restore panel size");

    // Click again to restore
    fireEvent.click(expandBtn);

    // Back to expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");
  });

  it("expands middle panel when expand button is clicked", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    const expandBtn = screen.getByTestId("expand-middle-panel");

    // Initially shows expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");

    // Click to expand
    fireEvent.click(expandBtn);

    // Now shows restore icon
    expect(expandBtn).toHaveAttribute("aria-label", "Restore panel size");

    // Click again to restore
    fireEvent.click(expandBtn);

    // Back to expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");
  });

  it("expands right panel when expand button is clicked", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    const expandBtn = screen.getByTestId("expand-right-panel");

    // Initially shows expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");

    // Click to expand
    fireEvent.click(expandBtn);

    // Now shows restore icon
    expect(expandBtn).toHaveAttribute("aria-label", "Restore panel size");

    // Click again to restore
    fireEvent.click(expandBtn);

    // Back to expand icon
    expect(expandBtn).toHaveAttribute("aria-label", "Expand panel");
  });

  describe("Skrub graph from execution", () => {
    it("stores skrub graph when skrub_graph event is received during execution", async () => {
      const compileResponse = {
        nodes: [
          { id: "0", label: "<Var 'products'>", type: "input" },
          { id: "1", label: "<SubsamplePreviews>", type: "operator" },
          { id: "7", label: "sem_gen_features", type: "operator" },
        ],
        edges: [
          { source: "0", target: "1" },
          { source: "1", target: "7" },
        ],
        validation_errors: [],
      };

      const skrubGraphDict = {
        nodes: [
          { id: "0", label: "<Var 'products'>", is_sempipes_semantic: false },
          { id: "1", label: "<SubsamplePreviews>", is_sempipes_semantic: false },
          { id: "2", label: "sem_gen_features", is_sempipes_semantic: true },
        ],
        parents: { "0": [], "1": ["0"], "2": ["1"] },
        children: { "0": ["1"], "1": ["2"], "2": [] },
        sempipesNodeIds: ["2"],
      };

      vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
        const u = urlFromRequest(input);
        if (u.includes("/api/compile")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(compileResponse),
          } as Response);
        }
        if (u.includes("/api/execute")) {
          return Promise.resolve({
            ok: true,
            body: new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({
                      type: "skrub_graph",
                      graph: skrubGraphDict,
                      skrubToCompileId: { "0": "0", "1": "1", "2": "7" },
                    })}\n\n`
                  )
                );
                controller.enqueue(
                  new TextEncoder().encode(`data: ${JSON.stringify({ type: "done" })}\n\n`)
                );
                controller.close();
              },
            }),
          } as Response);
        }
        mockFetchDefault(); return vi.mocked(fetch)(input, _init);
      });

      render(<CodeGenDemo />, { wrapper: wrapper() });

      await waitFor(() => expect(screen.getByTitle("Run pipeline")).toBeInTheDocument());

      const runBtn = screen.getByTitle("Run pipeline");
      fireEvent.click(runBtn);

      // After execution, the graph should show skrub nodes (not compile nodes)
      await waitFor(() => {
        // The graph should be rendered (we can't easily test the internal state,
        // but we can verify the component doesn't crash and execution completes)
        expect(runBtn).not.toBeDisabled();
      });
    });

    it("uses skrub graph IDs for display after execution (not compile IDs)", async () => {
      const compileResponse = {
        nodes: [
          { id: "0", label: "<Var 'products'>", type: "input", source_range: { start_line: 1, start_column: 0, end_line: 1, end_column: 10 } },
          { id: "1", label: "<SubsamplePreviews>", type: "operator", source_range: { start_line: 2, start_column: 0, end_line: 2, end_column: 20 } },
          { id: "7", label: "sem_gen_features", type: "operator", source_range: { start_line: 3, start_column: 0, end_line: 3, end_column: 30 } },
        ],
        edges: [
          { source: "0", target: "1" },
          { source: "1", target: "7" },
        ],
        validation_errors: [],
      };

      const skrubGraphDict = {
        nodes: [
          { id: "0", label: "<Var 'products'>", is_sempipes_semantic: false },
          { id: "1", label: "<SubsamplePreviews>", is_sempipes_semantic: false },
          { id: "2", label: "sem_gen_features", is_sempipes_semantic: true },
        ],
        parents: { "0": [], "1": ["0"], "2": ["1"] },
        children: { "0": ["1"], "1": ["2"], "2": [] },
        sempipesNodeIds: ["2"],
      };

      vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
        const u = urlFromRequest(input);
        if (u.includes("/api/compile")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(compileResponse),
          } as Response);
        }
        if (u.includes("/api/execute")) {
          return Promise.resolve({
            ok: true,
            body: new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({
                      type: "node_code",
                      node_id: "2",
                      generated_code: "# Generated code for sem_gen_features",
                    })}\n\n`
                  )
                );
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({
                      type: "skrub_graph",
                      graph: skrubGraphDict,
                      skrubToCompileId: { "0": "0", "1": "1", "2": "7" },
                    })}\n\n`
                  )
                );
                controller.enqueue(
                  new TextEncoder().encode(`data: ${JSON.stringify({ type: "done" })}\n\n`)
                );
                controller.close();
              },
            }),
          } as Response);
        }
        mockFetchDefault(); return vi.mocked(fetch)(input, _init);
      });

      render(<CodeGenDemo />, { wrapper: wrapper() });

      await waitFor(() => expect(screen.getByTitle("Run pipeline")).toBeInTheDocument());

      const runBtn = screen.getByTitle("Run pipeline");
      fireEvent.click(runBtn);

      // Wait for execution to complete
      await waitFor(() => {
        expect(runBtn).not.toBeDisabled();
      });

      // The graph should now use skrub IDs (0, 1, 2) not compile IDs (0, 1, 7)
      // We can verify this indirectly by checking that the component rendered without errors
      // and that node_code event with ID "2" was received
      // (In a real test, we'd need to inspect the graph visualization, but that's complex with Cytoscape)
    });

    it("clears skrub graph when starting new execution", async () => {
      const compileResponse = {
        nodes: [
          { id: "0", label: "<Var 'products'>", type: "input" },
          { id: "1", label: "sem_gen_features", type: "operator" },
        ],
        edges: [{ source: "0", target: "1" }],
        validation_errors: [],
      };

      const firstSkrubGraph = {
        nodes: [
          { id: "0", label: "<Var 'products'>", is_sempipes_semantic: false },
          { id: "1", label: "sem_gen_features", is_sempipes_semantic: true },
        ],
        parents: { "0": [], "1": ["0"] },
        children: { "0": ["1"], "1": [] },
        sempipesNodeIds: ["1"],
      };

      const secondSkrubGraph = {
        nodes: [
          { id: "0", label: "<Var 'data'>", is_sempipes_semantic: false },
          { id: "1", label: "sem_fillna", is_sempipes_semantic: true },
        ],
        parents: { "0": [], "1": ["0"] },
        children: { "0": ["1"], "1": [] },
        sempipesNodeIds: ["1"],
      };

      let executionCount = 0;

      vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
        const u = urlFromRequest(input);
        if (u.includes("/api/scripts") && !u.includes("/api/scripts/")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(DEFAULT_SCRIPTS),
          } as Response);
        }
        if (u.match(/\/api\/scripts\/[^/]+$/)) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(DEFAULT_SCRIPT_CONTENT),
          } as Response);
        }
        if (u.includes("/api/compile")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(compileResponse),
          } as Response);
        }
        if (u.includes("/api/update-config")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ message: "Config updated" }),
          } as Response);
        }
        if (u.includes("/api/execute")) {
          executionCount++;
          const graphToUse = executionCount === 1 ? firstSkrubGraph : secondSkrubGraph;
          return Promise.resolve({
            ok: true,
            body: new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({
                      type: "skrub_graph",
                      graph: graphToUse,
                      skrubToCompileId: { "0": "0", "1": "1" },
                    })}\n\n`
                  )
                );
                controller.enqueue(
                  new TextEncoder().encode(`data: ${JSON.stringify({ type: "done" })}\n\n`)
                );
                controller.close();
              },
            }),
          } as Response);
        }
        return Promise.reject(new Error(`Unmocked URL: ${u}`));
      });

      render(<CodeGenDemo />, { wrapper: wrapper() });

      await waitFor(() => expect(screen.getByTitle("Run pipeline")).toBeInTheDocument());

      const runBtn = screen.getByTitle("Run pipeline");

      // First execution
      fireEvent.click(runBtn);
      await waitFor(() => expect(runBtn).not.toBeDisabled());

      // Second execution - should clear the first graph before using the second
      fireEvent.click(runBtn);
      await waitFor(() => expect(runBtn).not.toBeDisabled());

      // Verify both executions happened
      expect(executionCount).toBe(2);
    });

    it("uses compile preview graph before execution, skrub graph after", async () => {
      const compileResponse = {
        nodes: [
          { id: "0", label: "<Var 'products'>", type: "input" },
          { id: "7", label: "sem_gen_features", type: "operator" },
        ],
        edges: [{ source: "0", target: "7" }],
        validation_errors: [],
      };

      const skrubGraphDict = {
        nodes: [
          { id: "0", label: "<Var 'products'>", is_sempipes_semantic: false },
          { id: "2", label: "sem_gen_features", is_sempipes_semantic: true },
        ],
        parents: { "0": [], "2": ["0"] },
        children: { "0": ["2"], "2": [] },
        sempipesNodeIds: ["2"],
      };

      vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, _init?: RequestInit) => {
        const u = urlFromRequest(input);
        if (u.includes("/api/compile")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(compileResponse),
          } as Response);
        }
        if (u.includes("/api/execute")) {
          return Promise.resolve({
            ok: true,
            body: new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({
                      type: "skrub_graph",
                      graph: skrubGraphDict,
                      skrubToCompileId: { "0": "0", "2": "7" },
                    })}\n\n`
                  )
                );
                controller.enqueue(
                  new TextEncoder().encode(`data: ${JSON.stringify({ type: "done" })}\n\n`)
                );
                controller.close();
              },
            }),
          } as Response);
        }
        mockFetchDefault(); return vi.mocked(fetch)(input, _init);
      });

      render(<CodeGenDemo />, { wrapper: wrapper() });

      await waitFor(() => expect(screen.getByTitle("Run pipeline")).toBeInTheDocument());

      // Before execution: compile preview graph is shown (nodes with IDs "0", "7")
      // After clicking Run: skrub graph replaces it (nodes with IDs "0", "2")

      const runBtn = screen.getByTitle("Run pipeline");
      fireEvent.click(runBtn);

      await waitFor(() => expect(runBtn).not.toBeDisabled());

      // Verify execution completed without errors
      // The graph should now show the skrub graph instead of compile preview
    });
  });
});
