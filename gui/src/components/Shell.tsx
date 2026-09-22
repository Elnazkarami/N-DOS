import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

const NAV = [
  { to: "/local", label: "This machine" },
  { to: "/viewer", label: "Manifest" },
  { to: "/query", label: "Query" },
  { to: "/validate", label: "Validate" },
  { to: "/docs", label: "Docs" },
] as const;

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-paper text-ink font-sans">
      <div className="riso-grain" aria-hidden="true" />
      <nav className="flex items-center justify-between gap-4 border-b-2 border-ink px-6 py-4">
        <Link to="/" className="flex items-center gap-2.5">
          <span className="relative h-6 w-6 rounded-full bg-purple ring-3 ring-cyan">
            <span className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan" />
          </span>
          <span className="font-display text-lg tracking-tight">N-DOS</span>
        </Link>
        <div className="hidden items-center gap-6 font-mono text-[11px] uppercase tracking-widest md:flex">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeProps={{ className: "bg-ink text-cream px-2.5 py-1 rounded-sm" }}
            >
              {item.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px]">
          <span className="rounded-sm border border-ink/30 bg-paper/70 px-2.5 py-1">read-only</span>
          <span className="rounded-sm border border-sage bg-sage/25 px-2.5 py-1">runs locally</span>
        </div>
      </nav>

      {children}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t-2 border-ink px-6 py-6 font-mono text-[11px] uppercase tracking-widest">
        <span className="text-ink/60">
          N-DOS · read-only · nothing leaves this machine · plans approved before any change
        </span>
        <a
          href="https://github.com/Elnazkarami/N-DOS"
          className="rounded-sm bg-purple px-2.5 py-1 text-cream"
        >
          Repository
        </a>
      </footer>
    </div>
  );
}

export function ProvenanceTag({
  provenance,
  suffix,
}: {
  provenance: "observed" | "computed" | "guessed";
  suffix?: string;
}) {
  const tone =
    provenance === "observed"
      ? "bg-cyan/20 border-cyan/40"
      : provenance === "computed"
        ? "bg-purple/20 border-purple/40"
        : "bg-magenta/20 border-magenta/40";
  return (
    <span
      className={`shrink-0 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-ink ${tone}`}
    >
      {provenance}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}

export function SectionHeading({ dot, children }: { dot: "purple" | "cyan" | "magenta"; children: ReactNode }) {
  const bg = dot === "purple" ? "bg-purple" : dot === "cyan" ? "bg-cyan" : "bg-magenta";
  return (
    <h2 className="mb-5 flex items-center gap-3 font-display text-2xl">
      <span className={`h-3 w-3 rounded-full ${bg}`} />
      {children}
    </h2>
  );
}
