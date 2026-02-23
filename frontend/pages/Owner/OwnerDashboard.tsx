
import React, { useState, useEffect, useRef } from 'react';
import { Card, Button, Modal, LoadingOverlay } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { UserSession } from '../../types';
import { dashboardApi, propertiesApi, type OwnerStayView, type OwnerInvitationView, type OwnerAuditLogEntry, type Property, type BulkUploadResult } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';

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

const OwnerDashboard: React.FC<{ user: UserSession; navigate: (v: string) => void; setLoading?: (l: boolean) => void; notify?: (t: 'success' | 'error', m: string) => void; initialTab?: string }> = ({ user, navigate, setLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {}, initialTab }) => {
  const [activeTab, setActiveTab] = useState(initialTab ?? 'dashboard');
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [inactiveProperties, setInactiveProperties] = useState<Property[]>([]);
  const [invitations, setInvitations] = useState<OwnerInvitationView[]>([]);
  const [loading, setLoadingState] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [revokeConfirmStay, setRevokeConfirmStay] = useState<OwnerStayView | null>(null);
  const [revokeSuccessGuest, setRevokeSuccessGuest] = useState<string | null>(null);
  const [packetModalStay, setPacketModalStay] = useState<OwnerStayView | null>(null);
  const [deleteConfirmProperty, setDeleteConfirmProperty] = useState<Property | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [visibleTokenId, setVisibleTokenId] = useState<number | null>(null);
  const [releasingTokenPropertyId, setReleasingTokenPropertyId] = useState<number | null>(null);
  const [releaseTokenModal, setReleaseTokenModal] = useState<{ propertyId: number; propertyName: string } | null>(null);
  const [releaseTokenSelectedStayIds, setReleaseTokenSelectedStayIds] = useState<number[]>([]);
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

  const setLoadingWrapper = (x: boolean) => { setLoadingState(x); setLoading(x); };

  const loadData = () => {
    setLoadingWrapper(true);
    setError(null);
    Promise.all([
      dashboardApi.ownerStays(),
      dashboardApi.ownerInvitations(),
      propertiesApi.list(),
      propertiesApi.listInactive(),
    ])
      .then(([staysData, invitationsData, propertiesList, inactiveList]) => {
        setStays(staysData);
        setInvitations(invitationsData);
        setProperties(propertiesList);
        setInactiveProperties(inactiveList);
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
    if (initialTab) setActiveTab(initialTab);
  }, [initialTab]);

  const releaseTokenToSelected = async () => {
    if (!releaseTokenModal || releaseTokenSelectedStayIds.length === 0) return;
    setReleasingTokenPropertyId(releaseTokenModal.propertyId);
    try {
      await propertiesApi.releaseUsatToken(releaseTokenModal.propertyId, releaseTokenSelectedStayIds);
      notify('success', `USAT token released to ${releaseTokenSelectedStayIds.length} guest(s). Only they can see it.`);
      setReleaseTokenModal(null);
      loadData();
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to release token.');
    } finally {
      setReleasingTokenPropertyId(null);
    }
  };

  const activeStays = stays.filter((s) => !s.checked_out_at && !s.cancelled_at);
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
      notify('success', 'Removal initiated. USAT token revoked. Guest and owner notified via email.');
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

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar Navigation (fixed width so it does not shrink) */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {[
            { id: 'dashboard', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
            { id: 'properties', label: 'My Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
            { id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
            { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
            { id: 'logs', label: 'Logs', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
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

        {/* Guests section: list guests with property and duration */}
        <div className="mt-6 pt-6 border-t border-slate-200 flex-grow min-h-0 flex flex-col">
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-3 px-1">Your guests</h3>
          {loading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : activeStays.length === 0 ? (
            <p className="text-slate-500 text-sm">No active guests. Invite someone to get started.</p>
          ) : (
            <ul className="space-y-3 overflow-y-auto no-scrollbar pr-1">
              {activeStays.map((stay) => (
                <li
                  key={stay.stay_id}
                  className={`rounded-xl p-3 border transition-colors ${activeTab === 'guests' ? 'bg-blue-600/10 border-blue-500/20' : 'bg-slate-100 border-slate-200 hover:bg-slate-100'}`}
                >
                  <div className="flex items-start gap-2">
                    <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs flex-shrink-0">
                      {stay.guest_name.charAt(0)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-slate-800 truncate">{stay.guest_name}</p>
                      <p className="text-xs text-slate-600 truncate mt-0.5" title={stay.property_name}>
                        {stay.property_name}
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        {formatStayDuration(stay.stay_start_date, stay.stay_end_date)}
                      </p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* No duplicate header on Settings/Help – those pages render their own title and content */}
        {activeTab !== 'settings' && activeTab !== 'help' && (
          <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-6">
            <div>
              <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">
                {activeTab === 'properties' ? 'My Properties' : activeTab === 'guests' ? 'Guests' : activeTab === 'invitations' ? 'Invitations' : activeTab === 'logs' ? 'Logs' : 'Overview'}
              </h1>
              <p className="text-slate-600 mt-1">
                {activeTab === 'properties' ? 'View, edit, or remove your registered properties.' : activeTab === 'guests' ? 'Guests currently staying at your properties and their stay details.' : activeTab === 'invitations' ? 'Pending invitations waiting for guests to accept.' : activeTab === 'logs' ? 'Immutable audit trail: status changes, guest signatures, and failed attempts. Filter by time, category, or search.' : 'Protecting your properties with AI Enforcement.'}
              </p>
            </div>
            <div className="flex gap-4 flex-wrap items-center">
              {activeTab !== 'properties' && (
                <Button variant="outline" onClick={() => setShowInviteModal(true)} className="px-6 flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                  Invite Guest
                </Button>
              )}
              {activeTab === 'properties' && (
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
        ) : activeTab === 'guests' ? (
          /* Guests tab: pending invitations + active & expired stays */
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
                                completed ? 'bg-slate-100 text-slate-600 border border-slate-200' : cancelled ? 'bg-slate-100 text-slate-500 border border-slate-200' : revoked ? 'bg-amber-50 text-amber-700 border border-amber-500/20' : overstay ? 'bg-red-50 text-red-600 border border-red-500/20' : 'bg-green-50 text-green-700 border border-green-200'
                              }`}>
                                {completed ? 'Completed' : cancelled ? 'Cancelled' : revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active'}
                              </span>
                            </td>
                            <td className="px-6 py-5 text-right space-x-2">
                              {completed || cancelled ? (
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
                <Button variant="primary" onClick={() => setShowInviteModal(true)}>Invite Guest</Button>
              </Card>
            )}
          </div>
        ) : activeTab === 'invitations' ? (
          /* Invitations tab: Pending, Accepted, Cancelled */
          <div className="space-y-8">
            <p className="text-slate-500 text-sm">
              Invitations you’ve sent. Pending invitations are labeled as expired after 12 hours if not accepted.
            </p>
            <div className="flex gap-4 flex-wrap">
              <Button variant="primary" onClick={() => setShowInviteModal(true)}>Invite Guest</Button>
            </div>

            {/* Pending (within 12h window) */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-amber-50">
                <h3 className="text-xl font-bold text-slate-800">Pending</h3>
                <p className="text-xs text-slate-500 mt-1">Invites not yet accepted (within 12-hour window)</p>
              </div>
              <div className="overflow-x-auto">
                {invitations.filter((i) => i.status === 'pending' && !i.is_expired).length === 0 ? (
                  <p className="p-6 text-slate-500 text-sm">No pending invitations.</p>
                ) : (
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Invited (email)</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Planned stay</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Invitation code</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {invitations.filter((i) => i.status === 'pending' && !i.is_expired).map((inv) => (
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
                            <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-amber-500/10 text-amber-700 border border-amber-200">Pending</span>
                          </td>
                          <td className="px-6 py-5">
                            <Button variant="outline" size="sm" onClick={async () => { try { await dashboardApi.cancelInvitation(inv.id); notify('success', 'Invitation cancelled.'); loadData(); } catch (e) { notify('error', (e as Error)?.message ?? 'Failed to cancel.'); } }}>Cancel invite</Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Card>

            {/* Expired (pending but 12h window exceeded) */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-slate-100">
                <h3 className="text-xl font-bold text-slate-800">Expired invites</h3>
                <p className="text-xs text-slate-500 mt-1">Pending invites whose 12-hour window was exceeded (not accepted in time)</p>
              </div>
              <div className="overflow-x-auto">
                {invitations.filter((i) => i.status === 'pending' && i.is_expired).length === 0 ? (
                  <p className="p-6 text-slate-500 text-sm">No expired invitations.</p>
                ) : (
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Invited (email)</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Planned stay</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Invitation code</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {invitations.filter((i) => i.status === 'pending' && i.is_expired).map((inv) => (
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
                            <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-100 text-slate-600 border border-slate-200">Expired</span>
                          </td>
                          <td className="px-6 py-5">
                            <Button variant="outline" size="sm" onClick={async () => { try { await dashboardApi.cancelInvitation(inv.id); notify('success', 'Invitation cancelled.'); loadData(); } catch (e) { notify('error', (e as Error)?.message ?? 'Failed to cancel.'); } }}>Cancel invite</Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Card>

            {/* Accepted */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-emerald-50">
                <h3 className="text-xl font-bold text-slate-800">Accepted</h3>
                <p className="text-xs text-slate-500 mt-1">Invites accepted by the guest (stay created)</p>
              </div>
              <div className="overflow-x-auto">
                {invitations.filter((i) => i.status === 'accepted').length === 0 ? (
                  <p className="p-6 text-slate-500 text-sm">No accepted invitations.</p>
                ) : (
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Invited (email)</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Planned stay</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Invitation code</th>
                        <th className="px-6 py-4">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {invitations.filter((i) => i.status === 'accepted').map((inv) => (
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
                            <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-emerald-100 text-emerald-700 border border-emerald-200">Accepted</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Card>

            {/* Cancelled: by owner (invitation cancelled) and by guest (stay cancelled after accept) */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-slate-50">
                <h3 className="text-xl font-bold text-slate-800">Cancelled</h3>
                <p className="text-xs text-slate-500 mt-1">Invites cancelled by you and stays cancelled by guests</p>
              </div>
              <div className="divide-y divide-slate-200">
                {/* Cancelled by you (invitation cancelled before guest accepted) */}
                <div className="p-6">
                  <h4 className="text-sm font-bold text-slate-700 mb-2">Cancelled by you</h4>
                  <p className="text-xs text-slate-500 mb-3">Invitations you cancelled before the guest accepted.</p>
                  {invitations.filter((i) => i.status === 'cancelled').length === 0 ? (
                    <p className="text-slate-500 text-sm">No cancelled invitations.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left">
                        <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                          <tr>
                            <th className="px-6 py-4">Invited (email)</th>
                            <th className="px-6 py-4">Property</th>
                            <th className="px-6 py-4">Planned stay</th>
                            <th className="px-6 py-4">Region</th>
                            <th className="px-6 py-4">Invitation code</th>
                            <th className="px-6 py-4">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200">
                          {invitations.filter((i) => i.status === 'cancelled').map((inv) => (
                            <tr key={`inv-${inv.id}`} className="hover:bg-slate-50 transition-colors">
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
                                <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-200 text-slate-600 border border-slate-300">Cancelled by you</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
                {/* Cancelled by guest (had accepted, then cancelled the stay) */}
                <div className="p-6">
                  <h4 className="text-sm font-bold text-slate-700 mb-2">Cancelled by guest</h4>
                  <p className="text-xs text-slate-500 mb-3">Stays that the guest cancelled after accepting your invitation.</p>
                  {stays.filter((s) => s.cancelled_at).length === 0 ? (
                    <p className="text-slate-500 text-sm">No stays cancelled by guests.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left">
                        <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                          <tr>
                            <th className="px-6 py-4">Guest</th>
                            <th className="px-6 py-4">Property</th>
                            <th className="px-6 py-4">Planned stay</th>
                            <th className="px-6 py-4">Region</th>
                            <th className="px-6 py-4">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200">
                          {stays.filter((s) => s.cancelled_at).map((stay) => (
                            <tr key={`stay-${stay.stay_id}`} className="hover:bg-slate-50 transition-colors">
                              <td className="px-6 py-5">
                                <span className="text-sm font-medium text-slate-800">{stay.guest_name}</span>
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
                                <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-200 text-slate-500 border border-slate-300">Cancelled by guest</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          </div>
        ) : activeTab === 'properties' ? (
          /* Properties tab: Active list + Inactive section */
          <div className="space-y-8">
            <p className="text-slate-500 text-sm">
              Remove a property from your dashboard when it has no active guest stay; it moves to Inactive and can be reactivated. Data is kept for logs. Inactive properties do not appear when creating an invite.
            </p>
            {properties.length === 0 && inactiveProperties.length === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">You haven’t registered any properties yet.</p>
                <Button variant="primary" onClick={() => navigate('add-property')}>Register your first property</Button>
              </Card>
            ) : (
              <>
              {/* Active properties */}
              {properties.length > 0 && (
              <div>
                <h3 className="text-lg font-bold text-slate-800 mb-4">Active properties</h3>
                <div className="grid gap-6">
                {properties.map((prop) => {
                  const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
                  const displayName = prop.name || address || `Property #${prop.id}`;
                  const hasResident = activeStays.some((s) => s.property_id === prop.id);
                  const activeStayForProp = activeStays.find((s) => s.property_id === prop.id);
                  const isOccupied = !!activeStayForProp;
                  const shieldOn = !!prop.shield_mode_enabled;
                  const shieldStatus = shieldOn ? (isOccupied ? 'PASSIVE GUARD' : 'ACTIVE ENFORCEMENT') : null;
                  const tokenVisible = visibleTokenId === prop.id;
                  const tokenReleased = (prop.usat_token_state || 'staged') === 'released';
                  const releaseInProgress = releasingTokenPropertyId === prop.id;
                  const copyToken = async () => {
                    if (prop.usat_token) {
                      const ok = await copyToClipboard(prop.usat_token);
                      if (ok) notify('success', 'Token copied to clipboard.');
                      else notify('error', 'Copy failed.');
                    }
                  };
                  const activeGuestsForProp = activeStays.filter((s) => s.property_id === prop.id);
                  const openReleaseModal = () => {
                    if (!hasResident) return;
                    setReleaseTokenModal({
                      propertyId: prop.id,
                      propertyName: displayName,
                    });
                    const alreadyHaveToken = activeGuestsForProp.filter((s) => s.usat_token_released_at).map((s) => s.stay_id);
                    setReleaseTokenSelectedStayIds(alreadyHaveToken.length > 0 ? alreadyHaveToken : activeGuestsForProp.map((s) => s.stay_id));
                  };
                  return (
                    <Card key={prop.id} className="p-6 border border-slate-200">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                        <button
                          type="button"
                          onClick={() => navigate(`property/${prop.id}`)}
                          className="min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                        >
                          <h3 className="text-lg font-bold text-slate-800 truncate">{displayName}</h3>
                          <p className="text-sm text-slate-600 mt-1 truncate">{address || '—'}</p>
                          <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                            <span>Region: <span className="text-slate-600 font-medium">{prop.region_code}</span></span>
                            {(prop.property_type_label || prop.property_type) && (
                              <span>Type: <span className="text-slate-600 font-medium">{prop.property_type_label || prop.property_type}</span></span>
                            )}
                            {prop.bedrooms && (
                              <span>Bedrooms: <span className="text-slate-600 font-medium">{prop.bedrooms}</span></span>
                            )}
                            {isOccupied && activeStayForProp && (
                              <span>
                                Dead Man&apos;s Switch: <span className={activeStayForProp.dead_mans_switch_enabled ? 'text-amber-600 font-medium' : 'text-slate-600 font-medium'}>
                                  {activeStayForProp.dead_mans_switch_enabled ? 'On' : 'Off'}
                                </span>
                              </span>
                            )}
                          </div>
                          <span className="inline-block mt-2 text-xs font-medium text-blue-400">View details →</span>
                        </button>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <Button variant="outline" onClick={() => navigate(`property/${prop.id}`)} className="px-4">
                            View & Edit
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => { setDeleteConfirmProperty(prop); setDeleteError(null); }}
                            className="px-4 text-red-600 hover:text-red-700 hover:bg-red-50"
                          >
                            Remove Property
                          </Button>
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
                          {isOccupied && activeStayForProp && (
                            <span className="text-sm text-slate-600">
                              Current guest: <span className="font-medium text-slate-800">{activeStayForProp.guest_name}</span>
                              {' · '}
                              Lease end: <span className="font-medium text-slate-800">{activeStayForProp.stay_end_date}</span>
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Shield Mode: turns on automatically on last day of guest's stay; owner can only turn OFF */}
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Shield Mode</p>
                        <div className="flex flex-wrap items-center gap-4">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              role="switch"
                              aria-checked={shieldOn}
                              disabled={shieldTogglePropertyId === prop.id || !shieldOn}
                              title={!shieldOn ? "Shield Mode turns on automatically on the last day of a guest's stay" : 'Turn Shield Mode off'}
                              onClick={async () => {
                                if (!shieldOn) return;
                                setShieldTogglePropertyId(prop.id);
                                try {
                                  await propertiesApi.update(prop.id, { shield_mode_enabled: false });
                                  notify('success', 'Shield Mode turned off.');
                                  loadData();
                                } catch (e) {
                                  notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                                } finally {
                                  setShieldTogglePropertyId(null);
                                }
                              }}
                              className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${shieldOn ? 'cursor-pointer bg-emerald-600' : 'cursor-not-allowed bg-slate-200 opacity-60'} ${shieldTogglePropertyId === prop.id ? 'opacity-50' : ''}`}
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
                            <span className="text-xs text-slate-500">Turns on automatically on the last day of a guest&apos;s stay</span>
                          )}
                          <span className="text-xs text-slate-400">$10/month subscription</span>
                        </div>
                      </div>

                      {/* USAT Token row: copyable, Release opens modal to choose which guests */}
                      {prop.usat_token && (
                        <div className="mt-6 pt-6 border-t border-slate-200">
                          <p className="text-xs text-slate-500 mb-2">Release opens a list of current guests for this property; choose who can see the token.</p>
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">USAT Token</span>
                            <code className={`px-3 py-1.5 rounded-lg font-mono text-sm ${tokenVisible ? 'bg-slate-100 text-slate-800' : 'bg-slate-100 text-slate-400'}`}>
                              {tokenVisible ? prop.usat_token : '••••••••••••••••••••••••••••••••'}
                            </code>
                            <button
                              type="button"
                              onClick={() => setVisibleTokenId(tokenVisible ? null : prop.id)}
                              className="text-xs font-semibold text-blue-600 hover:text-blue-800"
                            >
                              {tokenVisible ? 'Hide' : 'Show'}
                            </button>
                            <Button variant="outline" onClick={copyToken} className="text-xs py-1.5 px-3">
                              Copy
                            </Button>
                            <span className="text-slate-400">|</span>
                            <span
                              title={!hasResident ? 'No guest is resident on the property.' : tokenReleased ? 'Add or change which guests can see the token.' : undefined}
                              className="inline-flex"
                            >
                              <Button
                                variant="outline"
                                disabled={!hasResident || releaseInProgress}
                                onClick={openReleaseModal}
                                className="text-xs py-1.5 px-3"
                              >
                                {tokenReleased ? 'Manage' : releaseInProgress ? 'Releasing…' : 'Release'}
                              </Button>
                            </span>
                          </div>
                        </div>
                      )}
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
                    return (
                      <Card key={prop.id} className="p-6 border border-slate-200 bg-slate-50/50">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                          <div className="min-w-0 flex-1">
                            <h3 className="text-lg font-bold text-slate-700 truncate">{displayName}</h3>
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
                    <option value="dead_mans_switch">Dead Man&apos;s Switch</option>
                    <option value="guest_signature">Guest signature</option>
                    <option value="failed_attempt">Failed attempt</option>
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
                <h3 className="text-lg font-bold text-slate-800">Audit log (append-only)</h3>
                <p className="text-slate-500 text-sm mt-1">Status changes, Shield Mode and Dead Man&apos;s Switch on/off, guest signatures, and failed attempts are recorded. Use the category filter to view Shield Mode or Dead Man&apos;s Switch logs. Records cannot be edited or deleted.</p>
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
                              'bg-sky-100 text-sky-800'
                            }`}>
                              {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? "Dead Man's Switch" : entry.category.replace('_', ' ')}
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
            <Settings user={user} navigate={navigate} embedded />
          </div>
        ) : activeTab === 'help' ? (
          <div className="w-full">
            <HelpCenter navigate={navigate} embedded />
          </div>
        ) : (
          <>
            {/* Status Alert for Overstays (real data) */}
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

            <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
              <Card
                className="p-6 border-l-4 border-blue-500 hover:scale-[1.02] transition-transform cursor-pointer"
                onClick={() => setActiveTab('properties')}
              >
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
              <Card className="p-6 border-l-4 border-blue-400 hover:scale-[1.02] transition-transform cursor-pointer">
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Legal Shield</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1 uppercase tracking-tighter">{properties.length > 0 ? 'Protected' : '—'}</p>
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
                                <Button variant="ghost" onClick={() => handleRevokeClick(stay)} className="text-xs py-2 text-red-600 hover:text-red-700">Kill Switch</Button>
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
          <p><strong>Required columns:</strong> <code className="bg-slate-100 px-1 rounded">street_address</code> (or <code className="bg-slate-100 px-1 rounded">street</code>), <code className="bg-slate-100 px-1 rounded">city</code>, <code className="bg-slate-100 px-1 rounded">state</code>.</p>
          <p><strong>Optional columns:</strong> <code className="bg-slate-100 px-1 rounded">property_name</code>, <code className="bg-slate-100 px-1 rounded">zip_code</code>, <code className="bg-slate-100 px-1 rounded">region_code</code>, <code className="bg-slate-100 px-1 rounded">property_type</code>, <code className="bg-slate-100 px-1 rounded">bedrooms</code>, <code className="bg-slate-100 px-1 rounded">is_primary_residence</code> (true/false).</p>
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
            Use a CSV file with the following columns. <strong>Required:</strong> <code className="bg-slate-100 px-1 rounded">street_address</code> (or <code className="bg-slate-100 px-1 rounded">street</code>), <code className="bg-slate-100 px-1 rounded">city</code>, <code className="bg-slate-100 px-1 rounded">state</code>. <strong>Optional:</strong> <code className="bg-slate-100 px-1 rounded">property_name</code>, <code className="bg-slate-100 px-1 rounded">zip_code</code>, <code className="bg-slate-100 px-1 rounded">region_code</code>, <code className="bg-slate-100 px-1 rounded">property_type</code>, <code className="bg-slate-100 px-1 rounded">bedrooms</code>, <code className="bg-slate-100 px-1 rounded">is_primary_residence</code> (true/false).
          </p>
          <p className="text-xs text-slate-500">
            Existing properties (same street, city, state) are updated only when values change. Empty optional cells keep existing values. If the upload fails partway, rows before the failure are saved.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => {
                const header = 'property_name,street_address,city,state,zip_code,region_code,property_type,bedrooms,is_primary_residence';
                const example = 'Beach House,123 Ocean Ave,Miami,FL,33139,FL,entire_home,2,false';
                const blob = new Blob([header + '\n' + example], { type: 'text/csv' });
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

      {/* Loading overlay while bulk upload is processing */}
      {bulkUploading && <LoadingOverlay message="Uploading properties…" />}

      {/* Remove property (soft-delete) confirmation modal */}
      {deleteConfirmProperty && (
        <>
          <div className="fixed inset-0 bg-black/70 z-40" onClick={() => { setDeleteConfirmProperty(null); setDeleteError(null); }} />
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
          <div className="fixed inset-0 bg-black/70 z-40" onClick={() => setRevokeConfirmStay(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6 border-b border-slate-200">
                <h3 className="text-lg font-bold text-slate-800">Revoke stay authorization</h3>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-slate-600 text-sm">
                  Revoking <span className="font-bold text-slate-800">{revokeConfirmStay.guest_name}</span> will terminate their USAT token and trigger a 12-hour vacate notice. Proceed?
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
          <div className="fixed inset-0 bg-black/70 z-40" onClick={() => setRevokeSuccessGuest(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6">
                <p className="text-green-600 font-medium mb-4">Revocation successful. Legal audit trail updated.</p>
                <Button onClick={() => setRevokeSuccessGuest(null)}>Done</Button>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Initiate Removal modal */}
      {packetModalStay && (
        <>
          <div className="fixed inset-0 bg-black/70 z-40" onClick={() => !removalLoading && setPacketModalStay(null)} />
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
                    <li>Revoke the guest's USAT token (utility access disabled)</li>
                    <li>Send removal notice email to the guest</li>
                    <li>Send confirmation email to you</li>
                    <li>Log all actions for legal documentation</li>
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
          <div className="fixed inset-0 bg-black/70 z-40" onClick={() => setLogMessageModalEntry(null)} aria-hidden="true" />
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

      {releaseTokenModal && (
        <Modal
          open={!!releaseTokenModal}
          title="Release USAT token"
          onClose={() => setReleaseTokenModal(null)}
          className="max-w-md"
        >
          <div className="p-6" onClick={(e) => e.stopPropagation()}>
            <p className="text-slate-600 text-sm mb-4">
              Choose which guest(s) at <span className="font-medium text-slate-800">{releaseTokenModal.propertyName}</span> can see the USAT token. Only selected guests will see it on their dashboard.
            </p>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Select guest(s) to release the token to</p>
            <div className="space-y-2 mb-6 min-h-[80px]">
              {(activeStays ?? [])
                .filter((s) => s.property_id === releaseTokenModal.propertyId)
                .map((stay) => (
                  <label key={stay.stay_id} className="flex items-center gap-3 p-3 rounded-lg border border-slate-200 hover:bg-slate-50 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={releaseTokenSelectedStayIds.includes(stay.stay_id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setReleaseTokenSelectedStayIds((ids) => [...ids, stay.stay_id]);
                        } else {
                          setReleaseTokenSelectedStayIds((ids) => ids.filter((id) => id !== stay.stay_id));
                        }
                      }}
                      className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="font-medium text-slate-800">{stay.guest_name}</span>
                    <span className="text-xs text-slate-500">
                      {stay.stay_start_date} – {stay.stay_end_date}
                    </span>
                  </label>
                ))}
              {(activeStays ?? []).filter((s) => s.property_id === releaseTokenModal.propertyId).length === 0 && (
                <p className="text-slate-500 text-sm py-4">No current guests for this property. The guest list comes from active stays; invite and have a guest accept to see them here.</p>
              )}
            </div>
            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => setReleaseTokenModal(null)}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={releaseTokenToSelected}
                disabled={releaseTokenSelectedStayIds.length === 0 || releasingTokenPropertyId === releaseTokenModal.propertyId}
                className="flex-1"
              >
                {releasingTokenPropertyId === releaseTokenModal.propertyId ? 'Releasing…' : 'Release to selected'}
              </Button>
            </div>
          </div>
        </Modal>
      )}

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
