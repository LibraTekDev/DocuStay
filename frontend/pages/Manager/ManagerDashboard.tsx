import React, { useState, useEffect, useCallback } from 'react';
import { flushSync } from 'react-dom';
import { Card, Button, Modal, Input } from '../../components/UI';
import { InviteRoleChoiceModal } from '../../components/InviteRoleChoiceModal';
import { UserSession } from '../../types';
import { dashboardApi, invitationsApi, getContextMode, setContextMode, APP_ORIGIN } from '../../services/api';
import { getTodayLocal } from '../../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../../utils/invitationErrors';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';

interface PropertySummary {
  id: number;
  name: string | null;
  address: string;
  occupancy_status: string;
  unit_count: number;
  occupied_count: number;
}

interface UnitSummary {
  id: number;
  unit_label: string;
  occupancy_status: string;
}

const ManagerDashboard: React.FC<{
  user: UserSession;
  navigate: (v: string) => void;
  setLoading?: (l: boolean) => void;
  notify?: (t: 'success' | 'error', m: string) => void;
}> = ({ user, navigate, setLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {} }) => {
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [loading, setLoadingState] = useState(true);
  const [expandedPropertyId, setExpandedPropertyId] = useState<number | null>(null);
  const [units, setUnits] = useState<UnitSummary[]>([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  type ManagerTab = 'properties' | 'guests' | 'invitations' | 'logs' | 'billing' | 'settings' | 'help';
  const [activeTab, setActiveTab] = useState<ManagerTab>('properties');
  const [stays, setStays] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [billing, setBilling] = useState<any>(null);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  const [inviteRoleChoiceUnit, setInviteRoleChoiceUnit] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [inviteTenantModal, setInviteTenantModal] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [inviteTenantForm, setInviteTenantForm] = useState({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
  const [inviteTenantSubmitting, setInviteTenantSubmitting] = useState(false);
  const [inviteGuestOpen, setInviteGuestOpen] = useState(false);
  const [inviteGuestForm, setInviteGuestForm] = useState({ unit_id: 0, guest_name: '', checkin_date: '', checkout_date: '' });
  const [inviteGuestSubmitting, setInviteGuestSubmitting] = useState(false);
  const [inviteGuestLink, setInviteGuestLink] = useState('');
  const [inviteTenantLink, setInviteTenantLink] = useState('');

  const setLoadingWrapper = (x: boolean) => {
    setLoadingState(x);
    setLoading(x);
  };

  useEffect(() => {
    const load = async () => {
      setLoadingWrapper(true);
      try {
        const [propsData, pmUnits, staysData] = await Promise.all([
          dashboardApi.managerProperties(),
          dashboardApi.managerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
          dashboardApi.managerStays().catch(() => []),
        ]);
        setProperties(propsData || []);
        setPersonalModeUnits((pmUnits as { unit_ids: number[] }).unit_ids || []);
        setStays(staysData || []);
      } catch (e) {
        notify('error', (e as Error)?.message || 'Failed to load properties');
      } finally {
        setLoadingWrapper(false);
      }
    };
    load();
  }, []);

  useEffect(() => {
    if (activeTab === 'guests' || activeTab === 'invitations') dashboardApi.managerStays().then(setStays).catch(() => setStays([]));
  }, [activeTab]);
  useEffect(() => {
    if (contextMode === 'personal' && (activeTab === 'billing' || activeTab === 'logs')) setActiveTab('properties');
  }, [contextMode, activeTab]);
  useEffect(() => {
    if (activeTab === 'logs') dashboardApi.managerLogs().then(setLogs).catch(() => setLogs([]));
  }, [activeTab]);
  useEffect(() => {
    if (activeTab === 'billing') dashboardApi.managerBilling().then(setBilling).catch(() => setBilling(null));
  }, [activeTab]);

  const handleContextModeChange = useCallback((mode: 'business' | 'personal') => {
    setContextMode(mode);
    flushSync(() => {
      setContextModeState(mode);
      if (mode === 'personal' && (activeTab === 'billing' || activeTab === 'logs')) setActiveTab('properties');
    });
  }, [activeTab]);

  const handleInviteGuest = async () => {
    if (!inviteGuestForm.unit_id || !inviteGuestForm.guest_name || !inviteGuestForm.checkin_date || !inviteGuestForm.checkout_date) {
      notify('error', 'Please fill all fields');
      return;
    }
    if (inviteGuestForm.checkin_date < getTodayLocal()) {
      notify('error', 'Check-in date cannot be in the past.');
      return;
    }
    setInviteGuestSubmitting(true);
    try {
      const res = await invitationsApi.create({
        unit_id: inviteGuestForm.unit_id,
        guest_name: inviteGuestForm.guest_name,
        checkin_date: inviteGuestForm.checkin_date,
        checkout_date: inviteGuestForm.checkout_date,
      });
      if (res.status !== 'success' || !res.data?.invitation_code) {
        notify('error', res.message ?? 'We couldn\'t create a valid invitation link. Please try again.');
        return;
      }
      const code = res.data.invitation_code;
      const base = APP_ORIGIN || (typeof window !== 'undefined' ? window.location.origin : '');
      setInviteGuestLink(`${base}${typeof window !== 'undefined' ? window.location.pathname : ''}#invite/${code}`);
      notify('success', 'Invitation created.');
    } catch (err) {
      notify('error', toUserFriendlyInvitationError((err as Error)?.message ?? 'Failed to create invitation'));
    } finally {
      setInviteGuestSubmitting(false);
    }
  };

  const handleInviteTenant = async () => {
    if (!inviteTenantModal) return;
    const { tenant_name, tenant_email, lease_start_date, lease_end_date } = inviteTenantForm;
    if (!tenant_name.trim()) { notify('error', 'Tenant name is required'); return; }
    if (!lease_start_date || !lease_end_date) { notify('error', 'Lease dates are required'); return; }
    if (lease_start_date < getTodayLocal()) { notify('error', 'Lease start date cannot be in the past.'); return; }
    setInviteTenantSubmitting(true);
    try {
      const res = await dashboardApi.managerInviteTenant(inviteTenantModal.unitId, {
        tenant_name: tenant_name.trim(),
        tenant_email: tenant_email.trim(),
        lease_start_date,
        lease_end_date,
      });
      const base = typeof window !== 'undefined' ? window.location.origin : '';
      const link = `${base}${window.location.pathname}#invite/${res.invitation_code}`;
      setInviteTenantLink(link);
      notify('success', 'Tenant invitation created. Share the invite link with the tenant.');
      setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to create invitation');
    } finally {
      setInviteTenantSubmitting(false);
    }
  };

  const loadUnits = async (propertyId: number) => {
    if (expandedPropertyId === propertyId) {
      setExpandedPropertyId(null);
      return;
    }
    setUnitsLoading(true);
    try {
      const data = await dashboardApi.managerUnits(propertyId);
      setUnits(data || []);
      setExpandedPropertyId(propertyId);
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to load units');
    } finally {
      setUnitsLoading(false);
    }
  };

  const statusBadge = (status: string) => {
    const s = (status || '').toLowerCase();
    const cls =
      s === 'occupied' ? 'bg-emerald-100 text-emerald-700'
      : s === 'vacant' ? 'bg-sky-100 text-sky-700'
      : s === 'unconfirmed' ? 'bg-amber-100 text-amber-700'
      : 'bg-slate-100 text-slate-600';
    return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{status}</span>;
  };

  const activeStays = stays.filter((s: any) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);

  const sidebarNavBase: { id: ManagerTab; label: string; icon: string }[] = [
    { id: 'properties', label: 'Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
    { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
    ...(contextMode !== 'personal' ? [{ id: 'logs' as ManagerTab, label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' }] : []),
    ...(contextMode !== 'personal' ? [{ id: 'billing' as ManagerTab, label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' }] : []),
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];
  const sidebarNav = sidebarNavBase;

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar – same layout as Owner dashboard */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {sidebarNav.map((item) => (
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
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <ModeSwitcher
            contextMode={contextMode}
            personalModeUnits={personalModeUnits}
            onContextModeChange={handleContextModeChange}
            canUsePersonal={personalModeUnits.length > 0 || properties.length > 0}
          />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* Mobile tab nav when sidebar is hidden */}
        <div className="lg:hidden mb-6">
          <label htmlFor="manager-mobile-tab" className="sr-only">Navigate to</label>
          <select
            id="manager-mobile-tab"
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value as ManagerTab)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            {sidebarNav.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

        {activeTab === 'settings' ? (
          <div className="w-full">
            <Settings user={user} navigate={navigate} embedded />
          </div>
        ) : activeTab === 'help' ? (
          <div className="w-full">
            <HelpCenter navigate={navigate} embedded />
          </div>
        ) : (
          <>
            <header className="flex flex-col sm:flex-row justify-between items-start gap-4 mb-8">
              <div>
                <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">
                  {activeTab === 'properties' ? 'Properties' : activeTab === 'guests' ? 'Guests' : activeTab === 'invitations' ? 'Invitations' : activeTab === 'logs' ? 'Event ledger' : 'Billing'}
                </h1>
                <p className="text-slate-600 mt-1">
                  {activeTab === 'properties' ? 'Properties assigned to you.' : activeTab === 'guests' ? 'Guests currently staying at managed properties and their stay details.' : activeTab === 'invitations' ? 'Pending invitations for properties you manage.' : activeTab === 'logs' ? 'Event ledger for managed properties.' : 'Billing visibility for the properties you manage.'}
                </p>
              </div>
            </header>

      {activeTab === 'guests' && (
        <Card className="p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Guests</h2>
          <p className="text-slate-500 text-sm mb-4">Guests who accepted and their current or past stay at properties you manage.</p>
          {stays.filter((s: any) => !s.invitation_only).length === 0 ? (
            <p className="text-slate-500 text-sm">No stays yet. When guests accept an invitation, they appear here.</p>
          ) : (
            <ul className="space-y-2">
              {stays.filter((s: any) => !s.invitation_only).map((s: any) => (
                <li key={s.stay_id} className="flex justify-between items-center py-2 border-b border-slate-100 last:border-0">
                  <span className="text-sm">{s.guest_name} · {s.property_name} · {s.stay_start_date} – {s.stay_end_date}</span>
                  {s.checked_in_at && !s.checked_out_at && !s.cancelled_at && <span className="text-xs font-medium text-emerald-700">Active</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {activeTab === 'invitations' && (
        <Card className="p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Invitations</h2>
          <p className="text-slate-500 text-sm mb-4">Pending invitations for properties you manage. Invitations expire if not accepted within the configured window.</p>
          {stays.filter((s: any) => s.invitation_only || (s.token_state || '').toUpperCase() === 'STAGED').length === 0 ? (
            <p className="text-slate-500 text-sm">No pending invitations.</p>
          ) : (
            <ul className="space-y-2">
              {stays.filter((s: any) => s.invitation_only || (s.token_state || '').toUpperCase() === 'STAGED').map((s: any, idx: number) => {
                const inviteCode = s.invite_id || s.invitation_code || '';
                const inviteUrl = inviteCode ? `${typeof window !== 'undefined' ? window.location.origin : ''}${typeof window !== 'undefined' ? window.location.pathname : ''}#invite/${inviteCode}` : '';
                return (
                  <li key={s.invite_id || s.stay_id || idx} className="flex justify-between items-center gap-4 py-2 border-b border-slate-100 last:border-0 flex-wrap">
                    <span className="text-sm min-w-0 flex-1">{s.guest_name || '—'} · {s.property_name} · {s.stay_start_date} – {s.stay_end_date}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      {inviteUrl ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            navigator.clipboard.writeText(inviteUrl).then(() => notify('success', 'Invitation link copied to clipboard.')).catch(() => notify('error', 'Could not copy.'));
                          }}
                        >
                          Copy link
                        </Button>
                      ) : null}
                      <span className="text-xs text-slate-500">{(s.token_state || '').toUpperCase() || 'Pending'}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}

      {activeTab === 'logs' && (
        <Card className="p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Event ledger</h2>
          {logs.length === 0 ? <p className="text-slate-500 text-sm">No events.</p> : (
            <ul className="space-y-2 max-h-96 overflow-y-auto">
              {logs.map((r) => (
                <li key={r.id} className="text-sm py-2 border-b border-slate-100 last:border-0">
                  <span className="font-medium">{r.title}</span> · {r.property_name || '—'} · {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {activeTab === 'billing' && (
        <Card className="p-6">
          <h2 className="font-semibold text-gray-900 mb-2">Billing (read-only)</h2>
          <p className="text-slate-500 text-sm mb-4">Billing visibility for the properties you manage. You cannot modify billing or payment methods. Contact the property owner for changes.</p>
          {billing?.invoices?.length ? (
            <ul className="space-y-2">
              {billing.invoices.slice(0, 10).map((inv: any) => (
                <li key={inv.id} className="text-sm py-2 border-b border-slate-100">{inv.number || inv.id} · ${((inv.amount_paid_cents || 0) / 100).toFixed(2)}</li>
              ))}
            </ul>
          ) : <p className="text-slate-500 text-sm">No invoices.</p>}
        </Card>
      )}

      {activeTab === 'properties' && (loading ? (
        <div className="text-center py-12 text-slate-500">Loading...</div>
      ) : properties.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-slate-600">No properties assigned yet.</p>
          <p className="text-sm text-slate-500 mt-2">Owners can assign you to manage their properties.</p>
        </Card>
      ) : (
        <div className="space-y-6">
          <p className="text-slate-500 text-sm">Properties assigned to you. View details to see units, occupancy, event ledger, and billing for each property.</p>
          <div className="grid gap-6">
            {properties.map((p) => {
              const activeStayForProp = activeStays.find((s: any) => s.property_id === p.id);
              const isOccupied = !!activeStayForProp;
              const displayStatus = isOccupied ? 'OCCUPIED' : (p.occupancy_status ?? 'unknown').toUpperCase();
              const displayName = p.name || p.address || `Property #${p.id}`;
              return (
                <Card key={p.id} className="p-6 border border-slate-200">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                    <button
                      type="button"
                      onClick={() => navigate(`manager-dashboard/property/${p.id}`)}
                      className="min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                    >
                      <div className="flex flex-wrap items-center gap-2 gap-y-1">
                        <h3 className="text-lg font-bold text-slate-800 truncate">{displayName}</h3>
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
                      <p className="text-sm text-slate-600 mt-1 truncate">{p.address || '—'}</p>
                      <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                        <span>{p.occupied_count}/{p.unit_count} units occupied</span>
                        {isOccupied && activeStayForProp && (
                          <span>Current guest: <span className="font-medium text-slate-700">{activeStayForProp.guest_name}</span></span>
                        )}
                      </div>
                      <span className="inline-block mt-2 text-xs font-medium text-blue-400">View details →</span>
                    </button>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <Button variant="outline" onClick={() => navigate(`manager-dashboard/property/${p.id}`)} className="px-4">
                        View details
                      </Button>
                      <Button variant="ghost" type="button" onClick={(e) => { e.stopPropagation(); loadUnits(p.id); }} className="px-4">
                        {expandedPropertyId === p.id ? 'Hide units' : 'View units'}
                      </Button>
                    </div>
                  </div>
                  {/* Occupancy status – same UI as owner */}
                  <div className="mt-6 pt-6 border-t border-slate-200 rounded-xl bg-slate-50/80 p-4">
                    <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Occupancy status</p>
                    <div className="flex items-center gap-3 flex-wrap">
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
                      {isOccupied && activeStayForProp && (
                        <span className="text-sm text-slate-600">
                          Lease end: <span className="font-medium text-slate-800">{activeStayForProp.stay_end_date}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Units – expandable, same function as owner property detail */}
                  {expandedPropertyId === p.id && (
                    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/50 p-4">
                      <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Units</p>
                      {unitsLoading ? (
                        <p className="text-sm text-slate-500">Loading units...</p>
                      ) : (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                          {units.map((u) => (
                            <div key={u.id} className="bg-white rounded-lg p-3 border border-slate-200 flex flex-col gap-2">
                              <p className="font-medium text-slate-900">Unit {u.unit_label}</p>
                              {statusBadge(u.occupancy_status)}
                              {(u.occupancy_status || '').toLowerCase() === 'vacant' && u.id > 0 && (
                                <Button variant="outline" onClick={() => { setInviteRoleChoiceUnit({ unitId: u.id, unitLabel: u.unit_label }); }}>Invite</Button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      ))}

      <InviteRoleChoiceModal
        open={!!inviteRoleChoiceUnit}
        onClose={() => setInviteRoleChoiceUnit(null)}
        contextLabel={inviteRoleChoiceUnit?.unitId ? `Unit ${inviteRoleChoiceUnit.unitLabel}` : undefined}
        onSelectTenant={() => {
          if (inviteRoleChoiceUnit) {
            setInviteTenantModal({ unitId: inviteRoleChoiceUnit.unitId, unitLabel: inviteRoleChoiceUnit.unitLabel });
            setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
          }
          setInviteRoleChoiceUnit(null);
        }}
        onSelectGuest={() => {
          if (inviteRoleChoiceUnit?.unitId) {
            setInviteGuestForm({ unit_id: inviteRoleChoiceUnit.unitId, guest_name: '', checkin_date: '', checkout_date: '' });
          }
          setInviteGuestLink('');
          setInviteGuestOpen(true);
          setInviteRoleChoiceUnit(null);
        }}
      />

      {inviteTenantModal && (
        <Modal open={!!inviteTenantModal} onClose={() => { setInviteTenantModal(null); setInviteTenantLink(''); }} title="Invite tenant" className="max-w-lg">
          <div className="p-6 space-y-4">
            {inviteTenantLink ? (
              <>
                <p className="text-sm text-slate-600">Share this link with the tenant to complete registration.</p>
                <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all font-mono">{inviteTenantLink}</div>
                <div className="flex gap-3">
                  <Button variant="outline" className="flex-1" onClick={() => { navigator.clipboard.writeText(inviteTenantLink); notify('success', 'Link copied.'); }}>Copy link</Button>
                  <Button className="flex-1" onClick={() => { setInviteTenantModal(null); setInviteTenantLink(''); }}>Done</Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-slate-600">Unit {inviteTenantModal.unitLabel}. The tenant will receive an invite link to register.</p>
                <Input name="tenant_name" label="Tenant name" value={inviteTenantForm.tenant_name} onChange={(e) => setInviteTenantForm({ ...inviteTenantForm, tenant_name: e.target.value })} placeholder="Full name" required />
                <Input name="tenant_email" label="Tenant email" type="email" value={inviteTenantForm.tenant_email} onChange={(e) => setInviteTenantForm({ ...inviteTenantForm, tenant_email: e.target.value })} placeholder="email@example.com" />
                <Input name="lease_start_date" label="Lease start" type="date" min={getTodayLocal()} value={inviteTenantForm.lease_start_date} onChange={(e) => setInviteTenantForm({ ...inviteTenantForm, lease_start_date: e.target.value })} required />
                <Input name="lease_end_date" label="Lease end" type="date" min={inviteTenantForm.lease_start_date || getTodayLocal()} value={inviteTenantForm.lease_end_date} onChange={(e) => setInviteTenantForm({ ...inviteTenantForm, lease_end_date: e.target.value })} required />
                <div className="flex gap-3 pt-2">
                  <Button variant="outline" onClick={() => { setInviteTenantModal(null); setInviteTenantLink(''); }} className="flex-1">Cancel</Button>
                  <Button onClick={handleInviteTenant} disabled={inviteTenantSubmitting} className="flex-1">{inviteTenantSubmitting ? 'Creating…' : 'Create invitation'}</Button>
                </div>
              </>
            )}
          </div>
        </Modal>
      )}

      <Modal open={inviteGuestOpen} onClose={() => { setInviteGuestOpen(false); setInviteGuestLink(''); }} title="Invite guest" className="max-w-lg" disableBackdropClose={inviteGuestSubmitting || !!inviteGuestLink}>
        <div className="p-6">
          {inviteGuestLink ? (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">Share this link with your guest.</p>
              <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">{inviteGuestLink}</div>
              <div className="flex gap-3">
                <Button variant="outline" className="flex-1" onClick={() => { navigator.clipboard.writeText(inviteGuestLink); notify('success', 'Link copied.'); }}>Copy link</Button>
                <Button className="flex-1" onClick={() => { setInviteGuestOpen(false); setInviteGuestLink(''); }}>Done</Button>
              </div>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); handleInviteGuest(); }} className="space-y-4">
              <Input name="guest_name" label="Guest name" value={inviteGuestForm.guest_name} onChange={(e) => setInviteGuestForm({ ...inviteGuestForm, guest_name: e.target.value })} placeholder="Full name" required />
              <Input name="checkin_date" label="Check-in" type="date" min={getTodayLocal()} value={inviteGuestForm.checkin_date} onChange={(e) => setInviteGuestForm({ ...inviteGuestForm, checkin_date: e.target.value })} required />
              <Input name="checkout_date" label="Check-out" type="date" min={inviteGuestForm.checkin_date || getTodayLocal()} value={inviteGuestForm.checkout_date} onChange={(e) => setInviteGuestForm({ ...inviteGuestForm, checkout_date: e.target.value })} required />
              <div className="flex gap-3 pt-2">
                <Button type="button" variant="outline" onClick={() => setInviteGuestOpen(false)} className="flex-1">Cancel</Button>
                <Button type="submit" disabled={inviteGuestSubmitting} className="flex-1">{inviteGuestSubmitting ? 'Creating…' : 'Create invitation'}</Button>
              </div>
            </form>
          )}
        </div>
      </Modal>
          </>
        )}
      </main>
    </div>
  );
};

export default ManagerDashboard;
