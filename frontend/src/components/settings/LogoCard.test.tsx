/**
 * The site logo: shown in the navbar and the home hero, replaced or removed
 * here. The card now answers in place — the picked file appears while it
 * uploads, a removal takes effect before the server replies (and comes back
 * if the server refuses), and a destructive remove asks first in the app's
 * own dialog rather than the browser's.
 */
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { LogoCard } from './LogoCard';
import * as api from '../../api/settings';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getLogo: vi.fn(), uploadLogo: vi.fn(), deleteLogo: vi.fn(),
  };
});

const mocked = vi.mocked(api);
const SET = { logo_path: 'branding/logo.png', version: 1 };
const NONE = { logo_path: null };

function png(name = 'logo.png') {
  return new File(['\x89PNG'], name, { type: 'image/png' });
}

function fileInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[type="file"]')!;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getLogo.mockResolvedValue(SET);
});

describe('LogoCard', () => {
  it('holds its shape while loading and claims no state yet', () => {
    mocked.getLogo.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<LogoCard />);

    expect(screen.getByText('Site logo')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    expect(screen.queryByText('Not set')).not.toBeInTheDocument();
    expect(screen.queryByText(/No logo yet/)).not.toBeInTheDocument();
    // "Upload logo" as the primary button says "there is none" just as
    // loudly, and flipped to "Replace logo" a moment later.
    expect(screen.queryByRole('button', { name: /logo/i })).not.toBeInTheDocument();
  });

  it('does not call a failed fetch "no logo", and still offers the upload', async () => {
    mocked.getLogo.mockRejectedValue(new Error('Server down'));
    renderWithProviders(<LogoCard />);

    expect(await screen.findByText('Server down')).toBeInTheDocument();
    expect(screen.queryByText(/No logo yet/)).not.toBeInTheDocument();
    expect(screen.queryByText('Not set')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload logo' })).toBeEnabled();
  });

  it('shows the current logo, with Replace and Remove', async () => {
    renderWithProviders(<LogoCard />);

    const img = await screen.findByRole('img', { name: 'Current logo' });
    expect(img).toHaveAttribute('src', '/uploads/branding/logo.png?v=1');
    expect(screen.getByText('Set')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Replace logo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument();
  });

  it('offers an upload, and nothing to remove, when there is no logo', async () => {
    mocked.getLogo.mockResolvedValue(NONE);
    renderWithProviders(<LogoCard />);

    expect(await screen.findByText('Not set')).toBeInTheDocument();
    expect(screen.getByText(/No logo yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload logo' })).toHaveClass('btn-primary');
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
  });

  it('uploads the picked file and re-requests the image, whose path never changes', async () => {
    // The server always writes `branding/logo.png`. With the same src the
    // <img> never reloaded, so the card went on showing the logo you had
    // just replaced until the page was reloaded. The server's `version`
    // changes with the file, and it is what the URL now carries.
    const user = userEvent.setup();
    const REPLACED = { logo_path: 'branding/logo.png', version: 2 };
    mocked.uploadLogo.mockResolvedValue(REPLACED);
    const { container } = renderWithProviders(<LogoCard />);
    await screen.findByRole('img', { name: 'Current logo' });
    mocked.getLogo.mockResolvedValue(REPLACED);

    const file = png();
    await user.upload(fileInput(container), file);

    expect(mocked.uploadLogo).toHaveBeenCalledWith(file);
    expect(await screen.findByText('Logo updated')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'Current logo' }))
        .toHaveAttribute('src', '/uploads/branding/logo.png?v=2'));
  });

  it('shows the picked file at once while the upload runs', async () => {
    // jsdom has no object URLs at all; lend it a pair for this test only.
    const blobUrls = URL as unknown as Record<'createObjectURL' | 'revokeObjectURL', unknown>;
    const saved = { create: blobUrls.createObjectURL, revoke: blobUrls.revokeObjectURL };
    blobUrls.createObjectURL = vi.fn(() => 'blob:picked');
    blobUrls.revokeObjectURL = vi.fn();
    onTestFinished(() => {
      blobUrls.createObjectURL = saved.create;
      blobUrls.revokeObjectURL = saved.revoke;
    });
    const user = userEvent.setup();
    mocked.uploadLogo.mockReturnValue(new Promise(() => {}));
    const { container } = renderWithProviders(<LogoCard />);
    await screen.findByRole('img', { name: 'Current logo' });

    await user.upload(fileInput(container), png());

    expect(screen.getByRole('img', { name: 'New logo (uploading)' })).toHaveAttribute('src', 'blob:picked');
    expect(screen.getByText('Uploading')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled();
  });

  it('keeps the old logo and says why when the upload is refused', async () => {
    const user = userEvent.setup();
    mocked.uploadLogo.mockRejectedValue(new Error('Invalid image type'));
    const { container } = renderWithProviders(<LogoCard />);
    await screen.findByRole('img', { name: 'Current logo' });

    await user.upload(fileInput(container), png('notes.png'));

    expect(await screen.findByText('Invalid image type')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Current logo' })).toHaveAttribute('src', '/uploads/branding/logo.png?v=1');
    expect(screen.queryByText('Logo updated')).not.toBeInTheDocument();
  });

  it('takes a file dropped onto the preview', async () => {
    mocked.uploadLogo.mockResolvedValue(SET);
    const { container } = renderWithProviders(<LogoCard />);
    await screen.findByRole('img', { name: 'Current logo' });

    const file = png('dropped.png');
    fireEvent.drop(container.querySelector('.hr-sitelogo-stage')!, { dataTransfer: { files: [file] } });

    await waitFor(() => expect(mocked.uploadLogo).toHaveBeenCalledWith(file));
  });

  it('asks before removing, and Cancel keeps the logo', async () => {
    const user = userEvent.setup();
    renderWithProviders(<LogoCard />);

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Remove logo?' });
    expect(within(dialog).getByRole('button', { name: 'Remove logo' })).toHaveClass('btn-danger');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(mocked.deleteLogo).not.toHaveBeenCalled();
    expect(screen.getByRole('img', { name: 'Current logo' })).toBeInTheDocument();
  });

  it('removes it at once, before the server answers', async () => {
    const user = userEvent.setup();
    let finish!: () => void;
    mocked.deleteLogo.mockReturnValue(new Promise<void>(r => { finish = r; }));
    mocked.getLogo.mockResolvedValueOnce(SET).mockResolvedValue(NONE);
    renderWithProviders(<LogoCard />);

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Remove logo' }));

    // In flight, and the logo — here and in the navbar, which reads the same
    // query — is already gone.
    await waitFor(() => expect(screen.queryByRole('img', { name: 'Current logo' })).not.toBeInTheDocument());
    expect(screen.getByText('Not set')).toBeInTheDocument();

    finish();
    expect(await screen.findByText('Logo removed')).toBeInTheDocument();
  });

  it('puts the logo back, and says why, when the server refuses the removal', async () => {
    const user = userEvent.setup();
    mocked.deleteLogo.mockRejectedValue(new Error('Permission denied'));
    // The follow-up refetch never answers, so only the rollback can restore it.
    mocked.getLogo.mockResolvedValueOnce(SET).mockReturnValue(new Promise(() => {}));
    renderWithProviders(<LogoCard />);

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Remove logo' }));

    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Current logo' })).toBeInTheDocument();
    expect(screen.getByText('Set')).toBeInTheDocument();
    expect(screen.queryByText('Logo removed')).not.toBeInTheDocument();
  });

  it('gives a refused removal its own reason, not an earlier upload’s', async () => {
    // One ErrorNote, first failure wins: without clearing, the stale upload
    // error was the reason printed beside the logo the rollback put back.
    const user = userEvent.setup();
    mocked.uploadLogo.mockRejectedValue(new Error('Invalid image type'));
    mocked.deleteLogo.mockRejectedValue(new Error('Permission denied'));
    const { container } = renderWithProviders(<LogoCard />);
    await screen.findByRole('img', { name: 'Current logo' });

    await user.upload(fileInput(container), png('notes.png'));
    await screen.findByText('Invalid image type');

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    await user.click(screen.getByRole('button', { name: 'Remove logo' }));

    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    expect(screen.queryByText('Invalid image type')).not.toBeInTheDocument();
  });
});
