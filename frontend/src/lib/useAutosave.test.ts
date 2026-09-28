import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAutosave } from './useAutosave';

/**
 * The hook's doc comment makes three promises a naive debounce breaks —
 * saves never overlap, `flush`/unmount never lose keystrokes, "Saved" is only
 * claimed for the value on screen — and one more that is easy to miss: the
 * value it was mounted with is the baseline and is never sent back. These
 * pin each one against a fake server whose responses the test controls.
 */

/** A save the test resolves or rejects by hand, to hold a request in flight. */
function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/**
 * A fake server: records every value sent, the order they land in, and the
 * most requests ever in flight at once. `hold()` makes the NEXT save wait
 * for the test; otherwise saves resolve on the next microtask.
 */
function fakeServer() {
  const sent: string[] = [];
  let stored: string | undefined;
  let inFlight = 0;
  let maxInFlight = 0;
  const held: Array<ReturnType<typeof deferred>> = [];
  let holdNext = 0;
  let failNext: unknown = undefined;
  const save = vi.fn(async (v: string) => {
    sent.push(v);
    inFlight++;
    maxInFlight = Math.max(maxInFlight, inFlight);
    try {
      if (holdNext > 0) {
        holdNext--;
        const d = deferred();
        held.push(d);
        await d.promise;
      } else {
        await Promise.resolve();
      }
      if (failNext !== undefined) {
        const e = failNext;
        failNext = undefined;
        throw e;
      }
      stored = v;
    } finally {
      inFlight--;
    }
  });
  return {
    save,
    sent,
    get stored() { return stored; },
    get maxInFlight() { return maxInFlight; },
    hold(n = 1) { holdNext += n; },
    failWith(e: unknown) { failNext = e; },
    /** Resolve the oldest held request. */
    async release() {
      const d = held.shift();
      if (!d) throw new Error('nothing held');
      await act(async () => { d.resolve(); });
      await drain();
    },
  };
}

/** Let queued promise continuations (the save chain) run to completion. */
async function drain() {
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
}

async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

