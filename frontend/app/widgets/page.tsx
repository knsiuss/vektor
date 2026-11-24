import { WidgetManager } from "@/components/widgets/WidgetManager";

export default function WidgetsPage() {
  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="mb-4 text-xl font-semibold">Public Chatbot Widgets</h1>
      <WidgetManager />
    </main>
  );
}
