import React, { useCallback, useEffect, useState } from 'react';
import { Sparkles, ArrowRight, X, Loader2, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';

/**
 * SurpriseMeCapsule — draws ONE eligible outside-lane job on demand.
 *
 * Backend contract (see backend/domains/jobs/router.py):
 *   POST /api/v1/jobs/surprise-me        → { job, why_you_qualify[], remaining_today, message }
 *   GET  /api/v1/jobs/surprise-me/status → { limit, used_today, remaining_today }
 *
 * Rails on the UI side:
 *   * The button never becomes a dead click — disabled state says why
 *     ("5 of 5 used — resets at midnight UTC").
 *   * `why_you_qualify` is rendered verbatim; the UI never fabricates a
 *     reason or embellishes a trace.
 *   * A drawn job condenses in with the liquid morph animation.
 */
export default function SurpriseMeCapsule() {
  const [status, setStatus] = useState({ limit: 5, used_today: 0, remaining_today: 5 });
  const [drawing, setDrawing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const refreshStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/jobs/surprise-me/status');
      setStatus(data);
    } catch (e) {
      // consent gate quietly disables — the CTA copy handles the rest.
    }
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  const disabled = drawing || status.remaining_today <= 0;
  const label = drawing
    ? 'Drawing…'
    : status.remaining_today <= 0
      ? `${status.limit} of ${status.limit} used — resets at midnight UTC`
      : `Surprise me · ${status.remaining_today} left today`;

  const draw = async () => {
    setDrawing(true); setError(null);
    try {
      const { data } = await api.post('/api/v1/jobs/surprise-me', {});
      setResult(data);
      setStatus((s) => ({ ...s, used_today: s.used_today + 1, remaining_today: data.remaining_today }));
    } catch (e) {
      const d = e?.response?.data?.detail;
      setError(d?.message || d?.error || 'Draw failed. Please retry.');
    } finally {
      setDrawing(false);
    }
  };

  return (
    <div className="w-full" data-testid="surprise-me">
      <button
        type="button"
        onClick={draw}
        disabled={disabled}
        className="liquid-capsule liquid-primary text-sm px-4 py-2"
        data-testid="surprise-me-btn"
        title="Draw one eligible job outside your usual lanes"
      >
        {drawing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
        {label}
      </button>

      {error && (
        <div
          className="mt-2 rounded-md border border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400 px-3 py-1.5 text-xs"
          data-testid="surprise-me-error"
        >
          {error}
        </div>
      )}

      {result && (
        <div
          className="mt-3 liquid-sheet p-5 animate-surpriseCondense"
          data-testid="surprise-me-result"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2 text-xs muted uppercase tracking-wide">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              Outside your usual lanes
            </div>
            <button
              type="button"
              onClick={() => setResult(null)}
              className="text-ink-muted hover:text-ink dark:text-ink-dark-muted dark:hover:text-ink-dark"
              data-testid="surprise-me-dismiss"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {result.job ? (
            <>
              <div className="mt-3">
                <Link
                  to={`/jobs/${result.job.id}`}
                  className="text-lg font-semibold hover:underline"
                  data-testid="surprise-me-job-title"
                >
                  {result.job.title}
                </Link>
                <div className="text-sm muted mt-0.5">
                  <span data-testid="surprise-me-job-employer">{result.job.company_name}</span>
                  {result.job.taxonomy_family && <> · <span className="font-mono">{result.job.taxonomy_family}</span></>}
                </div>
              </div>

              {result.why_you_qualify?.length > 0 && (
                <div className="mt-4 rounded-2xl bg-accent/5 border border-accent/25 p-3">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-accent mb-1.5">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Why you qualify
                  </div>
                  <ul className="space-y-1" data-testid="surprise-me-why">
                    {result.why_you_qualify.map((reason, i) => (
                      <li key={`why-${i}-${reason.slice(0, 40)}`} className="text-sm text-ink dark:text-ink-dark leading-snug">
                        · {reason}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-2 text-[11px] muted italic">
                    Every line above is traced to an approved Passport claim. Nothing invented.
                  </div>
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                <Link
                  to={`/jobs/${result.job.id}`}
                  className="liquid-capsule liquid-primary no-underline text-sm"
                  data-testid="surprise-me-view"
                >
                  View job <ArrowRight className="h-4 w-4" />
                </Link>
                <button
                  type="button"
                  onClick={draw}
                  disabled={disabled}
                  className="liquid-capsule liquid-secondary text-sm"
                  data-testid="surprise-me-draw-again"
                >
                  Draw another ({status.remaining_today} left)
                </button>
              </div>
            </>
          ) : (
            <p className="mt-3 text-sm muted leading-relaxed" data-testid="surprise-me-empty">
              {result.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
