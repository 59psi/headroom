/**
 * The hat page's writes: each destructive one asks first in the app's own
 * dialog (Cancel must do nothing), clearing the palette is optimistic and
 * rolls back on failure, and a wear is acknowledged with an Undo only when
 * one was actually added.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useNavigate } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { HatDetailPage } from './HatDetailPage';
import * as hatsApi from '../api/hats';
import type { ColorTag, HatRead } from '../types';

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

const COLORS: ColorTag[] = [
  { color_name: 'navy', general_color: 'blue', hex_value: '#000080', dominance_rank: 1, tier: 'primary' },
  { color_name: 'hot pink', general_color: 'pink', hex_value: '#ff2eb6', dominance_rank: 2, tier: 'accent' },
];

function renderPage(hat: HatRead) {
  mocked.getHat.mockResolvedValue(hat);
  return renderWithProviders(
    <Routes>
      <Route path="/hats/:hatId" element={<HatDetailPage />} />
      <Route path="/hats" element={<div>hats list</div>} />
    </Routes>,
    { route: `/hats/${hat.id}` },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('HatDetailPage — delete', () => {
  it('asks first, and Cancel deletes nothing', async () => {
    const user = userEvent.setup();
    renderPage(hatFixture());

    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Delete this hat?' });
    // The dialog points at the undoable alternative before the permanent one.
    expect(within(dialog).getByText(/mark it disposed instead/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(mocked.deleteHat).not.toHaveBeenCalled();
  });

  it('deletes once confirmed, says so, and returns to the list', async () => {
    const user = userEvent.setup();
    mocked.deleteHat.mockResolvedValue(undefined);
    renderPage(hatFixture());

    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Delete this hat?' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete hat' }));

    await waitFor(() => expect(mocked.deleteHat).toHaveBeenCalledWith(5));
    expect(await screen.findByText('hats list')).toBeInTheDocument();
    expect(screen.getByText('Hat deleted')).toBeInTheDocument();
  });
});

describe('HatDetailPage — clear the palette', () => {
  it('empties the palette the moment it is confirmed, before the server answers', async () => {
    const user = userEvent.setup();
    let answer: (h: HatRead) => void = () => {};
    mocked.updateHatColors.mockImplementation(() => new Promise(r => { answer = r; }));
    renderPage(hatFixture({ colors: COLORS }));

    expect(await screen.findByText('blue')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear all' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Remove all 2 colors from this hat?' });
    await user.click(within(dialog).getByRole('button', { name: 'Clear colors' }));

    // Still in flight, and the palette is already empty.
    expect(await screen.findByText(/No colors yet/)).toBeInTheDocument();
    expect(mocked.updateHatColors).toHaveBeenCalledWith(5, []);

    answer(hatFixture({ colors: [] }));
    expect(await screen.findByText('Colors cleared')).toBeInTheDocument();
  });

  it('puts the colors back and says why when the clear fails', async () => {
    const user = userEvent.setup();
    const hat = hatFixture({ colors: COLORS });
    // Only the first load answers. Any refetch hangs, so the palette can only
    // come back through the rollback — not by a refetch papering over it.
    mocked.getHat.mockResolvedValueOnce(hat).mockImplementation(() => new Promise(() => {}));
    mocked.updateHatColors.mockRejectedValue(new Error('disk full'));
    renderWithProviders(
      <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
      { route: '/hats/5' },
    );

    await user.click(await screen.findByRole('button', { name: 'Clear all' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Clear colors' }));

    expect(await screen.findByText(/disk full/)).toBeInTheDocument();
    expect(screen.getByText('blue')).toBeInTheDocument();
    expect(screen.getByText('pink')).toBeInTheDocument();
    expect(screen.queryByText(/No colors yet/)).not.toBeInTheDocument();
  });

  it('keeps the colors when the confirmation is dismissed', async () => {
    const user = userEvent.setup();
    renderPage(hatFixture({ colors: COLORS }));

    await user.click(await screen.findByRole('button', { name: 'Clear all' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }));

    expect(mocked.updateHatColors).not.toHaveBeenCalled();
    expect(screen.getByText('blue')).toBeInTheDocument();
  });
});

describe('HatDetailPage — wearing it today', () => {
  it('acknowledges a logged wear with an Undo that removes it', async () => {
    const user = userEvent.setup();
    mocked.logWear.mockResolvedValue(hatFixture({ wear_count: 1, date_last_worn: '2026-09-27' }));
    mocked.undoLatestWear.mockResolvedValue(hatFixture({ wear_count: 0 }));
    // First load answers; every refetch hangs — so the new count can only
    // come from the wear call's own response being applied.
    mocked.getHat
      .mockResolvedValueOnce(hatFixture({ wear_count: 0 }))
      .mockImplementation(() => new Promise(() => {}));
    renderWithProviders(
      <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
      { route: '/hats/5' },
    );

    await user.click(await screen.findByRole('button', { name: /Wearing this today/ }));
    expect(await screen.findByText('Wear logged')).toBeInTheDocument();
    // The server's row is shown at once, not after a refetch.
    expect(screen.getByText('1×')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mocked.undoLatestWear).toHaveBeenCalledWith(5));
  });

  it('undoes the wear on the hat it was logged for, even from another hat’s page', async () => {
    // React Router keeps this page mounted from one hat to the next (Back
    // from hat 6 to hat 5 is the same component with a new id), and the
    // toast outlives both — so its Undo must not follow whichever hat is on
    // screen by the time it is tapped.
    const user = userEvent.setup();
    let wears5 = 0;
    mocked.getHat.mockImplementation(async id =>
      id === 5
        ? hatFixture({ wear_count: wears5 })
        : hatFixture({ id: 6, display_id: 'A-001-02', wear_count: 3 }));
    mocked.logWear.mockImplementation(async () => { wears5 = 1; return hatFixture({ wear_count: wears5 }); });
    mocked.undoLatestWear.mockImplementation(async id => hatFixture({ id, wear_count: 0 }));
    function GoToHat6() {
      const navigate = useNavigate();
      return <button type="button" onClick={() => navigate('/hats/6')}>go to hat 6</button>;
    }
    renderWithProviders(
      <>
        <GoToHat6 />
        <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>
      </>,
      { route: '/hats/5' },
    );

    await user.click(await screen.findByRole('button', { name: /Wearing this today/ }));
    expect(await screen.findByText('Wear logged')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'go to hat 6' }));
    expect(await screen.findByText('3×')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mocked.undoLatestWear).toHaveBeenCalledTimes(1));
    expect(mocked.undoLatestWear).toHaveBeenCalledWith(5);
  });

  it('lets the toast’s Undo take back only the wear it announced', async () => {
    // "Undo" deletes the LATEST wear on the server. Once the inline Undo has
    // already taken this one back, the toast's would delete an earlier, real
    // wear — so it does nothing then.
    const user = userEvent.setup();
    let wears = 2;
    mocked.getHat.mockImplementation(async () => hatFixture({ wear_count: wears }));
    mocked.logWear.mockImplementation(async () => { wears = 3; return hatFixture({ wear_count: wears }); });
    mocked.undoLatestWear.mockImplementation(async () => { wears -= 1; return hatFixture({ wear_count: wears }); });
    renderWithProviders(
      <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
      { route: '/hats/5' },
    );

    await user.click(await screen.findByRole('button', { name: /Wearing this today/ }));
    expect(await screen.findByText('Wear logged')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Undo the last logged wear' }));
    expect(await screen.findByText('Last wear removed')).toBeInTheDocument();
    expect(screen.getByText('2×')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await new Promise(r => setTimeout(r, 50));
    expect(mocked.undoLatestWear).toHaveBeenCalledTimes(1);
  });

  it('says a second tap the same day changed nothing — and offers no Undo', async () => {
    // Undoing a no-op would delete the earlier, real wear.
    const user = userEvent.setup();
    mocked.logWear.mockResolvedValue(hatFixture({ wear_count: 1, date_last_worn: '2026-09-27' }));
    renderPage(hatFixture({ wear_count: 1, date_last_worn: '2026-09-27' }));

    await user.click(await screen.findByRole('button', { name: /Wearing this today/ }));
    expect(await screen.findByText('Already logged for today')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });
});

describe('HatDetailPage — restoring a disposed hat', () => {
  const DISPOSED = hatFixture({
    disposed_at: '2026-09-01T00:00:00Z', disposed_via: 'trade', disposed_to: 'Eric F.',
  });

  it('names how it left, in words', async () => {
    renderPage(DISPOSED);
    expect(await screen.findByText(/Traded on/)).toBeInTheDocument();
  });

  it('asks first, and Cancel restores nothing', async () => {
    const user = userEvent.setup();
    renderPage(DISPOSED);

    await user.click(await screen.findByRole('button', { name: 'Undo — restore to active' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(mocked.undisposeHat).not.toHaveBeenCalled();
  });

  it('restores once confirmed', async () => {
    const user = userEvent.setup();
    mocked.undisposeHat.mockResolvedValue(hatFixture());
    renderPage(DISPOSED);

    await user.click(await screen.findByRole('button', { name: 'Undo — restore to active' }));
    const dialog = await screen.findByRole('dialog', { name: 'Restore this hat to active inventory?' });
    await user.click(within(dialog).getByRole('button', { name: 'Restore' }));

    await waitFor(() => expect(mocked.undisposeHat).toHaveBeenCalledWith(5));
    expect(await screen.findByText('Hat restored to active')).toBeInTheDocument();
  });
});
