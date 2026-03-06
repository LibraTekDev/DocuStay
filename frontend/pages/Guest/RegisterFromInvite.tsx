
import React, { useState, useEffect } from 'react';
import { Card, Input, Button } from '../../components/UI';
import { authApiGuest, invitationsApi, type InvitationDetails } from '../../services/api';
import { UserSession } from '../../types';
import AgreementSignModal from '../../components/AgreementSignModal';

interface Props {
  invitationId: string;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  setPendingVerification: (data: any) => void;
  onGuestLogin?: (user: UserSession) => void;
}

function formatDate(s: string | undefined): string {
  if (!s) return '—';
  const d = new Date(s);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

const RegisterFromInvite: React.FC<Props> = ({ invitationId, navigate, setLoading, notify, setPendingVerification, onGuestLogin }) => {
  const [inviteDetails, setInviteDetails] = useState<InvitationDetails | null>(null);
  const [inviteLoading, setInviteLoading] = useState(true);
  const normalizedCode = invitationId.trim().toUpperCase();
  const [agreementOpen, setAgreementOpen] = useState(false);
  const [agreementSignatureId, setAgreementSignatureId] = useState<number | null>(null);
  const [formData, setFormData] = useState({
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
    vacate_acknowledged: false
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const requiredFilled =
      formData.full_name.trim() &&
      formData.email.trim() &&
      formData.phone.trim() &&
      formData.password &&
      formData.confirm_password &&
      formData.permanent_address.trim() &&
      formData.permanent_city.trim() &&
      formData.permanent_state.trim() &&
      formData.permanent_zip.trim();
    const allCheckboxesChecked =
      formData.terms_agreed &&
      formData.privacy_agreed &&
      formData.guest_status_acknowledged &&
      formData.no_tenancy_acknowledged &&
      formData.vacate_acknowledged;
    if (!requiredFilled || !allCheckboxesChecked) {
      notify('error', 'Please fill in all required fields and accept all acknowledgments and agreements before continuing.');
      return;
    }
    if (!agreementSignatureId) {
      notify('error', 'You must review and sign the agreement to continue.');
      setAgreementOpen(true);
      return;
    }
    setLoading(true);
    try {
      const result = await authApiGuest.register({
        invitation_id: normalizedCode,
        invitation_code: normalizedCode,
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
        agreement_signature_id: agreementSignatureId,
      });
      setLoading(false);
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
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.checked });
  };

  useEffect(() => {
    if (!normalizedCode) {
      setInviteLoading(false);
      setInviteDetails({ valid: false });
      return;
    }
    invitationsApi.getDetails(normalizedCode)
      .then((d) => {
        setInviteDetails(d);
        if (!d.valid && d.expired) notify('error', 'This invitation has expired and can’t be used.');
        else if (!d.valid && d.used) notify('error', 'This invitation link has already been used.');
        else if (!d.valid) notify('error', 'Invalid invitation code.');
      })
      .catch(() => {
        setInviteDetails({ valid: false });
        notify('error', 'Invalid or expired invitation code.');
      })
      .finally(() => setInviteLoading(false));
  }, [normalizedCode, notify]);

  if (inviteLoading) {
    return (
      <div className="max-w-4xl mx-auto py-12">
        <p className="text-gray-400">Loading invitation…</p>
      </div>
    );
  }
  if (inviteDetails && !inviteDetails.valid) {
    return (
      <div className="max-w-4xl mx-auto py-12">
        <Card className="p-8 text-center">
          <p className="text-slate-600 mb-4">
            {inviteDetails.expired
              ? 'This invitation has expired (it was not accepted in time). Please ask your host for a new invitation.'
              : inviteDetails.used
                ? 'This invitation link has already been used and cannot be used again.'
                : 'This invitation could not be loaded.'}
          </p>
          <button onClick={() => navigate('guest-signup')} className="text-blue-600 hover:underline font-medium">Enter a different code</button>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto py-12">
      <Card className="p-0 overflow-hidden">
        {/* Invitation Banner */}
        <div className="bg-gradient-to-r from-blue-900 to-indigo-900 p-8 md:p-12 text-white relative">
           <div className="absolute top-0 right-0 w-64 h-full bg-blue-500/10 blur-[60px] rounded-full"></div>
           <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-8">
              <div>
                 <span className="inline-block px-3 py-1 rounded-full bg-blue-500/20 text-blue-400 text-xs font-bold uppercase tracking-widest mb-4">Official Invitation</span>
                 <h1 className="text-4xl font-extrabold mb-2">You're Invited to Stay.</h1>
                 <p className="text-blue-200 text-lg">Hosted by <span className="text-white font-bold">{inviteDetails?.host_name || 'Your host'}</span></p>
              </div>
              <div className="bg-white/10 backdrop-blur-md rounded-2xl p-6 border border-white/10 min-w-[280px]">
                 <div className="flex items-center gap-3 mb-4">
                    <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    <span className="font-bold">{inviteDetails?.property_name || 'Property'}</span>
                 </div>
                 <div className="grid grid-cols-2 gap-4 text-xs font-medium text-blue-200">
                    <div>
                       <p className="uppercase tracking-widest mb-1 opacity-60">Check-in</p>
                       <p className="text-white text-sm">{formatDate(inviteDetails?.stay_start_date)}</p>
                    </div>
                    <div>
                       <p className="uppercase tracking-widest mb-1 opacity-60">Check-out</p>
                       <p className="text-white text-sm">{formatDate(inviteDetails?.stay_end_date)}</p>
                    </div>
                 </div>
              </div>
           </div>
        </div>

        <div className="p-8 md:p-12 bg-slate-50">
          <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-12 gap-y-2">
            <div>
              <h3 className="text-2xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-sm font-bold">1</div>
                 Guest Profile
              </h3>
              <div className="space-y-4">
                <Input label="Full name" name="full_name" value={formData.full_name} onChange={e => setFormData({...formData, full_name: e.target.value})} required />
                <Input label="Email Address" name="email" type="email" value={formData.email} onChange={e => setFormData({...formData, email: e.target.value})} required />
                <Input label="Phone Number" name="phone" value={formData.phone} onChange={e => setFormData({...formData, phone: e.target.value})} placeholder="+1 555-000-0000" required />
                <div className="grid grid-cols-2 gap-4">
                   <Input label="Password" name="password" type="password" value={formData.password} onChange={e => setFormData({...formData, password: e.target.value})} required />
                   <Input label="Confirm" name="confirm_password" type="password" value={formData.confirm_password} onChange={e => setFormData({...formData, confirm_password: e.target.value})} required />
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-2xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-sm font-bold">2</div>
                 Permanent Residence
              </h3>
              <p className="text-xs text-slate-500 mb-6 italic">Required to confirm you have a primary residence elsewhere and are not seeking tenancy.</p>
              <div className="space-y-4">
                <Input label="Street Address" name="permanent_address" value={formData.permanent_address} onChange={e => setFormData({...formData, permanent_address: e.target.value})} placeholder="Your actual home address" required />
                <div className="grid grid-cols-2 gap-4">
                   <Input label="City" name="permanent_city" value={formData.permanent_city} onChange={e => setFormData({...formData, permanent_city: e.target.value})} required />
                   <Input label="State" name="permanent_state" value={formData.permanent_state} onChange={e => setFormData({...formData, permanent_state: e.target.value})} required />
                </div>
                <Input label="ZIP Code" name="permanent_zip" value={formData.permanent_zip} onChange={e => setFormData({...formData, permanent_zip: e.target.value})} required />
              </div>
            </div>

            <div className="md:col-span-2 mt-12">
              <h3 className="text-2xl font-bold text-slate-800 mb-8 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-sm font-bold">3</div>
                 Stay acknowledgments
              </h3>
              
              <div className="grid md:grid-cols-3 gap-6 mb-12">
                {[
                  { name: 'guest_status_acknowledged', label: 'Temporary Guest Status', desc: 'I acknowledge I am a guest only, not a tenant or resident.' },
                  { name: 'no_tenancy_acknowledged', label: 'Temporary stay', desc: 'I acknowledge this stay is temporary and does not grant tenancy.' },
                  { name: 'vacate_acknowledged', label: 'Agreement to Vacate', desc: 'I agree to vacate the property by the scheduled checkout date.' }
                ].map(ack => (
                  <div key={ack.name} className={`p-6 rounded-3xl border transition-all duration-300 ${formData[ack.name] ? 'bg-blue-50 border-blue-300 shadow-md' : 'bg-white border-slate-200'}`}>
                    <label className="flex flex-col gap-4 cursor-pointer h-full">
                       <div className="flex justify-between items-start">
                          <span className={`text-sm font-bold ${formData[ack.name] ? 'text-blue-700' : 'text-slate-700'}`}>{ack.label}</span>
                          <input 
                            type="checkbox" 
                            name={ack.name} 
                            checked={formData[ack.name]} 
                            onChange={handleCheckboxChange} 
                            className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0 mt-0.5" 
                            required 
                          />
                       </div>
                       <p className="text-xs text-slate-500 leading-relaxed">{ack.desc}</p>
                    </label>
                  </div>
                ))}
              </div>

              <div className="pt-8 border-t border-slate-200 space-y-4">
                <label className="flex items-start gap-3 cursor-pointer group w-full max-w-2xl">
                  <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0 mt-0.5" required />
                  <span className="text-sm text-slate-600 group-hover:text-slate-800 pt-0.5">I agree to the <a href="#" className="text-blue-600 font-semibold hover:underline">Terms of Service</a>.</span>
                </label>
                <label className="flex items-start gap-3 cursor-pointer group w-full max-w-2xl">
                  <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0 mt-0.5" required />
                  <span className="text-sm text-slate-600 group-hover:text-slate-800 pt-0.5">I agree to the <a href="#" className="text-blue-600 font-semibold hover:underline">Privacy Policy</a>.</span>
                </label>

                <div className="flex flex-col items-center gap-3 mt-6 text-center">
                  <Button
                    type="button"
                    variant={agreementSignatureId ? 'secondary' : 'outline'}
                    className="w-full max-w-xl py-4"
                    onClick={() => setAgreementOpen(true)}
                  >
                    {agreementSignatureId ? 'Agreement Signed ✓ (View)' : 'Review & Sign Agreement (Required)'}
                  </Button>
                  {!agreementSignatureId ? (
                    <p className="text-xs text-slate-500">Your signup cannot be completed until the agreement is signed.</p>
                  ) : null}
                </div>
                <div className="flex flex-col items-center mt-6">
                  <Button type="submit" disabled={!agreementSignatureId} className="w-full md:w-auto px-20 py-5 text-xl">Create Account & Accept Invitation</Button>
                  <p className="text-sm text-slate-600 mt-6">
                    Already have an account?{' '}
                    <button type="button" onClick={() => navigate(`guest-login/${normalizedCode}`)} className="text-blue-600 font-semibold hover:text-blue-700 underline underline-offset-4">
                      Sign in
                    </button>
                  </p>
                </div>
              </div>
            </div>
          </form>
        </div>
      </Card>

      <AgreementSignModal
        open={agreementOpen}
        invitationCode={normalizedCode}
        guestEmail={formData.email}
        guestFullName={formData.full_name}
        onClose={() => setAgreementOpen(false)}
        onSigned={(id) => setAgreementSignatureId(id)}
        notify={notify}
      />
    </div>
  );
};

export default RegisterFromInvite;
