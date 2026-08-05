import type { ReactElement, ReactNode } from 'react';
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';

/**
 * Render with the providers the app supplies at its root.
 *
 * A fresh QueryClient per call keeps tests isolated (no cache bleeding between
 * them), and retries are off so a rejected query surfaces immediately instead
 * of hanging the test for the duration of the backoff schedule.
 */
export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { client, ...render(ui, { wrapper: Wrapper }) };
}
