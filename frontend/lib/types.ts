export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type GroundingReport = {
  cited_indices: number[];
  invalid_citations: number[];
  has_context_without_citations: boolean;
  ungrounded_tokens: string[];
  warnings: string[];
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model: string | null;
  created_at: string;
  citations?: Citation[];
  toolCalls?: ToolCall[];
  grounding?: GroundingReport | null;
  reasoning?: string | null;
  status?: "answer" | "clarify" | "unknown" | null;
  clarify_options?: string[] | null;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    cached_tokens?: number;
    cache_creation_tokens?: number;
  } | null;
};

export type ToolCall = {
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: "success" | "blocked" | "error";
  output: string;
  ui_resource_uri?: string | null;
};

export type Citation = {
  document_id: string;
  document_title: string;
  chunk_index: number;
  content: string;
  semantic_score: number;
  lexical_score: number;
  score: number;
};

export type ChatResponse = {
  conversation_id: string;
  reply: string;
  provider: string;
  model: string;
  citations: Citation[];
  tool_calls: ToolCall[];
  grounding?: GroundingReport | null;
  reasoning?: string | null;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    cached_tokens?: number;
    cache_creation_tokens?: number;
  } | null;
};

export type ConversationContext = {
  used_tokens: number;
  limit_tokens: number;
  included_messages: number;
  total_messages: number;
};

// Older backends omit `context`; the meter simply stays hidden in that case.
export type ConversationDetail = Conversation & {
  messages: Message[];
  context?: ConversationContext;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  source: string;
  embedding_model: string;
  chunk_count: number;
  created_at: string;
  owner_id?: string;
  visibility?: "private" | "tenant" | "shared";
};

export type Usage = {
  total_conversations: number;
  total_messages: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  by_model: {
    provider: string;
    model: string;
    assistant_turns: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  }[];
};

export type DailyPoint = {
  date: string;
  conversations: number;
  messages: number;
  tokens: number;
};

export type PeriodTotals = {
  conversations: number;
  messages: number;
  tokens: number;
};

export type Timeseries = {
  days: number;
  start: string;
  end: string;
  points: DailyPoint[];
  current: PeriodTotals;
  previous: PeriodTotals;
};

export type ToolUsageItem = {
  tool_name: string;
  calls: number;
  share: number;
  success_rate: number;
  avg_duration_ms: number;
};

export type ToolUsageReport = {
  days: number;
  total_calls: number;
  tools: ToolUsageItem[];
};

export type Me = {
  user_id: string;
  tenant_id: string;
  roles: string[];
  is_admin: boolean;
};

export type RetrievalMode = "auto" | "always" | "explicit" | "off";

export type ReasoningEffort = "low" | "medium" | "high";

export type ChatRequest = {
  message: string;
  conversation_id?: string;
  retrieval_mode: RetrievalMode;
  document_ids?: string[];
  allow_mutating_tools: boolean;
  reasoning_effort?: ReasoningEffort | null;
};

export type Connection = {
  baseUrl: string;
  apiKey: string;
  /** Seconds to wait for a response before giving up. */
  timeoutSeconds?: number;
  /** Extra attempts for read requests that fail with a network or 502/503/504 error. */
  maxRetries?: number;
  /** Raw JSON object of extra X-* headers to forward to the backend. */
  extraHeaders?: string;
};

/** AI provider selected by the user in Connection Settings. */
export type ProviderName =
  | "openai"
  | "anthropic"
  | "google"
  | "openrouter"
  | "mistral"
  | "deepseek"
  | "qwen"
  | "custom";

export type ProviderStatus = "connected" | "disconnected" | "checking";

export type ProviderSetting = {
  provider: ProviderName;
  model: string | null;
  api_key_configured: boolean;
  base_url: string | null;
  connection_status: ProviderStatus;
  connection_error: string | null;
  last_checked_at: string | null;
  latency_ms: number | null;
};

export type ProviderModel = {
  id: string;
  name: string;
  context_length: number | null;
  prompt_price_per_million: number | null;
  completion_price_per_million: number | null;
  is_free: boolean | null;
};

export type ModelCatalog = {
  provider: string;
  models: ProviderModel[];
  error: string | null;
  endpoint: string;
  source: "provider" | "directory";
};

export type ProviderSettingIn = {
  provider: ProviderName;
  model: string | null;
  api_key: string | null;
  base_url: string | null;
};

export type ConnectionCheckResult = {
  status: ProviderStatus;
  latency_ms: number | null;
  model: string | null;
  error: string | null;
};

export type BackendStatus = "checking" | "connected" | "disconnected";

export type ConnectionCheck = {
  status: BackendStatus;
  auth: "valid" | "invalid" | "unknown";
  latencyMs: number | null;
  checkedAt: string | null;
  model: string | null;
  error: string | null;
};

export type View = "chat" | "knowledge" | "telemetry" | "workflows" | "settings";

export type WorkflowStepType = "knowledge_search" | "llm_step" | "tool_call" | "human_approval";

export type WorkflowStep = {
  id: string;
  type: WorkflowStepType;
  name: string;
  max_retries?: number;
  query_template?: string | null;
  top_k?: number;
  min_score?: number;
  system_prompt?: string | null;
  prompt_template?: string | null;
  temperature?: number;
  tool_name?: string | null;
  arguments_template?: Record<string, unknown>;
  allow_mutating?: boolean;
  message_template?: string | null;
};

export type WorkflowDefinition = {
  id: string;
  name: string;
  description: string;
  trigger_type: string;
  steps: WorkflowStep[];
  enabled: boolean;
  owner_id: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowStepLog = {
  step_id: string;
  step_name: string;
  step_type: WorkflowStepType;
  status: "completed" | "waiting_approval" | "approved" | "rejected" | "failed";
  output: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  current_step_index: number;
  triggered_by: string;
  input: Record<string, unknown>;
  step_logs: WorkflowStepLog[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ChatStreamEventName =
  | "meta"
  | "status"
  | "result"
  | "citations"
  | "tool"
  | "reasoning"
  | "delta"
  | "done"
  | "error";

/** One server-sent event from POST /api/v1/chat/stream. */
export type ChatStreamEvent = {
  event: ChatStreamEventName;
  conversation_id?: string;
  status?: string;
  delta?: string;
  reasoning?: string;
  provider?: string;
  model?: string;
  citations?: Citation[];
  tool_calls?: ToolCall[];
  grounding?: GroundingReport;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    cached_tokens?: number;
    cache_creation_tokens?: number;
  } | null;
  detail?: string;
};

/** The assistant turn that is being streamed right now. */
export type LiveTurn = {
  /** Text revealed so far (the typewriter output, not the raw network text). */
  text: string;
  /** Latest progress message from the backend, e.g. "Searching knowledge base...". */
  status: string | null;
  reasoning: string;
  citations: Citation[];
  toolCalls: ToolCall[];
  model: string | null;
};
