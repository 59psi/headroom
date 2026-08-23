import { useState } from 'react';
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

/**
 * A Combobox wired to real state.
 *
 * `setup` above holds `value` fixed with a mock `onChange`, which is right for
 * asserting what gets reported but useless for anything about typing: the
 * component is controlled, so the box never actually fills and every
 * filtering assertion would pass vacuously against an empty query.
 */
function Controlled({ options = OPTIONS, label = 'Construction' }: {
  options?: string[]; label?: string;
}) {
  const [value, setValue] = useState('');
  return (
    <Combobox id="ctrl" label={label} value={value} onChange={setValue} options={options} />
  );
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
    render(<Controlled />);

    await user.type(screen.getByLabelText('Construction'), 'hydr');

    expect(screen.getByRole('option', { name: 'HYDRO' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'HYDROLite' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Thermal' })).not.toBeInTheDocument();
  });

  it('filters even when what you typed exactly matches an option', async () => {
    // The reported bug. Typing a known value out in full showed the ENTIRE
    // list, because "the value equals an option" was being read as "the user
    // picked it". Typing "Links" into the collection field offered 'Ohana and
    // 23XI Racing — every option, alphabetically — which reads as the search
    // box being ignored.
    const user = userEvent.setup();
    render(<Controlled />);

    await user.type(screen.getByLabelText('Construction'), 'Thermal');

    expect(screen.getByRole('option', { name: 'Thermal' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'HYDRO' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Waxed Canvas' })).not.toBeInTheDocument();
  });

  it('puts what you typed above longer names that merely contain it', async () => {
    // The list is capped by screen height on a phone, and a plain filter is
    // alphabetical — so the exact thing you typed could sit below a longer
    // name, or off the bottom entirely.
    const user = userEvent.setup();
    render(<Controlled label="Collection" options={['Cypress Links', 'Links', 'Links Edition']} />);

    await user.type(screen.getByLabelText('Collection'), 'Links');

    const shown = screen.getAllByRole('option').map(o => o.textContent);
    expect(shown).toEqual(['Links', 'Links Edition', 'Cypress Links']);
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

  it('keeps the whole list visible after you PICK a value', async () => {
    // The real intent behind the old exact-match escape hatch: choosing an
    // option must not collapse the list to that one row, which would read as
    // the other choices disappearing. The distinction is where the value came
    // from — picked, not typed — which is what the old check got wrong.
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <Combobox id="p" label="Construction" value="" onChange={onChange} options={OPTIONS} />,
    );

    await user.click(screen.getByLabelText('Construction'));
    await user.click(screen.getByRole('option', { name: 'HYDRO' }));
    // The parent is the source of truth for `value`; reflect the pick back.
    rerender(
      <Combobox id="p" label="Construction" value="HYDRO" onChange={onChange} options={OPTIONS} />,
    );
    await user.click(screen.getByLabelText('Construction'));

    expect(screen.getByRole('option', { name: 'Thermal' })).toBeInTheDocument();
  });

  it('reopens the list when you tap the field after picking', async () => {
    // Found while fixing the filter, not reported. Picking calls
    // `preventDefault` on the option's mousedown so the field keeps focus —
    // which means after a pick the input is focused with the list closed, and
    // tapping it fires no focus event. Without an explicit click handler there
    // is no way back to the list except focusing something else first.
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText('Construction');

    await user.click(input);
    await user.click(screen.getByRole('option', { name: 'HYDRO' }));
    expect(screen.queryByRole('option', { name: 'Thermal' })).not.toBeInTheDocument();

    await user.click(input);

    expect(screen.getByRole('option', { name: 'Thermal' })).toBeInTheDocument();
  });

  it('reopening a filled field offers every choice, not just the current one', async () => {
    // Focusing a field that already holds a value means "change my mind",
    // not "search for the thing already in the box".
    const user = userEvent.setup();
    const { input } = setup('HYDRO');

    await user.click(input);

    expect(screen.getByRole('option', { name: 'Thermal' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Waxed Canvas' })).toBeInTheDocument();
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
