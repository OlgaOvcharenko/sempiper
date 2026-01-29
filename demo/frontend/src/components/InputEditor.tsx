import { useRef, useCallback } from "react";
import Editor from "@monaco-editor/react";

interface InputEditorProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function InputEditor({ value, onChange, disabled }: InputEditorProps) {
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]["onMount"]>>[1] | null>(null);

  const handleMount = useCallback(
    (_: unknown, monaco: Parameters<NonNullable<Parameters<typeof Editor>[0]["onMount"]>>[1]) => {
      editorRef.current = monaco;
    },
    []
  );

  return (
    <div className="h-full w-full rounded-lg border border-slate-700 bg-slate-900 overflow-hidden">
      <Editor
        height="100%"
        defaultLanguage="sql"
        language="sql"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={handleMount}
        theme="vs-dark"
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
