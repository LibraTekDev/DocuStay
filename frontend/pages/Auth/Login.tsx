import React, { useState } from 'react';
import { Card, Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';

interface LoginProps {
  onLogin: (user: any) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
}

const Login: React.FC<LoginProps> = ({ onLogin, setLoading, notify, navigate }) => {
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const showError = (message: string) => setErrorModal({ open: true, message });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await authApi.login(formData.email, formData.password, "owner");
      setLoading(false);
      if (result.status === 'success' && result.data) {
        notify('success', 'Logged in successfully.');
        onLogin(result.data);
      } else {
        showError(result.message || 'Login failed. Please check your email and password.');
      }
    } catch (err) {
      setLoading(false);
      showError((err as Error)?.message || 'Login failed. Please try again.');
    }
  };

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-5xl flex rounded-xl overflow-hidden border border-gray-200/60 bg-white/40 backdrop-blur-sm min-h-[520px] shadow-xl">
        {/* Left: Simple info */}
        <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-blue-100/40 via-blue-50/40 to-sky-100/40 p-10 flex-col justify-center border-r border-blue-200/40">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">Owner login</h2>
          <p className="text-gray-600 text-sm mb-8">Manage properties, invitations, and stays in one place.</p>
          <ul className="space-y-3 text-sm text-gray-600">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Jurisdiction-aware agreements
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Guest verification
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600" /> Stay documentation
            </li>
          </ul>
        </div>

        {/* Right: Form */}
        <div className="w-full lg:w-1/2 bg-white/40 backdrop-blur-sm p-8 md:p-10 flex flex-col justify-center">
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-gray-900 mb-1 lg:hidden">Owner login</h1>
            <p className="text-gray-600 text-sm mb-6">Sign in to your account.</p>
            
            <form onSubmit={handleSubmit} className="space-y-6">
              <Input 
                label="Work Email" 
                name="email" 
                type="email" 
                value={formData.email} 
                onChange={e => setFormData({ ...formData, email: e.target.value })} 
                placeholder="name@company.com"
                required
              />
              <div className="relative">
                <Input 
                  label="Password" 
                  name="password" 
                  type={showPassword ? "text" : "password"} 
                  value={formData.password} 
                  onChange={e => setFormData({ ...formData, password: e.target.value })} 
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
              
              <div className="flex items-center justify-between text-sm">
                <label className="flex items-center gap-2 cursor-pointer text-gray-600">
                  <input type="checkbox" className="w-4 h-4 rounded border-gray-300 text-gray-900 focus:ring-gray-400" />
                  Remember me
                </label>
                <a href="#" className="text-blue-700 hover:text-blue-800 font-medium">Forgot password?</a>
              </div>
              
              <Button type="submit" className="w-full py-2.5">Sign in</Button>
            </form>

            <div className="mt-8 space-y-2 text-center text-gray-500 text-sm">
              <p>
                Don't have an account?{' '}
                <button type="button" onClick={() => navigate('register')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Register as Owner</button>
                <span className="mx-1.5 text-gray-300">·</span>
                <button type="button" onClick={() => navigate('guest-signup')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Guest Signup</button>
              </p>
              <p>
                <button type="button" onClick={() => navigate('guest-login')} className="text-blue-700 hover:text-blue-800 underline underline-offset-2">Guest login</button>
                <span className="mx-1.5 text-gray-300">·</span>
                <button type="button" onClick={() => navigate('guest-signup')} className="text-blue-700 hover:text-blue-800 underline underline-offset-2">Enter invitation link</button>
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

export default Login;
