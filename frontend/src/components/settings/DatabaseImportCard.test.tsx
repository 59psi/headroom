/**
 * The import card's promise is that nothing changes until a person has read
 * what the file holds and said yes: staging shows the preview, and only the
 * confirmed "Replace" applies it.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { DatabaseImportCard } from './DatabaseImportCard';
import * as api from '../../api/settings';
import type { DatabaseImportPreview, RestorePointRead } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  const real = await importOriginal<typeof import('../../api/settings')>();
  return stubAll(real);
});

const mocked = vi.mocked(api);

function point(name: string, kind: RestorePointRead['kind'] = 'archive'): RestorePointRead {
  return { name, kind, size_bytes: 207 * 1024 * 1024, created_at: new Date().toISOString() };
}

function preview(over: Partial<DatabaseImportPreview> = {}): DatabaseImportPreview {
  return {
    token: 'tok-1', source: 'headroom-backup-2026-10-17T06-42-01Z.tar.gz', from_server: true,
    kind: 'archive', version: '2.84.1', hats: 245, disposed_hats: 3, cases: 70, rooms: 3,
    purchases: 294, wear_logs: 12, newest_change_at: new Date().toISOString(),
    photos_included: 245, photos_missing: 0, degraded: false, current_hats: 250,
    keeps_account: true, ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listRestorePoints.mockResolvedValue([
    point('headroom-backup-2026-10-17T06-42-01Z.tar.gz'),
    point('pre-upgrade-2.84.0-to-2.84.1-2026-10-17T23-31-04Z.db', 'pre_upgrade'),
  ]);
  mocked.getStagedImport.mockResolvedValue(null);
});

describe('DatabaseImportCard', () => {
  it('lists what is on the server, saying what each file is', async () => {
    renderWithProviders(<DatabaseImportCard />);

    const list = await screen.findByRole('list', { name: 'Backups on this server' });
    expect(within(list).getByText(/Full backup/)).toBeInTheDocument();
    expect(within(list).getByText(/Saved before an upgrade/)).toBeInTheDocument();
  });

  it('shows what a file holds before anything is replaced', async () => {
    mocked.stageRestorePoint.mockResolvedValue(preview({ photos_included: 240 }));
    renderWithProviders(<DatabaseImportCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Use headroom-backup-2026-10-17T06-42-01Z.tar.gz' }));

    const shown = await screen.findByRole('region', { name: 'What this file holds' });
    expect(within(shown).getByText('245')).toBeInTheDocument();
    expect(within(shown).getByText(/It replaces the 250 hats here/)).toBeInTheDocument();
    expect(within(shown).getByText(/Your sign-in, passkeys, share links and settings stay/)).toBeInTheDocument();
    expect(mocked.stageRestorePoint).toHaveBeenCalledWith('headroom-backup-2026-10-17T06-42-01Z.tar.gz');
    expect(mocked.applyImport).not.toHaveBeenCalled();
  });

  it('applies only after the confirm, and says where the old collection went', async () => {
    mocked.getStagedImport.mockResolvedValue(preview());
    mocked.applyImport.mockResolvedValue({
      source: 'x', hats: 245, photos_restored: 0, snapshot: 'pre-import-2026-10-18T06-00-00Z.db',
      keeps_account: true,
    });
    renderWithProviders(<DatabaseImportCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Replace my collection' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Replace your collection?' });
    expect(mocked.applyImport).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Replace collection' }));

    await waitFor(() => expect(mocked.applyImport).toHaveBeenCalledWith('tok-1'));
    expect(await screen.findByText(/saved as pre-import-2026-10-18T06-00-00Z\.db/)).toBeInTheDocument();
  });

  it('cancelling the confirm changes nothing', async () => {
    mocked.getStagedImport.mockResolvedValue(preview());
    renderWithProviders(<DatabaseImportCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Replace my collection' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Replace your collection?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(mocked.applyImport).not.toHaveBeenCalled();
  });

  it('warns about hats the file has no photo for', async () => {
    mocked.getStagedImport.mockResolvedValue(preview({ kind: 'database', photos_missing: 12 }));
    renderWithProviders(<DatabaseImportCard />);

    expect(await screen.findByText(/12 hats would show no photo/)).toBeInTheDocument();
    expect(screen.getByText(/A full backup \(\.tar\.gz\) carries the photos/)).toBeInTheDocument();
  });

  it('sends a picked file as the upload and shows the server refusing it', async () => {
    mocked.stageImportUpload.mockRejectedValue(
      new Error('That is not a Headroom backup (.tar.gz) or database (.db) file.'),
    );
    const { container } = renderWithProviders(<DatabaseImportCard />);
    await screen.findByRole('list', { name: 'Backups on this server' });

    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, file);

    await waitFor(() => expect(mocked.stageImportUpload).toHaveBeenCalledWith(file));
    expect(await screen.findByRole('alert')).toHaveTextContent('not a Headroom backup');
  });

  it('cancel drops the staged file and goes back to the list', async () => {
    mocked.getStagedImport.mockResolvedValue(preview());
    mocked.discardImport.mockResolvedValue(undefined);
    renderWithProviders(<DatabaseImportCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(mocked.discardImport).toHaveBeenCalledWith('tok-1'));
    expect(await screen.findByRole('list', { name: 'Backups on this server' })).toBeInTheDocument();
  });
});
