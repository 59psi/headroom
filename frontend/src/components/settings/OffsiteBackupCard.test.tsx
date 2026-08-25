/**
 * The card exists to answer one question — is there a copy of this collection
 * anywhere other than the box it is running on — and to let you set that up
 * without handing the browser a shell.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { OffsiteBackupCard } from './OffsiteBackupCard';
import * as api from '../../api/settings';
import type { BackupUploadProvider, BackupUploadStatus } from '../../types';

vi.mock('../../api/settings', () => ({
  getBackupUpload: vi.fn(),
  setBackupUpload: vi.fn(),
  clearBackupUpload: vi.fn(),
  testBackupUpload: vi.fn(),
}));

const mocked = vi.mocked(api);

function aProvider(over: Partial<BackupUploadProvider> = {}): BackupUploadProvider {
  return {
    name: 'rclone', label: 'Cloud storage (rclone)', destination_hint: 'remote:path',
    example: 'box:Headroom-Backups', setup: ['Run rclone config on the Pi.'],
    secret_env: null, binary: 'rclone', binary_available: true, ...over,
  };
}

const PROVIDERS = [
  aProvider(),
  aProvider({
    name: 'rsync', label: 'rsync over SSH', destination_hint: 'user@host:/path',
    example: 'pi@nas.local:/volume1/backups/headroom', binary: 'rsync',
    setup: ['Create an SSH key.', 'Authorize it on the destination.'],
  }),
  aProvider({
    name: 'synology', label: 'Synology NAS (rsync service)',
    destination_hint: 'user@host::module/path',
    example: 'backup@synology.local::NetBackup/headroom', binary: 'rsync',
    secret_env: 'HEADROOM_BACKUP_RSYNC_PASSWORD',
    setup: ['Enable the rsync service in DSM.', 'Add an rsync account.'],
  }),
];

function status(over: Partial<BackupUploadStatus> = {}): BackupUploadStatus {
  return {
    configured: false, provider: null, destination: null, from_environment: false,
    available_providers: PROVIDERS, binary_available: null,
    last_upload_at: null, last_upload_ok: null,
    last_upload_error: null, upload_successes: 0, upload_failures: 0, ...over,
  };
}

beforeEach(() => vi.clearAllMocks());

describe('OffsiteBackupCard', () => {
  it('says plainly when there is no off-site copy', async () => {
    mocked.getBackupUpload.mockResolvedValue(status());

    renderWithProviders(<OffsiteBackupCard />);

    expect(await screen.findByText(/only copies are on this machine/i)).toBeInTheDocument();
  });

  it('sends a provider and a destination, never a command', async () => {
    // The whole safety property, asserted at the boundary the browser owns.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    mocked.setBackupUpload.mockResolvedValue(status({ configured: true }));
    renderWithProviders(<OffsiteBackupCard />);
    await screen.findByLabelText('Upload destination');

    await user.type(screen.getByLabelText('Upload destination'), 'box:Headroom');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(mocked.setBackupUpload).toHaveBeenCalledWith('rclone', 'box:Headroom');
  });

  it("surfaces the server's reason for a rejected destination", async () => {
    // "that is a flag, not a remote" is more use than a generic failure.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    mocked.setBackupUpload.mockRejectedValue(new Error('Destination may not start with a flag'));
    renderWithProviders(<OffsiteBackupCard />);
    await screen.findByLabelText('Upload destination');

    await user.type(screen.getByLabelText('Upload destination'), '--config=/etc/x');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/may not start with a flag/i)).toBeInTheDocument();
  });

  it('distinguishes configured from proven', async () => {
    // Configured is not the same as working, and only one of them will still
    // be true on the day you need the backup.
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );

    renderWithProviders(<OffsiteBackupCard />);

    expect(await screen.findByText(/nothing has been uploaded yet/i)).toBeInTheDocument();
  });

  it('reports a failing upload rather than just a count', async () => {
    mocked.getBackupUpload.mockResolvedValue(status({
      configured: true, provider: 'rclone', destination: 'box:Headroom',
      last_upload_at: '2026-08-23T10:00:00Z', last_upload_ok: false,
      last_upload_error: 'exit 1: directory not found', upload_successes: 3, upload_failures: 2,
    }));

    renderWithProviders(<OffsiteBackupCard />);

    expect(await screen.findByText(/FAILED/)).toBeInTheDocument();
    expect(screen.getByText(/directory not found/)).toBeInTheDocument();
  });

  it('hides the form when the command came from the environment', async () => {
    // Host access set it; a browser must not be able to override that.
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, from_environment: true, provider: 'custom' }),
    );

    renderWithProviders(<OffsiteBackupCard />);
    await screen.findByText(/HEADROOM_BACKUP_UPLOAD_CMD/);

    expect(screen.queryByLabelText('Upload destination')).not.toBeInTheDocument();
  });

  it('tells you how to finish setting up the provider you picked', async () => {
    // The gap between "configured" and "working" is always host-side work.
    // Before this the card could only say which of the two states you were in,
    // never what closed the distance.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    renderWithProviders(<OffsiteBackupCard />);
    // The select renders before the query resolves, so waiting on the select
    // itself finds it empty — wait for an OPTION to exist.
    await screen.findByRole('option', { name: /Synology/ });

    await user.selectOptions(screen.getByLabelText('Upload provider'), 'synology');
    await user.click(screen.getByRole('button', { name: /How to finish setting up/i }));

    expect(await screen.findByText(/Enable the rsync service in DSM/i)).toBeInTheDocument();
    expect(screen.getByText(/Add an rsync account/i)).toBeInTheDocument();
  });

  it('names the environment variable a NAS password comes from', async () => {
    // It is read on the host and never stored, so the card can only name it —
    // which is exactly what someone needs in order to set it.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    renderWithProviders(<OffsiteBackupCard />);
    // The select renders before the query resolves, so waiting on the select
    // itself finds it empty — wait for an OPTION to exist.
    await screen.findByRole('option', { name: /Synology/ });

    await user.selectOptions(screen.getByLabelText('Upload provider'), 'synology');
    await user.click(screen.getByRole('button', { name: /How to finish setting up/i }));

    expect(await screen.findByText('HEADROOM_BACKUP_RSYNC_PASSWORD')).toBeInTheDocument();
  });

  it('shows the destination shape for the chosen provider, not a fixed one', async () => {
    // rclone's remote:path and Synology's user@host::module/path are different
    // transports; one placeholder for both is a wrong hint half the time.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    renderWithProviders(<OffsiteBackupCard />);
    // The select renders before the query resolves, so waiting on the select
    // itself finds it empty — wait for an OPTION to exist.
    await screen.findByRole('option', { name: /Synology/ });

    await user.selectOptions(screen.getByLabelText('Upload provider'), 'rsync');

    expect(screen.getByLabelText('Upload destination')).toHaveAttribute(
      'placeholder', 'pi@nas.local:/volume1/backups/headroom',
    );
  });

  it('warns when the configured provider has no binary in the container', async () => {
    // The failure that otherwise shows up only as an upload that never runs,
    // while the card still reads "configured".
    mocked.getBackupUpload.mockResolvedValue(status({
      configured: true, provider: 'rclone', destination: 'box:Headroom',
      binary_available: false,
    }));

    renderWithProviders(<OffsiteBackupCard />);

    expect(await screen.findByText(/isn.t available inside the container/i)).toBeInTheDocument();
  });

  it('offers a real test once configured', async () => {
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );
    mocked.testBackupUpload.mockResolvedValue({ ok: true, detail: 'Uploaded x.tar.gz with rclone.' });
    renderWithProviders(<OffsiteBackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Test now' }));

    expect(await screen.findByText(/Uploaded x.tar.gz/)).toBeInTheDocument();
  });

  it("shows the setup steps for the provider actually CONFIGURED, not rclone", async () => {
    // The bug: provider state was useState("rclone"), never synced to the
    // saved value. After configuring Synology, reopening Settings showed
    // rclone selected and rclone's steps — so the instructions for the
    // transport in use were in the payload but unreachable, which reads as
    // "you took away the instructions".
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status({
      configured: true, provider: "synology",
      destination: "backup@nas::NetBackup/x",
    }));
    renderWithProviders(<OffsiteBackupCard />);
    await screen.findByRole("option", { name: /Synology/ });

    expect(screen.getByLabelText("Upload provider")).toHaveValue("synology");

    await user.click(screen.getByRole("button", { name: /How to finish setting up/i }));
    expect(await screen.findByText(/Enable the rsync service in DSM/i)).toBeInTheDocument();
  });
});
