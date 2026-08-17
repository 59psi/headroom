import { Outlet } from 'react-router';
import { TopNav } from './TopNav';
import { BottomNav } from './BottomNav';
import { Footer } from './Footer';
import { ScrollToTop } from './ScrollToTop';
import { useKeyboardOpen } from '../../lib/useKeyboardOpen';

export function AppShell() {
  // Once, app-wide: iOS lifts fixed elements with the keyboard, which puts the
  // bottom nav in the middle of the screen over whatever you're typing into.
  useKeyboardOpen();
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
