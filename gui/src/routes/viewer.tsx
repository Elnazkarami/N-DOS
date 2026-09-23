import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Shell, SectionHeading, ProvenanceTag } from "@/components/Shell";
import { JsonDrop } from "@/components/JsonDrop";
import { FolderPicker } from "@/components/FolderPicker";
import { api, isLocal } from "@/lib/api";
import {
  analyseManifest,
  formatBytes,
  parseManifest,
  ManifestError,
  type Manifest,
} from "@/lib/ndos-manifest";

export const Route = createFileRoute("/viewer")({
  head: () => ({
    meta: [
      { title: "Manifest viewer — N-DOS" },
      {
        name: "description",
        content:
          "Read an N-DOS scan manifest in the browser: composition, duplicate files, largest directories, inferred layout and what needs attention.",
      },
      { property: "og:title", content: "Manifest viewer — N-DOS" },
      {
        property: "og:description",
        content: "Open a manifest.json produced by ndos scan. Nothing is uploaded.",
      },
    ],
  }),
  component: Viewer,
});

function Viewer() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const local = isLocal();

  const analysis = useMemo(() => (manifest ? analyseManifest(manifest) : null), [manifest]);

  const load = (text: string, fileName: string) => {
    try {
      setManifest(parseManifest(text));
      setName(fileName);
      setError(null);
    } catch (e) {
      setManifest(null);
      setName(null);
      setError(e instanceof ManifestError ? e.message : "Could not read that file.");
    }
  };

  // Served by `ndos gui`, the file can simply be opened by name. Dragging a
  // file into a page is a workaround for a page that cannot reach a disk.
  const openByPath = async (path: string, fileName: string) => {
    try {
      const { document } = await api.open(path);
      load(JSON.stringify(document), fileName);
    } catch (problem) {
      setManifest(null);
      setName(null);
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  };

  return (
    <Shell>
      <div className="px-6 py-10">
        <h1 className="font-display text-4xl leading-tight tracking-tight">Manifest viewer</h1>
        <p className="mt-3 max-w-2xl leading-relaxed">
          A manifest is what <code className="font-mono text-[13px]">ndos scan</code> writes: every
          file it found, and what it could tell about each one.{" "}
          {local
            ? "Pick one from this machine, or drop it in."
            : "Drop one in — it is read inside your browser and never sent anywhere."}
        </p>

        {local && (
          <div className="mt-6 max-w-2xl">
            <FolderPicker
              suffix=".json"
              chosen={name}
              chooseLabel="browse for a manifest"
              onChoose={() => undefined}
              onChooseFile={(path, fileName) => void openByPath(path, fileName)}
            />
          </div>
        )}

        <div className="mt-6 max-w-2xl">
          <JsonDrop
            label="manifest.json"
            hint="ndos scan output · manifest_version 0.2"
            onText={load}
            loadedName={name}
            error={error}
          />
        </div>

        {manifest && analysis ? (
          <div className="mt-10 space-y-12">
            <section>
              <SectionHeading dot="cyan">What is in here</SectionHeading>
              <div className="grid gap-5 lg:grid-cols-12">
                <div className="riso-panel p-5 lg:col-span-4">
                  <p className="riso-label mb-3">Scan facts</p>
                  <dl className="space-y-2 font-mono text-[12px]">
                    <Row k="source_root" v={manifest.source_root || "—"} />
                    <Row k="generated_at" v={manifest.generated_at || "—"} />
                    <Row
                      k="generator"
                      v={`${manifest.generator.name} ${manifest.generator.version}`}
                    />
                    <Row k="files" v={String(manifest.file_count)} />
                    <Row k="total" v={formatBytes(manifest.total_bytes)} />
                    <Row k="checksums" v={manifest.checksums ? "yes" : "no"} />
                    <Row k="skipped" v={String(manifest.skipped.length)} />
                  </dl>
                  <p className="mt-3 font-mono text-[11px] text-ink/50">
                    All observed. Nothing on this page modifies your data.
                  </p>
                </div>

                <div className="riso-panel p-5 lg:col-span-4">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="riso-label">Composition</p>
                    <ProvenanceTag provenance="guessed" />
                  </div>
                  <ul className="space-y-2 font-mono text-[12px]">
                    {analysis.composition.map((c) => (
                      <li key={c.category}>
                        <div className="flex items-center justify-between">
                          <span>{c.category}</span>
                          <span className="text-ink/60">
                            {formatBytes(c.bytes)} · {c.files}
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 w-full bg-ink/10">
                          <div
                            className="h-full bg-purple"
                            style={{ width: `${Math.max(c.share * 100, 1)}%` }}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 font-mono text-[11px] text-ink/50">
                    Categories come from filename heuristics — genuinely ambiguous extensions are
                    labelled <em>ambiguous</em> rather than guessed at.
                  </p>
                </div>

                <div className="riso-panel p-5 lg:col-span-4">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="riso-label">Extensions</p>
                    <ProvenanceTag provenance="observed" />
                  </div>
                  <ul className="space-y-1.5 font-mono text-[12px]">
                    {analysis.extensions.map((e) => (
                      <li key={e.extension} className="flex items-center justify-between">
                        <span>{e.extension}</span>
                        <span className="text-ink/60">
                          {e.files} · {formatBytes(e.bytes)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            <section>
              <SectionHeading dot="magenta">Inferred folder structure</SectionHeading>
              <div className="riso-panel divide-y-2 divide-ink/15">
                {analysis.structure.length === 0 ? (
                  <p className="p-5 font-mono text-[12px]">No nested directories in this manifest.</p>
                ) : (
                  analysis.structure.map((level) => (
                    <div key={level.depth} className="p-4">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="font-mono text-[12px] text-ink/40">depth {level.depth}</span>
                        <span className="font-mono text-[13px] font-medium">
                          looks like: {level.guess}
                        </span>
                        <ProvenanceTag
                          provenance="guessed"
                          suffix={level.confidence.toFixed(2)}
                        />
                      </div>
                      <p className="mt-2 font-mono text-[12px] text-ink/60">
                        e.g. {level.examples.join(" · ")}
                      </p>
                      {level.contradictions.length ? (
                        <p className="mt-1 font-mono text-[12px] text-magenta">
                          contradicts that reading: {level.contradictions.join(" · ")}
                        </p>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            </section>

            <section className="grid gap-5 lg:grid-cols-12">
              <div className="lg:col-span-7">
                <SectionHeading dot="purple">Duplicate files</SectionHeading>
                <div className="riso-panel overflow-hidden">
                  <div className="flex items-center justify-between border-b-2 border-ink bg-paper/60 px-4 py-3 font-mono text-[12px]">
                    <span>
                      {analysis.duplicates.length} byte-identical group
                      {analysis.duplicates.length === 1 ? "" : "s"}
                    </span>
                    <span>{formatBytes(analysis.wastedBytes)} wasted</span>
                  </div>
                  {analysis.duplicates.length === 0 ? (
                    <p className="p-4 font-mono text-[12px] text-ink/60">
                      {manifest.checksums
                        ? "No byte-identical copies found."
                        : "Scanned without checksums, so duplicates cannot be detected."}
                    </p>
                  ) : (
                    <ul className="divide-y divide-ink/15">
                      {analysis.duplicates.slice(0, 12).map((d) => (
                        <li key={d.sha256} className="px-4 py-3 font-mono text-[12px]">
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-ink/40">{d.sha256.slice(0, 10)}</span>
                            <ProvenanceTag provenance="computed" suffix={`×${d.paths.length}`} />
                          </div>
                          <ul className="mt-1.5 space-y-0.5 text-ink/70">
                            {d.paths.map((p) => (
                              <li key={p} className="truncate">
                                {p}
                              </li>
                            ))}
                          </ul>
                          <p className="mt-1 text-ink/50">{formatBytes(d.wasted_bytes)} recoverable</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              <div className="lg:col-span-5">
                <SectionHeading dot="cyan">Largest directories</SectionHeading>
                <ul className="riso-panel divide-y divide-ink/15">
                  {analysis.largestDirectories.map((d) => (
                    <li
                      key={d.path}
                      className="flex items-center justify-between gap-3 px-4 py-2.5 font-mono text-[12px]"
                    >
                      <span className="truncate">{d.path || "(root)"}</span>
                      <span className="shrink-0 text-ink/60">{formatBytes(d.bytes)}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-8">
                  <SectionHeading dot="magenta">Needs attention</SectionHeading>
                  <ul className="riso-panel divide-y divide-ink/15">
                    {analysis.attention.length === 0 ? (
                      <li className="px-4 py-3 font-mono text-[12px] text-ink/60">
                        Nothing flagged.
                      </li>
                    ) : (
                      analysis.attention.map((a, i) => (
                        <li key={`${a.kind}-${i}`} className="px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <span className="font-mono text-[12px] font-medium">{a.kind}</span>
                            <ProvenanceTag provenance={a.provenance} />
                          </div>
                          <p className="mt-1 font-mono text-[12px] text-ink/60">{a.detail}</p>
                        </li>
                      ))
                    )}
                  </ul>
                </div>
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </Shell>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-ink/50">{k}</dt>
      <dd className="truncate text-right">{v}</dd>
    </div>
  );
}
