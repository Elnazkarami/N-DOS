/**
 * Talking to the N-DOS server running on this machine.
 *
 * The page is served by `ndos gui`, which injects a token into the document
 * that only this page is given. Without it the server answers nothing — which
 * is what stops another site open in the same browser from reading the disk.
 */

declare global {
  interface Window {
    __NDOS__?: { token: string; version: string };
  }
}

export class NotLocalError extends Error {
  constructor() {
    super(
      "This page is not being served by N-DOS. Run `ndos gui` on the machine " +
        "holding the data, and it will open a page that can read it.",
    );
    this.name = "NotLocalError";
  }
}

export function isLocal(): boolean {
  return typeof window !== "undefined" && Boolean(window.__NDOS__?.token);
}

async function call<T>(endpoint: string, payload: Record<string, unknown> = {}): Promise<T> {
  const token = typeof window === "undefined" ? undefined : window.__NDOS__?.token;
  if (!token) throw new NotLocalError();

  // Absolute, not relative: the server mounts the API at /api, and a page
  // opened at /local/ rather than /local would resolve a relative path to
  // /local/api/... and get a 404 for every call it made.
  const response = await fetch(`/api/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-NDOS-Token": token },
    body: JSON.stringify(payload),
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error ?? `${endpoint} failed (${response.status})`);
  }
  return body as T;
}

export interface BrowseResult {
  path: string;
  parent: string | null;
  directories: { name: string; path: string }[];
  file_count: number;
  is_project: boolean;
}

export interface Estimate {
  file_count: number;
  total_bytes: number;
  remaining_bytes: number;
  bytes_per_second: number | null;
  seconds: number | null;
}

export interface Finding {
  level: "requirement" | "recommendation";
  code: string;
  message: string;
  fix: string;
  where: string;
}

export interface ValidateResult {
  spec_version: string;
  root: string;
  conforms: boolean;
  subject_count: number;
  session_count: number;
  findings: Finding[];
}

export interface Job<T> {
  id: string;
  kind: string;
  state: "running" | "done" | "failed";
  progress: {
    files?: number;
    total_files?: number | null;
    bytes?: number;
    bytes_per_second?: number;
    seconds_remaining?: number | null;
    reused?: number;
  };
  result: T | null;
  error: string | null;
}

export const api = {
  status: () => call<{ home: string; spec_version: string; interface_built: boolean }>("status"),
  browse: (path?: string) => call<BrowseResult>("browse", path ? { path } : {}),
  estimate: (path: string) => call<Estimate>("estimate", { path }),
  report: (path: string, checksums = false) =>
    call<Record<string, unknown>>("report", { path, checksums }),
  validate: (path: string) => call<ValidateResult>("validate", { path }),
  startScan: (path: string, checksums: boolean, cache?: string) =>
    call<{ job: string }>("scan", { path, checksums, cache }),
  job: <T,>(job: string) => call<Job<T>>("job", { job }),
};

/** Follow a job to completion, reporting progress as it goes. */
export async function followJob<T>(
  jobId: string,
  onProgress: (job: Job<T>) => void,
  intervalMs = 700,
): Promise<T> {
  for (;;) {
    const job = await api.job<T>(jobId);
    onProgress(job);
    if (job.state === "done") return job.result as T;
    if (job.state === "failed") throw new Error(job.error ?? "the job failed");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "unknown";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 90) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(Math.round(minutes % 60)).padStart(2, "0")}m`;
}
