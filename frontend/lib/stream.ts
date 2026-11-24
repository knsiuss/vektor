import { ApiError, backendHeaders, failureFrom } from "./api";
import { getSupabaseAccessToken, refreshSupabaseSession } from "./supabase";
import { parseSse } from "./sse";
import type { ChatRequest, ChatStreamEvent, Connection } from "./types";

/**
 * Send a chat turn and deliver server-sent events as they arrive.
 *
 * Resolves once the backend reports `done` or `error`. Rejects if the request fails, the
 * connection drops, or nothing arrives for longer than the idle limit (never below 60s, so
 * slow tool calls are not mistaken for a dead connection).
 */
export async function streamChat(
  connection: Connection,
  request: ChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const idleMs = Math.max(connection.timeoutSeconds ?? 30, 60) * 1000;
  const controller = new AbortController();
  let idled = false;
  let timer: number | undefined;
  const arm = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      idled = true;
      controller.abort();
    }, idleMs);
  };
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort, { once: true });

  let finished = false;
  const deliver = (events: ChatStreamEvent[]) => {
    for (const event of events) {
      if (event.event === "done" || event.event === "error") finished = true;
      onEvent(event);
    }
  };

  arm();
  try {
    let response: Response;
    // Chat must carry the signed-in identity, otherwise the turn is recorded anonymously.
    const accessToken = await getSupabaseAccessToken();
    const headers: Record<string, string> = backendHeaders(connection, true);
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const send = () =>
      fetch("/api/backend/chat/stream", {
        method: "POST",
        headers,
        body: JSON.stringify(request),
        signal: controller.signal,
        cache: "no-store",
      });
    try {
      response = await send();
      if (response.status === 401 && headers.Authorization) {
        const refreshed = await refreshSupabaseSession();
        if (refreshed) {
          headers.Authorization = `Bearer ${refreshed}`;
          response = await send();
        }
      }
    } catch (error) {
      if (signal?.aborted) throw error;
      if (idled) {
        throw new ApiError(
          `No response after ${Math.round(idleMs / 1000)}s. Raise the request timeout in Connection Settings.`,
          0,
        );
      }
      throw new ApiError("Could not reach the frontend server. Try again.", 0);
    }

    if (!response.ok) throw await failureFrom(response);
    if (!response.body) throw new ApiError("This browser could not read the streamed answer.", 0);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (error) {
        if (signal?.aborted) throw error;
        throw new ApiError(
          idled
            ? "The answer stopped arriving. Try again."
            : "The connection was interrupted before the answer finished.",
          0,
        );
      }
      if (chunk.done) break;
      arm();
      buffer += decoder.decode(chunk.value, { stream: true });
      const parsed = parseSse(buffer);
      buffer = parsed.rest;
      deliver(parsed.events);
    }

    // The stream may end without a trailing blank line; flush what is left.
    deliver(parseSse(`${buffer + decoder.decode()}\n\n`).events);
    if (!finished) throw new ApiError("The connection was interrupted before the answer finished.", 0);
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }
}
