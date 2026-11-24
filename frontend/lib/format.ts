function trimDecimal(value: number) {
  return (Math.round(value * 10) / 10).toString();
}

export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${trimDecimal(value / 1_000_000_000)}B`;
  if (abs >= 1_000_000) return `${trimDecimal(value / 1_000_000)}M`;
  if (abs >= 1_000) return `${trimDecimal(value / 1_000)}k`;
  return String(Math.round(value));
}

/** Percentage change versus the previous period, or null when there is nothing to compare. */
export function percentChange(current: number, previous: number): number | null {
  if (previous <= 0) return null;
  return ((current - previous) / previous) * 100;
}

/** The backend returns naive UTC timestamps for some databases; treat those as UTC. */
export function parseApiDate(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function formatDateTime(value: string | Date): string {
  const date = typeof value === "string" ? parseApiDate(value) : value;
  if (Number.isNaN(date.getTime())) return "Unknown";
  const day = date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const time = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  return `${day} \u2022 ${time}`;
}

export function formatDate(value: string | Date): string {
  const date = typeof value === "string" ? parseApiDate(value) : value;
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function plural(count: number, unit: string) {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

export function relativeTime(value: string, now = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - parseApiDate(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return plural(Math.floor(seconds / 60), "minute");
  if (seconds < 86_400) return plural(Math.floor(seconds / 3600), "hour");
  if (seconds < 7 * 86_400) return plural(Math.floor(seconds / 86_400), "day");
  return formatDate(value);
}

export type DocumentTone = "pdf" | "doc" | "md" | "text" | "data" | "image";

export function documentType(source: string, title: string): { label: string; tone: DocumentTone; badge: string } {
  const name = /\.[a-z0-9]+$/i.test(source) ? source : title;
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  switch (ext) {
    case "pdf": return { label: "PDF", tone: "pdf", badge: "PDF" };
    case "docx": return { label: "Word", tone: "doc", badge: "DOC" };
    case "md":
    case "markdown": return { label: "Markdown", tone: "md", badge: "md" };
    case "csv": return { label: "CSV", tone: "data", badge: "csv" };
    case "json": return { label: "JSON", tone: "data", badge: "json" };
    case "png":
    case "jpg":
    case "jpeg":
    case "webp": return { label: "Image", tone: "image", badge: "img" };
    default: return { label: "Text", tone: "text", badge: "txt" };
  }
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0];
  return letters.toUpperCase();
}

/** "alice.smith@example.com" -> "Alice Smith"; "dev" -> "Dev". */
export function nameFromUserId(userId: string): string {
  const local = userId.split("@")[0] ?? userId;
  return local
    .split(/[._\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || userId;
}
