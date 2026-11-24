import { EvalsManager } from "@/components/evals/EvalsManager";
import { OpsHeader } from "@/components/ops-header";

export default function EvalsPage() {
  return (
    <main className="ops-shell">
      <OpsHeader active="evals" title="Evals & Knowledge Audit" />
      <EvalsManager />
    </main>
  );
}
