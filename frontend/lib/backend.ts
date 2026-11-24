type BackendRequest = {
  path: string[];
  method: string;
  baseUrl: string | null;
  apiKey: string | null;
  allowedOrigins?: string;
  defaultBaseUrl?: string;
};

type ResolvedRequest = { url: string; apiKey?: string } | { error: string };

const routes: Record<string, string[]> = {
  chat: ["POST"],
  "chat/stream": ["POST"],
  conversations: ["GET"],
  "conversations/:id": ["GET", "DELETE"],
  "conversations/:id/compact": ["POST"],
  "knowledge/documents": ["GET"],
  "knowledge/documents/upload": ["POST"],
  "knowledge/documents/:id": ["DELETE"],
  "knowledge/search": ["POST"],
  usage: ["GET"],
  "usage/timeseries": ["GET"],
  "usage/breakdown": ["GET"],
  me: ["GET"],
  providers: ["GET", "POST"],
  "providers/models": ["POST"],
  "providers/test": ["POST"],
  "providers/api-key": ["DELETE"],
  health: ["GET"],
};

export function buildBackendRequest(input: BackendRequest): ResolvedRequest {
  const resource = input.path.join("/");
  let id = "";
  const match = Object.keys(routes).find((route) => {
    const routeParts = route.split("/");
    return (
      routeParts.length === input.path.length &&
      routeParts.every((part, index) => {
        if (part.startsWith(":")) {
          id = input.path[index];
          return true;
        }
        return part === input.path[index];
      })
    );
  });

  if (
    !match ||
    (id && !/^[a-f\d-]{36}$/i.test(id)) ||
    !routes[match].includes(input.method) ||
    input.path.some((part) => !part || part === "." || part === "..")
  ) {
    return { error: "This backend endpoint is not available to the frontend." };
  }

  let url: URL;
  try {
    url = new URL(input.baseUrl || input.defaultBaseUrl || "http://127.0.0.1:8000");
  } catch {
    return { error: "Enter a valid backend URL." };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { error: "Backend URL must use HTTP or HTTPS." };
  }
  if (url.username || url.password || url.search || url.hash) {
    return { error: "Backend URL must not contain credentials, a query, or a fragment." };
  }

  const allowed = (input.allowedOrigins ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  const localDefault = new URL(input.defaultBaseUrl || "http://127.0.0.1:8000").origin;
  if (url.origin !== localDefault && !allowed.includes(url.origin)) {
    return { error: "This backend origin is not allowed by the frontend server." };
  }

  const basePath = url.pathname.replace(/\/$/, "");
  url.pathname = `${basePath}/api/v1/${resource}`.replace(/\/+/g, "/");
  return { url: url.toString(), ...(input.apiKey ? { apiKey: input.apiKey } : {}) };
}
