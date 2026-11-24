import { ApprovalQueue } from "@/components/inbox/ApprovalQueue";
import { UnifiedInbox } from "@/components/inbox/UnifiedInbox";
import { OpsHeader } from "@/components/ops-header";

export default function InboxPage() {
  return (
    <main className="ops-shell">
      <OpsHeader active="inbox" title="Unified Channel Inbox & Handover" />
      <ApprovalQueue />
      <UnifiedInbox />
    </main>
  );
}
