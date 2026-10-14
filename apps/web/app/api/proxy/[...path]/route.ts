import { NextRequest } from "next/server";
import { ANALYZE_TIMEOUT_MS, DEFAULT_FETCH_TIMEOUT_MS, getAnalyzerBaseUrl } from "@/lib/config";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const ALLOWED_METHODS = new Set(["GET", "POST"]);

function targetUrl(request: NextRequest, path: string[]): URL {
  const base = getAnalyzerBaseUrl();
  const url = new URL(path.map(encodeURIComponent).join("/"), `${base}/`);
  url.search = request.nextUrl.search;
  if (!url.href.startsWith(base)) {
    throw new Error("Refusing to proxy outside the configured analyzer");
  }
  return url;
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  if (!ALLOWED_METHODS.has(request.method)) {
    return Response.json(
      { error: { code: "method_not_allowed", message: "Use GET or POST." } },
      { status: 405 },
    );
  }

  let url: URL;
  try {
    url = targetUrl(request, path);
  } catch (error) {
    return Response.json(
      {
        error: {
          code: "invalid_request",
          message: error instanceof Error ? error.message : "Invalid analyzer configuration",
        },
      },
      { status: 500 },
    );
  }

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const isAnalyze = path.join("/") === "api/analyze" && request.method === "POST";
  const timeoutMs = isAnalyze ? ANALYZE_TIMEOUT_MS : DEFAULT_FETCH_TIMEOUT_MS;
  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "backend_unavailable",
          message: "The analyzer is unavailable. Confirm it is running and ANALYZER_API_URL is correct.",
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  const retryAfter = upstream.headers.get("Retry-After");
  if (retryAfter) {
    responseHeaders.set("Retry-After", retryAfter);
  }
  const contentTypeOut = upstream.headers.get("content-type");
  if (contentTypeOut) {
    responseHeaders.set("Content-Type", contentTypeOut);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}
