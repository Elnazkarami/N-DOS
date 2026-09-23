import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { FolderPicker } from "@/components/FolderPicker";
import { api, isLocal, type CheckResult } from "@/lib/api";
import { Shell, SectionHeading } from "@/components/Shell";
import {
  ANIMAL_FIELDS,
  PROCEDURE_FIELDS,
  SESSION_FIELDS,
  buildMetadataDraft,
  downloadText,
  toCsv,
  validateFields,
  type FieldSpec,
  type FieldValues,
} from "@/lib/ndos-fields";

export const Route = createFileRoute("/validate")({
  head: () => ({
    meta: [
      { title: "Metadata entry & validation — N-DOS" },
      {
        name: "description",
        content:
          "Enter the animal, procedure and session facts only you know, check them against the N-DOS schema, and export JSON or CSV for the toolkit.",
      },
      { property: "og:title", content: "Metadata entry & validation — N-DOS" },
      {
        property: "og:description",
        content: "Schema-checked metadata forms for N-DOS. Everything stays in your browser.",
      },
    ],
  }),
  component: ValidatePage,
});

function ValidatePage() {
  const [animal, setAnimal] = useState<FieldValues>({});
  const [session, setSession] = useState<FieldValues>({});
  const [procedures, setProcedures] = useState<FieldValues[]>([{}]);
  const [checked, setChecked] = useState(false);

  const animalIssues = useMemo(() => validateFields(ANIMAL_FIELDS, animal), [animal]);
  const sessionIssues = useMemo(() => validateFields(SESSION_FIELDS, session), [session]);
  const procedureIssues = useMemo(
    () => procedures.map((p) => (isBlank(p) ? [] : validateFields(PROCEDURE_FIELDS, p))),
    [procedures],
  );

  const totalIssues =
    animalIssues.length + sessionIssues.length + procedureIssues.flat().length;

  const exportable = procedures.filter((p) => !isBlank(p));

  const local = isLocal();
  const [tables, setTables] = useState<CheckResult | null>(null);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [checkedPath, setCheckedPath] = useState<string | null>(null);

  // Checking tables that already exist is a different question from checking
  // what is being typed: it is the one that spans all three files, so it can
  // only be answered where the files are.
  const checkTables = async (path: string) => {
    setTablesError(null);
    try {
      const result = await api.check(path);
      setTables(result);
      setCheckedPath(result.directory);
    } catch (problem) {
      setTables(null);
      setCheckedPath(null);
      setTablesError(problem instanceof Error ? problem.message : String(problem));
    }
  };

  return (
    <Shell>
      <div className="px-6 py-10">
        <h1 className="font-display text-4xl leading-tight tracking-tight">
          Metadata entry &amp; validation
        </h1>
        <p className="mt-3 max-w-2xl leading-relaxed">
          N-DOS reads your filesystem; these are the facts only you know. Fields left blank stay
          absent rather than empty, so “not yet entered” is never confused with “checked and
          unknown”.
        </p>

        {local && (
          <section className="mt-8">
            <SectionHeading dot="purple">Tables you already have</SectionHeading>
            <p className="mb-3 max-w-2xl text-sm leading-relaxed">
              The form below checks one value at a time. A project's tables are checked across
              all three at once — whether a procedure names an animal that exists, whether a
              session date falls before the surgery it refers to. Nothing is written.
            </p>
            <div className="max-w-2xl">
              <FolderPicker
                chosen={checkedPath}
                chooseLabel="check this project"
                onChoose={(path) => void checkTables(path)}
              />
            </div>

            {tablesError && (
              <div className="mt-4 max-w-2xl riso-panel px-5 py-4">
                <p className="font-mono text-[11px] uppercase tracking-widest text-magenta">
                  nothing to check
                </p>
                <p className="mt-2 text-sm">{tablesError}</p>
              </div>
            )}

            {tables && <TableReport result={tables} />}
          </section>
        )}

        <div className="mt-8 grid gap-5 lg:grid-cols-12">
          <div className="lg:col-span-4">
            <SectionHeading dot="cyan">Animal</SectionHeading>
            <FieldPanel
              specs={ANIMAL_FIELDS}
              values={animal}
              onChange={setAnimal}
              issues={checked ? animalIssues : []}
            />
          </div>

          <div className="lg:col-span-4">
            <SectionHeading dot="purple">Session</SectionHeading>
            <FieldPanel
              specs={SESSION_FIELDS}
              values={session}
              onChange={setSession}
              issues={checked ? sessionIssues : []}
            />
          </div>

          <div className="lg:col-span-4">
            <SectionHeading dot="magenta">Procedures</SectionHeading>
            <div className="space-y-4">
              {procedures.map((p, i) => (
                <div key={i}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="riso-label">procedure {i + 1}</span>
                    {procedures.length > 1 ? (
                      <button
                        onClick={() => setProcedures(procedures.filter((_, j) => j !== i))}
                        className="font-mono text-[11px] uppercase tracking-widest text-magenta"
                      >
                        remove
                      </button>
                    ) : null}
                  </div>
                  <FieldPanel
                    specs={PROCEDURE_FIELDS}
                    values={p}
                    onChange={(next) =>
                      setProcedures(procedures.map((row, j) => (j === i ? next : row)))
                    }
                    issues={checked ? (procedureIssues[i] ?? []) : []}
                  />
                </div>
              ))}
              <button
                onClick={() => setProcedures([...procedures, {}])}
                className="w-full rounded-sm border border-ink/30 bg-cream py-2 font-mono text-[11px] uppercase tracking-widest"
              >
                + another procedure
              </button>
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button
            onClick={() => setChecked(true)}
            className="rounded-sm bg-ink px-5 py-3 font-mono text-[12px] uppercase tracking-widest text-cream"
          >
            Validate against schema
          </button>
          <button
            onClick={() =>
              downloadText(
                "session_metadata.json",
                JSON.stringify(buildMetadataDraft(animal, session, exportable), null, 2),
                "application/json",
              )
            }
            className="rounded-sm border-2 border-ink px-5 py-2.5 font-mono text-[12px] uppercase tracking-widest"
          >
            Export JSON
          </button>
          <button
            onClick={() => {
              downloadText("animals.csv", toCsv(ANIMAL_FIELDS, [animal]), "text/csv");
              downloadText("sessions.csv", toCsv(SESSION_FIELDS, [session]), "text/csv");
              if (exportable.length)
                downloadText("procedures.csv", toCsv(PROCEDURE_FIELDS, exportable), "text/csv");
            }}
            className="rounded-sm border-2 border-ink px-5 py-2.5 font-mono text-[12px] uppercase tracking-widest"
          >
            Export CSV tables
          </button>
          {checked ? (
            <span
              className={`rounded-sm px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest ${
                totalIssues === 0
                  ? "border border-sage bg-sage/30"
                  : "border border-magenta bg-magenta/20"
              }`}
            >
              {totalIssues === 0
                ? "all entered fields valid"
                : `${totalIssues} field${totalIssues === 1 ? "" : "s"} to fix`}
            </span>
          ) : null}
        </div>

        <p className="mt-4 max-w-2xl font-mono text-[11px] text-ink/55">
          These checks mirror schemas/session_metadata.schema.json. `python3 ndos.py table check`
          on your own machine remains the authority.
        </p>
      </div>
    </Shell>
  );
}

