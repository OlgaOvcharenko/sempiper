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
  /** When true, skip debounce and compile immediately (e.g. after loading a script). Cleared by this hook. */
  scriptLoadInProgressRef?: React.MutableRefObject<boolean>;
}): UseCompileReturn {
  const { pipelineCode, llmName, temperature, loadedScriptId, scriptLoadInProgressRef } = opts;

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
    if (typeof performance !== "undefined" && performance.mark) {
      performance.mark("compile-request-start");
      try {
        performance.measure(
          "load-to-compile-request",
          "pipeline-script-load-code-set",
          "compile-request-start"
        );
      } catch {
        // Ignore if measure fails (e.g. start mark missing)
      }
    }
    try {
      const tempValue = parseFloat(temperature);
      const res = await compilePipeline(pipelineCode, {
        signal: controller.signal,
        scriptId: loadedScriptId,
        llmName,
        temperature: isNaN(tempValue) ? undefined : tempValue,
      });
      if (compileAbortRef.current !== controller) return;
      if (typeof performance !== "undefined" && performance.mark)
        performance.mark("compile-request-end");
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

  // Debounce: re-compile after dependency changes. Skip debounce when code was just set by script load.
  useEffect(() => {
    const skipDebounce = scriptLoadInProgressRef?.current === true;
    if (skipDebounce && scriptLoadInProgressRef) scriptLoadInProgressRef.current = false;
    const delayMs = skipDebounce ? 0 : 400;
    const t = setTimeout(refreshCompileGraph, delayMs);
    return () => clearTimeout(t);
  }, [refreshCompileGraph, scriptLoadInProgressRef]);

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
