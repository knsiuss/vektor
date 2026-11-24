"use client";

import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";

import { groupConversations } from "@/lib/conversations";
import { initials } from "@/lib/format";
import { getSupabaseClient, isSupabaseConfigured } from "@/lib/supabase";
import type { ConnectionCheck, View } from "@/lib/types";

import {
  ChevronDown,
  ConnectionBars,
  IconButton,
  MessageSquare,
  Moon,
  MoreHorizontal,
  Plus,
  Settings,
  SidebarToggle,
  Sun,
  Trash2,
  VektorLogo,
} from "./icons";

type ConversationSummary = { id: string; title: string; updated_at: string };

export function Sidebar({
  open,
  onClose,
  hidden,
  onHide,
  conversations,
  loading,
  error,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRetry,
  view,
  onNavigate,
  check,
  userName,
  onOpenProfile,
  theme,
  onToggleTheme,
}: {
  conversations: ConversationSummary[];
  open: boolean;
  onClose: () => void;
  hidden: boolean;
  onHide: () => void;
  loading: boolean;
  error: string | null;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (conversation: ConversationSummary) => void;
  onRetry: () => void;
  view: View;
  onNavigate: (view: View) => void;
  check: ConnectionCheck;
  userName: string;
  onOpenProfile: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  const groups = groupConversations(conversations);
  const [menuId, setMenuId] = useState<string | null>(null);

  useEffect(() => {
    if (!menuId) return;
    const close = () => setMenuId(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    const [supabaseEmail, setSupabaseEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    const supabase = getSupabaseClient();
    if (!supabase) return;
    void supabase.auth.getUser().then(({ data }) => {
      setSupabaseEmail(data.user?.email ?? null);
    });
  }, []);

  const displayName = supabaseEmail ?? userName;

  return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuId]);

  const inSettings = view !== "chat";

  const statusText =
    check.status === "connected" ? "Connected" : check.status === "checking" ? "Connecting" : "Not connected";

  const [supabaseEmail, setSupabaseEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    const supabase = getSupabaseClient();
    if (!supabase) return;
    void supabase.auth.getUser().then(({ data }) => {
      setSupabaseEmail(data.user?.email ?? null);
    });
  }, []);

  const displayName = supabaseEmail ?? userName;

  return (
    <>
      {open && <button className="sidebar-scrim" aria-label="Close navigation" onClick={onClose} />}
      <aside className={`sidebar ${open ? "is-open" : ""} ${hidden ? "is-hidden" : ""}`}>
        <div className="brand-row">
          <div className="brand"><VektorLogo size={37} /><span className="sidebar-label">Vektor</span></div>
          <div className="brand-actions">
            <IconButton
              label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              onClick={onToggleTheme}
              className="theme-toggle-btn"
            >
              {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
            </IconButton>
            <IconButton label="Hide sidebar" onClick={onHide} className="desktop-toggle"><SidebarToggle /></IconButton>
            <IconButton label="Close navigation" onClick={onClose} className="mobile-menu-button"><SidebarToggle /></IconButton>
          </div>
        </div>
        <div className="sidebar-new"><button className="button new-session" onClick={onNew}><Plus size={18} aria-hidden="true" /><span className="sidebar-label">New Chat</span></button></div>
        <nav className="conversation-nav" aria-label="Conversation history">
          <div className="conversation-scroll">
            {loading && <div className="sidebar-state" role="status"><span className="loading-line" /><span className="loading-line short" /><span>Loading conversations</span></div>}
            {error && <div className="sidebar-state error"><p>{error}</p><button onClick={onRetry}>Retry connection</button></div>}
            {!loading && !error && conversations.length === 0 && <div className="sidebar-state"><MessageSquare size={22} aria-hidden="true" /><p>Your sessions will appear here.</p></div>}
            {!loading && !error && groups.map((group) => (
              <section className="conversation-group" key={group.label}>
                <h2>{group.label}</h2>
                {group.items.map((conversation) => (
                  <div className={`conversation-item ${activeId === conversation.id && view === "chat" ? "is-active" : ""}`} key={conversation.id}>
                    <button className="conversation-select" onClick={() => onSelect(conversation.id)} title={conversation.title}>
                      <MessageSquare size={17} aria-hidden="true" />
                      <span className="conversation-title">{conversation.title}</span>
                    </button>
                    <div className="v-menu-wrap">
                      <IconButton
                        className="conversation-more"
                        label={`Options for ${conversation.title}`}
                        aria-haspopup="menu"
                        aria-expanded={menuId === conversation.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          setMenuId(menuId === conversation.id ? null : conversation.id);
                        }}
                      >
                        <MoreHorizontal size={16} aria-hidden="true" />
                      </IconButton>
                      {menuId === conversation.id && (
                        <div className="v-menu" role="menu">
                          <button role="menuitem" className="danger" onClick={() => onDelete(conversation)}>
                            <Trash2 size={15} aria-hidden="true" /> Delete session
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </section>
            ))}
          </div>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-utilities">
            <button
              className={inSettings ? "is-active" : ""}
              aria-current={inSettings ? "page" : undefined}
              onClick={() => onNavigate("settings")}
            >
              <Settings size={19} aria-hidden="true" />
              <span className="sidebar-label">Settings</span>
            </button>
          </div>
          <button
            className="backend-status v-status-card"
            onClick={() => onNavigate("settings")}
            aria-label={`Backend ${statusText.toLowerCase()}. Open connection settings`}
          >
            <span className={`status-dot ${check.status}`} aria-hidden="true" />
            <span className="sidebar-label v-status-text">
              <strong>{statusText}</strong>
              <small>Vektor Backend{check.status === "connected" && check.model ? ` \u00b7 ${check.model}` : ""}</small>
            </span>
            <ConnectionBars active={check.status === "connected"} />
          </button>
          <div className="flex items-center gap-1">
            <button className="v-user flex-1" onClick={onOpenProfile} aria-label={`Open profile for ${displayName}`}>
              <span className="v-avatar" aria-hidden="true">{initials(displayName)}</span>
              <span className="sidebar-label v-user-name">{displayName}</span>
              <ChevronDown size={16} aria-hidden="true" />
            </button>
            {supabaseEmail && (
              <button
                type="button"
                onClick={() => void getSupabaseClient()?.auth.signOut()}
                title="Sign out"
                aria-label="Sign out"
                className="p-2 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60"
              >
                <LogOut size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
