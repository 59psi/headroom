import { Outlet } from 'react-router';
import { TopNav } from './TopNav';
import { BottomNav } from './BottomNav';
import { Footer } from './Footer';
import { ScrollToTop } from './ScrollToTop';

export function AppShell() {
  return (
    <>
      <ScrollToTop />
      <TopNav />
      <main className="container">
        <Outlet />
      </main>
      <Footer />
      <BottomNav />
    </>
  );
}
