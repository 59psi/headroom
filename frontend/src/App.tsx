import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppShell } from './components/layout/AppShell';
import { HomePage } from './pages/HomePage';
import { CasesPage } from './pages/CasesPage';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { NewCasePage } from './pages/NewCasePage';
import { EditCasePage } from './pages/EditCasePage';
import { HatsPage } from './pages/HatsPage';
import { HatDetailPage } from './pages/HatDetailPage';
import { AddHatPage } from './pages/AddHatPage';
import { EditHatPage } from './pages/EditHatPage';
import { RoomsPage } from './pages/RoomsPage';
import { RoomDetailPage } from './pages/RoomDetailPage';
import { SearchPage } from './pages/SearchPage';
import { DuplicatesPage } from './pages/DuplicatesPage';
import { SettingsPage } from './pages/SettingsPage';
import { ValuationPage } from './pages/ValuationPage';
import { StatsPage } from './pages/StatsPage';
import { BulkImportPage } from './pages/BulkImportPage';
import { LoginPage } from './pages/LoginPage';
import { SharePage } from './pages/SharePage';
import { GuestPage } from './pages/GuestPage';
import { TagLandingPage } from './pages/TagLandingPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

/** A case tag just opens the case; the indirection is what buys us the
 *  freedom to change that later without reprinting labels. */
function CaseTagRedirect() {
  const { displayId } = useParams();
  return <Navigate to={`/cases/${displayId}`} replace />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public routes — no auth, no app shell */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/share/:token" element={<SharePage />} />
          {/* Public and outside the shell: a guest has no session, so every
              nav tab would bounce them to the login screen. */}
          <Route path="/guest" element={<GuestPage />} />
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/cases/new" element={<NewCasePage />} />
            <Route path="/cases/:displayId" element={<CaseDetailPage />} />
            <Route path="/cases/:displayId/edit" element={<EditCasePage />} />
            <Route path="/hats" element={<HatsPage />} />
            <Route path="/hats/new" element={<AddHatPage />} />
            <Route path="/hats/import" element={<BulkImportPage />} />
            <Route path="/hats/:hatId" element={<HatDetailPage />} />
            <Route path="/hats/:hatId/edit" element={<EditHatPage />} />
            <Route path="/rooms" element={<RoomsPage />} />
            <Route path="/rooms/:roomId" element={<RoomDetailPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/duplicates" element={<DuplicatesPage />} />
            <Route path="/valuation" element={<ValuationPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            {/* Physical tags (QR stickers / NFC). Deliberately its own stable
                prefix rather than a link straight to /hats/:id — a sticker
                cannot be rewritten, so the URL a tag carries has to outlive
                any future reshuffle of the route table. See tag_service.py. */}
            <Route path="/t/h/:hatId" element={<TagLandingPage />} />
            <Route path="/t/c/:displayId" element={<CaseTagRedirect />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
