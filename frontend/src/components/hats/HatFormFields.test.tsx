import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { caseFixture } from '../../test/fixtures';
import { useHatFormOptions, HatBasicsCard, NEW_CASE_VALUE, type HatBasics } from './HatFormFields';

// Deliberately NOT 'Closet': that is the case fixture's room name, and the
// room <select> would then make every `getByText('Closet')` ambiguous between
// two legitimate controls rather than pinning the one under test.
vi.mock('../../api/rooms', () => ({
  getRoomOptions: vi.fn(async () => [{ value: '1', label: 'Loft' }]),
}));

vi.mock('../../api/hats', () => ({
  // `is_beanie` is served by the API, not derived from the value — it decides
  // which cases the picker offers, and a second definition client-side would
  // eventually disagree with the server. Mock the real payload shape.
  getStyles: vi.fn(async () => [
    { value: 'a_game', label: 'A-Game', is_beanie: false },
    { value: 'beanie', label: 'Beanie (unspecified)', is_beanie: true },
    { value: 'journey', label: 'Journey Beanie', is_beanie: true },
  ]),
  getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
  getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
  getConstructions: vi.fn(async () => ['HYDRO', 'HYDROLite', 'Thermal']),
  getCollections: vi.fn(async () => ['Piña', 'Skye Walker']),
}));

vi.mock('../../api/cases', () => ({
  // The shared, TYPED fixture: this literal was captioned "Real payload shape"
  // while missing five fields pydantic always serializes. The picker renders
  // occupancy from `nominal_capacity`, not `used + free`, so a partial shape
  // silently rendered "2" instead of "2/3" — and only a typed fixture makes
  // tsc notice the next such omission.
  listCases: vi.fn(async () => [
    caseFixture({
      id: 4, room_name: 'Closet', hat_count: 2, regular_count: 2,
      accepts_beanie: false, free_regular: 1, free_beanie: 0,
    }),
  ]),
}));

const BASICS: HatBasics = {
  roomId: '',
  limitedEdition: false,
  style: 'a_game', size: 'classic', condition: 'new', construction: '', artistSeries: '',
  caseId: '', dateLastWorn: '', purchasePrice: '', purchasedAt: '',
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
    await waitFor(() => screen.getByRole('option', { name: 'Beanie (unspecified)' }));

    await user.selectOptions(screen.getByLabelText('Style'), 'beanie');
    expect(onChange).toHaveBeenLastCalledWith('style', 'beanie');

    await user.click(screen.getByLabelText('Case Assignment'));
    await user.click(await screen.findByRole('option', { name: /A-001/ }));
    expect(onChange).toHaveBeenCalledWith('caseId', '4');
    // Picking a case also clears any room, so this is no longer the LAST call.
    // A case and a direct room are mutually exclusive server-side; leaving a
    // stale room selected underneath would show a placement the save drops.
    expect(onChange).toHaveBeenCalledWith('roomId', '');

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

  it('lists real cases with their type, occupancy and room', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onChange={vi.fn()} onCreateCase={vi.fn()} />);

    await user.click(screen.getByLabelText('Case Assignment'));

    const option = await screen.findByRole('option', { name: /A-001/ });
    expect(option).toHaveTextContent('Archive');
    expect(option).toHaveTextContent('2/3');
    expect(option).toHaveTextContent('Closet');
    expect(screen.getByRole('option', { name: 'Unassigned' })).toBeInTheDocument();
  });

  it('pins the newest cases above the room groups', async () => {
    // A hat being added now usually belongs in a case made minutes ago, and
    // hunting for it inside a room group is the long way round.
    const user = userEvent.setup();
    renderWithProviders(<Harness onChange={vi.fn()} onCreateCase={vi.fn()} />);

    await user.click(screen.getByLabelText('Case Assignment'));
    await screen.findByRole('option', { name: /A-001/ });

    expect(screen.getByText('Recently added')).toBeInTheDocument();
    // Not listed twice — pinned cases are removed from their room group.
    expect(screen.getAllByRole('option', { name: /A-001/ })).toHaveLength(1);

    // Once you're searching you've said what you want; the pinned block would
    // just be noise in front of the answer.
    await user.type(screen.getByLabelText('Case Assignment'), 'closet');
    expect(screen.queryByText('Recently added')).not.toBeInTheDocument();
    expect(screen.getByText('Closet')).toBeInTheDocument();
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
    await waitFor(() => screen.getByRole('option', { name: 'Beanie (unspecified)' }));
    expect(screen.getByLabelText('Style')).toHaveValue('beanie');
    // Closed, the field reads as the selection rather than the raw id.
    expect(screen.getByLabelText('Case Assignment')).toHaveValue('A-001 · Closet');
    expect(screen.getByLabelText('Date Last Worn')).toHaveValue('2026-01-02');
  });
});