function isBlank(values: FieldValues) {
  return Object.values(values).every((v) => !v?.trim());
}

function FieldPanel({
  specs,
  values,
  onChange,
  issues,
}: {
  specs: FieldSpec[];
  values: FieldValues;
  onChange: (next: FieldValues) => void;
  issues: { key: string; message: string }[];
}) {
  return (
    <div className="riso-panel space-y-4 p-5">
      {specs.map((spec) => {
        const issue = issues.find((i) => i.key === spec.key);
        const filled = Boolean((values[spec.key] ?? "").trim());
        return (
          <div key={spec.key}>
            <label className="riso-label mb-1.5 block" htmlFor={`${spec.key}-${spec.label}`}>
              {spec.label}
              {spec.required ? " *" : ""}
            </label>
            <div
              className={`flex items-center gap-2 border-b-2 pb-1 ${
                issue ? "border-magenta" : "border-ink"
              }`}
            >
              {spec.enumValues ? (
                <select
                  id={`${spec.key}-${spec.label}`}
                  value={values[spec.key] ?? ""}
                  onChange={(e) => onChange({ ...values, [spec.key]: e.target.value })}
                  className="w-full bg-transparent font-mono text-sm outline-none"
                >
                  <option value="">—</option>
                  {spec.enumValues.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id={`${spec.key}-${spec.label}`}
                  value={values[spec.key] ?? ""}
                  maxLength={500}
                  placeholder={spec.hint}
                  onChange={(e) => onChange({ ...values, [spec.key]: e.target.value })}
                  className="w-full bg-transparent font-mono text-sm outline-none placeholder:text-ink/35"
                />
              )}
              {issue ? (
                <span className="shrink-0 rounded-sm border border-magenta bg-magenta/20 px-1.5 font-mono text-[10px] uppercase tracking-widest">
                  fail
                </span>
              ) : filled ? (
                <span className="shrink-0 rounded-sm border border-sage bg-sage/30 px-1.5 font-mono text-[10px] uppercase tracking-widest">
                  valid
                </span>
              ) : null}
            </div>
            {issue ? (
              <p className="mt-1.5 font-mono text-[11px] text-magenta">{issue.message}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/**
 * What the real checker found in a project's tables.
 *
 * Completeness is shown per field rather than as one number, because "62%
 * complete" hides which 38% is missing — and a required field nobody filled
 * in is a different problem from an optional one.
 */
function TableReport({ result }: { result: CheckResult }) {
  const fields = Object.entries(result.completeness);
  const required = fields.filter(([, v]) => v.required);
  const optional = fields.filter(([, v]) => !v.required);

  return (
    <div className="mt-5 max-w-3xl space-y-5">
      <div className="riso-panel px-5 py-4">
        <p className="font-mono text-[12px]">
          {result.row_count} session rows · {result.complete_rows} with every required field
        </p>
        <p className="mt-1 font-mono text-[11px] text-ink/60">{result.directory}</p>
      </div>

      {result.problems.length > 0 ? (
        <div className="riso-panel overflow-hidden">
          <div className="border-b-2 border-ink/20 bg-paper/60 px-4 py-3">
            <h3 className="font-display text-lg leading-none">
              Problems <span className="font-mono text-[12px] text-ink/50">{result.problems.length}</span>
            </h3>
          </div>
          <ul className="divide-y divide-ink/15">
            {result.problems.slice(0, 50).map((problem, i) => (
              <li key={i} className="px-4 py-2.5">
                <div className="flex flex-wrap items-baseline gap-2 font-mono text-[12px]">
                  <span
                    className={
                      problem.level === "error" ? "text-magenta" : "text-ink/50"
                    }
                  >
                    {problem.level}
                  </span>
                  <span className="text-ink/40">{problem.where}</span>
                </div>
                <p className="mt-1 text-sm">{problem.message}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="font-mono text-[12px]">No contradictions between the tables.</p>
      )}

      <div className="riso-panel px-5 py-4">
        <p className="riso-label mb-3">How much is filled in</p>
        <Completeness rows={required} heading="required" />
        <Completeness rows={optional} heading="optional" />
      </div>
    </div>
  );
}

function Completeness({
  rows,
  heading,
}: {
  rows: [string, CheckResult["completeness"][string]][];
  heading: string;
}) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 first:mt-0">
      <p className="font-mono text-[11px] uppercase tracking-widest text-ink/50">{heading}</p>
      <ul className="mt-2 space-y-1.5">
        {rows.map(([field, v]) => (
          <li key={field} className="flex items-center gap-3 font-mono text-[12px]">
            <span className="w-40 shrink-0 truncate">{field}</span>
            <span className="h-1.5 flex-1 rounded-sm bg-ink/10">
              <span
                className={`block h-full rounded-sm ${
                  v.required && v.percent === 0 ? "bg-magenta" : "bg-purple"
                }`}
                style={{ width: `${Math.max(v.percent, v.percent > 0 ? 2 : 0)}%` }}
              />
            </span>
            <span className="w-24 shrink-0 text-right text-ink/60">
              {v.percent.toFixed(0)}%
              {v.explicit_unknown > 0 ? ` · ${v.explicit_unknown} unknown` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
