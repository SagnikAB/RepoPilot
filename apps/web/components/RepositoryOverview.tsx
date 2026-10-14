"use client";

import { Badge, statusTone } from "./ui/Badge";
import { useInvestigation } from "./workspace/InvestigationProvider";

function Stat({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-0.5 text-sm font-medium">{value ?? "—"}</p>
    </div>
  );
}

export function RepositoryOverview() {
  const { summary } = useInvestigation();
  if (!summary) {
    return (
      <section className="border-b border-border px-4 py-6 text-sm text-muted">
        Submit a public GitHub repository to start an analysis, or open the demo analysis ID{" "}
        <code className="font-mono text-text">4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a</code> after starting the
        analyzer demo server.
      </section>
    );
  }

  const stats = summary.stats;
  const duration =
    summary.duration_ms === null || summary.duration_ms === undefined
      ? "—"
      : `${(summary.duration_ms / 1000).toFixed(1)}s`;

  return (
    <section className="space-y-3 border-b border-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-base font-semibold">
          {summary.repository.owner}/{summary.repository.name}
        </h1>
        <Badge tone={statusTone(summary.status)}>{summary.status}</Badge>
        <a
          href={summary.repository.url}
          className="text-xs text-accent underline-offset-2 hover:underline"
          target="_blank"
          rel="noreferrer"
        >
          {summary.repository.url}
        </a>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        <Stat label="Reference" value={summary.repository.ref ?? "default"} />
        <Stat label="Commit" value={summary.repository.commit_sha?.slice(0, 12) ?? "unknown"} />
        <Stat label="Duration" value={duration} />
        <Stat label="Discovered" value={stats?.files_discovered} />
        <Stat label="Analyzed" value={stats?.files_analyzed} />
        <Stat label="Functions" value={stats?.functions} />
        <Stat label="Resolved edges" value={stats?.call_edges} />
        <Stat label="Unresolved" value={stats?.unresolved_calls} />
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted">
        <span>
          Findings: {stats?.findings === null || stats?.findings === undefined ? "not computed" : stats.findings}
        </span>
        {stats
          ? Object.entries(stats.findings_by_severity).map(([severity, count]) => (
              <span key={severity} className={`severity-${severity}`}>
                {severity}: {count}
              </span>
            ))
          : null}
        {stats
          ? Object.entries(stats.files_by_language).map(([language, count]) => (
              <span key={language}>
                {language}: {count}
              </span>
            ))
          : null}
      </div>
      <Diagnostics />
    </section>
  );
}

function Diagnostics() {
  const { summary } = useInvestigation();
  if (!summary) {
    return null;
  }
  const d = summary.diagnostics;
  return (
    <details className="rounded-md border border-border bg-surface p-3 text-sm" open={d.warnings.length > 0 || d.parse_errors.length > 0}>
      <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-muted">
        Diagnostics{d.truncated ? " (truncated)" : ""}
      </summary>
      <div className="mt-2 space-y-2 text-xs">
        {d.warnings.map((warning) => (
          <p key={warning} className="text-warn">
            {warning}
          </p>
        ))}
        {d.limits_reached.length > 0 ? (
          <ul className="list-disc pl-4">
            {d.limits_reached.map((limit) => (
              <li key={limit.limit}>
                Limit {limit.limit} = {limit.value}
              </li>
            ))}
          </ul>
        ) : null}
        {Object.keys(d.skipped_by_reason).length > 0 ? (
          <p>
            Skipped by reason:{" "}
            {Object.entries(d.skipped_by_reason)
              .map(([reason, count]) => `${reason} (${count})`)
              .join(", ")}
          </p>
        ) : null}
        {d.parse_errors.length > 0 ? (
          <ul className="list-disc pl-4">
            {d.parse_errors.map((error, index) => (
              <li key={`${error.path}-${index}`}>
                {error.path}
                {error.line ? `:${error.line}` : ""} — {error.message}
              </li>
            ))}
          </ul>
        ) : null}
        {d.skipped_files.length > 0 ? (
          <ul className="max-h-32 overflow-auto font-mono">
            {d.skipped_files.map((file) => (
              <li key={`${file.path}-${file.reason}`}>
                {file.path} ({file.reason})
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </details>
  );
}
