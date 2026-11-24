"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { getSupabaseClient, isSupabaseConfigured } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const configured = isSupabaseConfigured();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    const supabase = getSupabaseClient();
    if (!supabase) {
      setError("Supabase is not configured.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
        if (signInError) {
          setError(signInError.message);
          return;
        }
        router.push("/");
      } else {
        const { error: signUpError } = await supabase.auth.signUp({ email, password });
        if (signUpError) {
          setError(signUpError.message);
          return;
        }
        setNotice("Account created. Check your email to confirm, or sign in.");
        setMode("signin");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleSignIn() {
    setError(null);
    const supabase = getSupabaseClient();
    if (!supabase) {
      setError("Supabase is not configured.");
      return;
    }
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/` },
    });
    if (oauthError) setError(oauthError.message);
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        background:
          "radial-gradient(circle at 50% 0%, rgba(255,255,255,0.06) 0%, rgba(11,11,12,1) 55%)",
        color: "#f4f4f5",
        fontFamily: "var(--font-sans, system-ui, -apple-system, sans-serif)",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "400px",
          borderRadius: "20px",
          border: "1px solid rgba(255,255,255,0.09)",
          background: "rgba(20, 20, 22, 0.88)",
          backdropFilter: "blur(16px)",
          padding: "32px 28px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.55)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: "28px" }}>
          <div
            style={{
              width: "44px",
              height: "44px",
              borderRadius: "12px",
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.1)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: "14px",
            }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 5L11.5 19L15.5 11.5" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M14.5 5H20L17 10.5" stroke="#71717a" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h1 style={{ fontSize: "20px", fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
            {mode === "signin" ? "Welcome back to Vektor" : "Create your Vektor account"}
          </h1>
          <p style={{ fontSize: "13px", color: "#a1a1aa", marginTop: "6px", textAlign: "center" }}>
            {mode === "signin"
              ? "Sign in to access your workspace & saved API keys"
              : "Sign up to isolate your chats and BYOK keys"}
          </p>
        </div>

        {error && (
          <div
            style={{
              marginBottom: "16px",
              borderRadius: "10px",
              border: "1px solid rgba(239,68,68,0.35)",
              background: "rgba(239,68,68,0.1)",
              padding: "10px 12px",
              fontSize: "12px",
              color: "#fecaca",
            }}
          >
            {error}
          </div>
        )}

        {notice && (
          <div
            style={{
              marginBottom: "16px",
              borderRadius: "10px",
              border: "1px solid rgba(16,185,129,0.35)",
              background: "rgba(16,185,129,0.1)",
              padding: "10px 12px",
              fontSize: "12px",
              color: "#a7f3d0",
            }}
          >
            {notice}
          </div>
        )}

        <button
          type="button"
          disabled={loading || !configured}
          onClick={() => void handleGoogleSignIn()}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "10px",
            borderRadius: "10px",
            border: "1px solid rgba(255,255,255,0.14)",
            background: "rgba(255,255,255,0.04)",
            color: "#f4f4f5",
            padding: "10px 14px",
            fontSize: "13px",
            fontWeight: 500,
            cursor: loading || !configured ? "not-allowed" : "pointer",
            opacity: loading || !configured ? 0.5 : 1,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.5 3.9-5.5 3.9-3.3 0-6-2.7-6-6s2.7-6 6-6c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.5 14.6 2.6 12 2.6 6.8 2.6 2.6 6.8 2.6 12s4.2 9.4 9.4 9.4c5.4 0 9-3.8 9-9.1 0-.6-.1-1.1-.2-1.6H12z" />
          </svg>
          Continue with Google
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "12px", margin: "18px 0" }}>
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
          <span style={{ fontSize: "11px", color: "#71717a", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            or
          </span>
          <div style={{ flex: 1, height: "1px", background: "rgba(255,255,255,0.08)" }} />
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <div>
            <label style={{ display: "block", fontSize: "12px", color: "#a1a1aa", marginBottom: "6px" }}>
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={{
                width: "100%",
                boxSizing: "border-box",
                borderRadius: "10px",
                border: "1px solid rgba(255,255,255,0.1)",
                background: "#0f0f11",
                padding: "10px 12px",
                fontSize: "13px",
                color: "#f4f4f5",
                outline: "none",
              }}
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: "12px", color: "#a1a1aa", marginBottom: "6px" }}>
              Password
            </label>
            <input
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{
                width: "100%",
                boxSizing: "border-box",
                borderRadius: "10px",
                border: "1px solid rgba(255,255,255,0.1)",
                background: "#0f0f11",
                padding: "10px 12px",
                fontSize: "13px",
                color: "#f4f4f5",
                outline: "none",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading || !configured}
            style={{
              width: "100%",
              marginTop: "4px",
              borderRadius: "10px",
              border: "none",
              background: "#f4f4f5",
              color: "#09090b",
              padding: "10px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: loading || !configured ? "not-allowed" : "pointer",
              opacity: loading || !configured ? 0.5 : 1,
            }}
          >
            {loading ? "Please wait..." : mode === "signin" ? "Sign In" : "Create Account"}
          </button>
        </form>

        <div style={{ marginTop: "18px", textAlign: "center", fontSize: "12px", color: "#a1a1aa" }}>
          {mode === "signin" ? "Don't have an account?" : "Already have an account?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setNotice(null);
            }}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              color: "#f4f4f5",
              textDecoration: "underline",
              cursor: "pointer",
              fontSize: "12px",
            }}
          >
            {mode === "signin" ? "Sign up" : "Sign in"}
          </button>
        </div>
      </div>
    </main>
  );
}
