import type { ZodType } from "zod";
import {
  AnalyzerApiError,
  InvalidResponseError,
  errorFromResponseBody,
  parseRetryAfter,
} from "../errors";

export type FetchJsonOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs: number;
  signal?: AbortSignal;
};

export async function fetchJson<T>(
  url: string,
  schema: ZodType<T>,
  options: FetchJsonOptions,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("timeout"), options.timeoutMs);
  const onParentAbort = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", onParentAbort);

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch {
    if (controller.signal.aborted && controller.signal.reason === "timeout") {
      throw new AnalyzerApiError({
        status: 0,
        code: "request_timeout",
        message:
          options.timeoutMs >= 200_000
            ? "The analysis request timed out. The analyzer may still be working, or the clone/parse limits were exceeded."
            : "The analyzer did not respond in time.",
      });
    }
    throw new AnalyzerApiError({
      status: 0,
      code: "backend_unavailable",
      message: "The analyzer is unavailable. Confirm it is running and reachable.",
    });
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", onParentAbort);
  }

  const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
  const rawText = await response.text();
  let parsedJson: unknown = undefined;
  if (rawText.length > 0) {
    try {
      parsedJson = JSON.parse(rawText) as unknown;
    } catch {
      if (!response.ok) {
        throw errorFromResponseBody(response.status, undefined, retryAfter);
      }
      throw new InvalidResponseError("The analyzer returned non-JSON data.", response.status);
    }
  }

  if (!response.ok) {
    throw errorFromResponseBody(response.status, parsedJson, retryAfter);
  }

  const validated = schema.safeParse(parsedJson);
  if (!validated.success) {
    throw new InvalidResponseError(
      "The analyzer response did not match the documented contract.",
      response.status,
    );
  }
  return validated.data;
}

export function serializeQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue;
    }
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}
