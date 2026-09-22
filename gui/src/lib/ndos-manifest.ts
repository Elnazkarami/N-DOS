/**
 * Browser-side reading of N-DOS artefacts. Nothing here uploads or mutates
 * anything — a file is parsed in memory and thrown away when the tab closes.
 *
 * Mirrors schemas/manifest.schema.json (manifest_version 0.2) from the
 * N-DOS repository, and keeps the project's central rule: what was OBSERVED,
 * what was COMPUTED, and what was GUESSED are never mixed.
 */

export type Provenance = "observed" | "computed" | "guessed";

export interface ManifestFile {
  path: string;
  name: string;
  extension: string;
  size_bytes: number;
  modified: string;
  role: "unknown" | "raw" | "derived" | "metadata" | "documentation";
  sha256?: string;
}

export interface SkippedEntry {
  path: string;
  reason: string;
  detail?: string;
}

export interface Manifest {
  manifest_version: string;
  generated_at: string;
  generator: { name: string; version: string };
  source_root: string;
  checksums: boolean;
  file_count: number;
  total_bytes: number;
  files: ManifestFile[];
  skipped: SkippedEntry[];
}

export class ManifestError extends Error {}

export function parseManifest(text: string): Manifest {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ManifestError("That file is not valid JSON.");
  }
  if (typeof raw !== "object" || raw === null) {
    throw new ManifestError("Expected a JSON object at the top level.");
  }
  const m = raw as Partial<Manifest>;
  if (!m.manifest_version) {
    throw new ManifestError(
      "No manifest_version field. Point this at output from `ndos scan --output manifest.json`.",
    );
  }
  if (!Array.isArray(m.files)) {
    throw new ManifestError("This manifest has no files array.");
  }
  const files: ManifestFile[] = m.files.map((f, i): ManifestFile => {
    if (typeof f?.path !== "string" || typeof f?.size_bytes !== "number") {
      throw new ManifestError(`Entry ${i} is missing path or size_bytes.`);
    }
    return {
      path: f.path,
      name: f.name ?? f.path.split("/").pop() ?? f.path,
      extension: (f.extension ?? "").toLowerCase(),
      size_bytes: f.size_bytes,
      modified: f.modified ?? "",
      role: f.role ?? "unknown",
      ...(typeof f.sha256 === "string" ? { sha256: f.sha256 } : {}),
    };
  });

  return {
    manifest_version: m.manifest_version,
    generated_at: m.generated_at ?? "",
    generator: m.generator ?? { name: "unknown", version: "unknown" },
    source_root: m.source_root ?? "",
    checksums: Boolean(m.checksums),
    file_count: m.file_count ?? files.length,
    total_bytes: m.total_bytes ?? files.reduce((s, f) => s + f.size_bytes, 0),
    files,
    skipped: Array.isArray(m.skipped) ? (m.skipped as SkippedEntry[]) : [],
  };
}

/* ------------------------------------------------------------------ */
/* Category inference                                                  */
/* ------------------------------------------------------------------ */

export type Category =
  | "electrophysiology"
  | "imaging"
  | "behaviour"
  | "analysis"
  | "metadata"
  | "documentation"
  | "archive"
  | "ambiguous"
  | "unknown";

const COMPOUND: [RegExp, Category][] = [
  [/\.imec\d*\.(ap|lf)\.(bin|meta)$/i, "electrophysiology"],
  [/_g\d+_t\d+\./i, "electrophysiology"],
  [/\.nwb$/i, "electrophysiology"],
  [/\.(continuous|openephys|rhd|rhs|ns[1-6]|nev|plx|pl2|smr|abf)$/i, "electrophysiology"],
  [/\.(tif|tiff|ome\.tiff|czi|lif|nd2|lsm|svs|ndpi|dcm|nii|nii\.gz)$/i, "imaging"],
  [/\.(avi|mp4|mov|mkv|seq)$/i, "behaviour"],
  [/\.(csv|tsv|xlsx|xls)$/i, "behaviour"],
  [/\.(mat|npy|npz|pkl|h5|hdf5|parquet|feather)$/i, "analysis"],
  [/\.(json|yaml|yml|xml|toml|ini)$/i, "metadata"],
  [/\.(md|txt|pdf|docx|rtf)$/i, "documentation"],
  [/\.(zip|tar|tar\.gz|tgz|7z|rar|gz|bz2|xz)$/i, "archive"],
];

