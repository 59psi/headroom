import type { CaseRead } from '../types';

/** The two kinds of case, as the API spells them. */
export type CaseType = CaseRead['case_type'];

/**
 * Everything the UI knows about a case type, in one table.
 *
 * It was spread across six files: the hat page re-derived the words with a
 * nested ternary, the New case page, the Edit case page and the New case
 * modal each typed out the same two `<option>`s, the Edit case page worked the
 * id prefix out with `caseType === 'archive' ? 'A' : 'D'`, and the Cases tab
 * kept its own filter union. A third type would have been six edits, and the
 * one missed would have shown up as "Daily wear" on a case of the new kind.
 *
 * `prefix` is the letter `case_service._make_display_id` puts in front of the
 * number (A-001, D-001) — stated here for the warning the Edit case page shows
 * BEFORE a type change renumbers the case; the server remains what assigns it.
 */
export const CASE_TYPES: ReadonlyArray<{ value: CaseType; label: string; prefix: string }> = [
  { value: 'archive', label: 'Archive', prefix: 'A' },
  { value: 'daily_wear', label: 'Daily wear', prefix: 'D' },
];

function entry(type: CaseType) {
  return CASE_TYPES.find(t => t.value === type) ?? CASE_TYPES[0];
}

/** "Archive" / "Daily wear". */
export function caseTypeName(type: CaseType): string {
  return entry(type).label;
}

/** The display-id letter a case of this type is numbered under. */
export function caseTypePrefix(type: CaseType): string {
  return entry(type).prefix;
}

/** A value from outside (a URL, a select) narrowed to a real case type. */
export function isCaseType(value: string | null | undefined): value is CaseType {
  return CASE_TYPES.some(t => t.value === value);
}
