const API_BASE = "/api";

/** Pipeline script entry from GET /api/scripts. */
export interface PipelineScriptEntry {
  id: string;
  label: string;
}

/** Response from GET /api/scripts. */
export interface ListScriptsResponse {
  scripts: PipelineScriptEntry[];
}

/** Response from GET /api/scripts/{name}. */
export interface ScriptContentResponse {
  id: string;
  label: string;
  content: string;
}

export async function listPipelineScripts(
  mode: "normal" | "optimizer" = "normal"
): Promise<ListScriptsResponse> {
  const res = await fetch(`${API_BASE}/scripts?mode=${encodeURIComponent(mode)}`);
  if (!res.ok) throw new Error(res.statusText || "Failed to list scripts");
  try {
    return await res.json();
  } catch (e) {
    throw new Error("Invalid response from server (list scripts)");
  }
}

export async function getPipelineScriptContent(
  name: string,
  mode: "normal" | "optimizer" = "normal",
  options?: { signal?: AbortSignal }
): Promise<ScriptContentResponse> {
  const res = await fetch(
    `${API_BASE}/scripts/${encodeURIComponent(name)}?mode=${encodeURIComponent(mode)}`,
    { signal: options?.signal }
  );
  if (!res.ok) throw new Error(res.statusText || "Failed to load script");
  try {
    return await res.json();
  } catch (e) {
    throw new Error("Invalid response from server (script content)");
  }
}

/** Source range for editor decorations and code–graph mapping (1-based). */
export interface SourceRange {
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
}

export interface CompileNode {
  id: string;
  type: string;
  label: string;
  source_range: SourceRange | null;
}

export interface CompileEdge {
  source: string;
  target: string;
}

export interface CompileResponse {
  nodes: CompileNode[];
  edges?: CompileEdge[];
  validation_errors?: string[];
  /** Present when request included X-Compile-Timing: 1 and use_dynamic was true */
  compile_timings_ms?: Record<string, number>;
}

export interface CompileOptions {
  signal?: AbortSignal;
  /** Script id for SVG caching (simple, medium, full). */
  scriptId?: string | null;
  /** LLM model name for caching. */
  llmName?: string;
  /** LLM temperature for caching (0-2). */
  temperature?: number;
  /** Whether to use caching (default: true). */
  useCache?: boolean;
}

