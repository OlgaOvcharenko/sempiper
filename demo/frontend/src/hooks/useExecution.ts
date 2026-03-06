import { useState, useRef, useCallback } from "react";
import {
  executePipelineStream,
  updateSempipesConfig,
  type InputSummary,
} from "../api/client";

export interface UseExecutionReturn {
  isExecuting: boolean;
  liveNodeCode: Record<string, string>;
  liveNodeRetries: Record<string, number>;
  liveFallbackByNode: Record<string, boolean>;
  liveNodeCostUsd: Record<string, number>;
  inputSummaryByNode: Record<string, InputSummary>;
  nodeDataByNode: Record<string, InputSummary>;
  lastRunCostUsd: number | null;
  lastRunDurationMs: number | null;
  lastRunError: string | null;
  skrubToCompileId: Record<string, string>;
  /**
   * Starts execution, or aborts it if already running.
   * Both the Play and Stop buttons can call this — the hook toggles based on isExecuting.
   */
  handlePlay: () => Promise<void>;
  /**
   * Clears all live execution state (node code, summaries, costs, etc.).
   * Pass this as `onCodeChange` to useCompile so live data is flushed when code changes.
   */
  resetLiveState: () => void;
}

/**
 * Manages the full execution lifecycle: SSE streaming, per-node live state,
 * and the skrub→compile ID re-keying that bridges runtime IDs to compile graph IDs.
 */
