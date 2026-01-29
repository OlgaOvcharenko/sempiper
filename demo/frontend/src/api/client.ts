const API_BASE = "/api";

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

export async function compilePipeline(inputCode: string): Promise<CompileResponse> {
  const res = await fetch(`${API_BASE}/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_code: inputCode }),
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

/** SSE event from execute stream: terminal line or node_code update. */
export type ExecuteEvent =
  | { type: "terminal"; line: string }
  | { type: "node_code"; node_id: string; generated_code: string }
  | { type: "done" };

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
