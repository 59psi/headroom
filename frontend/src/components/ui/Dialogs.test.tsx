import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DialogProvider, useConfirm, usePrompt } from './Dialogs';
import { Modal } from '../common/Modal';

/**
 * The in-app confirm/prompt stand in for `window.confirm`/`window.prompt`
 * at every destructive call site, so the contract they must keep is the
 * browser's: the promise answers exactly once, every way out that is not the
 * action button answers "no", and the action runs only on "yes". Beyond
 * that, the two things the browser dialogs could never do: put focus on the
 * SAFE button when the action is destructive, and hand focus back after.
 */
let confirm: ReturnType<typeof useConfirm>;
let prompt: ReturnType<typeof usePrompt>;
function Capture() {
  confirm = useConfirm();
  prompt = usePrompt();
  return <button type="button">Opener</button>;
}

function setup() {
  return render(
    <DialogProvider>
      <Capture />
    </DialogProvider>,
  );
}

/** Open a dialog from outside React's event system, like an awaited call in a handler. */
function open<T>(call: () => Promise<T>): Promise<T> {
  let p!: Promise<T>;
  act(() => { p = call(); });
  return p;
}

describe('confirm', () => {
  it('resolves true on the action button and closes', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => confirm({ title: 'Revoke link?', confirmLabel: 'Revoke link' }));

    const dialog = await screen.findByRole('dialog', { name: 'Revoke link?' });
    await user.click(screen.getByRole('button', { name: 'Revoke link' }));

    await expect(answer).resolves.toBe(true);
    expect(dialog).not.toBeInTheDocument();
  });

  it.each([
    ['the Cancel button', async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
    }],
    ['Escape', async (user: ReturnType<typeof userEvent.setup>) => {
      await user.keyboard('{Escape}');
    }],
    ['the header close button', async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(screen.getByRole('button', { name: 'Close' }));
    }],
    ['a click on the backdrop', async () => {
      fireEvent.click(document.querySelector('.modal')!);
    }],
  ])('resolves false on %s', async (_label, dismiss) => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => confirm({ title: 'Delete case?', tone: 'danger' }));
    await screen.findByRole('alertdialog');

    await dismiss(user);

    await expect(answer).resolves.toBe(false);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('a click inside the dialog is not a dismissal', async () => {
    const user = userEvent.setup();
    setup();
    const settled = vi.fn();
    open(() => confirm({ title: 'Remove key?', body: 'Analysis falls back to colors only.' })).then(settled);

    await user.click(await screen.findByText('Analysis falls back to colors only.'));
    await user.click(screen.getByRole('heading', { name: 'Remove key?' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(settled).not.toHaveBeenCalled();
  });

  it('destructive: focus starts on Cancel, so a reflexive Enter is the safe answer', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => confirm({
      title: 'Delete case?', body: 'Its hats become unassigned.', tone: 'danger', confirmLabel: 'Delete case',
    }));
    await screen.findByRole('alertdialog');

    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Delete case' })).toHaveClass('btn-danger');

    await user.keyboard('{Enter}');
    await expect(answer).resolves.toBe(false);
  });

  it('destructive with no label says what it does — "Delete", not "Confirm"', async () => {
    setup();
    open(() => confirm({ title: 'Delete case?', tone: 'danger' }));
    expect(await screen.findByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });

  it('non-destructive: focus starts on the action', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => confirm({ title: 'Start backup?' }));
    await screen.findByRole('dialog');

    const action = screen.getByRole('button', { name: 'Confirm' });
    expect(action).toHaveFocus();
    expect(action).toHaveClass('btn-primary');

    await user.keyboard('{Enter}');
    await expect(answer).resolves.toBe(true);
  });

  it('shows the body, and reads it out as the dialog’s description', async () => {
    setup();
    open(() => confirm({ title: 'Remove key?', body: 'Analysis falls back to colors only.' }));
    const dialog = await screen.findByRole('dialog', { name: 'Remove key?' });
    // Without the description a screen reader hears the title and the focused
    // button — "Remove key? Cancel" — and never what removing it does.
    expect(dialog).toHaveAccessibleDescription('Analysis falls back to colors only.');
  });

  it('warns "can’t be undone" by default only when the action is destructive', async () => {
    const user = userEvent.setup();
    setup();
    open(() => confirm({ title: 'Delete case?', tone: 'danger' }));
    const destructive = await screen.findByRole('alertdialog', { name: 'Delete case?' });
    expect(destructive).toHaveAccessibleDescription('This can’t be undone.');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // Said under every confirm it told people "Re-analyze every hat?" was
    // irreversible — a warning on everything is a warning on nothing.
    open(() => confirm({ title: 'Re-analyze every hat?' }));
    const plain = await screen.findByRole('dialog', { name: 'Re-analyze every hat?' });
    expect(screen.queryByText('This can’t be undone.')).not.toBeInTheDocument();
    expect(plain).not.toHaveAttribute('aria-describedby');
  });

  it('an Escape in a confirm opened over another dialog closes only the confirm', async () => {
    // "Remove this color?" opens over the color editor. Every open modal
    // listened on the document, so one Escape dismissed both.
    const user = userEvent.setup();
    const outerClose = vi.fn();
    render(
      <DialogProvider>
        <Modal title="Edit colors" onClose={outerClose}><Capture /></Modal>
      </DialogProvider>,
    );
    const answer = open(() => confirm({ title: 'Remove this color?', tone: 'danger' }));
    await screen.findByRole('alertdialog');

    await user.keyboard('{Escape}');

    await expect(answer).resolves.toBe(false);
    expect(outerClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'Edit colors' })).toBeInTheDocument();
  });

  it('custom cancel label', async () => {
    setup();
    open(() => confirm({ title: 'Leave?', cancelLabel: 'Stay' }));
    expect(await screen.findByRole('button', { name: 'Stay' })).toBeInTheDocument();
  });

  it('hands focus back to the control that opened it', async () => {
    const user = userEvent.setup();
    setup();
    const opener = screen.getByRole('button', { name: 'Opener' });
    opener.focus();

    open(() => confirm({ title: 'Remove key?' }));
    await screen.findByRole('dialog');
    expect(opener).not.toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(opener).toHaveFocus();
  });

  it('keeps focus where the person put it when the provider re-renders', async () => {
    // The dialog's close handler must not change identity on every provider
    // render: the modal's focus effect keys on it, and re-running that effect
    // throws focus back to the autofocus button — here, from the destructive
    // action the person had tabbed to, back to Cancel under their finger.
    const user = userEvent.setup();
    const { rerender } = setup();
    open(() => confirm({ title: 'Delete case?', tone: 'danger', confirmLabel: 'Delete case' }));
    await screen.findByRole('alertdialog');

    await user.tab();
    const action = screen.getByRole('button', { name: 'Delete case' });
    expect(action).toHaveFocus();

    rerender(
      <DialogProvider>
        <Capture />
      </DialogProvider>,
    );

    expect(action).toHaveFocus();
  });

  it('a second request cancels the first instead of stacking two modals', async () => {
    setup();
    const first = open(() => confirm({ title: 'First?' }));
    await screen.findByRole('dialog', { name: 'First?' });

    open(() => confirm({ title: 'Second?' }));

    await expect(first).resolves.toBe(false);
    expect(await screen.findByRole('dialog', { name: 'Second?' })).toBeInTheDocument();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
  });
});

