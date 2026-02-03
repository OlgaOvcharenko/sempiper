import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listPipelineScripts,
  getPipelineScriptContent,
  executePipelineStream,
} from "../../src/api/client";

describe("api/client (pipeline scripts)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  describe("listPipelineScripts", () => {
    it("returns scripts from GET /api/scripts", async () => {
      const scripts = [
        { id: "simple", label: "Simple" },
        { id: "medium", label: "Medium" },
      ];
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ scripts }),
      } as Response);

      const result = await listPipelineScripts();

      expect(fetch).toHaveBeenCalledWith("/api/scripts");
      expect(result.scripts).toEqual(scripts);
      expect(result.scripts).toHaveLength(2);
      expect(result.scripts[0]).toEqual({ id: "simple", label: "Simple" });
    });

    it("throws when response is not ok", async () => {
      vi.mocked(fetch).mockResolvedValue({
        ok: false,
        statusText: "Internal Server Error",
      } as Response);

      await expect(listPipelineScripts()).rejects.toThrow(
        /Failed to list scripts|Internal Server Error/
      );
    });
  });

  describe("getPipelineScriptContent", () => {
    it("returns id, label, content from GET /api/scripts/{name}", async () => {
      const payload = {
        id: "simple",
        label: "Simple",
        content: "# pipeline code\nimport sempipes\n",
      };
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      } as Response);

      const result = await getPipelineScriptContent("simple");

      expect(fetch).toHaveBeenCalledWith("/api/scripts/simple");
      expect(result).toEqual(payload);
      expect(result.content).toContain("sempipes");
    });

    it("encodes script name in URL", async () => {
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            id: "a+b",
            label: "A+B",
            content: "# code",
          }),
      } as Response);

      await getPipelineScriptContent("a+b");

      expect(fetch).toHaveBeenCalledWith("/api/scripts/a%2Bb");
    });

    it("throws when response is not ok", async () => {
      vi.mocked(fetch).mockResolvedValue({
        ok: false,
        statusText: "Not Found",
      } as Response);

      await expect(getPipelineScriptContent("missing")).rejects.toThrow(
        /Failed to load script|Not Found/
      );
    });
  });

  describe("executePipelineStream", () => {
    it("parses skrub_graph event and calls onEvent with type and svg", async () => {
      const skrubSvg = "<svg><text>graph</text></svg>";
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                `data: ${JSON.stringify({ type: "skrub_graph", svg: skrubSvg })}\n\n`
              )
            );
            controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
            controller.close();
          },
        }),
        headers: new Headers({ "content-type": "text/event-stream" }),
      } as Response);

      const events: Array<{ type: string; svg?: string }> = [];
      executePipelineStream("x = 1", (e) => events.push(e));

      await new Promise<void>((resolve) => {
        const check = () => {
          if (events.some((e) => e.type === "done") || events.some((e) => e.type === "skrub_graph")) {
            resolve();
            return;
          }
          setTimeout(check, 20);
        };
        setTimeout(check, 20);
      });

      const skrubEvent = events.find((e) => e.type === "skrub_graph");
      expect(skrubEvent).toBeDefined();
      expect((skrubEvent as { type: "skrub_graph"; svg: string }).svg).toBe(skrubSvg);
    });
  });
});
