import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ShieldCheck, FileCheck2, ListChecks, LockKeyhole, XCircle, ArrowRight } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';

function Header() {
  return (
    <header className="px-6 md:px-10 py-5 flex items-center justify-between">
      <Link to="/" className="flex items-center gap-2 no-underline text-ink dark:text-ink-dark">
        <span className="h-7 w-7 rounded-md bg-ink dark:bg-white grid place-items-center">
          <span className="text-white dark:text-ink font-bold text-xs">O</span>
        </span>
        <span className="font-semibold tracking-tight">OpportunityOS</span>
      </Link>
      <nav className="flex items-center gap-3">
        <ThemeToggle />
        <Link to="/login" className="btn btn-secondary no-underline">Sign in</Link>
        <Link to="/signup" className="btn btn-primary no-underline">Create account</Link>
      </nav>
    </header>
  );
}

function Pillar({ icon: Icon, title, body }) {
  return (
    <div className="card p-6">
      <div className="h-9 w-9 rounded-md border border-line dark:border-line-dark grid place-items-center mb-4">
        <Icon className="h-4 w-4 text-accent" />
      </div>
      <h3 className="text-base font-semibold mb-1.5">{title}</h3>
      <p className="text-sm muted leading-relaxed">{body}</p>
    </div>
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
    <div className="min-h-screen bg-surface dark:bg-surface-dark">
      <Header />

      {/* HERO */}
      <section className="px-6 md:px-10 pt-10 md:pt-20 pb-16 md:pb-28 max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <span className="pill pill-accent mb-6">Candidate-fiduciary · Consent-first</span>
          <h1 className="text-4xl md:text-6xl font-semibold leading-[1.05] tracking-tight max-w-4xl">
            Apply to the right jobs with applications employers can trust — <span className="text-accent">and see the receipts.</span>
          </h1>
          <p className="muted mt-6 text-base md:text-lg max-w-2xl leading-relaxed">
            OpportunityOS is optimized for qualified interviews, not application volume. Your Career Passport is the only factual source of truth. Nothing gets processed, matched, or generated without your explicit consent.
          </p>
          <div className="flex flex-wrap gap-3 mt-8">
            <Link to="/signup" className="btn btn-primary no-underline">Create your account <ArrowRight className="h-4 w-4" /></Link>
            <Link to="/login" className="btn btn-secondary no-underline">I already have one</Link>
          </div>
        </motion.div>
      </section>

      {/* PILLARS */}
      <section className="px-6 md:px-10 py-16 max-w-5xl mx-auto">
        <div className="grid md:grid-cols-3 gap-4">
          <Pillar
            icon={ShieldCheck}
            title="Career Passport, approved by you"
            body="Every claim — skills, projects, education, employment — is stored, versioned, and approved by you before it ever leaves your account."
          />
          <Pillar
            icon={FileCheck2}
            title="Grounded materials, no fabrication"
            body="When materials are drafted for you, they are grounded strictly in your approved Passport. If we can't ground a sentence in a claim, we won't write it."
          />
          <Pillar
            icon={ListChecks}
            title="Consent ledger you can audit"
            body="Every grant and revoke is a row in an append-only ledger. Revoke a scope and dependent features stop working immediately — with a clear explanation."
          />
        </div>
      </section>

      {/* WHAT WE NEVER DO */}
      <section className="px-6 md:px-10 py-16 max-w-5xl mx-auto">
        <div className="card p-8 md:p-10">
          <div className="flex items-center gap-2 mb-4">
            <LockKeyhole className="h-5 w-5 text-accent" />
            <h2 className="text-xl md:text-2xl font-semibold">What we never do</h2>
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
      <footer className="px-6 md:px-10 py-10 border-t border-line dark:border-line-dark">
        <div className="max-w-5xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="text-xs muted">OpportunityOS · Phase 1 · Foundation build · v0.1</div>
          <div className="text-xs muted">This build has no dashboards or feed yet. That&apos;s intentional — later phases only light up when they can deliver honestly.</div>
        </div>
      </footer>
    </div>
  );
}
