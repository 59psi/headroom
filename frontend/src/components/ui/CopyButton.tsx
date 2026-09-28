import { useEffect, useState } from 'react';
import { copyText } from '../../lib/clipboard';
import { useToast } from './Toast';

/**
 * "Copy" beside a value you are likely to paste somewhere else — a
 * fingerprint, a token, an address.
 *
 * The acknowledgement is ON the button ("Copied" for a moment) rather than a
 * toast, because the button is where the eye is and there may be three of
 * them in one card: a toast saying "Copied" does not say which. Failure is
 * the exception — the clipboard API refuses outside a secure context, which
 * on a LAN install over plain http is the normal case — and says what to do
 * instead.
 *
 * `what` names the value for assistive tech: "Copy the IPv4 address".
 */
export function CopyButton({ text, what }: { text: string; what: string }) {
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
      className="btn btn-outline-secondary btn-sm hr-copy-btn"
      aria-label={copied ? `Copied the ${what}` : `Copy the ${what}`}
      onClick={async () => {
        if (await copyText(text)) setCopied(true);
        else toast.error(`Couldn’t copy the ${what} — select it and copy by hand.`);
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
