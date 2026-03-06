import React, { useState } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';

interface AdminLoginProps {
  onLogin: (user: any) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
}

const AdminLogin: React.FC<AdminLoginProps> = ({ onLogin, setLoading, notify, navigate }) => {
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const showError = (message: string) => setErrorModal({ open: true, message });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = formData.email.trim();
    const password = formData.password;
    if (!email || !password) {
      showError('Please enter your email and password.');
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.login(email, password, 'admin');
      setLoading(false);
      if (result.status === 'success' && result.data) {
        if (result.data.user_type === 'ADMIN') {
          notify('success', 'Signed in.');
          onLogin(result.data);
          navigate('admin');
        } else {
          showError('This account is not an admin. Use Owner Login or Guest Login.');
        }
      } else {
        showError(result.message || 'Login failed. Please check your email and password.');
      }
    } catch (err) {
      setLoading(false);
      showError((err as Error)?.message ?? 'Login failed. Please try again.');
    }
  };

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-5xl flex rounded-xl overflow-hidden border border-gray-200/60 bg-white/40 backdrop-blur-sm min-h-[520px] shadow-xl">
        {/* Left: Simple info */}
        <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-blue-100/40 via-blue-50/40 to-sky-100/40 p-10 flex-col justify-center border-r border-blue-200/40">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">Admin login</h2>
          <p className="text-gray-600 text-sm mb-8">Internal access to users, audit logs, and platform data.</p>
          <ul className="space-y-3 text-sm text-gray-600">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Users & roles
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Audit logs
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Properties, stays & invitations
            </li>
          </ul>
        </div>

        {/* Right: Form */}
        <div className="w-full lg:w-1/2 bg-white/40 backdrop-blur-sm p-8 md:p-10 flex flex-col justify-center">
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-gray-900 mb-1 lg:hidden">Admin login</h1>
            <p className="text-gray-600 text-sm mb-6">Sign in with an admin account.</p>

            <form onSubmit={handleSubmit} className="space-y-6">
              <Input
                label="Email"
                name="email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="admin@example.com"
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
                  className="absolute right-3 top-[34px] text-gray-400 hover:text-gray-600 transition-colors"
                >
                  {showPassword ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18"></path></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                  )}
                </button>
              </div>

              <Button type="submit" className="w-full py-2.5">Sign in</Button>
            </form>

            <div className="mt-8 text-center text-gray-500 text-sm">
              <button type="button" onClick={() => navigate('login')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">
                Back to main login
              </button>
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

export default AdminLogin;
