import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { TagsCard } from './TagsCard';
import * as api from '../../api/settings';
import type { TagBaseStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  const real = await importOriginal<typeof api>();
  return {
    ...stubAll(real),
    // The label-sheet URLs are plain string builders; keep the real ones so
    // the links are checked against what the server actually serves.
    hatLabelsUrl: real.hatLabelsUrl,
    caseLabelsUrl: real.caseLabelsUrl,
  };
});

const mocked = vi.mocked(api);

function status(over: Partial<TagBaseStatus> = {}): TagBaseStatus {
  return {
    base_url: 'http://10.0.0.7:8000',
    source: 'request',
    example_url: 'http://10.0.0.7:8000/t/h/1',
    ...over,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('TagsCard', () => {
  it('never says "Not set" before the status has loaded', async () => {
    let release!: (v: TagBaseStatus) => void;
    mocked.getTagBase.mockReturnValue(new Promise(r => { release = r; }));
    renderWithProviders(<TagsCard />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText(/Not set/)).not.toBeInTheDocument();
    expect(screen.queryByText('Not pinned')).not.toBeInTheDocument();

    release(status());
    expect(await screen.findByText('Not pinned')).toBeInTheDocument();
    expect(screen.getByText(/Not set — tags use whatever address/)).toBeInTheDocument();
  });

  it('offers Reset only once a host is pinned', async () => {
    mocked.getTagBase.mockResolvedValue(status());
    const { unmount } = renderWithProviders(<TagsCard />);
    await screen.findByText('Not pinned');
    expect(screen.queryByRole('button', { name: 'Reset' })).not.toBeInTheDocument();
    unmount();

    mocked.getTagBase.mockResolvedValue(status({ base_url: 'http://headroom.local:8000', source: 'settings' }));
    renderWithProviders(<TagsCard />);
    expect(await screen.findByText('Pinned')).toBeInTheDocument();
    expect(screen.getByText('http://headroom.local:8000')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeInTheDocument();
  });

  it('saves the trimmed host on Enter and shows the answer without a reload', async () => {
    const user = userEvent.setup();
    mocked.getTagBase.mockResolvedValue(status());
    const pinned = status({ base_url: 'http://headroom.local:8000', source: 'settings' });
    mocked.setTagBase.mockResolvedValue(pinned);
    renderWithProviders(<TagsCard />);
    await screen.findByText('Not pinned');

    const field = screen.getByRole('textbox', { name: 'Tag host' });
    mocked.getTagBase.mockResolvedValue(pinned);
    await user.type(field, '  http://headroom.local:8000  {Enter}');

    expect(mocked.setTagBase).toHaveBeenCalledWith('http://headroom.local:8000');
    expect(await screen.findByText('Tag host saved')).toBeInTheDocument();
    expect(await screen.findByText('Pinned')).toBeInTheDocument();
    expect(field).toHaveValue('');
  });

  it('will not save a blank host', async () => {
    const user = userEvent.setup();
    mocked.getTagBase.mockResolvedValue(status());
    renderWithProviders(<TagsCard />);
    await screen.findByText('Not pinned');

    await user.type(screen.getByRole('textbox', { name: 'Tag host' }), '   {Enter}');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(mocked.setTagBase).not.toHaveBeenCalled();
  });

  it('reports a rejected host in place and keeps what was typed', async () => {
    const user = userEvent.setup();
    mocked.getTagBase.mockResolvedValue(status());
    mocked.setTagBase.mockRejectedValue(new Error('Must start with http:// or https://'));
    renderWithProviders(<TagsCard />);
    await screen.findByText('Not pinned');

    const field = screen.getByRole('textbox', { name: 'Tag host' });
    await user.type(field, 'headroom.local');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Must start with http:// or https://');
    expect(field).toHaveValue('headroom.local');
    expect(screen.queryByText('Tag host saved')).not.toBeInTheDocument();
  });

  it('resets a pinned host', async () => {
    const user = userEvent.setup();
    mocked.getTagBase.mockResolvedValue(status({ source: 'settings' }));
    mocked.clearTagBase.mockResolvedValue(undefined);
    renderWithProviders(<TagsCard />);
    await screen.findByText('Pinned');

    mocked.getTagBase.mockResolvedValue(status());
    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(mocked.clearTagBase).toHaveBeenCalled();
    expect(await screen.findByText('Tag host reset')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Not pinned')).toBeInTheDocument());
  });

  it('links both printable label sheets', async () => {
    mocked.getTagBase.mockResolvedValue(status());
    renderWithProviders(<TagsCard />);
    await screen.findByText('Not pinned');

    expect(screen.getByRole('link', { name: 'Hat labels' })).toHaveAttribute('href', '/api/admin/hat-labels');
    expect(screen.getByRole('link', { name: 'Case labels' })).toHaveAttribute('href', '/api/admin/case-labels');
  });
});
