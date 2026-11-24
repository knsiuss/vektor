export type ActivityKind = "session" | "settings" | "knowledge" | "auth";
export type ActivityItem = { id: string; label: string; kind: ActivityKind; at: string };

const ACTIVITY_KEY = "vektor:activity";
const PROFILE_KEY = "vektor:profile";
const FIRST_SEEN_KEY = "vektor:first-seen";
const THEME_KEY = "vektor:theme";

function read<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage unavailable: continue without persistence.
  }
}

function isItem(value: unknown): value is ActivityItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" && typeof item.label === "string" && typeof item.at === "string";
}

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Local, per-browser activity trail shown in the profile dialog. It is not an audit log. */
export function loadActivity(): ActivityItem[] {
  const value = read<unknown>(ACTIVITY_KEY, []);
  return Array.isArray(value) ? value.filter(isItem) : [];
}

export function addActivity(label: string, kind: ActivityKind): ActivityItem[] {
  const next = [{ id: newId(), label, kind, at: new Date().toISOString() }, ...loadActivity()].slice(0, 50);
  write(ACTIVITY_KEY, next);
  return next;
}

export function loadProfileName(): string | null {
  const value = read<{ name?: unknown }>(PROFILE_KEY, {});
  return typeof value.name === "string" && value.name.trim() ? value.name : null;
}

export function saveProfileName(name: string | null) {
  write(PROFILE_KEY, { name: name?.trim() || null });
}

export function loadFirstSeen(): string {
  const existing = read<string | null>(FIRST_SEEN_KEY, null);
  if (typeof existing === "string") return existing;
  const now = new Date().toISOString();
  write(FIRST_SEEN_KEY, now);
  return now;
}

export type Theme = "light" | "dark";

/** Saved preference wins; dark is the default for first-time visitors. */
export function loadTheme(): Theme {
  return read<string>(THEME_KEY, "dark") === "light" ? "light" : "dark";
}

export function saveTheme(theme: Theme) {
  write(THEME_KEY, theme);
}
