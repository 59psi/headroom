import { useState, useRef, useEffect, useId, useMemo } from 'react';
import type { CaseRead } from '../../types';
import { usePickerOpen } from '../common/usePickerOpen';
import { AnchoredList } from '../common/AnchoredList';

/** How many freshly-made cases to pin above the room groups. */
const RECENT_COUNT = 3;

/** Sentinel that opens the "create a case" modal instead of selecting one. */
export const NEW_CASE_VALUE = '__new__';

/**
 * Searchable, grouped case picker.
 *
 * A native `<select>` is fine at six cases and unusable at sixty: iOS renders
 * it as a picker wheel with no search, so finding one case means spinning past
 * the rest. Worse, it happily let you choose a case the server will reject —
 * cases are type-exclusive (beanies or regular hats, never both) and
 * capacity-limited, so the save came back 409 with the case already chosen.
 *
 * So: type to filter on case id or room name, cases grouped under their room,
 * occupancy shown per case, and anything that would 409 rendered but disabled
 * with the reason. Disabled rather than hidden — a case you expected to see
 * silently missing is its own puzzle, and "A-021 is full" is the answer you
 * actually wanted.
 *
 * Acceptance is computed server-side (`services/capacity`) and sent on each
 * case, so this cannot disagree with the rule that gets enforced on save.
 */
