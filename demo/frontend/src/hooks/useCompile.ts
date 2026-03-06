import { useState, useEffect, useRef, useCallback } from "react";
import { compilePipeline, type CompileNode, type CompileEdge } from "../api/client";

export interface UseCompileReturn {
  compileNodes: CompileNode[];
  compileEdges: CompileEdge[];
  compileError: string | null;
  /** Graph validation errors from the last successful compile (empty if none). */
  compileValidationErrors: string[];
  /** Compile timing breakdown (ms) when X-Compile-Timing: 1 was sent; null otherwise. */
  compileTimingsMs: Record<string, number> | null;
  /** Kept in sync with compileNodes; useful for avoiding stale closures in callbacks. */
  compileNodesRef: React.RefObject<CompileNode[]>;
  /** Manually trigger a re-compile (e.g. after changing LLM config). */
  refreshCompileGraph: () => Promise<void>;
}

/**
 * Manages the compile-time graph state.
 *
 * - Debounces compile requests (400 ms) whenever pipelineCode / llmName / temperature changes.
 * - Calls `onCodeChange` when pipelineCode changes so callers can reset execution state.
 */
export function useCompile(opts: {
  pipelineCode: string;
  llmName: string;
  temperature: string;
  loadedScriptId: string | null;
  /** Called when pipelineCode changes — use to reset execution live state. */
  onCodeChange?: () => void;
}): UseCompileReturn {
  const { pipelineCode, llmName, temperature, loadedScriptId } = opts;

  const [compileNodes, setCompileNodes] = useState<CompileNode[]>([]);
  const [compileEdges, setCompileEdges] = useState<CompileEdge[]>([]);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [compileValidationErrors, setCompileValidationErrors] = useState<string[]>([]);
  const [compileTimingsMs, setCompileTimingsMs] = useState<Record<string, number> | null>(null);

  const compileAbortRef = useRef<AbortController | null>(null);
  const compileNodesRef = useRef<CompileNode[]>([]);
  compileNodesRef.current = compileNodes;

  // Keep a ref to onCodeChange so the effect below always calls the latest version
  // without needing to re-run when the callback identity changes.
  const onCodeChangeRef = useRef(opts.onCodeChange);
  onCodeChangeRef.current = opts.onCodeChange;

  const refreshCompileGraph = useCallback(async () => {
    if (compileAbortRef.current) compileAbortRef.current.abort();
    const controller = new AbortController();
    compileAbortRef.current = controller;
    setCompileError(null);
    try {
      const tempValue = parseFloat(temperature);
      const res = await compilePipeline(pipelineCode, {
        signal: controller.signal,
        scriptId: loadedScriptId,
        llmName,
        temperature: isNaN(tempValue) ? undefined : tempValue,
      });
      if (compileAbortRef.current !== controller) return;
      setCompileNodes(res.nodes);
      setCompileEdges(res.edges ?? []);
      setCompileValidationErrors(res.validation_errors ?? []);
      setCompileTimingsMs(res.compile_timings_ms ?? null);
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      setCompileNodes([]);
      setCompileEdges([]);
      setCompileValidationErrors([]);
      setCompileTimingsMs(null);
      setCompileError(err instanceof Error ? err.message : String(err));
    } finally {
      if (compileAbortRef.current === controller) compileAbortRef.current = null;
    }
  }, [pipelineCode, llmName, temperature, loadedScriptId]);

  // When pipelineCode changes: clear compile error and notify caller (resets execution state).
  useEffect(() => {
    setCompileError(null);
    onCodeChangeRef.current?.();
  }, [pipelineCode]);

  // Debounce: re-compile 400 ms after any compile dependency changes.
  useEffect(() => {
    const t = setTimeout(refreshCompileGraph, 400);
    return () => clearTimeout(t);
  }, [refreshCompileGraph]);

  return {
    compileNodes,
    compileEdges,
    compileError,
    compileValidationErrors,
    compileTimingsMs,
    compileNodesRef,
    refreshCompileGraph,
  };
}
