"use client";

import { FormEvent, useState } from "react";
import { githubUrlPattern } from "@/lib/source";
import { useInvestigation } from "./workspace/InvestigationProvider";

export function AnalyzeForm() {
  const { analyzing, submitAnalysis } = useInvestigation();
  const [repoUrl, setRepoUrl] = useState("https://github.com/");
  const [ref, setRef] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = repoUrl.trim();
    if (!githubUrlPattern().test(trimmed)) {
      setLocalError("Use https://github.com/<owner>/<repo> with no extra path, query, or credentials.");
      return;
    }
    setLocalError(null);
    void submitAnalysis(trimmed, ref);
  }

  return (
    <form onSubmit={onSubmit} className="flex min-w-0 flex-1 flex-wrap items-end gap-2">
      <label className="flex min-w-[16rem] flex-1 flex-col gap-1 text-xs text-muted">
        GitHub repository
        <input
          name="repo_url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          disabled={analyzing}
          spellCheck={false}
          autoComplete="off"
          placeholder="https://github.com/owner/repo"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text disabled:opacity-60"
        />
      </label>
      <label className="flex w-36 flex-col gap-1 text-xs text-muted">
        Branch or tag
        <input
          name="ref"
          value={ref}
          onChange={(event) => setRef(event.target.value)}
          disabled={analyzing}
          spellCheck={false}
          placeholder="default"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text disabled:opacity-60"
        />
      </label>
      <button
        type="submit"
        disabled={analyzing}
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground disabled:opacity-60"
      >
        {analyzing ? "Analyzing…" : "Analyze"}
      </button>
      {localError ? <p className="w-full text-xs text-danger">{localError}</p> : null}
    </form>
  );
}
