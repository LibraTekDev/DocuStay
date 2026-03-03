import React, { useEffect, useMemo, useState } from "react";
import { Button, Input, Modal } from "./UI";
import { agreementsApi, API_URL, type AgreementDocResponse } from "../services/api";

type AckKey = "read" | "temporary" | "vacate" | "electronic";

export default function AgreementSignModal(props: {
  open: boolean;
  invitationCode: string;
  guestEmail: string;
  guestFullName: string;
  onClose: () => void;
  onSigned: (signatureId: number) => void;
  notify: (t: "success" | "error", m: string) => void;
}) {
  const { open, invitationCode, guestEmail, guestFullName, onClose, onSigned, notify } = props;
  const normalizedCode = invitationCode.trim().toUpperCase();

  const [doc, setDoc] = useState<AgreementDocResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [signing, setSigning] = useState(false);
  const [typedSignature, setTypedSignature] = useState(guestFullName || "");
  const [acks, setAcks] = useState<Record<AckKey, boolean>>({
    read: false,
    temporary: false,
    vacate: false,
    electronic: false,
  });

  const allAcks = useMemo(() => Object.values(acks).every(Boolean), [acks]);

  useEffect(() => {
    if (!open) return;
    setTypedSignature(guestFullName || "");
    setAcks({ read: false, temporary: false, vacate: false, electronic: false });

    if (!normalizedCode) return;
    setLoading(true);
    agreementsApi
      .getInvitationAgreement(normalizedCode, guestEmail?.trim() || undefined)
      .then((d) => {
        setDoc(d);
        if (d?.already_signed && d?.signature_id != null) onSigned(d.signature_id);
      })
      .catch((e) => notify("error", (e as Error)?.message || "Could not load agreement."))
      .finally(() => setLoading(false));
  }, [open, normalizedCode, guestFullName, guestEmail, notify, onSigned]);

  const handleSign = async () => {
    if (!normalizedCode) return notify("error", "Invitation code is missing.");
    if (!guestEmail?.trim()) return notify("error", "Enter your email first.");
    if (!typedSignature?.trim()) return notify("error", "Type your full legal name to sign.");
    if (!doc) return notify("error", "Agreement is not loaded yet.");
    if (!allAcks) return notify("error", "Please acknowledge all items to proceed.");

    setSigning(true);
    try {
      const res = await agreementsApi.signInvitationAgreementWithDropbox({
        invitation_code: normalizedCode,
        guest_email: guestEmail.trim(),
        guest_full_name: guestFullName?.trim() || typedSignature.trim(),
        typed_signature: typedSignature.trim(),
        acks,
        document_hash: doc.document_hash,
      });
      notify("success", "Agreement sent to Dropbox Sign. Check your email to complete signing; you can download the signed PDF here after signing.");
      onSigned(res.signature_id);
      onClose();
    } catch (e) {
      notify("error", (e as Error)?.message || "Could not sign agreement.");
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
                href={`${API_URL}/agreements/invitation/${encodeURIComponent(normalizedCode)}/pdf${guestEmail?.trim() ? `?guest_email=${encodeURIComponent(guestEmail.trim())}` : ""}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
              >
                View / Download PDF
              </a>
            )}
          </div>
        </div>

        {doc?.already_signed && (
          <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-emerald-700 font-bold">✓ Signed</span>
            <span className="text-slate-600 text-sm">
              {doc.signed_by} on {doc.signed_at ? new Date(doc.signed_at).toLocaleDateString() : ""}
            </span>
            {doc.signature_id != null && doc.has_dropbox_signed_pdf && (
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

        <div className="grid lg:grid-cols-5 gap-6">
          {/* Agreement content */}
          <div className="lg:col-span-3">
            <div className="border border-slate-200 rounded-xl bg-white overflow-hidden shadow-sm">
              <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Agreement</p>
                {doc?.property_address ? (
                  <p className="text-xs text-slate-500 truncate max-w-[60%]" title={doc.property_address}>
                    {doc.property_address}
                  </p>
                ) : null}
              </div>
              <div className="p-4 max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-sm text-slate-700 leading-relaxed">
                {loading ? "Loading agreement…" : (doc?.content || "Agreement unavailable.")}
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
                    onChange={(e) => setAcks((p) => ({ ...p, [key]: e.target.checked }))}
                    className="mt-0.5 w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0"
                  />
                  <span className="text-sm text-slate-700">{label}</span>
                </label>
              ))}
            </div>

            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Signature</p>
              {doc?.already_signed ? (
                <p className="text-sm text-slate-600">This agreement is already signed. You can close this window.</p>
              ) : (
                <>
                  <Input
                    label="Type full legal name *"
                    name="typed_signature"
                    value={typedSignature}
                    onChange={(e) => setTypedSignature(e.target.value)}
                    placeholder="First Last"
                    required
                  />
                  <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold">
                    By signing, you agree to the terms of this agreement.
                  </p>
                  <div className="flex flex-col gap-3 pt-1">
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={onClose} className="flex-1 py-3">
                        Cancel
                      </Button>
                      <Button onClick={handleSign} disabled={signing || loading} className="flex-1 py-3">
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
