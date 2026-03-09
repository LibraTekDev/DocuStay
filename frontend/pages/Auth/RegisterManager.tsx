import React, { useState, useEffect } from 'react';
import { Card, Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApi } from '../../services/api';
import { validatePhone } from '../../utils/validatePhone';

interface RegisterManagerProps {
  inviteToken: string;
  onLogin: (user: any) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}

const RegisterManager: React.FC<RegisterManagerProps> = ({ inviteToken, onLogin, navigate, setLoading, notify }) => {
  const [inviteData, setInviteData] = useState<{ email: string; property_name: string } | null>(null);
  const [loadingInvite, setLoadingInvite] = useState(true);
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  useEffect(() => {
    if (!inviteToken) {
      setLoadingInvite(false);
      setErrorModal({ open: true, message: 'Invalid invitation link. Please use the link from your invitation email.' });
      return;
    }
    authApi
      .getManagerInvite(inviteToken)
      .then((data) => {
        setInviteData(data);
        setFormData((prev) => ({ ...prev, email: data.email }));
      })
      .catch(() => setErrorModal({ open: true, message: 'Invitation not found or expired.' }))
      .finally(() => setLoadingInvite(false));
  }, [inviteToken]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    const newErrors: Record<string, string> = {};
    if (!formData.full_name.trim()) newErrors.full_name = 'Full name is required.';
    if (!formData.email.trim()) newErrors.email = 'Email is required.';
    if (formData.phone && !validatePhone(formData.phone).valid) newErrors.phone = validatePhone(formData.phone).error ?? 'Invalid phone.';
    if (!formData.password) newErrors.password = 'Password is required.';
    if (formData.password && formData.password.length < 8) newErrors.password = 'Password must be at least 8 characters.';
    if (formData.password !== formData.confirm_password) newErrors.confirm_password = 'Passwords do not match.';
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.registerManager({
        invite_token: inviteToken,
        full_name: formData.full_name.trim(),
        email: formData.email.trim().toLowerCase(),
        phone: formData.phone.trim(),
        password: formData.password,
        confirm_password: formData.confirm_password,
      });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        notify('success', 'Account created. Please complete identity verification.');
        onLogin(result.data);
        // handleLogin redirects: if !identity_verified -> onboarding/identity; else manager-dashboard
      }
    } catch (err) {
      setLoading(false);
      setErrorModal({ open: true, message: (err as Error)?.message ?? 'Registration failed.' });
    }
  };

  if (loadingInvite) {
    return (
      <HeroBackground className="flex-grow flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-10 h-10 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-4" />
          <p className="text-gray-600">Loading invitation...</p>
        </div>
      </HeroBackground>
    );
  }

  if (!inviteData) {
    return (
      <HeroBackground className="flex-grow flex items-center justify-center">
        <Card className="max-w-md mx-auto p-6 text-center">
          <p className="text-gray-600 mb-4">Invalid or expired invitation. Please use the link from your invitation email.</p>
          <Button onClick={() => navigate('login/property_manager')}>Back to Login</Button>
        </Card>
        <ErrorModal open={errorModal.open} message={errorModal.message} onClose={() => setErrorModal((p) => ({ ...p, open: false }))} />
      </HeroBackground>
    );
  }

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-2xl mx-auto p-6">
        <Card className="p-8">
          <h1 className="text-xl font-semibold text-gray-900 mb-1">Property Manager Signup</h1>
          <p className="text-gray-600 text-sm mb-6">You've been invited to manage {inviteData.property_name}. Create your account below.</p>
          <form onSubmit={handleSubmit} className="space-y-5">
            <Input
              label="Full Name"
              name="full_name"
              value={formData.full_name}
              onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              placeholder="Your full name"
              required
              error={errors.full_name}
            />
            <Input
              label="Email"
              name="email"
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              placeholder="name@example.com"
              required
              error={errors.email}
              readOnly
              className="bg-gray-50"
            />
            <Input
              label="Phone"
              name="phone"
              value={formData.phone}
              onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
              placeholder="+1 555 123 4567"
              error={errors.phone}
            />
            <Input
              label="Password"
              name="password"
              type="password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              placeholder="At least 8 characters"
              required
              error={errors.password}
            />
            <Input
              label="Confirm Password"
              name="confirm_password"
              type="password"
              value={formData.confirm_password}
              onChange={(e) => setFormData({ ...formData, confirm_password: e.target.value })}
              placeholder="Repeat password"
              required
              error={errors.confirm_password}
            />
            <Button type="submit" className="w-full py-2.5">Create Account</Button>
          </form>
          <p className="mt-6 text-center text-gray-500 text-sm">
            Already have an account?{' '}
            <button type="button" onClick={() => navigate('login/property_manager')} className="text-blue-700 font-medium hover:underline">
              Log in
            </button>
          </p>
        </Card>
      </div>
      <ErrorModal open={errorModal.open} message={errorModal.message} onClose={() => setErrorModal((p) => ({ ...p, open: false }))} />
    </HeroBackground>
  );
};

export default RegisterManager;
