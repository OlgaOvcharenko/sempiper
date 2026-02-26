import { useState } from "react";
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
}

function AccordionItem({
    title,
    children,
    defaultOpen = false,
    isActive = false,
    onTitleClick,
}: {
    title: string;
    children: React.ReactNode;
    defaultOpen?: boolean;
    isActive?: boolean;
    onTitleClick?: () => void;
}) {
    const [isOpen, setIsOpen] = useState(defaultOpen);

    return (
        <div className={`border-b border-slate-100 dark:border-zinc-800 last:border-0 transition-colors ${isActive ? 'bg-emerald-50/60 dark:bg-emerald-900/20' : ''}`}>
            <button
                onClick={() => {
                    setIsOpen(!isOpen);
                    onTitleClick?.();
                }}
                className={`w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-50 dark:hover:bg-zinc-800 transition-colors ${isActive ? 'hover:bg-emerald-50 dark:hover:bg-emerald-900/30' : ''}`}
            >
                <span className="flex items-center gap-2">
                    {isActive && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                    )}
                    <span className={`text-xs font-medium uppercase tracking-wider ${isActive ? 'text-emerald-700 dark:text-emerald-400' : 'text-zinc-600 dark:text-zinc-300'}`}>{title}</span>
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

export function OptimizerDetailsPanel({ selectedTrial, isExpanded = false, expandButton = null, operatorName, activeOperatorName, onOperatorClick, isDark = false }: OptimizerDetailsPanelProps) {
    if (!selectedTrial) {
        return (
            <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
                <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
                    <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Trial Details</h2>
                    {expandButton}
                </div>
                <div className="flex-1 flex items-center justify-center p-6 text-zinc-500 dark:text-zinc-400 text-sm text-center">
                    Select a node in the optimizer tree to view its generated code.
                </div>
            </div>
        );
    }

    // Force array of objects for uniform handling: { name: string, code: string }
    const { search_node, state } = selectedTrial;
    let codeBlocks: { name: string, code: string }[] = [];

    if (typeof state.generated_code === 'string') {
        codeBlocks = [{ name: operatorName || "Generated Code", code: state.generated_code }];
    } else if (Array.isArray(state.generated_code)) {
        if (state.generated_code.length === 1) {
            codeBlocks = [{ name: operatorName || "Generated Code", code: state.generated_code[0] }];
        } else {
            // If explicit operator name provided, show only the last block (most relevant)
            if (operatorName) {
                const lastCode = state.generated_code[state.generated_code.length - 1];
                codeBlocks = [{ name: operatorName, code: lastCode }];
            } else {
                codeBlocks = state.generated_code.map((code, index) => ({
                    name: `Operator ${index + 1}`,
                    code
                }));
            }
        }
    } else if (typeof state.generated_code === 'object' && state.generated_code !== null) {
        // Record<string, string> - Use keys as names
        codeBlocks = Object.entries(state.generated_code).map(([name, code]) => ({
            name: name, // e.g., "product_features"
            code
        }));
    } else {
        codeBlocks = [{ name: "Generated Code", code: "# No code generated" }];
    }

    return (
        <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
            <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Trial #{search_node.trial}</h2>
                </div>
                {expandButton}
            </div>

            <div className="flex-1 min-h-0 overflow-auto p-0 flex flex-col bg-white dark:bg-zinc-900">
                {codeBlocks.map((block, index) => (
                    <AccordionItem
                        key={index}
                        title={block.name}
                        defaultOpen={false}
                        isActive={activeOperatorName?.toLowerCase() === block.name.toLowerCase()}
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
        </div>
    );
}
