import { describe, it, expect, vi, beforeEach } from 'vitest';
import { focusManager } from '@tanstack/react-query';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { EditHatPage } from './EditHatPage';
import * as hatsApi from '../api/hats';
import type { HatRead } from '../types';
import { hatFixture } from '../test/fixtures';

/**
 * The Collection / collab field is wired through a `Record<string, unknown>`
 * payload, so `tsc` cannot tell whether the state is actually placed on the
 * request. Forgetting the one payload line would leave a field that accepts
 * typing and silently discards it — invisible to every other check. These
 * tests pin the seed and the submit.
 */

const HAT: HatRead = hatFixture({
  id: 7, display_id: 'H-007', case_display_id: null, style: 'collab', brand: 'melin',
  artist_series: 'Skye Walker', model_name: 'Coronado', analysis_status: 'ok',
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
});

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getHat: vi.fn(async () => HAT),
    updateHat: vi.fn(async () => HAT),
    uploadHatPhoto: vi.fn(),
    assignHat: vi.fn(),
    updateHatColors: vi.fn(async () => HAT),
    getStyles: vi.fn(async () => [{ value: 'collab', label: 'Collab' }]),
    getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
    getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
    getConstructions: vi.fn(async () => ['HYDRO', 'HYDROLite', 'Thermal']),
    getCollections: vi.fn(async () => ['Piña', 'Skye Walker']),
    getColorwayOptions: vi.fn(async () => []),
  };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listCases: vi.fn(async () => [])
  };
});
vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useParams: () => ({ hatId: '7' }),
  useNavigate: () => vi.fn(),
}));

describe('EditHatPage — Collection / collab', () => {
  beforeEach(() => vi.clearAllMocks());

  it('seeds the field from the hat', async () => {
    renderWithProviders(<EditHatPage />);

    expect(await screen.findByLabelText('Collection or collaboration')).toHaveValue('Skye Walker');
  });

  it('submits what was typed as artist_series', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const field = await screen.findByLabelText('Collection or collaboration');
    await user.clear(field);
    await user.type(field, 'melin x OluKai');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).toMatchObject({
      artist_series: 'melin x OluKai',
    });
  });

  it('clears the field to null rather than an empty string', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    await user.clear(await screen.findByLabelText('Collection or collaboration'));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).toMatchObject({
      artist_series: null,
    });
  });
});

/**
 * The two price boxes are the only fields whose PRESENCE in the payload is
 * itself a decision. `hat_service.update_hat` reads a sent key as "a person
 * typed this number" and stamps the price `manual`, which is permanent:
 * `resolve_retail` returns it forever after, and both `refresh_melin_resale`
 * and `_apply_resale_pointer` bail on it.
 *
 * This form seeds both boxes from the loaded hat, so sending them
 * unconditionally meant editing a colorway silently relabeled a scraped
 * melinrecap median as "Price you entered — used as given" and froze it
 * against every future analysis — same number on screen, different meaning,
 * nothing to see.
 */
describe('EditHatPage — a price becomes "manual" only when you actually edit it', () => {
  const PRICED: HatRead = {
    ...HAT,
    estimated_new_price: 79,
    estimated_new_price_source: 'melin retail',
    resale_price: 52.5,
    resale_price_scope: 'model',
    resale_price_source: 'Median of 11 live listings',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(hatsApi.getHat).mockResolvedValue(PRICED);
  });

  it('omits both price keys when something else was edited', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const field = await screen.findByLabelText('Collection or collaboration');
    await user.clear(field);
    await user.type(field, 'melin x Hydro Flask');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    const payload = vi.mocked(hatsApi.updateHat).mock.calls[0][1];

    // `exclude_unset` on the server means ABSENT and null mean different
    // things here, so this must assert absence, not a null value.
    expect(payload).not.toHaveProperty('estimated_new_price');
    expect(payload).not.toHaveProperty('resale_price');
  });

  it('sends the price when the number really changed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const resale = await screen.findByLabelText('Resale ($)');
    await user.clear(resale);
    await user.type(resale, '60');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    const payload = vi.mocked(hatsApi.updateHat).mock.calls[0][1];

    expect(payload).toMatchObject({ resale_price: 60 });
    expect(payload).not.toHaveProperty('estimated_new_price');
  });

  it('sends null when a price is deliberately cleared', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    await user.clear(await screen.findByLabelText('Resale ($)'));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    // Clearing hands the hat back to the live market feed, which the server
    // does by nulling `resale_price_scope` — so the key must be SENT as null,
    // not omitted the way an untouched field is.
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).toMatchObject({
      resale_price: null,
    });
  });
});

/**
 * The two ways the price guard can be defeated, both found by review AFTER the
 * guard shipped. Comparing the box against the LIVE row rather than the seeded
 * one reopens the exact bug the guard closes, and `type="number"` collapses
 * "cleared" and "rejected what you typed" into the same empty string.
 */
describe('EditHatPage — the price guard cannot be defeated by a refetch or a typo', () => {
  const PRICED: HatRead = {
    ...HAT,
    estimated_new_price: 79,
    estimated_new_price_source: 'melin retail',
    resale_price: 52.5,
    resale_price_scope: 'model',
    resale_price_source: 'Median of 11 live listings',
  };

  beforeEach(() => vi.clearAllMocks());

  it('does not resend a stale price when a fresher one lands mid-edit', async () => {
    const user = userEvent.setup();
    // Seed at 52.5, then make the background refetch actually land 55. The box
    // still shows 52.5 because seeding is frozen per hat, so comparing the box
    // to the LIVE row calls that a user edit and writes 52.5 back as `manual`.
    //
    // The refetch has to be FORCED. An earlier version of this test just
    // queued a second mock return and asserted — nothing ever requested it, so
    // it passed against the bug it was written to catch. `focusManager` is
    // what `refetchOnWindowFocus` listens to, and jsdom fires no focus events
    // of its own.
    vi.mocked(hatsApi.getHat)
      .mockResolvedValueOnce(PRICED)
      .mockResolvedValue({ ...PRICED, resale_price: 55 });

    renderWithProviders(<EditHatPage />);

    const field = await screen.findByLabelText('Collection or collaboration');
    expect(await screen.findByLabelText('Resale ($)')).toHaveValue(52.5);

    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await waitFor(() => expect(vi.mocked(hatsApi.getHat).mock.calls.length).toBeGreaterThan(1));
    // The fresher row is in the cache; the box was deliberately not reseeded.
    expect(screen.getByLabelText('Resale ($)')).toHaveValue(52.5);

    await user.clear(field);
    await user.type(field, 'melin x Hydro Flask');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).not.toHaveProperty('resale_price');
  });

  it('does not clear a price when the browser rejected what was typed', async () => {
    const user = userEvent.setup();
    vi.mocked(hatsApi.getHat).mockResolvedValue(PRICED);
    renderWithProviders(<EditHatPage />);

    const resale = await screen.findByLabelText('Resale ($)');
    // A partial exponent like "1e" is accepted keystroke-by-keystroke but
    // sanitized to "" by the number input, with `badInput` set. jsdom does not
    // model that sanitization, so the state is forced directly.
    await user.clear(resale);
    Object.defineProperty(resale, 'validity', {
      configurable: true,
      value: { badInput: true },
    });
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).not.toHaveProperty('resale_price');
  });
});
