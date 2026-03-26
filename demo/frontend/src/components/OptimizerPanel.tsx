import { useEffect, useRef, useState, type ReactNode } from "react";
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
// @ts-ignore
import dagre from "cytoscape-dagre";
import { fetchOptimizerTrajectory, fetchOptimizerTrajectoryByScript, type OptimizerTrajectory, type OptimizerOutcome } from "../api/client";
import { toSkrubId } from "../utils/graphCodeSync";

cytoscape.use(dagre);

interface OptimizerPanelProps {
    expandButton?: ReactNode;
    onTrialSelect?: (trial: OptimizerOutcome | null) => void;
    selectedTrialId?: number | null;
    isExecuting?: boolean;
    hasFirstLiveNode?: boolean;
    onMetaUpdate?: (meta: { operatorName?: string }) => void;
    onTrajectoryLoaded?: (trajectory: OptimizerTrajectory | null) => void;
    showTree?: boolean;
    scriptId?: string | null;
    llmName?: string;
    temperature?: number;
    viewToggle?: React.ReactNode;
    isDark?: boolean;
    replayTrigger?: number;
}

// Same color palette as GraphPanel (Normal tab)
function getGraphColors(isDark: boolean) {
    return isDark
        ? {
            nodeBg: "#27272a", nodeBorder: "#52525b", nodeText: "#f4f4f5",
            canvasBg: "#09090b",
            operatorBg: "#27272a", operatorBorder: "#52525b",
            semBg: "#14532d", semBorder: "#4ade80",
            selSemBg: "#831843", selSemBorder: "#f472b6",
            selBg: "#78350f", selBorder: "#fbbf24",
            edgeColor: "#94a3b8",
        }
        : {
            nodeBg: "#ffffff", nodeBorder: "#64748b", nodeText: "#18181b",
            canvasBg: "#fafafa",
            operatorBg: "#ffffff", operatorBorder: "#94a3b8",
            semBg: "#dcfce7", semBorder: "#22c55e",
            selSemBg: "#fce7f3", selSemBorder: "#ec4899",
            selBg: "#fef9c3", selBorder: "#f59e0b",
            edgeColor: "#64748b",
        };
}

type GraphColors = ReturnType<typeof getGraphColors>;

function getStyles(colors: GraphColors) {
    return [
        {
            selector: "node",
            style: {
                "background-color": colors.nodeBg,
                "background-opacity": 0.3,
                "border-color": colors.nodeBorder,
                "border-width": 1.5,
                "border-style": "solid",
                label: "data(label)",
                "text-valign": "center",
                "text-halign": "center",
                "font-size": 12,
                "font-family": "ui-sans-serif, system-ui, -apple-system, sans-serif",
                color: colors.nodeText,
                width: "data(nodeWidth)",
                height: 32,
                shape: "round-rectangle",
                "text-wrap": "none",
                "opacity": 0,
                "transition-property": "opacity",
                "transition-duration": "600ms",
                "transition-timing-function": "ease-out",
            },
        },
        {
            selector: "node[nodeType = 'operator'][isSempipesSemantic = 'false']",
            style: {
                "background-color": colors.operatorBg,
                "background-opacity": 0.9,
                "border-style": "dashed",
                "border-color": colors.operatorBorder,
            },
        },
        {
            selector: "node[isSempipesSemantic = 'true']",
            style: {
                "background-color": colors.semBg,
                "background-opacity": 0.7,
                "border-color": colors.semBorder,
                "border-width": 2,
                "border-style": "dashed",
            },
        },
        {
            selector: "node.selected[isSempipesSemantic = 'true']",
            style: {
                "background-color": colors.selSemBg,
                "background-opacity": 1,
                "border-color": colors.selSemBorder,
                "border-width": 3,
                "border-style": "solid",
            },
        },
        {
            selector: "node.selected[isSempipesSemantic = 'false']",
            style: {
                "background-color": colors.selBg,
                "background-opacity": 1,
                "border-color": colors.selBorder,
                "border-width": 3,
                "border-style": "solid",
            },
        },
        {
            selector: "node.revealed",
            style: { "opacity": 1 },
        },
        {
            selector: "edge",
            style: {
                width: 1.5,
                "line-color": colors.edgeColor,
                "target-arrow-color": colors.edgeColor,
                "target-arrow-shape": "triangle",
                "curve-style": "straight",
                "arrow-scale": 0.8,
                "opacity": 0,
                "transition-property": "opacity",
                "transition-duration": "500ms",
                "transition-timing-function": "ease-out",
            },
        },
        {
            selector: "edge.revealed",
            style: { "opacity": 0.65 },
        },
        {
            selector: "edge.bestPath",
            style: {
                "line-color": colors.semBorder,
                "target-arrow-color": colors.semBorder,
                "width": 2,
            },
        },
        {
            selector: "edge.bestPath.revealed",
            style: { "opacity": 1 },
        },
    ];
}

