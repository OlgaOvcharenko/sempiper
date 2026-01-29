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
});
