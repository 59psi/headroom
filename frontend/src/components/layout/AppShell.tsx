import { Outlet } from 'react-router-dom';
import { TopNav } from './TopNav';
import { BottomNav } from './BottomNav';

export function AppShell() {
  return (
    <>
      <TopNav />
      <main className="container py-3">
        <Outlet />
      </main>
      <BottomNav />
    </>
  );
}
