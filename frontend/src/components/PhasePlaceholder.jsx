import React from 'react';
import { Clock } from 'lucide-react';
import Card from './ui/Card';

export function PhasePlaceholder({ title, phase = 'later phase', summary, checklist = [] }) {
  return (
    <div className="max-w-3xl mx-auto animate-fadeIn">
      <div className="flex items-center gap-2 mb-3">
        <span className="pill pill-neutral"><Clock className="h-3 w-3" />Coming in {phase} — not yet active</span>
      </div>
      <h1 className="text-2xl font-semibold mb-2">{title}</h1>
      {summary && <p className="muted mb-6 max-w-2xl leading-relaxed">{summary}</p>}
      <Card>
        <h3 className="text-sm font-semibold mb-3">What will be here when this ships</h3>
        {checklist.length ? (
          <ul className="space-y-2 text-sm">
            {checklist.map((c) => (
              <li key={c} className="flex items-start gap-2">
                <span className="mt-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent flex-shrink-0" />
                <span className="muted">{c}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm muted">Design and scope for this section are being finalized in the current phase brief.</p>
        )}
      </Card>
      <p className="text-xs muted mt-6">OpportunityOS never lights up a section until it can actually deliver on its promise. This surface intentionally has no controls yet.</p>
    </div>
  );
}
export default PhasePlaceholder;
