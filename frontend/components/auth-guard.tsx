"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getSupabaseClient, isSupabaseConfigured } from "@/lib/supabase";

const GUEST_PROMPT_KEY = "vektor_guest_prompts";
export const MAX_GUEST_PROMPTS = 5;

export function getGuestPromptCount(): number {
  if (typeof window === "undefined") return 0;
  const raw = window.localStorage.getItem(GUEST_PROMPT_KEY);
  const parsed = Number.parseInt(raw ?? "0", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

export function incrementGuestPromptCount(): number {
  const next = getGuestPromptCount() + 1;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(GUEST_PROMPT_KEY, String(next));
  }
  return next;
}

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const devBypass = process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true";
  const configured = isSupabaseConfigured() && !devBypass;
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    if (!configured) return;
    const supabase = getSupabaseClient();
    if (!supabase) return;

    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSignedIn(Boolean(data.session));
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setSignedIn(Boolean(session));
    });

    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, [configured]);

  return (
    <>
      {configured && !signedIn && (
        <button
          type="button"
          onClick={() => router.push("/login")}
          style={{
            position: "fixed",
            top: "14px",
            right: "18px",
            zIndex: 50,
            borderRadius: "9999px",
            border: "1px solid rgba(255,255,255,0.14)",
            background: "#f4f4f5",
            color: "#09090b",
            padding: "7px 16px",
            fontSize: "13px",
            fontWeight: 600,
            cursor: "pointer",
            boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
          }}
        >
          Log in
        </button>
      )}
      {children}
    </>
  );
}