function mount(server: ReturnType<typeof fakeServer>, initial = 'hello', options = { delay: 500 }) {
  return renderHook(
    ({ value, enabled }: { value: string; enabled?: boolean }) =>
      useAutosave(value, server.save, { ...options, enabled }),
    { initialProps: { value: initial } as { value: string; enabled?: boolean } },
  );
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('useAutosave', () => {
  it('never sends the value it was mounted with', async () => {
    const server = fakeServer();
    const { result } = mount(server);

    await advance(5000);

    expect(server.save).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('debounces: one save of the final value once typing pauses', async () => {
    const server = fakeServer();
    const { result, rerender } = mount(server);

    rerender({ value: 'hello w' });
    await advance(300);
    rerender({ value: 'hello wo' });
    await advance(300);
    rerender({ value: 'hello world' });

    expect(result.current.status).toBe('pending');
    await advance(499);
    expect(server.save).not.toHaveBeenCalled();

    await advance(1);
    expect(server.sent).toEqual(['hello world']);
    await drain();
    expect(result.current.status).toBe('saved');
    expect(result.current.savedCount).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it('reports "saving" while the request is in flight', async () => {
    const server = fakeServer();
    server.hold();
    const { result, rerender } = mount(server);

    rerender({ value: 'hello!' });
    await advance(500);
    expect(result.current.status).toBe('saving');

    await server.release();
    expect(result.current.status).toBe('saved');
  });

  it('never overlaps saves: a newer value waits for the slow one, then wins', async () => {
    const server = fakeServer();
    server.hold();
    const { result, rerender } = mount(server);

    rerender({ value: 'first' });
    await advance(500);
    expect(server.sent).toEqual(['first']);

    // Keep typing while the first save hangs. The debounce fires, but the
    // second request must queue, not race.
    rerender({ value: 'second' });
    await advance(500);
    expect(server.sent).toEqual(['first']);
    expect(result.current.status).toBe('saving');

    await server.release();

    expect(server.sent).toEqual(['first', 'second']);
    expect(server.maxInFlight).toBe(1);
    expect(server.stored).toBe('second');
    expect(result.current.status).toBe('saved');
  });

  it('says "Unsaved changes", not "Saved", when a save lands under newer typing', async () => {
    const server = fakeServer();
    server.hold();
    const { result, rerender } = mount(server);

    rerender({ value: 'first' });
    await advance(500);
    rerender({ value: 'first, then more' });
    // The follow-up's debounce has NOT fired yet when the first save lands.
    await server.release();

    expect(result.current.status).toBe('pending');
    expect(result.current.savedCount).toBe(1);

    await advance(500);
    expect(server.sent).toEqual(['first', 'first, then more']);
    expect(result.current.status).toBe('saved');
    expect(result.current.savedCount).toBe(2);
  });

  it('flush() saves now, without waiting for the pause', async () => {
    const server = fakeServer();
    const { result, rerender } = mount(server);

    rerender({ value: 'hello, blur' });
    await act(async () => { await result.current.flush(); });

    expect(server.sent).toEqual(['hello, blur']);
    expect(result.current.status).toBe('saved');

    // …and the debounce it pre-empted does not send it a second time.
    await advance(2000);
    expect(server.sent).toEqual(['hello, blur']);
  });

  it('flush() with nothing changed sends nothing', async () => {
    const server = fakeServer();
    const { result } = mount(server);

    await act(async () => { await result.current.flush(); });

    expect(server.save).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('unmounting two keystrokes after the last pause still saves them', async () => {
    const server = fakeServer();
    const { rerender, unmount } = mount(server);

    rerender({ value: 'hello there' });
    await advance(100);
    unmount();
    await drain();

    expect(server.sent).toEqual(['hello there']);
    expect(server.stored).toBe('hello there');
  });

  it('unmounting with nothing unsaved sends nothing', async () => {
    const server = fakeServer();
    const { rerender, unmount } = mount(server);

    rerender({ value: 'edited' });
    await advance(500);
    await drain();
    unmount();
    await drain();

    expect(server.sent).toEqual(['edited']);
  });

  it('a failed save reports "error" with the reason, and the next edit retries', async () => {
    const server = fakeServer();
    const boom = new Error('500 Internal Server Error');
    server.failWith(boom);
    const { result, rerender } = mount(server);

    rerender({ value: 'doomed' });
    await advance(500);
    await drain();

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe(boom);
    expect(result.current.savedCount).toBe(0);

    rerender({ value: 'doomed, retried' });
    // A new edit is unsaved work, not a standing failure.
    expect(result.current.status).toBe('pending');
    await advance(500);
    await drain();

    expect(server.sent).toEqual(['doomed', 'doomed, retried']);
    expect(result.current.status).toBe('saved');
    expect(result.current.error).toBeNull();
  });

  it('typing back to the saved text is not "Unsaved changes"', async () => {
    const server = fakeServer();
    const { result, rerender } = mount(server);

    rerender({ value: 'hello!' });
    expect(result.current.status).toBe('pending');
    rerender({ value: 'hello' });
    await advance(2000);

    // Nothing differs from what the server holds: no request, and no
    // "Unsaved changes" note left standing over a field with nothing unsaved.
    expect(server.save).not.toHaveBeenCalled();
    // 'idle', not 'saved' either: nothing was sent, so "Saved" would be a
    // claim about a request that never happened.
    expect(result.current.status).toBe('idle');
  });

  it('…including text saved earlier in the session, not just the mount value', async () => {
    const server = fakeServer();
    const { result, rerender } = mount(server);

    rerender({ value: 'saved once' });
    await advance(500);
    await drain();
    expect(result.current.status).toBe('saved');

    rerender({ value: 'saved once, then more' });
    expect(result.current.status).toBe('pending');
    rerender({ value: 'saved once' });
    await advance(2000);
    await drain();

    expect(server.sent).toEqual(['saved once']);
    expect(result.current.status).toBe('idle');
  });

  it('after a failure, landing on the failed text again retries it', async () => {
    // The failed text is NOT on the server; arriving back at it (type a
    // letter, delete it) is unsaved work like any other.
    const server = fakeServer();
    server.failWith(new Error('offline'));
    const { result, rerender } = mount(server);

    rerender({ value: 'hello!' });
    await advance(500);
    await drain();
    expect(result.current.status).toBe('error');

    rerender({ value: 'hello!x' });
    rerender({ value: 'hello!' });
    await advance(500);
    await drain();

    expect(server.sent).toEqual(['hello!', 'hello!']);
    expect(server.stored).toBe('hello!');
    expect(result.current.status).toBe('saved');
  });

  it('typing back to the saved text after a failure clears the failure', async () => {
    const server = fakeServer();
    server.failWith(new Error('offline'));
    const { result, rerender } = mount(server);

    rerender({ value: 'hello!' });
    await advance(500);
    await drain();
    expect(result.current.status).toBe('error');

    rerender({ value: 'hello' });
    await advance(2000);

    // What is on screen is what the server holds; "Not saved" would be a lie.
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(server.sent).toEqual(['hello!']);
  });

  it('reverting to the old text while an edit is in flight saves the revert', async () => {
    // The in-flight request will overwrite the server with the edit, so the
    // reverted text on screen is NOT what the server will hold — it must be
    // sent after, or the discarded edit silently wins.
    const server = fakeServer();
    server.hold();
    const { result, rerender } = mount(server);

    rerender({ value: 'hello, oops' });
    await advance(500);
    rerender({ value: 'hello' });
    await advance(500);
    await server.release();
    await advance(500);
    await drain();

    expect(server.sent).toEqual(['hello, oops', 'hello']);
    expect(server.stored).toBe('hello');
    expect(server.maxInFlight).toBe(1);
    expect(result.current.status).toBe('saved');
  });

  it('…and unmounting right after that revert still saves it', async () => {
    const server = fakeServer();
    server.hold();
    const { rerender, unmount } = mount(server);

    rerender({ value: 'hello, oops' });
    await advance(500);
    rerender({ value: 'hello' });
    unmount();
    await server.release();
    await drain();

    expect(server.stored).toBe('hello');
  });

  it('reverting while a doomed edit is in flight ends clean, not "Not saved"', async () => {
    // The edit fails, so the server still holds the old text — which is
    // exactly what is on screen. Nothing is unsaved; nothing failed that
    // still matters.
    const server = fakeServer();
    server.hold();
    server.failWith(new Error('offline'));
    const { result, rerender } = mount(server);

    rerender({ value: 'hello, oops' });
    await advance(500);
    rerender({ value: 'hello' });
    await server.release();
    await advance(500);
    await drain();

    expect(server.sent).toEqual(['hello, oops']);
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('unmounting while the last edit is on the wire gives it a second try if that fails', async () => {
    // The usual way out on a phone: type, tap Back. The blur flushes, so the
    // edit is in flight when the card unmounts. The in-flight request is what
    // the server WILL hold only if it lands — if it fails there is no card
    // left to say "Not saved" and no next keystroke to retry on, so the
    // unmount must still queue a save that checks again once it is done.
    const server = fakeServer();
    server.hold();
    server.failWith(new Error('offline'));
    const { result, rerender, unmount } = mount(server);

    rerender({ value: 'hello, blur' });
    act(() => { void result.current.flush(); });
    await drain();
    expect(server.sent).toEqual(['hello, blur']);
    unmount();
    await server.release();
    await drain();

    expect(server.sent).toEqual(['hello, blur', 'hello, blur']);
    expect(server.stored).toBe('hello, blur');
    expect(server.maxInFlight).toBe(1);
  });

  it('…and when that in-flight save lands, the unmount sends nothing more', async () => {
    const server = fakeServer();
    server.hold();
    const { result, rerender, unmount } = mount(server);

    rerender({ value: 'hello, blur' });
    act(() => { void result.current.flush(); });
    await drain();
    unmount();
    await server.release();
    await drain();

    expect(server.sent).toEqual(['hello, blur']);
    expect(server.stored).toBe('hello, blur');
  });

  it('typing away and back while a doomed edit is in flight still sends it', async () => {
    // The keystrokes came after the request left, so they are edits like any
    // other: when the request they were counting on fails, they get their
    // own save rather than leaving "Not saved" until the next keystroke.
    const server = fakeServer();
    server.hold();
    server.failWith(new Error('offline'));
    const { result, rerender } = mount(server);

    rerender({ value: 'draft' });
    await advance(500);
    rerender({ value: 'draft 2' });
    rerender({ value: 'draft' });
    await server.release();
    await advance(500);
    await drain();

    expect(server.sent).toEqual(['draft', 'draft']);
    expect(server.stored).toBe('draft');
    expect(result.current.status).toBe('saved');
    expect(result.current.error).toBeNull();
  });

  it('typing away and back while an edit is in flight sends nothing more', async () => {
    const server = fakeServer();
    server.hold();
    const { result, rerender } = mount(server);

    rerender({ value: 'draft' });
    await advance(500);
    rerender({ value: 'draft 2' });
    rerender({ value: 'draft' });
    await server.release();
    await advance(2000);
    await drain();

    expect(server.sent).toEqual(['draft']);
    expect(result.current.status).toBe('saved');
  });

  it('enabled: false holds edits back until re-enabled', async () => {
    const server = fakeServer();
    const { result, rerender } = mount(server);

    rerender({ value: 'offline edit', enabled: false });
    await advance(2000);
    expect(server.save).not.toHaveBeenCalled();

    rerender({ value: 'offline edit', enabled: true });
    await advance(500);
    await drain();
    expect(server.sent).toEqual(['offline edit']);
    expect(result.current.status).toBe('saved');
  });

  it('uses the latest save function, not the one from mount', async () => {
    const server = fakeServer();
    const other = vi.fn(async (_: string) => {});
    const { rerender } = renderHook(
      ({ value, save }) => useAutosave(value, save, { delay: 500 }),
      { initialProps: { value: 'a', save: server.save as (v: string) => Promise<unknown> } },
    );

    rerender({ value: 'b', save: other });
    await advance(500);
    await drain();

    expect(other).toHaveBeenCalledWith('b');
    expect(server.save).not.toHaveBeenCalled();
  });

  it('isEqual decides what counts as a change', async () => {
    const save = vi.fn(async (_: { text: string }) => {});
    const { rerender } = renderHook(
      ({ value }) => useAutosave(value, save, { delay: 500, isEqual: (a, b) => a.text === b.text }),
      { initialProps: { value: { text: 'same' } } },
    );

    // A new object with the same text is not an edit.
    rerender({ value: { text: 'same' } });
    await advance(1000);
    expect(save).not.toHaveBeenCalled();

    rerender({ value: { text: 'different' } });
    await advance(500);
    await drain();
    expect(save).toHaveBeenCalledWith({ text: 'different' });
  });
});
