import { useEffect, useState, type RefObject } from 'react';
import { copyText } from '../../lib/clipboard';
import { useToast } from './Toast';

/**
 * "Copy" beside a value you are likely to paste somewhere else — a
 * fingerprint, a token, an address, a URL to write onto a tag.
 *
 * The acknowledgment is ON the button ("Copied" for a moment) rather than a
 * toast, because the button is where the eye is and there may be three of
 * them in one card: a toast saying "Copied" does not say which. Failure is
 * the exception — the clipboard API refuses outside a secure context, which
 * on a LAN install over plain http is the normal case — and says what to do
 * instead.
 *
 * `what` names the value for assistive tech: "Copy the IPv4 address".
 *
 * `fallbackInput` is a readonly field already showing the same text. On plain
 * http `copyText` selects it and uses the legacy copy command, and if even
 * that is refused the text is left SELECTED, so the failure message's "copy
 * it by hand" is one long-press away. Three components each had their own
 * copy of this feedback before — one cleared its timer on unmount and said
 * nothing on failure, one showed a bare "✓" with no accessible name, one
 * toasted — so the same action behaved three ways.
 */
export function CopyButton({
  text,
  what,
  fallbackInput,
  className = '',
}: {
  text: string;
  what: string;
  fallbackInput?: RefObject<HTMLInputElement | null>;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <button
      type="button"
      className={`btn btn-outline-secondary btn-sm hr-copy-btn${className ? ` ${className}` : ''}`}
      aria-label={copied ? `Copied the ${what}` : `Copy the ${what}`}
      onClick={async () => {
        const ok = fallbackInput ? await copyText(text, fallbackInput.current) : await copyText(text);
        if (ok) setCopied(true);
        else {
          toast.error(fallbackInput
            ? `Couldn’t copy the ${what} — it is selected, copy it by hand.`
            : `Couldn’t copy the ${what} — select it and copy by hand.`);
        }
      }}
    >
      {/* The visible word stays "Copy" so it is always inside the accessible
          name ("Copy the API token") — a voice-control user says what they see. */}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
