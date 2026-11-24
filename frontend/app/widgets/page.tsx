import { OpsHeader } from "@/components/ops-header";
import { WidgetManager } from "@/components/widgets/WidgetManager";

export default function WidgetsPage() {
  return (
    <main className="ops-shell">
      <OpsHeader active="widgets" title="Public Chatbot Widgets" />
      <WidgetManager />
    </main>
  );
}
