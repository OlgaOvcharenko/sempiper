import { useRef, useCallback, useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";

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
  /** Whether the panel is expanded (controls word wrap). */
  isExpanded?: boolean;
}

const EDITOR_BG = "#ffffff";

/** Decoration class for as_X / as_y (input) elements. */
const INPUT_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-input-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Decoration for operators (sem_fillna, sem_gen_features, etc.) — green. */
const OPERATOR_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-operator-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Darker overlay when hovering a range (marks middle panel). */
const HOVER_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-hover-decoration",
  marginClassName: "sempipe-element-margin",
};

/** Selected graph node highlighted in code. */
const SELECTED_DECORATION: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-selected-decoration",
  marginClassName: "sempipe-element-margin",
};

function decorationForType(nodeType: string | undefined): editor.IModelDecorationOptions {
  return nodeType === "input" ? INPUT_DECORATION : OPERATOR_DECORATION;
}

export function InputEditor({
  value,
  onChange,
  disabled,
  nodeRanges = [],
  onHighlightNodes,
  onSelectNode,
  selectedNodeId = null,
  isExpanded = false,
}: InputEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof import("monaco-editor") | null>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const [hoveredNodeIds, setHoveredNodeIds] = useState<string[]>([]);

  const handleMount = useCallback((_: unknown, monaco: typeof import("monaco-editor")) => {
    monacoRef.current = monaco;
    monaco.editor.defineTheme("light-editor", {
      base: "vs",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": EDITOR_BG,
        "editor.foreground": "#18181b",
      },
    });
    monaco.editor.setTheme("light-editor");
  }, []);

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
        const isSelected = selectedNodeId === nr.id;
        const options = isSelected
          ? SELECTED_DECORATION
          : isHovered
            ? HOVER_DECORATION
            : decorationForType(nr.type);
        return {
          range: new monaco.Range(r.start_line, r.start_column, r.end_line, r.end_column),
          options,
        };
      })
    );
    decorationIdsRef.current = ids;
  }, [nodeRanges, getEditor, hoveredNodeIds, selectedNodeId]);

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
      const nodes = findNodesAtPosition(e.position.lineNumber, e.position.column);
      onHighlightNodes(nodes);
    });
    return () => disposable.dispose();
  }, [getEditor, onHighlightNodes, findNodesAtPosition]);

  useEffect(() => {
    const ed = getEditor();
    if (!ed || !onHighlightNodes) return;
    const disposable = ed.onMouseDown((e) => {
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

  return (
    <div
      className="h-full w-full rounded-lg border border-slate-200 overflow-hidden bg-white"
      style={{ backgroundColor: EDITOR_BG }}
    >
      <style>{`
        /* as_X / as_y (input) — one distinct colour */
        .sempipe-input-decoration {
          background-color: rgba(59, 130, 246, 0.14);
          border-radius: 3px;
        }
        /* Operators (sem_fillna, sem_gen_features, etc.) — green */
        .sempipe-operator-decoration {
          background-color: rgba(34, 197, 94, 0.14);
          border-radius: 3px;
        }
        /* Darker on hover to mark middle panel */
        .sempipe-hover-decoration {
          background-color: rgba(16, 185, 129, 0.28);
          border-radius: 3px;
        }
        /* Selected graph element highlighted in code */
        .sempipe-selected-decoration {
          background-color: rgba(251, 191, 36, 0.25);
          border: 1px solid rgba(251, 191, 36, 0.6);
          border-radius: 3px;
        }
        .sempipe-element-margin { display: none; }
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
        }}
        theme="light-editor"
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
