import { useMemo, useEffect, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { codeToHtml } from "shiki";
import { useRef } from "react";

interface CodeOutputProps {
  code: string;
  language: string;
  isLoading?: boolean;
}

const LINE_HEIGHT = 20;
const ESTIMATE_LINES = 100;

export function CodeOutput({ code, language, isLoading }: CodeOutputProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [html, setHtml] = useState<string>("");
  const [lineCount, setLineCount] = useState(0);

  const lang = useMemo(() => {
    const l = language.toLowerCase();
    if (l === "cpp" || l === "c++") return "cpp";
    if (l === "llvm") return "llvm";
    return l || "cpp";
  }, [language]);

  useEffect(() => {
    let cancelled = false;
    if (!code) {
      setHtml("");
      setLineCount(0);
      return;
    }
      codeToHtml(code, {
      lang,
      theme: "github-light",
    })
      .then((out) => {
        if (!cancelled) {
          setHtml(out);
          setLineCount((code.match(/\n/g) ?? []).length + 1);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHtml(`<pre class="p-4 text-slate-700 font-mono text-sm">${escapeHtml(code)}</pre>`);
          setLineCount((code.match(/\n/g) ?? []).length + 1);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang]);

  const virtualizer = useVirtualizer({
    count: Math.max(lineCount, ESTIMATE_LINES),
    getScrollElement: () => parentRef.current,
    estimateSize: () => LINE_HEIGHT,
    overscan: 20,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const useVirtual = lineCount > 500;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full w-full rounded-lg border border-slate-200 bg-slate-50">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-600 text-sm">Generating...</span>
        </div>
      </div>
    );
  }

  if (!code) {
    return (
      <div className="h-full w-full rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-center">
        <span className="text-slate-500 text-sm">Generated code will appear here</span>
      </div>
    );
  }

  if (!useVirtual) {
    return (
      <div className="h-full w-full rounded-lg border border-slate-200 bg-white overflow-auto">
        <div
          className="p-4 text-sm font-mono min-h-full [&_pre]:!bg-transparent [&_pre]:!p-0 [&_pre]:!m-0 [&_.line]:leading-5"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    );
  }

  const totalHeight = virtualizer.getTotalSize();
  return (
    <div
      ref={parentRef}
      className="h-full w-full rounded-lg border border-slate-200 bg-white overflow-auto"
    >
      <div
        style={{ height: totalHeight, position: "relative" }}
        className="w-full"
      >
        {virtualItems.map((item) => (
          <div
            key={item.key}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: `${item.size}px`,
              transform: `translateY(${item.start}px)`,
            }}
            className="flex items-center px-4 text-slate-700 font-mono text-sm"
          >
            {code.split("\n")[item.index]}
          </div>
        ))}
      </div>
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
