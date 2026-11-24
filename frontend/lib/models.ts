import type { ProviderModel } from "./types";

export type ModelFilter = {
  query: string;
  freeOnly: boolean;
};

/** Search across id and display name; `freeOnly` keeps models the provider priced at zero. */
export function filterModels(models: ProviderModel[], filter: ModelFilter): ProviderModel[] {
  const query = filter.query.trim().toLowerCase();
  return models.filter((model) => {
    if (filter.freeOnly && model.is_free !== true) return false;
    if (!query) return true;
    return model.id.toLowerCase().includes(query) || model.name.toLowerCase().includes(query);
  });
}

/** True when the provider published at least one model it considers free. */
export function hasFreeModels(models: ProviderModel[]): boolean {
  return models.some((model) => model.is_free === true);
}

/** 128000 -> "128k", 2000000 -> "2M", unknown -> "—". */
export function formatContextLength(value: number | null): string {
  if (!value || value <= 0) return "—";
  if (value >= 1_000_000) return `${Number((value / 1_000_000).toFixed(1))}M`;
  return `${Math.round(value / 1000)}k`;
}

/** USD per million tokens; null pricing means the provider did not publish it. */
export function formatPrice(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "Free";
  return `$${value < 1 ? value.toFixed(2) : value.toFixed(1)}/M`;
}


/**
 * Curated fallback when a provider cannot be listed (no key, offline, unsupported endpoint).
 * Used only to keep the picker usable; entries carry no pricing claim.
 */
export const FALLBACK_MODELS: Record<string, string[]> = {
  openai: ["openai/gpt-6.2-astra", "openai/gpt-6.2-sol", "openai/gpt-6.1-terra-pro"],
  anthropic: ["anthropic/claude-fable-5.2", "anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.5"],
  google: ["google/gemini-4-neon", "google/gemini-4-hydrogen", "google/gemini-omni-1.2-flash"],
  openrouter: ["liquid/lfm-3-1.7b:free", "inclusionai/ling-3.2-flash:free", "baidu/ernie-5.5-flash-preview:free"],
  mistral: ["mistralai/mistral-large-4-0", "mistralai/mistral-medium-3-5", "mistralai/mistral-small-2603"],
  deepseek: ["deepseek/deepseek-v4.1-flash-1017", "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro-0813"],
  qwen: ["qwen/qwen4-max", "qwen/qwen3.8-max-prime", "qwen/qwen3.8-flash"],
  custom: [],
};

export function fallbackModels(provider: string): ProviderModel[] {
  return (FALLBACK_MODELS[provider] ?? []).map((id) => ({
    id,
    name: id,
    context_length: null,
    prompt_price_per_million: null,
    completion_price_per_million: null,
    is_free: id.endsWith(":free") ? true : null,
  }));
}


/** Provider names arrive as "Vendor: Model"; keep the model part for the row title. */
export function cleanModelName(model: ProviderModel): string {
  const raw = model.name?.trim() || model.id;
  const separator = raw.indexOf(": ");
  if (separator === -1) return raw;
  const vendor = raw.slice(0, separator).toLowerCase();
  const vendorSlug = model.id.split("/")[0]?.toLowerCase() ?? "";
  if (vendor === vendorSlug || vendor.startsWith(vendorSlug)) return raw.slice(separator + 2);
  return raw;
}

export type ModelGroup = { key: "free" | "paid" | "unknown"; label: string; models: ProviderModel[] };

/** Split a list into free / paid / unpublished-pricing groups, preserving order. */
export function groupModels(models: ProviderModel[]): ModelGroup[] {
  const groups: ModelGroup[] = [
    { key: "free", label: "Free", models: [] },
    { key: "paid", label: "Paid", models: [] },
    { key: "unknown", label: "Pricing not published", models: [] },
  ];
  models.forEach((model) => {
    if (model.is_free === true) groups[0].models.push(model);
    else if (model.is_free === false) groups[1].models.push(model);
    else groups[2].models.push(model);
  });
  return groups.filter((group) => group.models.length > 0);
}


/** Compact label for footers: "liquid/lfm-3-1.7b:free" -> "lfm-3-1.7b". */
export function shortModelName(modelId: string | null | undefined): string {
  if (!modelId) return "";
  const withoutVendor = modelId.includes("/") ? modelId.split("/").slice(1).join("/") : modelId;
  return withoutVendor.replace(/:free$/, "");
}


