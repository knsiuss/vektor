import { describe, expect, it } from "vitest";

import { parseSse } from "./sse";
import { revealSize, safeCut, Typewriter } from "./typewriter";

const block = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify({ event, ...data })}\n\n`;

describe("parseSse", () => {
  it("parses complete events and keeps the unfinished tail", () => {
    const text = block("meta", { conversation_id: "c1" }) + block("delta", { delta: "Hel" }) + 'event: delta\ndata: {"event":"del';
    const { events, rest } = parseSse(text);
    expect(events.map((e) => e.event)).toEqual(["meta", "delta"]);
    expect(events[1].delta).toBe("Hel");
    expect(rest).toBe('event: delta\ndata: {"event":"del');
  });

  it("works when the same stream is delivered in arbitrary pieces", () => {
    const whole = block("status", { status: "Searching..." }) + block("delta", { delta: "ok" }) + block("done", {});
    for (const size of [1, 3, 7, 50]) {
      let buffer = "";
      const names: string[] = [];
      for (let i = 0; i < whole.length; i += size) {
        buffer += whole.slice(i, i + size);
        const parsed = parseSse(buffer);
        buffer = parsed.rest;
        names.push(...parsed.events.map((e) => e.event));
      }
      expect(names).toEqual(["status", "delta", "done"]);
    }
  });

  it("handles CRLF line endings and comment lines", () => {
    const { events } = parseSse(`: keep-alive\r\nevent: delta\r\ndata: {"event":"delta","delta":"x"}\r\n\r\n`);
    expect(events).toEqual([{ event: "delta", delta: "x" }]);
  });

  it("falls back to the SSE event name and skips unknown or malformed blocks", () => {
    const { events } = parseSse('event: status\ndata: {"status":"Working"}\n\nevent: nope\ndata: {"x":1}\n\ndata: {oops\n\n');
    expect(events).toEqual([{ event: "status", status: "Working" }]);
  });

  it("keeps multi-byte text intact", () => {
    const { events } = parseSse(block("delta", { delta: "Halo 👋 dunia" }));
    expect(events[0].delta).toBe("Halo 👋 dunia");
  });
});

describe("typewriter pacing", () => {
  it("reveals nothing for an empty buffer and never more than is buffered", () => {
    expect(revealSize(0)).toBe(0);
    expect(revealSize(1)).toBe(1);
    expect(revealSize(2)).toBe(2);
  });

  it("types slowly when caught up and speeds up with a backlog, within a cap", () => {
    expect(revealSize(10)).toBe(2);
    expect(revealSize(280)).toBe(20);
    expect(revealSize(100_000)).toBe(40);
  });

  it("never splits a surrogate pair", () => {
    const text = "ab👋cd";
    expect(safeCut(text, 3)).toBe(4);
    expect(safeCut(text, 2)).toBe(2);
    expect(safeCut(text, 99)).toBe(text.length);
  });

  it("shows text immediately in instant mode and ignores pushes after cancel", async () => {
    const seen: string[] = [];
    const typer = new Typewriter((text) => seen.push(text), true);
    typer.push("Hel");
    typer.push("lo");
    await typer.finish();
    expect(seen).toEqual(["Hel", "Hello"]);

    typer.cancel();
    typer.push("ignored");
    expect(seen).toEqual(["Hel", "Hello"]);
    await expect(typer.finish()).resolves.toBeUndefined();
  });
});
