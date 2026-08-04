import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ShieldCheck, FileCheck2, ListChecks, LockKeyhole, XCircle, ArrowRight } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';
import { FyndWordmark } from '../components/FyndMark';

/**
 * Landing — Fynd Liquid.
 * Only page with SVG displacement refraction (§2 performance rail).
 * Everything else is composition of the liquid tokens.
 */

function Header() {
  return (
    <header className="liquid-bar sticky top-0 z-40 px-6 md:px-10 py-4 flex items-center justify-between">
      <Link to="/" className="no-underline text-ink dark:text-ink-dark" data-testid="landing-home">
        <FyndWordmark />
      </Link>
      <nav className="flex items-center gap-3">
        <ThemeToggle />
        <Link to="/login" className="liquid-capsule liquid-secondary no-underline" data-testid="landing-signin">Sign in</Link>
        <Link to="/signup" className="liquid-capsule liquid-primary no-underline" data-testid="landing-signup">Create account</Link>
      </nav>
    </header>
  );
}

function Pillar({ icon: Icon, title, body, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-40px' }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1.2, 0.36, 1] }}
      className="liquid-card p-6"
    >
      <div className="h-10 w-10 rounded-2xl bg-accent/10 grid place-items-center mb-4">
        <Icon className="h-4 w-4 text-accent" />
      </div>
      <h3 className="text-base font-semibold mb-1.5">{title}</h3>
      <p className="text-sm muted leading-relaxed">{body}</p>
    </motion.div>
  );
}

function NeverItem({ children }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 flex-shrink-0 h-5 w-5 rounded-full border border-red-500/40 grid place-items-center">
        <XCircle className="h-3 w-3 text-red-500" />
      </span>
      <span className="text-sm text-ink dark:text-ink-dark leading-relaxed">{children}</span>
    </li>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen" data-testid="landing-page">
      <Header />

      {/* HERO */}
      <section className="relative px-6 md:px-10 pt-14 md:pt-24 pb-20 md:pb-32 max-w-6xl mx-auto">
        {/* Refraction blobs — the only place we use the SVG displacement filter */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 -top-20 h-[440px] overflow-hidden">
          <div className="absolute -top-24 -left-20 h-72 w-72 rounded-full bg-accent/25 blur-3xl liquid-refraction" />
          <div className="absolute top-10 right-0 h-80 w-80 rounded-full bg-sky-500/20 blur-3xl liquid-refraction" />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1.2, 0.36, 1] }}
          className="relative"
        >
          <span className="liquid-pill liquid-pill--accent mb-7">Candidate-fiduciary · Consent-first</span>
          <h1 className="text-5xl md:text-7xl font-semibold leading-[1.02] tracking-display-tight max-w-4xl">
            Apply to the right jobs with applications employers can trust — <span className="bg-gradient-to-br from-accent to-emerald-500 bg-clip-text text-transparent">and see the receipts.</span>
          </h1>
          <p className="muted mt-7 text-base md:text-lg max-w-2xl leading-relaxed">
            Fynd is optimized for qualified interviews, not application volume. Your Career Passport is the only factual source of truth. Nothing gets processed, matched, or generated without your explicit consent.
          </p>
          <div className="flex flex-wrap gap-3 mt-9">
            <Link to="/signup" className="liquid-capsule liquid-primary no-underline px-5 py-3 text-base" data-testid="hero-cta-signup">
              Create your account <ArrowRight className="h-4 w-4" />
            </Link>
            <Link to="/login" className="liquid-capsule liquid-secondary no-underline px-5 py-3 text-base" data-testid="hero-cta-signin">
              I already have one
            </Link>
          </div>
        </motion.div>
      </section>

      {/* PILLARS */}
      <section className="px-6 md:px-10 pb-16 max-w-6xl mx-auto">
        <div className="grid md:grid-cols-3 gap-5">
          <Pillar
            icon={ShieldCheck}
            title="Career Passport, approved by you"
            body="Every claim — skills, projects, education, employment — is stored, versioned, and approved by you before it ever leaves your account."
          />
          <Pillar
            icon={FileCheck2}
            title="Grounded materials, no fabrication"
            body="When materials are drafted for you, they are grounded strictly in your approved Passport. If we can't ground a sentence in a claim, we won't write it."
            delay={0.06}
          />
          <Pillar
            icon={ListChecks}
            title="Consent ledger you can audit"
            body="Every grant and revoke is a row in an append-only ledger. Revoke a scope and dependent features stop working immediately — with a clear explanation."
            delay={0.12}
          />
        </div>
      </section>

      {/* WHAT WE NEVER DO */}
      <section className="px-6 md:px-10 py-16 max-w-6xl mx-auto">
        <div className="liquid-sheet p-8 md:p-10">
          <div className="flex items-center gap-2 mb-4">
            <LockKeyhole className="h-5 w-5 text-accent" />
            <h2 className="text-xl md:text-2xl font-semibold tracking-display">What we never do</h2>
          </div>
          <p className="muted mb-6 max-w-2xl">A short list of things a candidate-fiduciary product doesn&apos;t do. Not marketing copy — operational rules.</p>
          <ul className="grid md:grid-cols-2 gap-4">
            <NeverItem>We never scrape employer sites or bypass their terms of service.</NeverItem>
            <NeverItem>We never ask for your account passwords.</NeverItem>
            <NeverItem>We never invent facts or embellish your background.</NeverItem>
            <NeverItem>We never auto-submit an application on your behalf without your explicit approval.</NeverItem>
          </ul>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="px-6 md:px-10 py-10 border-t border-white/10 dark:border-white/5">
        <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="text-xs muted">Fynd · Phase 1 · Foundation build · v0.1</div>
          <div className="text-xs muted">This build has no dashboards or feed yet. That&apos;s intentional — later phases only light up when they can deliver honestly.</div>
        </div>
      </footer>
    </div>
  );
}