const AMBIGUOUS = new Set([".bin", ".dat", ".raw", ".log", ".out"]);

/** Guessed, never observed: this is a filename heuristic and is labelled as such. */
export function categorise(file: ManifestFile): Category {
  for (const [re, cat] of COMPOUND) {
    if (re.test(file.name)) return cat;
  }
  if (AMBIGUOUS.has(file.extension)) return "ambiguous";
  if (!file.extension) return "unknown";
  return "unknown";
}

/* ------------------------------------------------------------------ */
/* Analysis                                                            */
/* ------------------------------------------------------------------ */

export interface CategorySlice {
  category: Category;
  files: number;
  bytes: number;
  share: number;
}

export interface DuplicateGroup {
  sha256: string;
  paths: string[];
  size_bytes: number;
  wasted_bytes: number;
}

export interface DirectorySize {
  path: string;
  files: number;
  bytes: number;
}

export interface StructureLevel {
  depth: number;
  guess: "subject" | "session" | "date" | "modality" | "unclear";
  confidence: number;
  examples: string[];
  contradictions: string[];
}

export interface AttentionItem {
  kind: string;
  detail: string;
  provenance: Provenance;
}

export interface Analysis {
  composition: CategorySlice[];
  duplicates: DuplicateGroup[];
  wastedBytes: number;
  largestDirectories: DirectorySize[];
  structure: StructureLevel[];
  attention: AttentionItem[];
  extensions: { extension: string; files: number; bytes: number; share: number }[];
}

const SUBJECT_RE = /^(sub|subject|animal|mouse|rat|m|s)[-_]?\d+/i;
const SESSION_RE = /^(ses|session|day|run|rec)[-_]?\d+/i;
const DATE_RE = /(\d{4}[-_]?\d{2}[-_]?\d{2}|\d{2}[-_]\d{2}[-_]\d{4})/;
const MODALITY_RE = /^(ephys|eeg|imaging|behav(iour|ior)?|histology|anat|func|analysis|raw|derived|video)$/i;

