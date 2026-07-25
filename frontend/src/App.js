import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Signup from './pages/Signup';
import GoogleCallback from './pages/GoogleCallback';
import Settings from './pages/Settings';
import Admin from './pages/Admin';
import Passport from './pages/Passport';
import Preferences from './pages/Preferences';
import Eligibility from './pages/Eligibility';
import Feed from './pages/Feed';
import JobDetail from './pages/JobDetail';
import Applications from './pages/Applications';
import ApplicationPrep from './pages/ApplicationPrep';
import Approvals from './pages/Approvals';
import Tracker from './pages/Tracker';
import Analytics from './pages/Analytics';
import Billing from './pages/Billing';
import Privacy from './pages/Privacy';
import PrivacyPolicy from './pages/PrivacyPolicy';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import RoleRoute from './components/RoleRoute';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/auth/callback" element={<GoogleCallback />} />
      <Route path="/privacy-policy" element={<PrivacyPolicy />} />

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
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/billing" element={<Billing />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/settings" element={<Settings />} />
        <Route
          path="/admin"
          element={<RoleRoute roles={["admin", "support"]}><Admin /></RoleRoute>}
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
