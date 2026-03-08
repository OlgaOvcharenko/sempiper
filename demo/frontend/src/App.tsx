import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CodeGenDemo } from "./components/CodeGenDemo";
import { OptimizerDemo } from "./components/OptimizerDemo";
import { useState, useEffect } from "react";
import { useTheme } from "./hooks/useTheme";

const queryClient = new QueryClient();

export default function App() {
  const [activeTab, setActiveTab] = useState<'codegen' | 'optimizer'>('codegen');
  const [layoutMode, setLayoutMode] = useState<'toggled' | 'left-split'>('toggled');
  const { isDark, toggle: toggleTheme } = useTheme();

  // Sync tab favicon with app theme so the tab icon matches light/dark
  useEffect(() => {
    const href16 = `${isDark ? "/favicon-16-dark.png" : "/favicon-16.png"}?v=${isDark ? "d" : "l"}`;
    const href32 = `${isDark ? "/favicon-32-dark.png" : "/favicon-32.png"}?v=${isDark ? "d" : "l"}`;
    document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]').forEach((link) => {
      const sizes = link.getAttribute("sizes") ?? "";
      if (sizes.includes("16")) link.href = href16;
      else if (sizes.includes("32")) link.href = href32;
    });
  }, [isDark]);

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col h-screen bg-slate-200 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 font-sans min-w-[1280px]">
        {/* Unified Header */}
        <header className="shrink-0 h-14 px-6 border-b border-slate-300 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm transition-colors duration-300 flex items-center justify-between relative">

          {/* LEFT Section: Mode & Theme Toggles */}
          <div className="flex items-center gap-4 z-10 w-[320px]">
            <div className="flex p-0.5 bg-slate-100 dark:bg-zinc-800 rounded-lg border border-slate-200 dark:border-zinc-700">
              <button
                onClick={() => setActiveTab('codegen')}
                className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${activeTab === 'codegen'
                  ? 'bg-white dark:bg-zinc-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                  : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
                  }`}
              >
                Normal
              </button>
              <button
                onClick={() => setActiveTab('optimizer')}
                className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${activeTab === 'optimizer'
                  ? 'bg-white dark:bg-zinc-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                  : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
                  }`}
              >
                Optimizer
              </button>
            </div>

            <button
              onClick={toggleTheme}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 hover:bg-slate-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            >
              {isDark ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-500">
                  <circle cx="12" cy="12" r="5" />
                  <line x1="12" y1="1" x2="12" y2="3" />
                  <line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" />
                  <line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-600">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              )}
            </button>
          </div>

          <div className="absolute inset-x-0 inset-y-0 flex items-center justify-center pointer-events-none">
            <h1 className="text-2xl font-bold tracking-tight pointer-events-auto flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              <img
                key={isDark ? "dark" : "light"}
                src={`${isDark ? "/logo-dark.png" : "/logo-light.png"}?v=${isDark ? "d" : "l"}`}
                alt=""
                className="h-10 w-10 shrink-0 object-contain"
                aria-hidden
              />
              <span className="inline-flex items-baseline">
                <span className="text-rose-400">Sem</span>
                <span className="text-slate-500 dark:text-slate-400">Pipes</span>
              </span>
            </h1>
          </div>

          {/* RIGHT Section: Layout buttons (Optimizer only) */}
          <div className="flex items-center justify-end gap-3 z-10 w-[320px]">
            {activeTab === 'optimizer' && (
              <div className="flex p-0.5 bg-slate-100 dark:bg-zinc-800 rounded-lg border border-slate-200 dark:border-zinc-700">
                {[
                  { id: 'toggled', label: 'D' },
                  { id: 'left-split', label: 'L' },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    onClick={() => setLayoutMode(mode.id as 'toggled' | 'left-split')}
                    className={`w-8 h-7 flex items-center justify-center text-[10px] font-bold rounded transition-all ${layoutMode === mode.id
                      ? 'bg-white dark:bg-zinc-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                      : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
                      }`}
                    title={mode.label}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </header>

        <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
          {activeTab === 'codegen' ? (
            <CodeGenDemo isDark={isDark} />
          ) : (
            <OptimizerDemo
              layoutMode={layoutMode}
              setLayoutMode={setLayoutMode}
              isDark={isDark}
            />
          )}
        </main>
      </div>
    </QueryClientProvider>
  );
}
