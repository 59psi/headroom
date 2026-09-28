/**
 * The Backups card answers two questions the file list alone cannot: is the
 * scheduler still working, and can I get a copy out right now.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { BackupsCard } from './BackupsCard';
import * as api from '../../api/settings';
import type { BackupHealth, BackupInfo } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  const real = await importOriginal<typeof import('../../api/settings')>();
  return {
    ...stubAll(real),
    listBackups: vi.fn(),
    getBackupHealth: vi.fn(),
    // The real URL builder: the hrefs are part of what is under test.
    backupDownloadUrl: real.backupDownloadUrl,
  };
});

const mocked = vi.mocked(api);

/** The real payload shape — pydantic serializes every field, defaults too. */
function health(over: Partial<BackupHealth> = {}): BackupHealth {
  return {
    enabled: true, running: true,
    last_attempt_at: null, last_success_at: null, last_success_derived: false,
    last_error: null, last_skip_reason: null, consecutive_failures: 0, ...over,
  };
}

function file(i: number): BackupInfo {
  const at = new Date(Date.UTC(2026, 8, 20 - i, 4, 0, 0)).toISOString();
  return {
    filename: `headroom-backup-2026-09-${String(20 - i).padStart(2, '0')}T04-00-00Z.tar.gz`,
    size_bytes: 12 * 1024 * 1024,
    created_at: at,
  };
}

function headerPill(container: HTMLElement) {
  return container.querySelector('.hr-panel-head .hr-pill');
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listBackups.mockResolvedValue([file(0), file(1)]);
  mocked.getBackupHealth.mockResolvedValue(health({ last_success_at: new Date().toISOString() }));
});

describe('BackupsCard', () => {
  it('offers the full archive as the main action and the database alone beside it', async () => {
    renderWithProviders(<BackupsCard />);

    const full = await screen.findByRole('link', { name: /Download full backup/ });
    const db = screen.getByRole('link', { name: /Database only/ });
    expect(full).toHaveAttribute('href', '/api/admin/backup');
    expect(full).toHaveClass('btn-primary');
    expect(db).toHaveAttribute('href', '/api/admin/backup?include_uploads=false');
    expect(db).not.toHaveClass('btn-primary');
  });

  it.each<[string, Partial<BackupHealth>]>([
    ['Healthy', {}],
    ['Stopped', { running: false }],
    ['Failing', { consecutive_failures: 2 }],
    ['Off', { enabled: false }],
  ])('sums the scheduler up as "%s"', async (word, over) => {
    mocked.getBackupHealth.mockResolvedValue(health(over));
    const { container } = renderWithProviders(<BackupsCard />);
    await screen.findByText(word);
    expect(headerPill(container)).toHaveTextContent(word);
  });

  it('ranks a stopped scheduler above a failure count', async () => {
    // No further attempt is coming to change a stopped task's count.
    mocked.getBackupHealth.mockResolvedValue(health({ running: false, consecutive_failures: 3 }));
    const { container } = renderWithProviders(<BackupsCard />);

    expect(await screen.findByText(/scheduler is not running/i)).toBeInTheDocument();
    expect(screen.queryByText(/in a row failed/)).not.toBeInTheDocument();
    expect(headerPill(container)).toHaveTextContent('Stopped');
  });

  it('says how many in a row failed, and shows the error', async () => {
    mocked.getBackupHealth.mockResolvedValue(health({
      consecutive_failures: 2, last_error: 'OSError: No space left on device',
    }));
    renderWithProviders(<BackupsCard />);

    expect(await screen.findByText('2 backups in a row failed.')).toBeInTheDocument();
    expect(screen.getByText(/No space left on device/)).toBeInTheDocument();
  });

  it('explains an old snapshot on an unchanged collection, and when it last checked', async () => {
    // A change-gated scheduler's last SUCCESS stops advancing by design; the
    // last ATTEMPT is what tells a healthy idle scheduler from a dead one.
    mocked.getBackupHealth.mockResolvedValue(health({
      last_success_at: new Date(Date.now() - 5 * 86_400_000).toISOString(),
      last_attempt_at: new Date(Date.now() - 20 * 60_000).toISOString(),
      last_skip_reason: 'No changes since the last backup.',
    }));
    renderWithProviders(<BackupsCard />);

    expect(await screen.findByText(/No changes since the last backup\./)).toBeInTheDocument();
    expect(screen.getByText('5 days ago')).toBeInTheDocument();
    expect(screen.getByText('20 min ago')).toBeInTheDocument();
  });

  it('says when the last success came from a file rather than a recorded run', async () => {
    mocked.getBackupHealth.mockResolvedValue(health({
      last_success_at: new Date().toISOString(), last_success_derived: true,
    }));
    renderWithProviders(<BackupsCard />);
    expect(await screen.findByText(/from the file on disk/i)).toBeInTheDocument();
  });

  it('lists the newest five snapshots and the rest on request', async () => {
    const user = userEvent.setup();
    mocked.listBackups.mockResolvedValue(Array.from({ length: 7 }, (_, i) => file(i)));
    renderWithProviders(<BackupsCard />);

    const list = await screen.findByRole('list', { name: 'Scheduled snapshots' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    // Newest first, as the server sends them.
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent(file(0).filename);
    expect(screen.getByText('7')).toBeInTheDocument(); // the "Snapshots kept" tile

    await user.click(screen.getByRole('button', { name: /Show all 7/ }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(7);

    await user.click(screen.getByRole('button', { name: 'Show fewer' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
  });

  it('says there are no snapshots only once the list has loaded empty', async () => {
    let release!: (files: BackupInfo[]) => void;
    mocked.listBackups.mockReturnValue(new Promise(r => { release = r; }));
    renderWithProviders(<BackupsCard />);

    // Title stays, body is a skeleton — never the empty state mid-load.
    expect(screen.getByText('Backups')).toBeInTheDocument();
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText(/No scheduled snapshots/)).not.toBeInTheDocument();

    release([]);
    expect(await screen.findByText(/No scheduled snapshots on disk yet/)).toBeInTheDocument();
  });

  it('reports a failed fetch instead of an empty list', async () => {
    mocked.listBackups.mockRejectedValue(new Error('Backups directory unreadable'));
    renderWithProviders(<BackupsCard />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Backups directory unreadable');
    expect(screen.queryByText(/No scheduled snapshots/)).not.toBeInTheDocument();
  });

  it('acknowledges a download tap, since the browser gives the page no event', async () => {
    const user = userEvent.setup();
    renderWithProviders(<BackupsCard />);
    const db = await screen.findByRole('link', { name: /Database only/ });
    // jsdom does not navigate; the click handler is what is under test.
    db.addEventListener('click', e => e.preventDefault());

    await user.click(db);

    expect(await screen.findByText(/Preparing the download/)).toBeInTheDocument();
  });
});
