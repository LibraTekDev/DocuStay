
import React, { useState, useEffect, useCallback } from 'react';
import { Card, Button, Input, Modal } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { UserSession } from '../../types';
import { JURISDICTION_RULES } from '../../services/jleService';
import { propertiesApi, dashboardApi, type Property, type OwnerStayView } from '../../services/api';

function formatStayDuration(startStr: string, endStr: string): string {
  const start = new Date(startStr);
  const end = new Date(endStr);
  const days = Math.max(1, Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return `${fmt(start)} – ${fmt(end)} (${days} day${days !== 1 ? 's' : ''})`;
}

const PROPERTY_TYPES = [
  { id: 'house', name: 'House' },
  { id: 'apartment', name: 'Apartment' },
  { id: 'condo', name: 'Condo' },
  { id: 'townhouse', name: 'Townhouse' },
  { id: 'entire_home', name: 'Entire home' },
  { id: 'private_room', name: 'Private room' },
];

function isOverstayed(endDateStr: string): boolean {
  const end = new Date(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return end.getTime() < today.getTime();
}

export const PropertyDetail: React.FC<{ propertyId: string; user: UserSession; navigate: (v: string) => void; setLoading?: (l: boolean) => void; notify?: (t: 'success' | 'error', m: string) => void }> = ({ propertyId, user, navigate, setLoading: setGlobalLoading = () => {}, notify = () => {} }) => {
  const [activeTab, setActiveTab] = useState('overview');
  const [property, setProperty] = useState<Property | null>(null);
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteSaving, setDeleteSaving] = useState(false);
  const [shieldToggling, setShieldToggling] = useState(false);
  const [reactivating, setReactivating] = useState(false);
  const [editForm, setEditForm] = useState({
    property_name: '',
    street_address: '',
    city: '',
    state: '',
    zip_code: '',
    region_code: '',
    property_type: 'house',
    bedrooms: '1',
    is_primary_residence: false,
  });
  const [editError, setEditError] = useState<string | null>(null);
  const [proofLoading, setProofLoading] = useState(false);
  const [confirmingOccupancy, setConfirmingOccupancy] = useState(false);
  const [confirmOccupancyAction, setConfirmOccupancyAction] = useState<'vacated' | 'renewed' | 'holdover' | null>(null);
  const [renewEndDate, setRenewEndDate] = useState('');
  const id = Number(propertyId);
  const stateKey = property?.state ?? 'FL';
  const jurisdictionInfo = JURISDICTION_RULES[stateKey as keyof typeof JURISDICTION_RULES] ?? JURISDICTION_RULES.FL;
  const propertyStays = stays.filter((s) => s.property_id === id);
  const activeStaysForProperty = propertyStays.filter((s) => !s.checked_out_at && !s.cancelled_at);
  const activeStays = stays.filter((s) => !s.checked_out_at && !s.cancelled_at);
  const activeStay = activeStaysForProperty.find((s) => !isOverstayed(s.stay_end_date)) ?? activeStaysForProperty[0];
  const isOccupied = activeStaysForProperty.length > 0;
  const hasActiveStay = activeStaysForProperty.length > 0;
  const shieldOn = !!(property?.shield_mode_enabled);
  const shieldStatus = shieldOn ? (isOccupied ? 'PASSIVE GUARD' : 'ACTIVE MONITORING') : null;
  const isInactive = !!(property?.deleted_at);
  // Display status: active stay → OCCUPIED; else use property.occupancy_status (vacant | occupied | unknown | unconfirmed)
  const displayStatus = isOccupied ? 'OCCUPIED' : (property?.occupancy_status ?? 'unknown').toUpperCase();
  const stayNeedingConfirmation = propertyStays.find((s) => s.show_occupancy_confirmation_ui);

  const loadData = useCallback(() => {
    if (!id || isNaN(id)) {
      const msg = 'Invalid property';
      setError(msg);
      notify('error', msg);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([propertiesApi.get(id), dashboardApi.ownerStays()])
      .then(([prop, staysData]) => {
        setProperty(prop);
        setStays(staysData);
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? 'Failed to load property.';
        setError(msg);
        notify('error', msg);
      })
      .finally(() => setLoading(false));
  }, [id, notify]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /** When edit modal opens, always pre-fill form from current property so existing values are retained. */
  const syncEditFormFromProperty = useCallback(() => {
    if (!property) return;
    const typeRaw = property.property_type_label ?? property.property_type ?? 'house';
    const typeNorm = String(typeRaw).toLowerCase().trim().replace(/\s+/g, '_');
    setEditForm({
      property_name: property.name ?? '',
      street_address: property.street ?? '',
      city: property.city ?? '',
      state: property.state ?? '',
      zip_code: property.zip_code ?? '',
      region_code: property.region_code ?? '',
      property_type: typeNorm || 'house',
      bedrooms: property.bedrooms ?? '1',
      is_primary_residence: property.owner_occupied ?? false,
    });
  }, [property]);

  const openEdit = () => {
    if (property) {
      syncEditFormFromProperty();
      setEditError(null);
      setEditOpen(true);
    }
  };

  /** Keep form in sync with current property whenever the edit modal is open (e.g. so existing values are shown). */
  useEffect(() => {
    if (editOpen && property) {
      syncEditFormFromProperty();
    }
  }, [editOpen, property, syncEditFormFromProperty]);

  const saveEdit = async () => {
    if (!property) return;
    const street = editForm.street_address?.trim();
    const city = editForm.city?.trim();
    const state = editForm.state?.trim();
    if (!street || !city || !state) {
      setEditError('Street address, city, and state are required.');
      return;
    }
    setEditSaving(true);
    setEditError(null);
    try {
      const payload: Parameters<typeof propertiesApi.update>[1] = {
        street_address: street,
        city,
        state,
        property_name: editForm.property_name?.trim() || undefined,
        zip_code: editForm.zip_code?.trim() || undefined,
        region_code: editForm.region_code?.trim() ? editForm.region_code.trim().toUpperCase().slice(0, 20) : undefined,
        property_type: editForm.property_type || undefined,
        bedrooms: editForm.bedrooms || undefined,
        is_primary_residence: editForm.is_primary_residence,
      };
      const updated = await propertiesApi.update(property.id, payload);
      setProperty(updated);
      setEditOpen(false);
      notify('success', 'Property updated.');
    } catch (e) {
      const msg = (e as Error)?.message ?? 'Failed to update property.';
      setEditError(msg);
      notify('error', msg);
    } finally {
      setEditSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!property) return;
    setDeleteSaving(true);
    setDeleteError(null);
    try {
      await propertiesApi.delete(property.id);
      setDeleteConfirmOpen(false);
      notify('success', 'Property removed from dashboard. It has been moved to Inactive properties.');
      navigate('dashboard/properties');
    } catch (e) {
      const msg = (e as Error)?.message ?? 'Failed to remove property.';
      setDeleteError(msg);
      notify('error', msg);
    } finally {
      setDeleteSaving(false);
    }
  };

  const address = property ? [property.street, property.city, property.state, property.zip_code].filter(Boolean).join(', ') : '';

  const sidebarNav = [
    { id: 'dashboard', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { id: 'properties', label: 'My Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
    { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
    { id: 'billing', label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' },
    { id: 'logs', label: 'Logs', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];

  const onNav = (itemId: string) => {
    if (itemId === 'settings') navigate('settings');
    else if (itemId === 'help') navigate('help');
    else if (itemId === 'properties') navigate('dashboard/properties');
    else if (itemId === 'billing') navigate('dashboard/billing');
    else if (itemId === 'guests') navigate('dashboard/guests');
    else if (itemId === 'invitations') navigate('dashboard/invitations');
    else if (itemId === 'logs') navigate('dashboard/logs');
    else navigate('dashboard');
  };

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar - same as OwnerDashboard (fixed width so it does not shrink) */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {sidebarNav.map((item) => (
            <button
              key={item.id}
              onClick={() => onNav(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${item.id === 'properties' ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} /></svg>
              {item.label}
            </button>
          ))}
        </div>
        <div className="mt-6 pt-6 border-t border-slate-200 flex-grow min-h-0 flex flex-col">
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-3 px-1">Your guests</h3>
          {loading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : activeStays.length === 0 ? (
            <p className="text-slate-500 text-sm">No active guests.</p>
          ) : (
            <ul className="space-y-3 overflow-y-auto no-scrollbar pr-1">
              {activeStays.map((stay) => (
                <li key={stay.stay_id} className="rounded-xl p-3 border border-slate-200 bg-slate-100 hover:bg-slate-100">
                  <div className="flex items-start gap-2">
                    <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs flex-shrink-0">
                      {stay.guest_name.charAt(0)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-slate-800 truncate">{stay.guest_name}</p>
                      <p className="text-xs text-slate-600 truncate mt-0.5">{stay.property_name}</p>
                      <p className="text-xs text-slate-500 mt-1">{formatStayDuration(stay.stay_start_date, stay.stay_end_date)}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <main className="flex-grow overflow-y-auto bg-transparent p-6 lg:p-8">
        {loading ? (
          <p className="text-slate-600">Loading property…</p>
        ) : error || !property ? (
          <Card className="p-8 text-center max-w-md mx-auto border-slate-200">
            <p className="text-slate-600 mb-4">Something went wrong loading this property.</p>
            <div className="flex gap-3 justify-center">
              <Button variant="outline" onClick={() => navigate('dashboard/properties')}>Back to My Properties</Button>
              <Button variant="primary" onClick={() => { setError(null); loadData(); }}>Try again</Button>
            </div>
          </Card>
        ) : (
          <>
      <header className="mb-8">
        <button onClick={() => navigate('dashboard/properties')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-6 text-sm font-medium transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" /></svg>
          Back to My Properties
        </button>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl lg:text-3xl font-bold text-slate-800 tracking-tight">{property.name || address || 'Property'}</h1>
              {isInactive && (
                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold uppercase tracking-wider bg-amber-100 text-amber-800 border border-amber-200">
                  Inactive
                </span>
              )}
            </div>
            <p className="text-slate-600 mt-1">{address || '—'}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" onClick={openEdit}>Edit Property</Button>
            {!isInactive && (
              <Button variant="primary" onClick={() => setShowInviteModal(true)}>Invite Guest</Button>
            )}
            {isInactive ? (
              <Button
                variant="primary"
                disabled={reactivating}
                onClick={async () => {
                  if (!property) return;
                  setReactivating(true);
                  try {
                    await propertiesApi.reactivate(property.id);
                    notify('success', 'Property reactivated. It appears in My Properties and in the invite list again.');
                    loadData();
                  } catch (e) {
                    notify('error', (e as Error)?.message ?? 'Failed to reactivate.');
                  } finally {
                    setReactivating(false);
                  }
                }}
              >
                {reactivating ? 'Reactivating…' : 'Reactivate property'}
              </Button>
            ) : (
              <Button
                variant="ghost"
                onClick={() => { setDeleteConfirmOpen(true); setDeleteError(null); }}
                disabled={hasActiveStay}
                title={hasActiveStay ? 'Cannot remove property while it has an active guest stay. Wait for the stay to end or be cancelled.' : 'Remove from dashboard (moves to Inactive properties)'}
                className="text-red-600 hover:text-red-700 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Remove Property
              </Button>
            )}
          </div>
        </div>
      </header>

      <div className="flex border-b border-slate-200 mb-8 overflow-x-auto no-scrollbar">
        {['Overview', 'Guests', 'Documentation'].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab.toLowerCase())}
            className={`px-6 py-3 text-sm font-medium whitespace-nowrap transition-all border-b-2 ${activeTab === tab.toLowerCase() ? 'text-slate-800 border-slate-800' : 'text-slate-500 border-transparent hover:text-slate-700'}`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
        {activeTab === 'overview' && (
          <div className="space-y-8">
            <div className="space-y-8">
              {property && (
                <>
                <Card className="p-6 border-slate-200">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Address & property details</h3>
                  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
                    {[
                      { label: 'Street', value: property.street },
                      { label: 'City', value: property.city },
                      { label: 'State', value: property.state },
                      { label: 'ZIP code', value: property.zip_code },
                      { label: 'Region', value: property.region_code },
                      { label: 'Property type', value: property.property_type_label || property.property_type },
                      { label: 'Bedrooms', value: property.bedrooms },
                      { label: 'Primary residence', value: property.owner_occupied ? 'Yes' : 'No' },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex flex-col gap-1">
                        <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</dt>
                        <dd className="text-sm font-medium text-slate-800">{value ?? '—'}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
                <Card className="p-6 border-slate-200">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Ownership proof</h3>
                  {property.ownership_proof_filename ? (
                    <div className="space-y-2">
                      <p className="text-sm text-slate-600">
                        {property.ownership_proof_filename}
                        {property.ownership_proof_type && (
                          <span className="ml-2 text-slate-500">({property.ownership_proof_type.replace(/_/g, ' ')})</span>
                        )}
                      </p>
                      <Button
                        variant="outline"
                        disabled={proofLoading}
                        className="text-sm px-4 py-2"
                        onClick={async () => {
                          if (!property) return;
                          setProofLoading(true);
                          try {
                            const blob = await propertiesApi.getOwnershipProofBlob(property.id);
                            const url = URL.createObjectURL(blob);
                            window.open(url, '_blank', 'noopener,noreferrer');
                            setTimeout(() => URL.revokeObjectURL(url), 60000);
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to load proof.');
                          } finally {
                            setProofLoading(false);
                          }
                        }}
                      >
                        {proofLoading ? 'Loading…' : 'View proof'}
                      </Button>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">You do not have any proof uploaded.</p>
                  )}
                </Card>
                {stayNeedingConfirmation && (
                  <Card className="mb-6 p-5 md:p-6 border-amber-200 bg-amber-50/80">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-amber-800 mb-2">Confirm occupancy status</h3>
                    <p className="text-sm text-amber-900 mb-3">
                      {stayNeedingConfirmation.needs_occupancy_confirmation
                        ? `Please confirm the status of this unit before ${stayNeedingConfirmation.confirmation_deadline_at ? new Date(stayNeedingConfirmation.confirmation_deadline_at).toLocaleString() : 'the deadline'}.`
                        : 'No response was received by the deadline. Status is UNCONFIRMED. Please confirm now.'}
                    </p>
                    <div className="flex flex-wrap gap-3">
                      <Button
                        variant="outline"
                        className="border-amber-600 text-amber-800 hover:bg-amber-100"
                        disabled={confirmingOccupancy}
                        onClick={async () => {
                          if (!stayNeedingConfirmation) return;
                          setConfirmOccupancyAction('vacated');
                          setConfirmingOccupancy(true);
                          try {
                            await dashboardApi.confirmOccupancyStatus(stayNeedingConfirmation.stay_id, 'vacated');
                            notify('success', 'Unit marked as vacated.');
                            loadData();
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                          } finally {
                            setConfirmingOccupancy(false);
                            setConfirmOccupancyAction(null);
                          }
                        }}
                      >
                        Unit Vacated
                      </Button>
                      <Button
                        variant="outline"
                        className="border-amber-600 text-amber-800 hover:bg-amber-100"
                        disabled={confirmingOccupancy}
                        onClick={() => setConfirmOccupancyAction('renewed')}
                      >
                        Lease Renewed
                      </Button>
                      <Button
                        variant="outline"
                        className="border-amber-600 text-amber-800 hover:bg-amber-100"
                        disabled={confirmingOccupancy}
                        onClick={async () => {
                          if (!stayNeedingConfirmation) return;
                          setConfirmOccupancyAction('holdover');
                          setConfirmingOccupancy(true);
                          try {
                            await dashboardApi.confirmOccupancyStatus(stayNeedingConfirmation.stay_id, 'holdover');
                            notify('success', 'Holdover confirmed.');
                            loadData();
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                          } finally {
                            setConfirmingOccupancy(false);
                            setConfirmOccupancyAction(null);
                          }
                        }}
                      >
                        Holdover
                      </Button>
                    </div>
                    {confirmOccupancyAction === 'renewed' && (
                      <div className="mt-4 flex flex-wrap items-center gap-3">
                        <input
                          type="date"
                          value={renewEndDate}
                          onChange={(e) => setRenewEndDate(e.target.value)}
                          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                          min={stayNeedingConfirmation?.stay_end_date ?? undefined}
                        />
                        <Button
                          variant="outline"
                          disabled={!renewEndDate || confirmingOccupancy}
                          onClick={async () => {
                            if (!stayNeedingConfirmation || !renewEndDate) return;
                            setConfirmingOccupancy(true);
                            try {
                              await dashboardApi.confirmOccupancyStatus(stayNeedingConfirmation.stay_id, 'renewed', renewEndDate);
                              notify('success', 'Lease renewed.');
                              setRenewEndDate('');
                              setConfirmOccupancyAction(null);
                              loadData();
                            } catch (e) {
                              notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                            } finally {
                              setConfirmingOccupancy(false);
                            }
                          }}
                        >
                          Confirm renewal
                        </Button>
                        <button
                          type="button"
                          className="text-sm text-slate-600 hover:text-slate-800"
                          onClick={() => { setConfirmOccupancyAction(null); setRenewEndDate(''); }}
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </Card>
                )}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6">
                  <Card className="p-5 md:p-6 border-slate-200 bg-slate-50/80 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Occupancy status</h3>
                    <div className="flex flex-col gap-3 flex-1 min-h-0">
                      <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium w-fit ${
                        displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                        displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                        displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        <span className={`w-2 h-2 rounded-full shrink-0 ${
                          displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                          displayStatus === 'VACANT' ? 'bg-slate-400' :
                          displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                        }`} />
                        {displayStatus}
                      </span>
                      {isOccupied && activeStay && (
                        <div className="text-sm text-slate-600 space-y-0.5">
                          <p>Current guest: <span className="font-medium text-slate-800">{activeStay.guest_name}</span></p>
                          <p>Lease end: <span className="font-medium text-slate-800">{activeStay.stay_end_date}</span></p>
                        </div>
                      )}
                      {displayStatus === 'UNCONFIRMED' && (
                        <p className="text-xs text-amber-700">Confirmation requested but no response received by deadline. Use the confirmation options above.</p>
                      )}
                    </div>
                  </Card>
                  <Card className="p-5 md:p-6 border-slate-200 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Shield Mode</h3>
                    <div className="flex flex-col gap-3 flex-1 min-h-0">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={shieldOn}
                          disabled={shieldToggling || !shieldOn}
                          title={!shieldOn ? "Shield Mode turns on automatically on the last day of a guest's stay" : 'Turn Shield Mode off'}
                          onClick={async () => {
                            if (!property || !shieldOn) return;
                            setShieldToggling(true);
                            try {
                              const updated = await propertiesApi.update(property.id, { shield_mode_enabled: false });
                              setProperty(updated);
                              notify('success', 'Shield Mode turned off.');
                            } catch (e) {
                              notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                            } finally {
                              setShieldToggling(false);
                            }
                          }}
                          className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${shieldOn ? 'cursor-pointer bg-emerald-600' : 'cursor-not-allowed bg-slate-200 opacity-60'} ${shieldToggling ? 'opacity-50' : ''}`}
                        >
                          <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform ${shieldOn ? 'translate-x-5' : 'translate-x-1'}`} />
                        </button>
                        <span className="text-sm font-medium text-slate-800">{shieldOn ? 'ON' : 'OFF'}</span>
                      </div>
                      {shieldOn && shieldStatus && (
                        <span className="text-sm text-slate-600">Status: <span className="font-semibold text-slate-800">{shieldStatus}</span></span>
                      )}
                      {!shieldOn && (
                        <span className="text-xs text-slate-500">Turns on automatically on the last day of a guest&apos;s stay</span>
                      )}
                    </div>
                  </Card>
                  <Card className="p-5 md:p-6 border-slate-200 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Dead Man&apos;s Switch</h3>
                    <div className="flex flex-col gap-2 flex-1 min-h-0">
                      {isOccupied && activeStay ? (
                        <>
                          <span className={`text-sm font-medium ${activeStay.dead_mans_switch_enabled ? 'text-amber-700' : 'text-slate-600'}`}>
                            {activeStay.dead_mans_switch_enabled ? 'On' : 'Off'}
                          </span>
                          <p className="text-xs text-slate-500">Alerts you if the stay ends without checkout or renewal. Shown for current guest stay.</p>
                        </>
                      ) : (
                        <span className="text-sm text-slate-500">No active stay at this property.</span>
                      )}
                    </div>
                  </Card>
                </div>
                </>
              )}

              <Card className="p-6 border-slate-200">
                <h3 className="text-lg font-semibold text-slate-800 mb-4">Jurisdiction Shield</h3>
                <div className="grid md:grid-cols-2 gap-10">
                  <div>
                    <div className="flex items-center gap-3 mb-6">
                      <div className="w-12 h-12 bg-blue-500/10 text-blue-600 rounded-2xl flex items-center justify-center font-black">{property.region_code || property.state}</div>
                      <div>
                        <p className="text-xs text-slate-500 uppercase font-black tracking-widest">State Rules</p>
                        <p className="text-slate-800 font-bold">{jurisdictionInfo.name}</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      <div className="flex justify-between items-center p-4 rounded-xl bg-slate-100 border border-slate-200">
                        <span className="text-sm text-slate-600">Max Safe Stay</span>
                        <span className="text-sm font-black text-green-600">{jurisdictionInfo.maxSafeStayDays} Days</span>
                      </div>
                      <div className="flex justify-between items-center p-4 rounded-xl bg-slate-100 border border-slate-200">
                        <span className="text-sm text-slate-600">Primary Statute</span>
                        <span className="text-sm font-black text-blue-600">{jurisdictionInfo.keyStatute}</span>
                      </div>
                    </div>
                  </div>
                  <div className="p-6 rounded-2xl bg-slate-50 border border-slate-200">
                    <p className="text-xs text-slate-600 font-semibold uppercase tracking-wider mb-2">Stay documentation</p>
                    <p className="text-sm text-slate-600 leading-relaxed">DocuStay records authorized stay limits by region for status documentation and audit history. Max stay for this region: {jurisdictionInfo.maxSafeStayDays} days.</p>
                  </div>
                </div>
              </Card>
            </div>
          </div>
        )}

        {activeTab === 'guests' && (
          <Card className="overflow-hidden border-slate-200">
            <table className="w-full text-left">
              <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-black">
                <tr>
                  <th className="px-6 py-4 text-center w-20">Risk</th>
                  <th className="px-6 py-4">Guest</th>
                  <th className="px-6 py-4">Check-in</th>
                  <th className="px-6 py-4">Check-out</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {propertyStays.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">No guests at this property.</td>
                  </tr>
                ) : (
                  propertyStays.map((stay) => {
                    const overstay = isOverstayed(stay.stay_end_date);
                    return (
                      <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors group">
                        <td className="px-6 py-5 text-center">
                          <div className={`w-3 h-3 rounded-full mx-auto ${stay.risk_indicator === 'high' ? 'bg-red-500' : stay.risk_indicator === 'medium' ? 'bg-yellow-500' : 'bg-green-500'} shadow-[0_0_8px_rgba(34,197,94,0.6)]`}></div>
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-full bg-blue-600/20 text-blue-600 flex items-center justify-center font-black text-xs">{stay.guest_name.charAt(0)}</div>
                            <div>
                              <p className="text-sm font-bold text-slate-800">{stay.guest_name}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600 font-mono">{stay.stay_start_date}</td>
                        <td className="px-6 py-5 text-sm text-slate-600 font-mono">{stay.stay_end_date}</td>
                        <td className="px-6 py-5">
                          <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border ${overstay ? 'bg-red-50 text-red-600 border-red-200' : 'bg-green-50 text-green-600 border-green-200'}`}>
                            {overstay ? 'Overstayed' : 'Active'}
                          </span>
                        </td>
                        <td className="px-6 py-5 text-right"><Button variant="ghost" className="text-xs">Revoke</Button></td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </Card>
        )}

        {activeTab === 'documentation' && (
          <div className="max-w-3xl space-y-8">
            <h3 className="text-3xl font-black text-slate-800 tracking-tighter">Region documentation: {jurisdictionInfo.name}</h3>

            <section>
              <h4 className="text-lg font-bold text-slate-700 mb-4 uppercase tracking-wider">Authorized stay limits</h4>
              <p className="text-slate-600 leading-relaxed mb-4">DocuStay uses region-based stay limits for documentation and audit purposes. For {jurisdictionInfo.name}, the documented max stay is {jurisdictionInfo.maxSafeStayDays} days. All stays are recorded in the audit trail.</p>
            </section>

            <section className="p-6 rounded-xl border border-slate-200 bg-slate-50/50">
              <h4 className="text-lg font-bold text-slate-800 mb-4 uppercase tracking-wider">Stay status categories</h4>
              <div className="grid gap-4 text-sm">
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Within limit:</span>
                  <span className="text-slate-600">Stay duration under {jurisdictionInfo.maxSafeStayDays - jurisdictionInfo.warningDays} days. Full documentation active.</span>
                </div>
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Approaching limit:</span>
                  <span className="text-slate-600">Within {jurisdictionInfo.warningDays} days of documented max. Verification logs recorded.</span>
                </div>
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Past limit:</span>
                  <span className="text-slate-600">Stay exceeds documented max for {property?.state}. Status and actions are recorded in the audit trail.</span>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>

      {/* Remove property (soft-delete) - same behaviour as dashboard */}
      <Modal
        open={deleteConfirmOpen && !!property}
        title="Remove Property"
        onClose={() => !deleteSaving && (setDeleteConfirmOpen(false), setDeleteError(null))}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            Remove <span className="font-bold text-slate-800">{property?.name || address || 'this property'}</span> from your dashboard? This is only allowed when there is no active guest stay. The property will move to <strong>Inactive properties</strong> and will not appear when creating an invite. Data is kept for logs. You can reactivate it anytime.
          </p>
          {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => { setDeleteConfirmOpen(false); setDeleteError(null); }} disabled={deleteSaving} className="flex-1">Cancel</Button>
            <Button variant="danger" onClick={handleDeleteConfirm} disabled={deleteSaving} className="flex-1">
              {deleteSaving ? 'Removing…' : 'Remove Property'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Edit property modal */}
      <Modal
        open={editOpen && !!property}
        title="Edit Property"
        onClose={() => setEditOpen(false)}
        className="max-w-lg"
      >
        <div className="px-6 py-4 space-y-4">
          {editError && <p className="text-sm text-red-600">{editError}</p>}
          <Input
            label="Property name (optional)"
            name="property_name"
            value={editForm.property_name}
            onChange={(e) => setEditForm({ ...editForm, property_name: e.target.value })}
            placeholder="e.g. Miami Beach Condo"
          />
          <Input
            label="Street address"
            name="street_address"
            value={editForm.street_address}
            onChange={(e) => setEditForm({ ...editForm, street_address: e.target.value })}
            placeholder="123 Main St"
            required
          />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="City"
              name="city"
              value={editForm.city}
              onChange={(e) => setEditForm({ ...editForm, city: e.target.value })}
              placeholder="Miami"
              required
            />
            <Input
              label="State"
              name="state"
              value={editForm.state}
              onChange={(e) => setEditForm({ ...editForm, state: e.target.value })}
              placeholder="FL"
              required
            />
          </div>
          <Input
            label="ZIP code (optional)"
            name="zip_code"
            value={editForm.zip_code}
            onChange={(e) => setEditForm({ ...editForm, zip_code: e.target.value })}
            placeholder="33139"
          />
          <Input
            label="Region code (optional)"
            name="region_code"
            value={editForm.region_code}
            onChange={(e) => setEditForm({ ...editForm, region_code: e.target.value })}
            placeholder="e.g. FL, CA"
          />
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-2">Property type</label>
            <div className="flex flex-wrap gap-2">
              {PROPERTY_TYPES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setEditForm({ ...editForm, property_type: t.id })}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${editForm.property_type === t.id ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600 hover:text-slate-800'}`}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>
          <Input
            label="Bedrooms"
            name="bedrooms"
            value={editForm.bedrooms}
            onChange={(e) => setEditForm({ ...editForm, bedrooms: e.target.value })}
            options={[
              { value: '1', label: '1' },
              { value: '2', label: '2' },
              { value: '3', label: '3' },
              { value: '4', label: '4' },
              { value: '5', label: '5+' },
            ]}
          />
          <label className="flex items-center gap-3 cursor-pointer p-3 rounded-xl bg-slate-100 border border-slate-200">
            <input
              type="checkbox"
              checked={editForm.is_primary_residence}
              onChange={(e) => setEditForm({ ...editForm, is_primary_residence: e.target.checked })}
              className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600"
            />
            <span className="text-sm font-medium text-slate-800">Primary residence / owner-occupied</span>
          </label>
          <div className="flex gap-3 pt-2">
            <Button variant="outline" onClick={() => setEditOpen(false)} className="flex-1">Cancel</Button>
            <Button variant="primary" onClick={saveEdit} disabled={editSaving || !editForm.street_address?.trim() || !editForm.city?.trim() || !editForm.state?.trim()} className="flex-1">
              {editSaving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </div>
      </Modal>

          </>
        )}
      </main>

      {/* Modal placed outside loading conditional so it doesn't unmount during data refresh */}
      <InviteGuestModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        user={user}
        setLoading={setGlobalLoading}
        notify={notify}
        navigate={navigate}
        initialPropertyId={id}
      />
    </div>
  );
};
