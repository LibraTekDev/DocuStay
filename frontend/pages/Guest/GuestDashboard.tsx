import React, { useState, useEffect, useCallback } from 'react';
import { Button, Input } from '../../components/UI';
import { UserSession } from '../../types';
import { dashboardApi, authApi, APP_ORIGIN, type GuestStayView, type GuestPendingInviteView } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import AgreementSignModal from '../../components/AgreementSignModal';
import { PENDING_INVITE_STORAGE_KEY } from './GuestLogin';

function parseInviteCode(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
}

function daysLeft(endDateStr: string): number {
  const end = new Date(endDateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  return Math.max(0, Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)));
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** True if [start1, end1] overlaps [start2, end2] (dates as YYYY-MM-DD or parseable strings). */
function datesOverlap(
  start1: string,
  end1: string,
  start2: string,
  end2: string
): boolean {
  const a1 = new Date(start1).getTime();
  const a2 = new Date(end1).getTime();
  const b1 = new Date(start2).getTime();
  const b2 = new Date(end2).getTime();
  return a1 < b2 && a2 > b1;
}

/** Today's date in local timezone as YYYY-MM-DD (so check-in on "today" shows as ongoing, not upcoming). */
function getTodayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** List of YYYY-MM-DD strings from start (inclusive) to end (inclusive). */
function dateRange(startStr: string, endStr: string): string[] {
  const out: string[] = [];
  const start = new Date(startStr);
  const end = new Date(endStr);
  const cur = new Date(start);
  while (cur <= end) {
    const y = cur.getFullYear();
    const m = String(cur.getMonth() + 1).padStart(2, '0');
    const d = String(cur.getDate()).padStart(2, '0');
    out.push(`${y}-${m}-${d}`);
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

/** Human-friendly countdown: "X days", "1 day", "Ends today", "Ended". */
function countdownLabel(endDateStr: string, todayStr: string): { label: string; sublabel?: string } {
  const days = daysLeft(endDateStr);
  if (days === 0) return { label: 'Ends today', sublabel: 'Check-out is today' };
  if (days === 1) return { label: '1 day left', sublabel: 'until check-out' };
  if (days > 0 && days <= 7) return { label: `${days} days left`, sublabel: 'until check-out' };
  if (days > 7) {
    const weeks = Math.floor(days / 7);
    const remainder = days % 7;
    if (remainder === 0) return { label: `${weeks} week${weeks !== 1 ? 's' : ''} left`, sublabel: `${days} days until check-out` };
    return { label: `${days} days left`, sublabel: `${weeks} week${weeks !== 1 ? 's' : ''} and ${remainder} day${remainder !== 1 ? 's' : ''} until check-out` };
  }
  return { label: 'Stay ended', sublabel: undefined };
}

type StayFilter = 'all' | 'ongoing' | 'future' | 'previous' | 'future_invites';

export const GuestDashboard: React.FC<{ user: UserSession; navigate: (v: string) => void; notify: (t: 'success' | 'error', m: string) => void }> = ({ user, navigate, notify }) => {
  const [stays, setStays] = useState<GuestStayView[]>([]);
  const [pendingInvites, setPendingInvites] = useState<GuestPendingInviteView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStay, setSelectedStay] = useState<GuestStayView | null>(null);
  const [stayFilter, setStayFilter] = useState<StayFilter>('all');
  const [endStayConfirm, setEndStayConfirm] = useState<GuestStayView | null>(null);
  const [endingStay, setEndingStay] = useState(false);
  const [cancelStayConfirm, setCancelStayConfirm] = useState<GuestStayView | null>(null);
  const [cancellingStay, setCancellingStay] = useState(false);
  const [agreementModalCode, setAgreementModalCode] = useState<string | null>(null);
  const [inviteLinkInput, setInviteLinkInput] = useState('');
  const [addingInvite, setAddingInvite] = useState(false);
  const [agreementDownloading, setAgreementDownloading] = useState(false);
  const [showLiveLinkModal, setShowLiveLinkModal] = useState(false);
  const [liveLinkSlug, setLiveLinkSlug] = useState<string | null>(null);
  const [copyToast, setCopyToast] = useState<string | null>(null);
  const [checkingInStay, setCheckingInStay] = useState<GuestStayView | null>(null);

  const loadData = useCallback(() => {
    Promise.all([
      dashboardApi.guestStays(),
      dashboardApi.guestPendingInvites().catch(() => []),
    ])
      .then(([staysData, pendingData]) => {
        setStays(staysData);
        setPendingInvites(pendingData);
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? 'Failed to load data.';
        setError(msg);
        notify('error', msg);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    const code = sessionStorage.getItem(PENDING_INVITE_STORAGE_KEY);
    if (!code) return;
    sessionStorage.removeItem(PENDING_INVITE_STORAGE_KEY);
    dashboardApi.guestAddPendingInvite(code)
      .then(() => {
        loadData();
        setAgreementModalCode(code);
      })
      .catch((e) => {
        loadData();
        notify('error', (e as Error)?.message ?? 'Invalid or expired invitation.');
      });
  }, [loadData, notify]);

  const handleAgreementSigned = useCallback(async (signatureId: number) => {
    if (!agreementModalCode) return;
    try {
      await authApi.acceptInvite(agreementModalCode, signatureId);
      notify('success', 'Invitation accepted. Your stay is confirmed.');
      setAgreementModalCode(null);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not accept invitation.');
    }
  }, [agreementModalCode, loadData, notify]);

  const handleEndStay = useCallback(async () => {
    if (!endStayConfirm) return;
    setEndingStay(true);
    try {
      await dashboardApi.guestEndStay(endStayConfirm.stay_id);
      notify('success', 'Checkout complete. Your stay has ended and status has been updated.');
      setEndStayConfirm(null);
      setSelectedStay(null);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not end stay.');
    } finally {
      setEndingStay(false);
    }
  }, [endStayConfirm, loadData, notify]);

  const handleCancelStay = useCallback(async () => {
    if (!cancelStayConfirm) return;
    setCancellingStay(true);
    try {
      await dashboardApi.guestCancelStay(cancelStayConfirm.stay_id);
      notify('success', 'Stay cancelled. Your upcoming stay has been removed.');
      setCancelStayConfirm(null);
      setSelectedStay(null);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not cancel stay.');
    } finally {
      setCancellingStay(false);
    }
  }, [cancelStayConfirm, loadData, notify]);

  const handleCheckIn = useCallback(async (s: GuestStayView) => {
    setCheckingInStay(s);
    try {
      await dashboardApi.guestCheckIn(s.stay_id);
      notify('success', 'You are checked in. Your stay is now active.');
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not check in.');
    } finally {
      setCheckingInStay(null);
    }
  }, [loadData, notify]);

  const handleAddInviteLink = useCallback(() => {
    const code = parseInviteCode(inviteLinkInput);
    if (!code) {
      notify('error', 'Please enter a valid invitation link or code.');
      return;
    }
    setAddingInvite(true);
    dashboardApi.guestAddPendingInvite(code)
      .then(() => {
        setInviteLinkInput('');
        loadData();
        setAgreementModalCode(code);
        notify('success', 'Invitation added. Review and sign the agreement below.');
      })
      .catch((e) => {
        notify('error', (e as Error)?.message ?? 'Invalid or expired invitation. Please check the link.');
      })
      .finally(() => setAddingInvite(false));
  }, [inviteLinkInput, loadData, notify]);

  if (loading) {
    return (
      <div className="flex-grow w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8 flex items-center justify-center min-h-[200px]">
        <p className="text-slate-500 text-sm">Loading…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-grow w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <p className="text-slate-600 text-sm mb-4">Something went wrong loading your dashboard.</p>
          <Button variant="primary" className="rounded-lg font-medium" onClick={() => { setError(null); loadData(); }}>Try again</Button>
        </div>
      </div>
    );
  }
  const isEmpty = stays.length === 0 && pendingInvites.length === 0;
  const today = getTodayStr();

  // Ongoing = guest has checked in and stay period includes today
  const ongoingStays = stays.filter(
    (s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at && s.approved_stay_start_date <= today && s.approved_stay_end_date >= today
  );
  const futureStays = stays.filter(
    (s) => !s.checked_out_at && !s.cancelled_at && s.approved_stay_start_date > today
  );
  const completedStays = stays.filter(
    (s) => s.checked_out_at != null || s.cancelled_at != null || (s.approved_stay_end_date < today && s.checked_in_at)
  );

  const filteredStays: GuestStayView[] =
    stayFilter === 'all'
      ? stays
      : stayFilter === 'ongoing'
        ? ongoingStays
        : stayFilter === 'future'
          ? futureStays
          : stayFilter === 'previous'
            ? completedStays
            : [];

  const futureInvites = pendingInvites.filter((inv) =>
    !stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
  );

  const guestEmail = user?.email ?? '';
  const guestFullName = user?.user_name ?? '';
  const stay = selectedStay ?? (stayFilter === 'future_invites' ? null : filteredStays[0] ?? null);
  const dLeft = stay ? daysLeft(stay.approved_stay_end_date) : 0;
  const totalDays = stay ? Math.max(1, Math.ceil((new Date(stay.approved_stay_end_date).getTime() - new Date(stay.approved_stay_start_date).getTime()) / (1000 * 60 * 60 * 24))) : 1;
  const elapsedDays = Math.max(0, totalDays - dLeft);
  const progressPercent = stay ? Math.min(100, (elapsedDays / totalDays) * 100) : 0;

  const filterButtons: { id: StayFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All stays', count: stays.length },
    { id: 'ongoing', label: 'Ongoing stay', count: ongoingStays.length },
    { id: 'future', label: 'Future stay', count: futureStays.length },
    { id: 'previous', label: 'Completed', count: completedStays.length },
    { id: 'future_invites', label: 'Future invites', count: futureInvites.length },
  ];

  return (
    <div className="flex-grow w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8 flex flex-col min-h-0 relative">
      {/* Filters in left margin (desktop) | Invitation + Stay cards full width */}
      <div className="flex flex-col md:block flex-1 min-w-0 mb-6 lg:mb-8">
        {/* Filters: in flow on mobile (below invitation), absolute in left margin on desktop */}
        <aside className="order-2 md:absolute md:right-full md:mr-8 md:top-6 w-full md:w-52 shrink-0">
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:sticky md:top-6">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3 px-0.5">Filters</h3>
            <nav className="flex flex-row md:flex-col gap-1 overflow-x-auto no-scrollbar md:overflow-visible pb-1 md:pb-0">
              {filterButtons.map(({ id, label, count }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => { setStayFilter(id); if (id !== 'future_invites') setSelectedStay(null); }}
                  className={`px-3 py-2.5 rounded-lg text-left whitespace-nowrap text-sm font-medium transition-colors w-full lg:w-full ${
                    stayFilter === id ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  <span>{label}</span>
                  <span className={`ml-1.5 tabular-nums ${stayFilter === id ? 'text-slate-300' : 'text-slate-400'}`}>({count})</span>
                </button>
              ))}
            </nav>
          </div>
        </aside>

        {/* Add invitation - full width (same as before) */}
        <section className="order-1 mb-6 lg:mb-8">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-sm">
              <h2 className="text-base font-semibold text-slate-900 mb-1">Add invitation</h2>
              <p className="text-sm text-slate-600 mb-4">
                {isEmpty ? 'Paste an invitation link from your host to view and sign the agreement.' : 'Have another link? Add it below to review and sign.'}
              </p>
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="flex-1 min-w-0">
                  <Input
                    label="Invitation link or code"
                    name="invite_link"
                    value={inviteLinkInput}
                    onChange={(e) => setInviteLinkInput(e.target.value)}
                    placeholder="Paste link or code (e.g. INV-XXXX)"
                  />
                </div>
                <Button
                  variant="primary"
                  className="shrink-0 self-stretch sm:self-auto sm:mt-7 h-10 px-5 rounded-lg font-medium"
                  onClick={handleAddInviteLink}
                  disabled={addingInvite || !parseInviteCode(inviteLinkInput)}
                >
                  {addingInvite ? 'Adding…' : 'View & sign'}
                </Button>
              </div>
            </div>
        </section>

        {/* Stay cards - right margin on desktop (vertical list), in flow on mobile */}
        <aside className="order-3 w-full md:absolute md:left-full md:ml-8 md:top-6 md:w-64 md:max-h-[calc(100vh-8rem)] md:overflow-y-auto shrink-0">
          {stayFilter !== 'future_invites' && (
            <>
              {filteredStays.length === 0 ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-6 md:p-4">
                  <p className="text-slate-600 text-sm">
                    {stayFilter === 'all' ? 'No stays yet.' : stayFilter === 'previous' ? 'No completed stays.' : `No ${stayFilter} stays.`} Add an invitation link and accept an invite to see stays here.
                  </p>
                </div>
              ) : (
                <div className="flex flex-col gap-3 md:gap-2">
                    {filteredStays.map((s) => {
                      const isOngoing = !!(s.checked_in_at && s.approved_stay_start_date <= today && s.approved_stay_end_date >= today);
                      const isFuture = s.approved_stay_start_date > today;
                      const isUpcoming = !s.checked_in_at && !s.checked_out_at && !s.cancelled_at && s.approved_stay_start_date <= today && s.approved_stay_end_date >= today;
                      // Show Check in when guest hasn't checked in yet (within stay window); show Checkout only after check-in or if revoked
                      const canCheckIn = isUpcoming;
                      const hasCheckedIn = !!(s.checked_in_at != null && s.checked_in_at !== '');
                      const canCheckout = (hasCheckedIn || s.revoked_at != null) && !s.checked_out_at && !s.cancelled_at && s.approved_stay_end_date >= today;
                      const canCancel = isFuture && !s.cancelled_at;
                      const isSelected = selectedStay?.stay_id === s.stay_id;
                      return (
                      <div
                        key={s.stay_id}
                        className={`rounded-xl border bg-white text-left transition-all ${
                          isSelected
                            ? 'border-slate-300 border-l-4 border-l-indigo-500 bg-indigo-50/40 shadow-sm'
                            : 'border-slate-200 hover:border-slate-300'
                        }`}
                      >
                          <button
                            type="button"
                            onClick={() => setSelectedStay(isSelected ? null : s)}
                            className="w-full text-left p-4"
                          >
                            <div className="flex items-center gap-2 mb-2 flex-wrap">
                              {(s.revoked_at || s.vacate_by) && (
                                <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide bg-red-50 text-red-700 border border-red-100">Revoked</span>
                              )}
                              <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${
                                s.cancelled_at ? 'bg-amber-50 text-amber-700 border border-amber-100' : s.checked_out_at ? 'bg-slate-100 text-slate-600 border border-slate-200' : isOngoing ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : isUpcoming ? 'bg-amber-50 text-amber-700 border border-amber-100' : isFuture ? 'bg-sky-50 text-sky-700 border border-sky-100' : 'bg-slate-100 text-slate-600'
                              }`}>
                                {s.cancelled_at ? 'Cancelled' : s.checked_out_at ? 'Completed' : isOngoing ? 'Ongoing' : isUpcoming ? 'Upcoming' : isFuture ? 'Future' : 'Previous'}
                              </span>
                              <span className="text-slate-400 text-xs">{s.region_code}</span>
                            </div>
                            <p className="font-semibold text-slate-900">{s.property_name}</p>
                            <p className="text-sm text-slate-500 mt-0.5">
                              {formatDate(s.approved_stay_start_date)} – {formatDate(s.approved_stay_end_date)}
                            </p>
                          </button>
                          {canCheckIn && (
                            <div className="px-4 pb-4 pt-0">
                              <button
                                type="button"
                                disabled={!!checkingInStay}
                                className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
                                onClick={(e) => { e.stopPropagation(); handleCheckIn(s); }}
                              >
                                {checkingInStay?.stay_id === s.stay_id ? 'Checking in…' : 'Check in'}
                              </button>
                            </div>
                          )}
                          {canCheckout && (
                            <div className="px-4 pb-4 pt-0">
                              <button
                                type="button"
                                className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                                onClick={(e) => { e.stopPropagation(); setEndStayConfirm(s); }}
                              >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                                Checkout
                              </button>
                            </div>
                          )}
                          {canCancel && (
                            <div className="px-4 pb-4 pt-0">
                              <button
                                type="button"
                                className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors flex items-center justify-center gap-2"
                                onClick={(e) => { e.stopPropagation(); setCancelStayConfirm(s); }}
                              >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                                Cancel stay
                              </button>
                            </div>
                          )}
                        </div>
                      );
                  })}
                </div>
              )}
            </>
          )}
        </aside>

        {/* Future invites - center content when that filter is selected */}
        <div className="order-4 flex-1 min-w-0 w-full space-y-6">
          {stayFilter === 'future_invites' && (
            <>
              <h2 className="text-lg font-semibold text-slate-900">Future invites</h2>
              <p className="text-sm text-slate-500 mb-4">Invitations that don't overlap your existing stays. Sign the agreement to accept.</p>
              {futureInvites.length === 0 ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-8">
                  <p className="text-slate-600 text-sm">No future invites. Add an invitation link above; only invites that don't overlap your stays will appear here.</p>
                </div>
              ) : (
                <ul className="space-y-3">
                  {futureInvites.map((inv) => (
                    <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border border-slate-200 bg-white">
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-slate-900">{inv.property_name}</p>
                        <p className="text-sm text-slate-500 mt-0.5">
                          {formatDate(inv.stay_start_date)} – {formatDate(inv.stay_end_date)}
                        </p>
                        <p className="text-xs text-slate-400 mt-0.5">{inv.host_name}</p>
                      </div>
                      <Button variant="primary" className="shrink-0 h-10 rounded-lg font-medium px-4" onClick={() => setAgreementModalCode(inv.invitation_code)}>
                        Review & sign
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>

      {/* Full-width stay detail (same width as invitation bar) - when a stay is selected, below Filters | Stay cards */}
      {stay && stayFilter !== 'future_invites' && (() => {
        const detailHasCheckedIn = !!(stay.checked_in_at != null && stay.checked_in_at !== '');
        return (
        <div className="w-full space-y-6 mb-6 lg:mb-8">
      {/* Revoked: must vacate in 12 hours */}
      {stay.revoked_at || stay.vacate_by ? (
        <div className="rounded-2xl border border-red-200 bg-red-50/80 p-5">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-red-100 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-red-900">Stay authorization revoked</h3>
              <p className="text-sm text-red-800 mt-1">You must vacate the property within <strong>12 hours</strong>.</p>
              {stay.vacate_by && (
                <p className="text-sm text-red-700 mt-2 font-medium">Vacate by: {new Date(stay.vacate_by).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {/* Hero: Stay overview */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-8">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-4 flex-wrap">
              <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide ${
                stay.cancelled_at
                  ? 'bg-amber-50 text-amber-700 border border-amber-100'
                  : stay.checked_out_at
                    ? 'bg-slate-100 text-slate-600'
                    : detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                      ? 'bg-emerald-50 text-emerald-700'
                      : !detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                        ? 'bg-amber-50 text-amber-700 border border-amber-100'
                        : stay.approved_stay_start_date > today
                          ? 'bg-sky-50 text-sky-700'
                          : 'bg-slate-100 text-slate-600'
              }`}>
                {stay.cancelled_at
                  ? 'Cancelled'
                  : stay.checked_out_at
                    ? 'Completed'
                    : detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                      ? 'Ongoing'
                      : !detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                        ? 'Upcoming'
                        : stay.approved_stay_start_date > today
                          ? 'Upcoming'
                          : 'Ended'}
              </span>
              <span className="text-slate-400">·</span>
              <span className="text-slate-500 text-sm">{stay.property_name}</span>
              <span className="text-slate-400 text-sm">({stay.region_code})</span>
              {stay.invite_id && (
                <>
                  <span className="text-slate-400">·</span>
                  <span className="text-slate-500 text-sm font-mono">Invite ID: {stay.invite_id}</span>
                  {stay.token_state && (
                    <span className={`ml-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                      stay.token_state === 'BURNED' ? 'bg-emerald-50 text-emerald-700' :
                      stay.token_state === 'EXPIRED' ? 'bg-slate-100 text-slate-600' :
                      stay.token_state === 'REVOKED' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'
                    }`}>
                      {stay.token_state}
                    </span>
                  )}
                </>
              )}
            </div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
              {stay.cancelled_at ? 'Stay cancelled' : stay.checked_out_at ? 'Stay completed' : stay.approved_stay_end_date < today ? 'Stay ended' : stay.approved_stay_start_date > today ? 'Upcoming stay' : `${dLeft} day${dLeft !== 1 ? 's' : ''} left`}
            </h1>
            <div className="flex gap-6 mt-4">
              <div>
                <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">Check-in</p>
                <p className="text-slate-900 font-medium mt-0.5">{formatDate(stay.approved_stay_start_date)}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">Check-out</p>
                <p className="text-slate-900 font-medium mt-0.5">{formatDate(stay.approved_stay_end_date)}</p>
              </div>
            </div>
          </div>
          <div className="md:w-56 flex flex-col gap-4 shrink-0">
            <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-slate-800 rounded-full transition-all duration-500" style={{ width: `${progressPercent}%` }} />
            </div>
            <p className="text-xs text-slate-400 font-medium">Stay progress</p>
            {stay.property_live_slug && (
              <Button
                type="button"
                variant="primary"
                className="w-full h-11 rounded-lg font-medium"
                onClick={() => { setLiveLinkSlug(stay.property_live_slug ?? null); setShowLiveLinkModal(true); }}
              >
                Open live link
              </Button>
            )}
            {!stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && stay.approved_stay_start_date <= today && !detailHasCheckedIn && (
              <button
                type="button"
                disabled={!!checkingInStay}
                className="w-full h-11 rounded-lg font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
                onClick={() => handleCheckIn(stay)}
              >
                {checkingInStay?.stay_id === stay.stay_id ? 'Checking in…' : 'Check in'}
              </button>
            )}
            {!stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && (detailHasCheckedIn || stay.revoked_at != null) && (
              <button
                type="button"
                className="w-full h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                onClick={() => setEndStayConfirm(stay)}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                Complete checkout
              </button>
            )}
            {!stay.cancelled_at && stay.approved_stay_start_date > today && (
              <button
                type="button"
                className="w-full h-11 rounded-lg font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors flex items-center justify-center gap-2"
                onClick={() => setCancelStayConfirm(stay)}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                Cancel stay
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Countdown & calendar: time left in a pretty view (only when stay is current or upcoming and not ended) */}
      {stay && !stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && (() => {
        const countdown = countdownLabel(stay.approved_stay_end_date, today);
        const allDays = dateRange(stay.approved_stay_start_date, stay.approved_stay_end_date);
        const total = allDays.length;
        const maxShow = 42; // ~6 weeks
        const showDays = total <= maxShow ? allDays : allDays.slice(-maxShow);
        const isUpcoming = stay.approved_stay_start_date > today;
        return (
          <section className="rounded-2xl border border-indigo-200/80 bg-gradient-to-br from-indigo-50/80 via-white to-slate-50/60 p-6 md:p-8 shadow-sm">
            <h3 className="text-sm font-bold uppercase tracking-wider text-indigo-700 mb-4">Time left on your stay</h3>
            <div className="flex flex-col sm:flex-row sm:items-center gap-8">
              {/* Big countdown */}
              <div className="flex-shrink-0">
                <div className="inline-flex flex-col items-center justify-center rounded-2xl bg-white/90 border-2 border-indigo-200/80 shadow-inner px-8 py-6 min-w-[180px]">
                  <span className="text-4xl md:text-5xl font-bold tabular-nums text-indigo-900">
                    {dLeft}
                  </span>
                  <span className="text-sm font-semibold uppercase tracking-wider text-indigo-600 mt-1">
                    {dLeft === 0 ? 'day (check-out today)' : dLeft === 1 ? 'day left' : 'days left'}
                  </span>
                  {countdown.sublabel && (
                    <span className="text-xs text-slate-500 mt-0.5">{countdown.sublabel}</span>
                  )}
                </div>
              </div>
              {/* Calendar strip */}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-slate-500 mb-2">
                  {isUpcoming ? 'Your stay period' : 'Stay timeline'} · {formatDate(stay.approved_stay_start_date)} → {formatDate(stay.approved_stay_end_date)}
                </p>
                <div className="flex flex-wrap gap-1">
                  {showDays.map((dayStr) => {
                    const isToday = dayStr === today;
                    const isEnd = dayStr === stay.approved_stay_end_date;
                    const isPast = dayStr < today;
                    const isStart = dayStr === stay.approved_stay_start_date;
                    const dayNum = new Date(dayStr + 'T12:00:00').getDate();
                    return (
                      <div
                        key={dayStr}
                        title={`${dayStr}${isToday ? ' (today)' : ''}${isEnd ? ' (check-out)' : ''}`}
                        className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-medium transition-all ${
                          isToday
                            ? 'bg-indigo-600 text-white ring-2 ring-indigo-300 ring-offset-1 scale-110'
                            : isEnd
                              ? 'bg-amber-500 text-white font-semibold'
                              : isPast
                                ? 'bg-slate-200 text-slate-500'
                                : isStart
                                  ? 'bg-indigo-100 text-indigo-800 border border-indigo-200'
                                  : 'bg-slate-100 text-slate-700 border border-slate-200/80'
                        }`}
                      >
                        {dayNum}
                      </div>
                    );
                  })}
                </div>
                {total > maxShow && (
                  <p className="text-xs text-slate-400 mt-2">Showing last {maxShow} days of stay</p>
                )}
                <div className="flex flex-wrap gap-4 mt-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded bg-indigo-600" /> Today
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded bg-amber-500" /> Check-out day
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded bg-slate-200" /> Past
                  </span>
                </div>
              </div>
            </div>
          </section>
        );
      })()}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left: Authorization & documentation */}
        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-900 mb-4">Signed agreement</h3>
            <p className="text-sm text-slate-600 mb-4">Review and download your signed guest agreement for this stay.</p>
            <Button
              variant="outline"
              disabled={agreementDownloading}
              onClick={async () => {
                if (!selectedStay) return;
                setAgreementDownloading(true);
                try {
                  const blob = await dashboardApi.guestStaySignedAgreementBlob(selectedStay.stay_id);
                  const url = URL.createObjectURL(blob);
                  window.open(url, '_blank');
                  setTimeout(() => URL.revokeObjectURL(url), 60000);
                } catch (e) {
                  notify('error', (e as Error)?.message ?? 'No signed agreement found for this stay.');
                } finally {
                  setAgreementDownloading(false);
                }
              }}
            >
              {agreementDownloading ? 'Loading…' : 'Download signed agreement'}
            </Button>
          </div>

          {/* Applicable law from Jurisdiction SOT (same as live property page) */}
          {stay && (stay.jurisdiction_state_name || (stay.jurisdiction_statutes && stay.jurisdiction_statutes.length > 0)) && (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600/90">Applicable law ({stay.jurisdiction_state_name ?? stay.region_code})</p>
              <ul className="mt-2 space-y-2">
                {(stay.jurisdiction_statutes ?? []).map((s, i) => (
                  <li key={i} className="text-sm text-slate-700">
                    <span className="font-medium text-slate-900">{s.citation}</span>
                    {s.plain_english && <span className="block text-slate-600 mt-0.5">{s.plain_english}</span>}
                  </li>
                ))}
              </ul>
              {stay.removal_guest_text && (
                <p className="text-slate-600 text-sm mt-2">
                  <span className="font-medium text-slate-700">Guest removal: </span>{stay.removal_guest_text}
                </p>
              )}
              {stay.removal_tenant_text && (
                <p className="text-slate-600 text-sm mt-0.5">
                  <span className="font-medium text-slate-700">Tenant eviction: </span>{stay.removal_tenant_text}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Right: Help */}
        <div className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h4 className="font-semibold text-slate-900 mb-3">Need help?</h4>
            <div className="flex flex-col gap-2">
              <Button variant="outline" className="w-full justify-center h-10 rounded-lg text-sm font-medium">Message host</Button>
              <Button variant="outline" className="w-full justify-center h-10 rounded-lg text-sm font-medium">Contact support</Button>
            </div>
          </div>
        </div>
      </div>

      {/* Live link QR modal (same as owner: one button opens this, modal has QR + Open live page + Copy live link) */}
      {showLiveLinkModal && liveLinkSlug && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => { setShowLiveLinkModal(false); setLiveLinkSlug(null); setCopyToast(null); }} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Live link page</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan or share this link to open the property info page (no login).</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`)}`}
                  alt="QR code for live link"
                  className="w-40 h-40 rounded-lg"
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="primary"
                className="w-full"
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`, '_blank', 'noopener,noreferrer')}
              >
                Open live page
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const url = `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`;
                  const ok = await copyToClipboard(url);
                  setCopyToast(ok ? 'Live link copied to clipboard.' : 'Could not copy.');
                  setTimeout(() => setCopyToast(null), 3000);
                }}
              >
                Copy live link
              </Button>
            </div>
            {copyToast && (
              <p className={`text-sm text-center mt-2 ${copyToast.startsWith('Live link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                {copyToast}
              </p>
            )}
          </div>
        </div>
      )}
        </div>
  );
})()}

      {/* Checkout confirmation */}
      {endStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Checkout</h3>
            <p className="text-sm text-slate-600 mb-4">
              Have you vacated the property? Completing checkout will end your stay and set your checkout date to today ({formatDate(today)}). This cannot be undone.
            </p>
            <p className="text-sm font-medium text-slate-700 mb-6">{endStayConfirm.property_name}</p>
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1 h-11 rounded-lg font-medium" onClick={() => setEndStayConfirm(null)} disabled={endingStay}>
                Cancel
              </Button>
              <button
                type="button"
                disabled={endingStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 flex items-center justify-center"
                onClick={handleEndStay}
              >
                {endingStay ? 'Completing…' : 'Complete checkout'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cancel stay confirmation */}
      {cancelStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Cancel stay</h3>
            <p className="text-sm text-slate-600 mb-4">
              Cancel your upcoming stay? This will remove the stay from your dashboard and notify the host. This cannot be undone.
            </p>
            <p className="text-sm font-medium text-slate-700 mb-6">{cancelStayConfirm.property_name}</p>
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1 h-11 rounded-lg font-medium" onClick={() => setCancelStayConfirm(null)} disabled={cancellingStay}>
                Keep stay
              </Button>
              <button
                type="button"
                disabled={cancellingStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-slate-700 hover:bg-slate-800 disabled:opacity-60 flex items-center justify-center"
                onClick={handleCancelStay}
              >
                {cancellingStay ? 'Cancelling…' : 'Cancel stay'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Overlapping invites: cannot accept */}
      {pendingInvites.filter((inv) =>
        stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
      ).length > 0 && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-6 mt-6">
          <h3 className="text-base font-semibold text-slate-900 mb-1">Overlapping invitations</h3>
          <p className="text-sm text-slate-600 mb-4">These overlap with an accepted stay and cannot be accepted.</p>
          <ul className="space-y-3">
            {pendingInvites
              .filter((inv) =>
                stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
              )
              .map((inv) => (
                <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 bg-white rounded-xl border border-amber-100">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-slate-900">{inv.property_name}</p>
                    <p className="text-sm text-slate-500 mt-0.5">
                      {formatDate(inv.stay_start_date)} – {formatDate(inv.stay_end_date)}
                    </p>
                    <p className="text-xs text-amber-700 font-medium mt-1">Overlaps existing stay</p>
                  </div>
                  <span className="text-sm font-medium text-slate-400 shrink-0">Cannot accept</span>
                </li>
              ))}
          </ul>
        </div>
      )}

      {agreementModalCode && (
        <AgreementSignModal
          open={!!agreementModalCode}
          invitationCode={agreementModalCode}
          guestEmail={guestEmail}
          guestFullName={guestFullName}
          onClose={() => setAgreementModalCode(null)}
          onSigned={handleAgreementSigned}
          notify={notify}
        />
      )}
    </div>
  );
};
