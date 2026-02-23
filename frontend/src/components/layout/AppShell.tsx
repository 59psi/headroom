import { Outlet } from 'react-router-dom';
import { TopNav } from './TopNav';
import { BottomNav } from './BottomNav';
import { Footer } from './Footer';

export function AppShell() {
  return (
    <>
      <TopNav />
      <main className="container py-3">
        <Outlet />
      </main>
      <Footer />
      <BottomNav />
    </>
  );
}
