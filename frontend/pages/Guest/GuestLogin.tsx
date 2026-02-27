import React, { useState } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';

const parseInviteCode = (raw: string): string => {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
};

interface GuestLoginProps {
  inviteCode?: string;
  onLogin: (user: any) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
}

const PENDING_INVITE_STORAGE_KEY = 'docustay_pending_invite_code';

const GuestLogin: React.FC<GuestLoginProps> = ({ inviteCode: inviteCodeFromUrl, onLogin, setLoading, notify, navigate }) => {
  const [formData, setFormData] = useState({ email: '', password: '', invitation_link: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const inviteCode = inviteCodeFromUrl || parseInviteCode(formData.invitation_link);
  const showError = (message: string) => setErrorModal({ open: true, message });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const hasInviteLink = !!formData.invitation_link.trim();
    if (hasInviteLink && (!formData.email.trim() || !formData.password)) {
      showError('The invitation link is optional. Please enter your email and password to sign in.');
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.login(formData.email, formData.password, "guest");
      setLoading(false);
      if (result.status !== 'success' || !result.data) {
        showError(result.message || 'Login failed. Please check your email and password.');
        return;
      }
      if (inviteCode) {
        sessionStorage.setItem(PENDING_INVITE_STORAGE_KEY, inviteCode.trim().toUpperCase());
        notify('success', 'Signed in. You can sign the invitation agreement on your dashboard.');
      } else {
        notify('success', 'Signed in successfully.');
      }
      onLogin(result.data);
      navigate('guest-dashboard');
    } catch (err) {
      setLoading(false);
      const msg = (err as Error)?.message || 'Login failed.';
      if (inviteCode && (msg.toLowerCase().includes('invalid') || msg.toLowerCase().includes('password'))) {
        showError("No guest account found for this email and password. If you haven't registered yet, use \"Create account\" below, then sign the agreement on your dashboard.");
      } else {
        showError(msg);
      }
    }
  };

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-5xl flex rounded-xl overflow-hidden border border-gray-200/60 bg-white/40 backdrop-blur-sm min-h-[520px] shadow-xl">
        {/* Left: Info */}
        <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-blue-100/40 via-blue-50/40 to-sky-100/40 p-10 flex-col justify-center border-r border-blue-200/40">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">Guest login</h2>
          <p className="text-gray-600 text-sm mb-8">Access your stays and invitations.</p>
          <ul className="space-y-3 text-sm text-gray-600">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> View approved stays
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Accept invitations
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Stay documentation
            </li>
          </ul>
          {inviteCode && (
            <div className="mt-8 p-4 rounded-lg bg-white/70 border border-blue-300/80">
              <p className="text-sm text-gray-700">You have an invitation. Sign in and we’ll accept it.</p>
            </div>
          )}
        </div>

        {/* Right: Form */}
        <div className="w-full lg:w-1/2 bg-white/40 backdrop-blur-sm p-8 md:p-10 flex flex-col justify-center">
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-gray-900 mb-1 lg:hidden">Guest login</h1>
            <p className="text-gray-600 text-sm mb-6">
              {inviteCode ? 'Sign in to continue. You’ll sign the agreement on your dashboard.' : 'Enter your credentials.'}
            </p>

            <form onSubmit={handleSubmit} className="space-y-6">
              <Input
                label="Invitation link (optional)"
                name="invitation_link"
                value={formData.invitation_link}
                onChange={(e) => setFormData({ ...formData, invitation_link: e.target.value })}
                placeholder="Paste invitation link or code if you have one"
              />
              <Input
                label="Email"
                name="email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="you@example.com"
                required
              />
              <div className="relative">
                <Input
                  label="Password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-[34px] text-gray-400 hover:text-blue-700 transition-colors"
                >
                  {showPassword ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" /></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>

              <Button type="submit" className="w-full py-2.5">Sign in</Button>
            </form>

            <div className="mt-8 space-y-2 text-center text-gray-500 text-sm">
              <p>
                {inviteCode && (
                  <>
                    First time?{' '}
                    <button type="button" onClick={() => navigate(`guest-signup/${inviteCode}`)} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Create account</button>
                    <span className="mx-1.5 text-gray-300">·</span>
                  </>
                )}
                Don't have an account?{' '}
                <button type="button" onClick={() => navigate('guest-signup')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Guest Signup</button>
                <span className="mx-1.5 text-gray-300">·</span>
                <button type="button" onClick={() => navigate('register')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Sign up as Owner</button>
              </p>
            </div>
          </div>
        </div>
      </div>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
    </HeroBackground>
  );
};

export default GuestLogin;
export { PENDING_INVITE_STORAGE_KEY };
