import { useEffect, useRef, useState, type ReactNode } from "react";
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
// @ts-ignore
import dagre from "cytoscape-dagre";
import { fetchOptimizerTrajectory, fetchOptimizerTrajectoryByScript, type OptimizerTrajectory, type OptimizerOutcome } from "../api/client";

cytoscape.use(dagre);

interface OptimizerPanelProps {
    expandButton?: ReactNode;
    onTrialSelect?: (trial: OptimizerOutcome | null) => void;
    selectedTrialId?: number | null;
    isExecuting?: boolean;
    hasFirstLiveNode?: boolean;
    onMetaUpdate?: (meta: { operatorName?: string }) => void;
    scriptId?: string | null;
    viewToggle?: React.ReactNode;
    isDark?: boolean;
    replayTrigger?: number;
}

// 1. Neon Cyberpunk
const TREE_COLORS = {
    bestNodeBgLight: '#ffe2e7',
    bestNodeBgDark: '#2d004b',
    bestNodeBorder: '#f43f5e',
    bestNodeTextLight: '#1e1b4b',
    bestNodeTextDark: '#e0e7ff',
    otherNodeBgLight: '#fffdf3',
    otherNodeBgDark: '#a79f82',
    otherNodeBorderLight: '#f0f0e2',
    otherNodeBorderDark: '#312e81',
    otherNodeTextLight: '#1e1b4b',
    otherNodeTextDark: '#e0e7ff',
    edgeNormalLight: '#818cf8',
    edgeNormalDark: '#4f46e5',
    edgeBest: '#ec4899',
    nodeSelected: '#818cf8'
};

type Palette = typeof TREE_COLORS;

function getStyles(isDark: boolean, palette: Palette) {
    return [
        {
            selector: "node",
            style: {
                "background-color": "data(nodeColor)",
                "border-color": "data(nodeBorder)",
                "border-width": 1.5,
                "label": "data(formattedScore)",
                "text-valign": "center",
                "text-halign": "center",
                "font-family": "'ui-monospace', 'SFMono-Regular', monospace",
                "font-size": 13,
                "font-weight": 600,
                "color": "data(nodeTextColor)",
                "width": 88,
                "height": 48,
                "shape": "roundrectangle",
                "text-outline-width": 0,
                "opacity": 0,
                "transition-property": "opacity",
                "transition-duration": "600ms",
                "transition-timing-function": "cubic-bezier(0.175, 0.885, 0.32, 1.275)",
            },
        },
        {
            selector: "node.revealed",
            style: {
                "opacity": 1,
            }
        },
        {
            selector: "node[isOverallBest = 'true']",
            style: {
                "font-size": 14,
                "border-width": 2.5,
                "z-index": 20,
            }
        },
        {
            selector: "edge",
            style: {
                "width": 0.75,
                "line-color": isDark ? palette.edgeNormalDark : palette.edgeNormalLight,
                "target-arrow-color": isDark ? palette.edgeNormalDark : palette.edgeNormalLight,
                "target-arrow-shape": "triangle",
                "curve-style": "unbundled-bezier",
                "control-point-weights": "data(cpWeights)",
                "control-point-distances": "data(cpDistances)",
                "source-endpoint": "0% 50%",
                "target-endpoint": "0% -50%",
                "arrow-scale": 0.7,
                "opacity": 0,
                "transition-property": "opacity",
                "transition-duration": "500ms",
                "transition-timing-function": "ease-out",
            },
        },
        {
            selector: "edge.revealed",
            style: {
                "opacity": 0.65,
            },
        },
        {
            selector: "edge[isBestPath = 'true']",
            style: {
                "width": 1,
                "line-color": palette.edgeBest,
                "target-arrow-color": palette.edgeBest,
                "z-index": 5,
            },
        },
        {
            selector: "edge[isBestPath = 'true'].revealed",
            style: {
                "opacity": 0.85,
            },
        },
        {
            selector: "node:selected",
            style: {
                "border-width": 4,
                "border-color": palette.nodeSelected,
                "border-opacity": 1,
                "z-index": 100,
                "overlay-opacity": 0,
            }
        }
    ];
}

