import React, { useState, useEffect } from 'react';
import { Card, Button, Input } from '../../components/UI';
import { UserSession } from '../../types';
import { ownerPoaApi, dashboardApi, API_URL } from '../../services/api';
import type { OwnerPOASignatureResponse } from '../../services/api';
import type { BillingResponse } from '../../services/api';

const Settings: React.FC<{
  user: UserSession | null;
  navigate: (v: string) => void;
  embedded?: boolean;
  /** When embedded in owner dashboard, call to switch to Billing tab */
  onOpenBilling?: () => void;
}> = ({ user, navigate, embedded, onOpenBilling }) => {
  const [poaSignature, setPoaSignature] = useState<OwnerPOASignatureResponse | null | undefined>(undefined);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);
  const [prefs, setPrefs] = useState({
    emailNotifs: true,
    smsNotifs: true,
    autoEnforce: false,
    defaultStayDays: 14,
    requireBiometrics: true,
  });

  const isOwner = user?.user_type === 'PROPERTY_OWNER';
  useEffect(() => {
    if (!isOwner) return;
    ownerPoaApi.getMySignature()
      .then((s) => setPoaSignature(s ?? null))
      .catch(() => setPoaSignature(null));
  }, [isOwner]);

  useEffect(() => {
    if (!isOwner) return;
    setBillingLoading(true);
    dashboardApi.billing()
      .then(setBilling)
      .catch(() => setBilling(null))
      .finally(() => setBillingLoading(false));
  }, [isOwner]);

  const openSignedPoaPdf = () => {
    if (!poaSignature?.signature_id) return;
    const token = typeof window !== 'undefined' ? localStorage.getItem('docustay_token') : null;
    if (!token) return;
    const url = `${API_URL}/agreements/owner-poa/signature/${poaSignature.signature_id}/signed-pdf`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        window.open(u, '_blank');
      })
      .catch(() => {});
  };

  return (
    <div className="w-full max-w-5xl py-4 md:py-6">
      {!embedded && (
        <button
          onClick={() => navigate('dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-blue-700 font-medium text-sm uppercase tracking-wider transition-colors mb-6"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Dashboard
        </button>
      )}
      <header className="mb-6">
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 tracking-tight">Settings</h1>
        <p className="text-gray-600 text-sm mt-1">Manage your DocuStay account and preferences.</p>
      </header>

      <div className="space-y-8">
        {/* Personal Information – main white card, larger */}
        <Card className="p-8 md:p-10">
          <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-8">Personal Information</h2>
          <div className="grid md:grid-cols-2 gap-6">
            <Input label="Full Legal Name" name="name" value={user?.user_name || ''} onChange={() => {}} disabled />
            <Input label="Verified Email" name="email" value={user?.email || ''} onChange={() => {}} disabled />
            <Input label="Phone Number" name="phone" value="+1 (555) 000-0000" onChange={() => {}} />
          </div>
          <div className="mt-8 flex justify-start">
            <Button variant="primary" type="button" className="px-8">
              Update Profile
            </Button>
          </div>
        </Card>

        {/* Subscription & Billing (owners only) */}
        {isOwner && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Subscription & Billing</h2>
            {billingLoading ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : billing === null ? (
              <p className="text-gray-500 text-sm">Unable to load billing information. Try the Billing tab or refresh.</p>
            ) : (
              <div className="space-y-4">
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-gray-50 border border-gray-200">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Active units (properties)</p>
                    <p className="text-2xl font-bold text-gray-900">{billing.current_unit_count ?? 0}</p>
                    <p className="text-sm text-gray-600 mt-1">$1/unit/mo baseline</p>
                  </div>
                  <div className="p-4 rounded-lg bg-gray-50 border border-gray-200">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Units with Shield</p>
                    <p className="text-2xl font-bold text-gray-900">{billing.current_shield_count ?? 0}</p>
                    <p className="text-sm text-gray-600 mt-1">$10/unit/mo when active</p>
                  </div>
                </div>
                <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
                  <p className="text-sm font-medium text-gray-800 mb-1">Monthly subscription</p>
                  <p className="text-sm text-gray-600">
                    Baseline: ${(billing.current_unit_count ?? 0) * 1}/mo
                    {(billing.current_shield_count ?? 0) > 0 && (
                      <> · Shield: ${(billing.current_shield_count ?? 0) * 10}/mo</>
                    )}
                    {' '}
                    (prorated when you add/remove properties or toggle Shield)
                  </p>
                </div>
                {(billing.current_unit_count ?? 0) === 0 && (
                  <p className="text-gray-500 text-sm">Add a property to start your subscription.</p>
                )}
                {billing.can_invite === false && (
                  <div className="p-4 rounded-lg bg-amber-50 border border-amber-200">
                    <p className="text-sm font-medium text-amber-800">Pay your onboarding invoice to invite guests.</p>
                    <p className="text-xs text-amber-700 mt-1">Go to Billing to view and pay.</p>
                  </div>
                )}
                {onOpenBilling && (
                  <Button variant="outline" type="button" onClick={onOpenBilling}>
                    View Billing & Invoices
                  </Button>
                )}
              </div>
            )}
          </Card>
        )}

        {/* Master POA (owners only) */}
        {isOwner && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Master Power of Attorney (POA)</h2>
            <p className="text-gray-600 text-sm mb-4">
              The Master POA is the one-time document you signed during registration that designates DocuStay as your Authorized Agent for utility authorization and audit trails for all your properties.
            </p>
            {poaSignature === undefined ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : poaSignature ? (
              <div className="space-y-3">
                <p className="text-sm text-gray-700">
                  <span className="font-medium">Signed:</span> {poaSignature.signed_by} on {new Date(poaSignature.signed_at).toLocaleDateString()}
                </p>
                <Button variant="outline" type="button" onClick={openSignedPoaPdf}>
                  Download signed PDF
                </Button>
              </div>
            ) : (
              <p className="text-sm text-gray-500">No Master POA signature on file for this account.</p>
            )}
          </Card>
        )}

        {/* Notifications */}
        <Card className="p-8 md:p-10">
          <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Multi-Channel Alerts</h2>
          <div className="space-y-4">
            {[
              { id: 'emailNotifs', label: 'Email Notifications', desc: 'Receive detailed stay reports and documentation copies.' },
             
            ].map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between p-4 rounded-lg bg-gray-50 border border-gray-200"
              >
                <div>
                  <p className="font-medium text-gray-900">{item.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{item.desc}</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0 ml-4">
                  <input
                    type="checkbox"
                    checked={(prefs as any)[item.id]}
                    onChange={(e) => setPrefs({ ...prefs, [item.id]: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-300 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500/40 rounded-full peer after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5 peer-checked:bg-blue-700" />
                </label>
              </div>
            ))}
          </div>
        </Card>

        {/* Default Stay Parameters */}
        <Card className="p-8 md:p-10">
          <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Default Stay Parameters</h2>
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Default Max Duration ({prefs.defaultStayDays} days)
              </label>
              <input
                type="range"
                min="1"
                max="29"
                value={prefs.defaultStayDays}
                onChange={(e) => setPrefs({ ...prefs, defaultStayDays: parseInt(e.target.value) })}
                className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-700"
              />
              <p className="mt-2 text-xs text-gray-500">
                DocuStay documents stays within the configured duration for your region.
              </p>
            </div>
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
              <h4 className="font-semibold text-slate-800 text-sm mb-2">Documentation defaults</h4>
              <ul className="text-sm text-gray-700 space-y-2">
                <li className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-blue-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  Temporary occupant status documented
                </li>
                <li className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-blue-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  Utility Kill Switch Authorization
                </li>
              </ul>
            </div>
          </div>
        </Card>

        {/* Security */}
        <Card className="p-8 md:p-10">
          <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Security</h2>
          <p className="text-gray-600 text-sm">Password and security options will appear here.</p>
        </Card>
      </div>
    </div>
  );
};

export default Settings;
