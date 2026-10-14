import { ModelInvestigationSchema, type ModelInvestigation } from "./types";

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

export type ProviderConfig = {
  apiKey: string;
  baseUrl: string;
  model: string;
};

export class ProviderError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ProviderError";
    this.code = code;
  }
}

export async function completeJson(
  config: ProviderConfig,
  messages: ChatMessage[],
  timeoutMs = 45_000,
): Promise<ModelInvestigation> {
  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: config.model,
        temperature: 0,
        response_format: { type: "json_object" },
        messages,
        max_tokens: 1600,
      }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ProviderError("provider_timeout", "The AI provider timed out.");
    }
    throw new ProviderError("provider_unavailable", "The AI provider could not be reached.");
  }

  if (response.status === 401 || response.status === 403) {
    throw new ProviderError("provider_auth", "The AI provider rejected the configured credentials.");
  }
  if (response.status === 429) {
    throw new ProviderError("provider_rate_limited", "The AI provider rate-limited the request.");
  }
  if (!response.ok) {
    throw new ProviderError("provider_failed", "The AI provider returned an error.");
  }

  let payload: { choices?: Array<{ message?: { content?: string | null } }> };
  try {
    payload = (await response.json()) as {
      choices?: Array<{ message?: { content?: string | null } }>;
    };
  } catch {
    throw new ProviderError("malformed_model_output", "The AI provider returned a non-JSON response.");
  }
  const content = payload.choices?.[0]?.message?.content;
  if (!content) {
    throw new ProviderError("malformed_model_output", "The model returned an empty response.");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content) as unknown;
  } catch {
    throw new ProviderError("malformed_model_output", "The model did not return valid JSON.");
  }

  const validated = ModelInvestigationSchema.safeParse(parsed);
  if (!validated.success) {
    throw new ProviderError("schema_validation_failed", "The model JSON did not match the investigation schema.");
  }
  return validated.data;
}
