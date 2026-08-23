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

vi.mock('../../api/settings', () => ({
  getBackupUpload: vi.fn(),
  setBackupUpload: vi.fn(),
  clearBackupUpload: vi.fn(),
  testBackupUpload: vi.fn(),
}));

const mocked = vi.mocked(api);

function status(over = {}) {
  return {
    configured: false, provider: null, destination: null, from_environment: false,
    available_providers: ['rclone'], last_upload_at: null, last_upload_ok: null,
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
});
