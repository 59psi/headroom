/**
 * The hat page's head: the id as the one h1 (set as a code, its case half a
 * breadcrumb), the construction / analysis / condition badges beside it, and
 * — while the hat loads — a bar in the title's place with exactly one
 * "Loading hat…" for the whole page. It is the shared `PageHeader` now; these
 * pin what the page's own head used to do.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { HatDetailPage } from './HatDetailPage';
import * as hatsApi from '../api/hats';
import type { HatRead } from '../types';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getTagBase: vi.fn(async () => ({ base_url: 'http://h', source: 'request', example_url: 'http://h/t/h/1' })),
  };
});

const mocked = vi.mocked(hatsApi);

function renderPage(hat: HatRead | Promise<HatRead>) {
  if (hat instanceof Promise) mocked.getHat.mockReturnValue(hat);
  else mocked.getHat.mockResolvedValue(hat);
  return renderWithProviders(
    <Routes>
      <Route path="/hats/:hatId" element={<HatDetailPage />} />
    </Routes>,
    { route: '/hats/5' },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('HatDetailPage — header', () => {
  it('titles the page with the id, as a code, its case half linking to the case', async () => {
    renderPage(hatFixture());

    const h1 = await screen.findByRole('heading', { level: 1, name: 'A-001-01' });
    expect(h1).toHaveClass('hr-page-head-code');
    expect(within(h1).getByRole('link', { name: 'A-001' })).toHaveAttribute('href', '/cases/A-001');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  it('carries the construction, analysis and condition badges in the head', async () => {
    renderPage(hatFixture({ construction: 'HYDRO', analysis_status: 'ok', condition: 'new' }));

    const head = (await screen.findByRole('heading', { level: 1 })).closest('header')!;
    expect(within(head).getByText('HYDRO')).toBeInTheDocument();
    expect(within(head).getByText('Analyzed')).toBeInTheDocument();
    // The condition's label, not its stored value (`ConditionBadge`).
    expect(within(head).getByText('New')).toBeInTheDocument();
  });

  it('while the hat loads: no heading yet, and one "Loading hat…" for the page', () => {
    renderPage(new Promise<HatRead>(() => {}));

    expect(screen.queryByRole('heading')).toBeNull();
    const statuses = screen.getAllByRole('status');
    expect(statuses).toHaveLength(1);
    expect(statuses[0]).toHaveTextContent('Loading hat…');
  });
});
