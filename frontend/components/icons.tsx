import type { ComponentPropsWithoutRef } from "react";
import {
  Activity,
  ArrowUp,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  FileText,
  Image,
  KeyRound,
  LoaderCircle,
  Menu,
  MessageSquare,
  Moon,
  Paperclip,
  Plus,
  Search,
  SendHorizontal,
  Settings2,
  ShieldAlert,
  Sun,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";

export {
  Activity,
  ArrowUp,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  FileText,
  Image,
  KeyRound,
  LoaderCircle,
  Menu,
  MessageSquare,
  Moon,
  Paperclip,
  Plus,
  Search,
  SendHorizontal,
  Settings2,
  ShieldAlert,
  Sun,
  Trash2,
  UploadCloud,
  X,
};

export {
  Calendar,
  ChevronUp,
  Clock,
  Cpu,
  Database,
  Eye,
  EyeOff,
  Gauge,
  History,
  Info,
  Layers,
  Lightbulb,
  Link as LinkIcon,
  Lock,
  LogOut,
  MoreHorizontal,
  MoreVertical,
  RefreshCw,
  Save,
  Server,
  Settings,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  User,
  Wrench,
  Zap,
  Brain,
  Square,
} from "lucide-react";

export function VektorLogo({ size = 80 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="vektor-logo"
      width={size}
      height={size * 0.82}
      viewBox="0 0 120 98"
      fill="none"
    >
      <path d="M6 12C3 4 11 0 18 4L62 79C66 88 61 96 53 96C49 96 46 93 43 89L6 12Z" fill="var(--logo-dark)" />
      <path d="M80 7C84 1 90 0 99 0H115C119 0 120 3 118 7L91 48C87 53 80 53 76 48L69 33C67 29 69 24 73 19L80 7Z" fill="var(--logo-light)" />
    </svg>
  );
}

export function SidebarToggle({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <path d="M9 3v18" />
    </svg>
  );
}

export function ConnectionBars({ active }: { active: boolean }) {
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" className={active ? "connection-bars is-active" : "connection-bars"}>
      <path d="M5 16v3M10 11v8M15 6v13M20 2v17" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export function IconButton({ label, children, className = "", ...props }: ComponentPropsWithoutRef<"button"> & { label: string }) {
  return (
    <button type="button" className={`icon-button ${className}`} aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}
