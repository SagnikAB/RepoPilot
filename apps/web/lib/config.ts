const DEFAULT_ANALYZER_URL = "http://127.0.0.1:8000";
const DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1";

const PLACEHOLDER_TOKENS = [
  "your-openai-api-key-here",
  "your-api-key-here",
  "your-key-here",
  "changeme",
  "replace-me",
  "placeholder",
  "example",
  "todo",
];

function isPlaceholderValue(value: string | undefined | null): boolean {
  if (!value) {
    return true;
  }
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!normalized) {
    return true;
  }
  return PLACEHOLDER_TOKENS.some((token) => normalized.includes(token.replace(/[^a-z0-9]/g, "")));
}

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
  const pathname = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/+$/, "");
  return `${parsed.origin}${pathname}`;
}

export function getAiProviderConfig(): {
  apiKey: string;
  baseUrl: string;
  model: string;
} | null {
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey || isPlaceholderValue(apiKey)) {
    return null;
  }

  const baseUrlValue = process.env.OPENAI_BASE_URL?.trim();
  const baseUrl = isPlaceholderValue(baseUrlValue)
    ? DEFAULT_OPENAI_BASE_URL
    : (baseUrlValue || DEFAULT_OPENAI_BASE_URL).replace(/\/$/, "");

  const modelValue = process.env.OPENAI_MODEL?.trim();
  const model = isPlaceholderValue(modelValue) ? "gpt-4o-mini" : (modelValue || "gpt-4o-mini");

  return { apiKey, baseUrl, model };
}
