const DEFAULT_ANALYZER_URL = "http://127.0.0.1:8000";

export const ANALYZE_TIMEOUT_MS = 240_000;
export const DEFAULT_FETCH_TIMEOUT_MS = 30_000;
export const SOURCE_CONTEXT_LINES = 5;
export const MAX_SOURCE_WINDOW = 500;

export function getAnalyzerBaseUrl(): string {
  const raw = process.env.ANALYZER_API_URL?.trim() || DEFAULT_ANALYZER_URL;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("ANALYZER_API_URL must be a valid absolute URL");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("ANALYZER_API_URL must use http or https");
  }
  if (parsed.username || parsed.password) {
    throw new Error("ANALYZER_API_URL must not contain credentials");
  }
  return parsed.origin;
}

export function getAiProviderConfig(): {
  apiKey: string;
  baseUrl: string;
  model: string;
} | null {
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) {
    return null;
  }
  const baseUrl = (process.env.OPENAI_BASE_URL?.trim() || "https://api.openai.com/v1").replace(
    /\/$/,
    "",
  );
  const model = process.env.OPENAI_MODEL?.trim() || "gpt-4o-mini";
  return { apiKey, baseUrl, model };
}
