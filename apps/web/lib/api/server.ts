import { getAnalyzerBaseUrl } from "../config";
import { createAnalyzerClient } from "./client";

export function serverAnalyzer() {
  return createAnalyzerClient(getAnalyzerBaseUrl());
}
