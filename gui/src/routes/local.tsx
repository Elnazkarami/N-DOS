import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { FolderPicker } from "@/components/FolderPicker";
import { SectionHeading, Shell } from "@/components/Shell";
import {
  api,
  followJob,
  formatBytes,
  formatDuration,
  isLocal,
  type Estimate,
  type Job,
  type ValidateResult,
} from "@/lib/api";

export const Route = createFileRoute("/local")({
  head: () => ({
    meta: [
      { title: "This machine — N-DOS" },
      {
        name: "description",
        content:
          "Point N-DOS at a folder on this machine: see what is in it, how long a full scan would take, and whether it follows the standard.",
      },
    ],
  }),
  component: LocalPage,
});

type Report = {
  summary: { file_count: number; total_bytes: number };
  composition: { category: string; file_count: number; total_bytes: number }[];
  attention: { severity: string; title: string; detail: string }[];
};

function LocalPage() {
  const [folder, setFolder] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [conformance, setConformance] = useState<ValidateResult | null>(null);
  const [progress, setProgress] = useState<Job<Report> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  if (!isLocal()) {
    return (
      <Shell>
        <main className="mx-auto max-w-3xl px-6 py-12">
          <SectionHeading dot="magenta">Not running locally</SectionHeading>
          <p className="mt-4 text-sm leading-relaxed">
            This page can only read a drive when it is served by N-DOS itself. On the machine
            holding the data, install the package and run:
          </p>
          <pre className="riso-panel mt-4 px-4 py-3 font-mono text-[12px]">ndos gui</pre>
          <p className="mt-4 text-sm leading-relaxed">
            That opens this interface with permission to read the folders you point it at. Nothing
            is uploaded and nothing leaves the machine.
          </p>
        </main>
      </Shell>
    );
  }

  const run = async (what: string, work: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    try {
      await work();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Shell>
      <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
        <header>
          <SectionHeading dot="purple">A folder on this machine</SectionHeading>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed">
            Reading only. Nothing is moved, renamed or written, and nothing leaves this computer.
          </p>
        </header>

        <FolderPicker onChoose={setFolder} chosen={folder} />

        {folder && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                run("estimate", async () => setEstimate(await api.estimate(folder)))
              }
              className="rounded-sm border-2 border-ink px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest disabled:opacity-40"
            >
              {busy === "estimate" ? "measuring…" : "how long would a full scan take?"}
            </button>
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                run("report", async () => {
                  const { job } = await api.startScan(folder, false);
                  setReport(await followJob<Report>(job, setProgress));
                })
              }
              className="rounded-sm bg-ink px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest text-cream disabled:opacity-40"
            >
              {busy === "report" ? "reading…" : "what is in here?"}
            </button>
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                run("validate", async () => setConformance(await api.validate(folder)))
              }
              className="rounded-sm border-2 border-purple px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest text-purple disabled:opacity-40"
            >
              {busy === "validate" ? "checking…" : "does it follow the standard?"}
            </button>
          </div>
        )}

        {error && (
          <div className="riso-panel border-magenta px-5 py-4">
            <p className="font-mono text-[11px] uppercase tracking-widest text-magenta">problem</p>
            <p className="mt-2 text-sm">{error}</p>
          </div>
        )}

        {busy === "report" && progress?.progress?.files != null && (
          <p className="font-mono text-[12px]">
            {progress.progress.files.toLocaleString()} files ·{" "}
            {formatBytes(progress.progress.bytes ?? 0)}
            {progress.progress.seconds_remaining != null &&
              ` · ~${formatDuration(progress.progress.seconds_remaining)} left`}
          </p>
        )}

        {estimate && (
          <section className="riso-panel px-5 py-4">
            <SectionHeading dot="cyan">Cost of a full scan</SectionHeading>
            <p className="mt-3 font-mono text-[12px]">
              {estimate.file_count.toLocaleString()} files ·{" "}
              {formatBytes(estimate.total_bytes)}
            </p>
            <p className="mt-1 font-mono text-[12px]">
              {estimate.bytes_per_second
                ? `this drive reads at about ${formatBytes(estimate.bytes_per_second)}/s`
                : "read speed could not be measured"}
            </p>
            <p className="mt-1 font-mono text-[12px] text-purple">
              checksumming everything would take about {formatDuration(estimate.seconds)}
            </p>
          </section>
        )}

        {report && (
          <section className="riso-panel px-5 py-4">
            <SectionHeading dot="cyan">What is in here</SectionHeading>
            <p className="mt-3 font-mono text-[12px]">
              {report.summary.file_count.toLocaleString()} files ·{" "}
              {formatBytes(report.summary.total_bytes)}
            </p>
            <ul className="mt-3 space-y-1">
              {report.composition.map((row) => (
                <li key={row.category} className="flex justify-between font-mono text-[12px]">
                  <span>{row.category}</span>
                  <span className="text-ink/70">
                    {row.file_count.toLocaleString()} · {formatBytes(row.total_bytes)}
                  </span>
                </li>
              ))}
            </ul>
            {report.attention.length > 0 && (
              <div className="mt-4 border-t border-ink/20 pt-3">
                <p className="font-mono text-[11px] uppercase tracking-widest">needs attention</p>
                <ul className="mt-2 space-y-2">
                  {report.attention.map((item) => (
                    <li key={item.title} className="text-sm">
                      <span className="font-medium">{item.title}</span>
                      <span className="block text-ink/70">{item.detail}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {conformance && (
          <section className="riso-panel px-5 py-4">
            <SectionHeading dot="magenta">
              N-DOS {conformance.spec_version} conformance
            </SectionHeading>
            <p className="mt-3 text-sm">
              {conformance.conforms
                ? "This project conforms."
                : "This project does not yet conform."}{" "}
              <span className="font-mono text-[12px] text-ink/70">
                {conformance.subject_count} subjects · {conformance.session_count} sessions
              </span>
            </p>
            <ul className="mt-3 space-y-3">
              {conformance.findings.map((finding) => (
                <li key={finding.code + finding.where} className="text-sm">
                  <span
                    className={`mr-2 rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                      finding.level === "requirement"
                        ? "bg-magenta text-cream"
                        : "border border-ink/30"
                    }`}
                  >
                    {finding.level === "requirement" ? "required" : "suggested"}
                  </span>
                  {finding.message}
                  <span className="mt-1 block font-mono text-[11px] text-ink/70">
                    {finding.fix}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </Shell>
  );
}