export function CasePicker({
  label,
  value,
  onChange,
  cases,
  isBeanie,
  onCreateCase,
}: {
  label: string;
  /** Case id as a string; '' means unassigned. */
  value: string;
  onChange: (v: string) => void;
  cases: CaseRead[];
  /** Whether the hat being placed is a beanie — decides which cases can take it. */
  isBeanie: boolean;
  onCreateCase: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);
  // State, not a ref: the portalled list positions against this element, and a
  // plain ref is still null on the render that first opens it.
  const [inputEl, setInputEl] = useState<HTMLInputElement | null>(null);
  const listId = useId();
  const inputId = useId();

  usePickerOpen(open);

  const selected = cases.find(c => String(c.id) === value) ?? null;

  useEffect(() => {
    if (!open) return;
    function onDocDown(e: PointerEvent) {
      const target = e.target as HTMLElement;
      // Portalled into <body>, so the list is not a descendant of the wrapper.
      if (wrapRef.current?.contains(target) || target.closest('.hr-combobox-list')) return;
      setOpen(false);
    }
    document.addEventListener('pointerdown', onDocDown);
    return () => document.removeEventListener('pointerdown', onDocDown);
  }, [open]);

  const { recent, groups } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (c: CaseRead) =>
      !q
      || c.display_id.toLowerCase().includes(q)
      || c.room_name.toLowerCase().includes(q)
      || caseTypeLabel(c).toLowerCase().includes(q);

    // The three newest, pinned to the top — a hat being added right now
    // usually belongs in a case made minutes ago, and hunting for it in a
    // room group is the long way round. Only when nothing is typed: once you
    // are searching, you have said what you want and a pinned section is just
    // noise in front of it.
    const recent = q
      ? []
      : [...cases]
          .sort((a, b) => b.created_at.localeCompare(a.created_at))
          .slice(0, RECENT_COUNT);
    const pinned = new Set(recent.map(c => c.id));

    // Grouped by room, rooms alphabetical, cases by display id within each —
    // the same order they appear on the Rooms page, so the two read the same.
    const byRoom = new Map<string, CaseRead[]>();
    for (const c of cases.filter(c => matches(c) && !pinned.has(c.id))) {
      const list = byRoom.get(c.room_name) ?? [];
      list.push(c);
      byRoom.set(c.room_name, list);
    }
    const groups = [...byRoom.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([room, list]) => ({
        room,
        list: list.sort((a, b) => a.display_id.localeCompare(b.display_id)),
      }));
    return { recent, groups };
  }, [cases, query]);

  function pick(next: string) {
    if (next === NEW_CASE_VALUE) onCreateCase();
    else onChange(next);
    setOpen(false);
    setQuery('');
  }

  /** One case row. Shared so the pinned recents and the room groups can't drift. */
  function renderCase(c: CaseRead) {
    const ok = isBeanie ? c.accepts_beanie : c.accepts_regular;
    const used = isBeanie ? c.beanie_count : c.regular_count;
    return (
      <li key={c.id}>
        <button
          type="button"
          role="option"
          aria-selected={String(c.id) === value}
          // Announced rather than shown, so a screen reader gets the reason
          // the visual dimming conveys.
          aria-disabled={!ok}
          disabled={!ok}
          className={
            'hr-combobox-option hr-case-option'
            + (String(c.id) === value ? ' is-selected' : '')
            + (ok ? '' : ' is-unavailable')
          }
          title={ok ? undefined : unavailableReason(c, isBeanie)}
          onMouseDown={e => { e.preventDefault(); if (ok) pick(String(c.id)); }}
        >
          <span className="hr-case-id font-mono">{c.display_id}</span>
          <span className="hr-case-meta">
            {/* `nominal_capacity`, not `used + free`: free hits 0 at full AND
                stays 0 when overfull, so the old sum rendered a 4th hat in a
                3-hat case as "4/4" — the one case where the number matters. */}
            {caseTypeLabel(c)} · {c.nominal_capacity > 0 ? `${used}/${c.nominal_capacity}` : used}
            {c.overfull && <span className="hr-case-overfull"> overfull</span>}
            {' · '}{c.room_name}
          </span>
          {!ok && <span className="hr-case-why">{unavailableReason(c, isBeanie)}</span>}
        </button>
      </li>
    );
  }

  const summary = selected
    ? `${selected.display_id} · ${selected.room_name}`
    : 'Unassigned';

  return (
    <div className="hr-combobox" ref={wrapRef}>
      <label className="form-label" htmlFor={inputId}>{label}</label>
      <input
        ref={setInputEl}
        id={inputId}
        aria-label={label}
        className="form-control"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        // Closed, the field reads as the current selection; open, it is the
        // search box. One control doing both is what keeps this to a single
        // tap for "which case is this again".
        value={open ? query : summary}
        placeholder="Search by case or room…"
        onFocus={() => { setOpen(true); setQuery(''); }}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}
      />
      <AnchoredList anchor={inputEl} open={open} id={listId} role="listbox">
          <li>
            <button
              type="button"
              role="option"
              aria-selected={value === ''}
              className={'hr-combobox-option' + (value === '' ? ' is-selected' : '')}
              onMouseDown={e => { e.preventDefault(); pick(''); }}
            >
              Unassigned
            </button>
          </li>
          <li>
            <button
              type="button"
              role="option"
              aria-selected={false}
              className="hr-combobox-option hr-case-new"
              onMouseDown={e => { e.preventDefault(); pick(NEW_CASE_VALUE); }}
            >
              + Create New Case…
            </button>
          </li>

          {recent.length > 0 && (
            <li>
              <div className="hr-case-group" aria-hidden="true">Recently added</div>
              <ul className="hr-plain-list">
                {recent.map(c => renderCase(c))}
              </ul>
            </li>
          )}

          {groups.map(({ room, list }) => (
            <li key={room}>
              <div className="hr-case-group" aria-hidden="true">{room}</div>
              <ul className="hr-plain-list">
                {list.map(c => renderCase(c))}
              </ul>
            </li>
          ))}

          {groups.length === 0 && recent.length === 0 && (
            <li className="hr-case-empty">No case matches “{query}”</li>
          )}
      </AnchoredList>
    </div>
  );
}

function caseTypeLabel(c: CaseRead): string {
  return c.case_type === 'archive' ? 'Archive' : 'Daily';
}

/** Why this case can't take the hat — the thing a bare 409 never told you. */
function unavailableReason(c: CaseRead, isBeanie: boolean): string {
  if (isBeanie && c.regular_count > 0) return 'holds regular hats';
  if (!isBeanie && c.beanie_count > 0) return 'holds beanies';
  return 'full';
}
