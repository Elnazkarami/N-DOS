import { createFileRoute, Link } from "@tanstack/react-router";
import { Shell, SectionHeading } from "@/components/Shell";

const MODULES = [
  "report",
  "scan",
  "organize",
  "table",
  "query",
  "validate",
  "convert",
  "archive",
  "tags",
  "protect",
  "prov",
];

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "N-DOS — Neuroscience Data Organization System" },
      {
        name: "description",
        content:
          "A browser interface for N-DOS: read a scan manifest, query sessions, and enter lab metadata. Observed, computed and guessed are never mixed.",
      },
      { property: "og:title", content: "N-DOS — Neuroscience Data Organization System" },
      {
        property: "og:description",
        content:
          "A BIDS-inspired standard and toolkit for organising wet-lab and animal neuroscience data, with a browser-only viewer.",
      },
    ],
  }),
  component: Home,
});

function Home() {
  return (
    <Shell>
      <header className="grid items-end gap-8 px-6 py-12 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <span className="mb-5 inline-block rounded-sm bg-purple px-3 py-1 font-mono text-[11px] uppercase tracking-[0.2em] text-cream">
            Neuroscience Data Organization System
          </span>
          <h1 className="font-display text-5xl leading-[0.95] tracking-tight md:text-6xl">
            See what was <span className="-mx-1 bg-cyan/25 px-1">OBSERVED</span>,
            <br />
            what was <span className="-mx-1 bg-purple/25 px-1">COMPUTED</span>,
            <br />
            and what was <span className="-mx-1 bg-magenta/20 px-1">GUESSED</span>.
          </h1>
          <p className="mt-6 max-w-xl text-base leading-relaxed">
            A BIDS-inspired, dependency-free CLI for wet-lab &amp; animal neuroscience data. N-DOS
            never presents a guess as a fact — every inference is labelled, and nothing is moved or
            modified without an approved plan.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link
              to="/viewer"
              className="rounded-sm bg-ink px-4 py-2.5 font-mono text-[12px] uppercase tracking-widest text-cream"
            >
              Open a manifest
            </Link>
            <span className="font-mono text-[11px] text-ink/60">
              nothing leaves this browser
            </span>
          </div>
        </div>
        <div className="lg:col-span-4">
          <div className="riso-panel p-5">
            <p className="riso-label mb-3">Module index</p>
            <div className="flex flex-wrap gap-2">
              {MODULES.map((m, i) => (
                <span
                  key={m}
                  className={
                    i === 0
                      ? "rounded-sm bg-ink px-2 py-1 font-mono text-[11px] text-cream"
                      : "rounded-sm border border-ink/30 bg-cream px-2 py-1 font-mono text-[11px]"
                  }
                >
                  {m}
                </span>
              ))}
            </div>
          </div>
        </div>
      </header>

      <section className="px-6 pb-12">
        <SectionHeading dot="magenta">Provenance — nothing presented as another</SectionHeading>
        <div className="grid gap-5 md:grid-cols-3">
          <article className="riso-panel relative overflow-hidden p-5">
            <span className="absolute right-0 top-0 rounded-bl-md bg-cyan px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-cream">
              Observed
            </span>
            <p className="mb-2 font-mono text-[11px] text-ink/50">src: file header</p>
            <p className="text-lg font-semibold">Session metadata parsed from acquisition log</p>
            <p className="mt-2 font-mono text-xs text-ink/60">subject: 8471 · rig: patch-clamp</p>
          </article>
          <article className="riso-panel relative overflow-hidden p-5">
            <span className="absolute right-0 top-0 rounded-bl-md bg-purple px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-cream">
              Computed
            </span>
            <p className="mb-2 font-mono text-[11px] text-ink/50">src: sha256 + size match</p>
            <p className="text-lg font-semibold">Duplicate cluster of 3 traces resolved</p>
            <p className="mt-2 font-mono text-xs text-ink/60">kept 1 · flagged 2 · 0 moved</p>
          </article>
          <article className="riso-panel relative overflow-hidden p-5">
            <span className="absolute right-0 top-0 rounded-bl-md bg-magenta px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-cream">
              Guessed
            </span>
            <p className="mb-2 font-mono text-[11px] text-ink/50">src: filename heuristic · 0.62</p>
            <p className="text-lg font-semibold">Folder inferred as /day03/epi</p>
            <p className="mt-2 font-mono text-xs text-ink/60">confidence labelled · not applied</p>
          </article>
        </div>
      </section>

      <div className="grid gap-5 px-6 pb-12 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <SectionHeading dot="purple">Session query</SectionHeading>
          <div className="riso-panel overflow-hidden">
            <div className="flex flex-wrap gap-2 border-b-2 border-ink bg-paper/60 p-4">
              <span className="rounded-sm bg-ink px-2.5 py-1 font-mono text-[11px] text-cream">
                species: mouse
              </span>
              <span className="rounded-sm border border-ink/40 bg-cream px-2.5 py-1 font-mono text-[11px]">
                target_region: CA1
              </span>
              <span className="rounded-sm border border-cyan bg-cyan/20 px-2.5 py-1 font-mono text-[11px]">
                duplicates: yes
              </span>
              <Link
                to="/query"
                className="rounded-sm border border-ink/30 bg-cream px-2.5 py-1 font-mono text-[11px]"
              >
                + add filter
              </Link>
            </div>
            <div className="divide-y divide-ink/15 font-mono text-[13px]">
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="w-12 text-ink/40">8471</span>
                <span className="flex-1">day03_ephiL_001.trc</span>
                <span className="rounded-sm border border-magenta/40 bg-magenta/20 px-2 py-0.5 text-[10px] uppercase tracking-widest">
                  guessed 0.62
                </span>
              </div>
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="w-12 text-ink/40">8471</span>
                <span className="flex-1">day03_ephiL_002.trc</span>
                <span className="rounded-sm border border-purple/40 bg-purple/20 px-2 py-0.5 text-[10px] uppercase tracking-widest">
                  dup 2/3
                </span>
              </div>
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="w-12 text-ink/40">9022</span>
                <span className="flex-1">day04_burst_004.trc</span>
                <span className="rounded-sm border border-cyan/40 bg-cyan/20 px-2 py-0.5 text-[10px] uppercase tracking-widest">
                  observed
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="lg:col-span-5">
          <SectionHeading dot="cyan">Metadata entry</SectionHeading>
          <div className="riso-panel space-y-4 p-5">
            <div>
              <span className="riso-label mb-1.5 block">subject_id</span>
              <div className="flex items-center justify-between border-b-2 border-ink pb-1 font-mono text-sm">
                <span>8471</span>
                <span className="rounded-sm border border-sage bg-sage/30 px-1.5 text-[10px] uppercase tracking-widest">
                  valid
                </span>
              </div>
            </div>
            <div>
              <span className="riso-label mb-1.5 block">species</span>
              <div className="flex items-center justify-between border-b-2 border-ink pb-1 font-mono text-sm">
                <span>mouse</span>
                <span className="rounded-sm border border-sage bg-sage/30 px-1.5 text-[10px] uppercase tracking-widest">
                  valid
                </span>
              </div>
            </div>
            <div>
              <span className="riso-label mb-1.5 block">sex</span>
              <div className="flex items-center justify-between border-b-2 border-magenta pb-1 font-mono text-sm">
                <span>f</span>
                <span className="rounded-sm border border-magenta bg-magenta/20 px-1.5 text-[10px] uppercase tracking-widest">
                  enum fail
                </span>
              </div>
              <p className="mt-1.5 font-mono text-[11px] text-magenta">
                must be one of [male, female, unknown]
              </p>
            </div>
            <Link
              to="/validate"
              className="mt-1 block w-full rounded-sm bg-ink py-3 text-center font-mono text-[12px] uppercase tracking-widest text-cream"
            >
              Validate against schema
            </Link>
          </div>
        </div>
      </div>
    </Shell>
  );
}
