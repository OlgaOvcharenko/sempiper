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

export async function listPipelineScripts(): Promise<ListScriptsResponse> {
  const res = await fetch(`${API_BASE}/scripts`);
  if (!res.ok) throw new Error(res.statusText || "Failed to list scripts");
  return res.json();
}

export async function getPipelineScriptContent(name: string): Promise<ScriptContentResponse> {
  const res = await fetch(`${API_BASE}/scripts/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(res.statusText || "Failed to load script");
  return res.json();
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
}

export interface CompileOptions {
  signal?: AbortSignal;
}

export async function compilePipeline(
  inputCode: string,
  options?: CompileOptions
): Promise<CompileResponse> {
  const res = await fetch(`${API_BASE}/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_code: inputCode }),
    signal: options?.signal,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
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
  return res.json();
}

/** Input node data summary (schema, sample, row count) from execute stream. */
export interface InputSummary {
  node_id: string;
  schema: Array<{ name: string; dtype: string }>;
  sample: Record<string, unknown>[];
  row_count: number;
}

/** SSE event from execute stream: terminal, node_code, input_summary, cost, or done. */
export type ExecuteEvent =
  | { type: "terminal"; line: string }
  | {
      type: "node_code";
      node_id: string;
      generated_code: string;
      retries?: number;
      cost_usd?: number;
    }
  | { type: "input_summary"; node_id: string; schema: InputSummary["schema"]; sample: InputSummary["sample"]; row_count: number }
  | { type: "cost"; total_usd: number }
  | { type: "done"; total_cost_usd?: number };

/**
 * Execute pipeline and stream events. Calls onEvent for each SSE event (terminal, node_code, done).
 * Returns an AbortController so the caller can abort the request.
 */
export function executePipelineStream(
  inputCode: string,
  onEvent: (event: ExecuteEvent) => void
): AbortController {
  const controller = new AbortController();
  const res = fetch(`${API_BASE}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_code: inputCode }),
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
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";
        for (const chunk of lines) {
          if (chunk.startsWith("data: ")) {
            try {
              const data = JSON.parse(chunk.slice(6)) as ExecuteEvent;
              onEvent(data);
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onEvent({ type: "terminal", line: `Error: ${err.message}` });
      onEvent({ type: "done" });
    });
  return controller;
}
