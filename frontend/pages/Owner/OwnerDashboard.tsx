
import React, { useState, useEffect, useRef } from 'react';
import { Card, Button, Modal, LoadingOverlay, Input } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { InviteRoleChoiceModal } from '../../components/InviteRoleChoiceModal';
import { InviteTenantModal } from '../../components/InviteTenantModal';
import { UserSession } from '../../types';
import { dashboardApi, propertiesApi, getContextMode, setContextMode, onPropertiesChanged, type OwnerStayView, type OwnerInvitationView, type OwnerAuditLogEntry, type Property, type BulkUploadResult, type BillingResponse, type BillingInvoiceView, type BillingPaymentView } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import { getTodayLocal } from '../../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../../utils/invitationErrors';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import { InvitationsTabContent } from '../../components/InvitationsTabContent';

function daysLeft(endDateStr: string): number {
  const end = new Date(endDateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  const diff = Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  return Math.max(0, diff);
}

function isOverstayed(endDateStr: string): boolean {
  const end = new Date(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return end.getTime() < today.getTime();
}

function formatStayDuration(startStr: string, endStr: string): string {
  const start = new Date(startStr);
  const end = new Date(endStr);
  const days = Math.max(1, Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return `${fmt(start)} – ${fmt(end)} (${days} day${days !== 1 ? 's' : ''})`;
}

/** Invite ID token state badge: displays Pending | Active | Expired | Revoked (maps from STAGED | BURNED | EXPIRED | REVOKED) */
function TokenStateBadge({ tokenState }: { tokenState?: string | null }) {
  const state = (tokenState || 'STAGED').toUpperCase();
  const classes =
    state === 'BURNED'
      ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
      : state === 'STAGED'
        ? 'bg-sky-100 text-sky-700 border-sky-200'
        : state === 'EXPIRED'
          ? 'bg-slate-100 text-slate-600 border-slate-200'
          : state === 'REVOKED'
            ? 'bg-amber-100 text-amber-700 border-amber-200'
            : state === 'CANCELLED'
              ? 'bg-slate-100 text-slate-600 border-slate-200'
              : 'bg-slate-100 text-slate-600 border-slate-200';
  const displayLabel = state === 'BURNED' ? 'Active' : state === 'STAGED' ? 'Pending' : state === 'REVOKED' ? 'Revoked' : state === 'CANCELLED' ? 'Cancelled' : state === 'EXPIRED' ? 'Expired' : state;
  return (
    <span className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest border ${classes}`}>
      {displayLabel}
    </span>
  );
}

const OwnerDashboard: React.FC<{ user: UserSession; navigate: (v: string) => void; setLoading?: (l: boolean) => void; notify?: (t: 'success' | 'error', m: string) => void; initialTab?: string }> = ({ user, navigate, setLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {}, initialTab }) => {
  const [activeTab, setActiveTab] = useState(initialTab ?? 'dashboard');
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [inactiveProperties, setInactiveProperties] = useState<Property[]>([]);
  const [invitations, setInvitations] = useState<OwnerInvitationView[]>([]);
  const [loading, setLoadingState] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [showInviteRoleChoice, setShowInviteRoleChoice] = useState(false);
  const [showInviteTenantModal, setShowInviteTenantModal] = useState(false);
  const [revokeConfirmStay, setRevokeConfirmStay] = useState<OwnerStayView | null>(null);
  const [revokeSuccessGuest, setRevokeSuccessGuest] = useState<string | null>(null);
  const [packetModalStay, setPacketModalStay] = useState<OwnerStayView | null>(null);
  const [deleteConfirmProperty, setDeleteConfirmProperty] = useState<Property | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [shieldTogglePropertyId, setShieldTogglePropertyId] = useState<number | null>(null);
  const [logs, setLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsFromTs, setLogsFromTs] = useState('');
  const [logsToTs, setLogsToTs] = useState('');
  const [logsCategory, setLogsCategory] = useState('');
  const [logsSearch, setLogsSearch] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [showBulkUploadModal, setShowBulkUploadModal] = useState(false);
  const [showBulkUploadRulesModal, setShowBulkUploadRulesModal] = useState(false);
  const [bulkUploadResult, setBulkUploadResult] = useState<BulkUploadResult | null>(null);
  const [bulkUploading, setBulkUploading] = useState(false);
  const bulkUploadFileInputRef = useRef<HTMLInputElement | null>(null);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);
  const [paymentReturnMessage, setPaymentReturnMessage] = useState<string | null>(null);
  const [paymentReturnIsError, setPaymentReturnIsError] = useState(false);
  const [showVoidInvoiceDialog, setShowVoidInvoiceDialog] = useState(false);
  const [showVerifyQRModal, setShowVerifyQRModal] = useState(false);
  const [verifyQRInviteId, setVerifyQRInviteId] = useState<string | null>(null);
  const [verifyQRCopyToast, setVerifyQRCopyToast] = useState<string | null>(null);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  type AssignedManagerItem = { user_id: number; email: string; full_name: string | null; has_resident_mode: boolean; resident_unit_id: number | null; resident_unit_label: string | null };
  const [propertyManagersMap, setPropertyManagersMap] = useState<Record<number, AssignedManagerItem[]>>({});
  const [removingManager, setRemovingManager] = useState<{ propertyId: number; userId: number } | null>(null);
  const [removingResidentMode, setRemovingResidentMode] = useState<{ propertyId: number; userId: number } | null>(null);
  const [shieldFilter, setShieldFilter] = useState<'all' | 'on' | 'off'>('all');
  const [selectedPropertyIds, setSelectedPropertyIds] = useState<Set<number>>(new Set());
  const [bulkShieldLoading, setBulkShieldLoading] = useState(false);

  const setLoadingWrapper = (x: boolean) => { setLoadingState(x); setLoading(x); };

  const handleContextModeChange = (mode: 'business' | 'personal') => {
    setContextMode(mode);
    setContextModeState(mode);
    // Clear guest-related state immediately so no data carries over between modes
    if (mode === 'business') {
      setStays([]);
      setInvitations([]);
    }
    loadData();
  };

  const loadData = () => {
    setLoadingWrapper(true);
    setError(null);
    Promise.all([
      dashboardApi.ownerStays(),
      dashboardApi.ownerInvitations(),
      propertiesApi.list(),
      propertiesApi.listInactive(),
      dashboardApi.ownerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
    ])
      .then(([staysData, invitationsData, propertiesList, inactiveList, pmUnits]) => {
        setStays(staysData);
        setInvitations(invitationsData);
        setProperties(propertiesList);
        setInactiveProperties(inactiveList);
        setPersonalModeUnits((pmUnits as { unit_ids: number[] }).unit_ids || []);
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? 'Failed to load dashboard.';
        setError(msg);
        notify('error', msg);
      })
      .finally(() => setLoadingWrapper(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const unsub = onPropertiesChanged(() => loadData());
    return unsub;
  }, []);

  useEffect(() => {
    if (initialTab) setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    if (contextMode === 'personal' && ['billing', 'logs'].includes(activeTab)) setActiveTab('dashboard');
    if (contextMode === 'business' && ['guests', 'invitations'].includes(activeTab)) setActiveTab('dashboard');
  }, [contextMode]);

  useEffect(() => {
    if (activeTab !== 'properties' || properties.length === 0) return;
    const loadManagers = async () => {
      const next: Record<number, AssignedManagerItem[]> = {};
      await Promise.all(
        properties.map(async (prop) => {
          try {
            const list = await propertiesApi.listAssignedManagers(prop.id);
            next[prop.id] = list;
          } catch {
            next[prop.id] = [];
          }
        })
      );
      setPropertyManagersMap(next);
    };
    loadManagers();
  }, [activeTab, properties]);

  // Only checked-in stays count as active for occupancy, current guest, and DMS
  const activeStays = stays.filter((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  const activeCount = activeStays.length;
  // Overstay = still active (not checked out, not cancelled) but end date has passed
  const overstays = activeStays.filter((s) => isOverstayed(s.stay_end_date));
  const firstOverstay = overstays[0];

  const handleRevokeClick = (stay: OwnerStayView) => {
    setRevokeConfirmStay(stay);
  };

  const [revokeLoading, setRevokeLoading] = useState(false);
  const handleRevokeConfirm = async () => {
    if (!revokeConfirmStay) return;
    setRevokeLoading(true);
    try {
      await dashboardApi.revokeStay(revokeConfirmStay.stay_id);
      notify('success', 'Stay revoked. Guest must vacate within 12 hours. Email sent.');
      setRevokeConfirmStay(null);
      setRevokeSuccessGuest(revokeConfirmStay.guest_name);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to revoke stay.');
    } finally {
      setRevokeLoading(false);
    }
  };

  const handleInitiateRemoval = (stay: OwnerStayView) => {
    setPacketModalStay(stay);
  };

  const [removalLoading, setRemovalLoading] = useState(false);
  const handleRemovalConfirm = async () => {
    if (!packetModalStay) return;
    setRemovalLoading(true);
    try {
      await dashboardApi.initiateRemoval(packetModalStay.stay_id);
      notify('success', 'Removal initiated. Guest and owner notified via email.');
      setPacketModalStay(null);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to initiate removal.');
    } finally {
      setRemovalLoading(false);
    }
  };

  const loadLogs = () => {
    setLogsLoading(true);
    dashboardApi.ownerLogs({
      from_ts: logsFromTs ? new Date(logsFromTs).toISOString() : undefined,
      to_ts: logsToTs ? new Date(logsToTs).toISOString() : undefined,
      category: logsCategory || undefined,
      search: logsSearch.trim() || undefined,
    })
      .then(setLogs)
      .catch(() => setLogs([]))
      .finally(() => setLogsLoading(false));
  };

  useEffect(() => {
    if (activeTab === 'logs') loadLogs();
  }, [activeTab]);

  const loadBilling = () => {
    setBillingLoading(true);
    dashboardApi.billing()
      .then(setBilling)
      .catch(() => setBilling({ invoices: [], payments: [], can_invite: true }))
      .finally(() => setBillingLoading(false));
  };

  useEffect(() => {
    if (activeTab === 'billing') loadBilling();
  }, [activeTab]);

  // When returning from Stripe payment (portal or hosted invoice), refetch billing and show message so user sees paid status without reloading
  useEffect(() => {
    if (activeTab !== 'billing' || typeof window === 'undefined') return;
    const search = window.location.search || '';
    const hash = window.location.hash || '';
    const hasPaymentReturn = /redirect_status=|payment_intent=|payment_intent_client_secret=/.test(search) || /[?&]redirect_status=|[?&]payment_intent=/.test(hash);
    if (!hasPaymentReturn) return;
    const paymentFailed = /redirect_status=failed|payment_failed/.test(search) || /[?&]redirect_status=failed|[?&]payment_failed/.test(hash);
    setBillingLoading(true);
    dashboardApi.billing()
      .then((data) => {
        setBilling(data);
        setPaymentReturnIsError(!!paymentFailed);
        setPaymentReturnMessage(paymentFailed
          ? "Your payment could not be processed. Please update your payment method in the payment portal and try again."
          : "We've refreshed your payment status. If you just paid, your invoice and invite access are now updated.");
        // Clear payment params from URL so we don't re-trigger; keep user on Billing tab
        window.history.replaceState(null, '', window.location.pathname + '#dashboard/billing');
      })
      .catch(() => setBilling((prev) => prev ?? { invoices: [], payments: [], can_invite: true }))
      .finally(() => setBillingLoading(false));
  }, [activeTab]);

  // Load billing once on mount so can_invite is available (required before inviting guests)
  useEffect(() => {
    loadBilling();
  }, []);

  const canInvite = billing?.can_invite !== false;

  const openInviteModalOrNotify = () => {
    if (!canInvite) {
      notify('error', 'Pay your onboarding invoice before inviting guests. Go to Billing to view and pay.');
      setActiveTab('billing');
      return;
    }
    setShowInviteRoleChoice(true);
  };

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar Navigation (fixed width so it does not shrink) */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {[
            { id: 'dashboard', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
            { id: 'properties', label: 'My Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
            ...(contextMode === 'personal' ? [{ id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' }] : []),
            ...(contextMode === 'personal' ? [{ id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' }] : []),
            ...(contextMode !== 'personal' ? [{ id: 'billing', label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' }] : []),
            ...(contextMode !== 'personal' ? [{ id: 'logs', label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' }] : []),
            { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
            { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' }
          ].map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === item.id ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon}></path></svg>
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex-grow min-h-0" />

        {/* Mode switcher at bottom */}
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <ModeSwitcher
            contextMode={contextMode}
            personalModeUnits={personalModeUnits}
            onContextModeChange={handleContextModeChange}
          />
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* Mobile tab nav: when sidebar is hidden (below lg), show dropdown so Billing and all tabs are reachable */}
        <div className="lg:hidden mb-6">
          <label htmlFor="mobile-tab-select" className="sr-only">Navigate to</label>
          <select
            id="mobile-tab-select"
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="dashboard">Dashboard</option>
            <option value="properties">My Properties</option>
            {contextMode === 'personal' && <option value="guests">Guests</option>}
            {contextMode === 'personal' && <option value="invitations">Invitations</option>}
            {contextMode !== 'personal' && <option value="billing">Billing</option>}
            {contextMode !== 'personal' && <option value="logs">Event ledger</option>}
            <option value="settings">Settings</option>
            <option value="help">Help Center</option>
          </select>
        </div>
        {/* No duplicate header on Settings/Help – those pages render their own title and content */}
        {activeTab !== 'settings' && activeTab !== 'help' && (
          <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-6">
            <div>
              <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">
                {activeTab === 'properties' ? 'My Properties' : activeTab === 'guests' ? 'Guests' : activeTab === 'invitations' ? 'Invitations' : activeTab === 'billing' ? 'Billing' : activeTab === 'logs' ? 'Event ledger' : 'Overview'}
              </h1>
              <p className="text-slate-600 mt-1">
                {activeTab === 'properties' ? 'View, edit, or remove your registered properties.' : activeTab === 'guests' ? 'Guests currently staying at your properties and their stay details.' : activeTab === 'invitations' ? 'Pending invitations waiting for guests to accept.' : activeTab === 'billing' ? 'Invoices and payment history. Onboarding and subscription charges appear here.' : activeTab === 'logs' ? 'Immutable event ledger: status changes, guest signatures, payment and billing activity, and failed attempts. Filter by time, category, or search.' : 'Documentation and authorization for your properties.'}
              </p>
            </div>
            <div className="flex gap-4 flex-wrap items-center">
              {activeTab !== 'properties' && contextMode === 'personal' && (
                <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                  {!canInvite && (
                    <span
                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-2 bg-gray-900 text-white text-xs rounded shadow-lg whitespace-nowrap opacity-0 pointer-events-none transition-opacity duration-150 z-[200] group-hover:opacity-100"
                      role="tooltip"
                    >
                      Go to Billing and pay your onboarding fee to invite guests.
                    </span>
                  )}
                  <Button variant="outline" onClick={openInviteModalOrNotify} className={`px-6 flex items-center gap-2${!canInvite ? ' pointer-events-none' : ''}`} disabled={!canInvite}>
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                    Invite
                  </Button>
                </span>
              )}
              {activeTab === 'properties' && contextMode !== 'personal' && (
                <div className="flex items-center gap-1.5">
                  <Button variant="outline" onClick={() => setShowBulkUploadModal(true)} className="px-6 flex items-center gap-2">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                    Upload in bulk
                  </Button>
                  <button
                    type="button"
                    onClick={() => setShowBulkUploadRulesModal(true)}
                    className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                    aria-label="Bulk upload rules"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                  </button>
                </div>
              )}
              <Button variant="primary" onClick={() => navigate('add-property')} className="px-6">
                Register Property
              </Button>
            </div>
          </header>
        )}

        {error && (
          <div className="mb-8 p-6 rounded-2xl bg-slate-50 border border-slate-200 text-center">
            <p className="text-slate-600 mb-4">Something went wrong loading the dashboard.</p>
            <Button variant="primary" onClick={() => { setError(null); loadData(); }}>Try again</Button>
          </div>
        )}

        {loading ? (
          <p className="text-slate-600">Loading dashboard…</p>
        ) : activeTab === 'guests' && contextMode === 'personal' ? (
          /* Guests tab: pending invitations + active & expired stays (personal mode only; never show in business) */
          <div className="space-y-8">
            <p className="text-slate-500 text-sm">
              Pending invitations, active stays, and past/expired stays. Data is loaded from your dashboard.
            </p>

            {/* Pending invitations */}
            {invitations.filter((i) => i.status === 'pending').length > 0 && (
              <Card className="overflow-hidden">
                <div className="p-6 border-b border-slate-200 bg-amber-50">
                  <h3 className="text-xl font-bold text-slate-800">Pending invitations</h3>
                  <p className="text-xs text-slate-500 mt-1">Invites not yet accepted by the guest</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Invited (email)</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Planned stay</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Code</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {invitations.filter((i) => i.status === 'pending').map((inv) => (
                        <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                          <td className="px-6 py-5">
                            <span className="text-sm font-medium text-slate-800">{inv.guest_name || inv.guest_email || '—'}</span>
                          </td>
                          <td className="px-6 py-5">
                            <p className="text-sm font-medium text-slate-800">{inv.property_name}</p>
                            <p className="text-xs text-slate-500">{inv.region_code}</p>
                          </td>
                          <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                            {formatStayDuration(inv.stay_start_date, inv.stay_end_date)}
                          </td>
                          <td className="px-6 py-5 text-sm text-slate-600">{inv.region_code}</td>
                          <td className="px-6 py-5 text-xs font-mono text-slate-600">{inv.invitation_code}</td>
                          <td className="px-6 py-5">
                            {inv.is_expired ? (
                              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-100 text-slate-600 border border-slate-200">Expired</span>
                            ) : (
                              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-amber-500/10 text-amber-700 border border-amber-200">Pending</span>
                            )}
                          </td>
                          <td className="px-6 py-5 text-right">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={async () => {
                                const url = `${typeof window !== 'undefined' ? window.location.origin : ''}${typeof window !== 'undefined' ? window.location.pathname : ''}#invite/${inv.invitation_code}`;
                                const ok = await copyToClipboard(url);
                                if (ok) notify('success', 'Invitation link copied to clipboard.');
                                else notify('error', 'Could not copy. Please copy the link manually.');
                              }}
                            >
                              Copy link
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {/* Stays: active and expired */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-white/60 backdrop-blur-md">
                <h3 className="text-xl font-bold text-slate-800">Stays (active & past)</h3>
                <p className="text-xs text-slate-500 mt-1">Guests who accepted and their current or past stay</p>
              </div>
              {stays.length === 0 ? (
                <div className="px-6 py-12 text-center text-slate-500">No stays yet. When guests accept an invitation, they appear here.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Guest</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Stay period</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Days left</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {stays.map((stay) => {
                        const overstay = isOverstayed(stay.stay_end_date);
                        const dLeft = daysLeft(stay.stay_end_date);
                        const revoked = !!stay.revoked_at;
                        const completed = !!stay.checked_out_at;
                        const cancelled = !!stay.cancelled_at;
                        const isActive = !completed && !cancelled;
                        return (
                          <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors">
                            <td className="px-6 py-5">
                              <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-sm">
                                  {stay.guest_name.charAt(0)}
                                </div>
                                <div>
                                  <p className="text-sm font-bold text-slate-800">{stay.guest_name}</p>
                                  <p className="text-xs text-slate-500">Stay #{stay.stay_id}</p>
                                </div>
                              </div>
                            </td>
                            <td className="px-6 py-5">
                              <p className="text-sm font-medium text-slate-800">{stay.property_name}</p>
                              <p className="text-xs text-slate-500">{stay.region_code}</p>
                            </td>
                            <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                              {formatStayDuration(stay.stay_start_date, stay.stay_end_date)}
                            </td>
                            <td className="px-6 py-5 text-sm text-slate-600">{stay.region_code}</td>
                            <td className="px-6 py-5">
                              <span className={`text-sm font-bold ${!isActive ? 'text-slate-500' : revoked ? 'text-amber-600' : overstay ? 'text-red-600' : 'text-green-600'}`}>
                                {completed || cancelled ? '—' : revoked ? '—' : overstay ? '—' : `${dLeft}d`}
                              </span>
                            </td>
                            <td className="px-6 py-5">
                              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
                                stay.invitation_only ? 'bg-amber-50 text-amber-700 border border-amber-200' : completed ? 'bg-slate-100 text-slate-600 border border-slate-200' : cancelled ? 'bg-slate-100 text-slate-500 border border-slate-200' : revoked ? 'bg-amber-50 text-amber-700 border border-amber-500/20' : overstay ? 'bg-red-50 text-red-600 border border-red-500/20' : 'bg-green-50 text-green-700 border border-green-200'
                              }`}>
                                {stay.invitation_only ? 'Pending sign-up' : completed ? 'Completed' : cancelled ? 'Cancelled' : revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active'}
                              </span>
                            </td>
                            <td className="px-6 py-5 text-right space-x-2">
                              {stay.invite_id && (
                                <Button variant="outline" onClick={() => { setVerifyQRInviteId(stay.invite_id ?? null); setShowVerifyQRModal(true); }} className="text-xs py-2">Verify QR</Button>
                              )}
                              {stay.invitation_only ? (
                                <span className="text-xs text-slate-500"></span>
                              ) : completed || cancelled ? (
                                <span className="text-xs text-slate-500">—</span>
                              ) : revoked ? (
                                <span className="text-xs text-slate-500">Revoked</span>
                              ) : overstay ? (
                                <Button variant="danger" onClick={() => handleInitiateRemoval(stay)} className="text-xs py-2">Remove</Button>
                              ) : (
                                <Button variant="ghost" onClick={() => handleRevokeClick(stay)} className="text-xs py-2 text-red-600 hover:text-red-700">Revoke</Button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {stays.length === 0 && invitations.filter((i) => i.status === 'pending').length === 0 && (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">No guests or pending invites yet. Invite someone to get started.</p>
                <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                  {!canInvite && (
                    <span
                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-2 bg-gray-900 text-white text-xs rounded shadow-lg whitespace-nowrap opacity-0 pointer-events-none transition-opacity duration-150 z-[200] group-hover:opacity-100"
                      role="tooltip"
                    >
                      Go to Billing and pay your onboarding fee to invite guests.
                    </span>
                  )}
                  <Button variant="primary" onClick={openInviteModalOrNotify} className={!canInvite ? 'pointer-events-none' : undefined} disabled={!canInvite}>Invite</Button>
                </span>
              </Card>
            )}
          </div>
        ) : activeTab === 'invitations' && contextMode === 'personal' ? (
          <InvitationsTabContent
            invitations={invitations}
            stays={stays}
            loadData={loadData}
            notify={notify}
            showVerifyQR={true}
            onVerifyQR={(code) => { setVerifyQRInviteId(code); setShowVerifyQRModal(true); }}
            onCancelInvitation={async (id) => { await dashboardApi.cancelInvitation(id); notify('success', 'Invitation cancelled.'); loadData(); }}
            introText="Invitations you've sent. Pending invitations are labeled as expired after 12 hours if not accepted."
          />
        ) : activeTab === 'properties' ? (
          /* Properties tab: Active list + Inactive section */
          <div className="space-y-8">
            
            {properties.length === 0 && inactiveProperties.length === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">You haven’t registered any properties yet.</p>
                {contextMode !== 'personal' && (
                  <Button variant="primary" onClick={() => navigate('add-property')}>Register your first property</Button>
                )}
              </Card>
            ) : (
              <>
              {/* Active properties */}
              {properties.length > 0 && (
              <div>
                {contextMode === 'business' && (
                  <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-6 mb-6">
                    <Card className="p-6 border-l-4 border-blue-500">
                      <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Properties</p>
                      <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.length}</p>
                    </Card>
                    <Card className="p-6 border-l-4 border-emerald-500">
                      <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Occupied</p>
                      <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'occupied').length}</p>
                    </Card>
                    <Card className="p-6 border-l-4 border-sky-500">
                      <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Vacant</p>
                      <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'vacant').length}</p>
                    </Card>
                    <Card className="p-6 border-l-4 border-slate-400">
                      <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Unknown</p>
                      <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())).length}</p>
                    </Card>
                    <Card className="p-6 border-l-4 border-amber-500">
                      <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Shield On</p>
                      <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => p.shield_mode_enabled).length}</p>
                    </Card>
                  </div>
                )}
                <h3 className="text-lg font-bold text-slate-800 mb-4">Active properties</h3>
                <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                  <span className="text-slate-500 text-sm">Filter and manage Shield Mode for your properties.</span>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Shield Mode:</span>
                    <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
                      {(['all', 'on', 'off'] as const).map((f) => (
                        <button
                          key={f}
                          type="button"
                          onClick={() => setShieldFilter(f)}
                          className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${shieldFilter === f ? 'bg-slate-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                        >
                          {f === 'all' ? 'All' : f === 'on' ? 'Shield ON' : 'Shield OFF'}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {(() => {
                  const filteredProps = shieldFilter === 'all' ? properties : shieldFilter === 'on' ? properties.filter((p) => p.shield_mode_enabled) : properties.filter((p) => !p.shield_mode_enabled);
                  const allFilteredSelected = filteredProps.length > 0 && filteredProps.every((p) => selectedPropertyIds.has(p.id));
                  return filteredProps.length > 0 && (
                    <div className="mb-3 flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setSelectedPropertyIds(allFilteredSelected ? new Set() : new Set(filteredProps.map((p) => p.id)))}
                        className="text-sm text-slate-600 hover:text-slate-800 underline"
                      >
                        {allFilteredSelected ? 'Select none' : 'Select all'}
                      </button>
                      <span className="text-slate-400">·</span>
                      <span className="text-sm text-slate-500">({filteredProps.length} propert{filteredProps.length === 1 ? 'y' : 'ies'} shown)</span>
                    </div>
                  );
                })()}
                {selectedPropertyIds.size > 0 && (
                  <div className="mb-4 p-4 rounded-xl bg-slate-100 border border-slate-200 flex flex-wrap items-center justify-between gap-4">
                    <span className="text-sm font-medium text-slate-700">{selectedPropertyIds.size} propert{selectedPropertyIds.size === 1 ? 'y' : 'ies'} selected</span>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setSelectedPropertyIds(new Set())}>Clear selection</Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={bulkShieldLoading}
                        onClick={async () => {
                          setBulkShieldLoading(true);
                          try {
                            const res = await dashboardApi.bulkShieldMode([...selectedPropertyIds], true);
                            notify('success', res.message || `Shield Mode turned on for ${res.updated_count} propert${res.updated_count === 1 ? 'y' : 'ies'}.`);
                            setSelectedPropertyIds(new Set());
                            loadData();
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                          } finally {
                            setBulkShieldLoading(false);
                          }
                        }}
                      >
                        {bulkShieldLoading ? 'Updating…' : 'Turn Shield ON'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={bulkShieldLoading}
                        onClick={async () => {
                          setBulkShieldLoading(true);
                          try {
                            const res = await dashboardApi.bulkShieldMode([...selectedPropertyIds], false);
                            notify('success', res.message || `Shield Mode turned off for ${res.updated_count} propert${res.updated_count === 1 ? 'y' : 'ies'}.`);
                            setSelectedPropertyIds(new Set());
                            loadData();
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                          } finally {
                            setBulkShieldLoading(false);
                          }
                        }}
                      >
                        {bulkShieldLoading ? 'Updating…' : 'Turn Shield OFF'}
                      </Button>
                    </div>
                  </div>
                )}
                <div className="grid gap-6">
                {(shieldFilter === 'all' ? properties : shieldFilter === 'on' ? properties.filter((p) => p.shield_mode_enabled) : properties.filter((p) => !p.shield_mode_enabled)).map((prop) => {
                  const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
                  const displayName = prop.name || address || `Property #${prop.id}`;
                  // Business mode: use property status only (no guest data). Personal mode: can use stays for occupancy.
                  const activeStayForProp = contextMode === 'personal' ? activeStays.find((s) => s.property_id === prop.id) : null;
                  const isOccupied = contextMode === 'business'
                    ? (prop.occupancy_status || '').toLowerCase() === 'occupied'
                    : !!activeStayForProp;
                  const shieldOn = !!prop.shield_mode_enabled;
                  const shieldStatus = shieldOn ? (isOccupied ? 'PASSIVE GUARD' : 'ACTIVE MONITORING') : null;
                  const isSelected = selectedPropertyIds.has(prop.id);
                  return (
                    <Card key={prop.id} className="p-6 border border-slate-200">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                        <div className="flex items-start gap-3 flex-shrink-0">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => {
                              e.stopPropagation();
                              setSelectedPropertyIds((prev) => {
                                const next = new Set(prev);
                                if (next.has(prop.id)) next.delete(prop.id);
                                else next.add(prop.id);
                                return next;
                              });
                            }}
                            className="mt-1 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                            aria-label={`Select ${displayName}`}
                          />
                        <button
                          type="button"
                          onClick={() => navigate(`property/${prop.id}`)}
                          className="min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                        >
                          <div className="flex flex-wrap items-center gap-2 gap-y-1">
                            <h3 className="text-lg font-bold text-slate-800 truncate">{displayName}</h3>
                            {(() => {
                              const displayStatus = isOccupied ? 'OCCUPIED' : (prop.occupancy_status ?? 'unknown').toUpperCase();
                              return (
                                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase ${
                                  displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                                  displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                                  displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                                  'bg-slate-100 text-slate-600'
                                }`}>
                                  <span className={`w-1.5 h-1.5 rounded-full ${
                                    displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                                    displayStatus === 'VACANT' ? 'bg-slate-400' :
                                    displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                                  }`} />
                                  {displayStatus}
                                </span>
                              );
                            })()}
                          </div>
                          <p className="text-sm text-slate-600 mt-1 truncate">{address || '—'}</p>
                          <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                            <span>Region: <span className="text-slate-600 font-medium">{prop.region_code}</span></span>
                            {(prop.property_type_label || prop.property_type) && (
                              <span>Type: <span className="text-slate-600 font-medium">{prop.property_type_label || prop.property_type}</span></span>
                            )}
                            {!prop.is_multi_unit && prop.bedrooms && (
                              <span>Bedrooms: <span className="text-slate-600 font-medium">{prop.bedrooms}</span></span>
                            )}
                            {contextMode === 'personal' && isOccupied && activeStayForProp && (
                              <span>
                                Stay end reminders: <span className={activeStayForProp.dead_mans_switch_enabled ? 'text-amber-600 font-medium' : 'text-slate-600 font-medium'}>
                                  {activeStayForProp.dead_mans_switch_enabled ? 'On' : 'Off'}
                                </span>
                              </span>
                            )}
                          </div>
                          <span className="inline-block mt-2 text-xs font-medium text-blue-400">View details →</span>
                        </button>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <Button variant="outline" onClick={() => navigate(`property/${prop.id}`)} className="px-4">
                            View & Edit
                          </Button>
                          {contextMode === 'business' && (
                            <Button
                              variant="ghost"
                              onClick={() => { setDeleteConfirmProperty(prop); setDeleteError(null); }}
                              className="px-4 text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              Remove Property
                            </Button>
                          )}
                        </div>
                      </div>
                      {/* Occupancy status: VACANT | OCCUPIED | UNKNOWN | UNCONFIRMED */}
                      <div className="mt-6 pt-6 border-t border-slate-200 rounded-xl bg-slate-50/80 p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Occupancy status</p>
                        <div className="flex items-center gap-3 flex-wrap">
                          {(() => {
                            const displayStatus = isOccupied ? 'OCCUPIED' : (prop.occupancy_status ?? 'unknown').toUpperCase();
                            return (
                          <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium ${
                            displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                            displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                            displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                            'bg-slate-100 text-slate-600'
                          }`}>
                            <span className={`w-2 h-2 rounded-full ${
                              displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                              displayStatus === 'VACANT' ? 'bg-slate-400' :
                              displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                            }`} />
                            {displayStatus}
                          </span>
                            );
                          })()}
                          {contextMode === 'personal' && isOccupied && activeStayForProp && (
                            <span className="text-sm text-slate-600">
                              Current guest: <span className="font-medium text-slate-800">{activeStayForProp.guest_name}</span>
                              {' · '}
                              Lease end: <span className="font-medium text-slate-800">{activeStayForProp.stay_end_date}</span>
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Shield Mode: independent of vacant/occupied; owner can turn ON or OFF anytime. Auto ON: last day of stay, DMS run (48h after stay end). Auto OFF: when new guest accepts invitation. */}
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Shield Mode</p>
                        <div className="flex flex-wrap items-center gap-4">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              role="switch"
                              aria-checked={shieldOn}
                              disabled={shieldTogglePropertyId === prop.id}
                              title={shieldOn ? 'Turn Shield Mode off' : 'Turn Shield Mode on'}
                              onClick={async () => {
                                setShieldTogglePropertyId(prop.id);
                                try {
                                  await propertiesApi.update(prop.id, { shield_mode_enabled: !shieldOn });
                                  notify('success', shieldOn ? 'Shield Mode turned off.' : 'Shield Mode turned on.');
                                  loadData();
                                } catch (e) {
                                  notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                                } finally {
                                  setShieldTogglePropertyId(null);
                                }
                              }}
                              className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${shieldOn ? 'cursor-pointer bg-emerald-600' : 'cursor-pointer bg-slate-200 hover:bg-slate-300'} ${shieldTogglePropertyId === prop.id ? 'opacity-50' : ''}`}
                            >
                              <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform ${shieldOn ? 'translate-x-5' : 'translate-x-1'}`} />
                            </button>
                            <span className="text-sm font-medium text-slate-800">{shieldOn ? 'ON' : 'OFF'}</span>
                          </div>
                          {shieldOn && shieldStatus && (
                            <span className="text-sm text-slate-600">
                              Status: <span className="font-semibold text-slate-800">{shieldStatus}</span>
                            </span>
                          )}
                          {!shieldOn && (
                            <span className="text-xs text-slate-500">Turn on anytime. Also turns on automatically on the last day of a guest&apos;s stay and when stay end reminders run (48h after stay end).</span>
                          )}
                          <span className="text-xs text-slate-400">$10/month subscription</span>
                        </div>
                      </div>

                      {/* Property managers: visible in both personal and business; remove only in business */}
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Property managers</p>
                        {(propertyManagersMap[prop.id]?.length ?? 0) === 0 ? (
                          <p className="text-sm text-slate-500">No managers assigned. Invite from property details.</p>
                        ) : (
                          <ul className="space-y-2">
                            {(propertyManagersMap[prop.id] || []).map((m) => (
                              <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0">
                                <div>
                                  <p className="text-sm font-medium text-slate-800">{m.full_name || m.email}</p>
                                  <p className="text-xs text-slate-500">{m.email}</p>
                                  {m.has_resident_mode && m.resident_unit_label && (
                                    <>
                                      <p className="text-xs text-emerald-600 mt-0.5">On-site resident · Unit {m.resident_unit_label}</p>
                                      {m.presence_status && (
                                        <p className="text-xs text-slate-600 mt-0.5">
                                          {m.presence_status === 'present' ? (
                                            <span className="text-emerald-600">Present</span>
                                          ) : m.presence_away_started_at ? (
                                            <span className="text-slate-600">Away since {new Date(m.presence_away_started_at).toLocaleDateString()}</span>
                                          ) : (
                                            <span className="text-slate-600">Away</span>
                                          )}
                                        </p>
                                      )}
                                    </>
                                  )}
                                </div>
                                {contextMode === 'business' && (
                                  <div className="flex items-center gap-2">
                                    {m.has_resident_mode && (
                                      <Button
                                        variant="outline"
                                        onClick={async () => {
                                          setRemovingResidentMode({ propertyId: prop.id, userId: m.user_id });
                                          try {
                                            await propertiesApi.removeManagerResidentMode(prop.id, m.user_id);
                                            notify('success', 'Manager removed as on-site resident. They remain assigned; that unit is now vacant.');
                                            const next = await propertiesApi.listAssignedManagers(prop.id);
                                            setPropertyManagersMap((prev) => ({ ...prev, [prop.id]: next }));
                                          } catch (e) {
                                            notify('error', (e as Error)?.message ?? 'Failed.');
                                          } finally {
                                            setRemovingResidentMode(null);
                                          }
                                        }}
                                        disabled={(removingResidentMode?.propertyId === prop.id && removingResidentMode?.userId === m.user_id) || removingManager !== null}
                                      >
                                        {removingResidentMode?.propertyId === prop.id && removingResidentMode?.userId === m.user_id ? 'Removing…' : 'Remove as on-site resident'}
                                      </Button>
                                    )}
                                    <Button
                                      variant="ghost"
                                      onClick={async () => {
                                        setRemovingManager({ propertyId: prop.id, userId: m.user_id });
                                        try {
                                          await propertiesApi.removePropertyManager(prop.id, m.user_id);
                                          notify('success', 'Manager removed from property.');
                                          setPropertyManagersMap((prev) => ({
                                            ...prev,
                                            [prop.id]: (prev[prop.id] || []).filter((x) => x.user_id !== m.user_id),
                                          }));
                                        } catch (e) {
                                          notify('error', (e as Error)?.message ?? 'Failed to remove manager.');
                                        } finally {
                                          setRemovingManager(null);
                                        }
                                      }}
                                      disabled={(removingManager?.propertyId === prop.id && removingManager?.userId === m.user_id) || removingResidentMode !== null}
                                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                                    >
                                      {removingManager?.propertyId === prop.id && removingManager?.userId === m.user_id ? 'Removing…' : 'Remove'}
                                    </Button>
                                  </div>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </Card>
                  );
                })}
                </div>
              </div>
              )}

              {/* Inactive properties */}
              {inactiveProperties.length > 0 && (
              <div>
                <h3 className="text-lg font-bold text-slate-800 mb-4">Inactive properties</h3>
                <p className="text-slate-500 text-sm mb-4">Removed from dashboard; not shown when creating an invite. Data is kept for logs. You can reactivate any time.</p>
                <div className="grid gap-6">
                  {inactiveProperties.map((prop) => {
                    const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
                    const displayName = prop.name || address || `Property #${prop.id}`;
                    const displayStatus = (prop.occupancy_status ?? 'unknown').toUpperCase();
                    return (
                      <Card key={prop.id} className="p-6 border border-slate-200 bg-slate-50/50">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2 gap-y-1">
                              <h3 className="text-lg font-bold text-slate-700 truncate">{displayName}</h3>
                              <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase ${
                                displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                                displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                                displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                                'bg-slate-100 text-slate-600'
                              }`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${
                                  displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                                  displayStatus === 'VACANT' ? 'bg-slate-400' :
                                  displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                                }`} />
                                {displayStatus}
                              </span>
                            </div>
                            <p className="text-sm text-slate-600 mt-1 truncate">{address || '—'}</p>
                            <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                              <span>Region: <span className="text-slate-600 font-medium">{prop.region_code}</span></span>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-3 flex-shrink-0">
                            <Button variant="outline" onClick={() => navigate(`property/${prop.id}`)} className="px-4">
                              View
                            </Button>
                            <Button
                              variant="outline"
                              onClick={async () => {
                                try {
                                  await propertiesApi.reactivate(prop.id);
                                  notify('success', 'Property reactivated. It appears in Active properties and in the invite list again.');
                                  loadData();
                                } catch (e) {
                                  notify('error', (e as Error)?.message ?? 'Failed to reactivate.');
                                }
                              }}
                              className="px-4"
                            >
                              Reactivate
                            </Button>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              </div>
              )}
              </>
            )}
          </div>
        ) : activeTab === 'billing' ? (
          <div className="space-y-6">
            {paymentReturnMessage && (
              <div className={`flex items-center justify-between gap-4 p-4 rounded-xl text-sm ${paymentReturnIsError ? 'bg-red-50 border border-red-200 text-red-800' : 'bg-emerald-50 border border-emerald-200 text-emerald-800'}`}>
                <span>{paymentReturnMessage}</span>
                <button type="button" onClick={() => { setPaymentReturnMessage(null); setPaymentReturnIsError(false); }} className={paymentReturnIsError ? 'text-red-600 hover:text-red-800 font-medium shrink-0' : 'text-emerald-600 hover:text-emerald-800 font-medium shrink-0'} aria-label="Dismiss">Dismiss</button>
              </div>
            )}
            <Card className="p-6">
              <h3 className="text-lg font-bold text-slate-800 mb-2">Billing</h3>
              <p className="text-slate-500 text-sm mb-4">Invoices and payment history. Onboarding and subscription charges appear here. Billing activity is also recorded in Event ledger.</p>
              {billing && (billing.current_unit_count != null || billing.current_shield_count != null) && (
                <p className="text-slate-600 text-sm mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <strong>Current subscription:</strong> {billing.current_unit_count ?? 0} unit{(billing.current_unit_count ?? 0) !== 1 ? 's' : ''} (${(billing.current_unit_count ?? 0) * 1}/mo baseline)
                  {(billing.current_shield_count ?? 0) > 0 && (
                    <>, {(billing.current_shield_count ?? 0)} with Shield (${(billing.current_shield_count ?? 0) * 10}/mo)</>
                  )}
                  . Your monthly subscription is based on your current property count. The onboarding invoice in the table shows the unit count at the time it was created and does not change when you add more properties.
                </p>
              )}
              {billingLoading ? (
                <p className="text-slate-500">Loading billing…</p>
              ) : (
                <>
                  <div className="mb-6">
                    <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Invoices</h4>
                    {(() => {
                      const displayInvoices = (billing?.invoices ?? []).filter((inv: BillingInvoiceView) => inv.status !== 'draft');
                      return !billing || displayInvoices.length === 0 ? (
                      <p className="text-slate-500 text-sm">No invoices yet. Invoices are created when you add your first properties (onboarding fee) and for monthly subscription.</p>
                    ) : (
                      <div className="overflow-x-auto border border-slate-200 rounded-lg">
                        <table className="w-full text-left text-sm">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs tracking-wider">
                            <tr>
                              <th className="px-4 py-3">Date</th>
                              <th className="px-4 py-3">Number</th>
                              <th className="px-4 py-3">Description</th>
                              <th className="px-4 py-3">Amount</th>
                              <th className="px-4 py-3">Status</th>
                              <th className="px-4 py-3">Action</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-200">
                            {displayInvoices.map((inv: BillingInvoiceView) => (
                              <tr key={inv.id} className="hover:bg-slate-50">
                                <td className="px-4 py-3 text-slate-600">{new Date(inv.created).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</td>
                                <td className="px-4 py-3 font-mono text-slate-700">{inv.number ?? inv.id.slice(0, 12)}</td>
                                <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{inv.description ?? '—'}</td>
                                <td className="px-4 py-3">${(inv.amount_due_cents / 100).toFixed(2)} {inv.currency.toUpperCase()}</td>
                                <td className="px-4 py-3">
                                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                                    inv.status === 'paid' ? 'bg-emerald-100 text-emerald-800' :
                                    inv.status === 'open' ? 'bg-amber-100 text-amber-800' :
                                    inv.status === 'past_due' ? 'bg-red-100 text-red-800' :
                                    inv.status === 'void' ? 'bg-slate-200 text-slate-600' :
                                    'bg-slate-100 text-slate-700'
                                  }`}>{inv.status === 'past_due' ? 'Payment failed' : inv.status}</span>
                                  {inv.status === 'past_due' && (
                                    <p className="text-xs text-red-600 mt-1">Update your payment method and try again.</p>
                                  )}
                                </td>
                                <td className="px-4 py-3">
                                  {inv.status === 'void' ? (
                                    <button
                                      type="button"
                                      onClick={() => setShowVoidInvoiceDialog(true)}
                                      className="text-blue-600 hover:underline"
                                    >
                                      Pay invoice
                                    </button>
                                  ) : inv.status !== 'paid' ? (
                                    inv.hosted_invoice_url ? (
                                      <a href={inv.hosted_invoice_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">Pay invoice</a>
                                    ) : (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          dashboardApi.billingPortalSession()
                                            .then((data) => { window.location.href = data.url; })
                                            .catch(() => notify('error', 'Could not open payment page. Try again.'));
                                        }}
                                        className="text-blue-600 hover:underline disabled:opacity-50"
                                      >
                                        Pay invoice
                                      </button>
                                    )
                                  ) : inv.hosted_invoice_url ? (
                                    <a href={inv.hosted_invoice_url} target="_blank" rel="noopener noreferrer" className="text-slate-500 hover:underline">View</a>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    );
                    })()}
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Payments</h4>
                    {!billing || billing.payments.length === 0 ? (
                      <p className="text-slate-500 text-sm">No payments yet.</p>
                    ) : (
                      <div className="overflow-x-auto border border-slate-200 rounded-lg">
                        <table className="w-full text-left text-sm">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs tracking-wider">
                            <tr>
                              <th className="px-4 py-3">Paid at</th>
                              <th className="px-4 py-3">Description</th>
                              <th className="px-4 py-3">Amount</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-200">
                            {billing.payments.map((pay: BillingPaymentView) => (
                              <tr key={pay.invoice_id} className="hover:bg-slate-50">
                                <td className="px-4 py-3 text-slate-600">{new Date(pay.paid_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                                <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{pay.description ?? 'Payment'}</td>
                                <td className="px-4 py-3 font-medium">${(pay.amount_cents / 100).toFixed(2)} {pay.currency.toUpperCase()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              )}
            </Card>
          </div>
        ) : activeTab === 'logs' ? (
          <div className="space-y-6">
            <Card className="p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">From (UTC)</label>
                  <input
                    type="datetime-local"
                    value={logsFromTs}
                    onChange={(e) => setLogsFromTs(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">To (UTC)</label>
                  <input
                    type="datetime-local"
                    value={logsToTs}
                    onChange={(e) => setLogsToTs(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Category</label>
                  <select
                    value={logsCategory}
                    onChange={(e) => setLogsCategory(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">All</option>
                    <option value="status_change">Status change</option>
                    <option value="shield_mode">Shield Mode</option>
                    <option value="dead_mans_switch">Stay end reminders</option>
                    <option value="guest_signature">Guest signature</option>
                    <option value="failed_attempt">Failed attempt</option>
                    <option value="billing">Billing</option>
                    <option value="presence">Presence / Away</option>
                    <option value="tenant_assignment">Tenant assignment</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Search (title/message)</label>
                  <input
                    type="text"
                    placeholder="Search…"
                    value={logsSearch}
                    onChange={(e) => setLogsSearch(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <Button variant="primary" onClick={loadLogs} disabled={logsLoading} className="mb-4">
                {logsLoading ? 'Loading…' : 'Apply filters'}
              </Button>
            </Card>
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-slate-50">
                <h3 className="text-lg font-bold text-slate-800">Event ledger (append-only)</h3>
                <p className="text-slate-500 text-sm mt-1">Status changes, Shield Mode and stay end reminders on/off, guest signatures, payment and billing activity (invoices created, paid), and failed attempts are recorded. Use the category filter to view Shield Mode, stay end reminders, or Billing events. Records cannot be edited or deleted.</p>
              </div>
              <div className="overflow-x-auto">
                {logsLoading && logs.length === 0 ? (
                  <p className="p-8 text-slate-500 text-center">Loading logs…</p>
                ) : logs.length === 0 ? (
                  <p className="p-8 text-slate-500 text-center">No logs match your filters. Adjust filters and click Apply, or ensure you have property-related activity.</p>
                ) : (
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Time (UTC)</th>
                        <th className="px-6 py-4">Category</th>
                        <th className="px-6 py-4">Title</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Actor</th>
                        <th className="px-6 py-4">Message</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {logs.map((entry) => (
                        <tr key={entry.id} className="hover:bg-slate-50">
                          <td className="px-6 py-3 text-slate-600 text-sm whitespace-nowrap">
                            {entry.created_at ? new Date(entry.created_at).toISOString().replace('T', ' ').slice(0, 19) + 'Z' : '—'}
                          </td>
                          <td className="px-6 py-3">
                            <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                              entry.category === 'failed_attempt' ? 'bg-red-100 text-red-800' :
                              entry.category === 'guest_signature' ? 'bg-emerald-100 text-emerald-800' :
                              entry.category === 'shield_mode' ? 'bg-violet-100 text-violet-800' :
                              entry.category === 'dead_mans_switch' ? 'bg-amber-100 text-amber-800' :
                              entry.category === 'billing' ? 'bg-slate-200 text-slate-800' :
                              'bg-sky-100 text-sky-800'
                            }`}>
                              {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? 'Stay end reminders' : entry.category === 'billing' ? 'Billing' : entry.category.replace('_', ' ')}
                            </span>
                          </td>
                          <td className="px-6 py-3 font-medium text-slate-800">{entry.title}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm">{entry.property_name ?? '—'}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm">{entry.actor_email ?? '—'}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm max-w-xs">
                            <span className="truncate block">{entry.message}</span>
                            <button
                              type="button"
                              onClick={() => setLogMessageModalEntry(entry)}
                              className="text-sky-600 hover:text-sky-800 text-xs mt-0.5 focus:outline-none focus:underline"
                            >
                              View full message
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Card>
          </div>
        ) : activeTab === 'settings' ? (
          <div className="w-full">
            <Settings
              user={user}
              navigate={navigate}
              embedded
              onOpenBilling={() => setActiveTab('billing')}
              contextMode={contextMode}
              personalModeUnits={personalModeUnits}
              onContextModeChange={handleContextModeChange}
            />
          </div>
        ) : activeTab === 'help' ? (
          <div className="w-full">
            <HelpCenter navigate={navigate} embedded />
          </div>
        ) : (
          <>
            {contextMode === 'personal' ? (
              <>
                {/* Status Alert for Overstays (personal mode only) */}
                {firstOverstay && (
                  <div className="mb-8 p-6 rounded-2xl bg-red-50 border border-red-200 flex flex-col md:flex-row items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center text-red-600">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                      </div>
                      <div>
                        <h3 className="text-lg font-bold text-slate-800">Overstay Detected</h3>
                        <p className="text-red-700 text-sm">{firstOverstay.guest_name} has exceeded their authorized stay period in {firstOverstay.region_code}.</p>
                      </div>
                    </div>
                    <Button variant="danger" onClick={() => handleInitiateRemoval(firstOverstay)} className="whitespace-nowrap">Initiate Removal</Button>
                  </div>
                )}

                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-10">
                  <Card className="p-6 border-l-4 border-blue-500 hover:scale-[1.02] transition-transform cursor-pointer" onClick={() => setActiveTab('properties')}>
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Properties</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-green-500 hover:scale-[1.02] transition-transform cursor-pointer">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Guests</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{activeCount}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-red-500 hover:scale-[1.02] transition-transform cursor-pointer">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Overstays</p>
                    <p className="text-4xl font-extrabold text-red-600 mt-1">{overstays.length}</p>
                  </Card>
                </div>

                <Card className="mb-10 overflow-hidden">
                  <div className="p-6 border-b border-slate-200 flex justify-between items-center bg-white/60 backdrop-blur-md">
                    <h3 className="text-xl font-bold text-slate-800">Guests</h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                        <tr>
                          <th className="px-6 py-4">Guest Name</th>
                          <th className="px-6 py-4">Property</th>
                          <th className="px-6 py-4">Days Left</th>
                          <th className="px-6 py-4">Status</th>
                          <th className="px-6 py-4 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {activeStays.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="px-6 py-12 text-center text-slate-500">No active stays. Invite a guest to get started.</td>
                          </tr>
                        ) : (
                          activeStays.map((stay) => {
                        const overstay = isOverstayed(stay.stay_end_date);
                        const dLeft = daysLeft(stay.stay_end_date);
                        const revoked = !!stay.revoked_at;
                        return (
                          <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors group">
                            <td className="px-6 py-5">
                              <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs">{stay.guest_name.charAt(0)}</div>
                                <span className="text-sm font-bold text-slate-800">{stay.guest_name}</span>
                              </div>
                            </td>
                            <td className="px-6 py-5 text-sm text-slate-600">{stay.property_name}</td>
                            <td className="px-6 py-5">
                              <span className={`text-sm font-bold ${revoked ? 'text-amber-600' : overstay ? 'text-red-600' : 'text-green-600'}`}>{revoked ? '—' : overstay ? 'EXPIRED' : `${dLeft}d`}</span>
                            </td>
                            <td className="px-6 py-5">
                              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
                                revoked ? 'bg-amber-50 text-amber-700 border border-amber-500/20' : overstay ? 'bg-red-50 text-red-600 border border-red-500/20' : 'bg-green-50 text-green-700 border border-green-200'
                              }`}>
                                {revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active'}
                              </span>
                            </td>
                            <td className="px-6 py-5 text-right space-x-3">
                              {revoked ? (
                                <span className="text-xs text-slate-500">Revoked</span>
                              ) : overstay ? (
                                <Button variant="danger" onClick={() => handleInitiateRemoval(stay)} className="text-xs py-2">Remove</Button>
                              ) : (
                                <Button variant="ghost" onClick={() => handleRevokeClick(stay)} className="text-xs py-2 text-red-600 hover:text-red-700">Revoke</Button>
                              )}
                              <Button variant="outline" className="text-xs py-2">Details</Button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
              </>
            ) : (
              /* Business mode: property/unit status only, no guest data */
              <div className="space-y-8">
                <p className="text-slate-500 text-sm">Property and unit status. Switch to Personal mode to view guest invitations, stays, and overstays.</p>
                <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-6">
                  <Card className="p-6 border-l-4 border-blue-500 hover:scale-[1.02] transition-transform cursor-pointer" onClick={() => setActiveTab('properties')}>
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Properties</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-emerald-500">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Occupied</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'occupied').length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-sky-500">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Vacant</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'vacant').length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-slate-400">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Unknown</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())).length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-amber-500">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Shield On</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => p.shield_mode_enabled).length}</p>
                  </Card>
                </div>
                <Card className="p-6">
                  <h3 className="text-lg font-bold text-slate-800 mb-4">Property status overview</h3>
                  <p className="text-slate-600 text-sm">View properties and unit-level occupancy in the Properties tab. Business mode does not display guest names, invitations, or stay details.</p>
                  <Button variant="outline" onClick={() => setActiveTab('properties')} className="mt-4">View Properties</Button>
                </Card>
              </div>
            )}
          </>
        )}
      </main>

      {/* Bulk upload rules modal (opened by info icon) */}
      <Modal
        open={showBulkUploadRulesModal}
        title="Bulk upload rules"
        onClose={() => setShowBulkUploadRulesModal(false)}
        className="max-w-lg"
      >
        <div className="px-6 py-4 space-y-3 text-slate-600 text-sm">
          <p><strong>Required:</strong> <code className="bg-slate-100 px-1 rounded">Address</code>, <code className="bg-slate-100 px-1 rounded">City</code>, <code className="bg-slate-100 px-1 rounded">State</code>, <code className="bg-slate-100 px-1 rounded">Zip</code>, <code className="bg-slate-100 px-1 rounded">Occupied</code> (YES/NO). If Occupied=YES: <code className="bg-slate-100 px-1 rounded">Tenant Name</code>, <code className="bg-slate-100 px-1 rounded">Lease Start</code>, <code className="bg-slate-100 px-1 rounded">Lease End</code>.</p>
          <p><strong>Property details (optional):</strong> <code className="bg-slate-100 px-1 rounded">property_name</code>, <code className="bg-slate-100 px-1 rounded">property_type</code> (house, apartment, condo, townhouse, duplex, triplex, quadplex), <code className="bg-slate-100 px-1 rounded">bedrooms</code> (for house/condo), <code className="bg-slate-100 px-1 rounded">units</code> (for apartment/duplex/triplex/quadplex), <code className="bg-slate-100 px-1 rounded">primary_residence_unit</code> (unit number 1, 2, … if owner lives there), <code className="bg-slate-100 px-1 rounded">occupied_unit</code> (which unit is occupied, for multi-unit with Occupied=YES), <code className="bg-slate-100 px-1 rounded">Unit No</code>, <code className="bg-slate-100 px-1 rounded">Shield Mode</code>, <code className="bg-slate-100 px-1 rounded">is_primary_residence</code>, <code className="bg-slate-100 px-1 rounded">tax_id</code>, <code className="bg-slate-100 px-1 rounded">apn</code>.</p>
          <p>Existing properties (same street, city, state) are updated only when values change. Empty optional cells keep existing values.</p>
          <p>If the upload fails partway, rows before the failure are saved.</p>
        </div>
      </Modal>

      {/* Bulk upload modal */}
      <Modal
        open={showBulkUploadModal}
        title="Upload properties in bulk"
        onClose={() => !bulkUploading && setShowBulkUploadModal(false)}
        className="max-w-lg"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            Use a CSV with: <strong>Required:</strong> <code className="bg-slate-100 px-1 rounded">Address</code>, <code className="bg-slate-100 px-1 rounded">City</code>, <code className="bg-slate-100 px-1 rounded">State</code>, <code className="bg-slate-100 px-1 rounded">Zip</code>, <code className="bg-slate-100 px-1 rounded">Occupied</code> (YES/NO). <strong>If Occupied=YES:</strong> <code className="bg-slate-100 px-1 rounded">Tenant Name</code>, <code className="bg-slate-100 px-1 rounded">Lease Start</code>, <code className="bg-slate-100 px-1 rounded">Lease End</code>. <strong>Optional:</strong> <code className="bg-slate-100 px-1 rounded">Unit No</code>, <code className="bg-slate-100 px-1 rounded">Shield Mode</code> (YES/NO, default NO), <code className="bg-slate-100 px-1 rounded">Tax ID</code>, <code className="bg-slate-100 px-1 rounded">APN</code>.
          </p>
          <p className="text-xs text-slate-500">
            Occupied=YES: property token is active, tenant is recorded, an invite link is created (Active) with stay end reminders from lease end. Occupied=NO: token stays Pending, status VACANT. Shield Mode is independent of Occupied—you can turn it on or off anytime in the dashboard; Shield Mode YES in CSV or when on adds $10/month. Existing properties (same address, city, state) are updated when values change.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => {
                const header = 'Address,Unit No,City,State,Zip,Occupied,Tenant Name,Lease Start,Lease End,Property Name,Property Type,Units,Bedrooms,Primary Residence Unit,Occupied Unit,Shield Mode,Tax ID,APN';
                const exampleOccupied = '123 Ocean Ave,,Miami,FL,33139,YES,Jane Doe,2025-01-01,2025-12-31,Miami Beach Condo,house,,3,,,NO,,';
                const exampleVacant = '456 Oak St,,Austin,TX,78701,NO,,,Astro Apartments,apartment,12,,1,,NO,,';
                const blob = new Blob([header + '\n' + exampleOccupied + '\n' + exampleVacant], { type: 'text/csv' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'properties_template.csv';
                a.click();
                URL.revokeObjectURL(a.href);
              }}
            >
              Download CSV template
            </Button>
            <Button
              variant="primary"
              disabled={bulkUploading}
              onClick={() => bulkUploadFileInputRef.current?.click()}
            >
              Choose CSV file
            </Button>
            <input
              ref={bulkUploadFileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (!file) return;
                setShowBulkUploadModal(false);
                setBulkUploading(true);
                try {
                  const result = await propertiesApi.bulkUpload(file);
                  setBulkUploadResult(result);
                  loadData();
                } catch (err) {
                  notify('error', (err as Error)?.message ?? 'Bulk upload failed.');
                } finally {
                  setBulkUploading(false);
                }
              }}
            />
          </div>
        </div>
      </Modal>

      {/* Bulk upload result modal */}
      <Modal
        open={bulkUploadResult !== null}
        title={bulkUploadResult?.failed_from_row == null ? 'Bulk upload complete' : 'Bulk upload partially completed'}
        onClose={() => setBulkUploadResult(null)}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          {bulkUploadResult != null && (
            bulkUploadResult.failed_from_row == null ? (
              <p className="text-slate-600 text-sm">
                <strong>{bulkUploadResult.created}</strong> propert{bulkUploadResult.created === 1 ? 'y' : 'ies'} created, <strong>{bulkUploadResult.updated}</strong> updated.
              </p>
            ) : (
              <p className="text-slate-600 text-sm">
                Properties until row <strong>{bulkUploadResult.failed_from_row - 1}</strong> were uploaded successfully (<strong>{bulkUploadResult.created}</strong> created, <strong>{bulkUploadResult.updated}</strong> updated). The rest failed from row <strong>{bulkUploadResult.failed_from_row}</strong>: {bulkUploadResult.failure_reason ?? 'Unknown error.'}
              </p>
            )
          )}
          <Button onClick={() => setBulkUploadResult(null)}>Done</Button>
        </div>
      </Modal>

      {/* Void invoice: cannot be paid; direct user to contact support */}
      <Modal
        open={showVoidInvoiceDialog}
        title="This invoice cannot be paid"
        onClose={() => setShowVoidInvoiceDialog(false)}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            This invoice is void and cannot be paid. Please contact support.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="primary"
              onClick={() => {
                setShowVoidInvoiceDialog(false);
                navigate('help');
              }}
            >
              Contact support
            </Button>
            <Button variant="outline" onClick={() => setShowVoidInvoiceDialog(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* Loading overlay while bulk upload is processing */}
      {bulkUploading && <LoadingOverlay message="Uploading properties…" />}

      {/* Remove property (soft-delete) confirmation modal */}
      {deleteConfirmProperty && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => { setDeleteConfirmProperty(null); setDeleteError(null); }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6 border-b border-slate-200">
                <h3 className="text-lg font-bold text-slate-800">Remove Property</h3>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-slate-600 text-sm">
                  Remove <span className="font-bold text-slate-800">{deleteConfirmProperty.name || [deleteConfirmProperty.street, deleteConfirmProperty.city].filter(Boolean).join(', ')}</span> from your dashboard? This is only allowed when there is no active guest stay. The property will move to <strong>Inactive properties</strong> and will not appear when creating an invite. Data is kept for logs. You can reactivate it anytime.
                </p>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => { setDeleteConfirmProperty(null); setDeleteError(null); }} className="flex-1">Cancel</Button>
                  <Button
                    variant="danger"
                    className="flex-1"
                    onClick={async () => {
                      try {
                        await propertiesApi.delete(deleteConfirmProperty.id);
                        setDeleteConfirmProperty(null);
                        setDeleteError(null);
                        notify('success', 'Property removed from dashboard. It has been moved to Inactive properties.');
                        loadData();
                      } catch (e) {
                        const msg = (e as Error)?.message ?? 'Failed to remove property.';
                        setDeleteError(msg);
                        notify('error', msg);
                      }
                    }}
                  >
                    Remove Property
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Revoke confirmation modal */}
      {revokeConfirmStay && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setRevokeConfirmStay(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6 border-b border-slate-200">
                <h3 className="text-lg font-bold text-slate-800">Revoke stay authorization</h3>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-slate-600 text-sm">
                  Revoking <span className="font-bold text-slate-800">{revokeConfirmStay.guest_name}</span> will trigger a 12-hour vacate notice. Proceed?
                </p>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => setRevokeConfirmStay(null)} className="flex-1" disabled={revokeLoading}>Cancel</Button>
                  <Button variant="danger" onClick={handleRevokeConfirm} className="flex-1" disabled={revokeLoading}>{revokeLoading ? 'Revoking…' : 'Proceed'}</Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Revoke success modal */}
      {revokeSuccessGuest && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setRevokeSuccessGuest(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6">
                <p className="text-green-600 font-medium mb-4">Revocation successful. Audit trail updated.</p>
                <Button onClick={() => setRevokeSuccessGuest(null)}>Done</Button>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Initiate Removal modal */}
      {packetModalStay && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => !removalLoading && setPacketModalStay(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-lg">
              <div className="p-6 border-b border-slate-200 flex items-center justify-between">
                <h3 className="text-lg font-bold text-red-700">Initiate Removal</h3>
                <button onClick={() => !removalLoading && setPacketModalStay(null)} className="text-slate-600 hover:text-slate-800" disabled={removalLoading}>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-sm text-slate-600">
                  You are about to initiate formal removal for <span className="font-bold text-slate-800">{packetModalStay.guest_name}</span> who is in overstay.
                </p>
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-2">
                  <p className="text-sm font-bold text-red-800">This action will:</p>
                  <ul className="text-sm text-red-700 list-disc list-inside space-y-1">
                    <li>Revoke the guest's stay authorization (access disabled)</li>
                    <li>Send removal notice email to the guest</li>
                    <li>Send confirmation email to you</li>
                    <li>Log all actions in the audit trail</li>
                  </ul>
                </div>
                <div className="text-sm">
                  <p className="text-slate-500 mb-1">Property</p>
                  <p className="text-slate-800">{packetModalStay.property_name}</p>
                </div>
                <div className="text-sm">
                  <p className="text-slate-500 mb-1">Jurisdiction</p>
                  <p className="text-slate-800 font-mono">{packetModalStay.region_code}</p>
                </div>
                <div className="flex gap-3 pt-2">
                  <Button variant="danger" onClick={handleRemovalConfirm} disabled={removalLoading} className="flex-1">
                    {removalLoading ? 'Processing...' : 'Confirm Removal'}
                  </Button>
                  <Button variant="outline" onClick={() => setPacketModalStay(null)} disabled={removalLoading}>
                    Cancel
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Full log message modal */}
      {logMessageModalEntry && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setLogMessageModalEntry(null)} aria-hidden="true" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="log-message-title">
            <Card className="w-full max-w-lg max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                <h3 id="log-message-title" className="text-lg font-bold text-slate-800">
                  Full message — {logMessageModalEntry.title}
                </h3>
                <button
                  type="button"
                  onClick={() => setLogMessageModalEntry(null)}
                  className="text-slate-500 hover:text-slate-700 p-1 rounded focus:outline-none focus:ring-2 focus:ring-sky-500"
                  aria-label="Close"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="p-4 overflow-y-auto flex-1">
                <p className="text-slate-700 text-sm whitespace-pre-wrap break-words">{logMessageModalEntry.message}</p>
              </div>
              <div className="p-4 border-t border-slate-200">
                <Button variant="outline" onClick={() => setLogMessageModalEntry(null)}>Close</Button>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Verify with QR code modal – opens #check with token pre-filled */}
      {showVerifyQRModal && verifyQRInviteId && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => { setShowVerifyQRModal(false); setVerifyQRInviteId(null); setVerifyQRCopyToast(null); }} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Verify with QR code</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan to open the Verify page with this invite&apos;s token pre-filled.</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`)}`}
                  alt="QR code for verify page"
                  className="w-40 h-40 rounded-lg"
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="primary"
                className="w-full"
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`, '_blank', 'noopener,noreferrer')}
              >
                Open verify page
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={async () => {
                  const url = `${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`;
                  const ok = await copyToClipboard(url);
                  setVerifyQRCopyToast(ok ? 'Verify link copied.' : 'Could not copy.');
                  setTimeout(() => setVerifyQRCopyToast(null), 3000);
                }}
              >
                Copy verify link
              </Button>
            </div>
            {verifyQRCopyToast && (
              <p className={`text-sm text-center mt-2 ${verifyQRCopyToast.startsWith('Verify link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                {verifyQRCopyToast}
              </p>
            )}
          </div>
        </div>
      )}

      <InviteRoleChoiceModal
        open={showInviteRoleChoice}
        onClose={() => setShowInviteRoleChoice(false)}
        onSelectTenant={() => setShowInviteTenantModal(true)}
        onSelectGuest={() => setShowInviteModal(true)}
      />

      <InviteTenantModal
        open={showInviteTenantModal}
        onClose={() => setShowInviteTenantModal(false)}
        properties={properties.map((p) => ({ id: p.id, name: p.name, street: p.street, address: p.address }))}
        getUnits={(propertyId) => propertiesApi.getUnits(propertyId).then((u) => u.filter((x) => x.id >= 0))}
        createInvitation={async (params) => {
          const unitId = params.unitId ?? 0;
          return unitId > 0
            ? propertiesApi.inviteTenant(unitId, { tenant_name: params.tenant_name, tenant_email: params.tenant_email, lease_start_date: params.lease_start_date, lease_end_date: params.lease_end_date })
            : propertiesApi.inviteTenantForProperty(params.propertyId, { tenant_name: params.tenant_name, tenant_email: params.tenant_email, lease_start_date: params.lease_start_date, lease_end_date: params.lease_end_date });
        }}
        notify={notify}
        onSuccess={loadData}
      />

      <InviteGuestModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        user={user}
        setLoading={setLoadingWrapper}
        notify={notify}
        onSuccess={loadData}
        navigate={navigate}
      />
    </div>
  );
};

export default OwnerDashboard;
