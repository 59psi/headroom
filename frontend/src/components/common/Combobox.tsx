import { useState, useRef, useEffect, useId } from 'react';
import { usePickerOpen } from './usePickerOpen';
import { AnchoredList } from './AnchoredList';

/**
 * Matches for `query`, best first: exact, then prefix, then anywhere.
 *
 * Ordering matters because the list is capped by screen height on a phone. A
 * plain `includes` filter is alphabetical, so typing "Links" put "Cypress
 * Links" above "Links" — the thing you typed, pushed below a longer name that
 * merely contains it.
 */
function rank(options: string[], query: string): string[] {
  const score = (o: string) => {
    const lower = o.toLowerCase();
    if (lower === query) return 0;
    if (lower.startsWith(query)) return 1;
    return lower.includes(query) ? 2 : 3;
  };
  return options
    .map((o, i) => ({ o, s: score(o), i }))
    .filter(x => x.s < 3)
    // Stable within a tier: preserve the caller's order (alphabetical from
    // `distinct_values`) rather than reshuffling equally-good matches.
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .map(x => x.o);
}

/**
 * A text field with a visible, tappable list of known values.
 *
 * Replaces a native `<datalist>`, which was the wrong tool on a phone: iOS
 * renders it as a thin suggestion strip above the keyboard that is easy to
 * miss entirely, so a field with ten known values read as a blank text box and
 * the structured half of the input was effectively invisible. This shows the
 * options as real, tappable rows — filtered as you type — while still
 * accepting anything typed, which is the whole point of the field.
 *
 * Free text is the value: there is no hidden id, and `onChange` fires with
 * exactly what is in the box. Picking a suggestion is a shortcut for typing it.
 */
export function Combobox({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
  help?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  // Whether the value in the box was typed here, as opposed to picked from the
  // list or arriving as a prop. Only typing should narrow the list.
  const [typing, setTyping] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  // State, not a ref: the list positions against this element, and a plain
  // ref would still be null on the render that first opens the list.
  const [inputEl, setInputEl] = useState<HTMLInputElement | null>(null);
  const listId = useId();

  // Filter on what's TYPED. The list stays whole when the field is empty, and
  // when the current value arrived by picking rather than typing — otherwise
  // choosing an option would immediately collapse the list to that one row,
  // which reads as the other choices vanishing.
  //
  // That second condition used to be `options.some(o => o === query)`, i.e.
  // "the value exactly matches a suggestion". It cannot tell picking from
  // typing, and typing a known value out in full is the normal case — so
  // typing "Links" when Links was already on the list showed the ENTIRE list,
  // headed by 'Ohana and 23XI Racing, and looked like the search was ignoring
  // the box. Tracking where the value came from is the distinction the old
  // test actually meant.
  const query = value.trim().toLowerCase();
  const shown = !query || !typing ? options : rank(options, query);

  // A click anywhere else closes the list. Pointerdown rather than click so the
  // list is gone before a tap on another control lands.
  useEffect(() => {
    if (!open) return;
    function onDocDown(e: PointerEvent) {
      const target = e.target as HTMLElement;
      // The list is portalled into <body>, so it is no longer a descendant of
      // the wrapper — without this second check, pointerdown on an option
      // closes the list before the option's own mousedown can land.
      if (wrapRef.current?.contains(target) || target.closest('.hr-combobox-list')) return;
      setOpen(false);
    }
    document.addEventListener('pointerdown', onDocDown);
    return () => document.removeEventListener('pointerdown', onDocDown);
  }, [open]);

  usePickerOpen(open);

  function choose(option: string) {
    onChange(option);
    setOpen(false);
    setActive(-1);
    // Picked, not typed — so reopening the list shows every choice again
    // rather than just the one already in the box.
    setTyping(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive(prev => {
        const next = prev + step;
        if (next < 0) return shown.length - 1;
        if (next >= shown.length) return 0;
        return next;
      });
      return;
    }
    // Enter only commits a highlighted suggestion. With nothing highlighted it
    // must fall through to the form, or the field would swallow submit.
    if (e.key === 'Enter' && open && active >= 0 && active < shown.length) {
      e.preventDefault();
      choose(shown[active]);
    }
  }

  return (
    <div className="hr-combobox" ref={wrapRef}>
      <label className="form-label" htmlFor={id}>{label}</label>
      <input
        ref={setInputEl}
        id={id}
        aria-label={label}
        className="form-control"
        placeholder={placeholder}
        value={value}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        onChange={e => { onChange(e.target.value); setOpen(true); setActive(-1); setTyping(true); }}
        // Focusing an already-filled field shows everything: you are reopening
        // the list to change your mind, not searching for what is already in
        // the box.
        onFocus={() => { setOpen(true); setTyping(false); }}
        // Focus alone is not enough to reopen. Picking an option calls
        // `preventDefault` on its mousedown so the field keeps focus, so after
        // a pick the input is focused with the list closed — and tapping it
        // again fires no focus event, leaving no way back to the list short of
        // focusing something else first.
        //
        // Guarded on `!open`: unlike focus, click fires every time, including
        // when you tap mid-word to move the cursor. Unconditionally clearing
        // `typing` there would widen the list back to everything while you are
        // still in the middle of narrowing it.
        onClick={() => { if (!open) { setOpen(true); setTyping(false); } }}
        onKeyDown={onKeyDown}
      />
      <AnchoredList anchor={inputEl} open={open && shown.length > 0} id={listId} role="listbox">
          {shown.map((option, i) => {
            const selected = option.toLowerCase() === query;
            return (
              <li key={option}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={
                    'hr-combobox-option'
                    + (i === active ? ' is-active' : '')
                    + (selected ? ' is-selected' : '')
                  }
                  // Mousedown, not click: the input's blur would otherwise
                  // close the list before the click landed.
                  onMouseDown={e => { e.preventDefault(); choose(option); }}
                >
                  {option}
                </button>
              </li>
            );
          })}
      </AnchoredList>
      {help && <div className="form-text">{help}</div>}
    </div>
  );
}
