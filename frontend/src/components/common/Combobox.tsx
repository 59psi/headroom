import { useState, useRef, useEffect, useId } from 'react';
import { usePickerOpen } from './usePickerOpen';
import { AnchoredList } from './AnchoredList';

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
  const wrapRef = useRef<HTMLDivElement>(null);
  // State, not a ref: the list positions against this element, and a plain
  // ref would still be null on the render that first opens the list.
  const [inputEl, setInputEl] = useState<HTMLInputElement | null>(null);
  const listId = useId();

  // Filter on what's typed, but show everything when the field is empty or
  // exactly matches a suggestion — otherwise picking an option immediately
  // collapses the list to that one item, which reads as the others vanishing.
  const query = value.trim().toLowerCase();
  const exact = options.some(o => o.toLowerCase() === query);
  const shown = !query || exact ? options : options.filter(o => o.toLowerCase().includes(query));

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
        onChange={e => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onFocus={() => setOpen(true)}
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
