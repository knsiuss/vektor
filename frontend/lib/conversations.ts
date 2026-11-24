import type { Conversation, ConversationDetail, Message } from "./types";

export function mapMessages(detail: ConversationDetail): Message[] {
  return detail.messages.map((message) => ({ ...message }));
}

export function approvalTarget(message: Message, messages: Message[]) {
  const index = messages.findIndex((candidate) => candidate.id === message.id);
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return null;
}

export function connectionLabel(baseUrl: string) {
  try {
    const url = new URL(baseUrl);
    if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) return "Local backend";
    return url.hostname;
  } catch {
    return "Custom backend";
  }
}

export function groupConversations(conversations: Pick<Conversation, "id" | "title" | "updated_at">[], now = new Date()) {
  const groups: { label: string; items: Pick<Conversation, "id" | "title" | "updated_at">[] }[] = [
    { label: "Today", items: [] },
    { label: "7 Days Ago", items: [] },
    { label: "Earlier", items: [] },
  ];
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  conversations.forEach((conversation) => {
    const timestamp = new Date(conversation.updated_at).getTime();
    const daysAgo = (startOfToday - timestamp) / 86_400_000;
    const index = daysAgo < 1 ? 0 : daysAgo < 7 ? 1 : 2;
    groups[index].items.push(conversation);
  });
  return groups.filter((group) => group.items.length > 0);
}