describe('prompt', () => {
  it('prefills the default, focuses the field, and resolves with what was typed', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => prompt({
      title: 'Rename room', label: 'Room name', defaultValue: 'Closet', confirmLabel: 'Rename',
    }));

    const field = await screen.findByLabelText('Room name');
    expect(field).toHaveValue('Closet');
    expect(field).toHaveFocus();

    await user.clear(field);
    await user.type(field, 'Garage');
    await user.click(screen.getByRole('button', { name: 'Rename' }));

    await expect(answer).resolves.toBe('Garage');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('Enter in the field submits', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => prompt({ title: 'New room', label: 'Room name' }));

    await user.type(await screen.findByLabelText('Room name'), 'Attic{Enter}');

    await expect(answer).resolves.toBe('Attic');
  });

  it('an emptied field answers "" — distinct from canceling', async () => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => prompt({ title: 'Edit label', label: 'Label', defaultValue: 'Old' }));

    await user.clear(await screen.findByLabelText('Label'));
    await user.click(screen.getByRole('button', { name: 'OK' }));

    await expect(answer).resolves.toBe('');
  });

  it.each([
    ['Cancel', async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
    }],
    ['Escape', async (user: ReturnType<typeof userEvent.setup>) => {
      await user.keyboard('{Escape}');
    }],
    ['the backdrop', async () => {
      fireEvent.click(document.querySelector('.modal')!);
    }],
  ])('resolves null on %s, even after typing', async (_label, dismiss) => {
    const user = userEvent.setup();
    setup();
    const answer = open(() => prompt({ title: 'Rename room', label: 'Room name', defaultValue: 'Closet' }));
    await user.type(await screen.findByLabelText('Room name'), ' 2');

    await dismiss(user);

    await expect(answer).resolves.toBeNull();
  });

  it('shows the body and placeholder', async () => {
    setup();
    open(() => prompt({
      title: 'New room', label: 'Room name', body: 'Rooms hold cases.', placeholder: 'e.g. Closet',
    }));
    expect(await screen.findByText('Rooms hold cases.')).toBeInTheDocument();
    expect(screen.getByLabelText('Room name')).toHaveAttribute('placeholder', 'e.g. Closet');
  });

  it('a second prompt opens with ITS default, not the first one’s typing', async () => {
    const user = userEvent.setup();
    setup();
    const first = open(() => prompt({ title: 'First', label: 'Name', defaultValue: 'one' }));
    await user.type(await screen.findByLabelText('Name'), ' typed');

    const second = open(() => prompt({ title: 'Second', label: 'Name', defaultValue: 'two' }));

    await expect(first).resolves.toBeNull();
    await screen.findByRole('dialog', { name: 'Second' });
    expect(screen.getByLabelText('Name')).toHaveValue('two');

    await user.click(screen.getByRole('button', { name: 'OK' }));
    await expect(second).resolves.toBe('two');
  });
});

