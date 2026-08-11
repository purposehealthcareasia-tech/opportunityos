import React, { useState } from 'react';
import { Waves, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { WaveErrorBlocks } from './apply_wave/WaveErrorBlocks';
import { WavePreviewPanel } from './apply_wave/WavePreviewPanel';
import { WaveSuccessPanel } from './apply_wave/WaveSuccessPanel';

const BASE = '/api/v1/wave';

/**
 * Phase 1 §v (1b) — Apply Wave capsule.
 *
 * A user can:
 *   1. Preview the exact spectrum of jobs a wave WOULD queue right now
 *      (dry-run — never mutates state) via GET /wave/preview
 *   2. Confirm with an explicit click → POST /wave/authorize
 *      (persists a `wave_authorizations` row + shortlists eligible jobs)
 *   3. Toggle Standing Wave — when on, subsequent AAB refresh cycles
 *      auto-queue new arrivals matching the scope, still cap-respecting
 *
 * States rendered honestly:
 *   - closed (default) — collapsible entry point
 *   - opened / loading preview
 *   - preview rendered → confirm button (with cap breakdown)
 *   - authorized → success summary
 *   - 403 consent-revoked → explicit "consent required" message
 *   - preview error → error message + retry
 *
 * 2026-08-11 — P2 Tier-2 split: preview / success / error rendering
 * moved to `./apply_wave/` sub-components; this file owns state +
 * async actions. All testids preserved. Zero behaviour change.
 */
export default function ApplyWaveCapsule({ lane, withinMi, onWaved }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [wave, setWave] = useState(null);            // POST authorize result
  const [standing, setStanding] = useState(false);

  const doPreview = async () => {
    setBusy(true); setErr(null); setWave(null);
    try {
      const params = new URLSearchParams();
      if (lane && lane !== 'all') params.set('lane', lane);
      if (withinMi != null) params.set('within_mi', String(withinMi));
      const q = params.toString() ? `?${params.toString()}` : '';
      const r = await api.get(`${BASE}/preview${q}`);
      setPreview(r.data);
    } catch (e) {
      if (e?.response?.status === 403) {
        setErr({ kind: 'consent', message: 'Apply Wave needs the "submit_applications" consent scope. Grant it in Settings to preview.' });
      } else {
        setErr({ kind: 'other', message: e?.response?.data?.detail || e.message || 'Preview failed.' });
      }
    } finally {
      setBusy(false);
    }
  };

  const doAuthorize = async () => {
    if (!preview) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`${BASE}/authorize`, {
        lane: preview.scope.lane,
        within_mi: preview.scope.within_mi,
        family: preview.scope.family,
        cap: preview.scope.cap,
        standing_wave: !!standing,
      });
      setWave(r.data);
      setPreview(null);
      onWaved && onWaved();
    } catch (e) {
      setErr({ kind: 'other', message: e?.response?.data?.detail || e.message || 'Authorize failed.' });
    } finally {
      setBusy(false);
    }
  };

  const doCancel = () => {
    setOpen(false); setPreview(null); setErr(null); setStanding(false);
  };

  const doCloseSuccess = () => {
    setOpen(false); setWave(null);
  };

  return (
    <div className="liquid-card p-4" data-testid="apply-wave-capsule">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-full bg-teal-500/10 text-teal-500">
          <Waves className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold">Apply Wave</div>
            <span className="text-[10px] muted uppercase tracking-wider">§v · dry-run</span>
          </div>
          <div className="text-xs muted mt-1">
            One batch authorization queues every job passing your 3 hard gates + rolling 30-day per-employer cap, with a full preview first.
          </div>

          {!open && (
            <button
              type="button"
              className="btn btn-sm btn-outline mt-3"
              onClick={() => { setOpen(true); doPreview(); }}
              data-testid="apply-wave-open"
            >
              Preview what would queue
            </button>
          )}

          {open && (
            <div className="mt-3 space-y-3">
              {busy && !preview && !wave && (
                <div className="flex items-center gap-2 text-xs muted" data-testid="apply-wave-loading">
                  <Loader2 className="h-3 w-3 animate-spin" /> Enumerating spectrum…
                </div>
              )}

              <WaveErrorBlocks err={err} />

              {preview && !wave && (
                <WavePreviewPanel
                  preview={preview}
                  busy={busy}
                  standing={standing}
                  onStandingChange={setStanding}
                  onAuthorize={doAuthorize}
                  onCancel={doCancel}
                  onRefresh={doPreview}
                />
              )}

              {wave && <WaveSuccessPanel wave={wave} onClose={doCloseSuccess} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