export async function compilePipeline(
  inputCode: string,
  options?: CompileOptions
): Promise<CompileResponse> {
  const body: {
    input_code: string;
    script_id?: string;
    llm_name?: string;
    temperature?: number;
    use_cache?: boolean;
  } = { input_code: inputCode };
  if (options?.scriptId) body.script_id = options.scriptId;
  if (options?.llmName !== undefined) body.llm_name = options.llmName;
  if (options?.temperature !== undefined) body.temperature = options.temperature;
  if (options?.useCache !== undefined) body.use_cache = options.useCache;
  const res = await fetch(`${API_BASE}/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: options?.signal,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  try {
    return await res.json();
  } catch (e) {
    throw new Error("Invalid response from server (compile)");
  }
}

export interface GenerateOptions {
  optimization_level?: number;
  target?: "cpp" | "rust" | "llvm";
}

export interface GenerateRequest {
  input_code: string;
  options?: GenerateOptions;
}

export interface StageTiming {
  name: string;
  time_ms: number;
}

export interface GenerateMetadata {
  optimizations_applied: string[];
  ir_size_bytes: number;
  stages: StageTiming[];
}

export interface GenerateResponse {
  generated_code: string;
  language: string;
  compilation_time_ms: number;
  metadata: GenerateMetadata;
}

export async function generateCode(req: GenerateRequest): Promise<GenerateResponse> {
  const res = await fetch(`${API_BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  try {
    return await res.json();
  } catch (e) {
    throw new Error("Invalid response from server (generate)");
  }
}

/** Input node data summary (schema, sample, row count) from execute stream. */
export interface InputSummary {
  node_id: string;
  schema: Array<{ name: string; dtype: string }>;
  sample: Record<string, unknown>[];
  row_count: number;
}

/** SSE event from execute stream: terminal, node_code, input_summary, node_data, cost, done, error, or skrub_graph. */
export type ExecuteEvent =
  | { type: "terminal"; line: string }
  | { type: "error"; message: string }
  | {
      type: "node_code";
      node_id: string;
      generated_code: string;
      retries?: number;
      cost_usd?: number;
      /** True when backend used placeholder (LLM unavailable or failed). */
      is_fallback?: boolean;
    }
  | { type: "input_summary"; node_id: string; schema: InputSummary["schema"]; sample: InputSummary["sample"]; row_count: number }
  | {
      /** Intermediate data for operator nodes (from .skb.preview()). */
      type: "node_data";
      node_id: string;
      schema: InputSummary["schema"];
      sample: InputSummary["sample"];
      row_count: number;
    }
  | { type: "cost"; total_usd: number }
  | { type: "done"; total_cost_usd?: number; duration_ms?: number }
  | { type: "skrub_graph"; graph?: SkrubGraphDict; svg?: string; skrubToCompileId?: Record<string, string> };

/** Skrub DAG from _Graph().run(dag): nodes, parents, children (interactive viz). */
export interface SkrubGraphDict {
  nodes: Array<{ id: string; label: string; is_sempipes_semantic?: boolean }>;
  parents: Record<string, string[]>;
  children: Record<string, string[]>;
  /** Sempipes semantic operator node ids in execution (topo) order; index matches captured code. */
  sempipesNodeIds?: string[];
}

/**
 * Convert compile graph (nodes + edges) to SkrubGraphDict for immediate preview.
 * Used when skrub graph is not yet available (before Run completes).
 * Final graph is always skrub graph; this is a best-effort preview.
 */
export function compileToSkrubGraph(
  nodes: CompileNode[],
  edges: CompileEdge[]
): SkrubGraphDict | null {
  const runnable = nodes.filter(
    (n) =>
      ["input", "operator", "pipeline"].includes(
        typeof n.type === "string" ? n.type.toLowerCase() : ""
      )
  );
  if (runnable.length === 0) return null;

  const nodeIds = new Set(runnable.map((n) => n.id));
  const validEdges = edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

  const parents: Record<string, string[]> = {};
  const children: Record<string, string[]> = {};
  for (const n of runnable) {
    parents[n.id] = [];
    children[n.id] = [];
  }
  for (const e of validEdges) {
    if (!parents[e.target].includes(e.source)) parents[e.target].push(e.source);
    if (!children[e.source].includes(e.target)) children[e.source].push(e.target);
  }

  // Only mark nodes as sempipes if their label starts with "sem_" (actual sempipes semantic operators)
  const isSempipesLabel = (label: string): boolean => {
    const low = (label ?? "").toLowerCase();
    return low.startsWith("sem_");
  };

  const sempipesNodeIds = runnable
    .filter((n) => (n.type ?? "").toLowerCase() === "operator" && isSempipesLabel(n.label))
    .map((n) => n.id);

  return {
    nodes: runnable.map((n) => ({
      id: n.id,
      label: n.label,
      is_sempipes_semantic: (n.type ?? "").toLowerCase() === "operator" && isSempipesLabel(n.label),
    })),
    parents,
    children,
    sempipesNodeIds,
  };
}

/** Request to update sempipes config (LLM name and temperature). */
export interface UpdateConfigRequest {
  llm_name: string;
  temperature: number;
}

/** Response from POST /api/update-config. */
export interface UpdateConfigResponse {
  status: string;
  llm_name: string;
  temperature: number;
}

export async function updateSempipesConfig(req: UpdateConfigRequest): Promise<UpdateConfigResponse> {
  const res = await fetch(`${API_BASE}/update-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  try {
    return await res.json();
  } catch (e) {
    throw new Error("Invalid response from server (update-config)");
  }
}

/** Options for executePipelineStream. */
export interface ExecuteOptions {
  /** Loaded script id (simple, medium, full); backend saves native skrub SVG to disk by this name. */
  scriptId?: string | null;
  /** LLM model name for caching. */
  llmName?: string;
  /** LLM temperature for caching (0-2). */
  temperature?: number;
  /** Whether to use caching (default: true). */
  useCache?: boolean;
}

/**
 * Execute pipeline and stream events. Calls onEvent for each SSE event (terminal, node_code, done).
 * Returns an AbortController so the caller can abort the request.
 * All onEvent calls are wrapped in try/catch so exceptions from the callback do not crash the app;
 * on exception we emit error + done and stop.
 */
export function executePipelineStream(
  inputCode: string,
  onEvent: (event: ExecuteEvent) => void,
  options?: ExecuteOptions
): AbortController {
  const controller = new AbortController();

  function safeOnEvent(event: ExecuteEvent): boolean {
    try {
      onEvent(event);
      return true;
    } catch (e) {
      try {
        onEvent({
          type: "error",
          message: e instanceof Error ? e.message : String(e),
        });
        onEvent({ type: "done" });
      } catch {
        // ignore if callback throws again
      }
      return false;
    }
  }

  const body: {
    input_code: string;
    script_id?: string;
    llm_name?: string;
    temperature?: number;
    use_cache?: boolean;
  } = { input_code: inputCode };
  if (options?.scriptId) body.script_id = options.scriptId;
  if (options?.llmName !== undefined) body.llm_name = options.llmName;
  if (options?.temperature !== undefined) body.temperature = options.temperature;
  if (options?.useCache !== undefined) body.use_cache = options.useCache;

  const res = fetch(`${API_BASE}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  });
  res
    .then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (value) buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = done ? "" : (lines.pop() ?? "");
        for (const chunk of lines) {
          if (chunk.startsWith("data: ")) {
            try {
              const data = JSON.parse(chunk.slice(6)) as ExecuteEvent;
              if (!safeOnEvent(data)) return;
            } catch {
              // ignore parse errors
            }
          }
        }
        if (done) break;
      }
      if (buffer.trim() && buffer.startsWith("data: ")) {
        try {
          const data = JSON.parse(buffer.slice(6)) as ExecuteEvent;
          safeOnEvent(data);
        } catch {
          // ignore
        }
      }
    })
    .catch((err) => {
      try {
        if (err.name !== "AbortError") {
          safeOnEvent({ type: "terminal", line: `Error: ${err.message}` });
        }
        safeOnEvent({ type: "done" });
      } catch {
        // prevent unhandled rejection
      }
    });
  return controller;
}

/**
 * Clear all cached data (compile, execute, svg).
 */
export async function clearCache(): Promise<void> {
  const resp = await fetch("/api/cache", {
    method: "DELETE",
  });
  if (!resp.ok) {
    throw new Error(`Failed to clear cache: ${resp.statusText}`);
  }
}