/** Return the set of raw trial IDs on the path from root to the best node. */
function getBestPathRawIds(outcomes: OptimizerOutcome[], bestTrialId: number): Set<string> {
    const ids = new Set<string>();
    let current: number | null = bestTrialId;
    while (current !== null) {
        ids.add(`trial_${current}`);
        const node = outcomes.find(o => o.search_node.trial === current);
        current = node?.search_node.parent_trial ?? null;
    }
    return ids;
}

function playRevealAnimation(cy: Core) {
    const nodes = cy.nodes();
    if (nodes.length === 0) return;
    nodes.stop(true, true);
    cy.edges().addClass('revealed');
    nodes.addClass('revealed');
}

// Helper to check deep equality of trajectory outcomes
function isTrajectoryEqual(prev: OptimizerTrajectory | null, next: OptimizerTrajectory): boolean {
    if (!prev) return false;
    if (prev.outcomes.length !== next.outcomes.length) return false;
    // Check the last outcome (usually the one changing) and the best score
    const validPrev = prev.outcomes.map(o => o.score).filter((s): s is number => s != null);
    const validNext = next.outcomes.map(o => o.score).filter((s): s is number => s != null);
    const prevBest = validPrev.length ? Math.max(...validPrev) : -Infinity;
    const nextBest = validNext.length ? Math.max(...validNext) : -Infinity;
    if (Math.abs(prevBest - nextBest) > 1e-6) return false;

    // Check last item equality
    const prevLast = prev.outcomes[prev.outcomes.length - 1];
    const nextLast = next.outcomes[next.outcomes.length - 1];
    const prevScore = prevLast.score ?? -Infinity;
    const nextScore = nextLast.score ?? -Infinity;
    return prevLast.search_node.trial === nextLast.search_node.trial &&
        Math.abs(prevScore - nextScore) < 1e-6;
}

