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

    it("uses backend mapping when available", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {
        skrubToCompileId: { "0": "as_X_1" },
      });
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

  describe("graphNodeToCompileIds (backend mapping precedence)", () => {
    const compileNodes = [
      { id: "as_X_1", label: "as_X", source_range: null },
      { id: "sem_fillna_2", label: "sem_fillna", source_range: null },
    ];

    it("prefers backend skrubToCompileId over label match", () => {
      const ids = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {
        skrubToCompileId: { "0": "sem_fillna_2" },
      });
      expect(ids).toEqual(["sem_fillna_2"]);
    });

    it("handles multiple skrub nodes with backend mapping", () => {
      const ids1 = graphNodeToCompileIds("0", { id: "0", label: "as_X" }, compileNodes, {
        skrubToCompileId: { "0": "as_X_1", "1": "sem_fillna_2" },
      });
      const ids2 = graphNodeToCompileIds("1", { id: "1", label: "sem_fillna" }, compileNodes, {
        skrubToCompileId: { "0": "as_X_1", "1": "sem_fillna_2" },
      });
      expect(ids1).toEqual(["as_X_1"]);
      expect(ids2).toEqual(["sem_fillna_2"]);
    });
  });
});
