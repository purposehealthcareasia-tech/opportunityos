import React from 'react';
import { useAuth } from '../lib/auth';
import Card, { CardHeader } from './ui/Card';

export function RoleRoute({ roles, children }) {
  const { user } = useAuth();
  if (!user) return null;
  if (!roles.includes(user.role)) {
    return (
      <div className="max-w-xl mx-auto py-16">
        <Card>
          <CardHeader title="Not available for your account" subtitle="This surface is limited to admin and support roles." />
          <p className="text-sm muted">
            If you believe you should have access, contact your OpportunityOS administrator.
          </p>
        </Card>
      </div>
    );
  }
  return children;
}
export default RoleRoute;
