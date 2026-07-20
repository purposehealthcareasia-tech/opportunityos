import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const { login } = useAuth();
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
