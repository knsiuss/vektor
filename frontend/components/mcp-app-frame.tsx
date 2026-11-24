"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Connection, ToolCall } from "@/lib/types";

type UIResourcePayload = {
  uri: string;
  name: string;
  mime_type: string;
  html: string;
};

type JsonRpcMessage = {
  jsonrpc?: string;
  id?: string | number;
  method?: string;
  params?: Record<string, unknown>;
};

const RESOURCE_CACHE = new Map<string, UIResourcePayload>();

export function McpAppFrame({
  tool,
  connection,
  onSendMessage,
  onWidgetState,
}: {
  tool: ToolCall;
  connection: Connection;
  onSendMessage?: (text: string) => void;
  onWidgetState?: (callId: string, state: unknown) => void;
}) {
  const uri = tool.ui_resource_uri;
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [resource, setResource] = useState<UIResourcePayload | null>(() =>
    uri ? (RESOURCE_CACHE.get(uri) ?? null) : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [height, setHeight] = useState<number>(210);

  useEffect(() => {
    if (!uri) return;
    const cached = RESOURCE_CACHE.get(uri);
    if (cached) {
      setResource(cached);
      return;
    }
    let cancelled = false;
    void api<UIResourcePayload>(
      `mcp/resources?uri=${encodeURIComponent(uri)}`,
      connection,
    )
      .then((res) => {
        RESOURCE_CACHE.set(uri, res);
        if (!cancelled) {
          setResource(res);
          setError(null);
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Failed to load MCP App widget.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [uri, connection]);

  useEffect(() => {
    if (!resource) return;
    const handleMessage = async (event: MessageEvent) => {
      const win = iframeRef.current?.contentWindow;
      if (!win || event.source !== win) return;
      const msg = event.data as JsonRpcMessage | null;
      if (!msg || msg.jsonrpc !== "2.0" || !msg.method) return;

      const reply = (result: unknown, rpcError?: { code: number; message: string }) => {
        if (msg.id === undefined) return;
        win.postMessage(
          rpcError
            ? { jsonrpc: "2.0", id: msg.id, error: rpcError }
            : { jsonrpc: "2.0", id: msg.id, result },
          "*",
        );
      };

      if (msg.method === "ui/initialize") {
        const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
        reply({
          theme,
          hostInfo: { name: "Vektor", version: "0.1.0" },
        });
        win.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-input",
            params: { toolName: tool.tool_name, arguments: tool.arguments },
          },
          "*",
        );
        win.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { callId: tool.call_id, status: tool.status, output: tool.output },
          },
          "*",
        );
        return;
      }

      if (msg.method === "ui/size-change") {
        const nextHeight = Number(msg.params?.height ?? 210);
        if (Number.isFinite(nextHeight)) {
          setHeight(Math.max(140, Math.min(520, Math.ceil(nextHeight))));
        }
        return;
      }

      if (msg.method === "ui/message") {
        const text = typeof msg.params?.text === "string" ? msg.params.text.trim() : "";
        if (text) onSendMessage?.(text);
        return;
      }

      if (msg.method === "ui/update-model-context") {
        onWidgetState?.(tool.call_id, msg.params?.widgetState ?? msg.params ?? {});
        return;
      }

      if (msg.method === "tools/call") {
        const name = typeof msg.params?.name === "string" ? msg.params.name : "";
        const args =
          msg.params?.arguments && typeof msg.params.arguments === "object"
            ? (msg.params.arguments as Record<string, unknown>)
            : {};
        try {
          const result = await api<ToolCall>("mcp/tools/call", connection, {
            method: "POST",
            body: { name, arguments: args, allow_mutating: false },
          });
          reply(result);
        } catch (cause) {
          reply(null, {
            code: -32000,
            message: cause instanceof Error ? cause.message : "Tool call failed.",
          });
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [resource, tool, connection, onSendMessage, onWidgetState]);

  if (!uri) return null;
  if (error) {
    return (
      <div className="mcp-widget-error" role="status">
        Widget unavailable ({uri}): {error}
      </div>
    );
  }
  if (!resource) {
    return <div className="mcp-widget-loading">Loading MCP App widget...</div>;
  }

  return (
    <div className="mcp-widget-card">
      <div className="mcp-widget-bar">
        <span>{resource.name}</span>
        <code>{resource.uri}</code>
      </div>
      <iframe
        ref={iframeRef}
        className="mcp-widget-iframe"
        title={resource.name}
        sandbox="allow-scripts"
        srcDoc={resource.html}
        style={{ height: `${height}px` }}
      />
    </div>
  );
}
