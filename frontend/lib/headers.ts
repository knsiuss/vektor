const NAME = /^x-[a-z0-9-]{1,60}$/i;
const MAX_HEADERS = 20;
const MAX_VALUE_LENGTH = 512;

function isReserved(name: string) {
  const lower = name.toLowerCase();
  return lower === "x-api-key" || lower.startsWith("x-vektor-");
}

/**
 * Parse the "Base Headers" setting. Only X-* headers are accepted, and the ones Vektor uses
 * itself (X-API-Key, X-Vektor-*) are reserved, so a header can never override authentication.
 */
export function parseExtraHeaders(raw: string | null | undefined): {
  headers: Record<string, string>;
  error: string | null;
} {
  const text = (raw ?? "").trim();
  if (!text) return { headers: {}, error: null };

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { headers: {}, error: 'Base headers must be valid JSON, e.g. {"X-Custom-Header": "value"}.' };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { headers: {}, error: "Base headers must be a JSON object." };
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  if (entries.length > MAX_HEADERS) {
    return { headers: {}, error: `Use at most ${MAX_HEADERS} base headers.` };
  }

  const headers: Record<string, string> = {};
  for (const [name, value] of entries) {
    if (!NAME.test(name) || isReserved(name)) {
      return {
        headers: {},
        error: `Header "${name}" is not allowed. Custom headers must start with X- (X-API-Key and X-Vektor-* are reserved).`,
      };
    }
    if (typeof value !== "string" || value.length > MAX_VALUE_LENGTH || /[\r\n\0]/.test(value)) {
      return { headers: {}, error: `Header "${name}" needs a plain-text value under ${MAX_VALUE_LENGTH} characters.` };
    }
    headers[name] = value;
  }
  return { headers, error: null };
}
