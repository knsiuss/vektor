import { ChannelAnalyticsCards } from "@/components/channels/ChannelAnalyticsCards";
import { ChannelManager } from "@/components/channels/ChannelManager";
import { OpsHeader } from "@/components/ops-header";

export default function ChannelsPage() {
  return (
    <main className="ops-shell">
      <OpsHeader active="channels" title="Omnichannel Chatbot Connectors" />
      <ChannelAnalyticsCards />
      <ChannelManager />
    </main>
  );
}
