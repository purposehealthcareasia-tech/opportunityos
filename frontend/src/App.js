import React, { Suspense, lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Signup from './pages/Signup';
import GoogleCallback from './pages/GoogleCallback';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import RoleRoute from './components/RoleRoute';

// Route-level code-splitting — authenticated pages are lazy so the
// landing bundle stays lean. Every page is < 200 lines, so per-route
// chunks are cheap and load on first authenticated navigation.
const Passport         = lazy(() => import('./pages/Passport'));
const Preferences      = lazy(() => import('./pages/Preferences'));
const Eligibility      = lazy(() => import('./pages/Eligibility'));
const Feed             = lazy(() => import('./pages/Feed'));
const JobDetail        = lazy(() => import('./pages/JobDetail'));
const Applications     = lazy(() => import('./pages/Applications'));
const ApplicationPrep  = lazy(() => import('./pages/ApplicationPrep'));
const Approvals        = lazy(() => import('./pages/Approvals'));
const Tracker          = lazy(() => import('./pages/Tracker'));
const Analytics        = lazy(() => import('./pages/Analytics'));
const Outcomes         = lazy(() => import('./pages/Outcomes'));
const Billing          = lazy(() => import('./pages/Billing'));
const Privacy          = lazy(() => import('./pages/Privacy'));
const PrivacyPolicy    = lazy(() => import('./pages/PrivacyPolicy'));
const About            = lazy(() => import('./pages/About'));
const Standards        = lazy(() => import('./pages/Standards'));
const EmployerIntake   = lazy(() => import('./pages/EmployerIntake'));
const SubmitSprint     = lazy(() => import('./pages/SubmitSprint'));
const FollowUps        = lazy(() => import('./pages/FollowUps'));
const OnboardingLaunch = lazy(() => import('./pages/OnboardingLaunch'));
const Settings         = lazy(() => import('./pages/Settings'));
const Admin            = lazy(() => import('./pages/Admin'));

function Fallback() {
  return <div className="p-8 text-sm muted" data-testid="lazy-fallback">Loading…</div>;
}

export default function App() {
  return (
    <Suspense fallback={<Fallback />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/auth/callback" element={<GoogleCallback />} />
        <Route path="/privacy-policy" element={<PrivacyPolicy />} />
        <Route path="/about" element={<About />} />
        <Route path="/standards" element={<Standards />} />
        <Route path="/employers" element={<EmployerIntake />} />

        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route path="/passport" element={<Passport />} />
          <Route path="/preferences" element={<Preferences />} />
          <Route path="/eligibility" element={<Eligibility />} />
          <Route path="/feed" element={<Feed />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/applications/:applicationId/prep" element={<ApplicationPrep />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/tracker" element={<Tracker />} />
          <Route path="/outcomes" element={<Outcomes />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/submit-sprint" element={<SubmitSprint />} />
          <Route path="/follow-ups" element={<FollowUps />} />
          <Route path="/onboarding/launch" element={<OnboardingLaunch />} />
          <Route
            path="/admin"
            element={<RoleRoute roles={["admin", "support"]}><Admin /></RoleRoute>}
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
