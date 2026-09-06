import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTagBase } from '../../api/settings';
import { copyText } from '../../lib/clipboard';

/**
 * Copy the URL to write onto an NFC tag for this hat or case.
 *
 * The base comes from the server rather than `window.location.origin` so that
 * what you write into hardware is the same host the printed labels carry —
 * browsing by IP once shouldn't quietly produce a batch of tags naming a DHCP
 * lease. See `tag_service.get_tag_base`.
 */
export function TagUrlRow({ kind, ident }: { kind: 'h' | 'c'; ident: string | number }) {
  const { data } = useQuery({ queryKey: ['settings', 'tags'], queryFn: getTagBase });
  const inputRef = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);

  if (!data) return null;
  const url = `${data.base_url}/t/${kind}/${ident}`;

  async function copy() {
    // See `lib/clipboard.copyText` — the secure-context check and the
    // selection fallback lived here first and are shared now.
    if (await copyText(url, inputRef.current)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }
  }

  return (
    <div className="hr-tag-url-row">
      <label className="form-label small text-secondary" htmlFor={`tag-url-${kind}-${ident}`}>
        NFC tag URL
      </label>
      <div className="d-flex gap-2">
        <input
          id={`tag-url-${kind}-${ident}`}
          ref={inputRef}
          className="form-control form-control-sm font-mono"
          value={url}
          readOnly
          onFocus={e => e.currentTarget.select()}
        />
        <button type="button" className="btn btn-outline-secondary btn-sm" onClick={copy}>
          {copied ? '✓' : 'Copy'}
        </button>
      </div>
    </div>
  );
}
