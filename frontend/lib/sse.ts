import type { ChatStreamEvent, ChatStreamEventName } from "./types";

const EVENT_NAMES = new Set<string>([
  "meta",
  "status",
  "citations",
  "tool",
  "reasoning",
  "delta",
  "done",
  "error",
]);

/**
 * Split a growing text buffer into complete server-sent events. Whatever follows the last
 * blank line is returned as `rest` and must be passed back in with the next chunk.
 */
export function parseSse(buffer: string): { events: ChatStreamEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n?/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ChatStreamEvent[] = [];

  for (const block of blocks) {
    let name = "";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") name = value;
      else if (field === "data") data.push(value);
    }
    if (data.length === 0) continue;
    try {
      const parsed = JSON.parse(data.join("\n")) as Partial<ChatStreamEvent>;
      const event = String(parsed.event ?? name);
      if (!EVENT_NAMES.has(event)) continue;
      events.push({ ...parsed, event: event as ChatStreamEventName });
    } catch {
      // A malformed block carries nothing we can use; skip it rather than abort the answer.
    }
  }
  return { events, rest };
}
