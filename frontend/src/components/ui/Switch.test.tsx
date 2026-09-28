import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Switch } from './Switch';

/**
 * A switch is announced as "on"/"off" and applies the moment it flips, so
 * what must hold is the ARIA contract (role, state, name, description) and
 * that every way a person can flip a button — tap, Space, Enter — reports
 * exactly one change, while a disabled one reports none.
 */
function Controlled({ initial = false, onChange }: { initial?: boolean; onChange?: (v: boolean) => void }) {
  const [on, setOn] = useState(initial);
  return (
    <Switch
      checked={on}
      onChange={v => { setOn(v); onChange?.(v); }}
      label="Scheduled backups"
      hint="Nightly, keeps the last seven."
    />
  );
}

describe('Switch', () => {
  it('is a switch named by its label and described by its hint', () => {
    render(<Controlled />);
    const sw = screen.getByRole('switch', { name: 'Scheduled backups' });
    expect(sw).toHaveAccessibleDescription('Nightly, keeps the last seven.');
    expect(sw).toHaveAttribute('aria-checked', 'false');
    // A real button: never submits a surrounding form by accident.
    expect(sw.tagName).toBe('BUTTON');
    expect(sw).toHaveAttribute('type', 'button');
  });

  it('reflects checked in aria-checked and the on style', () => {
    render(<Switch checked onChange={() => {}} label="Guest view" />);
    const sw = screen.getByRole('switch', { name: 'Guest view' });
    expect(sw).toBeChecked();
    expect(sw).toHaveClass('is-on');
  });

  it('a tap reports the opposite state, once', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} label="Guest view" />);

    await user.click(screen.getByRole('switch'));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('toggles back and forth when wired to state', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);
    const sw = screen.getByRole('switch');

    await user.click(sw);
    expect(sw).toBeChecked();
    await user.click(sw);
    expect(sw).not.toBeChecked();
    expect(onChange.mock.calls).toEqual([[true], [false]]);
  });

  it('Space and Enter flip it from the keyboard', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);

    await user.tab();
    expect(screen.getByRole('switch')).toHaveFocus();
    await user.keyboard(' ');
    expect(screen.getByRole('switch')).toBeChecked();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('switch')).not.toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it('disabled: cannot be flipped and says so', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} label="Guest view" disabled />);
    const sw = screen.getByRole('switch');

    await user.click(sw);
    sw.focus();
    await user.keyboard(' ');

    expect(onChange).not.toHaveBeenCalled();
    expect(sw).toBeDisabled();
    expect(sw.closest('.hr-switch-row')).toHaveClass('is-disabled');
  });

  it('busy: marked aria-busy, and still answers a tap', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch checked onChange={onChange} label="Guest view" busy />);
    const sw = screen.getByRole('switch');

    expect(sw).toHaveAttribute('aria-busy', 'true');
    expect(sw).toHaveClass('is-busy');
    await user.click(sw);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('not busy: no aria-busy at all, rather than aria-busy="false" noise', () => {
    render(<Switch checked onChange={() => {}} label="Guest view" />);
    expect(screen.getByRole('switch')).not.toHaveAttribute('aria-busy');
  });

  it('takes an id, and names itself from it', () => {
    render(<Switch id="guest-toggle" checked={false} onChange={() => {}} label="Guest view" hint="Read-only" />);
    const sw = screen.getByRole('switch', { name: 'Guest view' });
    expect(sw).toHaveAttribute('id', 'guest-toggle');
    expect(sw).toHaveAttribute('aria-labelledby', 'guest-toggle-label');
    expect(sw).toHaveAttribute('aria-describedby', 'guest-toggle-hint');
  });

  it('two switches without ids never share a label', () => {
    render(
      <>
        <Switch checked={false} onChange={() => {}} label="First" />
        <Switch checked={false} onChange={() => {}} label="Second" />
      </>,
    );
    expect(screen.getByRole('switch', { name: 'First' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Second' })).toBeInTheDocument();
  });

  it('no hint: no dangling aria-describedby', () => {
    render(<Switch checked={false} onChange={() => {}} label="Guest view" />);
    expect(screen.getByRole('switch')).not.toHaveAttribute('aria-describedby');
  });
});
