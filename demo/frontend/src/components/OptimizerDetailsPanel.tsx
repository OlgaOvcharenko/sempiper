import { useState, useRef } from "react";
import { CodeOutput } from "./CodeOutput";
import type { OptimizerOutcome } from "../api/client";

interface OptimizerDetailsPanelProps {
    selectedTrial: OptimizerOutcome | null;
    expandButton?: React.ReactNode;
    isExpanded?: boolean;
    operatorName?: string;
    activeOperatorName?: string;
    onOperatorClick?: (name: string) => void;
    isDark?: boolean;
    finalCode?: Record<string, string> | null;
    optimizedOperatorName?: string;
    hasRun?: boolean;
    isBestTrial?: boolean;
}

type OperatorKind = "optimized" | "pipeline";

function AccordionItem({
    title,
    children,
    defaultOpen = false,
    isActive = false,
    kind,
    isBest = false,
    onTitleClick,
}: {
    title: string;
    children: React.ReactNode;
    defaultOpen?: boolean;
    isActive?: boolean;
    kind?: OperatorKind;
    isBest?: boolean;
    onTitleClick?: () => void;
}) {
    const [isOpen, setIsOpen] = useState(defaultOpen);

    const isOptimized = kind === "optimized";
    const isPipeline = kind === "pipeline";

    const rowBg = isOptimized
        ? "border-l-2 border-l-amber-400 dark:border-l-amber-500"
        : isPipeline
        ? "border-l-2 border-l-slate-300 dark:border-l-zinc-600"
        : isActive
        ? "border-l-2 border-l-emerald-500 dark:border-l-emerald-400"
        : "border-l-2 border-l-transparent";

    const hoverBg = "hover:bg-slate-50 dark:hover:bg-zinc-800/60";

    const titleColor = isOptimized
        ? "text-amber-700 dark:text-amber-400"
        : isPipeline
        ? "text-zinc-600 dark:text-zinc-300"
        : isActive
        ? "text-emerald-700 dark:text-emerald-400"
        : "text-zinc-600 dark:text-zinc-300";

    return (
        <div className={`border-b border-slate-100 dark:border-zinc-800 last:border-0 transition-colors ${rowBg}`}>
            <button
                onClick={() => {
                    setIsOpen(!isOpen);
                    onTitleClick?.();
                }}
                className={`w-full px-4 py-3 flex items-center justify-between text-left transition-colors ${hoverBg}`}
            >
                <span className="flex items-center gap-2">
                    {isOptimized && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 shrink-0">
                            optimized
                        </span>
                    )}
                    {isOptimized && isBest && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 shrink-0">
                            best
                        </span>
                    )}
                    {isPipeline && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-slate-100 text-slate-600 dark:bg-zinc-700 dark:text-zinc-300 shrink-0">
                            pipeline
                        </span>
                    )}
                    {!isOptimized && !isPipeline && isActive && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                    )}
                    <span className={`text-xs font-medium uppercase tracking-wider ${titleColor}`}>{title}</span>
                </span>
                <span className="text-zinc-400">
                    {isOpen ? (
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                            <path fillRule="evenodd" d="M4 10a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H4.75A.75.75 0 014 10z" clipRule="evenodd" />
                        </svg>
                    ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                            <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
                        </svg>
                    )}
                </span>
            </button>
            {isOpen && (
                <div className="relative">
                    {children}
                </div>
            )}
        </div>
    );
}

