import { NextRequest } from "next/server";
import { z } from "zod";
import { AnalysisIdSchema } from "@/lib/types";
import { serverAnalyzer } from "@/lib/api/server";
import { runInvestigation } from "@/lib/investigation/service";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const BodySchema = z.object({
  analysis_id: AnalysisIdSchema,
  question: z.string().min(8).max(2000),
});

export async function POST(request: NextRequest) {
  let json: unknown;
  try {
    json = await request.json();
  } catch {
    return Response.json(
      { ok: false, error: { code: "invalid_request", message: "Expected a JSON body." } },
      { status: 400 },
    );
  }

  const parsed = BodySchema.safeParse(json);
  if (!parsed.success) {
    return Response.json(
      {
        ok: false,
        error: {
          code: "invalid_request",
          message: "Provide a valid analysis_id and a question between 8 and 2000 characters.",
        },
      },
      { status: 400 },
    );
  }

  const result = await runInvestigation(serverAnalyzer(), {
    analysisId: parsed.data.analysis_id,
    question: parsed.data.question,
  });

  const status = result.ok ? 200 : result.error.code === "ai_not_configured" ? 503 : 422;
  return Response.json(result, { status });
}
