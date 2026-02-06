/**
 * Graph–code sync utilities.
 *
 * Maps between graph node IDs (skrub_X) and compile node IDs for bidirectional
 * highlighting: code cursor ↔ graph node, graph node click → code highlight.
 */

export interface CompileNodeLike {
  id: string;
  label?: string;
  source_range?: { start_line: number; start_column: number; end_line: number; end_column: number } | null;
}

export interface GraphNodeLike {
  id: string;
  label?: string;
}

const SKRUB_PREFIX = "skrub_";

/** Strip skrub_ prefix from node id. */
export function skrubIdToRaw(skrubNodeId: string): string {
  return skrubNodeId.startsWith(SKRUB_PREFIX) ? skrubNodeId.slice(SKRUB_PREFIX.length) : skrubNodeId;
}

/** Add skrub_ prefix for display IDs. */
export function toSkrubId(rawId: string): string {
  return `${SKRUB_PREFIX}${rawId}`;
}

/**
 * Find compile node IDs that correspond to a graph node.
 * Uses, in order: backend mapping → label match → runnable index.
 */
export function graphNodeToCompileIds(
  graphNodeId: string,
  graphNode: GraphNodeLike,
  compileNodes: CompileNodeLike[],
  options: {
    skrubToCompileId?: Record<string, string>;
    runnableNodeIds?: string[];
  }
): string[] {
  const { skrubToCompileId = {}, runnableNodeIds = [] } = options;

  // 1. Backend mapping (most reliable, from execute stream)
  const mappedId = skrubToCompileId[graphNodeId];
  if (mappedId) {
    const match = compileNodes.find((n) => n.id === mappedId);
    return match ? [mappedId] : [];
  }

  // 2. Direct id match (preview mode: graph ids = compile ids)
  const byId = compileNodes.filter((n) => n.id === graphNodeId);
  if (byId.length > 0) return byId.map((n) => n.id);

  // 3. Label match
  const label = graphNode.label ?? "";
  const byLabel = compileNodes.filter((n) => (n.label ?? "") === label);
  if (byLabel.length > 0) return byLabel.map((n) => n.id);

  // 4. Runnable index (post-run: skrub uses "0","1","2")
  const idx = parseInt(graphNodeId, 10);
  if (!isNaN(idx) && idx >= 0 && idx < runnableNodeIds.length) {
    const cid = runnableNodeIds[idx];
    const match = compileNodes.find((n) => n.id === cid);
    return match ? [cid] : [];
  }

  return [];
}

/**
 * Map compile node IDs to skrub display IDs for graph highlighting.
 * Preview: graph ids = compile ids → skrub_${id}.
 * Post-run: match by label.
 */
export function compileIdsToSkrubIds(
  compileIds: string[],
  displayGraphNodes: GraphNodeLike[],
  compileNodes: CompileNodeLike[],
  isPostRun: boolean
): string[] {
  if (compileIds.length === 0 || !displayGraphNodes.length) return [];

  if (isPostRun) {
    const result: string[] = [];
    for (const cid of compileIds) {
      const compileNode = compileNodes.find((n) => n.id === cid);
      if (!compileNode) continue;
      for (const sn of displayGraphNodes) {
        if ((sn.label ?? "") === (compileNode.label ?? "")) result.push(toSkrubId(sn.id));
      }
    }
    return [...new Set(result)];
  }

  // Preview: graph node ids = compile ids
  return compileIds
    .filter((id) => displayGraphNodes.some((n) => n.id === id))
    .map((id) => toSkrubId(id));
}
