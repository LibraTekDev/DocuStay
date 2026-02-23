import React, { useState, useEffect, useRef } from 'react';
import { Modal, Input, Button } from './UI';
import { invitationsApi, propertiesApi } from '../services/api';
import { copyToClipboard } from '../utils/clipboard';
import type { UserSession } from '../types';

interface InviteGuestModalProps {
  open: boolean;
  onClose: () => void;
  user: UserSession | null;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onSuccess?: () => void;
  navigate?: (v: string) => void;
  /** When opening from a property page, preselect this property */
  initialPropertyId?: number | null;
}

export const InviteGuestModal: React.FC<InviteGuestModalProps> = ({
  open,
  onClose,
  user,
  setLoading,
  notify,
  onSuccess,
  navigate = (_: string) => {},
  initialPropertyId = null,
}) => {
  const [formData, setFormData] = useState({ guest_name: '', checkin_date: '', checkout_date: '' });
  const [inviteLink, setInviteLink] = useState('');
  const [showLinkResult, setShowLinkResult] = useState(false);
  const [properties, setProperties] = useState<Array<{ id: number; name: string | null; street: string; city: string; state: string; zip_code: string | null }>>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [propertiesLoading, setPropertiesLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const linkGeneratedRef = useRef(false);

  useEffect(() => {
    if (!open) {
      // Only reset when modal is closed AND we're not showing a link
      if (!linkGeneratedRef.current) {
        setShowLinkResult(false);
        setInviteLink('');
      }
      setFormData({ guest_name: '', checkin_date: '', checkout_date: '' });
      setPropertiesLoading(false);
      linkGeneratedRef.current = false;
      return;
    }
    // When opening from a property page, preselect that property immediately so the form is usable
    if (initialPropertyId != null) {
      setPropertyId(initialPropertyId);
    }
    setPropertiesLoading(true);
    propertiesApi
      .list()
      .then((list) => {
        setProperties(list);
        if (list.length > 0) {
          const preferred =
            initialPropertyId != null && list.some((p) => p.id === initialPropertyId)
              ? initialPropertyId
              : list[0].id;
          setPropertyId(preferred);
        } else if (initialPropertyId != null) {
          // List empty but we came from a property page: fetch this property so the form can show it
          propertiesApi
            .get(initialPropertyId)
            .then((prop) => {
              setProperties([prop]);
              setPropertyId(prop.id);
            })
            .catch(() => {})
            .finally(() => setPropertiesLoading(false));
          return;
        } else {
          setPropertyId(null);
        }
        setPropertiesLoading(false);
      })
      .catch(() => {
        if (initialPropertyId != null) {
          propertiesApi
            .get(initialPropertyId)
            .then((prop) => {
              setProperties([prop]);
              setPropertyId(prop.id);
            })
            .catch(() => {})
            .finally(() => setPropertiesLoading(false));
        } else {
          setPropertiesLoading(false);
        }
      });
  }, [open, initialPropertyId]);

  const selectedProperty = properties.find((p) => p.id === propertyId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!propertyId) {
      notify('error', 'Please add a property first, then create an invitation.');
      return;
    }
    if (!formData.checkin_date || !formData.checkout_date) {
      notify('error', 'Please select both start and end dates for the stay.');
      return;
    }
    if (new Date(formData.checkout_date) <= new Date(formData.checkin_date)) {
      notify('error', 'End date must be after start date.');
      return;
    }
    setSubmitting(true);
    try {
      const result = await invitationsApi.create({
        owner_id: user?.user_id ?? '',
        property_id: propertyId ?? undefined,
        guest_name: formData.guest_name,
        checkin_date: formData.checkin_date,
        checkout_date: formData.checkout_date,
      });
      if (result.status === 'success' && result.data?.invitation_code) {
        const link = `${window.location.origin}${window.location.pathname}#invite/${result.data.invitation_code}`;
        linkGeneratedRef.current = true;
        setInviteLink(link);
        setShowLinkResult(true);
        notify('success', 'Invitation link generated.');
        // Call onSuccess after state is set
        setTimeout(() => onSuccess?.(), 100);
      } else {
        notify('error', result.message || 'Invitation failed.');
      }
    } catch (err) {
      notify('error', (err as Error)?.message || 'Invitation failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(inviteLink);
    if (ok) notify('success', 'Link copied to clipboard.');
    else notify('error', 'Copy failed. Please copy the link manually.');
  };

  const handleClose = () => {
    linkGeneratedRef.current = false;
    setShowLinkResult(false);
    setInviteLink('');
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Invite a guest"
      className="max-w-lg"
      disableBackdropClose={submitting || showLinkResult}
    >
      <div className="p-6">
        {showLinkResult ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">Share this link with your guest. They will sign in or create an account, then sign the agreement on their dashboard.</p>
            <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">
              {inviteLink}
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={handleCopyLink} className="flex-1">Copy link</Button>
              <Button onClick={handleClose} className="flex-1">Done</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Property</label>
              {propertiesLoading && properties.length === 0 ? (
                <p className="text-sm text-slate-500 py-2">Loading property…</p>
              ) : properties.length === 0 ? (
                <div className="flex items-center gap-3 p-4 rounded-xl bg-amber-50 border border-amber-200">
                  <p className="text-sm text-amber-800">Add a property first.</p>
                  <Button variant="outline" type="button" onClick={() => { handleClose(); navigate('add-property'); }} className="shrink-0">Add property</Button>
                </div>
              ) : (
                <>
                  {properties.length > 1 ? (
                    <select
                      value={propertyId ?? ''}
                      onChange={(e) => setPropertyId(Number(e.target.value))}
                      className="w-full px-4 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm"
                    >
                      {properties.map((p) => (
                        <option key={p.id} value={p.id}>{p.name || `${p.city}, ${p.state}`}</option>
                      ))}
                    </select>
                  ) : (
                    <p className="text-sm text-slate-700 font-medium">{selectedProperty?.name || [selectedProperty?.street, selectedProperty?.city].filter(Boolean).join(', ') || 'Property'}</p>
                  )}
                </>
              )}
            </div>

            <Input
              label="Guest name"
              name="guest_name"
              value={formData.guest_name}
              onChange={(e) => setFormData({ ...formData, guest_name: e.target.value })}
              placeholder="Full name of your guest"
              required
            />

            <div className="grid grid-cols-2 gap-4">
              <Input label="Start date" name="checkin_date" type="date" value={formData.checkin_date} onChange={(e) => setFormData({ ...formData, checkin_date: e.target.value })} required />
              <Input label="End date" name="checkout_date" type="date" value={formData.checkout_date} onChange={(e) => setFormData({ ...formData, checkout_date: e.target.value })} required />
            </div>

            <div className="flex gap-3 pt-2">
              <Button variant="outline" type="button" onClick={handleClose} className="flex-1" disabled={submitting}>Cancel</Button>
              <Button type="submit" className="flex-1" disabled={properties.length === 0 || submitting}>
                {submitting ? 'Generating…' : 'Generate invite link'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Modal>
  );
};
