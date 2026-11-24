OPS_HEALTH_WIDGET_URI = "ui://widget/ops-health.html"

OPS_HEALTH_WIDGET_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root {
    --bg: #ffffff;
    --surface: #f4f4f5;
    --border: #e4e4e7;
    --ink: #18181b;
    --muted: #71717a;
    --ok: #16a34a;
    --ok-bg: rgba(22, 163, 74, 0.12);
    --btn-bg: #18181b;
    --btn-ink: #ffffff;
  }
  [data-theme="dark"] {
    --bg: #141416;
    --surface: #1c1c1f;
    --border: #27272a;
    --ink: #fafafa;
    --muted: #a1a1aa;
    --ok: #4ade80;
    --ok-bg: rgba(74, 222, 128, 0.14);
    --btn-bg: #fafafa;
    --btn-ink: #09090b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--ink);
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    background: var(--surface);
  }
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 12px;
  }
  .title { font-size: 14px; font-weight: 700; margin: 0; }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--ok);
    background: var(--ok-bg);
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
  .meta {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
    margin-bottom: 14px;
  }
  .kv {
    padding: 9px 11px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
  }
  .kv span { display: block; font-size: 11px; color: var(--muted); margin-bottom: 2px; }
  .kv strong { font-size: 12.5px; font-weight: 600; word-break: break-all; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  button {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    background: var(--bg);
    color: var(--ink);
  }
  button.primary {
    background: var(--btn-bg);
    color: var(--btn-ink);
    border-color: var(--btn-bg);
  }
  button:disabled { opacity: 0.6; cursor: wait; }
</style>
</head>
<body>
  <div class="card">
    <div class="top">
      <h1 class="title">Vektor System Health (MCP App)</h1>
      <span class="badge"><span class="dot"></span><span id="status-text">Initializing</span></span>
    </div>
    <div class="meta">
      <div class="kv">
        <span>Service</span>
        <strong id="service-name">Vektor AI Operations</strong>
      </div>
      <div class="kv"><span>Last Checked (UTC)</span><strong id="checked-at">-</strong></div>
      <div class="kv"><span>Refreshes</span><strong id="refresh-count">0</strong></div>
    </div>
    <div class="actions">
      <button class="primary" id="btn-refresh" type="button">Refresh Health</button>
      <button id="btn-ask" type="button">Ask AI to Analyze</button>
    </div>
  </div>
<script>
(function () {
  let rpcId = 1;
  let refreshCount = 0;
  const pending = new Map();

  function sendNotification(method, params) {
    window.parent.postMessage({ jsonrpc: "2.0", method: method, params: params || {} }, "*");
  }

  function sendRequest(method, params) {
    const id = rpcId++;
    const msg = { jsonrpc: "2.0", id: id, method: method, params: params || {} };
    window.parent.postMessage(msg, "*");
    return new Promise(function (resolve, reject) {
      pending.set(id, { resolve: resolve, reject: reject });
    });
  }

  function reportHeight() {
    sendNotification("ui/size-change", { height: document.documentElement.scrollHeight });
  }

  function applyHealthPayload(raw) {
    try {
      const data = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (data && data.status) {
        document.getElementById("status-text").textContent = String(data.status).toUpperCase();
      }
      if (data && data.service) {
        document.getElementById("service-name").textContent = String(data.service);
      }
      if (data && data.timestamp_utc) {
        document.getElementById("checked-at").textContent = String(data.timestamp_utc);
      }
    } catch (_e) {}
    reportHeight();
  }

  window.addEventListener("message", function (event) {
    const msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;

    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) p.reject(msg.error);
      else p.resolve(msg.result);
      return;
    }

    if (msg.method === "ui/notifications/tool-result" && msg.params) {
      applyHealthPayload(msg.params.output);
    }
  });

  document.getElementById("btn-refresh").addEventListener("click", async function () {
    const btn = this;
    btn.disabled = true;
    try {
      const res = await sendRequest("tools/call", { name: "get_system_health", arguments: {} });
      refreshCount += 1;
      document.getElementById("refresh-count").textContent = String(refreshCount);
      if (res && res.output) applyHealthPayload(res.output);
      sendNotification("ui/update-model-context", {
        widgetState: {
          refreshCount: refreshCount,
          lastStatus: document.getElementById("status-text").textContent
        }
      });
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById("btn-ask").addEventListener("click", function () {
    const checked = document.getElementById("checked-at").textContent;
    sendNotification("ui/message", {
      text:
        "Analyze the current Vektor system health (last checked: " +
        checked +
        ", refreshes: " +
        refreshCount +
        ")."
    });
  });

  sendRequest("ui/initialize", { appInfo: { name: "ops-health-widget", version: "1.0.0" } })
    .then(function (result) {
      if (result && result.theme) {
        document.documentElement.setAttribute("data-theme", result.theme);
      }
      reportHeight();
    });
})();
</script>
</body>
</html>
"""
