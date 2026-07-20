import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import { useAuth } from '../lib/auth';

export function Layout() {
  const { user } = useAuth();
  const isAdminOrSupport = user?.role === 'admin' || user?.role === 'support';
  return (
    <div className="min-h-screen flex bg-surface-muted dark:bg-surface-dark">
      <Sidebar isAdminOrSupport={isAdminOrSupport} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 p-6 md:p-8 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
export default Layout;
