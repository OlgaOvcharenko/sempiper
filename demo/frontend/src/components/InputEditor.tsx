import { useRef, useCallback, useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";

/** Node with source range for editor decorations and code–graph sync. */
interface NodeRange {
  id: string;
  type?: string;
  source_range: {
    start_line: number;
    start_column: number;
    end_line: number;
    end_column: number;
  };
}

interface InputEditorProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Nodes with source ranges for background decorations and code–graph sync. */
  nodeRanges?: NodeRange[];
  /** Called when cursor/click maps to node(s) in the graph. */
  onHighlightNodes?: (nodeIds: string[]) => void;
  /** When user clicks on a range, select this node in the graph. */
  onSelectNode?: (nodeId: string | null) => void;
  /** Currently selected graph node id — highlight its range in the code. */
  selectedNodeId?: string | null;
  /** Node IDs to show as selected (e.g. when selecting from graph, we pass compile node ids). */
  highlightedNodeIds?: string[];
  /** Whether the panel is expanded (controls word wrap). */
  isExpanded?: boolean;
  /** When set, move editor cursor to this node's source range (e.g. after graph node click). */
  focusNodeId?: string | null;
  /** Called after cursor has been moved to focusNodeId (parent should clear focusNodeId). */
  onFocusApplied?: () => void;
  /** Node IDs that are sempipes semantic operators (for pink selection styling). */
  sempipesNodeIds?: string[];
  /** Whether dark mode is active. */
  isDark?: boolean;
  /** The operator name to highlight and scroll to (e.g., from the Optimizer panel) */
  activeOperatorName?: string;
}

const EDITOR_BG_LIGHT = "#ffffff";
const EDITOR_BG_DARK = "#18181b"; // zinc-900

/** Decoration class for as_X / as_y (input) elements. */
const INPUT_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-input-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Decoration for sempipes operators (sem_fillna, sem_gen_features, etc.) — green. */
const SEMPIPES_OPERATOR_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-operator-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Decoration for non-sempipes operators (skb.subsample, etc.) — no color/white. */
const REGULAR_OPERATOR_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-regular-operator-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Darker overlay when hovering a range (marks middle panel). */
const HOVER_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-hover-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Selected non-sempipes graph node highlighted in code — yellow. */
const SELECTED_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-selected-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Selected sempipes graph node highlighted in code — pink. */
const SELECTED_SEMPIPES_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-selected-sempipes-decoration",
  marginClassName: "sempipe-element-margin",
};

function decorationForType(nodeType: string | undefined, isSempipes: boolean): editor.IModelDecorationOptions {
  if (nodeType === "input") return INPUT_DECORATION;
  if (isSempipes) return SEMPIPES_OPERATOR_DECORATION;
  return REGULAR_OPERATOR_DECORATION;
}

