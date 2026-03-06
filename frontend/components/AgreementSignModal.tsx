import React, { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Modal } from "./UI";
import { agreementsApi, API_URL, type AgreementDocResponse } from "../services/api";

type AckKey = "read" | "temporary" | "vacate" | "electronic";

/** Today's date in "Month DD, YYYY" for agreement display. */
function todayDisplayDate(): string {
  const d = new Date();
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

/**
 * Apply display-only placeholders: guest name, date, and optional IP.
 * Does not change the underlying doc content used for hashing.
 */
function contentForDisplay(
  content: string,
  guestName: string,
  ipAddress: string
): string {
  let out = content.replace(/\[Guest Name\]/g, guestName || "[Guest Name]");
  // Fill Date line ( **Date:** ___________________ )
  out = out.replace(
    /\*\*Date:\*\*\s*_+\s*/g,
    `**Date:** ${todayDisplayDate()}\n`
  );
  if (ipAddress.trim()) {
    out = out.replace(
      /IP Address:\s*_+\s*/g,
      `IP Address: ${ipAddress.trim()}\n`
    );
  }
  return out;
}

/** Render agreement content with **bold** segments as <strong>. Preserves newlines. */
function renderAgreementContent(content: string) {
  return content.split("\n").map((line, i) => (
    <Fragment key={i}>
      {i > 0 && <br />}
      {line.split(/\*\*(.+?)\*\*/g).map((seg, j) =>
        j % 2 === 1 ? <strong key={j}>{seg}</strong> : seg
      )}
    </Fragment>
  ));
}

export default function AgreementSignModal(props: {
  open: boolean;
  invitationCode: string;
  guestEmail: string;
  guestFullName: string;
  onClose: () => void;
  onSigned: (signatureId: number) => void;
  notify: (t: "success" | "error", m: string) => void;
  /** When provided and we get a sign_url, we call this and the parent redirects the user to Dropbox (same tab). */
  onRedirectToDropbox?: (invitationCode: string, signatureId: number, signUrl: string) => void;
}) {
  const { open, invitationCode, guestEmail, guestFullName, onClose, onSigned, notify, onRedirectToDropbox } = props;
  const normalizedCode = invitationCode.trim().toUpperCase();

  const notifyRef = useRef(notify);
  const onSignedRef = useRef(onSigned);
  notifyRef.current = notify;
  onSignedRef.current = onSigned;

  const [doc, setDoc] = useState<AgreementDocResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);
  const [typedSignature, setTypedSignature] = useState(guestFullName || "");
  const [ipAddress, setIpAddress] = useState("");
  const [acks, setAcks] = useState<Record<AckKey, boolean>>({
    read: false,
    temporary: false,
    vacate: false,
    electronic: false,
  });
  const [signError, setSignError] = useState<string | null>(null);
  /** After Sign with Dropbox: we wait for user to complete in Dropbox; modal stays open and we poll. */
  const [pendingDropboxSignatureId, setPendingDropboxSignatureId] = useState<number | null>(null);
  const [pendingSignUrl, setPendingSignUrl] = useState<string | null>(null);

  const allAcks = useMemo(() => Object.values(acks).every(Boolean), [acks]);

  const signatureIdToPoll =
    pendingDropboxSignatureId ??
    (doc?.already_signed && doc?.signature_id != null && !doc?.has_dropbox_signed_pdf ? doc.signature_id ?? null : null);

  useEffect(() => {
    if (!open || signatureIdToPoll == null) return;
    const id = signatureIdToPoll;
    const t = setInterval(() => {
      agreementsApi.getSignatureStatus(id).then((res) => {
        if (res.completed) {
          setPendingDropboxSignatureId(null);
          setPendingSignUrl(null);
          onSignedRef.current(id);
          onClose();
        }
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [open, signatureIdToPoll]);

  useEffect(() => {
    if (!open) return;
    setTypedSignature(guestFullName || "");
    setIpAddress("");
    setAcks({ read: false, temporary: false, vacate: false, electronic: false });
    setLoadError(null);
    setSignError(null);

    if (!normalizedCode) return;
    setLoading(true);
    setDoc(null);
    setPendingDropboxSignatureId(null);
    setPendingSignUrl(null);
    agreementsApi
      .getInvitationAgreement(normalizedCode, guestEmail?.trim() || undefined, guestFullName?.trim() || undefined)
      .then((d) => {
        setDoc(d);
        setLoadError(null);
        // Only treat as "signed" for accept when Dropbox PDF is available (stay confirmation)
        if (d?.already_signed && d?.signature_id != null && d?.has_dropbox_signed_pdf) onSignedRef.current(d.signature_id);
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? "";
        const expiredOrInvalid = msg.toLowerCase().includes("expired") || msg.toLowerCase().includes("not found") || msg.toLowerCase().includes("not pending");
        const userMsg = expiredOrInvalid ? "This invitation has expired or is invalid. You can’t use this link to sign." : msg || "Could not load agreement.";
        setLoadError(userMsg);
        setDoc(null);
        notifyRef.current("error", userMsg);
      })
      .finally(() => setLoading(false));
  }, [open, normalizedCode, guestFullName, guestEmail]);

  const handleSign = async () => {
    setSignError(null);
    if (!normalizedCode) {
      notify("error", "Invitation code is missing.");
      return;
    }
    if (!guestEmail?.trim()) {
      notify("error", "Enter your email first.");
      return;
    }
    if (!typedSignature?.trim()) {
      notify("error", "Type your full name to sign.");
      return;
    }
    if (!doc) {
      notify("error", "Agreement is not loaded yet.");
      return;
    }
    if (!allAcks) {
      const msg = "Please check all four acknowledgments above before signing.";
      setSignError(msg);
      notify("error", msg);
      return;
    }

    setSigning(true);
    try {
      const res = await agreementsApi.signInvitationAgreementWithDropbox({
        invitation_code: normalizedCode,
        guest_email: guestEmail.trim(),
        guest_full_name: guestFullName?.trim() || typedSignature.trim(),
        typed_signature: typedSignature.trim(),
        acks,
        document_hash: doc.document_hash,
        ip_address: ipAddress.trim() || undefined,
      });
      if (res.sign_url && onRedirectToDropbox) {
        onRedirectToDropbox(normalizedCode, res.signature_id, res.sign_url);
        return;
      }
      if (res.sign_url) {
        window.open(res.sign_url, "_blank", "noopener");
        notify("success", "Agreement sent to Dropbox Sign. Complete signing in the new tab. Your stay will confirm once you've signed.");
      } else {
        notify("success", "Agreement sent to Dropbox Sign. Check your email to complete signing.");
      }
      onClose();
    } catch (e) {
      const msg = (e as Error)?.message || "Could not sign agreement.";
      setSignError(msg);
      notify("error", msg);
    } finally {
      setSigning(false);
    }
  };

  const shortTitle = doc?.title?.includes("(") ? doc.title.slice(0, doc.title.indexOf("(")).trim() || doc.title : (doc?.title || "Review & Sign Agreement");

  return (
    <Modal open={open} onClose={onClose} title={shortTitle} className="max-w-5xl">
      <div className="p-6 md:p-8 space-y-6 bg-slate-50/50">
        {/* Meta row */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm text-slate-600">
              Invitation: <span className="font-semibold text-slate-800">{normalizedCode}</span>
              {doc?.region_code ? (
                <> · Region: <span className="font-semibold text-slate-800">{doc.region_code}</span></>
              ) : null}
            </p>
            <p className="text-xs text-slate-500 italic">DocuStay is a documentation platform, not a law firm.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {doc?.document_id ? (
              <span className="text-xs text-slate-500 font-mono">{doc.document_id}</span>
            ) : null}
            {doc && !loading && (
              <a
                href={`${API_URL}/agreements/invitation/${encodeURIComponent(normalizedCode)}/pdf${(() => {
                  const params = [
                    guestEmail?.trim() && `guest_email=${encodeURIComponent(guestEmail.trim())}`,
                    (guestFullName || typedSignature)?.trim() && `guest_full_name=${encodeURIComponent((guestFullName || typedSignature).trim())}`,
                  ].filter(Boolean);
                  return params.length ? `?${params.join("&")}` : "";
                })()}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
              >
                View / Download PDF
              </a>
            )}
          </div>
        </div>

        {doc?.already_signed && doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-emerald-700 font-bold">✓ Signed</span>
            <span className="text-slate-600 text-sm">
              {doc.signed_by} on {doc.signed_at ? new Date(doc.signed_at).toLocaleDateString() : ""}
            </span>
            {doc.signature_id != null && (
              <a
                href={`${API_URL}/agreements/signature/${doc.signature_id}/signed-pdf`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
              >
                Download signed PDF (Dropbox Sign)
              </a>
            )}
          </div>
        )}
        {doc?.already_signed && !doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-amber-800 font-bold">Awaiting your signature in Dropbox</span>
            <span className="text-slate-600 text-sm">
              Complete signing in the link we sent you by email, or use the button below when you open this from the same session.
            </span>
          </div>
        )}

        <div className="grid lg:grid-cols-5 gap-6">
          {/* Agreement content – readable document area */}
          <div className="lg:col-span-3">
            <div className="border border-slate-200 rounded-xl bg-white overflow-hidden shadow-sm flex flex-col max-h-[70vh]">
              <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2 shrink-0">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Agreement</p>
                {doc?.property_address ? (
                  <p className="text-xs text-slate-500 truncate max-w-[60%]" title={doc.property_address}>
                    {doc.property_address}
                  </p>
                ) : null}
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <div className="px-6 py-5 max-w-prose mx-auto">
                  <div className="text-base text-slate-800 leading-loose tracking-normal selection:bg-blue-100">
                    {loading
                      ? "Loading agreement…"
                      : loadError
                        ? loadError
                        : doc?.content
                          ? renderAgreementContent(
                              contentForDisplay(
                                doc.content,
                                guestFullName || typedSignature || "[Guest Name]",
                                ipAddress
                              )
                            )
                          : "Agreement unavailable."}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Acknowledgments + Signature */}
          <div className="lg:col-span-2 space-y-4">
            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Acknowledgments</p>
              {(
                [
                  ["read", "I have read the entire agreement"],
                  ["temporary", "I acknowledge my stay is temporary"],
                  ["vacate", "I agree to vacate by the checkout date"],
                  ["electronic", "I consent to electronic signature"],
                ] as Array<[AckKey, string]>
              ).map(([key, label]) => (
                <label key={key} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acks[key]}
                    onChange={(e) => {
                      setAcks((p) => ({ ...p, [key]: e.target.checked }));
                      setSignError(null);
                    }}
                    className="mt-0.5 w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0"
                  />
                  <span className="text-sm text-slate-700">{label}</span>
                </label>
              ))}
            </div>

            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Signature</p>
              {doc?.already_signed && doc?.has_dropbox_signed_pdf ? (
                <p className="text-sm text-slate-600">This agreement is already signed. You can close this window.</p>
              ) : signatureIdToPoll != null ? (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-slate-700">
                    Complete signing in Dropbox. This modal will close automatically when we detect your signature.
                  </p>
                  {pendingSignUrl && (
                    <Button
                      variant="outline"
                      onClick={() => window.open(pendingSignUrl!, "_blank", "noopener")}
                      className="w-full py-3"
                    >
                      Open Dropbox to sign
                    </Button>
                  )}
                  <p className="text-xs text-slate-500">You can close this modal; your stay will stay in pending actions until signing is complete.</p>
                </div>
              ) : (
                <>
                  <Input
                    label="Type full name *"
                    name="typed_signature"
                    value={typedSignature}
                    onChange={(e) => setTypedSignature(e.target.value)}
                    placeholder="First Last"
                    required
                  />
                  <Input
                    label="IP Address (optional)"
                    name="ip_address"
                    value={ipAddress}
                    onChange={(e) => setIpAddress(e.target.value)}
                    placeholder="e.g. 192.168.1.1"
                  />
                  {signError && (
                    <p className="text-sm text-red-600 font-medium" role="alert">
                      {signError}
                    </p>
                  )}
                  <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold">
                    By signing, you agree to the terms of this agreement.
                  </p>
                  <div className="flex flex-col gap-3 pt-1">
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={onClose} className="flex-1 py-3">
                        Cancel
                      </Button>
                      <Button
                        onClick={handleSign}
                        disabled={signing || loading || !allAcks}
                        className="flex-1 py-3"
                        title={!allAcks ? "Check all acknowledgments above to enable signing" : undefined}
                      >
                        {signing ? "Sending…" : "Sign with Dropbox Sign"}
                      </Button>
                    </div>
                    <p className="text-xs text-slate-500 leading-relaxed">
                      You will receive an email from Dropbox Sign with a link to sign. After signing there, you can download the signed PDF here.
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
