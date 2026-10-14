import { ErrorBodySchema, type ErrorBody } from "./types";

export class AnalyzerApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorBody["details"];
  readonly retryAfterSeconds: number | null;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    details?: ErrorBody["details"];
    retryAfterSeconds?: number | null;
  }) {
    super(options.message);
    this.name = "AnalyzerApiError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

export class InvalidResponseError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "InvalidResponseError";
    this.status = status;
  }
}

export function parseRetryAfter(header: string | null): number | null {
  if (!header) {
    return null;
  }
  const seconds = Number(header);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return seconds;
  }
  return null;
}

export function errorFromResponseBody(
  status: number,
  body: unknown,
  retryAfterSeconds: number | null,
): AnalyzerApiError {
  const parsed = ErrorBodySchema.safeParse(
    typeof body === "object" && body !== null && "error" in body
      ? (body as { error: unknown }).error
      : body,
  );
  if (parsed.success) {
    return new AnalyzerApiError({
      status,
      code: parsed.data.code,
      message: parsed.data.message,
      details: parsed.data.details,
      retryAfterSeconds,
    });
  }
  return new AnalyzerApiError({
    status,
    code: status === 0 ? "backend_unavailable" : "http_error",
    message: userFacingHttpMessage(status),
    retryAfterSeconds,
  });
}

export function userFacingHttpMessage(status: number): string {
  if (status === 0) {
    return "The analyzer is unavailable. Confirm it is running and ANALYZER_API_URL is correct.";
  }
  if (status === 429) {
    return "Too many analyses are running. Wait and retry.";
  }
  if (status === 503) {
    return "The analyzer is not ready (git may be missing on the server).";
  }
  if (status >= 500) {
    return "The analyzer encountered an internal error. Try again later.";
  }
  return `The analyzer returned HTTP ${status}.`;
}

export function recoveryHint(code: string): string | null {
  switch (code) {
    case "invalid_repository_url":
      return "Use https://github.com/<owner>/<repo> with no credentials, ports, or extra path segments.";
    case "ref_not_found":
      return "Use a branch or tag name. Commit SHAs are not supported.";
    case "analysis_not_found":
      return "This analysis expired or the analyzer restarted. Submit the repository again.";
    case "analysis_failed":
      return "The analysis exists but failed. Review diagnostics instead of loading the graph.";
    case "too_many_analyses":
      return "Wait for the Retry-After interval, then submit again.";
    case "clone_timeout":
    case "repository_too_large":
    case "repository_unavailable":
      return "The repository cannot be cloned as given. Check that it is public and within size/time limits.";
    case "backend_unavailable":
      return "Start the analyzer (demo server or uvicorn) on port 8000, then retry.";
    default:
      return null;
  }
}
