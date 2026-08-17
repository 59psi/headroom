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
}));

vi.mock('../../api/cases', () => ({
  listCases: vi.fn(async () => [
    { id: 4, display_id: 'A-001', case_type: 'archive', hat_count: 2, room_name: 'Closet' },
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

    await user.selectOptions(screen.getByLabelText('Case Assignment'), '4');
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

    await user.selectOptions(screen.getByLabelText('Case Assignment'), NEW_CASE_VALUE);

    expect(onCreateCase).toHaveBeenCalledOnce();
    expect(onChange).not.toHaveBeenCalledWith('caseId', NEW_CASE_VALUE);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('lists real cases with their type, count and room', async () => {
    renderWithProviders(<Harness onChange={vi.fn()} onCreateCase={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /A-001 \(Archive · 2 hats · Closet\)/ })).toBeInTheDocument();
    });
    expect(screen.getByRole('option', { name: 'Unassigned' })).toBeInTheDocument();
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
    expect(screen.getByLabelText('Case Assignment')).toHaveValue('4');
    expect(screen.getByLabelText('Date Last Worn')).toHaveValue('2026-01-02');
  });
});
