"use client";

import { useInvestigation } from "./workspace/InvestigationProvider";

export function ErrorBanner() {
  const { analysisError, health } = useInvestigation();
  if (!analysisError && health.status !== "error") {
    return null;
  }
  return (
    <div className="space-y-2 border-b border-danger/30 bg-danger/10 px-4 py-2 text-sm">
      {health.status === "error" ? (
        <p>
          <strong>Backend:</strong> {health.message}
        </p>
      ) : null}
      {analysisError ? (
        <div>
          <p>
            <strong>{analysisError.code}:</strong> {analysisError.message}
          </p>
          {analysisError.hint ? <p className="text-xs text-muted">{analysisError.hint}</p> : null}
          {analysisError.retryAfterSeconds !== null ? (
            <p className="text-xs text-muted">Retry after {analysisError.retryAfterSeconds} seconds.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
