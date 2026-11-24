import { AuthGuard } from "@/components/auth-guard";
import { VektorApp } from "@/components/vektor-app";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <AuthGuard>
      <VektorApp initialConversationId={id} />
    </AuthGuard>
  );
}
