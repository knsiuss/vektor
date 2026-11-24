import { describe, expect, it } from "vitest";

import {
  cleanModelName,
  filterModels,
  formatContextLength,
  formatPrice,
  groupModels,
  hasFreeModels,
  shortModelName,
} from "./models";
import type { ProviderModel } from "./types";

const model = (overrides: Partial<ProviderModel>): ProviderModel => ({
  id: "vendor/model",
  name: "Vendor Model",
  context_length: null,
  prompt_price_per_million: null,
  completion_price_per_million: null,
  is_free: null,
  ...overrides,
});

describe("filterModels", () => {
  const models = [
    model({ id: "liquid/lfm:free", name: "Liquid LFM", is_free: true }),
    model({ id: "openai/gpt-4o", name: "GPT-4o", is_free: false }),
    model({ id: "meta/llama", name: "Llama", is_free: null }),
  ];

  it("keeps only free models when the free filter is on", () => {
    expect(filterModels(models, { query: "", freeOnly: true }).map((item) => item.id)).toEqual([
      "liquid/lfm:free",
    ]);
  });

  it("searches id and display name case-insensitively", () => {
    expect(filterModels(models, { query: "gpt", freeOnly: false })).toHaveLength(1);
    expect(filterModels(models, { query: "LLAMA", freeOnly: false })).toHaveLength(1);
  });

  it("shows everything when the filter is off and the query is empty", () => {
    expect(filterModels(models, { query: "", freeOnly: false })).toHaveLength(3);
  });
});

describe("hasFreeModels", () => {
  it("is false when the provider publishes no free pricing", () => {
    expect(hasFreeModels([model({ is_free: null })])).toBe(false);
    expect(hasFreeModels([model({ is_free: true })])).toBe(true);
  });
});

describe("formatContextLength", () => {
  it("abbreviates thousands and millions", () => {
    expect(formatContextLength(128000)).toBe("128k");
    expect(formatContextLength(2_000_000)).toBe("2M");
    expect(formatContextLength(null)).toBe("—");
  });
});

describe("formatPrice", () => {
  it("labels zero as Free and unknown as a dash", () => {
    expect(formatPrice(0)).toBe("Free");
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(3)).toBe("$3.0/M");
    expect(formatPrice(0.15)).toBe("$0.15/M");
  });
});

describe("cleanModelName", () => {
  it("drops a vendor prefix that repeats the id vendor", () => {
    expect(
      cleanModelName({
        id: "anthropic/claude-fable-5.2",
        name: "Anthropic: Claude Fable 5.2",
        context_length: null,
        prompt_price_per_million: null,
        completion_price_per_million: null,
        is_free: null,
      }),
    ).toBe("Claude Fable 5.2");
  });

  it("keeps names without a vendor prefix intact", () => {
    expect(
      cleanModelName({
        id: "gemini-2.0-flash",
        name: "gemini-2.0-flash",
        context_length: null,
        prompt_price_per_million: null,
        completion_price_per_million: null,
        is_free: null,
      }),
    ).toBe("gemini-2.0-flash");
  });
});

describe("groupModels", () => {
  it("splits free, paid, and unpublished pricing while keeping order", () => {
    const groups = groupModels([
      model({ id: "a", is_free: true }),
      model({ id: "b", is_free: false }),
      model({ id: "c", is_free: null }),
      model({ id: "d", is_free: true }),
    ]);
    expect(groups.map((group) => group.key)).toEqual(["free", "paid", "unknown"]);
    expect(groups[0].models.map((item) => item.id)).toEqual(["a", "d"]);
  });
});


describe("shortModelName", () => {
  it("drops the vendor prefix and the free suffix", () => {
    expect(shortModelName("liquid/lfm-3-1.7b:free")).toBe("lfm-3-1.7b");
    expect(shortModelName("anthropic/claude-sonnet-5.5")).toBe("claude-sonnet-5.5");
    expect(shortModelName(null)).toBe("");
  });
});
