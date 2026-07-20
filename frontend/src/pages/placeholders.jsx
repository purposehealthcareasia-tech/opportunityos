import React from 'react';
import PhasePlaceholder from '../components/PhasePlaceholder';

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