export const OptimizerPanel: React.FC<OptimizerPanelProps> = ({
    expandButton = null,
    onTrialSelect,
    selectedTrialId,
    isExecuting = false,
    hasFirstLiveNode = false,
    onMetaUpdate,
    onTrajectoryLoaded,
    showTree = false,
    scriptId,
    llmName,
    temperature,
    viewToggle = null,
    isDark = false,
    replayTrigger = 0,
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<Core | null>(null);
    const [trajectory, setTrajectory] = useState<OptimizerTrajectory | null>(null);

    // Internal state for selection if props are not provided (fallback) or for tracking
    const [internalSelectedId, setInternalSelectedId] = useState<string | null>(null);

    // Determine active selection: prop takes precedence if defined.
    // Cytoscape IDs are skrub_trial_N (toSkrubId adds the prefix).
    const activeSelectedNodeId = selectedTrialId !== undefined && selectedTrialId !== null
        ? toSkrubId(`trial_${selectedTrialId}`)
        : internalSelectedId;

    // Ref to track previous trajectory for polling comparison
    const prevTrajectoryRef = useRef<OptimizerTrajectory | null>(null);
    // Ref to track last RENDERED run ID for graph hard reset
    const lastRenderedRunIdRef = useRef<string | null>(null);
    // Ref to track shunned run IDs (e.g. from previous runs)
    const shunnedRunIdsRef = useRef<Set<string>>(new Set());
    // Ref to track if we've already cleared for the current execution
    const hasClearedForExecutionRef = useRef<boolean>(false);
    // Deferred replay: set when replayTrigger fires before Cytoscape is ready
    const pendingReplayRef = useRef<boolean>(false);

    useEffect(() => {
        onTrajectoryLoaded?.(trajectory);
    }, [trajectory, onTrajectoryLoaded]);

    useEffect(() => {
        if (replayTrigger > 0) {
            if (cyRef.current) {
                playRevealAnimation(cyRef.current);
            } else {
                // Cytoscape not yet initialised (panel just mounted) — defer until init
                pendingReplayRef.current = true;
            }
        }
    }, [replayTrigger]);

    // Handle Execution Start - Clear Graph
    useEffect(() => {
        if (isExecuting) {
            if (!hasClearedForExecutionRef.current) {
                console.log("Execution started - clearing graph and shunning current trajectory.");

                // Shun the current trajectory so it doesn't reappear during execution
                if (trajectory?.run_id) {
                    shunnedRunIdsRef.current.add(trajectory.run_id);
                }

                setTrajectory(null);
                prevTrajectoryRef.current = null;
                lastRenderedRunIdRef.current = null;

                if (cyRef.current) {
                    cyRef.current.destroy();
                    cyRef.current = null;
                }
                if (onTrialSelect) onTrialSelect(null);

                hasClearedForExecutionRef.current = true;
            }
        } else {
            // Reset flag when execution stops
            hasClearedForExecutionRef.current = false;
            // Clear shun list so the next poll can show the trajectory (critical for cached runs
            // which complete instantly and return the same run_id that was shunned at start)
            shunnedRunIdsRef.current.clear();
        }
    }, [isExecuting, trajectory?.run_id, onTrialSelect]);

    // Poll for trajectory data
    useEffect(() => {
        let mounted = true;
        const fetchData = async () => {
            try {
                const data = scriptId
                    ? await fetchOptimizerTrajectoryByScript(scriptId, llmName, temperature)
                    : await fetchOptimizerTrajectory();
                if (mounted) {
                    // Check if run ID is shunned
                    if (data.run_id && shunnedRunIdsRef.current.has(data.run_id)) {
                        /* console.log("Ignoring shunned run ID:", data.run_id); */
                        // If we are executing and see a shunned ID, keep showing nothing (loading)
                        // If NOT executing, we might want to show it? Or keeping it hidden is safer.
                        // For now, let's keep it hidden to avoid flashing old data.
                        return;
                    }

                    // Only update state if data changed to avoid re-renders
                    if (!isTrajectoryEqual(prevTrajectoryRef.current, data)) {
                        setTrajectory(data);
                        prevTrajectoryRef.current = data;

                        // Notify parent of operator name
                        if (onMetaUpdate && data.optimizer_args?.operator_name) {
                            onMetaUpdate({ operatorName: data.optimizer_args.operator_name });
                        }
                    }
                }
            } catch (err) {
                if (mounted) {
                    // On error, keep existing data (or could set error state)
                }
            }
        };

        fetchData();
        const interval = setInterval(fetchData, 2000);
        return () => {
            mounted = false;
            clearInterval(interval);
        };
    }, [scriptId, llmName, temperature, onMetaUpdate]);

    // Update Cytoscape Graph — incremental diff, dagre tree layout, same style as Normal tab
    useEffect(() => {
        if (!containerRef.current || !trajectory) return;

        const outcomes = trajectory.outcomes;
        if (outcomes.length === 0) return;

        // Wipe on run-id change
        if (trajectory.run_id && lastRenderedRunIdRef.current && trajectory.run_id !== lastRenderedRunIdRef.current) {
            if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; }
            if (onTrialSelect) onTrialSelect(null);
        }
        if (trajectory.run_id) lastRenderedRunIdRef.current = trajectory.run_id;

        const bestOutcome = [...outcomes].sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity))[0];
        const bestTrialId = bestOutcome.search_node.trial;
        const bestPathRawIds = getBestPathRawIds(outcomes, bestTrialId);

        const makeNodeEl = (o: OptimizerOutcome) => ({
            data: {
                id: `skrub_trial_${o.search_node.trial}`,
                label: o.score != null ? o.score.toFixed(3) : "N/A",
                nodeType: "operator" as const,
                isSempipesSemantic: o.search_node.trial === bestTrialId ? "true" : "false",
                nodeWidth: 70,
                outcomeObj: o,
            },
        });

        const makeEdgeEl = (o: OptimizerOutcome) => ({
            data: {
                id: `skrub_trial_${o.search_node.parent_trial}-skrub_trial_${o.search_node.trial}`,
                source: `skrub_trial_${o.search_node.parent_trial}`,
                target: `skrub_trial_${o.search_node.trial}`,
            },
        });

        const colors = getGraphColors(isDark);

        if (!cyRef.current) {
            const nodeEls = outcomes.map(makeNodeEl);
            const edgeEls = outcomes.filter(o => o.search_node.parent_trial !== null).map(makeEdgeEl);

            const cy = cytoscape({
                container: containerRef.current,
                elements: [...nodeEls, ...edgeEls],
                style: getStyles(colors) as any,
                minZoom: 0.1,
                maxZoom: 3,
            });

            cy.layout({ name: "dagre", rankDir: "TB", nodeSep: 60, rankSep: 80, fit: true, padding: 20 } as any).run();

            cy.edges().forEach((edge: cytoscape.EdgeSingular) => {
                const srcRaw = edge.source().id().replace("skrub_", "");
                const tgtRaw = edge.target().id().replace("skrub_", "");
                if (bestPathRawIds.has(srcRaw) && bestPathRawIds.has(tgtRaw)) edge.addClass("bestPath");
            });

            if (activeSelectedNodeId) cy.getElementById(activeSelectedNodeId).addClass("selected");

            cy.on("tap", "node", (evt) => {
                const node = evt.target as NodeSingular;
                cy.nodes().removeClass("selected");
                node.addClass("selected");
                const outcome = node.data("outcomeObj") as OptimizerOutcome | undefined;
                if (outcome && onTrialSelect) onTrialSelect(outcome);
                setInternalSelectedId(node.id());
            });
            cy.on("tap", (evt) => {
                if (evt.target === cy) {
                    cy.nodes().removeClass("selected");
                    setInternalSelectedId(null);
                    if (onTrialSelect) onTrialSelect(null);
                }
            });

            cyRef.current = cy;

            if (pendingReplayRef.current) pendingReplayRef.current = false;
            playRevealAnimation(cy);

        } else {
            const cy = cyRef.current;
            const existingNodeIds = new Set(cy.nodes().map((n: cytoscape.NodeSingular) => n.id()));
            const existingEdgeIds = new Set(cy.edges().map((e: cytoscape.EdgeSingular) => e.id()));

            const newNodeEls = outcomes
                .filter(o => !existingNodeIds.has(`skrub_trial_${o.search_node.trial}`))
                .map(makeNodeEl);
            const newEdgeEls = outcomes
                .filter(o => o.search_node.parent_trial !== null &&
                    !existingEdgeIds.has(`skrub_trial_${o.search_node.parent_trial}-skrub_trial_${o.search_node.trial}`))
                .map(makeEdgeEl);

            cy.batch(() => {
                if (newNodeEls.length > 0) {
                    const added = cy.add(newNodeEls);
                    added.forEach((node: cytoscape.NodeSingular) => {
                        const incoming = node.connectedEdges().filter((e: cytoscape.EdgeSingular) => e.target().id() === node.id());
                        if (incoming.length > 0) node.position({ ...incoming[0].source().position() });
                    });
                }
                if (newEdgeEls.length > 0) cy.add(newEdgeEls);

                // Update isSempipesSemantic for all nodes (best may have changed)
                outcomes.forEach(o => {
                    const node = cy.getElementById(`skrub_trial_${o.search_node.trial}`);
                    if (node.length > 0) node.data("isSempipesSemantic", o.search_node.trial === bestTrialId ? "true" : "false");
                });

                // Sync best-path edges
                cy.edges().forEach((edge: cytoscape.EdgeSingular) => {
                    const srcRaw = edge.source().id().replace("skrub_", "");
                    const tgtRaw = edge.target().id().replace("skrub_", "");
                    if (bestPathRawIds.has(srcRaw) && bestPathRawIds.has(tgtRaw)) edge.addClass("bestPath");
                    else edge.removeClass("bestPath");
                });
            });

            if (newNodeEls.length > 0 || newEdgeEls.length > 0) {
                cy.layout({ name: "dagre", rankDir: "TB", nodeSep: 60, rankSep: 80, fit: false, animate: true, animationDuration: 300 } as any).run();
                newNodeEls.forEach(n => cy.getElementById(n.data.id).addClass("revealed"));
                newEdgeEls.forEach(e => cy.getElementById(e.data.id).addClass("revealed"));
            }

            cy.style(getStyles(colors) as any);
        }
    }, [trajectory, isDark, showTree]); // showTree gates containerRef being in the DOM

    return (
        <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
            <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex items-center justify-between gap-2">
                <div className="flex-1">
                    <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Optimizer trajectory</h2>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">Exploring pipeline code variants to maximise score</p>
                </div>
                <div className="flex items-center gap-4">
                    {viewToggle}
                    {expandButton}
                </div>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden bg-slate-50 dark:bg-zinc-950 relative">
                {!showTree && !isExecuting ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="text-slate-300 dark:text-zinc-600">
                            <polygon points="5,3 19,12 5,21" />
                        </svg>
                        <div className="text-sm text-zinc-400 dark:text-zinc-500">Press Run to view the optimizer tree</div>
                    </div>
                ) : (
                    <>
                        <div
                            ref={containerRef}
                            className="w-full h-full"
                            style={{ visibility: trajectory ? 'visible' : 'hidden' }}
                        />
                        {!trajectory && (
                            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                                {isExecuting ? (
                                    !hasFirstLiveNode ? (
                                        <>
                                            <div className="w-10 h-10 rounded-full border-2 border-slate-300 border-t-emerald-500 animate-spin" />
                                            <div className="text-sm text-emerald-600 font-medium animate-pulse">Waiting for first node...</div>
                                        </>
                                    ) : (
                                        <>
                                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="text-slate-300 dark:text-zinc-700">
                                                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                                            </svg>
                                            <div className="text-sm text-slate-600 dark:text-zinc-400 font-medium">Running fresh pipeline</div>
                                            <div className="text-xs text-slate-400 dark:text-zinc-500 max-w-xs text-center">Trajectories are disabled for live runs.<br />Wait for execution to finish.</div>
                                        </>
                                    )
                                ) : (
                                    <>
                                        <div className="w-10 h-10 rounded-full border-2 border-slate-300 border-t-zinc-400" />
                                        <div className="text-sm text-zinc-500">Waiting for run...</div>
                                    </>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
