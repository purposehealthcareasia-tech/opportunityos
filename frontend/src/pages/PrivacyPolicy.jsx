import React, { useEffect } from 'react';

/**
 * P0 Truth Audit (a) — /privacy-policy is now a static-file redirect stub.
 *
 * The real, crawlable, versioned policy lives at /privacy.html
 * (frontend/public/privacy.html, Version 1.0, served with text/html,
 * canonical https://fynd.llc/privacy.html, robots index,follow).
 *
 * Before this pass, /privacy-policy was a 349-line React component
 * rendering the same content through JavaScript. Search crawlers, screen
 * readers, and headless auditors couldn't reliably see the policy text
 * without executing JS — violating the founder rail "serve the real
 * policy as static crawlable text, versioned".
 *
 * Behaviour now:
 *  - Any browser that lands on /privacy-policy is redirected via
 *    window.location.replace() to /privacy.html on first render.
 *  - The <noscript> fallback below carries a direct visible link for
 *    browsers with JS disabled.
 *  - The sitemap.xml (P0 item g) advertises /privacy.html as the
 *    canonical location.
 */
export default function PrivacyPolicyRedirect() {
  useEffect(() => {
    // Preserve query/hash if the founder ever appends anchors like #your-rights.
    const target = '/privacy.html' + (window.location.hash || '');
    window.location.replace(target);
  }, []);

  return (
    <div
      className="min-h-screen bg-canvas text-fg p-6 flex items-center justify-center"
      data-testid="privacy-policy-redirect"
    >
      <div className="max-w-md space-y-3 text-center">
        <p className="text-sm muted">Redirecting to the current Fynd Privacy Policy…</p>
        <noscript>
          <p className="text-sm">
            Please open{' '}
            <a className="text-accent underline" href="/privacy.html">
              /privacy.html
            </a>{' '}
            to read the current Fynd Privacy Policy (Version 1.0).
          </p>
        </noscript>
        <a
          className="text-xs muted underline"
          href="/privacy.html"
          data-testid="privacy-policy-fallback-link"
        >
          Go to the current Privacy Policy
        </a>
      </div>
    </div>
  );
}
