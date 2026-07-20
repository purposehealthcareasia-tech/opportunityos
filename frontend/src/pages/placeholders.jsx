import React from 'react';
import PhasePlaceholder from '../components/PhasePlaceholder';

export function Passport() {
  return (
    <PhasePlaceholder
      title="Career Passport"
      phase="Phase 2"
      summary="The Passport is the only factual source of truth for your candidacy. Every claim gets ingested, deduplicated, and approved by you before it can be used in materials or matching."
      checklist={[
        'Résumé upload + parse into structured claims',
        'Per-claim approval, versioning, and evidence attachment',
        'Sealed sensitive fields (e.g., work authorization) never shown to reviewers',
        'Supersede-by chain so history is never lost',
      ]}
    />
  );
}

export function Preferences() {
  return (
    <PhasePlaceholder
      title="Preferences"
      phase="Phase 2"
      summary="Where you want to work, comp expectations, availability, and screener answers — all editable, all versioned, none exposed until you approve them for a specific application."
      checklist={[
        'Location, comp range, remote/hybrid tolerances',
        'Screener-question answers with per-employer scoping',
        'Availability + notice-period declarations',
      ]}
    />
  );
}

export function Eligibility() {
  return (
    <PhasePlaceholder
      title="Eligibility"
      phase="Phase 2"
      summary="Work authorization and visa timelines live here. These fields are sealed by default — admins and support see them masked; only you see the real values."
      checklist={[
        'Work-authorization declarations',
        'Visa timeline (STEM OPT, H-1B lottery windows, TN start dates, etc.)',
        'Sponsor-required vs sponsor-optional filters',
      ]}
    />
  );
}

export function Feed() {
  return (
    <PhasePlaceholder
      title="Opportunity feed"
      phase="Phase 3"
      summary="A feed of live openings that match your approved Passport — not a spray-and-pray inbox. SampleCo demo jobs are seeded today for downstream testing but will be badged and excluded from metrics."
      checklist={[
        'Fresh-only listings with last_verified timestamps',
        'Green-lane employers highlighted; sample rows badged',
        'Per-job rationale (“why this matches”) grounded in claims',
      ]}
    />
  );
}

export function Applications() {
  return (
    <PhasePlaceholder
      title="Applications"
      phase="Phase 4"
      summary="Grounded materials get drafted here — strictly from your approved Passport. Nothing leaves your account until you approve it. Models will be pinned: parsing gpt-5 (fallback gpt-4o), generation claude-sonnet-4."
      checklist={[
        'Per-application résumé + cover-letter drafts',
        'Claim provenance underneath every sentence',
        'Explicit approve/reject before send',
      ]}
    />
  );
}

export function Tracker() {
  return (
    <PhasePlaceholder
      title="Application tracker"
      phase="Phase 5"
      summary="State of every application you’ve explicitly sent — last touch, next step, interview loop status — with real receipts you can audit."
      checklist={[
        'Status timeline per application',
        'Interview-loop stage tracker',
        'Follow-up nudges (only if you opt in)',
      ]}
    />
  );
}

export function Analytics() {
  return (
    <PhasePlaceholder
      title="Analytics"
      phase="Phase 5"
      summary="Honest metrics: qualified-interview rate, response quality, time-to-first-recruiter-touch. Sample jobs are excluded from every cohort."
      checklist={[
        'Qualified-interview conversion (not applications sent)',
        'Per-role-family funnel',
        'Personal baseline over time',
      ]}
    />
  );
}

export function Billing() {
  return (
    <PhasePlaceholder
      title="Billing"
      phase="Phase 6"
      summary="Payment methods, plan status, receipts. Stripe integration is deferred to phase 6."
      checklist={[
        'Plan selection + prorated changes',
        'Invoice history',
        'Card / bank-transfer methods',
      ]}
    />
  );
}

export function Privacy() {
  return (
    <PhasePlaceholder
      title="Privacy"
      phase="Phase 2"
      summary="Data export, deletion, and per-action audit trail viewer."
      checklist={[
        'Full data export in machine-readable form',
        'Account deletion (append a tombstone; consent ledger preserved)',
        'Per-action audit trail viewer',
      ]}
    />
  );
}
