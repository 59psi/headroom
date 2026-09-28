import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ConstructionAuditCard } from './ConstructionAuditCard';
import * as api from '../../api/settings';
import type { ConstructionAuditRow, ConstructionClearResult } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    auditConstructions: vi.fn(),
    clearConstruction: vi.fn(),
  };
});

const mocked = vi.mocked(api);

const ROWS: ConstructionAuditRow[] = [
  { construction: 'HYDROLite', hat_count: 12, priced_from_table: 9 },
  { construction: 'HYDRO', hat_count: 3, priced_from_table: 1 },
];

function result(over: Partial<ConstructionClearResult> = {}): ConstructionClearResult {
  return {
    construction: 'HYDROLite', to: null, dry_run: true, owner_set_skipped: 2,
    hats_cleared: 10, model_names_corrected: 4, prices_cleared: 9,
    manual_prices_kept: 1, samples: ['A-001-01', 'A-001-02'],
    ...over,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('ConstructionAuditCard', () => {
  it('states how many hats carry a construction, or that there is nothing to do', async () => {
    mocked.auditConstructions.mockResolvedValue(ROWS);
    const { unmount } = renderWithProviders(<ConstructionAuditCard />);
    expect(await screen.findByText('15 hats')).toBeInTheDocument();
    unmount();

    mocked.auditConstructions.mockResolvedValue([]);
    renderWithProviders(<ConstructionAuditCard />);
    expect(await screen.findByText('Nothing to do')).toBeInTheDocument();
    expect(screen.getByText('No constructions recorded.')).toBeInTheDocument();
  });

  it('previews before it writes, and writes only on the explicit button', async () => {
    const user = userEvent.setup();
    mocked.auditConstructions.mockResolvedValue(ROWS);
    mocked.clearConstruction.mockImplementation(async (value, dryRun, to) =>
      result({ construction: value, dry_run: dryRun, to: to ?? null }));
    renderWithProviders(<ConstructionAuditCard />);

    await user.click(await screen.findByRole('button', { name: 'Clear HYDROLite…' }));

    expect(await screen.findByText(/Clear “HYDROLite” from 10 hats\?/)).toBeInTheDocument();
    expect(screen.getByText(/left alone because/)).toBeInTheDocument();
    expect(mocked.clearConstruction).toHaveBeenCalledTimes(1);
    expect(mocked.clearConstruction).toHaveBeenLastCalledWith('HYDROLite', true, null);

    await user.click(screen.getByRole('button', { name: 'Clear them' }));

    await waitFor(() =>
      expect(mocked.clearConstruction).toHaveBeenLastCalledWith('HYDROLite', false, null));
    expect(await screen.findByText('Cleared “HYDROLite” from 10 hats')).toBeInTheDocument();
  });

  it('applies the target it previewed, and a new target retires the old preview', async () => {
    // The apply used to re-read the text box, so a value typed after the
    // preview was applied without ever being previewed. Editing the box now
    // withdraws the preview instead — there is no stale plan to confirm.
    const user = userEvent.setup();
    mocked.auditConstructions.mockResolvedValue(ROWS);
    mocked.clearConstruction.mockImplementation(async (value, dryRun, to) =>
      // The server canonicalizes the target; the card must apply ITS answer.
      result({ construction: value, dry_run: dryRun, to: to ? 'HYDRO' : null }));
    renderWithProviders(<ConstructionAuditCard />);

    const box = await screen.findByLabelText('Change them to');
    await user.type(box, ' hydro ');
    await user.click(await screen.findByRole('button', { name: 'Change HYDROLite…' }));

    // Trimmed on the way out.
    expect(mocked.clearConstruction).toHaveBeenLastCalledWith('HYDROLite', true, 'hydro');
    expect(await screen.findByText(/Change “HYDROLite” to “HYDRO” on 10 hats\?/)).toBeInTheDocument();

    await user.type(box, 'x');
    expect(screen.queryByRole('button', { name: 'Change them' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Change HYDROLite…' }));
    await user.click(await screen.findByRole('button', { name: 'Change them' }));
    // What was previewed — the canonical value — not the raw box.
    await waitFor(() =>
      expect(mocked.clearConstruction).toHaveBeenLastCalledWith('HYDROLite', false, 'HYDRO'));
  });

  it('drops a preview that lands after the target was edited', async () => {
    // Editing the box withdraws an open preview, but a dry run still in
    // flight used to land AFTER the edit and put up a plan for the old
    // target: "Clear “HYDROLite”…?" under a box that now says HYDRO, one tap
    // from clearing hats the owner had just said how to correct.
    const user = userEvent.setup();
    mocked.auditConstructions.mockResolvedValue(ROWS);
    let answer!: (r: ConstructionClearResult) => void;
    mocked.clearConstruction.mockReturnValueOnce(
      new Promise<ConstructionClearResult>(resolve => { answer = resolve; }));
    renderWithProviders(<ConstructionAuditCard />);

    await user.click(await screen.findByRole('button', { name: 'Clear HYDROLite…' }));
    await user.type(screen.getByLabelText('Change them to'), 'HYDRO');
    answer(result({ to: null }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Change HYDROLite…' })).toBeEnabled());
    expect(screen.queryByText(/Clear “HYDROLite” from/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Clear them' })).toBeNull();
  });

  it('cannot apply a preview that would change nothing', async () => {
    const user = userEvent.setup();
    mocked.auditConstructions.mockResolvedValue(ROWS);
    mocked.clearConstruction.mockResolvedValue(result({ hats_cleared: 0, owner_set_skipped: 12 }));
    renderWithProviders(<ConstructionAuditCard />);

    await user.click(await screen.findByRole('button', { name: 'Clear HYDROLite…' }));
    expect(await screen.findByRole('button', { name: 'Clear them' })).toBeDisabled();
  });

  it('keeps the title up while loading instead of an empty card', async () => {
    mocked.auditConstructions.mockReturnValue(new Promise<ConstructionAuditRow[]>(() => {}));
    renderWithProviders(<ConstructionAuditCard />);
    expect(screen.getByRole('heading', { name: 'Construction audit' })).toBeInTheDocument();
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('No constructions recorded.')).toBeNull();
    expect(screen.queryByText('Nothing to do')).toBeNull();
  });
});
