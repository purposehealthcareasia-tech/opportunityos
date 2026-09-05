import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Zap, ClipboardCheck, IdCard, ShieldCheck, Rss } from 'lucide-react';
import { api } from '../lib/api';

/**
 * SmartCTA — ONE primary contextual call-to-action per screen.
 * Never a dead click; disabled states say WHY (per directive §3).
 *
 * Priority (highest wins):
 *   1. Passport not activated              → "Finish Passport — 2 min"
 *   2. Awaiting-approval applications > 0  → "Review N approvals"
 *   3. Shortlisted queue >= 3              → "Start Sprint"
 *   4. Fresh feed rows                     → "Review today's queue (N)"
 *   5. Fallback                            → "Open your feed"
 */
export default function SmartCTA({ hide = false, className = '' }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // These calls are all consent-gated on the user's already-granted
        // scopes for the fixture — any 403 quietly demotes to the fallback.
        const [meRes, appsRes, feedRes] = await Promise.allSettled([
          api.get('/api/v1/auth/me'),
          api.get('/api/v1/applications'),
          api.get('/api/v1/jobs/feed'),
        ]);
        if (!alive) return;
        const me = meRes.status === 'fulfilled' ? meRes.value.data : null;
        const apps = appsRes.status === 'fulfilled' ? (appsRes.value.data?.applications || []) : [];
        const feed = feedRes.status === 'fulfilled' ? feedRes.value.data : null;
        setState({
          loading: false,
          passportActivated: !!me?.passport_activated,
          awaitingCount: apps.filter((a) => a.state === 'awaiting_approval').length,
          shortlistedCount: apps.filter((a) => a.state === 'shortlisted').length,
          feedPassing: feed?.passing?.length || 0,
        });
      } catch (e) {
        if (alive) setState({ loading: false });
      }
    })();
    return () => { alive = false; };
  }, []);

  if (hide || state.loading) return null;

  let cta;
  // FYND ATLAS §44 zero-tolerance rail: primary CTAs must produce an
  // observable action. When the user is ALREADY on the destination and
  // clicking the SmartCTA would push a same-URL history entry (which is
  // a no-op — the founder-observed "inert click" bug), we deep-link with
  // a query param (?action=…) so the destination page can react by
  // opening its resume-flow modal / scrolling to the action area.
  if (state.passportActivated === false) {
    cta = { to: '/passport?action=add-identity', label: 'Finish Passport — 2 min', Icon: IdCard, tone: 'primary' };
  } else if (state.awaitingCount > 0) {
    cta = { to: '/approvals', label: `Review ${state.awaitingCount} approval${state.awaitingCount === 1 ? '' : 's'}`, Icon: ClipboardCheck, tone: 'primary' };
  } else if (state.shortlistedCount >= 3) {
    cta = { to: '/submit-sprint', label: `Start Sprint (${state.shortlistedCount} queued)`, Icon: Zap, tone: 'primary' };
  } else if (state.feedPassing > 0) {
    cta = { to: '/feed', label: `Review today's queue (${state.feedPassing})`, Icon: Rss, tone: 'primary' };
  } else {
    cta = { to: '/feed', label: 'Open your feed', Icon: Rss, tone: 'secondary' };
  }

  const Icon = cta.Icon;
  return (
    <Link
      to={cta.to}
      className={`liquid-capsule ${cta.tone === 'primary' ? 'liquid-primary' : 'liquid-secondary'} no-underline ${className}`}
      data-testid="smart-cta"
    >
      <Icon className="h-4 w-4" />
      {cta.label}
      <ArrowRight className="h-3.5 w-3.5" />
    </Link>
  );
}
