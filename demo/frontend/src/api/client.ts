const API_BASE = "/api";

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

export async function generateCode(
  req: GenerateRequest
): Promise<GenerateResponse> {
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
