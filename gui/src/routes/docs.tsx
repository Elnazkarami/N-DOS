import { createFileRoute } from "@tanstack/react-router";
import { Shell, SectionHeading } from "@/components/Shell";

export const Route = createFileRoute("/docs")({
  head: () => ({
    meta: [
      { title: "Docs & module reference — N-DOS" },
      {
        name: "description",
        content:
          "Quickstart, the N-DOS standard in brief, and what each module does: report, scan, organize, table, query, validate, convert, archive, tags, protect, prov.",
      },
      { property: "og:title", content: "Docs & module reference — N-DOS" },
      {
        property: "og:description",
        content: "How to run N-DOS end to end, and what every module is for.",
      },
    ],
  }),
  component: Docs,
});

const PIPELINE = [
  { cmd: "python3 ndos.py report /path/to/chaos", note: "what is in here?" },
  { cmd: "python3 ndos.py archive inspect /path/to/chaos -c arch.json", note: "what is in the zips?" },
  { cmd: "python3 ndos.py organize apply /path/to/chaos -d ./project", note: "build the N-DOS layout" },
  { cmd: "python3 ndos.py table export ./project -d ./metadata", note: "fill in what only you know" },
  { cmd: "python3 ndos.py table check ./metadata --emit linked.json", note: "check and link it" },
  { cmd: "python3 ndos.py query linked.json -w species=mouse -w target_region=CA1", note: "ask questions of it" },
  { cmd: "python3 ndos.py convert bids ./project -d ./bids-export --write", note: "hand it to BIDS tools" },
];

const MODULES = [
  {
    name: "ndos_report.py",
    line: "Understand a directory you have inherited",
    body: "Composition by category and size, the folder structure it appears to use, duplicate files, largest directories, and what needs attention. No metadata or setup required.",
  },
  {
    name: "ndos_scan.py",
    line: "Read-only inventory",
    body: "A versioned JSON manifest: every file with path, size, modification time and SHA-256, plus an explicit list of everything skipped and why.",
  },
  {
    name: "ndos_organize.py",
    line: "Build the N-DOS layout",
    body: "Proposes a plan you approve first. Symbolic links by default; --mode move is the only variant that touches your files.",
  },
  {
    name: "ndos_table.py",
    line: "Fill in what only you know",
    body: "Exports spreadsheets for animals, procedures and sessions, then checks them and emits a linked metadata file.",
  },
  {
    name: "ndos_query.py",
    line: "Ask questions of the result",
    body: "Filters linked sessions by declared and computed fields, e.g. species=mouse with target_region=CA1.",
  },
  {
    name: "ndos_validate.py",
    line: "Does this project follow the standard?",
    body: "Checks a project against SPECIFICATION.md — layout, session structure, identifiers, naming and data flags.",
  },
  {
    name: "ndos_convert.py",
    line: "Export to BIDS",
    body: "Writes a BIDS-shaped export from an N-DOS project so existing BIDS tooling can read it.",
  },
  {
    name: "ndos_archive.py",
    line: "See inside the zips",
    body: "Inspects archives without extracting; extraction is a separate, explicit step.",
  },
  {
    name: "ndos_tags.py",
    line: "Data flags",
    body: "Reads and sweeps N-DOS flags; --apply shows a plan and asks first.",
  },
  {
    name: "ndos_protect.py",
    line: "Guard what must not change",
    body: "Marks raw data so later steps cannot quietly write over it.",
  },
  {
    name: "ndos_prov.py",
    line: "Provenance record",
    body: "Records what produced what, so a derived file can be traced back to the recording it came from.",
  },
];

