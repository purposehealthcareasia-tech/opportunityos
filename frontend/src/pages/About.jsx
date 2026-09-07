import React, { useEffect } from 'react';

/**
 * P0 Truth Audit (e) — /about is a static-file redirect stub.
 *
 * The real, crawlable operator page lives at /about.html
 * (frontend/public/about.html: legal entity Purpose Healthcare Labs,
 * contact channels, jurisdiction, build-metadata pointer). Same
 * rationale as PrivacyPolicy.jsx: SPA rendering isn't a substitute
 * for a real static file when auditors + crawlers need to see the
 * operator identity without JS.
 */
export default function AboutRedirect() {
  useEffect(() => {
    const target = '/about.html' + (window.location.hash || '');
    window.location.replace(target);
  }, []);

  return (
    <div
      className="min-h-screen bg-canvas text-fg p-6 flex items-center justify-center"
      data-testid="about-redirect"
    >
      <div className="max-w-md space-y-3 text-center">
        <p className="text-sm muted">Redirecting to the Fynd operator page…</p>
        <noscript>
          <p className="text-sm">
            Please open{' '}
            <a className="text-accent underline" href="/about.html">
              /about.html
            </a>{' '}
            to read the operator information.
          </p>
        </noscript>
        <a className="text-xs muted underline" href="/about.html" data-testid="about-fallback-link">
          Go to the operator page
        </a>
      </div>
    </div>
  );
}
