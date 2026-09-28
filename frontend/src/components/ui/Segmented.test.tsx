import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Segmented, type SegmentedOption } from './Segmented';

/**
 * Segmented replaced four hand-rolled copies, and each call site's tests
 * find its options as buttons by name and read `aria-pressed`. So what must
 * hold is that contract — a named group of plain toggle buttons, exactly one
 * pressed — plus the pieces a call site leans on: counts that show only when
 * given, icon-only options that still have a name, and Tab/Space/Enter
 * behaving like the buttons they are. Never a tablist or radios.
 */
type Scope = 'major' | 'accent' | 'all';

const SCOPES: ReadonlyArray<SegmentedOption<Scope>> = [
  { value: 'major', label: 'Main colors' },
  { value: 'accent', label: 'Accents only' },
  { value: 'all', label: 'Any' },
];

function Controlled({ onChange }: { onChange?: (v: Scope) => void }) {
  const [value, setValue] = useState<Scope>('major');
  return (
    <Segmented
      label="Color match"
      options={SCOPES}
      value={value}
      onChange={v => { setValue(v); onChange?.(v); }}
    />
  );
}

describe('Segmented', () => {
  it('is a named group of toggle buttons, exactly one pressed', () => {
    render(<Controlled />);
    const group = screen.getByRole('group', { name: 'Color match' });
    const buttons = within(group).getAllByRole('button');

    expect(buttons.map(b => b.textContent)).toEqual(['Main colors', 'Accents only', 'Any']);
    expect(buttons.map(b => b.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false']);
    // Real buttons that never submit a surrounding form by accident.
    for (const b of buttons) expect(b).toHaveAttribute('type', 'button');
    // Not a tablist, not radios: those promise arrow keys and a panel.
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('a tap reports the option, and the pressed state follows', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Accents only' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('accent');
    expect(screen.getByRole('button', { name: 'Accents only' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Main colors' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('is reached with Tab and chosen with Space or Enter, like any button', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);

    await user.tab();
    expect(screen.getByRole('button', { name: 'Main colors' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Accents only' })).toHaveFocus();
    await user.keyboard(' ');
    await user.tab();
    await user.keyboard('{Enter}');

    expect(onChange.mock.calls).toEqual([['accent'], ['all']]);
    expect(screen.getByRole('button', { name: 'Any' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('takes its name from a visible label when pointed at one', () => {
    render(
      <>
        <span id="tier-label">Tier</span>
        <Segmented labelledBy="tier-label" label="ignored" options={SCOPES} value="all" onChange={() => {}} />
      </>,
    );
    const group = screen.getByRole('group', { name: 'Tier' });
    expect(group).toHaveAttribute('aria-labelledby', 'tier-label');
    // One name, not two competing ones.
    expect(group).not.toHaveAttribute('aria-label');
  });

  it('shows a count only where one is given — a zero included', () => {
    render(
      <Segmented
        label="Case type"
        options={[
          { value: 'all', label: 'All', count: 3 },
          { value: 'archive', label: 'Archive', count: 0 },
          { value: 'daily_wear', label: 'Daily wear' },
        ]}
        value="all"
        onChange={() => {}}
      />,
    );
    // Count after the label, in the button's own text — what the Cases
    // page's tests read ("Archive2").
    expect(screen.getByRole('button', { name: /^All/ })).toHaveTextContent('All3');
    expect(screen.getByRole('button', { name: /^Archive/ })).toHaveTextContent('Archive0');
    const daily = screen.getByRole('button', { name: 'Daily wear' });
    expect(daily).toHaveTextContent(/^Daily wear$/);
    expect(daily.querySelector('.hr-seg-count')).toBeNull();
  });

  it('icon-only: the label is the name and tooltip, the glyph stays hidden', () => {
    const glyph = <svg data-testid="grid-glyph" width="16" height="16" />;
    render(
      <Segmented
        label="View"
        iconOnly
        options={[
          { value: 'list', label: 'List view', icon: <svg width="16" height="16" /> },
          { value: 'gallery', label: 'Gallery view', icon: glyph },
        ]}
        value="gallery"
        onChange={() => {}}
      />,
    );
    const gallery = screen.getByRole('button', { name: 'Gallery view' });
    expect(gallery).toHaveAttribute('aria-pressed', 'true');
    expect(gallery).toHaveAttribute('title', 'Gallery view');
    // No visible words — the glyph is the face, and it is decorative.
    expect(gallery).toHaveTextContent(/^$/);
    expect(screen.getByTestId('grid-glyph').closest('[aria-hidden="true"]')).not.toBeNull();
    expect(screen.getByRole('group', { name: 'View' })).toHaveClass('is-icons');
  });

  it('an icon beside a label is decorative; the label still names the button', () => {
    render(
      <Segmented
        label="Platform"
        options={[{ value: 'ios', label: 'iPhone & iPad', icon: <svg data-testid="phone" /> }]}
        value="ios"
        onChange={() => {}}
      />,
    );
    const btn = screen.getByRole('button', { name: 'iPhone & iPad' });
    expect(btn).not.toHaveAttribute('aria-label');
    expect(btn).not.toHaveAttribute('title');
    expect(screen.getByTestId('phone').closest('[aria-hidden="true"]')).not.toBeNull();
  });

  it('carries the variant, fill and the caller’s placement class', () => {
    const { rerender } = render(
      <Segmented label="Case type" fill className="hr-cp-toolbar-end" options={SCOPES} value="all" onChange={() => {}} />,
    );
    const group = screen.getByRole('group', { name: 'Case type' });
    expect(group).toHaveClass('hr-seg', 'is-segmented', 'is-fill', 'hr-cp-toolbar-end');

    // `fill` is a strip's layout; chips wrap instead, so it does not apply.
    rerender(<Segmented label="Case type" variant="chips" fill options={SCOPES} value="all" onChange={() => {}} />);
    expect(group).toHaveClass('hr-seg', 'is-chips');
    expect(group).not.toHaveClass('is-fill');
    expect(group).not.toHaveClass('is-segmented');
  });

  it('renders exactly the options it is given, so a caller can add one conditionally', () => {
    // HatsPage shows "In a room" only once a hat is kept that way.
    function Placement({ withRoom }: { withRoom: boolean }) {
      return (
        <Segmented
          variant="chips"
          label="Where the hat is kept"
          options={[
            { value: 'all', label: 'All' },
            ...(withRoom ? [{ value: 'room', label: 'In a room', count: 2 }] : []),
            { value: 'none', label: 'Unassigned', count: 1 },
          ]}
          value="all"
          onChange={() => {}}
        />
      );
    }
    const { rerender } = render(<Placement withRoom={false} />);
    const group = screen.getByRole('group', { name: 'Where the hat is kept' });
    expect(within(group).getAllByRole('button')).toHaveLength(2);

    rerender(<Placement withRoom />);
    expect(within(group).getAllByRole('button').map(b => b.textContent)).toEqual(['All', 'In a room2', 'Unassigned1']);
  });
});
