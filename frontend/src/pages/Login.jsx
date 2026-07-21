import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';

// Inline Google glyph — 20px, brand-accurate, no external asset.
function GoogleGlyph({ className = '' }) {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden className={className}>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.14-3.09-.4-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
      <path fill="none" d="M0 0h48v48H0z"/>
    </svg>
  );
}

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const { login, googleStart } = useAuth();
  const [form, setForm] = useState({ email: '', password: '' });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login({ email: form.email.trim().toLowerCase(), password: form.password });
      const redirect = loc.state?.from && loc.state.from !== '/login' ? loc.state.from : '/settings';
      nav(redirect, { replace: true });
    } catch (err) {
      setError('Email or password not recognized.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-surface-muted dark:bg-surface-dark">
      <header className="px-6 md:px-10 py-5 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 no-underline text-ink dark:text-ink-dark">
          <ArrowLeft className="h-4 w-4" /> <span className="text-sm">Back to home</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="px-6 md:px-10 pb-16">
        <div className="max-w-md mx-auto pt-10">
          <h1 className="text-2xl font-semibold mb-2">Sign in</h1>
          <p className="muted text-sm mb-8">Welcome back. Use the email and password you registered with.</p>
          <form onSubmit={handleSubmit} className="card p-6 space-y-5">
            <button
              type="button"
              onClick={googleStart}
              data-testid="google-signin-btn"
              className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 hover:bg-neutral-50 dark:hover:bg-neutral-800 py-2 text-sm font-medium text-ink dark:text-ink-dark"
            >
              <GoogleGlyph /> Continue with Google
            </button>
            <div className="relative py-1">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-line dark:border-line-dark" /></div>
              <div className="relative text-center"><span className="bg-white dark:bg-bg-dark px-3 text-[10px] uppercase tracking-wider muted">or continue with email</span></div>
            </div>
            <Input
              label="Email"
              type="email"
              required
              autoComplete="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
            <Input
              label="Password"
              type="password"
              required
              autoComplete="current-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            {error && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-3 py-2">
                {error}
              </div>
            )}
            <div className="flex items-center justify-between">
              <p className="text-xs muted">No account? <Link to="/signup" className="font-medium">Create one</Link>.</p>
              <Button type="submit" loading={submitting}>Sign in</Button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}
