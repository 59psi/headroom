import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { DEFAULT_HAT_BASICS } from '../hats/HatFormFields';
import { useHatLabels } from '../../lib/labels';
import { CopyButton } from '../ui/CopyButton';
import { Panel } from '../ui/Panel';
import { Segmented, type SegmentedOption } from '../ui/Segmented';
import { StatusPill } from '../ui/StatusPill';

type Platform = 'ios' | 'android';

const PLATFORMS: ReadonlyArray<SegmentedOption<Platform>> = [
  { value: 'ios', label: 'iPhone & iPad' },
  { value: 'android', label: 'Android' },
];

/**
 * Which recipe to open first. Only Android is detected: everything else —
 * iOS, and a desktop browser, where the likeliest reason to be reading this
 * is to copy the import URL into a Shortcut on the phone beside you — gets
 * the iOS recipe, the only one with anything to set up.
 */
function detectPlatform(): Platform {
  if (typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)) return 'android';
  return 'ios';
}

/**
 * Static how-to: Android PWA share target + the equivalent iOS Shortcut recipe.
 *
 * Two recipes that each matter to exactly one phone used to be printed one
 * after the other, so every reader scrolled past the one that was not theirs.
 * Now a two-way switch shows one at a time, opening on the phone this is
 * being read on. The iOS recipe is unchanged step for step — it is the whole
 * point of the card and a Shortcut built from half of it does nothing — and
 * its URL, the one thing that is tedious to type on a phone, gets a copy
 * button.
 */
export function ShareTargetCard() {
  const labels = useHatLabels();
  const [platform, setPlatform] = useState<Platform>(detectPlatform);
  const urlRef = useRef<HTMLInputElement>(null);
  const importUrl = `${window.location.origin}/api/hats/import`;

  return (
    <Panel
      title="Share photos to Headroom"
      className="hr-sharing"
      // Nothing here is stored — the setup lives on each phone — so the one
      // word is what the card asks of you, not a state it could check.
      status={(
        <StatusPill tone="info" title="A one-time setup on each phone; nothing to switch on here">
          Per phone
        </StatusPill>
      )}
      description="Send photos from your phone's share sheet straight into a bulk import."
      help={(
        <>
          <p>
            A shared photo goes into the same queue as the Bulk Import page:
            each one becomes a hat, its background is removed, and — with a
            Claude key — it is identified. Nothing about the photo leaves this
            server.
          </p>
          <p>
            Android uses the browser&rsquo;s Web Share Target, which only an
            installed app gets. iOS Safari has no Share Target, so a Shortcut
            posts the photos instead, signed with your API token — rotating
            the token means updating the Shortcut.
          </p>
        </>
      )}
    >
      <Segmented
        label="Instructions for"
        fill
        className="hr-share-platforms"
        options={PLATFORMS}
        value={platform}
        onChange={setPlatform}
      />

      {platform === 'android' ? (
        <div className="hr-share-recipe">
          <p className="mb-0">
            <strong>Android Chrome:</strong> install Headroom as a PWA (browser
            menu → Install app), then “Share to Headroom” appears in the system
            share sheet automatically — selected photos route into a bulk-import
            job.
          </p>
        </div>
      ) : (
        <div className="hr-share-recipe">
          <p>
            <strong>iOS Safari</strong> doesn&rsquo;t support Web Share Target
            yet, so use a one-time Shortcut. Open the Shortcuts app → tap{' '}
            <strong>+</strong> → add these actions in order:
          </p>
          <ol className="hr-share-steps">
            <li><strong>Receive</strong> Images from Share Sheet (turn “Show in Share Sheet” on)</li>
            <li>
              <strong>Get Contents of URL</strong>
              <ul>
                <li>
                  URL:
                  <div className="hr-field-row mt-1">
                    <input
                      ref={urlRef}
                      className="form-control font-mono hr-share-field"
                      aria-label="Import URL"
                      value={importUrl}
                      readOnly
                      onFocus={e => e.currentTarget.select()}
                    />
                    {/* The field is the fallback: `copyText` selects it and,
                        when even that is refused, leaves it selected for a
                        long-press → Copy. */}
                    <CopyButton text={importUrl} what="import URL" fallbackInput={urlRef} />

                  </div>
                </li>
                <li>Method: <code>POST</code></li>
                <li>
                  Headers → add: key=<code>Authorization</code>,
                  value=<code>Bearer YOUR-API-TOKEN</code> (copy the token from
                  the <Link to="/settings?tab=device">Account</Link> card
                  on the <strong>Device</strong> tab)
                </li>
                <li>Request Body: <code>Form</code></li>
                <li>Add field: key=<code>photos</code>, type=<code>File</code>, value=<em>Shortcut Input</em></li>
              </ul>
            </li>
            <li>Name it “Add to Headroom” and you&rsquo;re done.</li>
          </ol>
          <p className="mb-0">
            Now open Photos → select multiple → Share → “Add to Headroom”.
          </p>
        </div>
      )}

      <p className="text-muted small mt-3 mb-0">
        Each shared photo becomes a hat with the same defaults the Bulk Import
        page uses (style: {labels.style(DEFAULT_HAT_BASICS.style)} · size:{' '}
        {labels.size(DEFAULT_HAT_BASICS.size)} · condition:{' '}
        {labels.condition(DEFAULT_HAT_BASICS.condition)}) — edit after Claude finishes analyzing.
      </p>
    </Panel>
  );
}
