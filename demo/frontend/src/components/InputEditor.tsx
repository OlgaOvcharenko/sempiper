import { useRef, useCallback } from "react";
import Editor from "@monaco-editor/react";

interface InputEditorProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

const EDITOR_BG = "#18181b"; /* zinc-900 — matches panel dark */

export function InputEditor({ value, onChange, disabled }: InputEditorProps) {
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]["onMount"]>>[1] | null>(null);

  const handleMount = useCallback(
    (_: unknown, monaco: Parameters<NonNullable<Parameters<typeof Editor>[0]["onMount"]>>[1]) => {
      editorRef.current = monaco;
      monaco.editor.defineTheme("dark-editor", {
        base: "vs-dark",
        inherit: true,
        rules: [],
        colors: {
          "editor.background": EDITOR_BG,
          "editor.foreground": "#e4e4e7",
        },
      });
      monaco.editor.setTheme("dark-editor");
    },
    []
  );

  return (
    <div
      className="h-full w-full rounded-lg border border-zinc-800 overflow-hidden"
      style={{ backgroundColor: EDITOR_BG }}
    >
      <Editor
        height="100%"
        defaultLanguage="python"
        language="python"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={handleMount}
        theme="dark-editor"
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
