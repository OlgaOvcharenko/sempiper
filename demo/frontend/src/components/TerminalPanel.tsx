/**
 * Terminal / console panel: shows live stdout/stderr during pipeline execution.
 */
import { useEffect, useRef } from "react";

interface TerminalPanelProps {
  lines: string[];
  isRunning?: boolean;
  className?: string;
}

export function TerminalPanel({ lines, isRunning = false, className = "" }: TerminalPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines.length]);

  return (
    <div
      className={`flex flex-col rounded-lg border border-slate-200 bg-zinc-900 overflow-hidden font-mono text-sm ${className}`}
    >
      <div className="shrink-0 px-3 py-2 border-b border-zinc-700 bg-zinc-800 flex items-center gap-2">
        <span className="text-zinc-400">Terminal</span>
        {isRunning && (
          <span className="inline-flex items-center gap-1.5 text-amber-400 text-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            Running…
          </span>
        )}
      </div>
      <div className="flex-1 min-h-[120px] max-h-[200px] overflow-auto p-3 text-zinc-300 whitespace-pre-wrap break-words">
        {lines.length === 0 && !isRunning && (
          <span className="text-zinc-500">Output will appear here when you run the pipeline.</span>
        )}
        {lines.map((line, i) => (
          <div key={i} className="leading-relaxed">
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
