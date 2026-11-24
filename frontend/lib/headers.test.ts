import { describe, expect, it } from "vitest";

import { parseExtraHeaders } from "./headers";

describe("parseExtraHeaders", () => {
  it("accepts an empty value", () => {
    expect(parseExtraHeaders("")).toEqual({ headers: {}, error: null });
    expect(parseExtraHeaders(undefined)).toEqual({ headers: {}, error: null });
  });

  it("accepts X-* headers with string values", () => {
    expect(parseExtraHeaders('{"X-Custom-Header": "value"}')).toEqual({
      headers: { "X-Custom-Header": "value" },
      error: null,
    });
  });

  it("rejects invalid JSON and non-objects", () => {
    expect(parseExtraHeaders("{nope").error).toMatch(/valid JSON/);
    expect(parseExtraHeaders("[1]").error).toMatch(/JSON object/);
  });

  it("rejects reserved and non X- headers", () => {
    expect(parseExtraHeaders('{"X-API-Key": "stolen"}').error).toMatch(/not allowed/);
    expect(parseExtraHeaders('{"x-vektor-backend": "http://evil"}').error).toMatch(/not allowed/);
    expect(parseExtraHeaders('{"Authorization": "Bearer x"}').error).toMatch(/not allowed/);
    expect(parseExtraHeaders('{"Host": "evil"}').error).toMatch(/not allowed/);
  });

  it("rejects non-string values and header injection", () => {
    expect(parseExtraHeaders('{"X-A": 1}').error).toMatch(/plain-text/);
    expect(parseExtraHeaders('{"X-A": "a\\nX-B: b"}').error).toMatch(/plain-text/);
  });
});
