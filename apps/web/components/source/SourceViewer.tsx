"use client";

import { Highlight, themes } from "prism-react-renderer";
import { splitSourceLines } from "@/lib/source";
import { useInvestigation } from "../workspace/InvestigationProvider";

function prismLanguage(language: string): string {
  if (language === "javascript") {
    return "javascript";
  }
  if (language === "typescript") {
    return "tsx";
  }
  return "clike";
}

export function SourceViewer() {
  const { source, loadMoreSource } = useInvestigation();

  if (source.status === "idle") {
    return (
      <div className="h-full p-3 text-sm text-muted">
        Select a finding, graph node, call site, or path step to load source from the analyzer.
      </div>
    );
  }
  if (source.status === "loading") {
    return <p className="p-3 text-sm text-muted">Loading {source.target.path}…</p>;
  }
  if (source.status === "error") {
    return (
      <div className="p-3 text-sm">
        <p className="text-danger">{source.message}</p>
        <p className="text-xs text-muted">
          {source.target.path}:{source.target.highlight_start}–{source.target.highlight_end}
        </p>
      </div>
    );
  }

  const lines = splitSourceLines(source.data.content);
  const emptyFile = source.data.total_lines === 0 && source.data.end_line === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
        <span className="font-mono">{source.data.path}</span>
        <span className="text-muted">
          lines {source.data.start_line}–{source.data.end_line} of {source.data.total_lines}
        </span>
        <span className="text-muted">{source.target.label}</span>
        {source.data.redacted_values > 0 ? (
          <span className="text-warn">{source.data.redacted_values} redacted value(s)</span>
        ) : null}
        {source.data.truncated ? <span className="text-warn">Window truncated (500-line cap)</span> : null}
      </div>
      {emptyFile ? (
        <p className="p-3 text-sm text-muted">This file is empty.</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          <Highlight
            theme={themes.nightOwl}
            code={lines.join("\n")}
            language={prismLanguage(source.data.language)}
          >
            {({ tokens, getLineProps, getTokenProps }) => (
              <pre className="m-0 p-2 font-mono text-[12px] leading-5">
                {tokens.map((line, index) => {
                  const lineNumber = source.data.start_line + index;
                  const highlighted =
                    lineNumber >= source.target.highlight_start && lineNumber <= source.target.highlight_end;
                  const lineProps = getLineProps({ line });
                  return (
                    <div
                      key={lineNumber}
                      {...lineProps}
                      className={`${lineProps.className} flex ${highlighted ? "bg-accent/20" : ""}`}
                    >
                      <span className="w-12 shrink-0 select-none pr-3 text-right text-muted">{lineNumber}</span>
                      <span className="min-w-0 whitespace-pre-wrap break-all">
                        {line.map((token, tokenIndex) => (
                          <span key={tokenIndex} {...getTokenProps({ token })} />
                        ))}
                      </span>
                    </div>
                  );
                })}
              </pre>
            )}
          </Highlight>
        </div>
      )}
      {source.data.truncated ? (
        <button type="button" className="border-t border-border px-3 py-2 text-xs text-accent" onClick={loadMoreSource}>
          Load next 500-line window
        </button>
      ) : null}
    </div>
  );
}