// Styling rule: 
// 1. Uniform background for ALL nodes (slate dark / white light).
// 2. Pink (#fb7185) is ONLY used for details: best node border, best path edges, selected rings.
function getNodeStyle(isBest: boolean, isDark: boolean, palette: Palette): {
    bg: string;
    border: string;
    textColor: string;
} {
    if (isBest) return {
        bg: isDark ? palette.bestNodeBgDark : palette.bestNodeBgLight,
        border: palette.bestNodeBorder,
        textColor: isDark ? palette.bestNodeTextDark : palette.bestNodeTextLight,
    };

    return {
        bg: isDark ? palette.otherNodeBgDark : palette.otherNodeBgLight,
        border: isDark ? palette.otherNodeBorderDark : palette.otherNodeBorderLight,
        textColor: isDark ? palette.otherNodeTextDark : palette.otherNodeTextLight,
    };
}

function playRevealAnimation(cy: Core) {
    const unrevealedNodes = cy.nodes();
    if (unrevealedNodes.length === 0) return;

    // Reset visibility immediately
    unrevealedNodes.removeClass('revealed');
    cy.edges().removeClass('revealed');
    // Stop all ongoing animations
    unrevealedNodes.stop(true, true);

    const sortedNodes = unrevealedNodes.sort((a, b) => {
        const idA = parseInt(a.id().replace('trial_', '')) || 0;
        const idB = parseInt(b.id().replace('trial_', '')) || 0;
        return idA - idB;
    });

    // Time between each trial's reveal
    const TIME_PER_TRIAL = 600; // ms
    const EDGE_DELAY = 400; // time between edge showing and node appearing

    sortedNodes.forEach((node, i) => {
        const isRoot = i === 0;
        const startTime = isRoot ? 100 : i * TIME_PER_TRIAL;

        setTimeout(() => {
            if (node.removed()) return;

            if (isRoot) {
                // Root node appears immediately
                node.addClass('revealed');
            } else {
                // For child nodes, reveal the edge from parent first
                const incomingEdges = node.connectedEdges().filter(e => e.target().id() === node.id());
                if (incomingEdges.length > 0) {
                    incomingEdges[0].addClass('revealed');

                    // Then reveal the node shortly after edge starts forming
                    setTimeout(() => {
                        if (!node.removed()) {
                            node.addClass('revealed');
                        }
                    }, EDGE_DELAY);
                } else {
                    node.addClass('revealed');
                }
            }
        }, startTime);
    });
}

// Helper to check deep equality of trajectory outcomes
function isTrajectoryEqual(prev: OptimizerTrajectory | null, next: OptimizerTrajectory): boolean {
    if (!prev) return false;
    if (prev.outcomes.length !== next.outcomes.length) return false;
    // Check the last outcome (usually the one changing) and the best score
    const prevBest = Math.max(...prev.outcomes.map(o => o.score));
    const nextBest = Math.max(...next.outcomes.map(o => o.score));
    if (Math.abs(prevBest - nextBest) > 1e-6) return false;

    // Check last item equality
    const prevLast = prev.outcomes[prev.outcomes.length - 1];
    const nextLast = next.outcomes[next.outcomes.length - 1];
    return prevLast.search_node.trial === nextLast.search_node.trial &&
        Math.abs(prevLast.score - nextLast.score) < 1e-6;
}

