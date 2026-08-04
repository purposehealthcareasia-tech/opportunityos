import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import DailyBudgetCapsule from './DailyBudgetCapsule';
import { useAuth } from '../lib/auth';

export function Layout() {
  const { user } = useAuth();
  const isAdminOrSupport = user?.role === 'admin' || user?.role === 'support';
  return (
    <div className="min-h-screen flex">
      <Sidebar isAdminOrSupport={isAdminOrSupport} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 px-5 md:px-8 py-6 md:py-8 pb-24 md:pb-28 overflow-y-auto">
          <Outlet />
        </main>
        <DailyBudgetCapsule />
      </div>
    </div>
  );
}
export default Layout;
