import { useRef } from "react";
import { InputEditor } from "./InputEditor";
import type { PipelineScriptEntry, CompileNode, ExecuteProfile } from "../api/client";

interface PipelineEditorPanelProps {
    width?: string;
    isExpanded?: boolean;
    onToggleExpand?: () => void;
    isDark?: boolean;
    pipelineScripts: PipelineScriptEntry[];
    loadedScriptId: string | null;
    onLoadScript: (id: string) => void;
    onPipelineCodeChange: (code: string) => void;
    isExecuting: boolean;
    isPlayDisabled?: boolean;
    isReadOnly?: boolean;
    onPlay: () => void;
    onClearCache: () => void;
    llmName: string;
    onLlmNameChange: (name: string) => void;
    temperature: string;
    onTemperatureChange: (val: string) => void;
    temperatureError?: boolean;
    temperatureShake?: boolean;
    pipelineCode: string;
    compileNodes: CompileNode[];
    highlightedNodeIds: string[];
    onHighlightNodes: (ids: string[]) => void;
    selectedNodeId: string | null;
    onSelectNode: (id: string | null) => void;
    cursorFocusNodeId: string | null;
    onFocusApplied: () => void;
    sempipesNodeIds: string[];
    activeOperatorName?: string;
    lastRunDurationMs?: number | null;
    lastRunCostUsd?: number | null;
    lastRunProfile?: ExecuteProfile | null;
    showNewOption?: boolean;
    className?: string;
    /** When provided, replaces the Model + Temperature inputs with custom content. */
    llmSelectorContent?: React.ReactNode;
    /** When provided (only after Run in optimizer mode), shows a summary below the code editor. */
    optimizerSummary?: { scoring?: string; bestScore?: number; trials: number; operator?: string } | null;
}

const AVAILABLE_LLMS = [
    "gpt-5-mini",
    "gpt-4.1-mini",
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.5-flash-lite",
    "gemini/gemini-2.5-pro",
    "gemini/gemini-3-flash-preview",
    "gemini/gemini-3-flash-lite-preview",
    "gemini/gemini-3-pro-preview",
];

