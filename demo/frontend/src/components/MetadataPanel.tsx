import type { GenerateMetadata } from "../api/client";

interface MetadataPanelProps {
  compilationTimeMs: number | null;
  metadata: GenerateMetadata | null;
}

export function MetadataPanel({ compilationTimeMs, metadata }: MetadataPanelProps) {
  if (compilationTimeMs == null && !metadata) return null;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-3">
      <h3 className="text-sm font-medium text-slate-300">Generation info</h3>
      {compilationTimeMs != null && (
        <p className="text-sm text-slate-400">
          <span className="text-emerald-500 font-medium">{compilationTimeMs.toFixed(1)}</span> ms
          total
        </p>
      )}
      {metadata?.optimizations_applied && metadata.optimizations_applied.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Optimizations</p>
          <ul className="text-sm text-slate-400 flex flex-wrap gap-2">
            {metadata.optimizations_applied.map((o) => (
              <li key={o} className="px-2 py-0.5 rounded bg-slate-700/80 text-slate-300">
                {o}
              </li>
            ))}
          </ul>
        </div>
      )}
      {metadata?.ir_size_bytes != null && metadata.ir_size_bytes > 0 && (
        <p className="text-sm text-slate-400">
          IR size: <span className="text-slate-300">{metadata.ir_size_bytes}</span> bytes
        </p>
      )}
      {metadata?.stages && metadata.stages.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Stages</p>
          <ul className="space-y-1">
            {metadata.stages.map((s) => (
              <li key={s.name} className="flex justify-between text-sm">
                <span className="text-slate-400">{s.name}</span>
                <span className="text-emerald-500/90 tabular-nums">{s.time_ms.toFixed(1)} ms</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
