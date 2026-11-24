import { parseExtraHeaders } from "./headers";
import { getSupabaseAccessToken, refreshSupabaseSession } from "./supabase";
import type {
  ChatRequest,
  ChatResponse,
  Connection,
  ConnectionCheckResult,
  ConversationDetail,
  ModelCatalog,
  ProviderSetting,
  ProviderSettingIn,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type Options = {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
  /** Overrides the timeout from Connection Settings. */
  timeoutMs?: number;
  /** Overrides the retry count from Connection Settings (GET requests only). */
  retries?: number;
};

const DEFAULT_TIMEOUT_SECONDS = 30;

function isRetryable(error: ApiError) {
  return error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504;
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Headers every request to the Next.js backend proxy carries. */
export function backendHeaders(connection: Connection, json: boolean): Record<string, string> {
  const extra = parseExtraHeaders(connection.extraHeaders).headers;
  return {
    "x-vektor-backend": connection.baseUrl,
    "x-vektor-api-key": connection.apiKey,
    ...(Object.keys(extra).length > 0
      ? { "x-vektor-extra-headers": encodeURIComponent(connection.extraHeaders?.trim() ?? "") }
      : {}),
    ...(json ? { "content-type": "application/json" } : {}),
  };
}

/** Turn a non-2xx proxy response into an ApiError with a message the user can act on. */
export async function failureFrom(response: Response): Promise<ApiError> {
  const data = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  const message =
    typeof data?.detail === "string"
      ? data.detail
      : response.status === 401
        ? "The backend rejected this API key. Check Connection Settings."
        : response.status === 429
          ? "Request limit reached. Wait a moment, then try again."
          : "The backend could not complete this request.";
  return new ApiError(message, response.status);
}

async function request<T>(path: string, connection: Connection, options: Options, timeoutMs: number): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;

  const headers = backendHeaders(
    connection,
    options.body !== undefined && !(options.body instanceof FormData),
  );
  const accessToken = await getSupabaseAccessToken();
  if (accessToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const send = () =>
    fetch(`/api/backend/${path}`, {
      method: options.method ?? "GET",
      headers,
      body:
        options.body instanceof FormData
          ? options.body
          : options.body === undefined
            ? undefined
            : JSON.stringify(options.body),
      signal,
      cache: "no-store",
    });

  let response: Response;
  try {
    response = await send();
    // An expired token is a 401 even though the session is still valid: refresh once.
    if (response.status === 401 && headers.Authorization) {
      const refreshed = await refreshSupabaseSession();
      if (refreshed) {
        headers.Authorization = `Bearer ${refreshed}`;
        response = await send();
      }
    }
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(`No response after ${Math.round(timeoutMs / 1000)}s. Raise the request timeout in Connection Settings.`, 0);
    }
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Could not reach the frontend server. Try again.", 0);
  }

  if (!response.ok) throw await failureFrom(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function api<T>(path: string, connection: Connection, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const timeoutMs = options.timeoutMs ?? (connection.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS) * 1000;
  const retries = method === "GET" ? Math.max(0, options.retries ?? connection.maxRetries ?? 0) : 0;

  let lastError: ApiError | null = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await request<T>(path, connection, options, timeoutMs);
    } catch (error) {
      if (error instanceof ApiError && isRetryable(error) && attempt < retries) {
        lastError = error;
        await sleep(300 * 2 ** attempt);
        continue;
      }
      throw error;
    }
  }
  throw lastError ?? new ApiError("The request failed.", 0);
}

export function sendChat(connection: Connection, request: ChatRequest, signal?: AbortSignal) {
  // Model calls routinely take longer than ordinary reads, so never go below 60 seconds.
  const timeoutMs = Math.max(connection.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS, 60) * 1000;
  return api<ChatResponse>("chat", connection, { method: "POST", body: request, signal, timeoutMs });
}

/** Summarize older turns into one message; slow because it calls the provider. */
export function compactConversation(connection: Connection, conversationId: string) {
  return api<ConversationDetail>(`conversations/${encodeURIComponent(conversationId)}/compact`, connection, {
    method: "POST",
    timeoutMs: Math.max(connection.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS, 60) * 1000,
  });
}

/** Ask the provider which models exist, using the draft endpoint/key from the form. */
export function listProviderModels(
  connection: Connection,
  payload: { provider: string; base_url?: string | null; api_key?: string | null },
) {
  return api<ModelCatalog>("providers/models", connection, {
    method: "POST",
    body: payload,
    timeoutMs: 20_000,
  });
}

export function getProviderSettings(connection: Connection) {
  return api<ProviderSetting>("providers", connection);
}

export function upsertProviderSettings(connection: Connection, payload: ProviderSettingIn) {
  return api<ProviderSetting>("providers", connection, {
    method: "POST",
    body: payload,
  });
}

export function testProviderConnection(connection: Connection, payload: ProviderSettingIn) {
  return api<ConnectionCheckResult>("providers/test", connection, {
    method: "POST",
    body: payload,
    timeoutMs: 15_000,
  });
}

export function clearProviderApiKey(connection: Connection) {
  return api<void>("providers/api-key", connection, { method: "DELETE" });
}
