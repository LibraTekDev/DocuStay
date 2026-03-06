import React, { useState } from 'react';
import { Card, Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApiGuest } from '../../services/api';
import AgreementSignModal, { type GuestInviteFormData } from '../../components/AgreementSignModal';

interface GuestSignupProps {
  initialInviteCode?: string;
  setPendingVerification?: (data: { userId: string; type: 'email'; generatedAt: string }) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onGuestLogin?: (user: any) => void;
}

const parseInviteCode = (raw: string): string => {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
};

const GuestSignup: React.FC<GuestSignupProps> = ({ initialInviteCode, setPendingVerification, navigate, setLoading, notify, onGuestLogin }) => {
  const [inviteAcceptModalOpen, setInviteAcceptModalOpen] = useState(false);
  const [inviteAcceptCode, setInviteAcceptCode] = useState('');
  const [pendingInviteFormData, setPendingInviteFormData] = useState<GuestInviteFormData | null>(null);
  const [formData, setFormData] = useState({
    invitation_link: (initialInviteCode || '').trim(),
    full_name: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
    permanent_address: '',
    permanent_city: '',
    permanent_state: '',
    permanent_zip: '',
    terms_agreed: false,
    privacy_agreed: false,
    guest_status_acknowledged: false,
    no_tenancy_acknowledged: false,
    vacate_acknowledged: false,
  });
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const showError = (message: string) => setErrorModal({ open: true, message });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const inviteCode = parseInviteCode(formData.invitation_link);
    const requiredFields = {
      full_name: formData.full_name.trim(),
      email: formData.email.trim(),
      phone: formData.phone.trim(),
      password: formData.password,
      confirm_password: formData.confirm_password,
      permanent_address: formData.permanent_address.trim(),
      permanent_city: formData.permanent_city.trim(),
      permanent_state: formData.permanent_state.trim(),
      permanent_zip: formData.permanent_zip.trim(),
    };
    const allFieldsFilled = Object.values(requiredFields).every(Boolean);
    const allCheckboxesChecked =
      formData.terms_agreed &&
      formData.privacy_agreed &&
      formData.guest_status_acknowledged &&
      formData.no_tenancy_acknowledged &&
      formData.vacate_acknowledged;

    if (!allFieldsFilled || !allCheckboxesChecked) {
      showError('Please fill in all required fields and accept all acknowledgments and agreements before continuing.');
      return;
    }

    setLoading(true);
    try {
      const result = await authApiGuest.register({
        invitation_id: inviteCode,
        invitation_code: inviteCode,
        full_name: formData.full_name,
        email: formData.email,
        phone: formData.phone,
        password: formData.password,
        confirm_password: formData.confirm_password,
        permanent_address: formData.permanent_address,
        permanent_city: formData.permanent_city,
        permanent_state: formData.permanent_state,
        permanent_zip: formData.permanent_zip,
        terms_agreed: formData.terms_agreed,
        privacy_agreed: formData.privacy_agreed,
        guest_status_acknowledged: formData.guest_status_acknowledged,
        no_tenancy_acknowledged: formData.no_tenancy_acknowledged,
        vacate_acknowledged: formData.vacate_acknowledged,
        agreement_signature_id: inviteCode ? 0 : null,
      });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        const d = result.data as any;
        // Store invite code BEFORE any navigation so it's available after email verification
        if (inviteCode) sessionStorage.setItem('docustay_pending_invite_code', inviteCode);
        if (d.verificationRequired && d.user_id && setPendingVerification) {
          notify('success', result.message || 'Check your email for the verification code.');
          setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
          navigate('verify');
          return;
        }
        notify('success', inviteCode ? 'Account created. Sign the agreement on your dashboard to accept the invitation.' : 'Account created successfully.');
        if (onGuestLogin) onGuestLogin(result.data);
        navigate('guest-dashboard');
      } else {
        showError(result.message || 'Registration failed. Please correct the errors and try again.');
      }
    } catch (err) {
      setLoading(false);
      const msg = (err as Error)?.message ?? 'Registration failed. Please try again.';
      showError(msg);
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.checked });
  };

  return (
    <HeroBackground className="flex-grow flex flex-col items-center py-8">
      <div className="w-full max-w-4xl rounded-xl overflow-hidden shadow-xl border border-gray-200/60 bg-white/40 backdrop-blur-sm">
        <div className="border-b border-gray-200/50 bg-white/30 px-8 py-6">
            <h1 className="text-xl font-semibold text-gray-900">Guest Signup</h1>
            <p className="text-gray-600 text-sm mt-1">Create your guest account.</p>
          </div>

          <div className="p-8 md:p-10 bg-gradient-to-b from-blue-100/35 via-blue-50/30 to-sky-100/25">
            <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-10 gap-y-6">
              <div className="md:col-span-2">
                <Input
                  label="Invitation link (optional)"
                  name="invitation_link"
                  value={formData.invitation_link}
                  onChange={e => setFormData({ ...formData, invitation_link: e.target.value })}
                  placeholder="Paste invitation link or code if you have one"
                />
                {(initialInviteCode || parseInviteCode(formData.invitation_link).length >= 5) && (
                  <div className="mt-3">
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full md:w-auto"
                      onClick={() => {
                        const code = initialInviteCode || parseInviteCode(formData.invitation_link);
                        if (code) {
                          setInviteAcceptCode(code);
                          setInviteAcceptModalOpen(true);
                        }
                      }}
                    >
                      Accept this invitation (property address + your details + sign)
                    </Button>
                  </div>
                )}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-blue-200 text-blue-800 flex items-center justify-center text-xs font-medium">1</span>
                  Guest Profile
                </h3>
                <div className="space-y-4">
                  <Input label="Full name" name="full_name" value={formData.full_name} onChange={e => setFormData({ ...formData, full_name: e.target.value })} required />
                  <Input label="Email Address" name="email" type="email" value={formData.email} onChange={e => setFormData({ ...formData, email: e.target.value })} required />
                  <Input label="Phone Number" name="phone" value={formData.phone} onChange={e => setFormData({ ...formData, phone: e.target.value })} placeholder="+1 555-000-0000" required />
                  <div className="grid grid-cols-2 gap-4">
                    <Input label="Password" name="password" type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} required />
                    <Input label="Confirm" name="confirm_password" type="password" value={formData.confirm_password} onChange={e => setFormData({ ...formData, confirm_password: e.target.value })} required />
                  </div>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-blue-200 text-blue-800 flex items-center justify-center text-xs font-medium">2</span>
                  Permanent Residence
                </h3>
                <p className="text-xs text-gray-500 mb-4">Required to confirm you have a primary residence elsewhere.</p>
                <div className="space-y-4">
                  <Input label="Street Address" name="permanent_address" value={formData.permanent_address} onChange={e => setFormData({ ...formData, permanent_address: e.target.value })} placeholder="Your actual home address" required />
                  <div className="grid grid-cols-2 gap-4">
                    <Input label="City" name="permanent_city" value={formData.permanent_city} onChange={e => setFormData({ ...formData, permanent_city: e.target.value })} required />
                    <Input label="State" name="permanent_state" value={formData.permanent_state} onChange={e => setFormData({ ...formData, permanent_state: e.target.value })} required />
                  </div>
                  <Input label="ZIP Code" name="permanent_zip" value={formData.permanent_zip} onChange={e => setFormData({ ...formData, permanent_zip: e.target.value })} required />
                </div>
              </div>

              <div className="md:col-span-2 mt-8">
                <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-blue-200 text-blue-800 flex items-center justify-center text-xs font-medium">3</span>
                  Stay acknowledgments
                </h3>
                <div className="grid md:grid-cols-3 gap-4 mb-6">
                  {[
                    { name: 'guest_status_acknowledged', label: 'Temporary Guest Status', desc: 'I acknowledge I am a guest only, not a tenant or resident.' },
                    { name: 'no_tenancy_acknowledged', label: 'Temporary stay', desc: 'I acknowledge this stay is temporary and does not grant tenancy.' },
                    { name: 'vacate_acknowledged', label: 'Agreement to Vacate', desc: 'I agree to vacate by the scheduled checkout date.' },
                  ].map(ack => (
                    <div key={ack.name} className={`p-4 rounded-lg border ${formData[ack.name as keyof typeof formData] ? 'bg-white border-gray-400' : 'bg-white border-gray-200'}`}>
                      <label className="flex flex-col gap-2 cursor-pointer h-full">
                        <div className="flex justify-between items-start">
                          <span className="text-sm font-medium text-gray-900">{ack.label}</span>
                          <input type="checkbox" name={ack.name} checked={!!formData[ack.name as keyof typeof formData]} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-gray-300 text-gray-900 focus:ring-gray-400 shrink-0 mt-0.5" required />
                        </div>
                        <p className="text-xs text-gray-500 leading-relaxed">{ack.desc}</p>
                      </label>
                    </div>
                  ))}
                </div>

                <div className="pt-6 border-t border-slate-200 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Agreements</p>
                  <label className="flex items-start gap-4 cursor-pointer p-4 rounded-xl border border-slate-200 bg-white/80 hover:border-slate-300 hover:bg-white transition-colors focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:border-blue-400">
                    <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0 shrink-0 mt-0.5 accent-blue-600" required />
                    <span className="text-sm text-slate-700 leading-relaxed">
                      I agree to the <a href="#" className="text-blue-600 font-semibold hover:text-blue-700 hover:underline underline-offset-2 transition-colors">Terms of Service</a>.
                    </span>
                  </label>
                  <label className="flex items-start gap-4 cursor-pointer p-4 rounded-xl border border-slate-200 bg-white/80 hover:border-slate-300 hover:bg-white transition-colors focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:border-blue-400">
                    <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0 shrink-0 mt-0.5 accent-blue-600" required />
                    <span className="text-sm text-slate-700 leading-relaxed">
                      I agree to the <a href="#" className="text-blue-600 font-semibold hover:text-blue-700 hover:underline underline-offset-2 transition-colors">Privacy Policy</a>.
                    </span>
                  </label>
                </div>

                <div className="mt-8 flex flex-col items-center gap-1">
                  <Button type="submit" className="w-full md:min-w-[200px] py-3">
                    Create Guest Account
                  </Button>
                  <p className="mt-4 text-center text-gray-500 text-sm">
                    Already have an account?{' '}
                    <button type="button" onClick={() => navigate('guest-login')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Login instead</button>
                  </p>
                  <p className="mt-1 text-center">
                    <button type="button" onClick={() => navigate('register')} className="text-blue-700 hover:text-blue-800 text-sm font-medium underline underline-offset-2">Sign up as Owner</button>
                  </p>
                </div>
              </div>
            </form>
          </div>
        </div>

      {inviteAcceptCode && (
        <AgreementSignModal
          open={inviteAcceptModalOpen}
          invitationCode={inviteAcceptCode}
          guestEmail=""
          guestFullName=""
          onClose={() => {
            setInviteAcceptModalOpen(false);
            setInviteAcceptCode('');
            setPendingInviteFormData(null);
          }}
          onSigned={async (signatureId) => {
            if (!pendingInviteFormData || !inviteAcceptCode) return;
            const code = inviteAcceptCode.trim().toUpperCase();
            setLoading(true);
            try {
              const result = await authApiGuest.register({
                ...pendingInviteFormData,
                invitation_id: code,
                invitation_code: code,
                agreement_signature_id: signatureId,
                guest_status_acknowledged: true,
                no_tenancy_acknowledged: true,
                vacate_acknowledged: true,
              });
              setLoading(false);
              setInviteAcceptModalOpen(false);
              setInviteAcceptCode('');
              setPendingInviteFormData(null);
              if (result.status === 'success' && result.data) {
                const d = result.data as any;
                if (d.verificationRequired && d.user_id && setPendingVerification) {
                  notify('success', result.message || 'Check your email for the verification code.');
                  setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
                  navigate('verify');
                  return;
                }
                notify('success', 'Registration successful!');
                if (onGuestLogin) onGuestLogin(result.data);
                navigate('guest-dashboard');
              } else {
                notify('error', result.message || 'Registration failed.');
              }
            } catch (err) {
              setLoading(false);
              notify('error', (err as Error)?.message || 'Registration failed.');
            }
          }}
          notify={notify}
          inviteAcceptMode
          onContinueToSign={(formData) => setPendingInviteFormData(formData)}
        />
      )}

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
    </HeroBackground>
  );
};

export default GuestSignup;
