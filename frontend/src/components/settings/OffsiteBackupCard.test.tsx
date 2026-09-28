/**
 * The card exists to answer one question — is there a copy of this collection
 * anywhere other than the box it is running on — and to let you set that up
 * without handing the browser a shell.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderWithProviders } from '../../test/utils';
import { OffsiteBackupCard } from './OffsiteBackupCard';
import * as api from '../../api/settings';
import type { BackupUploadProvider, BackupUploadStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getBackupUpload: vi.fn(),
    setBackupUpload: vi.fn(),
    clearBackupUpload: vi.fn(),
    testBackupUpload: vi.fn(),
  };
});

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
    last_upload_at: null, last_upload_ok: null, last_upload_name: null,
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

    expect(await screen.findByText(/nothing has ever been uploaded/i)).toBeInTheDocument();
  });

  it('names the date, time AND file of the last upload', async () => {
    // "It ran" is not an answer anyone can act on. The card has to say WHEN
    // and WHICH ARCHIVE, or it cannot answer the only question it exists for:
    // does a copy of my data exist off this card, and how old is it.
    mocked.getBackupUpload.mockResolvedValue(status({
      configured: true, provider: 'synology',
      destination: 'brandon@10.0.111.10::home/Backups/headroom',
      last_upload_at: '2026-08-26T05:41:08Z', last_upload_ok: true,
      last_upload_name: 'headroom-backup-2026-08-26T05-41-08Z.tar.gz',
      upload_successes: 9, upload_failures: 0,
    }));

    renderWithProviders(<OffsiteBackupCard />);

    expect(
      await screen.findByText(/headroom-backup-2026-08-26T05-41-08Z\.tar\.gz/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Last uploaded/i)).toBeInTheDocument();
    // And it must NOT claim nothing has happened.
    expect(screen.queryByText(/nothing has ever been uploaded/i)).not.toBeInTheDocument();
  });

  it('reports a failing upload rather than just a count', async () => {
    mocked.getBackupUpload.mockResolvedValue(status({
      configured: true, provider: 'rclone', destination: 'box:Headroom',
      last_upload_at: '2026-08-23T10:00:00Z', last_upload_ok: false,
      last_upload_error: 'exit 1: directory not found', upload_successes: 3, upload_failures: 2,
    }));

    renderWithProviders(<OffsiteBackupCard />);

    // Was an all-caps "FAILED" in the sentence; the sentence is now sentence
    // case and the header pill carries the state in one word as well.
    expect(await screen.findByText(/Last attempt failed/i)).toBeInTheDocument();
    expect(screen.getByText('Failing')).toBeInTheDocument();
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

    // Configured, the form is folded away — and the steps for the SAVED
    // provider are still one tap from the summary, without opening it.
    await user.click(await screen.findByRole("button", { name: /How to finish setting up Synology/i }));
    expect(await screen.findByText(/Enable the rsync service in DSM/i)).toBeInTheDocument();

    // And opening the form lands on the saved provider, not on rclone.
    await user.click(screen.getByRole("button", { name: "Change destination" }));
    expect(screen.getByLabelText("Upload provider")).toHaveValue("synology");
  });

  it('leads with the saved destination and folds the form behind "Change destination"', async () => {
    // Changing where backups go is a rare errand; the fields for it were
    // most of the card on every visit in between.
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );
    renderWithProviders(<OffsiteBackupCard />);

    expect(await screen.findByText('box:Headroom')).toBeInTheDocument();
    expect(screen.getByText('Cloud storage (rclone)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Upload destination')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Change destination' }));
    expect(screen.getByLabelText('Upload destination')).toHaveFocus();

    // Cancel folds it again without saving anything.
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('Upload destination')).not.toBeInTheDocument();
    expect(mocked.setBackupUpload).not.toHaveBeenCalled();
  });

  it('shows the saved state the moment the server accepts it, and says so', async () => {
    // The PUT answers with the full status; the card uses it directly rather
    // than waiting on a second round trip to find out what it just did.
    const user = userEvent.setup();
    const saved = status({ configured: true, provider: 'rclone', destination: 'box:Headroom' });
    // The refetch that follows never answers, so what the card shows after
    // saving can only have come from the PUT's own response.
    mocked.getBackupUpload
      .mockResolvedValueOnce(status())
      .mockReturnValue(new Promise(() => {}));
    mocked.setBackupUpload.mockResolvedValue(saved);
    renderWithProviders(<OffsiteBackupCard />);

    await user.type(await screen.findByLabelText('Upload destination'), 'box:Headroom');
    await user.keyboard('{Enter}'); // Enter in the field submits, like Save

    expect(mocked.setBackupUpload).toHaveBeenCalledWith('rclone', 'box:Headroom');
    expect(await screen.findByText('Off-site backup saved')).toBeInTheDocument();
    expect(await screen.findByText('box:Headroom')).toBeInTheDocument();
    expect(screen.queryByLabelText('Upload destination')).not.toBeInTheDocument();
  });

  it('clears a rejected-destination error as soon as you type again', async () => {
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(status());
    mocked.setBackupUpload.mockRejectedValue(new Error('Destination may not start with a flag'));
    renderWithProviders(<OffsiteBackupCard />);

    const field = await screen.findByLabelText('Upload destination');
    await user.type(field, '--x');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/may not start with a flag/i)).toBeInTheDocument();

    await user.type(field, 'y');
    expect(screen.queryByText(/may not start with a flag/i)).not.toBeInTheDocument();
  });

  it('asks before turning it off, and Cancel changes nothing', async () => {
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );
    renderWithProviders(<OffsiteBackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Turn off' }));
    const dialog = await screen.findByRole('alertdialog', { name: /Turn off off-site backup/i });
    expect(within(dialog).getByText(/every copy stays on this machine/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(mocked.clearBackupUpload).not.toHaveBeenCalled();
    expect(screen.getByText('box:Headroom')).toBeInTheDocument();
  });

  it('turns it off only once confirmed, and shows the result in place', async () => {
    const user = userEvent.setup();
    // As above: the refetch never answers, so the unconfigured state on
    // screen afterwards is the DELETE's own response.
    mocked.getBackupUpload
      .mockResolvedValueOnce(status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }))
      .mockReturnValue(new Promise(() => {}));
    mocked.clearBackupUpload.mockResolvedValue(status());
    renderWithProviders(<OffsiteBackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Turn off' }));
    const dialog = await screen.findByRole('alertdialog', { name: /Turn off off-site backup/i });
    expect(mocked.clearBackupUpload).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Turn off' }));

    expect(mocked.clearBackupUpload).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Off-site backup turned off')).toBeInTheDocument();
    expect(await screen.findByText(/only copies are on this machine/i)).toBeInTheDocument();
  });

  it.each([
    ['Not set', status()],
    ['Untested', status({ configured: true, provider: 'rclone', destination: 'box:H' })],
    ['Working', status({
      configured: true, provider: 'rclone', destination: 'box:H',
      last_upload_at: '2026-08-26T05:41:08Z', last_upload_ok: true, upload_successes: 1,
    })],
    ['Can’t run', status({
      configured: true, provider: 'rclone', destination: 'box:H', binary_available: false,
    })],
  ])('sums the state up as "%s" in the header', async (word, s) => {
    mocked.getBackupUpload.mockResolvedValue(s);
    const { container } = renderWithProviders(<OffsiteBackupCard />);
    await screen.findByText(word);
    expect(container.querySelector('.hr-panel-head .hr-pill')).toHaveTextContent(word);
  });

  it('reports a failed test in place, without a success toast', async () => {
    const user = userEvent.setup();
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );
    mocked.testBackupUpload.mockResolvedValue({ ok: false, detail: 'exit 23: permission denied' });
    renderWithProviders(<OffsiteBackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Test now' }));

    expect(await screen.findByText(/permission denied/)).toBeInTheDocument();
    expect(screen.queryByText('Test upload finished')).not.toBeInTheDocument();
  });

  it('never shows the empty state while the status is still loading', async () => {
    // "Your only copies are on this machine" flashed at someone who HAS an
    // off-site copy would be the wrong alarm at the wrong moment.
    let release!: (s: BackupUploadStatus) => void;
    mocked.getBackupUpload.mockReturnValue(new Promise(r => { release = r; }));
    renderWithProviders(<OffsiteBackupCard />);

    expect(screen.getByText('Off-site backup')).toBeInTheDocument();
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText(/only copies are on this machine/i)).not.toBeInTheDocument();

    release(status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }));
    expect(await screen.findByText('box:Headroom')).toBeInTheDocument();
    expect(screen.queryByText(/only copies are on this machine/i)).not.toBeInTheDocument();
  });

  it('can be set up again straight after turning it off', async () => {
    // The server's DELETE stores the provider as "" (not null), so every
    // status after a turn-off reads `provider: ""`. The card used to take
    // that empty string as the choice — no option selected, no shape hint,
    // no setup steps — and Save sent `provider: ""` to be rejected.
    const user = userEvent.setup();
    const cleared = status({ provider: '', destination: '' });
    mocked.getBackupUpload
      .mockResolvedValueOnce(status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }))
      .mockResolvedValue(cleared);
    mocked.clearBackupUpload.mockResolvedValue(cleared);
    mocked.setBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Other' }),
    );
    renderWithProviders(<OffsiteBackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Turn off' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Turn off' }));

    const field = await screen.findByLabelText('Upload destination');
    expect(screen.getByLabelText('Upload provider')).toHaveValue('rclone');
    expect(screen.getByText('remote:path')).toBeInTheDocument(); // the shape hint
    await user.type(field, 'box:Other');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(mocked.setBackupUpload).toHaveBeenCalledWith('rclone', 'box:Other');
  });

  it('still states the consequence when asked outside the in-app dialog', async () => {
    // Rendered bare (no DialogProvider) the confirm falls back to
    // window.confirm, which carries only text: an element body would ask the
    // bare question and drop "every copy stays on this machine".
    const user = userEvent.setup();
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false);
    mocked.getBackupUpload.mockResolvedValue(
      status({ configured: true, provider: 'rclone', destination: 'box:Headroom' }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><OffsiteBackupCard /></QueryClientProvider>);

    await user.click(await screen.findByRole('button', { name: 'Turn off' }));

    expect(ask).toHaveBeenCalledWith(expect.stringMatching(/every copy stays on this machine/));
    expect(mocked.clearBackupUpload).not.toHaveBeenCalled();
    ask.mockRestore();
  });

  describe('keeps keyboard focus when the pressed button goes away', () => {
    // Cancel, Save and Turn off each unmount the button that was pressed; a
    // removed focused element drops focus to <body>, i.e. the top of the page.
    const configured = status({ configured: true, provider: 'rclone', destination: 'box:Headroom' });

    it('Cancel returns it to "Change destination"', async () => {
      const user = userEvent.setup();
      mocked.getBackupUpload.mockResolvedValue(configured);
      renderWithProviders(<OffsiteBackupCard />);

      await user.click(await screen.findByRole('button', { name: 'Change destination' }));
      await user.click(screen.getByRole('button', { name: 'Cancel' }));

      expect(screen.getByRole('button', { name: 'Change destination' })).toHaveFocus();
    });

    it('Save returns it to "Change destination"', async () => {
      const user = userEvent.setup();
      mocked.getBackupUpload.mockResolvedValue(configured);
      mocked.setBackupUpload.mockResolvedValue(
        status({ configured: true, provider: 'rclone', destination: 'box:Other' }),
      );
      renderWithProviders(<OffsiteBackupCard />);

      await user.click(await screen.findByRole('button', { name: 'Change destination' }));
      await user.type(screen.getByLabelText('Upload destination'), 'box:Other');
      await user.click(screen.getByRole('button', { name: 'Save' }));

      expect(await screen.findByText('Off-site backup saved')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Change destination' })).toHaveFocus();
    });

    it('Turn off moves it to the provider, the first field of the form it opens', async () => {
      const user = userEvent.setup();
      mocked.getBackupUpload
        .mockResolvedValueOnce(configured)
        .mockReturnValue(new Promise(() => {}));
      mocked.clearBackupUpload.mockResolvedValue(status());
      renderWithProviders(<OffsiteBackupCard />);

      await user.click(await screen.findByRole('button', { name: 'Turn off' }));
      await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Turn off' }));

      expect(await screen.findByText('Off-site backup turned off')).toBeInTheDocument();
      expect(screen.getByLabelText('Upload provider')).toHaveFocus();
    });

    it('does not pull focus back once the person has moved on', async () => {
      const user = userEvent.setup();
      let answer!: (s: BackupUploadStatus) => void;
      mocked.getBackupUpload.mockResolvedValue(configured);
      mocked.setBackupUpload.mockReturnValue(new Promise(r => { answer = r; }));
      renderWithProviders(
        <>
          <OffsiteBackupCard />
          <input aria-label="Somewhere else" />
        </>,
      );

      await user.click(await screen.findByRole('button', { name: 'Change destination' }));
      await user.type(screen.getByLabelText('Upload destination'), 'box:Other{Enter}');
      const elsewhere = screen.getByLabelText('Somewhere else');
      await user.click(elsewhere);
      answer(status({ configured: true, provider: 'rclone', destination: 'box:Other' }));

      expect(await screen.findByText('Off-site backup saved')).toBeInTheDocument();
      expect(elsewhere).toHaveFocus();
    });
  });
});
