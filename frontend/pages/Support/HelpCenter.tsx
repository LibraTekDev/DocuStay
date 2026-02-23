import React, { useState } from 'react';
import { Card, Button } from '../../components/UI';

const FAQS = [
  { q: "How does DocuStay prevent squatter rights?", a: "DocuStay uses AI to analyze jurisdiction-specific laws (like Florida's HB 621) and forces guests to sign a Revocable License rather than a lease. We also strictly cap stay durations and capture biometric verification to prove temporary status." },
  { q: "What is a USAT Token?", a: "The Utility Service Authorization Token is a cryptographically signed pass that authorizes a guest to USE utilities without establishing an account in their name, preventing a common residency indicator." },
  { q: "How do I remove a guest who won't leave?", a: "If a guest overstays, go to your dashboard and click 'Initiate Removal'. This will revoke their USAT token (disabling utility access), send removal notices to both you and the guest, and log all actions for legal documentation. You can then contact local law enforcement with the documentation from your dashboard." },
];

const HelpCenter: React.FC<{ navigate: (v: string) => void; embedded?: boolean }> = ({ navigate, embedded }) => {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  return (
    <div className="w-full max-w-5xl py-4 md:py-6">
      {!embedded && (
        <button
          onClick={() => navigate('dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-blue-700 font-medium text-sm uppercase tracking-wider transition-colors mb-6"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Dashboard
        </button>
      )}

      <header className="mb-8">
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 tracking-tight">DocuStay Help Center</h1>
        <p className="text-gray-600 text-sm mt-1">Legal-tech protection at your fingertips.</p>
      </header>

      <section className="space-y-4 mb-10">
        <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wider mb-4">Frequently Asked Questions</h2>
        {FAQS.map((faq, i) => (
          <Card key={i} className="overflow-hidden">
            <button
              type="button"
              onClick={() => setOpenIdx(openIdx === i ? null : i)}
              className="w-full p-5 md:p-6 text-left flex justify-between items-center gap-4 group hover:bg-gray-50 transition-colors"
            >
              <span className="font-semibold text-gray-900 group-hover:text-blue-700 text-left">{faq.q}</span>
              <svg
                className={`w-5 h-5 text-gray-500 shrink-0 transition-transform ${openIdx === i ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {openIdx === i && (
              <div className="px-5 md:px-6 pb-5 md:pb-6 pt-0 border-t border-gray-100">
                <p className="text-gray-600 text-sm leading-relaxed">{faq.a}</p>
              </div>
            )}
          </Card>
        ))}
      </section>

      <Card className="p-8 md:p-10 bg-gradient-to-br from-blue-50 to-sky-50 border-blue-200 text-center">
        <h2 className="text-xl md:text-2xl font-bold text-gray-900 mb-3">Emergency Support?</h2>
        <p className="text-gray-600 text-sm mb-6 max-w-lg mx-auto">
          Our AI Enforcement Team is available 24/7 for owners facing active unauthorized occupancy situations.
        </p>
        <div className="flex flex-col sm:flex-row justify-center gap-3">
          <Button variant="primary" type="button" className="px-8 py-3">
            Live Chat with Legal AI
          </Button>
          <Button variant="outline" type="button" className="px-8 py-3">
            Request Removal Help
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default HelpCenter;
