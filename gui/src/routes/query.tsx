import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Shell, ProvenanceTag } from "@/components/Shell";
import { JsonDrop } from "@/components/JsonDrop";
import {
  formatBytes,
  ManifestError,
  parseSessionMetadata,
  sessionFacets,
  type SessionMetadata,
} from "@/lib/ndos-manifest";

export const Route = createFileRoute("/query")({
  head: () => ({
    meta: [
      { title: "Session query — N-DOS" },
      {
        name: "description",
        content:
          "Filter linked N-DOS sessions by species, target region, session type and any declared field, in the browser.",
      },
      { property: "og:title", content: "Session query — N-DOS" },
      {
        property: "og:description",
        content: "Open linked.json from ndos table check and filter sessions visually.",
      },
    ],
  }),
  component: QueryPage,
});

function QueryPage() {
  const [data, setData] = useState<SessionMetadata | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<{ key: string; value: string }[]>([]);
  const [draft, setDraft] = useState<{ key: string; value: string }>({ key: "", value: "" });

  const rows = useMemo(() => {
    if (!data) return [];
    return data.sessions.map((s) => ({ session: s, facets: sessionFacets(s) }));
  }, [data]);

  const facetKeys = useMemo(() => {
    const keys = new Set<string>();
    rows.forEach((r) => Object.keys(r.facets).forEach((k) => keys.add(k)));
    return [...keys].sort();
  }, [rows]);

  const valuesForKey = useMemo(() => {
    const set = new Set<string>();
    if (draft.key) rows.forEach((r) => r.facets[draft.key] && set.add(r.facets[draft.key]!.value));
    return [...set].sort();
  }, [rows, draft.key]);

  const filtered = rows.filter((r) =>
    filters.every((f) => (r.facets[f.key]?.value ?? "").toLowerCase() === f.value.toLowerCase()),
  );

  const load = (text: string, fileName: string) => {
    try {
      setData(parseSessionMetadata(text));
      setName(fileName);
      setError(null);
      setFilters([]);
    } catch (e) {
      setData(null);
      setName(null);
      setError(e instanceof ManifestError ? e.message : "Could not read that file.");
    }
  };

  return (
    <Shell>
      <div className="px-6 py-10">
        <h1 className="font-display text-4xl leading-tight tracking-tight">Session query</h1>
        <p className="mt-3 max-w-2xl leading-relaxed">
          Produce a linked file with{" "}
          <code className="font-mono text-[13px]">python3 ndos.py table check ./metadata --emit linked.json</code>{" "}
          and open it here. Filters work on declared and computed fields, and each value keeps the
          label for how it is known.
        </p>

        <div className="mt-6 max-w-2xl">
          <JsonDrop
            label="linked.json"
            hint="ndos table check output · metadata_version 0.1"
            onText={load}
            loadedName={name}
            error={error}
          />
        </div>

        {data ? (
          <div className="mt-8 riso-panel overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b-2 border-ink bg-paper/60 p-4">
              {filters.map((f) => (
                <button
                  key={`${f.key}=${f.value}`}
                  onClick={() => setFilters(filters.filter((x) => x !== f))}
                  className="rounded-sm bg-ink px-2.5 py-1 font-mono text-[11px] text-cream"
                >
                  {f.key}: {f.value} ×
                </button>
              ))}
              <select
                value={draft.key}
                onChange={(e) => setDraft({ key: e.target.value, value: "" })}
                className="rounded-sm border border-ink/40 bg-cream px-2 py-1 font-mono text-[11px]"
              >
                <option value="">field…</option>
                {facetKeys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
              <select
                value={draft.value}
                disabled={!draft.key}
                onChange={(e) => {
                  const value = e.target.value;
                  if (value && draft.key) {
                    setFilters([...filters, { key: draft.key, value }]);
                    setDraft({ key: "", value: "" });
                  }
                }}
                className="rounded-sm border border-ink/40 bg-cream px-2 py-1 font-mono text-[11px]"
              >
                <option value="">value…</option>
                {valuesForKey.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
              <span className="ml-auto font-mono text-[11px] text-ink/60">
                {filtered.length} of {rows.length} sessions
              </span>
            </div>

            <ul className="divide-y divide-ink/15">
              {filtered.map(({ session, facets }) => (
                <li key={session.ndos_id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-3 font-mono text-[13px]">
                    <span className="text-ink/40">{session.ndos_id}</span>
                    <span className="flex-1 truncate">{session.observed?.path}</span>
                    <span className="text-ink/50">
                      {session.observed?.file_count ?? 0} files ·{" "}
                      {formatBytes(session.observed?.bytes ?? 0)}
                    </span>
                    {session.observed?.match ? (
                      <ProvenanceTag provenance="guessed" suffix={session.observed.match} />
                    ) : null}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries(facets).map(([k, v]) => (
                      <span
                        key={k}
                        className={`rounded-sm border px-2 py-0.5 font-mono text-[11px] ${
                          v.provenance === "computed"
                            ? "border-purple/40 bg-purple/15"
                            : v.provenance === "guessed"
                              ? "border-magenta/40 bg-magenta/15"
                              : "border-ink/25 bg-cream"
                        }`}
                        title={`${v.provenance}`}
                      >
                        {k}: {v.value}
                      </span>
                    ))}
                  </div>
                </li>
              ))}
              {filtered.length === 0 ? (
                <li className="px-4 py-4 font-mono text-[12px] text-ink/60">
                  No session matches every filter.
                </li>
              ) : null}
            </ul>
          </div>
        ) : null}
      </div>
    </Shell>
  );
}
