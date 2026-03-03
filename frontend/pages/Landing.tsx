import React, { useState, useEffect } from 'react';
import { Button } from '../components/UI';

/** High-quality property/home images (Unsplash – free to use, no watermark) */
const HERO_IMAGES = [
  'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1920&q=80',
  'https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=1920&q=80',
  'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1920&q=80',
  'https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=1920&q=80',
  'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=1920&q=80',
];

const CAROUSEL_INTERVAL_MS = 5000;

type LandingProps = {
  navigate: (view: string) => void;
};

const Landing: React.FC<LandingProps> = ({ navigate }) => {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const t = setInterval(() => {
      setActiveIndex((i) => (i + 1) % HERO_IMAGES.length);
    }, CAROUSEL_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Hero: full-viewport background carousel + overlay + content */}
      <section className="relative min-h-[90vh] flex items-center justify-center overflow-hidden">
        {/* Background slideshow */}
        <div className="absolute inset-0">
          {HERO_IMAGES.map((src, i) => (
            <div
              key={src}
              className={`absolute inset-0 bg-cover bg-center transition-opacity duration-1000 ease-out ${
                i === activeIndex ? 'opacity-100 z-0' : 'opacity-0 z-[-1]'
              }`}
              style={{ backgroundImage: `url(${src})` }}
              aria-hidden={i !== activeIndex}
            />
          ))}
          {/* Dark overlay for text readability */}
          <div className="absolute inset-0 bg-slate-900/60 z-[1]" />
        </div>

        {/* Hero content */}
        <div className="relative z-10 max-w-4xl mx-auto px-6 text-center text-white">
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight mb-5 drop-shadow-lg">
            Your property,{' '}
            <span className="text-sky-300">documented.</span>
          </h1>
          <p className="text-lg sm:text-xl text-slate-200/95 max-w-2xl mx-auto mb-10 leading-relaxed">
            DocuStay is a neutral documentation platform: authorization records, identity verification, and an immutable audit trail for temporary stays.
          </p>
          <div className="flex flex-col sm:flex-row justify-center gap-4">
            <Button
              variant="primary"
              onClick={() => navigate('register')}
              className="px-8 py-3.5 bg-sky-600 hover:bg-sky-700 border-0 text-white font-semibold shadow-lg shadow-sky-900/30"
            >
              Get started
            </Button>
            <button
              type="button"
              onClick={() => navigate('login')}
              className="px-8 py-3.5 rounded-lg text-sm font-medium border-2 border-white/80 text-white bg-transparent hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white/50 focus:ring-offset-2 focus:ring-offset-transparent transition-colors"
            >
              Sign in
            </button>
          </div>
        </div>

        {/* Carousel indicators */}
        <div className="absolute bottom-8 left-0 right-0 z-10 flex justify-center gap-2">
          {HERO_IMAGES.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className={`h-2 rounded-full transition-all duration-300 ${
                i === activeIndex ? 'w-8 bg-white' : 'w-2 bg-white/50 hover:bg-white/70'
              }`}
              aria-label={`Slide ${i + 1}`}
            />
          ))}
        </div>
      </section>

      {/* Value props */}
      <section className="py-20 px-6 bg-white">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl font-bold text-gray-900 text-center mb-4">
            Why DocuStay?
          </h2>
          <p className="text-gray-600 text-center max-w-2xl mx-auto mb-16">
            Built for owners who want clear documentation and authorization records for temporary stays.
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {[
              {
                title: 'Clear agreements',
                desc: 'Guests sign region-specific agreements so everyone knows the terms of the stay.',
                icon: '📄',
              },
              {
                title: 'Identity verification',
                desc: 'Verify guest identity with Stripe Identity so you know who is staying.',
                icon: '✓',
              },
              {
                title: 'Utility controls',
                desc: 'Authority letters and utility provider management keep services in your name.',
                icon: '🔑',
              },
              {
                title: 'Stay limits & alerts',
                desc: 'Region-aware stay limits and status alerts keep your documentation up to date.',
                icon: '🛡️',
              },
            ].map((item) => (
              <div
                key={item.title}
                className="p-6 rounded-2xl bg-slate-50/80 border border-slate-100 hover:border-sky-200 hover:shadow-md transition-all"
              >
                <div className="text-2xl mb-3">{item.icon}</div>
                <h3 className="font-semibold text-gray-900 mb-2">{item.title}</h3>
                <p className="text-gray-600 text-sm leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works (compact) */}
      <section className="py-20 px-6 bg-gradient-to-b from-slate-50 to-white">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-gray-900 mb-4">
            Simple flow for owners
          </h2>
          <p className="text-gray-600 mb-12">
            Register your property, verify your identity, add utilities, and invite guests with a single link.
          </p>
          <div className="flex flex-wrap justify-center gap-6 sm:gap-10">
            {['Add property', 'Verify identity', 'Invite guest', 'Guest signs'].map((step, i) => (
              <div key={step} className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-600 text-white font-semibold text-sm">
                  {i + 1}
                </span>
                <span className="text-gray-700 font-medium">{step}</span>
                {i < 3 && <span className="hidden sm:inline text-slate-300">→</span>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-20 px-6 bg-slate-900 text-white">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-bold mb-4">
            Ready to document your stays?
          </h2>
          <p className="text-slate-300 mb-8">
            Join DocuStay and manage short-term stays with confidence.
          </p>
          <Button
            variant="primary"
            onClick={() => navigate('register')}
            className="px-8 py-3.5 bg-sky-500 hover:bg-sky-600 border-0 text-white font-semibold"
          >
            Get started free
          </Button>
        </div>
      </section>

      <footer className="py-6 px-4 bg-slate-950 text-slate-400 text-center text-sm">
        © {new Date().getFullYear()} DocuStay. Documentation platform—not a law firm.
      </footer>
    </div>
  );
};

export default Landing;
