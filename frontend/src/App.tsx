import { BrowserRouter, Routes, Route } from 'react-router-dom';
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
import { SearchPage } from './pages/SearchPage';
import { SettingsPage } from './pages/SettingsPage';
import { ValuationPage } from './pages/ValuationPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/cases/new" element={<NewCasePage />} />
            <Route path="/cases/:displayId" element={<CaseDetailPage />} />
            <Route path="/cases/:displayId/edit" element={<EditCasePage />} />
            <Route path="/hats" element={<HatsPage />} />
            <Route path="/hats/new" element={<AddHatPage />} />
            <Route path="/hats/:hatId" element={<HatDetailPage />} />
            <Route path="/hats/:hatId/edit" element={<EditHatPage />} />
            <Route path="/rooms" element={<RoomsPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/valuation" element={<ValuationPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