export function InputEditor({
  value,
  onChange,
  disabled,
  nodeRanges = [],
  onHighlightNodes,
  onSelectNode,
  selectedNodeId = null,
  highlightedNodeIds = [],
  isExpanded = false,
  focusNodeId = null,
  onFocusApplied,
  sempipesNodeIds = [],
  isDark = false,
  activeOperatorName,
}: InputEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof import("monaco-editor") | null>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const [hoveredNodeIds, setHoveredNodeIds] = useState<string[]>([]);
  const [editorReady, setEditorReady] = useState(false);

  const handleMount = useCallback((_: unknown, monaco: typeof import("monaco-editor")) => {
    monacoRef.current = monaco;
    monaco.editor.defineTheme("light-editor", {
      base: "vs",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": EDITOR_BG_LIGHT,
        "editor.foreground": "#18181b",
      },
    });
    monaco.editor.defineTheme("dark-editor", {
      base: "vs-dark",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": EDITOR_BG_DARK,
        "editor.foreground": "#f4f4f5",
      },
    });
    monaco.editor.setTheme(isDark ? "dark-editor" : "light-editor");
  }, [isDark]);

  // Update Monaco theme when isDark changes after mount
  useEffect(() => {
    const monaco = monacoRef.current;
    if (!monaco) return;
    monaco.editor.setTheme(isDark ? "dark-editor" : "light-editor");
  }, [isDark]);

  const operatorDecorationIdsRef = useRef<string[]>([]);
  const getEditor = useCallback(() => editorRef.current, []);

  useEffect(() => {
    const monaco = monacoRef.current;
    const ed = getEditor();
    if (!monaco || !ed) return;
    const model = ed.getModel();
    if (!model) return;

    const ids = ed.deltaDecorations(
      decorationIdsRef.current,
      nodeRanges.map((nr) => {
        const r = nr.source_range;
        const isHovered = hoveredNodeIds.includes(nr.id);
        const isSelected =
          selectedNodeId === nr.id || highlightedNodeIds.includes(nr.id);
        const isSempipes = sempipesNodeIds.includes(nr.id);
        const options = isSelected
          ? isSempipes
            ? SELECTED_SEMPIPES_DECORATION
            : SELECTED_DECORATION
          : isHovered
            ? HOVER_DECORATION
            : decorationForType(nr.type, isSempipes);
        return {
          range: new monaco.Range(r.start_line, r.start_column, r.end_line, r.end_column),
          options,
        };
      })
    );
    decorationIdsRef.current = ids;
  }, [nodeRanges, getEditor, hoveredNodeIds, selectedNodeId, highlightedNodeIds, sempipesNodeIds]);

  // ─── Code–graph sync: cursor/mouse → highlight nodes ───
  const findNodesAtPosition = useCallback(
    (line: number, column: number): string[] => {
      return nodeRanges
        .filter((nr) => {
          const r = nr.source_range;
          if (line < r.start_line || line > r.end_line) return false;
          if (line === r.start_line && column < r.start_column) return false;
          if (line === r.end_line && column > r.end_column) return false;
          return true;
        })
        .map((nr) => nr.id);
    },
    [nodeRanges]
  );

  useEffect(() => {
    const ed = getEditor();
    if (!ed || !onHighlightNodes) return;
    const disposable = ed.onDidChangeCursorPosition((e) => {
      // Cursor move: update highlighted nodes
      const nodes = findNodesAtPosition(e.position.lineNumber, e.position.column);
      onHighlightNodes(nodes);
    });
    return () => disposable.dispose();
  }, [getEditor, onHighlightNodes, findNodesAtPosition]);

  useEffect(() => {
    const ed = getEditor();
    if (!ed || !onHighlightNodes) return;
    const disposable = ed.onMouseDown((e) => {
      // Click in editor: highlight and select node
      const target = e.target;
      if (target?.position) {
        const nodes = findNodesAtPosition(target.position.lineNumber, target.position.column);
        onHighlightNodes(nodes);
        onSelectNode?.(nodes[0] ?? null);
      }
    });
    return () => disposable.dispose();
  }, [getEditor, onHighlightNodes, onSelectNode, findNodesAtPosition]);

  useEffect(() => {
    const ed = getEditor();
    if (!ed) return;
    const disposable = ed.onMouseMove((e) => {
      // Hover: show hover decoration
      const target = e.target;
      if (target?.position) {
        const nodes = findNodesAtPosition(target.position.lineNumber, target.position.column);
        setHoveredNodeIds(nodes);
      } else {
        setHoveredNodeIds([]);
      }
    });
    return () => disposable.dispose();
  }, [getEditor, findNodesAtPosition]);

  useEffect(() => {
    const ed = getEditor();
    if (!ed) return;
    const disposable = ed.onMouseLeave(() => setHoveredNodeIds([]));
    return () => disposable.dispose();
  }, [getEditor]);

  // ─── Graph→code: when graph node is clicked, move editor cursor to that node's range ───
  useEffect(() => {
    if (!focusNodeId || !editorReady) return;
    const ed = getEditor();
    const monaco = monacoRef.current;
    if (!ed || !monaco) return;
    const nr = nodeRanges.find((r) => r.id === focusNodeId);
    if (!nr) return;

    const { start_line, start_column, end_line, end_column } = nr.source_range;
    const range = new monaco.Range(start_line, start_column, end_line, end_column);

    ed.setPosition({ lineNumber: start_line, column: start_column });
    ed.setSelection(range);
    ed.revealRangeInCenter(range);

    // Defer focus so it runs after the click event; otherwise the graph panel keeps focus
    const t = setTimeout(() => {
      ed.focus();
      onFocusApplied?.();
    }, 0);
    return () => clearTimeout(t);
  }, [focusNodeId, editorReady, getEditor, nodeRanges, onFocusApplied]);


  const editorBg = isDark ? EDITOR_BG_DARK : EDITOR_BG_LIGHT;

  // ─── Active Operator Highlight & Scroll ───
  useEffect(() => {
    const ed = getEditor();
    const monaco = monacoRef.current;
    if (!ed || !monaco || !activeOperatorName) {
      if (ed && operatorDecorationIdsRef.current.length > 0) {
        operatorDecorationIdsRef.current = ed.deltaDecorations(operatorDecorationIdsRef.current, []);
      }
      return;
    }
    const model = ed.getModel();
    if (!model) return;

    // We want to find the operator definition. Usually it looks like: name="<activeOperatorName>" or name='...'
    // Then we find the nearest preceding `sem_` function call to highlight it.

    // 1. Find the name argument
    const matches = model.findMatches(
      `name=["']${activeOperatorName}["']`,
      false, // searchOnlyEditableRange
      true, // isRegex
      false, // matchCase
      null, // wordSeparators
      true // captureMatches
    );

    if (matches.length > 0) {
      const matchRange = matches[0].range;

      // Let's search backwards from this match to find the actual method call, e.g., 'sem_gen_features'
      // We'll search for 'sem_[a-zA-Z_]+'
      const methodMatches = model.findMatches(
        `sem_[a-zA-Z_]+`,
        false,
        true,
        false,
        null,
        false
      );

      // Find the closest method match that is BEFORE or ON the line where name="..." is.
      let bestMethodMatch = null;
      for (const m of methodMatches) {
        if (m.range.startLineNumber <= matchRange.startLineNumber) {
          if (!bestMethodMatch || (m.range.startLineNumber > bestMethodMatch.range.startLineNumber) ||
            (m.range.startLineNumber === bestMethodMatch.range.startLineNumber && m.range.startColumn > bestMethodMatch.range.startColumn)) {
            bestMethodMatch = m;
          }
        }
      }

      const rangeToHighlight = bestMethodMatch ? bestMethodMatch.range : matchRange;

      operatorDecorationIdsRef.current = ed.deltaDecorations(
        operatorDecorationIdsRef.current,
        [
          {
            range: rangeToHighlight,
            options: {
              isWholeLine: false,
              className: "sempipe-active-operator-highlight",
            },
          }
        ]
      );

      // Scroll to show it
      ed.revealRangeInCenterIfOutsideViewport(rangeToHighlight);
    } else {
      operatorDecorationIdsRef.current = ed.deltaDecorations(operatorDecorationIdsRef.current, []);
    }
  }, [activeOperatorName, getEditor, editorReady]);


  return (
    <div
      className="h-full w-full rounded-lg border border-slate-200 dark:border-zinc-700 overflow-hidden"
      style={{ backgroundColor: editorBg }}
      data-testid="input-editor"
      data-highlighted={highlightedNodeIds.join(",") || undefined}
    >
      <style>{isDark ? `
        /* as_X / as_y (input) — blue, dark variant */
        .sempipe-input-decoration {
          background-color: rgba(59, 130, 246, 0.22);
          border-radius: 3px;
        }
        /* Sempipes operators — green, dark variant */
        .sempipe-operator-decoration {
          background-color: rgba(34, 197, 94, 0.18);
          border-radius: 3px;
        }
        /* Regular operators — no color */
        .sempipe-regular-operator-decoration {
          background-color: transparent;
          border-radius: 3px;
        }
        /* Hover — teal, dark variant */
        .sempipe-hover-decoration {
          background-color: rgba(16, 185, 129, 0.35);
          border-radius: 3px;
        }
        /* Selected non-sempipes — amber, dark variant */
        .sempipe-selected-decoration {
          background-color: rgba(251, 191, 36, 0.3);
          border: 2px solid rgb(251, 191, 36);
          border-radius: 4px;
          box-shadow: 0 0 0 1px rgba(251, 191, 36, 0.25);
        }
        /* Selected sempipes — pink, dark variant */
        .sempipe-selected-sempipes-decoration {
          background-color: rgba(236, 72, 153, 0.25);
          border: 2px solid rgb(244, 114, 182);
          border-radius: 4px;
          box-shadow: 0 0 0 1px rgba(244, 114, 182, 0.25);
        }
        .sempipe-element-margin { display: none; }
        /* Active operator highlight (from optimizer) */
        .sempipe-active-operator-highlight {
          background-color: rgba(251, 146, 60, 0.3); /* orange-400 */
          border-bottom: 2px solid rgb(249, 115, 22);
        }
      ` : `
        /* as_X / as_y (input) — one distinct colour */
        .sempipe-input-decoration {
          background-color: rgba(59, 130, 246, 0.14);
          border-radius: 3px;
        }
        /* Sempipes operators (sem_fillna, sem_gen_features, etc.) — green */
        .sempipe-operator-decoration {
          background-color: rgba(34, 197, 94, 0.14);
          border-radius: 3px;
        }
        /* Regular operators (skb.subsample, etc.) — no color/white */
        .sempipe-regular-operator-decoration {
          background-color: transparent;
          border-radius: 3px;
        }
        /* Darker on hover to mark middle panel */
        .sempipe-hover-decoration {
          background-color: rgba(16, 185, 129, 0.28);
          border-radius: 3px;
        }
        /* Selected non-sempipes graph element highlighted in code — yellow */
        .sempipe-selected-decoration {
          background-color: rgba(251, 191, 36, 0.45);
          border: 2px solid rgb(245, 158, 11);
          border-radius: 4px;
          box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.3);
        }
        /* Selected sempipes graph element highlighted in code — pink */
        .sempipe-selected-sempipes-decoration {
          background-color: rgba(252, 231, 243, 0.9);
          border: 2px solid rgb(236, 72, 153);
          border-radius: 4px;
          box-shadow: 0 0 0 1px rgba(236, 72, 153, 0.3);
        }
        .sempipe-element-margin { display: none; }
        /* Active operator highlight (from optimizer) */
        .sempipe-active-operator-highlight {
          background-color: rgba(251, 146, 60, 0.3); /* orange-400 */
          border-bottom: 2px solid rgb(249, 115, 22);
        }
      `}</style>
      <Editor
        height="100%"
        defaultLanguage="python"
        language="python"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={(_, monaco) => {
          handleMount(_, monaco);
          editorRef.current = _;
          setEditorReady(true);
        }}
        theme={isDark ? "dark-editor" : "light-editor"}
        options={{
          readOnly: disabled,
          minimap: { enabled: false },
          fontSize: 11,
          fontFamily: "ui-monospace, monospace",
          padding: { top: 8 },
          scrollBeyondLastLine: false,
          wordWrap: isExpanded ? "off" : "on",
          wrappingStrategy: "advanced",
          lineNumbersMinChars: 3,
          glyphMargin: false,
        }}
      />
    </div>
  );
}
