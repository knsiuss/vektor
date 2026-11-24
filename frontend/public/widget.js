(function () {
  var script = document.currentScript;
  if (!script) return;
  var key = script.getAttribute("data-widget-key");
  if (!key) return;

  var baseUrl = script.getAttribute("data-base-url") || new URL(script.src).origin;
  var isOpen = false;

  var container = document.createElement("div");
  container.style.cssText =
    "position:fixed;bottom:20px;right:20px;z-index:2147483647;font-family:system-ui,sans-serif;";

  var iframe = document.createElement("iframe");
  iframe.src = baseUrl + "/embed/" + encodeURIComponent(key);
  iframe.title = "Chat Widget";
  iframe.style.cssText =
    "display:none;width:380px;height:560px;max-width:calc(100vw - 32px);max-height:calc(100vh - 96px);border:none;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,0.18);margin-bottom:12px;background:#fff;";

  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-label", "Toggle chat");
  btn.textContent = "Chat";
  btn.style.cssText =
    "display:block;margin-left:auto;padding:12px 18px;border-radius:9999px;border:none;background:#2563eb;color:#fff;font-weight:600;font-size:14px;cursor:pointer;box-shadow:0 4px 14px rgba(37,99,235,0.4);";

  btn.addEventListener("click", function () {
    isOpen = !isOpen;
    iframe.style.display = isOpen ? "block" : "none";
    btn.textContent = isOpen ? "Close" : "Chat";
  });

  container.appendChild(iframe);
  container.appendChild(btn);
  document.body.appendChild(container);
})();
