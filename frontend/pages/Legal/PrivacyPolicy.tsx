import React from 'react';

const SECTIONS = [
  { id: 'intro', label: 'Introduction' },
  { id: 'collect', label: 'Information We Collect' },
  { id: 'use', label: 'How We Use Your Information' },
  { id: 'share', label: 'How We Share Your Information' },
  { id: 'retention', label: 'Data Retention' },
  { id: 'security', label: 'Security' },
  { id: 'rights', label: 'Your Rights and Choices' },
  { id: 'cookies', label: 'Cookies and Tracking' },
  { id: 'transfers', label: 'International Transfers' },
  { id: 'children', label: 'Children' },
  { id: 'changes', label: 'Changes to This Policy' },
  { id: 'contact', label: 'Contact Us' },
];

const PrivacyPolicy: React.FC<{ navigate: (v: string) => void }> = ({ navigate }) => {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-50">
      {/* Header banner */}
      <header className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.03\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
          <div className="flex items-center gap-4 mb-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/10 backdrop-blur-sm border border-white/20">
              <svg className="w-7 h-7 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Privacy Policy</h1>
              <p className="text-slate-400 text-sm mt-1">Last updated: {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
            </div>
          </div>
          <p className="text-slate-300 max-w-2xl text-sm md:text-base leading-relaxed">
            We take your privacy seriously. This policy explains how we collect, use, and protect your personal information when you use DocuStay.
          </p>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
        <div className="flex flex-col lg:flex-row gap-12">
          {/* Sticky table of contents */}
          <aside className="lg:w-64 shrink-0">
            <nav className="lg:sticky lg:top-24 space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-4">On this page</p>
              {SECTIONS.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  onClick={(e) => { e.preventDefault(); document.getElementById(s.id)?.scrollIntoView({ behavior: 'smooth' }); }}
                  className="block py-2 text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors rounded-lg px-3 -mx-3"
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>

          {/* Main content */}
          <main className="flex-1 min-w-0">
            <div className="space-y-8">
              <section id="intro" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">1</span>
                    Introduction
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;) operates a neutral documentation platform for property status, occupancy, authorized presence, and related records. This Privacy Policy explains how we collect, use, disclose, and protect your personal information when you use our Platform, website, and services.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    By using DocuStay, you consent to the practices described in this policy. If you do not agree, please do not use the Platform.
                  </p>
                </div>
              </section>

              <section id="collect" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">2</span>
                    Information We Collect
                  </h2>
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">2.1 Information You Provide</h3>
                      <ul className="space-y-2">
                        {[
                          { title: 'Account information', desc: 'Name, email address, phone number, and password when you register. Property owners may provide ownership verification documents (e.g., deed, tax bill).' },
                          { title: 'Property information', desc: 'Addresses, property details, occupancy status, and documentation preferences for properties you add to the Platform.' },
                          { title: 'Invitation and guest data', desc: 'Guest or tenant names, email addresses, stay dates, and related information when you create invitations or accept them.' },
                          { title: 'Identity verification data', desc: 'When you complete identity verification (e.g., via Stripe Identity), we receive verification status and identifiers. We do not store raw identity documents.' },
                          { title: 'Agreement and signature data', desc: 'Electronic signatures, agreement acceptance timestamps, and related metadata when you sign documents.' },
                        ].map((item, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="text-[#6B90F2] mt-1">•</span>
                            <span className="text-slate-600"><strong className="text-slate-800">{item.title}:</strong> {item.desc}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">2.2 Information Collected Automatically</h3>
                      <ul className="space-y-2 text-slate-600">
                        <li><strong>Usage data:</strong> Logs of actions, page views, API requests, and interactions for security and service improvement.</li>
                        <li><strong>Device and browser data:</strong> IP address, browser type, operating system, and similar technical data.</li>
                      </ul>
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">2.3 Information from Third Parties</h3>
                      <p className="text-slate-600 leading-relaxed">We may receive information from identity verification providers (e.g., Stripe), email delivery services, and other service providers that support Platform operations.</p>
                    </div>
                  </div>
                </div>
              </section>

              <section id="use" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">3</span>
                    How We Use Your Information
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">We use your information to:</p>
                  <ul className="space-y-2 mb-4">
                    {[
                      { title: 'Provide the Platform', desc: 'Create and manage accounts, document property status, process invitations, generate agreements, maintain audit trails.' },
                      { title: 'Verify identity', desc: 'Facilitate identity verification and link verification results to your account.' },
                      { title: 'Communicate with you', desc: 'Send transactional emails (verification codes, invitation links, stay reminders, status alerts).' },
                      { title: 'Improve and secure the Platform', desc: 'Analyze usage, detect fraud, debug issues, and enhance performance.' },
                      { title: 'Comply with legal obligations', desc: 'Respond to lawful requests and enforce our Terms of Service.' },
                    ].map((item, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="text-emerald-500 mt-1">✓</span>
                        <span className="text-slate-600"><strong className="text-slate-800">{item.title}:</strong> {item.desc}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="rounded-xl bg-emerald-50/80 border border-emerald-200/60 p-4">
                    <p className="text-slate-700 text-sm font-medium">We do not sell your personal information to third parties for marketing purposes.</p>
                  </div>
                </div>
              </section>

              <section id="share" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">4</span>
                    How We Share Your Information
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">We may share your information with:</p>
                  <ul className="space-y-2 mb-4">
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Other users as necessary:</strong> Property owners see guest/tenant info for invitations they create. Guests and tenants see relevant property details.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Verification and public pages:</strong> Our public Verify page allows token-based authorization checks without exposing full personal details.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Service providers:</strong> Hosting, email, identity verification, analytics. Contractually required to protect your data.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Legal and safety:</strong> When required by law or to protect rights and safety.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    Documentation and audit records are immutable and append-only. Once created, they may be retained and shared as described in this policy.
                  </p>
                </div>
              </section>

              <section id="retention" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">5</span>
                    Data Retention
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    We retain your information for as long as your account is active. After account closure, we may retain:
                  </p>
                  <ul className="space-y-2 mb-4">
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Documentation and audit records:</strong> For legal, compliance, and dispute-resolution purposes.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-slate-400">•</span><strong className="text-slate-800">Backup and operational data:</strong> For a limited period for security and recovery.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    You may request deletion of your account and associated data subject to our retention obligations and applicable law.
                  </p>
                </div>
              </section>

              <section id="security" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">6</span>
                    Security
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    We implement technical and organizational measures to protect your data, including encryption in transit and at rest, access controls, and secure development practices. No system is completely secure; you are responsible for safeguarding your account credentials.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    If we become aware of a data breach affecting your personal information, we will notify you and relevant authorities as required by applicable law.
                  </p>
                </div>
              </section>

              <section id="rights" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">7</span>
                    Your Rights and Choices
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">Depending on your location, you may have rights to:</p>
                  <div className="grid sm:grid-cols-2 gap-3 mb-4">
                    {['Access', 'Correction', 'Deletion', 'Portability', 'Opt-out', 'Object or restrict'].map((right, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-50 px-4 py-2">
                        <span className="text-[#6B90F2]">✓</span>
                        <span className="text-slate-700 font-medium">{right}</span>
                      </div>
                    ))}
                  </div>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    To exercise these rights, contact us through the support options on the Platform. Residents of California, the EEA, the UK, and other jurisdictions may have additional rights under applicable law.
                  </p>
                </div>
              </section>

              <section id="cookies" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">8</span>
                    Cookies and Tracking
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">We use cookies for:</p>
                  <ul className="space-y-2 mb-4">
                    <li className="text-slate-600"><strong className="text-slate-800">Authentication:</strong> Keeping you signed in and managing your session.</li>
                    <li className="text-slate-600"><strong className="text-slate-800">Security:</strong> Detecting and preventing fraud and abuse.</li>
                    <li className="text-slate-600"><strong className="text-slate-800">Functionality:</strong> Remembering preferences and supporting core features.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    You can control cookies through your browser settings. Disabling certain cookies may affect Platform functionality.
                  </p>
                </div>
              </section>

              <section id="transfers" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">9</span>
                    International Transfers
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    Your information may be processed and stored in the United States or other countries. By using the Platform, you consent to such transfer. We take steps to ensure adequate protection in accordance with applicable law.
                  </p>
                </div>
              </section>

              <section id="children" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">10</span>
                    Children
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    The Platform is not intended for users under 18. We do not knowingly collect personal information from children. If you believe we have collected information from a child, please contact us and we will take steps to delete it.
                  </p>
                </div>
              </section>

              <section id="changes" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">11</span>
                    Changes to This Policy
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    We may update this Privacy Policy from time to time. We will notify you of material changes by posting the updated policy and updating the &quot;Last updated&quot; date. Your continued use constitutes acceptance. We encourage you to review this policy periodically.
                  </p>
                </div>
              </section>

              <section id="contact" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">12</span>
                    Contact Us
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    For questions about this Privacy Policy or our data practices, please contact us through the support options available on the Platform.
                  </p>
                </div>
              </section>
            </div>

            {/* Footer CTA */}
            <div className="mt-12 rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 p-8 md:p-10 text-white">
              <h3 className="text-lg font-semibold mb-2">Related documents</h3>
              <p className="text-slate-300 text-sm mb-6">Review our Terms of Service for the full agreement governing your use of DocuStay.</p>
              <div className="flex flex-wrap gap-4">
                <button onClick={() => navigate('terms')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 font-medium text-sm transition-colors">
                  Terms of Service
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" /></svg>
                </button>
                <button onClick={() => navigate('')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-slate-300 hover:text-white hover:bg-white/10 font-medium text-sm transition-colors">
                  Back to Home
                </button>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};

export default PrivacyPolicy;
