/** How many characters to reveal this tick: slow when caught up, faster when a backlog builds. */
export function revealSize(backlog: number): number {
  if (backlog <= 0) return 0;
  return Math.min(backlog, Math.max(2, Math.min(40, Math.ceil(backlog / 14))));
}

/** Cut index that never splits a surrogate pair (emoji and other astral characters). */
export function safeCut(text: string, wanted: number): number {
  if (wanted >= text.length) return text.length;
  const code = text.charCodeAt(wanted - 1);
  return code >= 0xd800 && code <= 0xdbff ? wanted + 1 : wanted;
}

/**
 * Reveals pushed text gradually, like ChatGPT or Claude. Network chunks (or a whole answer
 * that arrives at once) go into a buffer that is drained at a steady, adaptive pace.
 * With reduced-motion enabled, or in a background tab, text is shown immediately.
 */
export class Typewriter {
  private pending = "";
  private shown = "";
  private timer: number | undefined;
  private cancelled = false;
  private waiters: Array<() => void> = [];
  private readonly instant: boolean;

  constructor(
    private readonly onUpdate: (text: string) => void,
    instant?: boolean,
  ) {
    this.instant =
      instant ??
      (typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  push(text: string): void {
    if (this.cancelled || !text) return;
    if (this.instant) {
      this.shown += text;
      this.onUpdate(this.shown);
      return;
    }
    this.pending += text;
    this.schedule();
  }

  /** Resolves once everything pushed so far has been revealed. */
  finish(): Promise<void> {
    if (this.pending === "") return Promise.resolve();
    return new Promise((resolve) => {
      this.waiters.push(resolve);
      this.schedule();
    });
  }

  /** Stop revealing and drop anything still buffered. */
  cancel(): void {
    this.cancelled = true;
    this.pending = "";
    if (this.timer !== undefined) window.clearTimeout(this.timer);
    this.timer = undefined;
    this.release();
  }

  private schedule(): void {
    if (this.timer === undefined) this.timer = window.setTimeout(() => this.tick(), 16);
  }

  private release(): void {
    const waiters = this.waiters;
    this.waiters = [];
    for (const resolve of waiters) resolve();
  }

  private tick(): void {
    this.timer = undefined;
    if (this.cancelled) return;
    const hidden = typeof document !== "undefined" && document.hidden;
    const count = hidden ? this.pending.length : safeCut(this.pending, revealSize(this.pending.length));
    this.shown += this.pending.slice(0, count);
    this.pending = this.pending.slice(count);
    this.onUpdate(this.shown);
    if (this.pending) {
      this.schedule();
      return;
    }
    this.release();
  }
}
