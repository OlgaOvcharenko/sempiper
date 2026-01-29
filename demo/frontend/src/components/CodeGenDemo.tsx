import { useState, useCallback } from "react";
import { useCodeGen } from "../hooks/useCodeGen";
import { InputEditor } from "./InputEditor";
import { CodeOutput } from "./CodeOutput";
import { MetadataPanel } from "./MetadataPanel";

const defaultInput = "SELECT * FROM table WHERE id > 0;";

export function CodeGenDemo() {
  const [inputCode, setInputCode] = useState(defaultInput);
  const { mutateAsync: generate, isPending, data, error } = useCodeGen();

  const handleGenerate = useCallback(() => {
    generate({
      input_code: inputCode,
      options: { optimization_level: 2, target: "cpp" },
    });
  }, [inputCode, generate]);

  const handleCopy = useCallback(() => {
    if (!data?.generated_code) return;
    navigator.clipboard.writeText(data.generated_code);
  }, [data?.generated_code]);

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100 font-sans min-w-[1280px]">
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-800 shrink-0">
        <h1 className="text-lg font-medium text-slate-200">VLDB Code Gen Demo</h1>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isPending}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
        >
          {isPending ? "Generating…" : "Generate"}
        </button>
      </header>

      <div className="flex flex-1 min-h-0 px-6 py-4 gap-6">
        <div className="w-[40%] flex flex-col min-w-0 gap-2">
          <label className="text-sm text-slate-400">Input (DSL / SQL)</label>
          <div className="flex-1 min-h-[320px]">
            <InputEditor
              value={inputCode}
              onChange={setInputCode}
              disabled={isPending}
            />
          </div>
        </div>

        <div className="w-[60%] flex flex-col min-w-0 gap-2">
          <div className="flex items-center justify-between">
            <label className="text-sm text-slate-400">Generated code</label>
            {data?.generated_code && (
              <button
                type="button"
                onClick={handleCopy}
                className="text-xs px-2 py-1 rounded border border-slate-600 hover:border-slate-500 text-slate-400 hover:text-slate-300 transition-colors"
              >
                Copy
              </button>
            )}
          </div>
          <div className="flex-1 min-h-[320px]">
            <CodeOutput
              code={data?.generated_code ?? ""}
              language={data?.language ?? "cpp"}
              isLoading={isPending}
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="mx-6 mb-2 px-4 py-2 rounded-lg bg-red-900/30 border border-red-800 text-red-300 text-sm">
          {error.message}
        </div>
      )}

      <aside className="px-6 pb-6 shrink-0">
        <MetadataPanel
          compilationTimeMs={data?.compilation_time_ms ?? null}
          metadata={data?.metadata ?? null}
        />
      </aside>
    </div>
  );
}
