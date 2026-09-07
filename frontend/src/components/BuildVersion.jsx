import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';

/**
 * P0 Truth Audit (c) — build-derived version string.
 *
 * Reads GET /api/v1/meta/version at first render (fire-and-forget) and
 * renders `Fynd · v{version} · {git_sha8}`. Never a literal — the
 * version+SHA come from the backend, which reads them from
 * frontend/package.json + `git rev-parse HEAD` at boot.
 *
 * Rendered on the marketing footer (Landing) + the authed shell
 * (Sidebar bottom). Non-blocking: falls back to a subtle "Fynd" text
 * if the endpoint fails (never a lie).
 */
export function BuildVersion({ className = 'text-xs muted', prefix = 'Fynd', 'data-testid': testId = 'build-version' }) {
  const [meta, setMeta] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/meta/version');
        if (!cancelled) setMeta(data);
      } catch {
        /* fail-quiet — footer degrades to bare 'Fynd' */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (!meta || meta.version === 'unversioned') {
    return <span className={className} data-testid={testId}>{prefix}</span>;
  }
  const sha = meta.git_sha && meta.git_sha !== 'unknown' ? ` · ${meta.git_sha.slice(0, 8)}` : '';
  return (
    <span className={className} data-testid={testId} title={`booted ${meta.booted_at}`}>
      {prefix} · v{meta.version}{sha}
    </span>
  );
}
