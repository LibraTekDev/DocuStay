import React, { useState, useEffect } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';
import { getOwnerSignupErrorFriendly } from '../../utils/ownerSignupErrors';
import { validatePhone } from '../../utils/validatePhone';

interface Props {
  setPendingVerification: (data: any) => void;
  onLogin?: (user: any) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}

const RegisterOwner: React.FC<Props> = ({ setPendingVerification, onLogin, navigate, setLoading, notify }) => {
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
    country: 'USA',
    state: '',
    city: '',
    terms_agreed: false,
    privacy_agreed: false
  });
  const [errors, setErrors] = useState<any>({});
  const [passwordStrength, setPasswordStrength] = useState(0);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  useEffect(() => {
    let strength = 0;
    if (formData.password.length >= 8) strength++;
    if (/[A-Z]/.test(formData.password)) strength++;
    if (/[0-9]/.test(formData.password)) strength++;
    if (/[^A-Za-z0-9]/.test(formData.password)) strength++;
    setPasswordStrength(strength);
  }, [formData.password]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    const phoneCheck = validatePhone(formData.phone);
    if (!phoneCheck.valid) {
      setErrors((prev: any) => ({ ...prev, phone: { error: phoneCheck.error } }));
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.register({ ...formData });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        // Always go to email verification when backend returns user_id (pending signup).
        if ('user_id' in result.data) {
          setPendingVerification({
            userId: result.data.user_id,
            type: 'email',
            generatedAt: new Date().toISOString()
          });
          notify('success', 'Check your email for the verification code.');
          navigate('verify');
        } else if (result.data && 'token' in result.data && onLogin) {
          // Continue onboarding (existing incomplete owner).
          notify('success', 'Welcome back. Next: verify your identity.');
          onLogin(result.data);
          navigate('onboarding/identity');
        }
      } else {
        setErrors(result.validation || {});
        const friendly = getOwnerSignupErrorFriendly(result.message);
        setErrorModal({ open: true, message: friendly.message });
      }
    } catch (err) {
      setLoading(false);
      const friendly = getOwnerSignupErrorFriendly((err as Error)?.message);
      setErrorModal({ open: true, message: friendly.message });
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.checked });
  };

  return (
    <HeroBackground className="flex-grow flex flex-col items-center justify-center">
      <div className="w-full max-w-6xl flex rounded-xl overflow-hidden border border-gray-200/60 bg-white/40 backdrop-blur-sm shadow-xl">
        {/* Left: Info */}
        <div className="hidden lg:flex w-2/5 bg-gradient-to-br from-blue-100/40 via-blue-50/40 to-sky-100/40 p-10 flex-col justify-center border-r border-blue-200/40">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">Create owner account</h2>
          <p className="text-gray-600 text-sm mb-8">Manage temporary stays with clear agreements and verification.</p>
          <ul className="space-y-4 text-sm">
            {[
              { title: "Legal Shield", desc: "Agreements that waive squatter claims." },
              { title: "Guest Verification", desc: "Know who is entering your property." },
              { title: "Stay Tracking", desc: "Alerts before legal time limits." },
            ].map(f => (
              <li key={f.title} className="flex gap-3">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-600 mt-1.5 shrink-0" />
                <div>
                  <span className="font-medium text-gray-900">{f.title}</span>
                  <span className="text-gray-600"> — {f.desc}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Right: Form — no inner scroll; page scrolls as a whole */}
        <div className="w-full lg:w-3/5 bg-white/40 backdrop-blur-sm pt-6 px-6 pb-6 md:pt-8 md:px-10 md:pb-8 flex flex-col justify-center min-h-0">
          <div className="max-w-2xl mx-auto w-full">
            <div className="flex justify-between items-center mb-6">
              <h1 className="text-xl font-semibold text-gray-900">Create Owner Account</h1>
              <span className="text-xs text-gray-500 uppercase tracking-wide">Step 1 of 3 · Identity & POA next</span>
            </div>
            
            <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-6 gap-y-4">
              <div className="md:col-span-2">
                <Input 
                  label="Full Legal Name" 
                  name="full_name" 
                  value={formData.full_name} 
                  onChange={e => setFormData({ ...formData, full_name: e.target.value })} 
                  error={errors.full_name?.error}
                  placeholder="John D. Miller"
                  required
                />
              </div>
              <Input 
                label="Work Email" 
                name="email" 
                type="email" 
                value={formData.email} 
                onChange={e => setFormData({ ...formData, email: e.target.value })} 
                error={errors.email?.error}
                placeholder="john@example.com"
                required
              />
              <Input 
                label="Phone Number" 
                name="phone" 
                value={formData.phone} 
                onChange={e => setFormData({ ...formData, phone: e.target.value })} 
                error={errors.phone?.error}
                placeholder="+1 (555) 000-0000"
                required
              />
              
              <div className="relative">
                <Input 
                  label="Password" 
                  name="password" 
                  type="password" 
                  value={formData.password} 
                  onChange={e => setFormData({ ...formData, password: e.target.value })} 
                  error={errors.password?.error}
                  placeholder="••••••••"
                  required
                />
                <div className="flex gap-1 mt-1 px-1">
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${passwordStrength >= i ? (passwordStrength <= 2 ? 'bg-amber-500' : 'bg-green-600') : 'bg-gray-200'}`}></div>
                  ))}
                </div>
                <p className="text-xs text-gray-500 mt-1.5">At least 8 characters with numbers and symbols</p>
              </div>
              
              <Input 
                label="Confirm Password" 
                name="confirm_password" 
                type="password" 
                value={formData.confirm_password} 
                onChange={e => setFormData({ ...formData, confirm_password: e.target.value })} 
                error={errors.password_match?.error}
                placeholder="••••••••"
                required
              />

              <Input 
                label="Primary State" 
                name="state" 
                value={formData.state} 
                onChange={e => setFormData({ ...formData, state: e.target.value })} 
                options={[
                  { value: 'NY', label: 'New York' },
                  { value: 'FL', label: 'Florida' },
                  { value: 'CA', label: 'California' },
                  { value: 'TX', label: 'Texas' },
                  { value: 'WA', label: 'Washington' }
                ]}
                required
              />
              <Input 
                label="City" 
                name="city" 
                value={formData.city} 
                onChange={e => setFormData({ ...formData, city: e.target.value })} 
                placeholder="Miami"
                required
              />
              
              <div className={`md:col-span-2 space-y-3 mt-2 p-4 rounded-lg bg-gradient-to-r from-blue-50 to-sky-50/80 border ${errors.terms?.error || errors.privacy?.error ? 'border-red-300' : 'border-blue-200'}`}>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-gray-300 text-blue-700 focus:ring-blue-600 shrink-0 mt-0.5" />
                  <span className="text-sm text-gray-600 leading-relaxed">I agree to the <a href="#" className="text-blue-700 font-medium hover:underline">Terms of Service</a> and the platform's specific protocols for preventing squatter tenancy rights.</span>
                </label>
                {errors.terms?.error && <p className="text-xs text-red-500 pl-8">{errors.terms.error}</p>}
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-gray-300 text-blue-700 focus:ring-blue-600 shrink-0 mt-0.5" />
                  <span className="text-sm text-gray-600">I agree to the processing of my data according to the <a href="#" className="text-blue-700 font-medium hover:underline">Privacy Policy</a>.</span>
                </label>
                {errors.privacy?.error && <p className="text-xs text-red-500 pl-8">{errors.privacy.error}</p>}
              </div>

              <div className="md:col-span-2 mt-6 flex flex-col items-center">
                <p className="text-sm text-slate-500 mb-2">After signup you will verify your identity, then sign the Master POA.</p>
                <Button type="submit" className="w-full md:min-w-[200px] py-3">
                  Create Secure Account
                </Button>
                <p className="mt-4 text-center text-gray-500 text-sm">
                  Already have an account? <button type="button" onClick={() => navigate('login')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Login instead</button>
                </p>
                <p className="mt-1 text-center">
                  <button type="button" onClick={() => navigate('guest-signup')} className="text-blue-700 hover:text-blue-800 text-sm font-medium underline underline-offset-2">Sign up as Guest</button>
                </p>
              </div>
            </form>
          </div>
        </div>
      </div>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
        actionLabel={errorModal.message.toLowerCase().includes("already registered") ? "Go to login" : undefined}
        onAction={errorModal.message.toLowerCase().includes("already registered") ? () => navigate("login") : undefined}
      />
    </HeroBackground>
  );
};

export default RegisterOwner;
