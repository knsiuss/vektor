import { AuthGuard } from "@/components/auth-guard";
import { VektorApp } from "@/components/vektor-app";

export default function Home() {
  return (
    <AuthGuard>
      <VektorApp />
    </AuthGuard>
  );
}
