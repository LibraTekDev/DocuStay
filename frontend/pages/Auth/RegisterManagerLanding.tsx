import React, { useState } from 'react';
import { Card, Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';

interface RegisterManagerLandingProps {
  navigate: (v: string) => void;
}

/** Extracts invite token from a pasted invite link or raw token. */
function extractInviteToken(input: string): string | null {
  const s = (input || '').trim();
  if (!s) return null;
  // Full URL with hash: ...#register/manager/TOKEN or .../register/manager/TOKEN
  const hashMatch = s.match(/#register\/manager\/([^?#&]+)/);
  if (hashMatch) return hashMatch[1];
  const pathMatch = s.match(/\/register\/manager\/([^?#&/]+)/);
  if (pathMatch) return pathMatch[1];
  // Plain token (alphanumeric)
  if (/^[a-zA-Z0-9_-]+$/.test(s)) return s;
  return null;
}

const RegisterManagerLanding: React.FC<RegisterManagerLandingProps> = ({ navigate }) => {
  const [inviteInput, setInviteInput] = useState('');
  const [error, setError] = useState('');
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const token = extractInviteToken(inviteInput);
    if (!token) {
      setError('Please paste your invite link from the property owner email, or enter your invite code.');
      return;
    }
    navigate(`register/manager/${token}`);
  };

  return (
    <HeroBackground className="flex-grow">
      <div className="w-full max-w-md mx-auto p-6">
        <Card className="p-8">
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Property Manager Signup</h1>
          <p className="text-gray-600 text-sm mb-6">
            Property managers receive invitations from property owners. Paste your invite link from the email to create your account.
          </p>
          <form onSubmit={handleSubmit} className="space-y-5">
            <Input
              label="Invite link or code"
              name="invite_link"
              value={inviteInput}
              onChange={(e) => setInviteInput(e.target.value)}
              placeholder="Paste invite link from email"
              error={error}
            />
            <Button type="submit" className="w-full py-2.5">Continue</Button>
          </form>
          <p className="mt-6 text-center text-gray-500 text-sm">
            Already have an account?{' '}
            <button type="button" onClick={() => navigate('login/property_manager')} className="text-blue-700 font-medium hover:underline">
              Log in
            </button>
          </p>
          <p className="mt-4 text-center">
            <button type="button" onClick={() => navigate('')} className="text-sm text-gray-500 hover:text-gray-700 underline underline-offset-2">
              Back
            </button>
          </p>
        </Card>
      </div>
      <ErrorModal open={errorModal.open} message={errorModal.message} onClose={() => setErrorModal((p) => ({ ...p, open: false }))} />
    </HeroBackground>
  );
};

export default RegisterManagerLanding;
