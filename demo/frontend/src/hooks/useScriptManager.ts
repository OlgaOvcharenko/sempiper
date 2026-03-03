import { useState, useEffect, useRef, useCallback } from "react";
import {
  listPipelineScripts,
  getPipelineScriptContent,
  type PipelineScriptEntry,
} from "../api/client";

export interface UseScriptManagerReturn {
  pipelineScripts: PipelineScriptEntry[];
  pipelineCode: string;
  loadedScriptId: string | null;
  setPipelineCode: (code: string) => void;
  handleLoadScript: (id: string) => Promise<void>;
  handleFileUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
}

/**
 * Manages pipeline script loading, the active code, and the loaded script ID.
 *
 * Options are treated as initialization values and should be stable across renders
 * (pass constants or values that don't change after mount).
 */
export function useScriptManager(opts: {
  mode: "normal" | "optimizer";
  /** Code to show before any script is loaded, and for synthetic entries. */
  initialCode?: string;
  /** ID of the script to load by default (falls back to first available script). */
  defaultScriptId?: string;
  /** Extra entries prepended to the script list (e.g. a "— New —" entry). */
  prependEntries?: PipelineScriptEntry[];
  /** If loading this ID, set code to initialCode instead of fetching from backend. */
  syntheticNewId?: string;
}): UseScriptManagerReturn {
  const [pipelineScripts, setPipelineScripts] = useState<PipelineScriptEntry[]>([]);
  const [pipelineCode, setPipelineCode] = useState(opts.initialCode ?? "");
  const [loadedScriptId, setLoadedScriptId] = useState<string | null>(
    opts.defaultScriptId ?? null
  );

  // Capture initialization opts in a ref so the mount effect closes over stable values.
  const initRef = useRef(opts);

  useEffect(() => {
    const {
      mode,
      initialCode = "",
      defaultScriptId,
      prependEntries = [],
      syntheticNewId,
    } = initRef.current;

    let cancelled = false;

    listPipelineScripts(mode)
      .then(({ scripts }) => {
        if (cancelled) return;
        const allScripts: PipelineScriptEntry[] = [...prependEntries, ...(scripts ?? [])];
        setPipelineScripts(allScripts);

        // Choose which script to open by default.
        // Prefer defaultScriptId if it exists in server scripts; otherwise first server script;
        // otherwise first prepended entry (e.g. the synthetic "new" entry).
        const serverScripts = scripts ?? [];
        const effectiveDefaultId =
          defaultScriptId && serverScripts.some((s) => s.id === defaultScriptId)
            ? defaultScriptId
            : serverScripts[0]?.id ?? prependEntries[0]?.id ?? null;

        if (effectiveDefaultId) {
          setLoadedScriptId(effectiveDefaultId);
          if (syntheticNewId && effectiveDefaultId === syntheticNewId) {
            if (!cancelled) setPipelineCode(initialCode);
          } else {
            getPipelineScriptContent(effectiveDefaultId, mode)
              .then(({ content }) => {
                if (!cancelled) setPipelineCode(content);
              })
              .catch(() => {
                if (!cancelled)
                  setPipelineCode(`# Failed to load script: ${effectiveDefaultId}\n`);
              });
          }
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (prependEntries.length > 0) {
          // Degrade gracefully: show the prepended synthetic entries and initial code.
          setPipelineScripts(prependEntries);
          setLoadedScriptId(prependEntries[0].id);
          setPipelineCode(initialCode);
        } else {
          setPipelineCode(
            `# Failed to load scripts. Is the backend running?\n${err}`
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, []); // intentionally run only once on mount

  const handleLoadScript = useCallback(async (id: string) => {
    const { mode, initialCode = "", syntheticNewId } = initRef.current;
    setLoadedScriptId(id);
    if (syntheticNewId && id === syntheticNewId) {
      setPipelineCode(initialCode);
      return;
    }
    try {
      const { content } = await getPipelineScriptContent(id, mode);
      setPipelineCode(content);
    } catch {
      setPipelineCode(`# Failed to load script: ${id}\n`);
    }
  }, []);

  const handleFileUpload = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result;
        if (typeof content === "string") {
          setPipelineCode(content);
          setLoadedScriptId(null);
        }
      };
      reader.readAsText(file);
      // Reset so the same file can be re-uploaded
      event.target.value = "";
    },
    []
  );

  return {
    pipelineScripts,
    pipelineCode,
    loadedScriptId,
    setPipelineCode,
    handleLoadScript,
    handleFileUpload,
  };
}