export function analyseManifest(m: Manifest): Analysis {
  /* Composition — computed from observed sizes, categories are guessed. */
  const byCat = new Map<Category, { files: number; bytes: number }>();
  const byExt = new Map<string, { files: number; bytes: number }>();
  for (const f of m.files) {
    const c = categorise(f);
    const a = byCat.get(c) ?? { files: 0, bytes: 0 };
    a.files += 1;
    a.bytes += f.size_bytes;
    byCat.set(c, a);
    const key = f.extension || "(no extension)";
    const e = byExt.get(key) ?? { files: 0, bytes: 0 };
    e.files += 1;
    e.bytes += f.size_bytes;
    byExt.set(key, e);
  }
  const total = m.files.reduce((s, f) => s + f.size_bytes, 0) || 1;
  const composition = [...byCat.entries()]
    .map(([category, v]) => ({ category, ...v, share: v.bytes / total }))
    .sort((a, b) => b.bytes - a.bytes);
  const extensions = [...byExt.entries()]
    .map(([extension, v]) => ({ extension, ...v, share: v.bytes / total }))
    .sort((a, b) => b.bytes - a.bytes)
    .slice(0, 12);

  /* Duplicates — computed from sha256 digests only. */
  const bySha = new Map<string, ManifestFile[]>();
  for (const f of m.files) {
    if (!f.sha256) continue;
    const list = bySha.get(f.sha256) ?? [];
    list.push(f);
    bySha.set(f.sha256, list);
  }
  const duplicates: DuplicateGroup[] = [...bySha.entries()]
    .filter(([, list]) => list.length > 1)
    .map(([sha256, list]) => {
      const size = list[0]?.size_bytes ?? 0;
      return {
        sha256,
        paths: list.map((f) => f.path),
        size_bytes: size,
        wasted_bytes: size * (list.length - 1),
      };
    })
    .sort((a, b) => b.wasted_bytes - a.wasted_bytes);
  const wastedBytes = duplicates.reduce((s, d) => s + d.wasted_bytes, 0);

  /* Largest directories — computed, rolled up over every ancestor. */
  const dirs = new Map<string, { files: number; bytes: number }>();
  for (const f of m.files) {
    const parts = f.path.split("/").slice(0, -1);
    for (let i = 1; i <= parts.length; i++) {
      const key = parts.slice(0, i).join("/");
      const d = dirs.get(key) ?? { files: 0, bytes: 0 };
      d.files += 1;
      d.bytes += f.size_bytes;
      dirs.set(key, d);
    }
  }
  const largestDirectories = [...dirs.entries()]
    .map(([path, v]) => ({ path, ...v }))
    .sort((a, b) => b.bytes - a.bytes)
    .slice(0, 8);

  /* Inferred structure — a guess, always labelled with its confidence. */
  const levelNames = new Map<number, Map<string, number>>();
  for (const f of m.files) {
    const parts = f.path.split("/").slice(0, -1);
    parts.forEach((name, depth) => {
      const level = levelNames.get(depth) ?? new Map<string, number>();
      level.set(name, (level.get(name) ?? 0) + 1);
      levelNames.set(depth, level);
    });
  }
  const structure: StructureLevel[] = [...levelNames.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(0, 5)
    .map(([depth, names]) => {
      const unique = [...names.keys()];
      const score = (re: RegExp) => unique.filter((n) => re.test(n)).length / unique.length;
      const candidates: { guess: StructureLevel["guess"]; score: number }[] = [
        { guess: "subject", score: score(SUBJECT_RE) },
        { guess: "session", score: score(SESSION_RE) },
        { guess: "date", score: score(DATE_RE) },
        { guess: "modality", score: score(MODALITY_RE) },
      ];
      candidates.sort((a, b) => b.score - a.score);
      const best = candidates[0] ?? { guess: "unclear" as const, score: 0 };
      const confidence = best.score;
      const winner: StructureLevel["guess"] = confidence >= 0.5 ? best.guess : "unclear";
      const re =
        winner === "subject"
          ? SUBJECT_RE
          : winner === "session"
            ? SESSION_RE
            : winner === "date"
              ? DATE_RE
              : winner === "modality"
                ? MODALITY_RE
                : null;
      return {
        depth,
        guess: winner,
        confidence: Number(confidence.toFixed(2)),
        examples: unique.slice(0, 4),
        contradictions: re ? unique.filter((n) => !re.test(n)).slice(0, 4) : [],
      };
    });

  /* Needs attention. */
  const attention: AttentionItem[] = [];
  const archives = m.files.filter((f) => categorise(f) === "archive");
  if (archives.length) {
    attention.push({
      kind: "Unextracted archives",
      detail: `${archives.length} archive${archives.length === 1 ? "" : "s"} — contents unknown until inspected (\`ndos archive inspect\`)`,
      provenance: "observed",
    });
  }
  const zeroByte = m.files.filter((f) => f.size_bytes === 0);
  if (zeroByte.length) {
    attention.push({
      kind: "Zero-byte files",
      detail: `${zeroByte.length} file${zeroByte.length === 1 ? "" : "s"} of size 0, e.g. ${zeroByte[0]?.path ?? ""}`,
      provenance: "observed",
    });
  }
  const unsafe = m.files.filter((f) => /[<>:"|?*\\]|\s$/.test(f.name));
  if (unsafe.length) {
    attention.push({
      kind: "Names that break elsewhere",
      detail: `${unsafe.length} path${unsafe.length === 1 ? "" : "s"} use characters other systems reject, e.g. ${unsafe[0]?.name ?? ""}`,
      provenance: "observed",
    });
  }
  if (!m.checksums) {
    attention.push({
      kind: "No checksums",
      detail: "Scanned with --no-checksum, so duplicates cannot be detected here.",
      provenance: "observed",
    });
  }
  if (duplicates.length) {
    attention.push({
      kind: "Duplicate files",
      detail: `${duplicates.length} byte-identical group${duplicates.length === 1 ? "" : "s"} wasting ${formatBytes(wastedBytes)}`,
      provenance: "computed",
    });
  }
  const unclear = structure.filter((s) => s.guess === "unclear").length;
  if (unclear) {
    attention.push({
      kind: "Layout not readable",
      detail: `${unclear} directory level${unclear === 1 ? "" : "s"} match no expected shape — see RECIPES.md before organising.`,
      provenance: "guessed",
    });
  }
  for (const s of m.skipped.slice(0, 3)) {
    attention.push({
      kind: `Skipped: ${s.reason}`,
      detail: s.path,
      provenance: "observed",
    });
  }

  return {
    composition,
    duplicates,
    wastedBytes,
    largestDirectories,
    structure,
    attention,
    extensions,
  };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

/* ------------------------------------------------------------------ */
/* Session metadata (schemas/session_metadata.schema.json)             */
/* ------------------------------------------------------------------ */

export interface DeclaredField {
  value: string;
  status: string;
}

export interface SessionRecord {
  ndos_id: string;
  observed: {
    path: string;
    folder_subject?: string;
    folder_session?: string;
    match?: string;
    file_count: number;
    bytes: number;
    modalities?: string[];
  };
  declared?: Record<string, DeclaredField>;
  animal?: { subject_id: string; declared?: Record<string, DeclaredField> };
  procedures?: { procedure_id: string; declared?: Record<string, DeclaredField> }[];
  derived?: Record<string, DeclaredField>;
}

export interface SessionMetadata {
  metadata_version: string;
  generated_at: string;
  session_count: number;
  sessions: SessionRecord[];
}

export function parseSessionMetadata(text: string): SessionMetadata {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ManifestError("That file is not valid JSON.");
  }
  const m = raw as Partial<SessionMetadata>;
  if (!Array.isArray(m?.sessions)) {
    throw new ManifestError(
      "No sessions array. Point this at output from `ndos table check --emit linked.json`.",
    );
  }
  return {
    metadata_version: m.metadata_version ?? "unknown",
    generated_at: m.generated_at ?? "",
    session_count: m.session_count ?? m.sessions.length,
    sessions: m.sessions as SessionRecord[],
  };
}

/** Every queryable key/value pair on a session, with where it came from. */
export function sessionFacets(s: SessionRecord): Record<string, { value: string; provenance: Provenance }> {
  const out: Record<string, { value: string; provenance: Provenance }> = {};
  for (const [k, v] of Object.entries(s.declared ?? {})) {
    if (v?.value) out[k] = { value: v.value, provenance: "observed" };
  }
  for (const [k, v] of Object.entries(s.animal?.declared ?? {})) {
    if (v?.value) out[k] = { value: v.value, provenance: "observed" };
  }
  for (const p of s.procedures ?? []) {
    for (const [k, v] of Object.entries(p.declared ?? {})) {
      if (v?.value && !out[k]) out[k] = { value: v.value, provenance: "observed" };
    }
  }
  for (const [k, v] of Object.entries(s.derived ?? {})) {
    if (v?.value) out[k] = { value: v.value, provenance: "computed" };
  }
  if (s.observed?.match) out["match"] = { value: s.observed.match, provenance: "guessed" };
  return out;
}