export const OptimizerPanel: React.FC<OptimizerPanelProps> = ({
    expandButton = null,
    onTrialSelect,
    selectedTrialId,
    isExecuting = false,
    hasFirstLiveNode = false,
    onMetaUpdate,
    scriptId,
    viewToggle = null,
    isDark = false,
    replayTrigger = 0,
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<Core | null>(null);
    const [trajectory, setTrajectory] = useState<OptimizerTrajectory | null>(null);

    // Internal state for selection if props are not provided (fallback) or for tracking
    const [internalSelectedId, setInternalSelectedId] = useState<string | null>(null);

    // Determine active selection: prop takes precedence if defined
    const activeSelectedNodeId = selectedTrialId !== undefined && selectedTrialId !== null
        ? `trial_${selectedTrialId}`
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
                    ? await fetchOptimizerTrajectoryByScript(scriptId)
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
    }, [scriptId, onMetaUpdate]);

    // Pulse Animation Effect
    useEffect(() => {
        let animationFrameId: number;
        let startTime = Date.now();

        const animate = () => {
            if (!cyRef.current || !isExecuting) return;

            const nodes = cyRef.current.nodes();
            if (nodes.length === 0) return;

            // Simple pulse effect on border width or opacity
            const time = Date.now() - startTime;
            // distinct pulse for latest node vs others? 
            // User asked: "When node 0 is ready, it should show it pulsing. When node 1 arrives it the whole pipeline should pulse."

            // We can pulse the opacity or a subtle shadow/glow
            const pulse = (Math.sin(time / 500) + 1) / 2; // 0 to 1
            // Pulse opacity between 0.8 and 1.0
            const opacity = 0.8 + (pulse * 0.2);

            cyRef.current.batch(() => {
                // Pulse all nodes to look "alive"
                nodes.style({
                    'opacity': opacity
                });

                // Best path stays fully opaque or pulses differently?
                // Let's keep it simple: everything pulses slightly.
            });

            animationFrameId = requestAnimationFrame(animate);
        };

        if (isExecuting) {
            animate();
        } else {
            // Reset styles when execution stops
            if (cyRef.current) {
                cyRef.current.nodes().style({
                    'opacity': 1
                });
                cyRef.current.nodes('[isBestPath = "true"]').style({
                    'opacity': 1
                });
            }
        }

        return () => {
            if (animationFrameId) cancelAnimationFrame(animationFrameId);
        };
    }, [isExecuting, trajectory]); // Re-start animation if execution state or trajectory (new nodes) changes

    // Update Cytoscape Graph
    useEffect(() => {
        if (!containerRef.current || !trajectory) return;

        // 0. Check for Run ID change - WIPE EVERYTHING if changed
        if (trajectory.run_id && lastRenderedRunIdRef.current && trajectory.run_id !== lastRenderedRunIdRef.current) {
            console.log("Run ID changed from", lastRenderedRunIdRef.current, "to", trajectory.run_id, "- Wiping graph.");
            if (cyRef.current) {
                cyRef.current.destroy();
                cyRef.current = null;
            }
            if (onTrialSelect) onTrialSelect(null);
        }

        // Update the last rendered run ID
        if (trajectory.run_id) {
            lastRenderedRunIdRef.current = trajectory.run_id;
        }

        // 1. Prepare elements
        const outcomes = trajectory.outcomes;
        if (outcomes.length === 0) return;

        // Find Golden Path
        const bestOutcome = [...outcomes].sort((a, b) => b.score - a.score)[0];
        const bestPathIds = new Set<number>();
        if (bestOutcome) {
            let current: number | null = bestOutcome.search_node.trial;
            while (current !== null) {
                bestPathIds.add(current);
                const node = outcomes.find((o) => o.search_node.trial === current);
                current = node?.search_node.parent_trial ?? null;
            }
        }

        const nodes = outcomes.map((o) => {
            const id = o.search_node.trial;
            const isBestPath = bestPathIds.has(id);
            const isOverallBest = id === bestOutcome.search_node.trial;
            const style = getNodeStyle(isOverallBest, isDark, TREE_COLORS);

            return {
                data: {
                    id: `trial_${id}`,
                    label: o.score.toFixed(3),
                    score: o.score,
                    formattedScore: o.score.toFixed(3),
                    isBestPath: isBestPath ? "true" : "false",
                    isOverallBest: isOverallBest ? "true" : "false",
                    nodeColor: style.bg,
                    nodeBorder: style.border,
                    nodeTextColor: style.textColor,
                    // Hardcode widths so dagre layout engine doesn't cram them while tiny
                    width: 88,
                    height: 48,
                    // EMBED FULL DATA HERE for strict sync
                    generatedCode: o.state.generated_code,
                    outcomeObj: o,
                },
            };
        });

        const edges = outcomes
            .filter((o) => o.search_node.parent_trial !== null)
            .map((o) => {
                const source = o.search_node.parent_trial!;
                const target = o.search_node.trial;
                const isBest = bestPathIds.has(source) && bestPathIds.has(target);
                return {
                    data: {
                        id: `edge_${source}_${target}`,
                        source: `trial_${source}`,
                        target: `trial_${target}`,
                        isBestPath: isBest ? "true" : "false",
                        cpDistances: "0 0",
                        cpWeights: "0.1 0.9",
                    },
                };
            });

        // 2. Initialize or Update Cytoscape
        let cy = cyRef.current;

        if (!cy) {
            // Initialize
            cy = cytoscape({
                container: containerRef.current,
                elements: [...nodes, ...edges],
                style: getStyles(isDark, TREE_COLORS) as any,
                minZoom: 0.1,
                maxZoom: 3,
            });

            const layoutOptions = {
                name: "dagre",
                rankDir: "TB",
                nodeSep: 60, // Increased spacing to prevent cramping
                rankSep: 80,
                fit: true,
                padding: 20,
            };

            const updateEdgeControlPoints = (edge: cytoscape.EdgeSingular) => {
                const p1 = edge.source().position();
                const p2 = edge.target().position();
                if (p1 && p2) {
                    const dx = p2.x - p1.x;
                    const scale = -0.2; // Based on user preference
                    const d1 = -dx * scale;
                    const d2 = dx * scale;
                    // Directly apply style to override anything else immediately
                    edge.style('control-point-distances', `${d1} ${d2}`);
                }
            };

            // Calculate dynamic control points for beautiful S-curves after ANY layout
            cy.on('layoutstop', () => {
                if (!cyRef.current) return;
                cyRef.current.batch(() => {
                    cyRef.current!.edges().forEach(updateEdgeControlPoints);
                });
            });

            // Also calculate during any node movement or animation to avoid incorrect rendering
            cy.on('position', 'node', (evt) => {
                const node = evt.target as NodeSingular;
                node.connectedEdges().forEach(updateEdgeControlPoints);
            });

            // Capture non-null instance for the closure. Using cyRef.current would fail
            // if the layout fires synchronously (before cyRef.current = cy is reached).
            const cyInstance = cy;
            cy.one('layoutstop', () => {
                playRevealAnimation(cyInstance);
            });

            // Run layout manually
            cy.layout(layoutOptions as any).run();

            // Set Initial Selection
            if (activeSelectedNodeId) {
                cy.getElementById(activeSelectedNodeId).select();
            }

            // Node Selection - Read from embedded data
            cy.on("tap", "node", (evt) => {
                const node = evt.target as NodeSingular;
                const data = node.data();

                if (onTrialSelect && data.outcomeObj) {
                    // Use embedded object to ensure sync
                    onTrialSelect(data.outcomeObj);
                }
                setInternalSelectedId(node.id());
            });

            cy.on("tap", (evt) => {
                if (evt.target === cy) {
                    setInternalSelectedId(null);
                    if (onTrialSelect) onTrialSelect(null);
                }
            });

            cyRef.current = cy;

            // Consume a deferred replay request (replayTrigger fired before this init ran)
            if (pendingReplayRef.current) {
                pendingReplayRef.current = false;
                playRevealAnimation(cy);
            }
        } else {
            // Intelligent Update using Diffing
            const instance = cy; // Capture non-null instance

            instance.batch(() => {
                const existingNodeIds = new Set(instance.nodes().map(n => n.id()));
                const existingEdgeIds = new Set(instance.edges().map(e => e.id()));

                const newNodes = nodes.filter(n => !existingNodeIds.has(n.data.id));
                const newEdges = edges.filter(e => !existingEdgeIds.has(e.data.id));

                // 1. Add new elements and pre-position them at their parent
                if (newNodes.length > 0) {
                    const addedNodes = instance.add(newNodes);
                    if (newEdges.length > 0) instance.add(newEdges);

                    addedNodes.forEach(node => {
                        const parentEdges = node.connectedEdges().filter(e => e.target().id() === node.id());
                        if (parentEdges.length > 0) {
                            node.position({ ...parentEdges[0].source().position() });
                        } else {
                            node.position({ x: node.position().x, y: node.position().y - 40 });
                        }
                    });
                } else if (newEdges.length > 0) {
                    instance.add(newEdges);
                }

                // 2. Update existing nodes (color, bestPath, AND embedded data)
                nodes.forEach(n => {
                    if (existingNodeIds.has(n.data.id)) {
                        const node = instance.getElementById(n.data.id);
                        // Always update data to ensure sync (e.g. if we want to update score/code dynamic)
                        // though typically they are immutable per trial ID.
                        // But best path status changes.
                        node.data(n.data);
                    }
                });

                edges.forEach(e => {
                    if (existingEdgeIds.has(e.data.id)) {
                        const edge = instance.getElementById(e.data.id);
                        if (edge.data("isBestPath") !== e.data.isBestPath) {
                            edge.data(e.data);
                        }
                    }
                });
            });

            // Sync dynamic styles from PALETTE
            instance.style(getStyles(isDark, TREE_COLORS) as any);

            // Force recalculation of edge curves for any newly added edges
            instance.edges().forEach((edge: cytoscape.EdgeSingular) => {
                const p1 = edge.source().position();
                const p2 = edge.target().position();
                if (p1 && p2) {
                    const dx = p2.x - p1.x;
                    const scale = -0.2;
                    const d1 = -dx * scale;
                    const d2 = dx * scale;
                    edge.style('control-point-distances', `${d1} ${d2}`);
                }
            });

            // Ensure all elements are revealed so CSS fade starts now
            instance.nodes().addClass('revealed');
            instance.edges().addClass('revealed');

            // 3. Layout - Always run "soft" layout (fit: false) to ensure new nodes are positioned
            instance.layout({
                name: "dagre",
                rankDir: "TB",
                nodeSep: 60,
                rankSep: 80,
                fit: false,
                animate: true,
                animationDuration: 300,
            } as any).run();

            // Update Selection State based on activeSelectedNodeId
            if (activeSelectedNodeId) {
                const instance = cy; // capture local ref
                const node = instance.getElementById(activeSelectedNodeId);
                if (node.length > 0) {
                    if (!node.selected()) {
                        instance.$(':selected').unselect();
                        node.select();
                    }
                }
            } else {
                cy.elements().unselect();
            }
        }
    }, [trajectory, activeSelectedNodeId, isDark]); // Re-run if trajectory changes, selection changes, or palette changes

    return (
        <div className="h-full flex flex-col rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 overflow-hidden shadow-md">
            <div className="shrink-0 h-[var(--header-height)] px-3 border-b border-slate-300 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 flex flex-col justify-center gap-0.5">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex-1">
                        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Optimizer Trajectory</h2>
                        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                            {trajectory
                                ? (
                                    <>
                                        <span>MCTS Tree · {trajectory.outcomes.length} trials</span>
                                        {trajectory.optimizer_args?.scoring && (
                                            <>
                                                <span className="mx-1">·</span>
                                                <span className="font-medium">Metric: {trajectory.optimizer_args.scoring}</span>
                                            </>
                                        )}
                                        <span className="mx-1">·</span>
                                        <span>Best: {Math.max(...trajectory.outcomes.map(o => o.score)).toFixed(3)}</span>
                                        {isExecuting && <span className="ml-2 text-emerald-600 animate-pulse">Running...</span>}
                                    </>
                                )
                                : (isExecuting
                                    ? <span className="text-emerald-600 animate-pulse">Starting optimization...</span>
                                    : "Waiting for optimization...")}
                        </p>
                    </div>
                    <div className="flex items-center gap-4">
                        {viewToggle}
                        {expandButton}
                    </div>
                </div>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden bg-slate-50 dark:bg-zinc-950 relative">
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
                                <div
                                    className="w-10 h-10 rounded-full border-2 border-slate-300 border-t-zinc-400"
                                />
                                <div className="text-sm text-zinc-500">Waiting for run...</div>
                            </>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
