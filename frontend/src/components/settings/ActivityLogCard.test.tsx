/**
 * Recent activity: what changed, when, and whether the prune that bounds
 * this log is still running.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ActivityLogCard } from './ActivityLogCard';
import * as api from '../../api/settings';
import type { ActivityRow, RetentionStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getActivityLog: vi.fn(),
    getRetentionStatus: vi.fn(),
  };
});

const mocked = vi.mocked(api);

let nextId = 1;
function row(over: Partial<ActivityRow> = {}): ActivityRow {
  return {
    id: nextId++, occurred_at: new Date().toISOString(), kind: 'hat.updated',
    entity_type: 'hat', entity_id: 12, summary: 'Updated hat H-012', details: null, ...over,
  };
}

function retention(over: Partial<RetentionStatus['health']> = {}): RetentionStatus {
  return {
    retention_days: 90,
    health: {
      name: 'retention prune', last_attempt_at: null, last_success_at: null,
      last_error: null, consecutive_failures: 0, last_result: 0, ...over,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getActivityLog.mockResolvedValue([]);
  mocked.getRetentionStatus.mockResolvedValue(retention());
});

describe('ActivityLogCard', () => {
  it('fetches exactly the rows it shows', async () => {
    renderWithProviders(<ActivityLogCard />);
    await screen.findByText('No activity logged yet.');
    expect(mocked.getActivityLog).toHaveBeenCalledWith(25);
  });

  it('groups rows under a heading per day, newest first', async () => {
    mocked.getActivityLog.mockResolvedValue([
      row({ summary: 'Created case C-3' }),
      row({ summary: 'Created room Garage', occurred_at: new Date(Date.now() - 4 * 86_400_000).toISOString() }),
    ]);
    renderWithProviders(<ActivityLogCard />);

    await screen.findByText('Created case C-3');
    const days = screen.getAllByRole('heading', { level: 3 });
    expect(days).toHaveLength(2);
    expect(days[0]).toHaveTextContent('Today');
    expect(days[1]).not.toHaveTextContent(/Today|Yesterday/);
    // The kind still names what happened; the dot color is only decoration.
    expect(screen.getAllByText('hat.updated')).toHaveLength(2);
  });

  it('marks a wrong password at a re-check, and the lockout after it, as failures', async () => {
    mocked.getActivityLog.mockResolvedValue([
      row({ summary: 'Wrong password revealing the API token', kind: 'auth.reauth_failed', entity_type: 'user', entity_id: 1 }),
      row({ summary: 'Password checks paused', kind: 'auth.reauth_blocked', entity_type: 'user', entity_id: 1 }),
      row({ summary: 'Colors edited', kind: 'hat.colors_updated', entity_type: 'hat', entity_id: 2 }),
    ]);
    const { container } = renderWithProviders(<ActivityLogCard />);

    await screen.findByText('Password checks paused');
    const tones = [...container.querySelectorAll('.hr-upkeep-event')].map(li => li.className);
    expect(tones[0]).toContain('is-bad');
    expect(tones[1]).toContain('is-bad');
    expect(tones[2]).toContain('is-neutral');
  });

  it('links a row to the hat or room it is about, but not to a deleted one', async () => {
    mocked.getActivityLog.mockResolvedValue([
      row({ summary: 'Updated hat H-012', entity_type: 'hat', entity_id: 12 }),
      row({ summary: 'Created room Garage', kind: 'room.created', entity_type: 'room', entity_id: 4 }),
      row({ summary: 'Deleted hat H-009', kind: 'hat.deleted', entity_type: 'hat', entity_id: 9 }),
      row({ summary: 'Created case C-3', kind: 'case.created', entity_type: 'case', entity_id: 3 }),
    ]);
    renderWithProviders(<ActivityLogCard />);

    expect(await screen.findByRole('link', { name: 'Updated hat H-012' })).toHaveAttribute('href', '/hats/12');
    expect(screen.getByRole('link', { name: 'Created room Garage' })).toHaveAttribute('href', '/rooms/4');
    // Deleted: nothing to open. Cases route by display id, which the log
    // does not carry — plain text rather than a link to a guess.
    expect(screen.getByText('Deleted hat H-009')).not.toHaveAttribute('href');
    expect(screen.queryByRole('link', { name: 'Deleted hat H-009' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Created case C-3' })).not.toBeInTheDocument();
  });

  it('says loudly when the retention prune is failing', async () => {
    mocked.getRetentionStatus.mockResolvedValue(retention({
      consecutive_failures: 3, last_error: 'database is locked',
    }));
    const { container } = renderWithProviders(<ActivityLogCard />);

    expect(await screen.findByText(/Retention prune failing \(3 times in a row\)/)).toHaveTextContent(
      /database is locked.*growing unbounded/,
    );
    expect(container.querySelector('.hr-panel-head .hr-pill')).toHaveTextContent('Prune failing');
  });

  it('reports the last prune when it is healthy', async () => {
    mocked.getRetentionStatus.mockResolvedValue(retention({
      last_success_at: new Date().toISOString(), last_result: 4,
    }));
    const { container } = renderWithProviders(<ActivityLogCard />);

    expect(await screen.findByText(/Pruned 4 rows older than 90 days/)).toBeInTheDocument();
    expect(container.querySelector('.hr-panel-head .hr-pill')).toHaveTextContent('Keeps 90 days');
  });

  it('does not imply a prune ran when none has since the restart', async () => {
    renderWithProviders(<ActivityLogCard />);
    expect(await screen.findByText(/has not run yet since the last restart/)).toBeInTheDocument();
  });

  it('shows a skeleton, not "No activity", while the log is loading', async () => {
    let release!: (rows: ActivityRow[]) => void;
    mocked.getActivityLog.mockReturnValue(new Promise(r => { release = r; }));
    renderWithProviders(<ActivityLogCard />);

    expect(screen.getByText('Recent activity')).toBeInTheDocument();
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('No activity logged yet.')).not.toBeInTheDocument();

    release([row({ summary: 'Signed in' })]);
    expect(await screen.findByText('Signed in')).toBeInTheDocument();
  });

  it('refreshes the log AND the retention record together', async () => {
    // Sibling keys: "activity" is not a prefix of "retention", so the button
    // has to invalidate both or the prune line goes stale beside fresh rows.
    const user = userEvent.setup();
    renderWithProviders(<ActivityLogCard />);
    await screen.findByText('No activity logged yet.');
    expect(mocked.getActivityLog).toHaveBeenCalledTimes(1);
    expect(mocked.getRetentionStatus).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    await waitFor(() => expect(mocked.getActivityLog).toHaveBeenCalledTimes(2));
    expect(mocked.getRetentionStatus).toHaveBeenCalledTimes(2);
  });
});
