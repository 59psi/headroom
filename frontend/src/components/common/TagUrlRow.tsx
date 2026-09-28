import { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTagBase } from '../../api/settings';
import { qk } from '../../lib/queryKeys';
import { CopyButton } from '../ui/CopyButton';

/**
 * Copy the URL to write onto an NFC tag for this hat or case.
 *
 * The base comes from the server rather than `window.location.origin` so that
 * what you write into hardware is the same host the printed labels carry —
 * browsing by IP once shouldn't quietly produce a batch of tags naming a DHCP
 * lease. See `tag_service.get_tag_base`.
 */
export function TagUrlRow({ kind, ident }: { kind: 'h' | 'c'; ident: string | number }) {
  const { data } = useQuery({ queryKey: qk.settings.tags(), queryFn: getTagBase });
  const inputRef = useRef<HTMLInputElement>(null);

  if (!data) return null;
  const url = `${data.base_url}/t/${kind}/${ident}`;

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
        {/* The field doubles as the plain-http fallback: `copyText` selects
            it for the legacy copy command, and leaves it selected when even
            that is refused. */}
        <CopyButton text={url} what="NFC tag URL" fallbackInput={inputRef} />
      </div>
    </div>
  );
}
