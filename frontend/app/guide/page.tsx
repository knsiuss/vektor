import { GuideContent } from "@/components/guide/GuideContent";
import { OpsHeader } from "@/components/ops-header";

export default function GuidePage() {
  return (
    <main className="ops-shell">
      <OpsHeader active="guide" title="Vektor Setup Guide / Panduan" />
      <GuideContent />
    </main>
  );
}
