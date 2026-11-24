import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import "@/app/ops.css";

interface OpsHeaderProps {
  active: "inbox" | "channels" | "widgets" | "evals" | "guide";
  title: string;
}

const LINKS = [
  { key: "inbox", href: "/inbox", label: "Inbox" },
  { key: "channels", href: "/channels", label: "Channels" },
  { key: "widgets", href: "/widgets", label: "Web Widgets" },
  { key: "evals", href: "/evals", label: "Evals" },
  { key: "guide", href: "/guide", label: "Guide" },
] as const;

export function OpsHeader({ active, title }: OpsHeaderProps) {
  return (
    <header className="ops-header">
      <div className="ops-header-left">
        <Link href="/" className="ops-back">
          <ArrowLeft size={14} aria-hidden="true" />
          Vektor
        </Link>
        <h1>{title}</h1>
      </div>
      <nav className="ops-nav" aria-label="Operations navigation">
        {LINKS.map((item) => (
          <Link key={item.key} href={item.href} className={active === item.key ? "is-active" : ""}>
            {item.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
