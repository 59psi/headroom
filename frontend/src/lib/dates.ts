/**
 * Calendar dates — the kind a person enters, not instants.
 *
 * A wear is logged against a DAY, and a purchase is dated by a day. Neither
 * has a time of day, and both went wrong the same way: through a `Date`,
 * which is an instant. `new Date().toISOString().slice(0, 10)` is the date in
 * Greenwich, so from 5 pm on the US west coast "today" was already tomorrow
 * — the tag page offered a second wear for a hat worn that morning. And
 * `new Date('2024-03-15T00:00:00Z').toLocaleDateString()` is the evening of
 * the 14th anywhere west of Greenwich, so the hat page printed a purchase date
 * one day earlier than the Edit form beside it.
 *
 * Both helpers stay in the calendar: the device's own day for "today", and a
 * date read straight off the string's date part, never through a UTC instant.
 */

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/**
 * Today on this device, as `YYYY-MM-DD` — the day the person holding the
 * phone is living in, which is the day a wear logged now belongs to.
 */
export function localToday(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * A date-only value for display, in the device's locale format.
 *
 * Takes `YYYY-MM-DD` or a timestamp whose date part is what was entered —
 * `purchased_at` is stored as midnight of the chosen day and read back as
 * `…T00:00:00Z`, and that midnight is not a moment anyone meant. The date part
 * is parsed as a LOCAL calendar date, so it prints as the day that was typed
 * in every time zone. Anything unparseable comes back as it was.
 */
export function formatDateOnly(value: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return value;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString();
}
