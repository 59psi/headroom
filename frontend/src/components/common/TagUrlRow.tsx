import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTagBase } from '../../api/settings';

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
    const input = inputRef.current;
    try {
      // `navigator.clipboard` only exists in a secure context. Headroom is
      // commonly served over plain HTTP on the LAN (docker-compose.http80),
      // where this is undefined — so the fallback isn't a legacy nicety, it's
      // the path most installs actually take. Without it the button would
      // appear to work and copy nothing.
      if (window.isSecureContext && navigator.clipboard) {
        await navigator.clipboard.writeText(url);
      } else if (input) {
        input.select();
        input.setSelectionRange(0, url.length); // iOS ignores select() alone
        document.execCommand('copy');
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Both paths refused (older iOS Safari can). The field is readonly and
      // selectable, so long-press → Copy still works; select it for them.
      input?.select();
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
