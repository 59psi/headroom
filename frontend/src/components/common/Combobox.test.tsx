import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Combobox } from './Combobox';

/**
 * This replaced a native `<datalist>`, which was the wrong control on a phone:
 * iOS renders it as a thin suggestion strip above the keyboard that is easy to
 * miss, so a field with ten known values read as a plain text box and the
 * structured half of the input was invisible. These pin that the known values
 * are actually on screen and actually selectable.
 */
const OPTIONS = ['HYDRO', 'HYDROLite', 'Thermal', 'Waxed Canvas'];

function setup(value = '') {
  const onChange = vi.fn();
  render(
    <Combobox
      id="c" label="Construction" value={value} onChange={onChange} options={OPTIONS}
    />,
  );
  return { onChange, input: screen.getByLabelText('Construction') };
}

describe('Combobox', () => {
  it('shows the known values on focus, not hidden behind a keyboard strip', async () => {
    const user = userEvent.setup();
    const { input } = setup();

    await user.click(input);

    for (const option of OPTIONS) {
      expect(screen.getByRole('option', { name: option })).toBeInTheDocument();
    }
  });

  it('selecting a known value reports it', async () => {
    const user = userEvent.setup();
    const { onChange, input } = setup();

    await user.click(input);
    await user.click(screen.getByRole('option', { name: 'HYDROLite' }));

    expect(onChange).toHaveBeenCalledWith('HYDROLite');
  });

  it('filters as you type — this is the autocomplete', async () => {
    const user = userEvent.setup();
    // A partial word, not "hydro": an exact match deliberately keeps the whole
    // list on screen (see the test below), so it would not exercise filtering.
    const { input } = setup('hydr');

    await user.click(input);

    expect(screen.getByRole('option', { name: 'HYDRO' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'HYDROLite' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Thermal' })).not.toBeInTheDocument();
  });

  it('still accepts a fabric that is on no list', async () => {
    const user = userEvent.setup();
    const { onChange, input } = setup();

    await user.type(input, 'Boiled Wool');

    // Free text is the value — the structured list is a shortcut, not a gate.
    const calls = onChange.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1][0]).toBe('l');
  });

  it('keeps the whole list visible once a value exactly matches', async () => {
    const user = userEvent.setup();
    const { input } = setup('HYDRO');

    await user.click(input);

    // Filtering on an exact match would collapse the list to one row, which
    // reads as the other choices having disappeared.
    expect(screen.getByRole('option', { name: 'Thermal' })).toBeInTheDocument();
  });

  it('is keyboard navigable', async () => {
    const user = userEvent.setup();
    const { onChange, input } = setup();

    await user.click(input);
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');

    expect(onChange).toHaveBeenCalledWith('HYDROLite');
  });

  it('does not swallow form submit when nothing is highlighted', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(e => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Combobox id="c2" label="Construction" value="" onChange={() => {}} options={OPTIONS} />
        <button type="submit">Save</button>
      </form>,
    );

    await user.click(screen.getByLabelText('Construction'));
    await user.keyboard('{Enter}');

    expect(onSubmit).toHaveBeenCalled();
  });
});

describe('Combobox — escaping the card', () => {
  it('renders the list outside the form, not inside the clipping card', async () => {
    // `.card` sets `overflow: hidden`, so a list positioned inside one is cut
    // off mid-row and the options below it are unreachable — no z-index fixes
    // that, because the pixels are never drawn. Portalling to <body> is the
    // only thing that escapes it (and the two other ancestor traps:
    // `.card-body`'s stacking context, and the card hover `transform`).
    const user = userEvent.setup();
    const { container } = render(
      <div className="card">
        <div className="card-body">
          <Combobox
            id="c3" label="Construction" value="" onChange={() => {}} options={OPTIONS}
          />
        </div>
      </div>,
    );

    await user.click(screen.getByLabelText('Construction'));

    const list = document.querySelector('.hr-combobox-list');
    expect(list).not.toBeNull();
    expect(container.querySelector('.hr-combobox-list')).toBeNull();
    expect(list!.closest('.card')).toBeNull();
  });

  it('still selects an option once the list lives in the body', async () => {
    // Portalling moves the list out of the wrapper, so the click-outside
    // handler would otherwise treat a tap on an option as "outside" and close
    // the list before the option's own handler ran.
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <div className="card">
        <div className="card-body">
          <Combobox
            id="c4" label="Construction" value="" onChange={onChange} options={OPTIONS}
          />
        </div>
      </div>,
    );

    await user.click(screen.getByLabelText('Construction'));
    await user.click(screen.getByRole('option', { name: 'Thermal' }));

    expect(onChange).toHaveBeenCalledWith('Thermal');
  });
});
