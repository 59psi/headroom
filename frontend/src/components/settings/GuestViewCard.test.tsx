import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { GuestViewCard } from './GuestViewCard';
import * as api from '../../api/settings';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});

const mocked = vi.mocked(api);

/** A promise the test settles by hand, to look at the in-flight state. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('GuestViewCard', () => {
  it('never draws the switch — or an "Off" — before the status has loaded', async () => {
    const load = deferred<{ enabled: boolean }>();
    mocked.getGuestView.mockReturnValue(load.promise);
    renderWithProviders(<GuestViewCard />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.queryByText('Off')).not.toBeInTheDocument();

    load.resolve({ enabled: false });
    expect(await screen.findByRole('switch', { name: 'Allow guest browsing' }))
      .toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText('Off')).toBeInTheDocument();
  });

  it('applies on flip, before the server answers, and says so when it has', async () => {
    const user = userEvent.setup();
    mocked.getGuestView.mockResolvedValue({ enabled: false });
    const save = deferred<{ enabled: boolean }>();
    mocked.setGuestView.mockReturnValue(save.promise);
    renderWithProviders(<GuestViewCard />);

    const sw = await screen.findByRole('switch', { name: 'Allow guest browsing' });
    await user.click(sw);

    // Optimistic: on, with the pill agreeing, while the PUT is still out.
    expect(mocked.setGuestView).toHaveBeenCalledWith(true);
    expect(sw).toHaveAttribute('aria-checked', 'true');
    expect(sw).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('On')).toBeInTheDocument();

    mocked.getGuestView.mockResolvedValue({ enabled: true });
    save.resolve({ enabled: true });
    expect(await screen.findByText('Guest browsing on')).toBeInTheDocument(); // toast
    expect(sw).toHaveAttribute('aria-checked', 'true');
  });

  it('ignores a second flip while the first is still saving', async () => {
    const user = userEvent.setup();
    mocked.getGuestView.mockResolvedValue({ enabled: false });
    mocked.setGuestView.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<GuestViewCard />);

    const sw = await screen.findByRole('switch', { name: 'Allow guest browsing' });
    await user.click(sw);
    await user.click(sw);

    expect(mocked.setGuestView).toHaveBeenCalledTimes(1);
    expect(sw).toHaveAttribute('aria-checked', 'true');
  });

  it('snaps back and shows the reason when the save fails', async () => {
    const user = userEvent.setup();
    // The refetch after the failure never answers, so the only thing that can
    // put the switch back is the rollback itself — not a fresh server read.
    mocked.getGuestView
      .mockResolvedValueOnce({ enabled: false })
      .mockReturnValue(new Promise(() => {}));
    mocked.setGuestView.mockRejectedValue(new Error('Admin only'));
    renderWithProviders(<GuestViewCard />);

    const sw = await screen.findByRole('switch', { name: 'Allow guest browsing' });
    await user.click(sw);

    expect(await screen.findByRole('alert')).toHaveTextContent('Admin only');
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'false'));
    expect(screen.getByText('Off')).toBeInTheDocument();
    // An error is reported in place, not as a success toast.
    expect(screen.queryByText('Guest browsing on')).not.toBeInTheDocument();
  });

  it('reads "Unknown", not "Off", when the status cannot be loaded — and can retry', async () => {
    const user = userEvent.setup();
    mocked.getGuestView.mockRejectedValueOnce(new Error('Server error'));
    renderWithProviders(<GuestViewCard />);

    expect(await screen.findByText('Unknown')).toBeInTheDocument();
    expect(screen.getByText('Unknown — could not load this setting')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Allow guest browsing' })).toBeDisabled();
    expect(screen.queryByText('Off')).not.toBeInTheDocument();
    expect(screen.queryByText(/sign-in required/)).not.toBeInTheDocument();

    mocked.getGuestView.mockResolvedValueOnce({ enabled: true });
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('On')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Allow guest browsing' })).toBeEnabled();
  });

  it('prints what guests see and what is never sent', async () => {
    mocked.getGuestView.mockResolvedValue({ enabled: false });
    renderWithProviders(<GuestViewCard />);
    await screen.findByRole('switch');

    for (const item of ['Photos', 'Brand, model and style', 'Colors', 'Where each hat lives']) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    for (const item of ['Prices and values', 'What you paid', 'What anything sold for', 'Your notes', "Hats you've disposed of"]) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    expect(screen.getByText(/never sent\. Guests cannot change anything/)).toBeInTheDocument();
  });

  it('says what turning it on does while it is still off', async () => {
    // The reader deciding whether to flip it is the one looking at "Off".
    mocked.getGuestView.mockResolvedValue({ enabled: false });
    renderWithProviders(<GuestViewCard />);
    await screen.findByRole('switch');

    expect(screen.getByText(/“browse as a guest” link to the login screen/)).toBeInTheDocument();
  });
});
