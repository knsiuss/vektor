"use client";

import type { ReactNode } from "react";
import { useEffect, useId, useRef, useState } from "react";

import { formatDate, initials, relativeTime } from "@/lib/format";
import type { ActivityItem } from "@/lib/activity";
import type { Connection, Me } from "@/lib/types";

import { FileText, History, IconButton, Info, Lock, LogOut, MessageSquare, Settings, ShieldCheck, User, Wrench, X } from "./icons";

type Tab = "profile" | "preferences" | "keys" | "activity" | "about";

const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: "profile", label: "Profile", icon: <User size={18} aria-hidden="true" /> },
  { id: "preferences", label: "Preferences", icon: <Settings size={18} aria-hidden="true" /> },
  { id: "keys", label: "API Keys", icon: <Wrench size={18} aria-hidden="true" /> },
  { id: "activity", label: "Activity Log", icon: <History size={18} aria-hidden="true" /> },
  { id: "about", label: "About", icon: <Info size={18} aria-hidden="true" /> },
];

const SUBTITLES: Record<Tab, string> = {
  profile: "Manage your account information",
  preferences: "Choose how Vektor looks on this device",
  keys: "How this browser authenticates with the backend",
  activity: "Recent activity recorded in this browser",
  about: "Version and connection details",
};

function activityIcon(kind: ActivityItem["kind"]) {
  if (kind === "session") return <MessageSquare size={17} aria-hidden="true" />;
  if (kind === "settings") return <Settings size={17} aria-hidden="true" />;
  if (kind === "knowledge") return <FileText size={17} aria-hidden="true" />;
  return <ShieldCheck size={17} aria-hidden="true" />;
}

function ActivityList({ items, empty }: { items: ActivityItem[]; empty: string }) {
  if (items.length === 0) return <p className="v-hint">{empty}</p>;
  return (
    <ul className="v-activity">
      {items.map((item) => (
        <li key={item.id}><span>{activityIcon(item.kind)}</span><strong>{item.label}</strong><em>{relativeTime(item.at)}</em></li>
      ))}
    </ul>
  );
}

export function ProfileModal({
  onClose,
  me,
  name,
  onNameChange,
  firstSeen,
  activity,
  connection,
  theme,
  onThemeChange,
  onClearActivity,
  onClearKey,
  onSignOut,
}: {
  onClose: () => void;
  me: Me | null;
  name: string;
  onNameChange: (name: string) => void;
  firstSeen: string;
  activity: ActivityItem[];
  connection: Connection;
  theme: "light" | "dark";
  onThemeChange: (theme: "light" | "dark") => void;
  onClearActivity: () => void;
  onClearKey: () => void;
  onSignOut: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [tab, setTab] = useState<Tab>("profile");
  const [draftName, setDraftName] = useState(name);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  useEffect(() => setDraftName(name), [name]);

  const identity = me?.user_id ?? "";
  const isEmail = identity.includes("@");
  const keyTail = connection.apiKey ? connection.apiKey.slice(-4) : "";

  return (
    <dialog
      ref={ref}
      className="v-profile"
      aria-labelledby={`${id}-title`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <div className="v-profile-shell">
        <aside className="v-profile-rail">
          <span className="v-avatar large" aria-hidden="true">{initials(name)}</span>
          <strong>{name}</strong>
          <small>{identity || "Not signed in"}</small>
          <nav aria-label="Profile sections">
            {TABS.map((item) => (
              <button key={item.id} className={tab === item.id ? "is-active" : ""} aria-current={tab === item.id ? "page" : undefined} onClick={() => setTab(item.id)}>{item.icon}{item.label}</button>
            ))}
          </nav>
          <button className="v-signout" onClick={onSignOut}><LogOut size={17} aria-hidden="true" />Sign Out</button>
        </aside>

        <div className="v-profile-main">
          <IconButton label="Close profile" className="v-profile-close" onClick={onClose}><X size={21} aria-hidden="true" /></IconButton>
          <h2 id={`${id}-title`}>{TABS.find((item) => item.id === tab)?.label}</h2>
          <p className="v-profile-sub">{SUBTITLES[tab]}</p>

          {tab === "profile" && (
            <>
              <div className="v-profile-fields">
                <label htmlFor={`${id}-name`}>Full Name</label>
                <input
                  id={`${id}-name`}
                  value={draftName}
                  maxLength={60}
                  onChange={(event) => setDraftName(event.target.value)}
                  onBlur={() => onNameChange(draftName)}
                  onKeyDown={(event) => { if (event.key === "Enter") onNameChange(draftName); }}
                />
                <label htmlFor={`${id}-id`}>{isEmail ? "Email Address" : "User ID"}</label>
                <div className="v-locked"><input id={`${id}-id`} value={identity || "Unknown"} readOnly /><Lock size={16} aria-hidden="true" /></div>
                <span className="v-label">Role</span>
                <span><em className="v-pill">{me ? (me.is_admin ? "Admin" : "Member") : "Unknown"}</em></span>
                <span className="v-label">Member Since</span>
                <span className="v-value">{formatDate(firstSeen)}</span>
              </div>
              <hr />
              <h3>Account Activity</h3>
              <p className="v-profile-sub">Your recent activity in this browser</p>
              <ActivityList items={activity.slice(0, 3)} empty="Nothing recorded yet." />
            </>
          )}

          {tab === "preferences" && (
            <div className="v-prefs">
              <div className="v-pref-row">
                <div><strong>Theme</strong><span>Applies to this browser only.</span></div>
                <div className="v-segmented" role="group" aria-label="Theme">
                  <button className={theme === "light" ? "is-active" : ""} aria-pressed={theme === "light"} onClick={() => onThemeChange("light")}>Light</button>
                  <button className={theme === "dark" ? "is-active" : ""} aria-pressed={theme === "dark"} onClick={() => onThemeChange("dark")}>Dark</button>
                </div>
              </div>
              <div className="v-pref-row">
                <div><strong>Display name</strong><span>Shown in the sidebar. Not shared with the backend.</span></div>
                <button className="button secondary" onClick={() => { onNameChange(""); }}>Reset name</button>
              </div>
            </div>
          )}

          {tab === "keys" && (
            <div className="v-prefs">
              <div className="v-pref-row">
                <div><strong>Key saved in this browser</strong><span>{connection.apiKey ? `Ends in \u2026${keyTail}` : "No key saved."}</span></div>
                <button className="button secondary" onClick={onClearKey} disabled={!connection.apiKey}>Remove key</button>
              </div>
              <p className="v-hint">Keys are issued per user by a tenant administrator, using <code>python -m api.cli create-key</code> on the backend. This page cannot create or list keys.</p>
            </div>
          )}

          {tab === "activity" && (
            <>
              <ActivityList items={activity} empty="Nothing recorded yet." />
              {activity.length > 0 && <button className="button secondary v-clear" onClick={onClearActivity}>Clear activity log</button>}
              <p className="v-hint">This list lives in your browser only. It is not the backend audit log.</p>
            </>
          )}

          {tab === "about" && (
            <dl className="v-facts v-about">
              <div><dt>Application</dt><dd>Vektor 0.1.0</dd></div>
              <div><dt>Backend</dt><dd>{connection.baseUrl}</dd></div>
              <div><dt>Tenant</dt><dd>{me?.tenant_id ?? "Unknown"}</dd></div>
              <div><dt>Role</dt><dd>{me ? (me.is_admin ? "Admin" : "Member") : "Unknown"}</dd></div>
            </dl>
          )}
        </div>
      </div>
    </dialog>
  );
}