describe('outside a provider', () => {
  // A bare-rendered component still ASKS before it destroys anything — in
  // the browser's style, which is a cosmetic bug, instead of not at all,
  // which is a data-loss one.
  it('confirm falls back to window.confirm, carrying the warning text', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<Capture />);

    await expect(confirm({
      title: 'Remove key?', body: 'Analysis falls back to colors only.', tone: 'danger',
    })).resolves.toBe(false);

    expect(spy).toHaveBeenCalledTimes(1);
    const message = spy.mock.calls[0][0] as string;
    expect(message).toContain('Remove key?');
    // The body is the warning the call site used to pass to window.confirm
    // directly; the fallback must not drop it.
    expect(message).toContain('Analysis falls back to colors only.');

    spy.mockReturnValue(true);
    await expect(confirm({ title: 'Remove key?' })).resolves.toBe(true);
  });

  it('prompt falls back to window.prompt with the default value', async () => {
    const spy = vi.spyOn(window, 'prompt').mockReturnValue('Garage');
    render(<Capture />);

    await expect(prompt({ title: 'Rename room', label: 'Room name', defaultValue: 'Closet' }))
      .resolves.toBe('Garage');

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toContain('Rename room');
    expect(spy.mock.calls[0][1]).toBe('Closet');

    spy.mockReturnValue(null);
    await expect(prompt({ title: 'Rename room', label: 'Room name' })).resolves.toBeNull();
  });

  it('never asks a blank question when the title is markup', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('x');
    render(<Capture />);

    await confirm({ title: <>Delete <strong>Closet</strong>?</> });
    await prompt({ title: <em>Rename</em>, label: 'Room name' });
    // A title split across expressions arrives as an array of strings.
    await confirm({ title: ['Delete ', 'Closet', '?'] });

    expect(confirmSpy.mock.calls[0][0]).toBe('Are you sure?');
    expect(promptSpy.mock.calls[0][0]).toBe('Room name');
    expect(confirmSpy.mock.calls[1][0]).toBe('Delete Closet?');
  });

  it('never renders an in-app dialog', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<Capture />);
    await confirm({ title: 'Remove key?' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
