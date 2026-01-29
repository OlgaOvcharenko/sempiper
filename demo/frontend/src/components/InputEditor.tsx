import { useRef, useCallback, useEffect } from "react";
import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";

interface NodeRange {
  id: string;
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
}

const EDITOR_BG = "#ffffff";
const DECORATION_OPTIONS: editor.IModelDecorationOptions = {
  isWholeLine: false,
  className: "sempipe-element-decoration",
  marginClassName: "sempipe-element-margin",
};

export function InputEditor({
  value,
  onChange,
  disabled,
  nodeRanges = [],
  onHighlightNodes,
}: InputEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof import("monaco-editor") | null>(null);
  const decorationIdsRef = useRef<string[]>([]);

  const handleMount = useCallback(
    (
      _: unknown,
      monaco: typeof import("monaco-editor")
    ) => {
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
    },
    []
  );

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
        return {
          range: new monaco.Range(r.start_line, r.start_column, r.end_line, r.end_column),
          options: DECORATION_OPTIONS,
        };
      })
    );
    decorationIdsRef.current = ids;
  }, [nodeRanges, getEditor]);

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
      }
    });
    return () => disposable.dispose();
  }, [getEditor, onHighlightNodes, findNodesAtPosition]);

  return (
    <div
      className="h-full w-full rounded-lg border border-slate-200 overflow-hidden bg-white"
      style={{ backgroundColor: EDITOR_BG }}
    >
      <style>{`
        .sempipe-element-decoration {
          background-color: rgba(16, 185, 129, 0.12);
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
          fontSize: 13,
          fontFamily: "ui-monospace, monospace",
          padding: { top: 12 },
          scrollBeyondLastLine: false,
        }}
      />
    </div>
  );
}
