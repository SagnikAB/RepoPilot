import { SOURCE_CONTEXT_LINES } from "./config";
import type { SourceQuery } from "./api/client";
import type { SourceReference } from "./types";

export function splitSourceLines(content: string): string[] {
  if (content === "") {
    return [];
  }
  const parts = content.split("\n");
  if (parts[parts.length - 1] === "") {
    parts.pop();
  }
  return parts;
}

export function sourceWindowForLocation(location: SourceReference, extra = SOURCE_CONTEXT_LINES): SourceQuery {
  const start = Math.max(1, location.start_line - extra);
  return {
    path: location.path,
    start_line: start,
    end_line: location.end_line + extra,
  };
}

export function sourceWindowForNode(
  node: { path: string; start_line: number; end_line: number },
  extra = SOURCE_CONTEXT_LINES,
): SourceQuery {
  return sourceWindowForLocation(
    { path: node.path, start_line: node.start_line, end_line: node.end_line },
    extra,
  );
}

export function sourceWindowForLine(path: string, line: number, extra = SOURCE_CONTEXT_LINES): SourceQuery {
  return {
    path,
    start_line: Math.max(1, line - extra),
    end_line: line + extra,
  };
}

export function githubUrlPattern(): RegExp {
  return /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/;
}
