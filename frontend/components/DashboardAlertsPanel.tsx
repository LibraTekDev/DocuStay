import React, { useState, useEffect, useCallback } from 'react';
import { dashboardApi, type DashboardAlertView, type OwnerAuditLogEntry } from '../services/api';

/** Dispatch this event to refresh alerts immediately (e.g. after revoke, confirm occupancy). */
export const DASHBOARD_ALERTS_REFRESH_EVENT = 'docustay-dashboard-alerts-refresh';

const POLL_INTERVAL_MS = 25_000; // 25 seconds – realtime without hammering the API

/** Ledger notification titles to hide in the notifications section. */
const HIDDEN_LEDGER_TITLES = new Set([
  'Invitation created (manager invite tenant)',
  'Onboarding invoice created',
  'Ownership proof uploaded',
  'ManagerInvited',
  'Property registered',
  'Invitation created',
  'User logged in'
]);

const severityStyles: Record<string, string> = {
  urgent: 'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info: 'bg-sky-50 border-sky-200 text-sky-800',
};

function formatAlertTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

/** Role for notifications: when set, the panel shows event ledger entries (same data as Event ledger tab) in notification format. */
export type NotificationsRole = 'owner' | 'property_manager' | 'tenant' | 'guest';

interface DashboardAlertsPanelProps {
  /** When set, notifications show event ledger data (same API as Event ledger) in notification format. Per-role and context mode (business/personal) use the same filtered data as the ledger. */
  role?: NotificationsRole;
  /** Max items to show (default 50). */
  limit?: number;
  /** Only for legacy alerts mode (when role is not set): show only unread. */
  unreadOnly?: boolean;
  /** Callback when an alert is marked read (legacy alerts mode only). */
  onAlertsChange?: () => void;
  /** Optional class for the container. */
  className?: string;
}

export const DashboardAlertsPanel: React.FC<DashboardAlertsPanelProps> = ({
  role,
  limit = 50,
  unreadOnly = false,
  onAlertsChange,
  className = '',
}) => {
  const [alerts, setAlerts] = useState<DashboardAlertView[]>([]);
  const [ledgerEntries, setLedgerEntries] = useState<OwnerAuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [markingId, setMarkingId] = useState<number | null>(null);

  const loadLedger = useCallback(async (silent = false) => {
    if (!role) return;
    if (!silent) setLoading(true);
    const fromTs = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
    try {
      let list: OwnerAuditLogEntry[] = [];
      if (role === 'owner') {
        list = await dashboardApi.ownerLogs({ from_ts: fromTs });
      } else if (role === 'property_manager') {
        list = await dashboardApi.managerLogs({ from_ts: fromTs });
      } else if (role === 'tenant') {
        list = await dashboardApi.tenantLogs({ from_ts: fromTs });
      } else if (role === 'guest') {
        list = await dashboardApi.guestLogs({ from_ts: fromTs });
      }
      setLedgerEntries(list.slice(0, limit));
    } catch {
      if (!silent) setLedgerEntries([]);
    } finally {
      setLoading(false);
    }
  }, [role, limit]);

  const loadAlerts = useCallback(async (silent = false) => {
    if (role) return;
    if (!silent) setLoading(true);
    try {
      const list = await dashboardApi.getAlerts({ limit, unread_only: unreadOnly });
      setAlerts(list);
    } catch {
      if (!silent) setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [limit, unreadOnly, role]);

  const load = useCallback(
    async (silent = false) => {
      if (role) {
        await loadLedger(silent);
      } else {
        await loadAlerts(silent);
      }
    },
    [role, loadLedger, loadAlerts]
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => load(true), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') load(true);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [load]);

  useEffect(() => {
    const onRefresh = () => load(true);
    window.addEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onRefresh);
  }, [load]);

  const markRead = async (alert: DashboardAlertView) => {
    if (alert.read_at) return;
    setMarkingId(alert.id);
    try {
      await dashboardApi.markAlertRead(alert.id);
      setAlerts((prev) => prev.map((a) => (a.id === alert.id ? { ...a, read_at: new Date().toISOString() } : a)));
      onAlertsChange?.();
    } finally {
      setMarkingId(null);
    }
  };

  const useLedger = Boolean(role);
  const filteredLedgerEntries = useLedger
    ? ledgerEntries.filter((e) => !HIDDEN_LEDGER_TITLES.has(e.title?.trim() ?? ''))
    : [];
  const items = useLedger ? filteredLedgerEntries : alerts;
  const unreadCount = useLedger ? 0 : alerts.filter((a) => !a.read_at).length;

  if (loading && items.length === 0) {
    return (
      <div className={`rounded-xl border border-slate-200 bg-white p-4 ${className}`}>
        <p className="text-slate-500 text-sm">Loading notifications…</p>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border border-slate-200 bg-white overflow-hidden ${className}`}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <span className="font-semibold text-slate-800 flex items-center gap-2">
          Notifications
          {!useLedger && unreadCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-amber-500 text-white text-xs font-bold">
              {unreadCount}
            </span>
          )}
        </span>
        <svg
          className={`w-5 h-5 text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded &&
        (useLedger ? (
          items.length === 0 ? (
            <div className="border-t border-slate-200 px-4 py-6 text-center">
              <p className="text-slate-500 text-sm">No recent activity.</p>
              <p className="text-slate-400 text-xs mt-1">Event ledger updates will appear here.</p>
            </div>
          ) : (
            <ul className="border-t border-slate-200 max-h-[320px] overflow-y-auto">
              {items.map((entry) => (
                <li key={entry.id} className="border-b border-slate-100 last:border-b-0 px-4 py-3">
                  <div className={`rounded-lg border p-3 ${severityStyles.info}`}>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm">{entry.title}</p>
                      <p className="text-sm mt-1 opacity-90">{entry.message}</p>
                      {(entry.property_name || entry.category) && (
                        <p className="text-xs mt-1 opacity-75">
                          {[entry.property_name, entry.category].filter(Boolean).join(' · ')}
                        </p>
                      )}
                      <p className="text-xs mt-2 opacity-75">{formatAlertTime(entry.created_at)}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : items.length === 0 ? (
          <div className="border-t border-slate-200 px-4 py-6 text-center">
            <p className="text-slate-500 text-sm">No new notifications.</p>
            <p className="text-slate-400 text-xs mt-1">Status updates and alerts will appear here.</p>
          </div>
        ) : (
          <ul className="border-t border-slate-200 max-h-[320px] overflow-y-auto">
            {alerts.map((alert) => (
              <li
                key={alert.id}
                className={`border-b border-slate-100 last:border-b-0 px-4 py-3 ${!alert.read_at ? 'bg-slate-50/50' : ''}`}
              >
                <div className={`rounded-lg border p-3 ${severityStyles[alert.severity] || severityStyles.info}`}>
                  <div className="flex justify-between items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm">{alert.title}</p>
                      <p className="text-sm mt-1 opacity-90">{alert.message}</p>
                      <p className="text-xs mt-2 opacity-75">{formatAlertTime(alert.created_at)}</p>
                    </div>
                    {!alert.read_at && (
                      <button
                        type="button"
                        onClick={() => markRead(alert)}
                        disabled={markingId === alert.id}
                        className="shrink-0 text-xs font-medium underline hover:no-underline disabled:opacity-50"
                      >
                        {markingId === alert.id ? '…' : 'Mark read'}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
};