export function useExecution(opts: {
  pipelineCode: string;
  llmName: string;
  temperature: string;
  loadedScriptId: string | null;
  /** Pure temperature validation function (from useLlmConfig). */
  validateTemperature: (value: string) => boolean;
  /**
   * Called when temperature is invalid at execution start — use to show error
   * highlight + shake animation on the temperature input.
   */
  onTemperatureInvalid?: () => void;
  /**
   * Called before the SSE stream starts. Return true to indicate that execution
   * has been handled (no SSE will start), false to proceed normally.
   *
   * Use case: OptimizerDemo's "simulated script" path that replays stored
   * trajectories instead of running the pipeline.
   */
  onBeforeExecute?: () => boolean;
  /** Send useCache: true to the execute endpoint (e.g. for OptimizerDemo). */
  useCache?: boolean;
  /**
   * If loadedScriptId equals this value, no scriptId is sent to the execute
   * endpoint (i.e. the script is treated as anonymous/new).
   * Use case: OptimizerDemo's "new" synthetic pipeline entry.
   */
  newPipelineId?: string;
}): UseExecutionReturn {
  const {
    pipelineCode,
    llmName,
    temperature,
    loadedScriptId,
    validateTemperature,
    useCache,
    newPipelineId,
  } = opts;

  const [isExecuting, setIsExecuting] = useState(false);
  const [liveNodeCode, setLiveNodeCode] = useState<Record<string, string>>({});
  const [liveNodeRetries, setLiveNodeRetries] = useState<Record<string, number>>({});
  const [liveFallbackByNode, setLiveFallbackByNode] = useState<Record<string, boolean>>({});
  const [liveNodeCostUsd, setLiveNodeCostUsd] = useState<Record<string, number>>({});
  const [inputSummaryByNode, setInputSummaryByNode] = useState<Record<string, InputSummary>>({});
  const [nodeDataByNode, setNodeDataByNode] = useState<Record<string, InputSummary>>({});
  const [lastRunCostUsd, setLastRunCostUsd] = useState<number | null>(null);
  const [lastRunDurationMs, setLastRunDurationMs] = useState<number | null>(null);
  const [lastRunError, setLastRunError] = useState<string | null>(null);
  const [skrubToCompileId, setSkrubToCompileId] = useState<Record<string, string>>({});

  const executeAbortRef = useRef<AbortController | null>(null);
  const skrubToCompileIdRef = useRef<Record<string, string>>({});

  // Keep callback refs so handlePlay doesn't need to be recreated when callbacks change.
  const onTemperatureInvalidRef = useRef(opts.onTemperatureInvalid);
  onTemperatureInvalidRef.current = opts.onTemperatureInvalid;
  const onBeforeExecuteRef = useRef(opts.onBeforeExecute);
  onBeforeExecuteRef.current = opts.onBeforeExecute;

  const resetLiveState = useCallback(() => {
    setLiveNodeCode({});
    setLiveNodeRetries({});
    setLiveNodeCostUsd({});
    setInputSummaryByNode({});
    setNodeDataByNode({});
    setLastRunCostUsd(null);
    setLastRunDurationMs(null);
    setSkrubToCompileId({});
    skrubToCompileIdRef.current = {};
  }, []);

  const handlePlay = useCallback(async () => {
    // If already executing, abort and return (Stop button uses the same handler).
    if (isExecuting && executeAbortRef.current) {
      executeAbortRef.current.abort();
      return;
    }

    // Validate temperature before starting.
    if (!validateTemperature(temperature)) {
      onTemperatureInvalidRef.current?.();
      setLastRunError("Invalid temperature. Please enter a value between 0 and 2.");
      return;
    }

    // Clear all live state from any previous run.
    setLiveNodeCode({});
    setLiveNodeRetries({});
    setLiveFallbackByNode({});
    setLiveNodeCostUsd({});
    setInputSummaryByNode({});
    setNodeDataByNode({});
    setLastRunCostUsd(null);
    setSkrubToCompileId({});
    skrubToCompileIdRef.current = {};
    setLastRunDurationMs(null);
    setLastRunError(null);

    // Extension point: caller can intercept before SSE starts (e.g. simulation replay).
    if (onBeforeExecuteRef.current?.()) return;

    setIsExecuting(true);

    // Push LLM config to backend before execution.
    try {
      const tempValue = parseFloat(temperature);
      if (!isNaN(tempValue)) {
        await updateSempipesConfig({ llm_name: llmName, temperature: tempValue });
      }
    } catch (e) {
      setLastRunError(`Config update failed: ${e instanceof Error ? e.message : String(e)}`);
      setIsExecuting(false);
      return;
    }

    // Determine the scriptId to send. If loadedScriptId equals the synthetic "new" entry,
    // don't send any scriptId (the pipeline is anonymous).
    const effectiveScriptId =
      newPipelineId && loadedScriptId === newPipelineId ? undefined : loadedScriptId ?? undefined;

    // Helper: re-key a live-state map from skrub runtime IDs to compile IDs.
    // Called once per map when the skrub_graph event arrives with skrubToCompileId.
    const rekey = <T>(
      prev: Record<string, T>,
      mapping: Record<string, string>
    ): Record<string, T> => {
      const updated = { ...prev };
      for (const [skrubId, compileId] of Object.entries(mapping)) {
        const value = prev[skrubId] ?? prev[`skrub_${skrubId}`];
        if (value !== undefined) {
          updated[compileId] = value;
          updated[`skrub_${compileId}`] = value;
        }
      }
      return updated;
    };

    const controller = executePipelineStream(
      pipelineCode,
      (event) => {
        try {
          if (event.type === "input_summary") {
            const summary = {
              node_id: event.node_id,
              schema: event.schema,
              sample: event.sample,
              row_count: event.row_count,
            };
            setInputSummaryByNode((prev) => ({ ...prev, [event.node_id]: summary }));
            // Also store in nodeDataByNode so "Output data (preview)" shows it without fallback
            setNodeDataByNode((prev) => ({ ...prev, [event.node_id]: summary }));
          } else if (event.type === "node_data") {
            const data = {
              node_id: event.node_id,
              schema: event.schema,
              sample: event.sample,
              row_count: event.row_count,
            };
            setNodeDataByNode((prev) => {
              const next = { ...prev, [event.node_id]: data };
              // If this is a skrub_ ID and we have a mapping, also set under compile ID so
              // the panel finds it when the graph uses compile IDs (avoids depending on rekey timing)
              const mapping = skrubToCompileIdRef.current;
              if (mapping && event.node_id.startsWith("skrub_")) {
                const skid = event.node_id.slice(6);
                const compileId = mapping[skid];
                if (compileId) next[compileId] = data;
              }
              return next;
            });
          } else if (event.type === "node_code") {
            const nodeId = event.node_id;
            // Store under both the raw ID and the skrub-prefixed ID so NodeDetailsPanel
            // can find the code regardless of which ID format it looks up.
            const skrubId = nodeId.startsWith("skrub_") ? nodeId : `skrub_${nodeId}`;
            setLiveNodeCode((prev) => ({
              ...prev,
              [nodeId]: event.generated_code,
              [skrubId]: event.generated_code,
            }));
            if (event.retries != null) {
              const retries = event.retries;
              setLiveNodeRetries((prev) => ({
                ...prev,
                [nodeId]: retries,
                [skrubId]: retries,
              }));
            }
            if (event.is_fallback != null) {
              const isFallback = event.is_fallback;
              setLiveFallbackByNode((prev) => ({
                ...prev,
                [nodeId]: isFallback,
                [skrubId]: isFallback,
              }));
            }
            if (event.cost_usd != null) {
              const cost = event.cost_usd;
              setLiveNodeCostUsd((prev) => ({
                ...prev,
                [nodeId]: cost,
                [skrubId]: cost,
              }));
            }
          } else if (event.type === "error") {
            setLastRunError(event.message);
          } else if (event.type === "cost") {
            setLastRunCostUsd(event.total_usd);
          } else if (event.type === "skrub_graph") {
            // Keep the skrub→compile ID mapping for node-selection fallback,
            // but do NOT replace the display graph — the compile graph is canonical.
            if (event.skrubToCompileId) {
              const mapping = event.skrubToCompileId as Record<string, string>;
              skrubToCompileIdRef.current = mapping;
              setSkrubToCompileId(mapping);
              // Re-key all live maps so NodeDetailsPanel can find data via compile IDs
              // (the compile graph uses compile IDs, but node_code events used runtime IDs).
              setLiveNodeCode((prev) => rekey(prev, mapping));
              setLiveNodeRetries((prev) => rekey(prev, mapping));
              setLiveFallbackByNode((prev) => rekey(prev, mapping));
              setLiveNodeCostUsd((prev) => rekey(prev, mapping));
              setNodeDataByNode((prev) => rekey(prev, mapping));
              setInputSummaryByNode((prev) => rekey(prev, mapping));
            }
          } else if (event.type === "done") {
            if (event.total_cost_usd != null) setLastRunCostUsd(event.total_cost_usd);
            if (event.duration_ms != null) setLastRunDurationMs(event.duration_ms);
            setIsExecuting(false);
            executeAbortRef.current = null;
            // Rekey again so node_data that arrived after skrub_graph get copied to compile IDs (e.g. cache replay)
            const mapping = skrubToCompileIdRef.current;
            if (mapping && Object.keys(mapping).length > 0) {
              setNodeDataByNode((prev) => rekey(prev, mapping));
              setInputSummaryByNode((prev) => rekey(prev, mapping));
            }
          }
        } catch (e) {
          setLastRunError(e instanceof Error ? e.message : String(e));
          setIsExecuting(false);
          executeAbortRef.current = null;
        }
      },
      {
        scriptId: effectiveScriptId,
        llmName,
        temperature: parseFloat(temperature),
        useCache,
      }
    );

    executeAbortRef.current = controller;
  }, [pipelineCode, isExecuting, llmName, temperature, loadedScriptId, validateTemperature, newPipelineId, useCache]);

  return {
    isExecuting,
    liveNodeCode,
    liveNodeRetries,
    liveFallbackByNode,
    liveNodeCostUsd,
    inputSummaryByNode,
    nodeDataByNode,
    lastRunCostUsd,
    lastRunDurationMs,
    lastRunError,
    skrubToCompileId,
    handlePlay,
    resetLiveState,
  };
}
