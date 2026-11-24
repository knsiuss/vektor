import { describe, expect, it } from "vitest";

import { contextLevel, contextPercent, formatTokens } from "./context";

const base = {
  used_tokens: 0,
  limit_tokens: 3500,
  included_messages: 0,
  total_messages: 0,
};

describe("contextPercent", () => {
  it("rounds usage against the configured limit", () => {
    expect(contextPercent({ ...base, used_tokens: 1750 })).toBe(50);
  });

  it("clamps a conversation that exceeded the limit", () => {
    expect(contextPercent({ ...base, used_tokens: 9000 })).toBe(100);
  });

  it("returns zero when the backend reports no limit", () => {
    expect(contextPercent({ ...base, limit_tokens: 0, used_tokens: 10 })).toBe(0);
  });
});

describe("contextLevel", () => {
  it("maps usage bands to meter colours", () => {
    expect(contextLevel(12)).toBe("low");
    expect(contextLevel(50)).toBe("medium");
    expect(contextLevel(80)).toBe("high");
  });
});

describe("formatTokens", () => {
  it("keeps small counts exact and abbreviates thousands", () => {
    expect(formatTokens(850)).toBe("850");
    expect(formatTokens(3500)).toBe("3.5k");
    expect(formatTokens(24000)).toBe("24k");
  });
});
