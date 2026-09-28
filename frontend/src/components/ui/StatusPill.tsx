import type { ReactNode } from 'react';

/**
 * A card's state in one word, readable from across the room: Connected, Not
 * set, Running, Failing. Settings used to state these in a sentence buried in
 * each card body ("No key configured — fallback provides colors only"), so
 * finding the one thing that needed attention meant reading every card.
 *
 * The dot carries the tone for sighted users; the WORD carries it for
 * everyone else, so a pill must never be color-only ("●" with no label).
 */
export type PillTone = 'ok' | 'warn' | 'error' | 'info' | 'off' | 'busy';

export function StatusPill({
  tone,
  children,
  title,
}: {
  tone: PillTone;
  children: ReactNode;
  /** Optional tooltip with the longer story. */
  title?: string;
}) {
  return (
    <span className={`hr-pill is-${tone}`} title={title}>
      <span className="hr-pill-dot" aria-hidden="true" />
      {children}
    </span>
  );
}
