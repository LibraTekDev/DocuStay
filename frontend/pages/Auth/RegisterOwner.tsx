import React, { useState, useEffect } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';
import { getOwnerSignupErrorFriendly } from '../../utils/ownerSignupErrors';
import { validatePhone, sanitizePhoneInput } from '../../utils/validatePhone';

interface Props {
  setPendingVerification: (data: any) => void;
  onLogin?: (user: any) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}

const RegisterOwner: React.FC<Props> = ({ setPendingVerification, onLogin, navigate, setLoading, notify }) => {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
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
    const newErrors: Record<string, { error: string }> = {};
    if (!formData.first_name.trim()) newErrors.first_name = { error: 'First name is required.' };
    if (!formData.last_name.trim()) newErrors.last_name = { error: 'Last name is required.' };
    if (!formData.email.trim()) newErrors.email = { error: 'Email is required.' };
    const phoneCheck = validatePhone(formData.phone);
    if (!phoneCheck.valid) newErrors.phone = { error: phoneCheck.error };
    if (!formData.password) newErrors.password = { error: 'Password is required.' };
    if (formData.password && formData.password.length < 8) newErrors.password = { error: 'Password must be at least 8 characters.' };
    if (formData.password !== formData.confirm_password) newErrors.password_match = { error: 'Passwords do not match.' };
    if (!formData.state) newErrors.state = { error: 'Primary state is required.' };
    if (!formData.city.trim()) newErrors.city = { error: 'City is required.' };
    if (!formData.terms_agreed) newErrors.terms = { error: 'You must agree to the Terms of Service.' };
    if (!formData.privacy_agreed) newErrors.privacy = { error: 'You must agree to the Privacy Policy.' };
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setLoading(true);
    try {
      const fullName = `${formData.first_name} ${formData.last_name}`.trim();
      const result = await authApi.register({
        account_type: 'individual',
        first_name: formData.first_name,
        last_name: formData.last_name,
        full_name: fullName,
        email: formData.email,
        phone: formData.phone,
        password: formData.password,
        confirm_password: formData.confirm_password,
        country: formData.country,
        state: formData.state,
        city: formData.city,
        terms_agreed: formData.terms_agreed,
        privacy_agreed: formData.privacy_agreed,
      });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        if ('user_id' in result.data) {
          setPendingVerification({
            userId: result.data.user_id,
            type: 'email',
            email: formData.email,
          });
          navigate('onboarding/identity-complete');
        } else if (result.data && 'access_token' in result.data) {
          onLogin?.(result.data as any);
        }
      }
    } catch (err) {
      setLoading(false);
      const friendly = getOwnerSignupErrorFriendly((err as Error)?.message);
      notify('error', friendly.message);
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, checked } = e.target;
    setFormData((prev) => ({ ...prev, [name]: checked }));
  };

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-5xl flex rounded-xl overflow-hidden border border-gray-200/60 bg-white/40 backdrop-blur-sm min-h-[520px] shadow-xl">
        <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-blue-100/40 via-blue-50/40 to-sky-100/40 p-10 flex-col justify-center border-r border-blue-200/40">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">Create Owner Account</h2>
          <p className="text-gray-600 text-sm mb-8">
            Register to manage your properties, invite guests, and document temporary stays.
          </p>
        </div>
        <div className="w-full lg:w-1/2 bg-white/40 backdrop-blur-sm p-8 md:p-10 flex flex-col justify-center">
          <div className="max-w-md mx-auto w-full">
            <h1 className="text-xl font-semibold text-gray-900 mb-4">Create Owner Account</h1>

            <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-6 gap-y-4">
              <Input
                label="First Name"
                name="first_name"
                value={formData.first_name}
                onChange={e => setFormData({ ...formData, first_name: e.target.value })}
                error={errors.first_name?.error}
                placeholder="John"
                required
              />
              <Input
                label="Last Name"
                name="last_name"
                value={formData.last_name}
                onChange={e => setFormData({ ...formData, last_name: e.target.value })}
                error={errors.last_name?.error}
                placeholder="Miller"
                required
              />
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
                onChange={e => setFormData({ ...formData, phone: sanitizePhoneInput(e.target.value) })}
                error={errors.phone?.error}
                placeholder="+15551234567 or 5551234567"
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
                  <span className="text-sm text-gray-600 leading-relaxed">I agree to the <a href="#" className="text-blue-700 font-medium hover:underline">Terms of Service</a> and the platform's documentation and authorization protocols for temporary stays.</span>
                </label>
                {errors.terms?.error && <p className="text-xs text-red-500 pl-8">{errors.terms.error}</p>}
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-gray-300 text-blue-700 focus:ring-blue-600 shrink-0 mt-0.5" />
                  <span className="text-sm text-gray-600">I agree to the processing of my data according to the <a href="#" className="text-blue-700 font-medium hover:underline">Privacy Policy</a>.</span>
                </label>
                {errors.privacy?.error && <p className="text-xs text-red-500 pl-8">{errors.privacy.error}</p>}
              </div>
              <div className="md:col-span-2 mt-6 flex flex-col items-center">
                <p className="text-sm text-slate-500 mb-2">After signup you'll complete verification and authorization.</p>
                <Button type="submit" className="w-full md:min-w-[200px] py-3">
                  Create Secure Account
                </Button>
                <p className="mt-4 text-center text-gray-500 text-sm">
                  Already have an account? <button type="button" onClick={() => navigate('login')} className="text-blue-700 font-medium hover:text-blue-800 hover:underline underline-offset-2">Owner login</button>
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