export function PipelineEditorPanel({
    isExpanded = false,
    onToggleExpand,
    isDark = false,
    pipelineScripts,
    loadedScriptId,
    onLoadScript,
    onPipelineCodeChange,
    isExecuting,
    isPlayDisabled,
    isReadOnly = false,
    onPlay,
    onClearCache,
    llmName,
    onLlmNameChange,
    temperature,
    onTemperatureChange,
    temperatureError,
    temperatureShake,
    pipelineCode,
    compileNodes,
    highlightedNodeIds,
    onHighlightNodes,
    selectedNodeId,
    onSelectNode,
    cursorFocusNodeId,
    onFocusApplied,
    sempipesNodeIds,
    activeOperatorName,
    lastRunDurationMs,
    lastRunCostUsd,
    lastRunProfile,
    className = "",
    llmSelectorContent,
    optimizerSummary,
}: PipelineEditorPanelProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (event) => {
            const content = event.target?.result as string;
            onPipelineCodeChange(content);
        };
        reader.readAsText(file);
    };

    return (
        <div className={`flex flex-col min-h-0 rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md transition-all duration-300 ${className}`}>
            <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex flex-col justify-center gap-1">
                {/* Primary row: Script + Play */}
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <span className="text-xs text-zinc-500 dark:text-zinc-400">Pipeline:</span>
                        <select
                            value={loadedScriptId ?? ""}
                            onChange={(e) => onLoadScript(e.target.value)}
                            disabled={isExecuting}
                            className="text-xs px-2 py-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-700 dark:text-zinc-200 min-w-[140px]"
                        >
                            {pipelineScripts.map(({ id, label }) => (
                                <option key={id} value={id}>{label}</option>
                            ))}
                        </select>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".py,.txt"
                            onChange={handleFileUpload}
                            className="hidden"
                        />
                        <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={isExecuting}
                            className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-500 dark:text-zinc-400"
                            title="Upload script"
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                        </button>
                        <button
                            type="button"
                            onClick={onPlay}
                            disabled={isExecuting || isPlayDisabled}
                            className={`p-1.5 rounded border transition-colors ${isPlayDisabled
                                ? "border-slate-300 bg-slate-100 text-slate-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-500 cursor-not-allowed"
                                : "border-emerald-600 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white"
                                }`}
                            title={isPlayDisabled ? "This benchmark script cannot be executed directly; trajectory is pre-computed." : "Run pipeline"}
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <polygon points="5,3 19,12 5,21" />
                            </svg>
                        </button>
                        <button
                            type="button"
                            onClick={onPlay}
                            disabled={!isExecuting}
                            className={`p-1.5 rounded border transition-colors ${isExecuting
                                ? "border-red-600 bg-red-600 hover:bg-red-500 text-white"
                                : "border-slate-300 dark:border-zinc-600 bg-slate-100 dark:bg-zinc-800 text-slate-300 dark:text-zinc-600 cursor-not-allowed"
                                }`}
                            title="Stop"
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <rect x="6" y="6" width="12" height="12" />
                            </svg>
                        </button>
                        <button
                            type="button"
                            onClick={onClearCache}
                            disabled={isExecuting}
                            className="p-1.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 disabled:opacity-50 text-zinc-600 dark:text-zinc-400"
                            title="Clear cache"
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                        </button>
                    </div>
                    {onToggleExpand && (
                        <button
                            type="button"
                            onClick={onToggleExpand}
                            className="shrink-0 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-400 text-2xl"
                            title={isExpanded ? "Collapse" : "Expand"}
                        >
                            {isExpanded ? "⤡" : "⤢"}
                        </button>
                    )}
                </div>

                {/* Secondary row: Settings */}
                <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400 overflow-x-auto no-scrollbar">
                    {llmSelectorContent ?? (
                        <>
                            <div className="flex items-center gap-1.5 shrink-0">
                                <span>Model:</span>
                                <select
                                    value={llmName}
                                    onChange={(e) => onLlmNameChange(e.target.value)}
                                    disabled={isExecuting}
                                    className="text-xs px-1.5 py-0.5 rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
                                >
                                    {AVAILABLE_LLMS.map((n) => <option key={n} value={n}>{n}</option>)}
                                </select>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                                <span>Temperature:</span>
                                <input
                                    type="text"
                                    value={temperature}
                                    onChange={(e) => onTemperatureChange(e.target.value)}
                                    disabled={isExecuting}
                                    className={`text-xs px-1.5 py-0.5 rounded border w-12 transition-all ${temperatureError ? "border-red-500 bg-red-50 dark:bg-red-900/20 text-red-600" : "border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300"} ${temperatureShake ? "animate-shake" : ""}`}
                                />
                            </div>
                        </>
                    )}
                    {lastRunDurationMs != null && (
                        <span className="shrink-0 opacity-60">· {Math.round(lastRunDurationMs / 1000)}s</span>
                    )}
                    {lastRunCostUsd != null && (
                        <span className="shrink-0 text-emerald-600 dark:text-emerald-400 font-medium">· ${lastRunCostUsd.toFixed(4)}</span>
                    )}
                </div>

                {lastRunProfile && Object.keys(lastRunProfile).length > 0 && (
                    <div className="mt-1.5 overflow-x-auto">
                        <table className="text-[10px] text-zinc-600 dark:text-zinc-400 w-full border-collapse">
                            <thead>
                                <tr className="border-b border-slate-200 dark:border-zinc-600">
                                    <th className="text-left py-0.5 pr-2 font-medium">Phase</th>
                                    <th className="text-right py-0.5 font-medium">Time (ms)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {lastRunProfile.prepare_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Backend: prepare (cache + compile)</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.prepare_ms}</td>
                                    </tr>
                                )}
                                {lastRunProfile.runner_startup_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Runner: startup (imports)</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.runner_startup_ms}</td>
                                    </tr>
                                )}
                                {lastRunProfile.runner_exec_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Runner: pipeline execution (data + LLM + fit)</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.runner_exec_ms}</td>
                                    </tr>
                                )}
                                {lastRunProfile.runner_post_exec_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Runner: post-exec (graph, summaries)</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.runner_post_exec_ms}</td>
                                    </tr>
                                )}
                                {lastRunProfile.subprocess_wall_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Backend: subprocess wall</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.subprocess_wall_ms}</td>
                                    </tr>
                                )}
                                {lastRunProfile.emit_ms != null && (
                                    <tr className="border-b border-slate-100 dark:border-zinc-700/50">
                                        <td className="py-0.5 pr-2">Backend: emit events</td>
                                        <td className="text-right tabular-nums">{lastRunProfile.emit_ms}</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            <div className="flex-1 min-h-0">
                <InputEditor
                    value={pipelineCode}
                    onChange={onPipelineCodeChange}
                    disabled={isExecuting || isReadOnly}
                    isExpanded={isExpanded}
                    nodeRanges={compileNodes.map(n => ({ id: n.id, source_range: n.source_range! })).filter(n => n.source_range)}
                    onHighlightNodes={onHighlightNodes}
                    onSelectNode={onSelectNode}
                    selectedNodeId={selectedNodeId}
                    highlightedNodeIds={highlightedNodeIds}
                    focusNodeId={cursorFocusNodeId}
                    onFocusApplied={onFocusApplied}
                    sempipesNodeIds={sempipesNodeIds}
                    isDark={isDark}
                    activeOperatorName={activeOperatorName}
                />
            </div>
            {optimizerSummary && (
                <div className="shrink-0 border-t border-slate-200 dark:border-zinc-700 px-3 py-2 bg-slate-50 dark:bg-zinc-800/60 text-xs text-zinc-500 dark:text-zinc-400 space-y-1">
                    <p className="font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wider text-[10px]">Optimization results</p>
                    <div className="flex flex-wrap gap-x-4 gap-y-0.5">
                        {optimizerSummary.operator && <span>operator: <span className="text-zinc-700 dark:text-zinc-200 font-medium">{optimizerSummary.operator}</span></span>}
                        {optimizerSummary.scoring && <span>scoring: <span className="text-zinc-700 dark:text-zinc-200 font-medium">{optimizerSummary.scoring}</span></span>}
                        {optimizerSummary.bestScore != null && <span>best: <span className="text-emerald-600 dark:text-emerald-400 font-medium">{optimizerSummary.bestScore.toFixed(3)}</span></span>}
                        <span>trials: <span className="text-zinc-700 dark:text-zinc-200 font-medium">{optimizerSummary.trials}</span></span>
                    </div>
                </div>
            )}
        </div>
    );
}
