import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Shell } from "@/components/Shell";
import { FolderPicker } from "@/components/FolderPicker";
import { api, isLocal, NotLocalError, type QueryResult, type QueryRow } from "@/lib/api";

export const Route = createFileRoute("/query")({
  head: () => ({
    meta: [
      { title: "Session query — N-DOS" },
      {
        name: "description",
        content:
          "Build a cohort from linked N-DOS sessions, and see which sessions were excluded, which matched, and which simply cannot be ruled out.",
      },
      { property: "og:title", content: "Session query — N-DOS" },
      {
        property: "og:description",
        content: "Cohort queries that never present a missing answer as a negative one.",
      },
    ],
  }),
  component: QueryPage,
});

function QueryPage() {
  const local = isLocal();
  const [source, setSource] = useState<{ path: string; label: string } | null>(null);
  const [constraints, setConstraints] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (next: string[], from = source) => {
    if (!from) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.query({ path: from.path }, next));
    } catch (problem) {
      setResult(null);
      setError(
        problem instanceof NotLocalError
          ? problem.message
          : problem instanceof Error
            ? problem.message
            : String(problem),
      );
    } finally {
      setBusy(false);
    }
  };

  const add = () => {
    const text = draft.trim();
    if (!text || constraints.includes(text)) return;
    const next = [...constraints, text];
    setConstraints(next);
    setDraft("");
    void run(next);
  };

  const drop = (text: string) => {
    const next = constraints.filter((c) => c !== text);
    setConstraints(next);
    void run(next);
  };

  return (
    <Shell>
      <div className="px-6 py-10">
        <h1 className="font-display text-4xl leading-tight tracking-tight">Session query</h1>
        <p className="mt-3 max-w-2xl leading-relaxed">
          Build a cohort from a project's metadata. Every session is placed in one of three
          groups, because a session that never recorded a species is not a session known not to
          be a mouse — and a cohort that treats those as the same thing is quietly biased.
        </p>

        {!local ? (
          <NotServed />
        ) : (
          <>
            <div className="mt-6 max-w-2xl">
              <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-ink/60">
                a project, or a linked.json
              </p>
              <FolderPicker
                suffix=".json"
                chosen={source?.label ?? null}
                chooseLabel="query this project"
                onChoose={(path) => {
                  const chosen = { path, label: path };
                  setSource(chosen);
                  void run(constraints, chosen);
                }}
                onChooseFile={(path, name) => {
                  const chosen = { path, label: name };
                  setSource(chosen);
                  void run(constraints, chosen);
                }}
              />
              <p className="mt-2 font-mono text-[11px] text-ink/50">
                Metadata is linked in memory. Nothing is written.
              </p>
            </div>

            {source && (
              <div className="mt-6 max-w-2xl">
                <div className="flex flex-wrap items-center gap-2">
                  {constraints.map((c) => (
                    <button
                      key={c}
                      onClick={() => drop(c)}
                      className="rounded-sm bg-ink px-2.5 py-1 font-mono text-[11px] text-cream"
                    >
                      {c} ×
                    </button>
                  ))}
                  <input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") add();
                    }}
                    placeholder="species=mouse"
                    className="min-w-[14rem] flex-1 rounded-sm border border-ink/40 bg-cream px-2 py-1 font-mono text-[12px]"
                  />
                  <button
                    onClick={add}
                    disabled={!draft.trim() || busy}
                    className="rounded-sm bg-purple px-3 py-1 font-mono text-[11px] text-cream disabled:opacity-40"
                  >
                    {busy ? "running…" : "add"}
                  </button>
                </div>
                <p className="mt-2 font-mono text-[11px] text-ink/50">
                  field=value, field~contains, field&gt;=number, field:unknown
                </p>
              </div>
            )}

            {error && (
              <div className="mt-6 max-w-2xl riso-panel px-5 py-4">
                <p className="font-mono text-[11px] uppercase tracking-widest text-magenta">
                  that query did not run
                </p>
                <p className="mt-2 text-sm">{error}</p>
              </div>
            )}

            {result && <Outcome result={result} />}
          </>
        )}
      </div>
    </Shell>
  );
}

