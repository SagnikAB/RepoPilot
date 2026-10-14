export function Badge({
  children,
  tone = "neutral",
}: {
  children: string;
  tone?: "neutral" | "ok" | "warn" | "danger" | "accent";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-surface-2 text-muted border-border",
    ok: "bg-ok/15 text-ok border-ok/30",
    warn: "bg-warn/15 text-warn border-warn/30",
    danger: "bg-danger/15 text-danger border-danger/30",
    accent: "bg-accent/15 text-accent border-accent/30",
  };
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function statusTone(status: string): "ok" | "warn" | "danger" | "neutral" {
  if (status === "completed" || status === "ok") {
    return "ok";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "running" || status === "queued") {
    return "warn";
  }
  return "neutral";
}
