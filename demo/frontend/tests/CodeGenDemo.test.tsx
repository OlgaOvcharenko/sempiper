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

describe("CodeGenDemo", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("renders title and compile button", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Sempipes pipeline demo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compile/i })).toBeInTheDocument();
  });

  it("renders Play button (execute pipeline)", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByRole("button", { name: /play/i })).toBeInTheDocument();
  });

  it("renders terminal panel for execution output", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(
      screen.getByText(/output will appear here when you run the pipeline/i)
    ).toBeInTheDocument();
  });

  it("renders middle panel as compiled graph", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText("Compiled graph")).toBeInTheDocument();
  });

  it("renders node details placeholder when no node selected", () => {
    render(<CodeGenDemo />, { wrapper: wrapper() });
    expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
  });

  it("calls API when Compile is clicked", async () => {
    const mockFetch = vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          generated_code: "int main() {}",
          language: "cpp",
          compilation_time_ms: 10,
          metadata: {
            optimizations_applied: [],
            ir_size_bytes: 0,
            stages: [],
          },
        }),
    } as Response);

    render(<CodeGenDemo />, { wrapper: wrapper() });
    fireEvent.click(screen.getByRole("button", { name: /compile/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/generate",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string);
    expect(body.input_code).toBeDefined();
    expect(body.options).toEqual({ optimization_level: 2, target: "cpp" });
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
    vi.mocked(fetch).mockImplementation((url: string | URL | Request) => {
      const u = typeof url === "string" ? url : url instanceof Request ? url.url : (url as URL).href;
      if (u.includes("/api/compile")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(compileResponse),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            generated_code: "",
            language: "cpp",
            compilation_time_ms: 0,
            metadata: {},
          }),
      } as Response);
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
});
