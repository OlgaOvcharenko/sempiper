import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listPipelineScripts,
  getPipelineScriptContent,
  executePipelineStream,
  compileToSkrubGraph,
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

  describe("compileToSkrubGraph", () => {
    it("converts compile nodes and edges to SkrubGraphDict for preview", () => {
      const nodes = [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        { id: "sem_fillna_2", type: "operator", label: "sem_fillna", source_range: null },
      ];
      const edges = [{ source: "as_X_1", target: "sem_fillna_2" }];
      const result = compileToSkrubGraph(nodes, edges);
      expect(result).not.toBeNull();
      expect(result!.nodes).toHaveLength(2);
      expect(result!.nodes[0]).toEqual({ id: "as_X_1", label: "as_X", is_sempipes_semantic: false });
      expect(result!.nodes[1]).toEqual({ id: "sem_fillna_2", label: "sem_fillna", is_sempipes_semantic: true });
      expect(result!.parents["as_X_1"]).toEqual([]);
      expect(result!.parents["sem_fillna_2"]).toEqual(["as_X_1"]);
      expect(result!.children["as_X_1"]).toEqual(["sem_fillna_2"]);
      expect(result!.sempipesNodeIds).toEqual(["sem_fillna_2"]);
    });

    it("returns null when nodes array is empty", () => {
      expect(compileToSkrubGraph([], [])).toBeNull();
    });

    it("filters edges to only include valid node references", () => {
      const nodes = [
        { id: "n1", type: "input", label: "a", source_range: null },
        { id: "n2", type: "operator", label: "b", source_range: null },
      ];
      const edges = [
        { source: "n1", target: "n2" },
        { source: "n1", target: "n3" },
        { source: "n0", target: "n2" },
      ];
      const result = compileToSkrubGraph(nodes, edges);
      expect(result!.parents["n2"]).toEqual(["n1"]);
      expect(result!.children["n1"]).toEqual(["n2"]);
    });

    it("produces medium-like structure for layout: baskets branch before products branch", () => {
      const nodes = [
        { id: "var_products_13", type: "input", label: "products", source_range: null },
        { id: "var_baskets_14", type: "input", label: "baskets", source_range: null },
        { id: "subsample_15", type: "operator", label: "skb.subsample", source_range: null },
        { id: "as_X_18", type: "input", label: "as_X", source_range: null },
        { id: "as_y_19", type: "input", label: "as_y", source_range: null },
        { id: "sem_fillna_22", type: "operator", label: "sem_fillna", source_range: null },
        { id: "sem_gen_features_28", type: "operator", label: "sem_gen_features", source_range: null },
        { id: "skb_apply_36", type: "operator", label: "skb.apply", source_range: null },
        { id: "apply_with_sem_choose_44", type: "operator", label: "apply_with_sem_choose", source_range: null },
        { id: "sem_choose_47", type: "operator", label: "sem_choose", source_range: null },
      ];
      const edges = [
        { source: "var_baskets_14", target: "subsample_15" },
        { source: "subsample_15", target: "as_X_18" },
        { source: "subsample_15", target: "as_y_19" },
        { source: "var_products_13", target: "sem_fillna_22" },
        { source: "sem_fillna_22", target: "sem_gen_features_28" },
        { source: "as_X_18", target: "sem_gen_features_28" },
        { source: "sem_gen_features_28", target: "skb_apply_36" },
        { source: "as_X_18", target: "apply_with_sem_choose_44" },
        { source: "skb_apply_36", target: "apply_with_sem_choose_44" },
        { source: "as_y_19", target: "apply_with_sem_choose_44" },
        { source: "sem_choose_47", target: "apply_with_sem_choose_44" },
      ];
      const result = compileToSkrubGraph(nodes, edges);
      expect(result).not.toBeNull();
      expect(result!.nodes).toHaveLength(10);
      expect(result!.children["var_baskets_14"]).toContain("subsample_15");
      expect(result!.children["var_products_13"]).toContain("sem_fillna_22");
      expect(result!.parents["as_X_18"]).toContain("subsample_15");
      expect(result!.parents["as_y_19"]).toContain("subsample_15");
      expect(result!.parents["sem_gen_features_28"]).toEqual(
        expect.arrayContaining(["sem_fillna_22", "as_X_18"])
      );
      const nodeIndex = new Map(result!.nodes.map((n, i) => [n.id, i]));
      const basketsChildIdx = Math.min(...(result!.children["var_baskets_14"] ?? []).map((c) => nodeIndex.get(c) ?? 999));
      const productsChildIdx = Math.min(...(result!.children["var_products_13"] ?? []).map((c) => nodeIndex.get(c) ?? 999));
      expect(basketsChildIdx).toBeLessThan(productsChildIdx);
    });

    it("marks all 10 SemPipes operators as sempipes for highlighting (sempipesNodeIds and is_sempipes_semantic)", () => {
      const sempipesOperatorLabels = [
        "sem_fillna",
        "sem_gen_features",
        "sem_extract_features",
        "sem_clean",
        "sem_augment",
        "sem_agg_features",
        "sem_refine",
        "sem_select",
        "sem_distill",
        "sem_choose",
      ];
      const nodes = [
        { id: "as_X_1", type: "input", label: "as_X", source_range: null },
        ...sempipesOperatorLabels.map((label, i) => ({
          id: `op_${i}`,
          type: "operator" as const,
          label,
          source_range: null as null,
        })),
      ];
      const edges = sempipesOperatorLabels.map((_, i) => ({
        source: i === 0 ? "as_X_1" : `op_${i - 1}`,
        target: `op_${i}`,
      }));
      const result = compileToSkrubGraph(nodes, edges);
      expect(result).not.toBeNull();
      expect(result!.sempipesNodeIds).toHaveLength(10);
      expect(result!.sempipesNodeIds).toEqual(expect.arrayContaining(nodes.slice(1).map((n) => n.id)));
      for (const node of result!.nodes) {
        if (sempipesOperatorLabels.includes(node.label)) {
          expect(node.is_sempipes_semantic).toBe(true);
        }
      }
    });
  });
});
