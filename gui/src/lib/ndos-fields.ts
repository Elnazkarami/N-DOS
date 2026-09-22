/**
 * Field definitions for metadata entry, taken from the declared-field
 * property names allowed by schemas/session_metadata.schema.json (0.1).
 *
 * Validation here is client-side convenience only — `ndos table check` on
 * your own machine remains the authority.
 */

export interface FieldSpec {
  key: string;
  label: string;
  hint: string;
  required?: boolean;
  enumValues?: string[];
  pattern?: RegExp;
  patternHint?: string;
  /** Maps a spelling onto the value the standard uses. */
  normalise?: (raw: string) => string;
}

import {
  ANIMAL_FIELDS as GENERATED_ANIMAL,
  PROCEDURE_FIELDS as GENERATED_PROCEDURE,
  SESSION_FIELDS as GENERATED_SESSION,
  ISO_DATE,
  type GeneratedField,
} from "./ndos-generated";

/**
 * The tools accept several spellings for a value and map them onto the one the
 * standard uses. The interface does the same, so what someone types here is
 * what `ndos table check` would accept there.
 */
function normalise(field: GeneratedField, raw: string): string {
  const lowered = raw.trim().toLowerCase();
  return field.synonyms[lowered] ?? (field.enumValues ? lowered : raw.trim());
}

function toSpec(field: GeneratedField): FieldSpec {
  // Spread rather than assign undefined: an optional property that is present
  // and undefined is not the same as an absent one, and the checker is strict
  // about the difference.
  return {
    key: field.key,
    label: field.key,
    hint: field.hint,
    required: field.required,
    ...(field.enumValues ? { enumValues: field.enumValues } : {}),
    ...(field.isDate ? { pattern: ISO_DATE, patternHint: "must be YYYY-MM-DD" } : {}),
    normalise: (raw: string) => normalise(field, raw),
  };
}

export const ANIMAL_FIELDS: FieldSpec[] = GENERATED_ANIMAL.map(toSpec);
export const PROCEDURE_FIELDS: FieldSpec[] = GENERATED_PROCEDURE.map(toSpec);
export const SESSION_FIELDS: FieldSpec[] = GENERATED_SESSION.map(toSpec);

export type FieldValues = Record<string, string>;

export interface FieldIssue {
  key: string;
  message: string;
}

export function validateFields(specs: FieldSpec[], values: FieldValues): FieldIssue[] {
  const issues: FieldIssue[] = [];
  for (const spec of specs) {
    const raw = (values[spec.key] ?? "").trim();
    if (!raw) {
      if (spec.required) issues.push({ key: spec.key, message: "required — leave nothing blank here" });
      continue;
    }
    if (raw.length > 500) {
      issues.push({ key: spec.key, message: "must be under 500 characters" });
      continue;
    }
    const value = spec.normalise ? spec.normalise(raw) : raw;
    if (spec.enumValues && !spec.enumValues.includes(value)) {
      issues.push({ key: spec.key, message: `must be one of [${spec.enumValues.join(", ")}]` });
      continue;
    }
    if (spec.pattern && !spec.pattern.test(raw)) {
      issues.push({ key: spec.key, message: spec.patternHint ?? "wrong format" });
    }
  }
  return issues;
}

function declaredBlock(specs: FieldSpec[], values: FieldValues) {
  const out: Record<string, { value: string; status: "declared" }> = {};
  for (const spec of specs) {
    const raw = (values[spec.key] ?? "").trim();
    if (raw) {
      out[spec.key] = {
        value: spec.normalise ? spec.normalise(raw) : raw,
        status: "declared",
      };
    }
  }
  return out;
}

/** Values nobody supplied are absent, never empty — per the N-DOS schema. */
export function buildMetadataDraft(
  animal: FieldValues,
  session: FieldValues,
  procedures: FieldValues[],
) {
  return {
    metadata_version: "0.1",
    generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    generator: { name: "ndos-web-entry", version: "0.1" },
    session_count: 1,
    sessions: [
      {
        declared: declaredBlock(SESSION_FIELDS, session),
        animal: {
          subject_id: (animal["subject_id"] ?? "").trim(),
          declared: declaredBlock(ANIMAL_FIELDS, animal),
        },
        ...(procedures.length
          ? {
              procedures: procedures.map((p, i) => ({
                procedure_id: (p["procedure_id"] ?? `proc-${i + 1}`).trim(),
                declared: declaredBlock(PROCEDURE_FIELDS, p),
              })),
            }
          : {}),
      },
    ],
  };
}

export function toCsv(specs: FieldSpec[], rows: FieldValues[]): string {
  const header = specs.map((s) => s.key);
  const escape = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = [header.join(",")];
  for (const row of rows) {
    lines.push(header.map((k) => escape((row[k] ?? "").trim())).join(","));
  }
  return lines.join("\n");
}

export function downloadText(filename: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