export function OptimizerDetailsPanel({
    selectedTrial,
    isExpanded = false,
    expandButton = null,
    operatorName,
    activeOperatorName,
    onOperatorClick,
    isDark = false,
    finalCode,
    optimizedOperatorName,
    hasRun = false,
    isBestTrial = false,
}: OptimizerDetailsPanelProps) {
    const hasFinalCode = finalCode && Object.keys(finalCode).length > 0;

    const emptyContent = !hasRun ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-zinc-400 dark:text-zinc-500">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                <polygon points="5,3 19,12 5,21" />
            </svg>
            <span className="text-sm text-center">Press Run to view generated code</span>
        </div>
    ) : (
        <div className="flex-1 flex items-center justify-center p-6 text-zinc-500 dark:text-zinc-400 text-sm text-center">
            {hasFinalCode
                ? "Select a node in the optimizer tree to highlight the optimized operator."
                : "Select a node in the optimizer tree to view its generated code."}
        </div>
    );

    // --- Build code blocks from finalCode (preferred) or trial state ---
    let codeBlocks: { name: string; code: string; kind?: OperatorKind }[] = [];

    if (hasFinalCode) {
        // Show all operators from the final code file; when a trial is selected,
        // substitute the optimized operator's code with that trial's specific output.
        codeBlocks = Object.entries(finalCode).map(([name, code]) => {
            let displayCode = code;
            if (selectedTrial && name === optimizedOperatorName) {
                const tc = selectedTrial.state.generated_code;
                if (typeof tc === "string") displayCode = tc;
                else if (Array.isArray(tc) && tc.length > 0) displayCode = tc[tc.length - 1];
            }
            return { name, code: displayCode, kind: name === optimizedOperatorName ? "optimized" : "pipeline" };
        });
    } else if (selectedTrial) {
        const { state } = selectedTrial;
        if (typeof state.generated_code === "string") {
            codeBlocks = [{ name: operatorName || "Generated Code", code: state.generated_code }];
        } else if (Array.isArray(state.generated_code)) {
            if (state.generated_code.length === 1) {
                codeBlocks = [{ name: operatorName || "Generated Code", code: state.generated_code[0] }];
            } else if (operatorName) {
                const lastCode = state.generated_code[state.generated_code.length - 1];
                codeBlocks = [{ name: operatorName, code: lastCode }];
            } else {
                codeBlocks = state.generated_code.map((code, index) => ({
                    name: `Operator ${index + 1}`,
                    code,
                }));
            }
        } else if (typeof state.generated_code === "object" && state.generated_code !== null) {
            codeBlocks = Object.entries(state.generated_code).map(([name, code]) => ({ name, code }));
        } else {
            codeBlocks = [{ name: "Generated Code", code: "# No code generated" }];
        }
    }

    const title = hasFinalCode ? "Operator code" : "Code details";

    // Track trial changes so the optimized accordion auto-reopens on each trial click
    const trialSelectionCountRef = useRef(0);
    const prevTrialRef = useRef<typeof selectedTrial>(selectedTrial);
    if (prevTrialRef.current !== selectedTrial) {
        prevTrialRef.current = selectedTrial;
        trialSelectionCountRef.current += 1;
    }
    const trialKey = trialSelectionCountRef.current;

    return (
        <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
            <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">{title}</h2>
                </div>
                {expandButton}
            </div>

            {!hasRun || codeBlocks.length === 0 ? (
                emptyContent
            ) : (
                <div className="flex-1 min-h-0 overflow-auto p-0 flex flex-col bg-white dark:bg-zinc-900">
                    {codeBlocks.map((block, index) => (
                        <AccordionItem
                            key={block.kind === 'optimized' ? `opt-${trialKey}` : `pipe-${block.name}`}
                            title={block.name}
                            defaultOpen={block.kind === 'optimized'}
                            kind={block.kind}
                            isBest={block.kind === 'optimized' && isBestTrial}
                            isActive={!block.kind && activeOperatorName?.toLowerCase() === block.name.toLowerCase()}
                            onTitleClick={() => onOperatorClick?.(block.name)}
                        >
                            <div className="h-64 sm:h-96 relative border-b border-slate-100 last:border-0">
                                <div className="absolute inset-0">
                                    <CodeOutput
                                        code={block.code}
                                        language="python"
                                        isLoading={false}
                                        isExpanded={isExpanded}
                                        isDark={isDark}
                                    />
                                </div>
                            </div>
                        </AccordionItem>
                    ))}
                </div>
            )}
        </div>
    );
}
