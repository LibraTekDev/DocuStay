import React, { useState, useEffect } from 'react';
import { publicApi, type VerifyResponse } from '../../services/api';

function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'short' });
}

const APP_ORIGIN = typeof window !== 'undefined' ? window.location.origin : '';

export const VerifyPage: React.FC = () => {
  const [tokenId, setTokenId] = useState('');
  const [propertyAddress, setPropertyAddress] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VerifyResponse | null>(null);

  // Pre-fill from query params (#verify?token=...&address=... or ?token=...&address=...)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const hash = window.location.hash || '';
    const fromHash = new URLSearchParams(hash.split('?')[1] || '');
    const fromSearch = new URLSearchParams(window.location.search || '');
    const token = fromHash.get('token') || fromHash.get('token_id') || fromSearch.get('token') || fromSearch.get('token_id') || '';
    const address = fromHash.get('address') || fromHash.get('property_address') || fromSearch.get('address') || fromSearch.get('property_address') || '';
    if (token) setTokenId(token);
    if (address) setPropertyAddress(decodeURIComponent(address));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    if (!(tokenId ?? "").trim()) {
      setError('Token ID is required.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await publicApi.verify({
        token_id: (tokenId ?? "").trim(),
        property_address: (propertyAddress ?? "").trim() || undefined,
        name: (name ?? "").trim() || undefined,
        phone: (phone ?? "").trim() || undefined,
      });
      setResult(res);
    } catch (err) {
      setError((err as Error)?.message ?? 'Verification failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const liveLink = typeof window !== 'undefined' ? window.location.href : `${APP_ORIGIN}/#verify`;

  const inputClass = "w-full px-4 py-2.5 rounded-lg border border-gray-300 text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors";

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-100/60 via-blue-50/30 to-sky-50/50 text-gray-800 print:bg-white print:min-h-0">
      <div className="max-w-xl mx-auto px-4 sm:px-6 py-8 sm:py-10 space-y-6 print:py-6">
        <header className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Verify authorization</h1>
          <p className="text-gray-600 mt-1 text-sm">
            Enter the token (Invitation ID) to check for an active authorization. The property address will be shown in the result.
          </p>
        </header>

        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 space-y-4 print:shadow-none print:border">
          <div>
            <label htmlFor="verify-token" className="block text-sm font-medium text-gray-700 mb-1.5">
              Token ID <span className="text-red-500">*</span>
            </label>
            <input
              id="verify-token"
              type="text"
              value={tokenId}
              onChange={(e) => setTokenId(e.target.value)}
              placeholder="e.g. INV-XXXX"
              className={inputClass}
              required
            />
          </div>
          <div>
            <label htmlFor="verify-address" className="block text-sm font-medium text-gray-600 mb-1.5">
              Property address <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <textarea
              id="verify-address"
              value={propertyAddress}
              onChange={(e) => setPropertyAddress(e.target.value)}
              placeholder="Street, city, state, ZIP"
              rows={2}
              className={`${inputClass} resize-none`}
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="verify-name" className="block text-sm font-medium text-gray-600 mb-1.5">Name (optional)</label>
              <input id="verify-name" type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label htmlFor="verify-phone" className="block text-sm font-medium text-gray-600 mb-1.5">Phone (optional)</label>
              <input id="verify-phone" type="text" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />
            </div>
          </div>
          {error && (
            <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-center gap-2">
              <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full sm:w-auto min-w-[140px] px-6 py-2.5 rounded-lg bg-blue-700 text-white font-medium hover:bg-blue-800 disabled:opacity-50 disabled:cursor-not-allowed focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
          >
            {submitting ? (
              <span className="inline-flex items-center gap-2">
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
                Verifying…
              </span>
            ) : (
              'Verify'
            )}
          </button>
        </form>

        {result && (
          <section className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden print:shadow-none print:border">
            <div className={`px-6 py-4 border-b ${result.valid ? 'bg-emerald-50 border-emerald-100' : 'bg-amber-50 border-amber-100'} print:bg-gray-50 print:border-gray-200`}>
              <h2 className="text-sm font-bold uppercase tracking-wider text-gray-700">Result</h2>
            </div>
            <div className="p-6 sm:p-8 space-y-5">
              {result.valid ? (
                <>
                  <div className="inline-flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200">
                    <svg className="w-5 h-5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
                    <span className="font-semibold">Active authorization found</span>
                  </div>
                  <dl className="grid gap-4 text-sm">
                    <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Property</dt><dd className="text-gray-900 font-medium">{result.property_name || '—'}</dd></div>
                    <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Address</dt><dd className="text-gray-900">{result.property_address || '—'}</dd></div>
                    <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Occupancy</dt><dd className="text-gray-900">{result.occupancy_status ?? '—'}</dd></div>
                    <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Authorization state</dt><dd className="text-gray-900">{result.token_state ?? '—'}</dd></div>
                    {result.guest_name && <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Guest</dt><dd className="text-gray-900">{result.guest_name}</dd></div>}
                    {result.stay_end_date && <div className="pb-3 border-b border-gray-100"><dt className="text-gray-500 font-medium mb-0.5">Stay end date</dt><dd className="text-gray-900">{new Date(result.stay_end_date).toLocaleDateString('en-US')}</dd></div>}
                  </dl>
                  <p className="text-sm text-gray-500">
                    This property is documented under a signed Master POA.{result.poa_signed_at && ` POA signed: ${new Date(result.poa_signed_at).toLocaleDateString('en-US')}.`}
                  </p>
                  <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-gray-200 text-sm">
                    <span className="text-gray-600">Record ID: <span className="font-mono text-gray-800 bg-gray-100 px-2 py-1 rounded text-xs">{result.live_slug ?? '—'}</span></span>
                    <span className="text-gray-400">{result.generated_at ? formatDateTime(result.generated_at) : ''}</span>
                    {result.live_slug && (
                      <a
                        href={`${APP_ORIGIN}/#live/${result.live_slug}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-700 hover:text-blue-800 font-medium hover:underline inline-flex items-center gap-1"
                      >
                        Open full evidence page
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                      </a>
                    )}
                  </div>
                  <a href={liveLink} className="inline-flex items-center gap-1.5 text-blue-700 hover:text-blue-800 font-medium text-sm">
                    Live link for re-verification
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                  </a>
                </>
              ) : (
                <>
                  <div className="inline-flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-amber-50 text-amber-800 border border-amber-200">
                    <svg className="w-5 h-5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
                    <span className="font-semibold">No active authorization found</span>
                  </div>
                  {result.reason && <p className="text-gray-700">{result.reason}</p>}
                  <p className="text-sm text-gray-500">
                    {result.generated_at ? `Checked at ${formatDateTime(result.generated_at)}` : ''}
                  </p>
                </>
              )}
            </div>
            {result.valid && result.audit_entries && result.audit_entries.length > 0 && (
              <div className="border-t border-gray-200 px-6 py-4 bg-gray-50/50">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">Recent audit timeline</h3>
                <ul className="space-y-2 text-sm text-gray-700 max-h-48 overflow-y-auto">
                  {result.audit_entries.slice(0, 10).map((entry, i) => (
                    <li key={i} className="flex gap-3 items-start">
                      <span className="text-gray-400 shrink-0 text-xs">{entry.created_at ? formatDateTime(entry.created_at) : '—'}</span>
                      <span>{entry.title || entry.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {result && (
          <div className="flex justify-end print:block">
            <button
              type="button"
              onClick={() => window.print()}
              className="px-5 py-2.5 rounded-lg bg-gray-700 text-white text-sm font-medium hover:bg-gray-800 print:hidden transition-colors"
            >
              Print page
            </button>
          </div>
        )}

        <footer className="text-center text-xs text-gray-500 pt-6 print:pt-2">
          <p className="font-medium text-gray-600">DocuStay Verify</p>
          <p className="mt-0.5 text-gray-400">Read-only · All attempts are logged</p>
        </footer>
      </div>
    </div>
  );
};
