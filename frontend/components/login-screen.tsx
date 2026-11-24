"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Connection } from "@/lib/types";

import { VektorLogo } from "./icons";

type ProviderAvailability = { google: boolean; github: boolean };

/**
 * Sign-in screen shown when the API rejects the request. Buttons redirect into the
 * backend OAuth flow, which returns to this origin with a session cookie.
 */
export function LoginScreen({ connection, reason }: { connection: Connection; reason: string | null }) {
  const [available, setAvailable] = useState<ProviderAvailability | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<ProviderAvailability>("auth/providers", connection, { retries: 0 })
      .then((result) => {
        if (!cancelled) setAvailable(result);
      })
      .catch(() => {
        if (!cancelled) setAvailable({ google: false, github: false });
      });
    return () => {
      cancelled = true;
    };
  }, [connection]);

  const start = (provider: "google" | "github") => {
    window.location.assign(`/api/backend/auth/${provider}/start`);
  };

  return (
    <div className="login-shell">
      <div className="login-card">
        <VektorLogo size={64} />
        <h1>Sign in to Vektor</h1>
        <p className="login-sub">Operations assistant for database and infrastructure work.</p>

        {reason && <div className="form-message error" role="alert"><div><strong>Sign-in failed</strong><p>{reason}</p></div></div>}

        <div className="login-actions">
          <button
            type="button"
            className="login-provider"
            onClick={() => start("google")}
            disabled={available !== null && !available.google}
          >
            <span className="login-provider-mark" aria-hidden="true">G</span>
            Continue with Google
          </button>
          <button
            type="button"
            className="login-provider"
            onClick={() => start("github")}
            disabled={available !== null && !available.github}
          >
            <span className="login-provider-mark" aria-hidden="true">GH</span>
            Continue with GitHub
          </button>
        </div>

        {available !== null && !available.google && !available.github && (
          <p className="login-footnote">
            No provider is configured on this server. Set the OAuth client id and secret.
          </p>
        )}
      </div>
    </div>
  );
}