function NotServed() {
  return (
    <div className="mt-6 max-w-2xl riso-panel px-5 py-4">
      <p className="font-mono text-[11px] uppercase tracking-widest text-magenta">
        not running on your machine
      </p>
      <p className="mt-2 text-sm leading-relaxed">
        Querying runs against the same code the command line uses, on the machine holding the
        data. This page is not being served by it.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-sm bg-ink/5 p-3 font-mono text-[12px]">
        ndos gui
      </pre>
    </div>
  );
}

/**
 * The three outcomes, given equal weight.
 *
 * "Cannot be ruled out" is deliberately not hidden behind a disclosure: it is
 * the group a person needs to see before they believe a cohort is complete.
 */
function Outcome({ result }: { result: QueryResult }) {
  const { counts } = result;
  return (
    <div className="mt-8 space-y-6">
      <div className="flex flex-wrap gap-3">
        <Count label="matched" value={counts.matched} tone="border-ink bg-cream" />
        <Count
          label="cannot be ruled out"
          value={counts.unresolved}
          tone="border-magenta/50 bg-magenta/10"
        />
        <Count label="excluded" value={counts.excluded} tone="border-ink/30 bg-ink/5" />
        <Count label="considered" value={counts.considered} tone="border-ink/20 bg-transparent" />
      </div>

      {result.diagnosis.length > 0 && (
        <div className="riso-panel px-5 py-4">
          {result.diagnosis.map((note) => (
            <p key={note} className="text-sm leading-relaxed">
              {note}
            </p>
          ))}
        </div>
      )}

      <Group
        title="Matched"
        hint="every constraint satisfied by recorded evidence"
        rows={result.matched}
      />
      <Group
        title="Cannot be ruled out"
        hint="nothing contradicts the query; something was never recorded"
        rows={result.unresolved}
        emphasis
      />
      <Group
        title="Excluded"
        hint="recorded evidence contradicts the query"
        rows={result.excluded}
      />
    </div>
  );
}

function Count({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`rounded-sm border-2 px-4 py-2 ${tone}`}>
      <div className="font-display text-2xl leading-none">{value}</div>
      <div className="mt-1 font-mono text-[11px] uppercase tracking-widest text-ink/60">
        {label}
      </div>
    </div>
  );
}

function Group({
  title,
  hint,
  rows,
  emphasis,
}: {
  title: string;
  hint: string;
  rows: QueryRow[];
  emphasis?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <div className={`riso-panel overflow-hidden ${emphasis ? "border-magenta/50" : ""}`}>
      <div className="border-b-2 border-ink/20 bg-paper/60 px-4 py-3">
        <h2 className="font-display text-xl leading-none">
          {title}{" "}
          <span className="font-mono text-[12px] text-ink/50">{rows.length}</span>
        </h2>
        <p className="mt-1 font-mono text-[11px] text-ink/60">{hint}</p>
      </div>
      <ul className="divide-y divide-ink/15">
        {rows.slice(0, 200).map((row) => (
          <li key={row.ndos_id || row.path} className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-3 font-mono text-[13px]">
              <span className="text-ink/40">{row.ndos_id}</span>
              <span className="flex-1 truncate">{row.path}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {row.evidence.map((e, i) => (
                <span
                  key={`${e.constraint}-${i}`}
                  className="rounded-sm border border-ink/25 bg-cream px-2 py-0.5 font-mono text-[11px]"
                  title={e.field ? `${e.field}: ${e.value ?? ""}` : undefined}
                >
                  {e.constraint} ✓
                </span>
              ))}
              {row.missing.map((e, i) => (
                <span
                  key={`missing-${e.constraint}-${i}`}
                  className="rounded-sm border border-magenta/40 bg-magenta/15 px-2 py-0.5 font-mono text-[11px]"
                  title={e.reason}
                >
                  {e.constraint} — not recorded
                </span>
              ))}
              {row.failed.map((c) => (
                <span
                  key={`failed-${c}`}
                  className="rounded-sm border border-ink/30 bg-ink/10 px-2 py-0.5 font-mono text-[11px] line-through"
                >
                  {c}
                </span>
              ))}
            </div>
          </li>
        ))}
        {rows.length > 200 && (
          <li className="px-4 py-3 font-mono text-[11px] text-ink/60">
            showing the first 200 of {rows.length}
          </li>
        )}
      </ul>
    </div>
  );
}
