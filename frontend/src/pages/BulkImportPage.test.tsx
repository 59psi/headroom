/**
 * Bulk import: photos go in by picker or by drop (deduped, images only), the
 * import starts with the chosen defaults, a running job's Cancel asks first,
 * and "finished" is announced only when this page watched it finish.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { caseFixture } from '../test/fixtures';
import { BulkImportPage } from './BulkImportPage';
import * as settingsApi from '../api/settings';
import type { ImportJobRead } from '../types';

vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});
vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getStyles: vi.fn(async () => [{ value: 'a_game', label: 'A-Game', is_beanie: false }]),
    getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
    getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
  };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listCases: vi.fn(async () => [caseFixture({ id: 4, display_id: 'A-004', hat_count: 1 })]),
  };
});

const api = vi.mocked(settingsApi);

function job(over: Partial<ImportJobRead> = {}): ImportJobRead {
  return {
    id: 7, created_at: '2026-09-27T10:00:00Z', finished_at: null,
    total: 2, done: 0, errors: 0, skipped: 0, status: 'running',
    items: [
      { id: 1, filename: 'a.jpg', status: 'processing', hat_id: null, error: null, bytes: 10 },
      { id: 2, filename: 'b.jpg', status: 'queued', hat_id: null, error: null, bytes: 10 },
    ],
    ...over,
  };
}

const photo = (name: string) => new File([new Uint8Array(8)], name, { type: 'image/jpeg', lastModified: 1 });

beforeEach(() => {
  vi.clearAllMocks();
  api.listImportJobs.mockResolvedValue([]);
});

describe('BulkImportPage — picking and starting', () => {
  it('starts the import with the picked photos and the chosen defaults', async () => {
    const user = userEvent.setup();
    api.createImportJob.mockResolvedValue({ id: 7, total: 2, status: 'queued' });
    api.getImportJob.mockResolvedValue(job());
    renderWithProviders(<BulkImportPage />, { route: '/hats/import' });

    await user.selectOptions(await screen.findByLabelText('Case'), '4');
    await user.upload(screen.getByLabelText('Choose photos to import'), [photo('a.jpg'), photo('b.jpg')]);
    expect(screen.getByText('a.jpg')).toBeInTheDocument();
    expect(screen.getByText('2 of 100')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Start import (2)' }));

    await waitFor(() => expect(api.createImportJob).toHaveBeenCalled());
    const [sentFiles, defaults] = api.createImportJob.mock.calls[0];
    expect(sentFiles.map(f => f.name)).toEqual(['a.jpg', 'b.jpg']);
    expect(defaults).toEqual({ case_id: 4, condition: 'new', size: 'classic', style: 'a_game' });
    expect(await screen.findByText('Import started — 2 photos queued')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Import #7' })).toBeInTheDocument();
  });

  it('counts a case’s hats in words that agree — "1 hat", never "1 hats"', async () => {
    renderWithProviders(<BulkImportPage />, { route: '/hats/import' });
    expect(await screen.findByRole('option', { name: 'A-004 (1 hat)' })).toBeInTheDocument();
  });

  it('takes dropped images, skipping duplicates and anything that is not an image', async () => {
    renderWithProviders(<BulkImportPage />, { route: '/hats/import' });
    const zone = await screen.findByRole('button', { name: /Add photos/ });
    const files = [photo('a.jpg'), photo('a.jpg'), new File(['x'], 'list.csv', { type: 'text/csv' })];
    const dataTransfer = { files, types: ['Files'] };
    fireEvent.dragOver(zone, { dataTransfer });
    fireEvent.drop(zone, { dataTransfer });

    expect(await screen.findByText('1 of 100')).toBeInTheDocument();
    expect(screen.queryByText('list.csv')).not.toBeInTheDocument();
  });

  it('removes one photo, or clears them all', async () => {
    const user = userEvent.setup();
    renderWithProviders(<BulkImportPage />, { route: '/hats/import' });
    await user.upload(await screen.findByLabelText('Choose photos to import'), [photo('a.jpg'), photo('b.jpg')]);

    await user.click(screen.getByRole('button', { name: 'Remove a.jpg' }));
    expect(screen.queryByText('a.jpg')).not.toBeInTheDocument();
    expect(screen.getByText('b.jpg')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('0 of 100')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start import (0)' })).toBeDisabled();
  });

  it('can take a Clear back — it sits right beside "Add more"', async () => {
    const user = userEvent.setup();
    renderWithProviders(<BulkImportPage />, { route: '/hats/import' });
    await user.upload(await screen.findByLabelText('Choose photos to import'), [photo('a.jpg'), photo('b.jpg')]);

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('0 of 100')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Undo' }));

    expect(screen.getByText('2 of 100')).toBeInTheDocument();
    expect(screen.getByText('a.jpg')).toBeInTheDocument();
    expect(screen.getByText('b.jpg')).toBeInTheDocument();
  });
});

describe('BulkImportPage — a running job', () => {
  it('shows live progress as a labeled bar and per-photo states', async () => {
    api.getImportJob.mockResolvedValue(job({ done: 1, items: [
      { id: 1, filename: 'a.jpg', status: 'done', hat_id: 31, error: null, bytes: 10 },
      { id: 2, filename: 'b.jpg', status: 'processing', hat_id: null, error: null, bytes: 10 },
    ] }));
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=7' });

    const bar = await screen.findByRole('progressbar', { name: 'Import progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '1');
    expect(bar).toHaveAttribute('aria-valuemax', '2');
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Processing')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View hat →' })).toHaveAttribute('href', '/hats/31');
  });

  it('asks before canceling, and "Keep going" cancels nothing', async () => {
    const user = userEvent.setup();
    api.getImportJob.mockResolvedValue(job());
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=7' });

    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Cancel this import?' });
    await user.click(within(dialog).getByRole('button', { name: 'Keep going' }));

    expect(api.cancelImportJob).not.toHaveBeenCalled();
  });

  it('cancels once confirmed', async () => {
    const user = userEvent.setup();
    api.getImportJob.mockResolvedValue(job());
    api.cancelImportJob.mockResolvedValue(job({ status: 'canceled' }));
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=7' });

    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Cancel this import?' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel import' }));

    await waitFor(() => expect(api.cancelImportJob).toHaveBeenCalledWith(7));
    expect(await screen.findByText('Import canceled')).toBeInTheDocument();
  });

  it('announces the finish it watched happen', async () => {
    api.getImportJob
      .mockResolvedValueOnce(job())
      .mockResolvedValue(job({ status: 'done', done: 2, items: [] }));
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=7' });

    // One 2s poll takes it from running to done.
    expect(await screen.findByText('Import finished — 2 of 2 added', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Done — go to hats' })).toBeInTheDocument();
  });

  it('says a job it cannot load could not be loaded, and offers a fresh start', async () => {
    const user = userEvent.setup();
    api.getImportJob.mockRejectedValue(new Error('404'));
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=99' });

    expect(await screen.findByText(/Couldn't load import job #99/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start a new import' }));
    expect(await screen.findByRole('heading', { name: 'Photos' })).toBeInTheDocument();
  });

  it('stops polling a job it cannot load — a bad ?job= is not asked for every 2s forever', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    try {
      api.getImportJob.mockRejectedValue(new Error('Import job not found'));
      renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=99' });
      await vi.waitFor(() => expect(api.getImportJob).toHaveBeenCalledTimes(1));
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getImportJob).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not announce an old job that was already finished', async () => {
    api.getImportJob.mockResolvedValue(job({ status: 'done', done: 2, items: [] }));
    renderWithProviders(<BulkImportPage />, { route: '/hats/import?job=7' });

    expect(await screen.findByRole('button', { name: 'Done — go to hats' })).toBeInTheDocument();
    expect(screen.queryByText(/Import finished/)).not.toBeInTheDocument();
  });
});
