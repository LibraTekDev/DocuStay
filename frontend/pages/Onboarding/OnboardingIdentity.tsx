import React, { useEffect, useRef, useState } from "react";
import { Card, Button } from "../../components/UI";
import { getOwnerSignupErrorFriendly } from "../../utils/ownerSignupErrors";

const API_URL = (import.meta as any).env?.VITE_API_URL || (typeof window !== "undefined" ? "/api" : "http://127.0.0.1:8000");
const getToken = () => (typeof window !== "undefined" ? localStorage.getItem("docustay_token") : null);

interface Props {
  isPendingOwner?: boolean;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: "success" | "error", m: string) => void;
}

/** Redirect to Stripe Identity. For new signup (pending) use pending-owner session; for existing owner use identity session. Run only once per mount to avoid duplicate API calls. */
export default function OnboardingIdentity({ isPendingOwner, navigate, setLoading, notify }: Props) {
  const [error, setError] = useState<string | null>(null);
  const sessionStartedRef = useRef(false);

  useEffect(() => {
    if (sessionStartedRef.current) return;
    sessionStartedRef.current = true;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const TIMEOUT_MS = 15000;
    const timeoutId = setTimeout(() => {
      if (cancelled) return;
      const friendly = getOwnerSignupErrorFriendly("Request timed out.");
      setError(friendly.message);
      setLoading(false);
      notify("error", friendly.message);
    }, TIMEOUT_MS);

    const path = isPendingOwner ? "/auth/pending-owner/identity-session" : "/auth/identity/verification-session";
    const token = getToken();
    const headers: HeadersInit = { "Content-Type": "application/json", Accept: "application/json" };
    if (token) (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;

    const body = isPendingOwner
      ? JSON.stringify({ return_url: `${window.location.origin}/onboarding/identity-complete` })
      : undefined;

    const promise = fetch(`${API_URL}${path}`, { method: "POST", headers, body }).then(async (r) => {
      const text = await r.text();
      if (!r.ok) {
        let msg = r.statusText;
        try {
          if (text) {
            const j = JSON.parse(text);
            msg = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg ?? d).join(", ") : j.detail ?? msg;
          }
        } catch {
          if (text) msg = text;
        }
        throw new Error(msg);
      }
      return text ? JSON.parse(text) : null;
    });

    promise
      .then((res) => {
        clearTimeout(timeoutId);
        if (res == null) {
          if (!cancelled) {
            const friendly = getOwnerSignupErrorFriendly("No response from server.");
            setError(friendly.message);
            notify("error", friendly.message);
          }
          return;
        }
        const raw = typeof res === "object" ? (res as Record<string, unknown>) : null;
        const dataUrl = raw?.data && typeof (raw.data as Record<string, unknown>)?.url === "string" ? ((raw.data as Record<string, unknown>).url as string) : null;
        const url: string | null =
          (typeof raw?.url === "string" && raw.url) ||
          (typeof raw?.redirect_url === "string" && raw.redirect_url) ||
          dataUrl ||
          null;
        if ((import.meta as any).env?.DEV) console.log("[OnboardingIdentity] identity session response", { hasUrl: !!url, url: url ? `${url.slice(0, 50)}...` : null, keys: raw ? Object.keys(raw) : [] });
        if (url && url.startsWith("http")) {
          if (!cancelled) setLoading(false);
          const redirectUrl: string = url;
          setTimeout(() => {
            window.location.href = redirectUrl;
          }, 0);
          return;
        }
        if (!cancelled) {
          const friendly = getOwnerSignupErrorFriendly("Verification link not available.");
          setError(friendly.message);
          notify("error", friendly.message);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          clearTimeout(timeoutId);
          const friendly = getOwnerSignupErrorFriendly((e as Error)?.message ?? "Could not start identity verification.");
          setError(friendly.message);
          notify("error", friendly.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          clearTimeout(timeoutId);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [isPendingOwner]);

  return (
    <div className="flex-grow flex flex-col items-center justify-center p-6">
      <Card className="max-w-lg w-full p-8 text-center">
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Identity Verification</h1>
        <p className="text-gray-600 mb-6">
          You will be redirected to our secure partner to verify your identity with a government-issued ID and selfie.
        </p>
        {error ? (
          <>
            <p className="text-red-600 text-sm mb-4">{error}</p>
            <div className="flex flex-col gap-2">
              <Button onClick={() => { setError(null); window.location.reload(); }} className="w-full">
                Try again
              </Button>
              <button type="button" onClick={() => navigate("verify")} className="text-sm text-slate-600 hover:text-slate-900 underline">
                Back to verification
              </button>
            </div>
          </>
        ) : (
          <p className="text-slate-500 text-sm">Redirecting to verification…</p>
        )}
      </Card>
    </div>
  );
}
