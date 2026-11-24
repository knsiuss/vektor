import { type NextRequest, NextResponse } from "next/server";

import { buildBackendRequest } from "@/lib/backend";
import { parseExtraHeaders } from "@/lib/headers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

/** A saved localhost backend is meaningless on a deployed host; fall back to the server default. */
function usableBackendHeader(request: NextRequest): string | null {
  const raw = request.headers.get("x-vektor-backend");
  if (!raw) return null;
  let host = "";
  try {
    host = new URL(raw).hostname;
  } catch {
    return raw;
  }
  const pageHost = request.nextUrl.hostname;
  if (LOOPBACK_HOSTS.has(host) && !LOOPBACK_HOSTS.has(pageHost)) return null;
  return raw;
}

async function forward(
  request: NextRequest,
  { params }: { params: Promise<{ path?: string[] }> },
) {
  const { path = [] } = await params;
  const resolved = buildBackendRequest({
    path,
    method: request.method,
    baseUrl: usableBackendHeader(request),
    apiKey: request.headers.get("x-vektor-api-key"),
    allowedOrigins: process.env.VEKTOR_ALLOWED_BACKEND_ORIGINS,
    defaultBaseUrl: process.env.VEKTOR_BACKEND_URL,
  });

  if ("error" in resolved) {
    return NextResponse.json({ detail: resolved.error }, { status: 400 });
  }

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (resolved.apiKey) headers.set("x-api-key", resolved.apiKey);

  // OAuth uses the same origin as the app, so the browser cookie must travel both ways.
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);

  const encodedExtra = request.headers.get("x-vektor-extra-headers");
  if (encodedExtra) {
    try {
      const { headers: extra } = parseExtraHeaders(decodeURIComponent(encodedExtra));
      for (const [name, value] of Object.entries(extra)) headers.set(name, value);
    } catch {
      // Malformed extra headers are ignored; the client validates them before sending.
    }
  }

  // Forward query parameters (for example ?days=30) to the same, already allow-listed path.
  const upstreamUrl = new URL(resolved.url);
  upstreamUrl.search = request.nextUrl.search;

  try {
    const body =
      request.method === "GET" || request.method === "DELETE"
        ? undefined
        : await request.arrayBuffer();
    const upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });

    const responseHeaders = new Headers({
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store, no-transform",
      "x-accel-buffering": "no",
    });
    const location = upstream.headers.get("location");
    if (location) responseHeaders.set("location", location);
    for (const cookieHeader of upstream.headers.getSetCookie()) {
      responseHeaders.append("set-cookie", cookieHeader);
    }

    const bodyless =
      upstream.status === 204 || upstream.status === 304 || Boolean(location);
    return new NextResponse(bodyless ? null : upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    if (request.signal.aborted) return new NextResponse(null, { status: 499 });
    console.error("Vektor backend request failed", error);
    return NextResponse.json(
      { detail: "Could not reach the Vektor backend. Check the backend URL and try again." },
      { status: 502 },
    );
  }
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
