import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { useHatFormOptions, HatBasicsCard, NEW_CASE_VALUE, type HatBasics } from './HatFormFields';

vi.mock('../../api/hats', () => ({
  getStyles: vi.fn(async () => [
    { value: 'a_game', label: 'A-Game' },
    { value: 'beanie', label: 'Beanie' },
  ]),
  getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
  getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
  getConstructions: vi.fn(async () => ['HYDRO', 'HYDROLite', 'Thermal']),
  getCollections: vi.fn(async () => ['Piña', 'Skye Walker']),
}));

vi.mock('../../api/cases', () => ({
  listCases: vi.fn(async () => [
    {
      id: 4, display_id: 'A-001', case_type: 'archive', hat_count: 2, room_name: 'Closet',
      beanie_count: 0, regular_count: 2, capacity: null,
      accepts_regular: true, accepts_beanie: false, free_regular: 2, free_beanie: 0,
    },
  ]),
}));

const BASICS: HatBasics = {
  style: 'a_game', size: 'classic', condition: 'new', construction: '', artistSeries: '',
  caseId: '', dateLastWorn: '',
};

function Harness(props: {
  onChange: <K extends keyof HatBasics>(k: K, v: HatBasics[K]) => void;
  onCreateCase: () => void;
  values?: HatBasics;
  caseLabel?: string;
  dateLabel?: string;
}) {
  const options = useHatFormOptions();
  return (
    <HatBasicsCard
      values={props.values ?? BASICS}
      onChange={props.onChange}
      options={options}
      onCreateCase={props.onCreateCase}
      caseLabel={props.caseLabel}
      dateLabel={props.dateLabel}
    />
  );
}

beforeEach(() => { vi.clearAllMocks(); });

describe('HatBasicsCard', () => {
  it('reports each field change back to the page under the right key', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<Harness onChange={onChange} onCreateCase={vi.fn()} />);
    await waitFor(() => screen.getByRole('option', { name: 'Beanie' }));

    await user.selectOptions(screen.getByLabelText('Style'), 'beanie');
    expect(onChange).toHaveBeenLastCalledWith('style', 'beanie');

    await user.click(screen.getByLabelText('Case Assignment'));
    await user.click(await screen.findByRole('option', { name: /A-001/ }));
    expect(onChange).toHaveBeenLastCalledWith('caseId', '4');

    await user.type(screen.getByLabelText('Date Last Worn'), '2026-08-04');
    expect(onChange).toHaveBeenLastCalledWith('dateLastWorn', '2026-08-04');
  });

  it('opens the new-case modal on the sentinel WITHOUT writing it as a case id', async () => {
    // The sentinel is not a real case id. If it leaked into state the form
    // would POST case_id=NaN on submit.
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onCreateCase = vi.fn();
    renderWithProviders(<Harness onChange={onChange} onCreateCase={onCreateCase} />);

    await user.click(screen.getByLabelText('Case Assignment'));
    await user.click(await screen.findByRole('option', { name: /Create New Case/ }));

    expect(onCreateCase).toHaveBeenCalledOnce();
    expect(onChange).not.toHaveBeenCalledWith('caseId', NEW_CASE_VALUE);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('lists real cases grouped by room, with occupancy', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onChange={vi.fn()} onCreateCase={vi.fn()} />);

    await user.click(screen.getByLabelText('Case Assignment'));

    const option = await screen.findByRole('option', { name: /A-001/ });
    expect(option).toHaveTextContent('Archive');
    expect(option).toHaveTextContent('2/4');
    expect(screen.getByText('Closet')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Unassigned' })).toBeInTheDocument();
  });

  it('filters as you type — the reason a 60-case wheel had to go', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onChange={vi.fn()} onCreateCase={vi.fn()} />);

    const field = screen.getByLabelText('Case Assignment');
    await user.click(field);
    await screen.findByRole('option', { name: /A-001/ });

    // Room name, not just case id — "where is it" is how you actually think.
    await user.type(field, 'closet');
    expect(screen.getByRole('option', { name: /A-001/ })).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, 'garage');
    expect(screen.queryByRole('option', { name: /A-001/ })).not.toBeInTheDocument();
  });

  it('disables a case that would 409, and says why', async () => {
    // The archive case holds 2 regular hats, so it cannot take a beanie —
    // the old <select> let you pick it and the save came back 409.
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <Harness onChange={onChange} onCreateCase={vi.fn()} values={{ ...BASICS, style: 'beanie' }} />,
    );

    await user.click(screen.getByLabelText('Case Assignment'));
    const option = await screen.findByRole('option', { name: /A-001/ });

    expect(option).toBeDisabled();
    expect(option).toHaveTextContent('holds regular hats');

    await user.click(option);
    expect(onChange).not.toHaveBeenCalledWith('caseId', '4');
  });

  it('takes the page-specific labels the Add form passes', () => {
    renderWithProviders(
      <Harness
        onChange={vi.fn()}
        onCreateCase={vi.fn()}
        caseLabel="Assign to Case (optional)"
        dateLabel="Date Last Worn (optional)"
      />,
    );
    expect(screen.getByLabelText('Assign to Case (optional)')).toBeInTheDocument();
    expect(screen.getByLabelText('Date Last Worn (optional)')).toBeInTheDocument();
  });

  it('reflects the values it is given (controlled, not internal state)', async () => {
    renderWithProviders(
      <Harness
        onChange={vi.fn()}
        onCreateCase={vi.fn()}
        values={{ ...BASICS, style: 'beanie', caseId: '4', dateLastWorn: '2026-01-02' }}
      />,
    );
    await waitFor(() => screen.getByRole('option', { name: 'Beanie' }));
    expect(screen.getByLabelText('Style')).toHaveValue('beanie');
    // Closed, the field reads as the selection rather than the raw id.
    expect(screen.getByLabelText('Case Assignment')).toHaveValue('A-001 · Closet');
    expect(screen.getByLabelText('Date Last Worn')).toHaveValue('2026-01-02');
  });
});
