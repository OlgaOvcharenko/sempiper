import { describe, it, expect } from "vitest";
import {
  skrubIdToRaw,
  toSkrubId,
  graphNodeToCompileIds,
  compileIdsToSkrubIds,
} from "../../src/utils/graphCodeSync";

describe("graphCodeSync", () => {
  describe("skrubIdToRaw", () => {
    it("strips skrub_ prefix", () => {
      expect(skrubIdToRaw("skrub_0")).toBe("0");
      expect(skrubIdToRaw("skrub_as_X_1")).toBe("as_X_1");
    });
    it("returns id unchanged when no prefix", () => {
      expect(skrubIdToRaw("as_X_1")).toBe("as_X_1");
    });
  });

  describe("toSkrubId", () => {
    it("adds skrub_ prefix", () => {
      expect(toSkrubId("0")).toBe("skrub_0");
      expect(toSkrubId("as_X_1")).toBe("skrub_as_X_1");
    });
  });

  describe("graphNodeToCompileIds", () => {
    const compileNodes = [
      { id: "as_X_1", label: "as_X", source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 20 } },
      { id: "sem_fillna_2", label: "sem_fillna", source_range: { start_line: 2, start_column: 1, end_line: 2, end_column: 25 } },
    ];

    it("matches by id or label (compile-time only; skrubToCompileId not used for code-graph sync)", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {});
      expect(ids).toEqual(["as_X_1"]);
    });

    it("matches by id in preview mode", () => {
      const ids = graphNodeToCompileIds("as_X_1", { id: "as_X_1", label: "as_X" }, compileNodes, {});
      expect(ids).toEqual(["as_X_1"]);
    });

    it("matches by label when id does not match", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {});
      expect(ids).toEqual(["as_X_1"]);
    });

    it("uses runnable index when numeric id", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "x" }, compileNodes, {
        runnableNodeIds: ["as_X_1", "sem_fillna_2"],
      });
      expect(ids).toEqual(["as_X_1"]);
    });

    it("returns empty when no match", () => {
      const ids = graphNodeToCompileIds("99", { id: "99", label: "unknown" }, compileNodes, {});
      expect(ids).toEqual([]);
    });
  });

  describe("compileIdsToSkrubIds", () => {
    const displayNodes = [
      { id: "0", label: "as_X" },
      { id: "1", label: "sem_fillna" },
    ];
    const compileNodes = [
      { id: "as_X_1", label: "as_X", source_range: null },
      { id: "sem_fillna_2", label: "sem_fillna", source_range: null },
    ];

    it("maps by label in post-run mode", () => {
      const ids = compileIdsToSkrubIds(["as_X_1"], displayNodes, compileNodes, true);
      expect(ids).toContain("skrub_0");
    });

    it("maps multiple compile ids to skrub ids in post-run mode", () => {
      const ids = compileIdsToSkrubIds(["as_X_1", "sem_fillna_2"], displayNodes, compileNodes, true);
      expect(ids).toContain("skrub_0");
      expect(ids).toContain("skrub_1");
      expect(ids).toHaveLength(2);
    });

    it("maps by id in preview mode", () => {
      const displayPreview = [{ id: "as_X_1", label: "as_X" }];
      const ids = compileIdsToSkrubIds(["as_X_1"], displayPreview, compileNodes, false);
      expect(ids).toEqual(["skrub_as_X_1"]);
    });

    it("returns empty when no compile ids", () => {
      expect(compileIdsToSkrubIds([], displayNodes, compileNodes, true)).toEqual([]);
    });

    it("returns empty when display graph has no nodes", () => {
      expect(compileIdsToSkrubIds(["as_X_1"], [], compileNodes, true)).toEqual([]);
    });
  });

  describe("graphNodeToCompileIds (compile-time only; run does not change mapping)", () => {
    const compileNodes = [
      { id: "as_X_1", label: "as_X", source_range: null },
      { id: "sem_fillna_2", label: "sem_fillna", source_range: null },
    ];

    it("uses label match not runtime skrubToCompileId so mapping is stable after run", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {
        skrubToCompileId: { "0": "sem_fillna_2" },
      });
      expect(ids).toEqual(["as_X_1"]);
    });

    it("handles multiple graph nodes by label / runnable index", () => {
      const ids1 = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {});
      const ids2 = graphNodeToCompileIds("1", { id: "1", label: "sem_fillna" }, compileNodes, {});
      expect(ids1).toEqual(["as_X_1"]);
      expect(ids2).toEqual(["sem_fillna_2"]);
    });
  });

  describe("graphNodeToCompileIds (order-sensitive scenarios)", () => {
    /**
     * Regression tests for the bug where clicking node N highlights code for node N-1.
     * This happens when the node mapping returns the wrong compile node.
     */

    it("does not return earlier node when labels are different", () => {
      const compileNodes = [
        { id: "var_5", label: "var", source_range: { start_line: 5, start_column: 1, end_line: 5, end_column: 20 } },
        { id: "fillna_6", label: "sem_fillna", source_range: { start_line: 6, start_column: 1, end_line: 6, end_column: 25 } },
        { id: "gen_7", label: "sem_gen_features", source_range: { start_line: 7, start_column: 1, end_line: 7, end_column: 30 } },
      ];

      // Clicking sem_gen_features (node 2 in graph) should return gen_7, not fillna_6
      const ids = graphNodeToCompileIds("2", { id: "2", label: "sem_gen_features" }, compileNodes, {
        runnableNodeIds: ["var_5", "fillna_6", "gen_7"],
      });

      expect(ids).toEqual(["gen_7"]);
      expect(ids).not.toContain("fillna_6"); // Should NOT be the previous node
    });

    it("correctly maps consecutive graph nodes to consecutive compile nodes", () => {
      const compileNodes = [
        { id: "node_A", label: "op_A", source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 10 } },
        { id: "node_B", label: "op_B", source_range: { start_line: 2, start_column: 1, end_line: 2, end_column: 10 } },
        { id: "node_C", label: "op_C", source_range: { start_line: 3, start_column: 1, end_line: 3, end_column: 10 } },
      ];

      // Graph nodes 0, 1, 2 should map to node_A, node_B, node_C respectively
      const ids0 = graphNodeToCompileIds("0", { id: "0", label: "op_A" }, compileNodes, {
        runnableNodeIds: ["node_A", "node_B", "node_C"],
      });
      const ids1 = graphNodeToCompileIds("1", { id: "1", label: "op_B" }, compileNodes, {
        runnableNodeIds: ["node_A", "node_B", "node_C"],
      });
      const ids2 = graphNodeToCompileIds("2", { id: "2", label: "op_C" }, compileNodes, {
        runnableNodeIds: ["node_A", "node_B", "node_C"],
      });

      expect(ids0).toEqual(["node_A"]);
      expect(ids1).toEqual(["node_B"]);
      expect(ids2).toEqual(["node_C"]);
    });

    it("handles multiple nodes with the same label by preferring document order", () => {
      // Scenario: Two skrub.var calls with the same name argument
      const compileNodes = [
        { id: "var_products_5", label: "products", source_range: { start_line: 5, start_column: 1, end_line: 5, end_column: 20 } },
        { id: "var_products_8", label: "products", source_range: { start_line: 8, start_column: 1, end_line: 8, end_column: 20 } },
      ];

      // When graphNodeId is "0", should return the first matching node (line 5)
      const ids0 = graphNodeToCompileIds("0", { id: "0", label: "products" }, compileNodes, {});

      // Currently returns both - this test documents current behavior
      // The fix should make this more predictable
      expect(ids0).toContain("var_products_5");
    });

    it("uses runnable index correctly for numeric graph IDs", () => {
      const compileNodes = [
        { id: "a_1", label: "input_a", source_range: { start_line: 1, start_column: 1, end_line: 1, end_column: 10 } },
        { id: "b_2", label: "sem_fillna", source_range: { start_line: 2, start_column: 1, end_line: 2, end_column: 10 } },
        { id: "c_3", label: "sem_gen_features", source_range: { start_line: 3, start_column: 1, end_line: 3, end_column: 10 } },
      ];

      // Graph node "1" with label "unknown" should use index 1 -> b_2
      const ids = graphNodeToCompileIds("1", { id: "1", label: "unknown" }, compileNodes, {
        runnableNodeIds: ["a_1", "b_2", "c_3"],
      });

      expect(ids).toEqual(["b_2"]);
    });

    it("regression: clicking graph node 2 does not return compile node 1's ID", () => {
      // This is the specific bug: clicking sem_gen_features (graph node 2)
      // returns sem_fillna (compile node at index 1) instead of sem_gen_features

      const compileNodes = [
        { id: "var_8", label: "products", source_range: { start_line: 8, start_column: 12, end_line: 8, end_column: 22 } },
        { id: "subsample_9", label: "skb.subsample", source_range: { start_line: 9, start_column: 15, end_line: 9, end_column: 30 } },
        { id: "gen_11", label: "sem_gen_features", source_range: { start_line: 11, start_column: 15, end_line: 11, end_column: 31 } },
        { id: "eval_17", label: "skb.eval", source_range: { start_line: 17, start_column: 11, end_line: 17, end_column: 22 } },
      ];

      // Clicking node 2 (sem_gen_features) should return gen_11
      const ids = graphNodeToCompileIds("2", { id: "2", label: "sem_gen_features" }, compileNodes, {
        runnableNodeIds: ["var_8", "subsample_9", "gen_11", "eval_17"],
      });

      expect(ids).toEqual(["gen_11"]);
      expect(ids).not.toContain("subsample_9"); // Should NOT return the previous node
    });
  });
});
