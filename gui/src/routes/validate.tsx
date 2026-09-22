import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
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
