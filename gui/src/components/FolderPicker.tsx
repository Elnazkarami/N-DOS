import { useCallback, useEffect, useState } from "react";
import { api, formatBytes, type BrowseResult } from "@/lib/api";

/**
 * Choosing a folder on this machine.
 *
 * A browser will not hand a program a filesystem path, so the browsing happens
 * on the server side and this shows what it found.
 */
export function FolderPicker({
  onChoose,
  chosen,
  suffix,
  onChooseFile,
  chooseLabel = "use this folder",
}: {
  onChoose: (path: string) => void;
  chosen?: string | null;
  /** Also offer the files ending in this, e.g. ".json". */
  suffix?: string;
  onChooseFile?: (path: string, name: string) => void;
  chooseLabel?: string;
}) {
  const [here, setHere] = useState<BrowseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const go = useCallback(
    async (path?: string) => {
      setBusy(true);
      setError(null);
      try {
        setHere(await api.browse(path, suffix));
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : String(problem));
      } finally {
        setBusy(false);
      }
    },
    [suffix],
  );

  useEffect(() => {
    void go();
  }, [go]);

  if (error) {
    return (
      <div className="riso-panel px-5 py-4">
        <p className="font-mono text-[11px] uppercase tracking-widest text-magenta">
          cannot browse
        </p>
        <p className="mt-2 text-sm">{error}</p>
      </div>
    );
  }

  return (
    <div className="riso-panel">
      <div className="flex items-center justify-between gap-3 border-b border-ink/20 px-4 py-2.5">
        <span className="truncate font-mono text-[11px]" title={here?.path}>
          {here?.path ?? "…"}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          {here?.parent && (
            <button
              type="button"
              onClick={() => void go(here.parent ?? undefined)}
              className="rounded-sm border border-ink/30 px-2 py-0.5 font-mono text-[11px] hover:bg-ink hover:text-cream"
            >
              up
            </button>
          )}
          {here && (
            <button
              type="button"
              onClick={() => onChoose(here.path)}
              className="rounded-sm bg-purple px-2.5 py-0.5 font-mono text-[11px] text-cream"
            >
              {chooseLabel}
            </button>
          )}
        </div>
      </div>

      <div className="max-h-64 overflow-y-auto">
        {busy && <p className="px-4 py-3 font-mono text-[11px]">reading…</p>}
        {!busy && here?.directories.length === 0 && (here?.files ?? []).length === 0 && (
          <p className="px-4 py-3 font-mono text-[11px] text-ink/60">
            nothing to choose here · {here.file_count} files
          </p>
        )}
        {!busy &&
          here?.directories.map((directory) => (
            <button
              key={directory.path}
              type="button"
              onClick={() => void go(directory.path)}
              className="flex w-full items-center gap-2 px-4 py-1.5 text-left font-mono text-[12px] hover:bg-ink/5"
            >
              <span aria-hidden="true">/</span>
              <span className="truncate">{directory.name}</span>
            </button>
          ))}

        {!busy &&
          onChooseFile &&
          here?.files?.map((file) => (
            <button
              key={file.path}
              type="button"
              onClick={() => onChooseFile(file.path, file.name)}
              className="flex w-full items-center gap-2 px-4 py-1.5 text-left font-mono text-[12px] hover:bg-purple/10"
            >
              <span aria-hidden="true" className="text-purple">
                ·
              </span>
              <span className="truncate">{file.name}</span>
              <span className="ml-auto shrink-0 text-ink/40">{formatBytes(file.bytes)}</span>
            </button>
          ))}
      </div>

      {here?.is_project && (
        <p className="border-t border-ink/20 px-4 py-2 font-mono text-[11px] text-ink">
          this looks like an N-DOS project
        </p>
      )}
      {chosen && (
        <p className="border-t border-ink/20 px-4 py-2 font-mono text-[11px]">
          chosen: <span className="text-purple">{chosen}</span>
        </p>
      )}
    </div>
  );
}
