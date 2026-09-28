import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ShareLinksCard } from './ShareLinksCard';
import * as auth from '../../api/auth';
import * as clipboard from '../../lib/clipboard';
import type { ShareLinkInfo } from '../../api/auth';

vi.mock('../../api/auth', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});

vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn(async () => true) }));

const mocked = vi.mocked(auth);
const copyText = vi.mocked(clipboard.copyText);

const DAY = 86_400_000;

function link(over: Partial<ShareLinkInfo> = {}): ShareLinkInfo {
  return {
    id: 1,
    token: 'tok-1',
    label: 'Group chat',
    url_path: '/share/tok-1',
    created_at: '2026-09-01T00:00:00Z',
    expires_at: new Date(Date.now() + 10 * DAY).toISOString(),
    revoked_at: null,
    ...over,
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  copyText.mockResolvedValue(true);
});

describe('ShareLinksCard', () => {
  it('lists live links with their expiry, and leaves revoked ones out', async () => {
    mocked.listShareLinks.mockResolvedValue([
      link(),
      link({ id: 2, label: 'Forever', token: 't2', url_path: '/share/t2', expires_at: null }),
      link({ id: 3, label: 'Gone', token: 't3', url_path: '/share/t3', revoked_at: '2026-09-02T00:00:00Z' }),
    ]);
    renderWithProviders(<ShareLinksCard />);

    expect(await screen.findByText('Group chat')).toBeInTheDocument();
    expect(screen.getByText('expires in 10 days')).toBeInTheDocument();
    expect(screen.getByText('Forever')).toBeInTheDocument();
    expect(screen.getByText('never expires')).toBeInTheDocument();
    expect(screen.queryByText('Gone')).not.toBeInTheDocument();
    expect(screen.getByText('2 active')).toBeInTheDocument();
  });

  it('does not count an expired link as active', async () => {
    mocked.listShareLinks.mockResolvedValue([
      link({ expires_at: new Date(Date.now() - DAY).toISOString() }),
    ]);
    renderWithProviders(<ShareLinksCard />);

    expect(await screen.findByText('expired')).toBeInTheDocument();
    expect(screen.getByText('None active')).toBeInTheDocument();
  });

  it('says "No active share links" only for a successful empty answer', async () => {
    mocked.listShareLinks.mockRejectedValueOnce(new Error('Server error'));
    renderWithProviders(<ShareLinksCard />);

    expect(await screen.findByText(/Could not load share links/)).toBeInTheDocument();
    expect(screen.queryByText('No active share links.')).not.toBeInTheDocument();
    expect(screen.queryByText('None active')).not.toBeInTheDocument();
  });

  it('copies the full URL and confirms with a toast', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([link()]);
    renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Copy link: Group chat' }));

    expect(copyText).toHaveBeenCalledWith(`${window.location.origin}/share/tok-1`);
    expect(await screen.findByText('Link copied')).toBeInTheDocument();
  });

  it('keeps the link when the revoke is canceled', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([link()]);
    renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Revoke link: Group chat' }));
    const dialog = await screen.findByRole('alertdialog');
    // The original warning, now in the in-app dialog rather than window.confirm.
    expect(within(dialog).getByText('Anyone holding it loses access.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(mocked.revokeShareLink).not.toHaveBeenCalled();
    expect(screen.getByText('Group chat')).toBeInTheDocument();
  });

  it('removes the link as soon as the revoke is confirmed, before the server answers', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([link(), link({ id: 2, label: 'Keep me', token: 't2', url_path: '/share/t2' })]);
    const revoke = deferred<void>();
    mocked.revokeShareLink.mockReturnValue(revoke.promise);
    renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Revoke link: Group chat' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Revoke link' }));

    expect(mocked.revokeShareLink).toHaveBeenCalledWith(1);
    await waitFor(() => expect(screen.queryByText('Group chat')).not.toBeInTheDocument());
    expect(screen.getByText('Keep me')).toBeInTheDocument();

    mocked.listShareLinks.mockResolvedValue([
      link({ revoked_at: new Date().toISOString() }),
      link({ id: 2, label: 'Keep me', token: 't2', url_path: '/share/t2' }),
    ]);
    revoke.resolve();
    expect(await screen.findByText('Link revoked')).toBeInTheDocument();
    expect(screen.queryByText('Group chat')).not.toBeInTheDocument();
  });

  it('puts the link back, with the reason, when the revoke fails', async () => {
    const user = userEvent.setup();
    // The refetch after the failure never answers, so only the rollback can
    // bring the row back.
    mocked.listShareLinks
      .mockResolvedValueOnce([link()])
      .mockReturnValue(new Promise(() => {}));
    mocked.revokeShareLink.mockRejectedValue(new Error('Database is locked'));
    renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Revoke link: Group chat' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Revoke link' }));

    expect(await screen.findByText('Database is locked')).toBeInTheDocument();
    expect(screen.getByText('Group chat')).toBeInTheDocument();
    expect(screen.queryByText('Link revoked')).not.toBeInTheDocument();
  });

  it('rolls back only the failed revoke, not a row something else changed meanwhile', async () => {
    // B's revoke is out when another write marks A revoked (a refetch that
    // landed, another device). A whole-list snapshot taken when B started
    // would bring A back on B's failure.
    const user = userEvent.setup();
    mocked.listShareLinks
      .mockResolvedValueOnce([
        link({ id: 1, label: 'A' }),
        link({ id: 2, label: 'B', token: 't2', url_path: '/share/t2' }),
      ])
      .mockReturnValue(new Promise(() => {}));
    const revokeB = deferred<void>();
    mocked.revokeShareLink.mockReturnValueOnce(revokeB.promise);
    const { client } = renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Revoke link: B' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Revoke link' }));
    await waitFor(() => expect(screen.queryByText('B')).not.toBeInTheDocument());

    client.setQueryData<ShareLinkInfo[]>(['share-links'], list =>
      list?.map(l => (l.id === 1 ? { ...l, revoked_at: new Date().toISOString() } : l)));
    await waitFor(() => expect(screen.queryByText('A')).not.toBeInTheDocument());

    revokeB.reject(new Error('Database is locked'));
    expect(await screen.findByText('B')).toBeInTheDocument();
    expect(screen.queryByText('A')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Database is locked');
  });

  it('revokes one link at a time, so a failure is never hidden behind a later revoke', async () => {
    // The mutation reports only its latest call: with two revokes in flight,
    // the first one's failure put its row back without a word.
    const user = userEvent.setup();
    mocked.listShareLinks
      .mockResolvedValueOnce([
        link({ id: 1, label: 'A' }),
        link({ id: 2, label: 'B', token: 't2', url_path: '/share/t2' }),
      ])
      .mockReturnValue(new Promise(() => {}));
    const revokeB = deferred<void>();
    mocked.revokeShareLink.mockReturnValueOnce(revokeB.promise);
    renderWithProviders(<ShareLinksCard />);

    await user.click(await screen.findByRole('button', { name: 'Revoke link: B' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Revoke link' }));
    await waitFor(() => expect(screen.queryByText('B')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Revoke link: A' })).toBeDisabled();

    revokeB.reject(new Error('Database is locked'));
    expect(await screen.findByText('B')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Database is locked');
    expect(screen.getByRole('button', { name: 'Revoke link: A' })).toBeEnabled();
    expect(mocked.revokeShareLink).toHaveBeenCalledTimes(1);
  });

  it('creates with the default 30-day expiry and a fallback label', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([]);
    mocked.createShareLink.mockResolvedValue({ id: 9, token: 'new', url_path: '/share/new' });
    renderWithProviders(<ShareLinksCard />);
    await screen.findByText('No active share links.');

    await user.click(screen.getByRole('button', { name: 'Create link' }));

    expect(mocked.createShareLink).toHaveBeenCalledWith('Shared collection', 30);
    expect(await screen.findByText('Link created')).toBeInTheDocument();
  });

  it('creates a never-expiring link only when asked, warns about it, and clears the label', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([]);
    mocked.createShareLink.mockResolvedValue({ id: 9, token: 'new', url_path: '/share/new' });
    renderWithProviders(<ShareLinksCard />);
    await screen.findByText('No active share links.');

    const label = screen.getByRole('textbox', { name: 'Share link label' });
    await user.type(label, '  Cousins  ');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Link expires after' }), 'Never');
    expect(screen.getByText(/never expires works until you revoke it/)).toBeInTheDocument();
    // Enter in the label field submits, like the button.
    await user.type(label, '{Enter}');

    expect(mocked.createShareLink).toHaveBeenCalledWith('Cousins', null);
    await waitFor(() => expect(label).toHaveValue(''));
  });

  it("offers to copy the new link from the confirmation", async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([]);
    mocked.createShareLink.mockResolvedValue({ id: 9, token: 'new', url_path: '/share/new' });
    renderWithProviders(<ShareLinksCard />);
    await screen.findByText('No active share links.');

    await user.click(screen.getByRole('button', { name: 'Create link' }));
    const toast = (await screen.findByText('Link created')).closest('.hr-toast') as HTMLElement;
    await user.click(within(toast).getByRole('button', { name: 'Copy link' }));

    expect(copyText).toHaveBeenCalledWith(`${window.location.origin}/share/new`);
  });

  it('shows a failed create in place', async () => {
    const user = userEvent.setup();
    mocked.listShareLinks.mockResolvedValue([]);
    mocked.createShareLink.mockRejectedValue(new Error('Label too long'));
    renderWithProviders(<ShareLinksCard />);
    await screen.findByText('No active share links.');

    await user.click(screen.getByRole('button', { name: 'Create link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Label too long');
  });
});
