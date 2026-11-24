import { describe, expect, it } from "vitest";

import { buildBackendRequest } from "./backend";

const config = {
  baseUrl: "http://127.0.0.1:8000",
  apiKey: "local-test-key",
  allowedOrigins: "https://staging.example.com",
  defaultBaseUrl: "http://127.0.0.1:8000",
};

describe("backend connection boundary", () => {
  it("uses the configured local backend without exposing its key in the URL", () => {
    expect(buildBackendRequest({ path: ["chat"], method: "POST", ...config })).toEqual({
      url: "http://127.0.0.1:8000/api/v1/chat",
      apiKey: "local-test-key",
    });
  });

  it("only allows explicitly configured remote backend origins", () => {
    expect(
      buildBackendRequest({
        ...config,
        path: ["usage"],
        method: "GET",
        baseUrl: "https://staging.example.com",
      }),
    ).toEqual({
      url: "https://staging.example.com/api/v1/usage",
      apiKey: "local-test-key",
    });
    expect(
      buildBackendRequest({
        ...config,
        path: ["usage"],
        method: "GET",
        baseUrl: "https://unapproved.example.com",
      }),
    ).toEqual({ error: "This backend origin is not allowed by the frontend server." });
  });

  it("allows the model discovery and compaction endpoints", () => {
    expect(
      buildBackendRequest({ ...config, path: ["providers", "models"], method: "POST" }),
    ).toEqual({
      url: "http://127.0.0.1:8000/api/v1/providers/models",
      apiKey: "local-test-key",
    });
    expect(
      buildBackendRequest({
        ...config,
        path: ["conversations", "0f0e4b2a-1111-2222-3333-444455556666", "compact"],
        method: "POST",
      }),
    ).toEqual({
      url: "http://127.0.0.1:8000/api/v1/conversations/0f0e4b2a-1111-2222-3333-444455556666/compact",
      apiKey: "local-test-key",
    });
  });

  it("rejects non-http schemes and unsupported paths", () => {
    expect(
      buildBackendRequest({ ...config, path: ["chat"], method: "POST", baseUrl: "ftp://localhost/secret" }),
    ).toEqual({ error: "Backend URL must use HTTP or HTTPS." });
    expect(
      buildBackendRequest({ ...config, path: ["settings"], method: "GET" }),
    ).toEqual({ error: "This backend endpoint is not available to the frontend." });
  });
});
