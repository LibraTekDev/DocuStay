import React from 'react';

const SECTIONS = [
  { id: 'agreement', label: 'Agreement to Terms' },
  { id: 'description', label: 'Description of the Platform' },
  { id: 'accounts', label: 'Account Types and Responsibilities' },
  { id: 'documentation', label: 'Documentation and Legal Effect' },
  { id: 'acceptable-use', label: 'Acceptable Use' },
  { id: 'ip', label: 'Intellectual Property' },
  { id: 'disclaimers', label: 'Disclaimers' },
  { id: 'liability', label: 'Limitation of Liability' },
  { id: 'indemnification', label: 'Indemnification' },
  { id: 'termination', label: 'Termination' },
  { id: 'changes', label: 'Changes to Terms' },
  { id: 'general', label: 'General' },
];

const TermsOfService: React.FC<{ navigate: (v: string) => void }> = ({ navigate }) => {

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-50">
      {/* Header banner */}
      <header className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.03\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
          <div className="flex items-center gap-4 mb-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/10 backdrop-blur-sm border border-white/20">
              <svg className="w-7 h-7 text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Terms of Service</h1>
              <p className="text-slate-400 text-sm mt-1">Last updated: {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
            </div>
          </div>
          <p className="text-slate-300 max-w-2xl text-sm md:text-base leading-relaxed">
            Please read these terms carefully before using DocuStay. By creating an account or using our platform, you agree to be bound by these Terms of Service.
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
              <section id="agreement" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">1</span>
                    Agreement to Terms
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    These Terms of Service (&quot;Terms&quot;) govern your access to and use of DocuStay (&quot;Platform,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;), a neutral documentation platform for property status, occupancy, authorized presence, and related records. By creating an account, signing in, or using any part of the Platform, you agree to be bound by these Terms. If you do not agree, you may not use the Platform.
                  </p>
                  <div className="rounded-xl bg-amber-50/80 border border-amber-200/60 p-4">
                    <p className="text-slate-700 text-sm leading-relaxed">
                      <strong className="text-amber-800">DocuStay is a documentation platform—not a law firm.</strong> We provide tools for documenting property status, guest and tenant authorization, identity verification, and audit trails. We do not provide legal advice. You should consult your own legal counsel for questions about your rights and obligations.
                    </p>
                  </div>
                </div>
              </section>

              <section id="description" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">2</span>
                    Description of the Platform
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay enables property owners, property managers, tenants, and guests to document and manage property-related records. Core features include:
                  </p>
                  <ul className="space-y-3 mb-4">
                    {[
                      { title: 'Property status documentation', desc: 'Recording occupancy status (vacant or occupied), authorized presence, and status changes over time with timestamped, immutable records.' },
                      { title: 'Guest and tenant authorization', desc: 'Inviting guests or tenants, having them sign region-specific agreements (e.g., Revocable Licenses), and maintaining records of authorization periods.' },
                      { title: 'Identity verification', desc: 'Using third-party services (e.g., Stripe Identity) to verify identity for audit trail purposes.' },
                      { title: 'Audit trail', desc: 'Maintaining an append-only, tamper-evident record of actions, status changes, and documentation events.' },
                      { title: 'Verification tools', desc: 'Public verification pages allowing third parties to confirm whether a given token or invitation has active authorization.' },
                    ].map((item, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#6B90F2]/10 text-[#6B90F2] text-xs font-semibold mt-0.5">✓</span>
                        <span className="text-slate-600"><strong className="text-slate-800">{item.title}:</strong> {item.desc}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    Guest authorization is one use case among many. The Platform is designed for broader property-status documentation, including vacant properties and occupancy tracking.
                  </p>
                </div>
              </section>

              <section id="accounts" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">3</span>
                    Account Types and Responsibilities
                  </h2>
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">3.1 Property Owners</h3>
                      <p className="text-slate-600 leading-relaxed">Owners register properties, verify their identity, and may sign a Master Power of Attorney (POA) that authorizes DocuStay to act on their behalf for documentation activities. Owners are responsible for the accuracy of property information, the terms of invitations they send, and compliance with applicable laws. Owners may revoke guest or tenant authorization at any time through the Platform.</p>
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">3.2 Property Managers</h3>
                      <p className="text-slate-600 leading-relaxed">Property managers operate under authority granted by owners. Managers must complete identity verification and comply with the same documentation standards as owners when managing properties on the Platform.</p>
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-slate-800 mb-2">3.3 Guests and Tenants</h3>
                      <p className="text-slate-600 leading-relaxed">Guests and tenants accept invitations, sign agreements, and receive documentation of their authorized presence. They must provide accurate information, comply with the terms of their agreements, and vacate when authorization ends or is revoked. Stay durations may be capped by region-specific rules.</p>
                    </div>
                  </div>
                </div>
              </section>

              <section id="documentation" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">4</span>
                    Documentation and Legal Effect
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay generates and stores documentation records, including signed agreements, occupancy status, and audit events. The Platform does not guarantee the legal enforceability of any document in any jurisdiction. The legal effect of documentation depends on applicable law, the parties&apos; conduct, and other factors. You are responsible for ensuring that your use of the Platform and any documents produced comply with local laws.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    Region-specific agreements (e.g., Revocable Licenses) are tailored to the property&apos;s location. Stay limits, notice requirements, and other terms may vary by jurisdiction. DocuStay provides tools to support documentation; it does not replace legal advice.
                  </p>
                </div>
              </section>

              <section id="acceptable-use" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">5</span>
                    Acceptable Use
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">You agree not to:</p>
                  <ul className="space-y-2 mb-4">
                    {[
                      'Use the Platform for any illegal purpose or in violation of any applicable law.',
                      'Provide false, misleading, or inaccurate information when registering, inviting, or documenting.',
                      'Impersonate another person or entity.',
                      'Attempt to gain unauthorized access to the Platform, other accounts, or systems.',
                      'Interfere with or disrupt the Platform\'s operation or security.',
                      'Use the Platform to harass, abuse, or harm others.',
                      'Circumvent region-specific stay limits or documentation requirements.',
                    ].map((item, i) => (
                      <li key={i} className="flex gap-2 text-slate-600">
                        <span className="text-red-400">×</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    Violation of these terms may result in suspension or termination of your account and access to the Platform.
                  </p>
                </div>
              </section>

              <section id="ip" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">6</span>
                    Intellectual Property
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    DocuStay and its licensors own all rights in the Platform, including software, design, and branding. You retain ownership of your data and content. By using the Platform, you grant DocuStay a limited license to process, store, and display your data as necessary to provide the service and as described in our Privacy Policy.
                  </p>
                </div>
              </section>

              <section id="disclaimers" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">7</span>
                    Disclaimers
                  </h2>
                  <div className="rounded-xl bg-slate-100/80 border border-slate-200 p-4 mb-4">
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      THE PLATFORM IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot; WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED. DOCUSTAY DISCLAIMS ALL WARRANTIES, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE DO NOT GUARANTEE THAT THE PLATFORM WILL BE UNINTERRUPTED, ERROR-FREE, OR SECURE.
                    </p>
                  </div>
                  <p className="text-slate-600 leading-relaxed">
                    DocuStay is a documentation platform. We do not provide legal, tax, or professional advice. Documentation generated through the Platform may or may not be sufficient or legally effective for your purposes. You are solely responsible for your use of the Platform and any decisions you make based on the documentation it produces.
                  </p>
                </div>
              </section>

              <section id="liability" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">8</span>
                    Limitation of Liability
                  </h2>
                  <div className="rounded-xl bg-slate-100/80 border border-slate-200 p-4 mb-4">
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      TO THE MAXIMUM EXTENT PERMITTED BY LAW, DOCUSTAY AND ITS AFFILIATES, OFFICERS, EMPLOYEES, AND AGENTS SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, DATA, OR GOODWILL, ARISING FROM YOUR USE OF OR INABILITY TO USE THE PLATFORM.
                    </p>
                  </div>
                  <p className="text-slate-600 leading-relaxed">
                    IN NO EVENT SHALL OUR TOTAL LIABILITY EXCEED THE GREATER OF (A) THE AMOUNT YOU PAID US IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM, OR (B) ONE HUNDRED U.S. DOLLARS ($100).
                  </p>
                </div>
              </section>

              <section id="indemnification" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">9</span>
                    Indemnification
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    You agree to indemnify, defend, and hold harmless DocuStay and its affiliates, officers, employees, and agents from and against any claims, damages, losses, liabilities, and expenses (including reasonable attorneys&apos; fees) arising from your use of the Platform, your violation of these Terms, or your violation of any third-party rights.
                  </p>
                </div>
              </section>

              <section id="termination" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">10</span>
                    Termination
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    We may suspend or terminate your account and access to the Platform at any time, with or without cause or notice. You may stop using the Platform at any time. Upon termination, your right to use the Platform ceases immediately. Provisions that by their nature should survive (including disclaimers, limitations of liability, and indemnification) will survive termination.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    Documentation and audit records created before termination may be retained as described in our Privacy Policy and for legal and operational purposes.
                  </p>
                </div>
              </section>

              <section id="changes" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">11</span>
                    Changes to Terms
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    We may modify these Terms from time to time. We will notify you of material changes by posting the updated Terms on the Platform and updating the &quot;Last updated&quot; date. Your continued use of the Platform after such changes constitutes acceptance of the revised Terms. If you do not agree, you must stop using the Platform.
                  </p>
                </div>
              </section>

              <section id="general" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">12</span>
                    General
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    These Terms constitute the entire agreement between you and DocuStay regarding the Platform. If any provision is found unenforceable, the remaining provisions will remain in effect. Our failure to enforce any right does not waive that right. These Terms are governed by the laws of the United States and the State of Delaware, without regard to conflict of law principles.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    For questions about these Terms, please contact us through the support options available on the Platform.
                  </p>
                </div>
              </section>
            </div>

            {/* Footer CTA */}
            <div className="mt-12 rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 p-8 md:p-10 text-white">
              <h3 className="text-lg font-semibold mb-2">Related documents</h3>
              <p className="text-slate-300 text-sm mb-6">Review our Privacy Policy to understand how we collect, use, and protect your data.</p>
              <div className="flex flex-wrap gap-4">
                <button onClick={() => navigate('privacy')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 font-medium text-sm transition-colors">
                  Privacy Policy
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

export default TermsOfService;
