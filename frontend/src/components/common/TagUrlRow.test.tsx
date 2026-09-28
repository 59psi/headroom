import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { TagUrlRow } from './TagUrlRow';
import * as settingsApi from '../../api/settings';
import * as clipboard from '../../lib/clipboard';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getTagBase: vi.fn() };
});
vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn() }));

const copyText = vi.mocked(clipboard.copyText);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(settingsApi.getTagBase).mockResolvedValue({
    base_url: 'http://headroom.local', source: 'settings', example_url: 'http://headroom.local/t/h/1',
  });
});

describe('TagUrlRow', () => {
  it("writes the SERVER's tag host, not whatever host this page happens to be on", async () => {
    // Browsing by IP once must not produce a batch of tags naming a DHCP lease.
    renderWithProviders(<TagUrlRow kind="h" ident={5} />);
    expect(await screen.findByRole('textbox', { name: 'NFC tag URL' }))
      .toHaveValue('http://headroom.local/t/h/5');
  });

  it('copies with the field as its plain-http fallback, and acknowledges on the button', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);
    renderWithProviders(<TagUrlRow kind="c" ident="A-001" />);

    await user.click(await screen.findByRole('button', { name: 'Copy the NFC tag URL' }));

    expect(copyText).toHaveBeenCalledWith(
      'http://headroom.local/t/c/A-001',
      screen.getByRole('textbox', { name: 'NFC tag URL' }),
    );
    expect(await screen.findByRole('button', { name: 'Copied the NFC tag URL' })).toBeInTheDocument();
  });

  it('says what to do when the browser refuses, instead of nothing', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(false);
    renderWithProviders(<TagUrlRow kind="h" ident={5} />);

    await user.click(await screen.findByRole('button', { name: 'Copy the NFC tag URL' }));

    expect(await screen.findByText(/it is selected, copy it by hand/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Copied/ })).not.toBeInTheDocument();
  });
});