function Docs() {
  return (
    <Shell>
      <div className="px-6 py-10">
        <h1 className="font-display text-4xl leading-tight tracking-tight">Docs</h1>
        <p className="mt-3 max-w-2xl leading-relaxed">
          N-DOS Core is Python 3.9+ standard library only — no pip install, no environment, no
          dependencies, because the machine that most needs inventorying is often an acquisition PC
          where you cannot install anything.
        </p>

        <section className="mt-10 grid gap-5 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <SectionHeading dot="cyan">Install nothing</SectionHeading>
            <div className="riso-panel space-y-1 p-5 font-mono text-[12.5px] leading-relaxed">
              <p>git clone https://github.com/Elnazkarami/N-DOS.git ndos</p>
              <p>cd ndos</p>
              <p>python3 ndos.py --help</p>
              <p>python3 ndos.py report /path/to/your/data</p>
              <p className="pt-2 text-ink/50"># or, if you would rather type `ndos report`</p>
              <p>pip install -e .</p>
            </div>
          </div>
          <div className="lg:col-span-6">
            <SectionHeading dot="purple">The whole thing, end to end</SectionHeading>
            <ol className="riso-panel divide-y divide-ink/15">
              {PIPELINE.map((step) => (
                <li key={step.cmd} className="px-4 py-2.5">
                  <p className="font-mono text-[12.5px]">{step.cmd}</p>
                  <p className="font-mono text-[11px] text-ink/50">{step.note}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mt-12">
          <SectionHeading dot="magenta">Safety guarantee</SectionHeading>
          <div className="riso-panel max-w-3xl p-5 leading-relaxed">
            <p>
              <code className="font-mono text-[13px]">ndos_scan.py</code> and{" "}
              <code className="font-mono text-[13px]">ndos_report.py</code> never modify, move,
              rename, extract or delete anything below the directory you point them at. They open
              files only to read bytes for checksums, and tests snapshot every size and modification
              time before and after a scan.
            </p>
            <p className="mt-3">
              The only commands that ever write to your files are{" "}
              <code className="font-mono text-[13px]">ndos_organize --mode move</code>,{" "}
              <code className="font-mono text-[13px]">ndos_archive extract</code> and{" "}
              <code className="font-mono text-[13px]">ndos_tags sweep --apply</code> — each shows a
              plan and asks first.
            </p>
          </div>
        </section>

        <section className="mt-12">
          <SectionHeading dot="cyan">Module reference</SectionHeading>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {MODULES.map((m) => (
              <article key={m.name} className="riso-panel p-5">
                <p className="font-mono text-[12px] text-purple">{m.name}</p>
                <h3 className="mt-1.5 text-lg font-semibold leading-snug">{m.line}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink/75">{m.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mt-12">
          <SectionHeading dot="purple">The standard</SectionHeading>
          <div className="riso-panel max-w-3xl p-5 leading-relaxed">
            <p>
              The directory layout, session structure, identifiers, naming conventions and data
              flags are stated in SPECIFICATION.md, so a project can be checked against them rather
              than argued about. It comes from the manuscript, which explains the reasoning; the
              specification states the rules.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <a
                href="https://github.com/Elnazkarami/N-DOS/blob/main/SPECIFICATION.md"
                className="rounded-sm bg-ink px-3 py-2 font-mono text-[11px] uppercase tracking-widest text-cream"
              >
                Specification
              </a>
              <a
                href="https://github.com/Elnazkarami/N-DOS/blob/main/QUICKSTART.md"
                className="rounded-sm border border-ink/30 bg-cream px-3 py-2 font-mono text-[11px] uppercase tracking-widest"
              >
                Quickstart
              </a>
              <a
                href="https://github.com/Elnazkarami/N-DOS/blob/main/RECIPES.md"
                className="rounded-sm border border-ink/30 bg-cream px-3 py-2 font-mono text-[11px] uppercase tracking-widest"
              >
                Recipes
              </a>
              <a
                href="https://github.com/Elnazkarami/N-DOS/issues/new?template=3-pilot-feedback.yml"
                className="rounded-sm border border-magenta bg-magenta/20 px-3 py-2 font-mono text-[11px] uppercase tracking-widest"
              >
                Pilot feedback
              </a>
            </div>
          </div>
        </section>
      </div>
    </Shell>
  );
}
