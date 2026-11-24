"use client";

import { useEffect, useMemo, useRef } from "react";

interface HtmlAppViewerProps {
  html: string;
  title: string;
  onHeightChange?: (height: number) => void;
}

const STRICT_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:;";

function injectCsp(html: string): string {
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${STRICT_CSP}">`;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head[^>]*>/i, (match) => `${match}${cspMeta}`);
  }
  return `<!DOCTYPE html><html><head>${cspMeta}</head><body>${html}</body></html>`;
}

export function HtmlAppViewer({ html, title, onHeightChange }: HtmlAppViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const srcDoc = useMemo(() => injectCsp(html), [html]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.source !== iframeRef.current?.contentWindow) return;
      if (typeof event.data !== "object" || event.data === null) return;
      const payload = event.data as { type?: unknown; height?: unknown };
      if (payload.type === "vektor:resize" && typeof payload.height === "number") {
        onHeightChange?.(Math.min(Math.max(payload.height, 200), 2000));
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onHeightChange]);

  return (
    <iframe
      ref={iframeRef}
      title={title}
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      className="h-full w-full border-0 bg-white"
      referrerPolicy="no-referrer"
    />
  );
}
