import { useId, useMemo, useState, type ComponentType, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { AnthropicKeyCard } from '../components/settings/AnthropicKeyCard';
import { ClaudeModelCard } from '../components/settings/ClaudeModelCard';
import { GoogleVisionKeyCard } from '../components/settings/GoogleVisionKeyCard';
import { RecentErrorsCard } from '../components/settings/RecentErrorsCard';
import { AnalysisQueueCard } from '../components/settings/AnalysisQueueCard';
import { RepricingCard } from '../components/settings/RepricingCard';
import { EbayCredsCard } from '../components/settings/EbayCredsCard';
import { MdnsCard } from '../components/settings/MdnsCard';
import { ActivityLogCard } from '../components/settings/ActivityLogCard';
import { ShareTargetCard } from '../components/settings/ShareTargetCard';
import { InventoryReportCard } from '../components/settings/InventoryReportCard';
import { CollectionExportCard } from '../components/settings/CollectionExportCard';
import { OffsiteBackupCard } from '../components/settings/OffsiteBackupCard';
import { BackupsCard } from '../components/settings/BackupsCard';
import { LogoCard } from '../components/settings/LogoCard';
import { ColorwayCatalogCard } from '../components/settings/ColorwayCatalogCard';
import { PurchasesCard } from '../components/settings/PurchasesCard';
import { AccountCard } from '../components/settings/AccountCard';
import { ShareLinksCard } from '../components/settings/ShareLinksCard';
import { TagsCard } from '../components/settings/TagsCard';
import { ConstructionAuditCard } from '../components/settings/ConstructionAuditCard';
import { SharedPricesCard } from '../components/settings/SharedPricesCard';
import { FrozenPricesCard } from '../components/settings/FrozenPricesCard';
import { GuestViewCard } from '../components/settings/GuestViewCard';
import { TrustCertCard } from '../components/settings/TrustCertCard';
import { useAnalysisErrorCount, analysisErrorLabel } from '../components/layout/AnalysisErrorBadge';

/**
 * Settings, grouped by what you came here to do.
 *
 * This was nineteen cards in one flat scroll, ordered by the sequence they
 * happened to be built in — the API keys next to LAN discovery next to the
 * backup list. Finding anything meant scrolling past everything, and on a
 * phone "everything" is most of a minute.
 *
 * Grouped by INTENT rather than by subsystem: "how hats get identified" is one
 * errand, and it does not matter that it spans two API keys, a worker queue and
 * an error list. The names are the errand, not the component.
 *
 * Each card entry carries the title the card renders and a few words people
 * might search for instead ("anthropic" for the Claude key, "restore" for
 * backups). Search reads these rather than the rendered DOM, so it can find a
 * card in a section that is not mounted — and the census test holds every
 * `name` to the title its card actually renders, so the two cannot drift.
 */
interface CardEntry {
  Card: ComponentType;
  /** Exactly the title the card renders. */
  name: string;
  /** Extra search terms, space-separated. */
  keywords: string;
}

interface Section {
  id: string;
  label: string;
  blurb: string;
  icon: ReactNode;
  cards: readonly CardEntry[];
}

const ICON_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  className: 'hr-settings-tab-icon',
  'aria-hidden': true,
};

// Exported for `SettingsPage.test.tsx`, which must count the REAL cards
// rather than a number typed beside a hand-written roster. That roster said
// 21 while 22 were mounted, and the missing one (TrustCertCard) could be
// deleted with the whole suite green — the exact failure the census exists to
// prevent, committed inside the census itself.
export const SECTIONS: readonly Section[] = [
  {
    id: 'analysis',
    label: 'Analysis',
    blurb: 'How a photo becomes an identified hat.',
    icon: <svg {...ICON_PROPS}><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></svg>,
    cards: [
      { Card: AnthropicKeyCard, name: 'Claude API key', keywords: 'anthropic api key token claude ai vision' },
      { Card: ClaudeModelCard, name: 'Claude model', keywords: 'model opus sonnet haiku anthropic' },
      { Card: GoogleVisionKeyCard, name: 'Google Vision key', keywords: 'google cloud vision logo brand fallback api key' },
      { Card: AnalysisQueueCard, name: 'Analysis queue', keywords: 'queue worker reanalyze re-analyze backlog analyze' },
      { Card: RecentErrorsCard, name: 'Recent analysis errors', keywords: 'errors failures failed retry' },
    ],
  },
  {
    id: 'data',
    label: 'Data',
    blurb: 'What the app knows about your hats, and where it came from.',
    icon: <svg {...ICON_PROPS}><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /><path d="M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></svg>,
    cards: [
      { Card: ConstructionAuditCard, name: 'Construction audit', keywords: 'hydro hydrolite construction material' },
      { Card: RepricingCard, name: 'Re-pricing', keywords: 'price resale melin recap sweep schedule value' },
      { Card: FrozenPricesCard, name: 'Frozen prices', keywords: 'price locked stuck manual' },
      { Card: SharedPricesCard, name: 'Prices shared by many hats', keywords: 'price duplicate shared line median' },
      { Card: ColorwayCatalogCard, name: 'Colorway catalog', keywords: 'colorway catalog melin recap autocomplete' },
      { Card: PurchasesCard, name: 'Purchase history', keywords: 'purchase order email cost basis import json paid' },
      { Card: EbayCredsCard, name: 'eBay comparable listings', keywords: 'ebay comps listings browse api credentials' },
    ],
  },
  {
    id: 'sharing',
    label: 'Sharing',
    blurb: 'Getting the collection out of here — on screen, on paper, or on a tag.',
    icon: <svg {...ICON_PROPS}><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.2 10.9l7.6-4.6M8.2 13.1l7.6 4.6" /></svg>,
    cards: [
      { Card: GuestViewCard, name: 'Guest browsing', keywords: 'guest public read-only visitor' },
      { Card: ShareLinksCard, name: 'Share links', keywords: 'share link token public url' },
      { Card: CollectionExportCard, name: 'Share the collection', keywords: 'export csv download collection' },
      { Card: InventoryReportCard, name: 'Inventory report', keywords: 'report print pdf inventory insurance' },
      { Card: TagsCard, name: 'Tags & labels', keywords: 'nfc qr tag label sticker print' },
      { Card: ShareTargetCard, name: 'Share photos to Headroom', keywords: 'share sheet ios shortcut android import token' },
    ],
  },
  {
    id: 'device',
    label: 'Device',
    blurb: 'Reaching Headroom, and who is allowed to.',
    icon: <svg {...ICON_PROPS}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg>,
    cards: [
      { Card: TrustCertCard, name: 'Trust this device', keywords: 'https certificate tls ca trust' },
      { Card: AccountCard, name: 'Account', keywords: 'account password passkey login sign out api token user' },
      { Card: MdnsCard, name: 'LAN discovery (mDNS)', keywords: 'mdns lan bonjour network hostname headroom.local ip' },
      { Card: LogoCard, name: 'Site logo', keywords: 'logo branding image icon' },
    ],
  },
  {
    id: 'maintenance',
    label: 'Upkeep',
    blurb: 'Making sure you still have all of this tomorrow.',
    icon: <svg {...ICON_PROPS}><path d="M12 3a9 9 0 1 0 9 9" /><path d="M21 3v6h-6" /><path d="M12 7v5l3 2" /></svg>,
    cards: [
      { Card: BackupsCard, name: 'Backups', keywords: 'backup restore download archive' },
      { Card: OffsiteBackupCard, name: 'Off-site backup', keywords: 'offsite rclone upload cloud backup' },
      { Card: ActivityLogCard, name: 'Recent activity', keywords: 'activity log audit history' },
    ],
  },
];

function matches(section: Section, card: CardEntry, terms: string[]): boolean {
  const haystack = `${card.name} ${card.keywords} ${section.label}`.toLowerCase();
  return terms.every(t => haystack.includes(t));
}

export function SettingsPage() {
  // In the URL, like the Cases type filter: a section is worth linking to
  // ("open Settings → Construction audit"), and it survives a reload. `replace`
  // so tapping through five tabs doesn't build a back stack you have to unwind
  // one press at a time to leave the page.
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const active = SECTIONS.find(s => s.id === requested) ?? SECTIONS[0];
  const [query, setQuery] = useState('');
  const searchId = useId();
  const errorCount = useAnalysisErrorCount();

  const terms = useMemo(
    () => query.toLowerCase().split(/\s+/).filter(Boolean),
    [query],
  );
  const results = useMemo(
    () => terms.length === 0
      ? []
      : SECTIONS
        .map(s => ({ section: s, cards: s.cards.filter(c => matches(s, c, terms)) }))
        .filter(r => r.cards.length > 0),
    [terms],
  );
  const searching = terms.length > 0;

  function selectTab(id: string) {
    setQuery('');
    setParams({ tab: id }, { replace: true });
  }

  return (
    <>
      <h1 className="mb-3">Settings</h1>

      <div className="hr-settings">
        {/* The side column on a wide screen (sticky, beside the cards). On a
            phone this wrapper dissolves (`display: contents`) so ONLY the tab
            strip sticks — search and tabs stuck together would hold ~115px of
            an 844px screen. */}
        <div className="hr-settings-side">
          <div className="hr-settings-search">
            <svg className="hr-settings-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
            </svg>
            <label htmlFor={searchId} className="visually-hidden">Search settings</label>
            <input
              id={searchId}
              type="search"
              className="form-control"
              placeholder="Search settings"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') setQuery(''); }}
              autoComplete="off"
              enterKeyHint="search"
            />
          </div>

          {/* One row of five on a phone, a labeled list on a wide screen. The
              section names are short (Data / Device / Upkeep) precisely so five
              equal columns fit ~320px without ellipsis. */}
          <nav className="hr-settings-nav" aria-label="Settings sections">
          <div className="hr-settings-tabs" role="tablist" aria-label="Settings sections">
            {SECTIONS.map(section => {
              const isActive = !searching && section.id === active.id;
              const count = section.id === 'analysis' ? errorCount : 0;
              return (
                <button
                  key={section.id}
                  type="button"
                  role="tab"
                  id={`settings-tab-${section.id}`}
                  aria-selected={isActive}
                  aria-controls={`settings-panel-${section.id}`}
                  className={`hr-settings-tab${isActive ? ' is-active' : ''}`}
                  onClick={() => selectTab(section.id)}
                >
                  {section.icon}
                  <span className="hr-settings-tab-text">
                    <span>{section.label}</span>
                    {/* Hidden from the tab's accessible name: it would read
                        "Upkeep Making sure you still have…", and the same
                        sentence heads the panel the tab opens. */}
                    <span className="hr-settings-tab-blurb" aria-hidden="true">{section.blurb}</span>
                  </span>
                  {count > 0 && (
                    <span className="hr-settings-count" title={analysisErrorLabel(count)}>
                      <span aria-hidden="true">{count > 9 ? '9+' : count}</span>
                      <span className="visually-hidden">{analysisErrorLabel(count)}</span>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          </nav>
        </div>

        <div className="hr-settings-main">
          {searching ? (
            <div role="region" aria-label="Search results" aria-live="polite">
              {results.length === 0 ? (
                <div className="card hr-settings-empty">
                  <p className="mb-2">No settings match “{query.trim()}”.</p>
                  <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setQuery('')}>
                    Clear search
                  </button>
                </div>
              ) : (
                results.map(({ section, cards }) => (
                  <div key={section.id} className="hr-settings-group">
                    <div className="hr-settings-heading">
                      <h2>{section.label}</h2>
                      <p>{section.blurb}</p>
                    </div>
                    <div className="hr-settings-panel">
                      {cards.map(({ Card, name }) => <Card key={name} />)}
                    </div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <>
              <div className="hr-settings-heading">
                <h2>{active.label}</h2>
                <p>{active.blurb}</p>
              </div>
              {/* Only the active section is mounted. Each card owns its own
                  query, so the flat page fired one request per card on open —
                  most for cards you were never going to look at. */}
              <div
                role="tabpanel"
                id={`settings-panel-${active.id}`}
                className="hr-settings-panel"
                // `labelledby` is the ARIA spelling and is NOT subject to the
                // American-spelling rule — it is a W3C attribute name, not
                // prose. An unanchored `labelled -> labeled` sweep renamed it
                // in 2.57.0; React passes unknown `aria-*` through verbatim, so
                // the only signal was a console warning nobody read, and the
                // tabpanel lost its name.
                aria-labelledby={`settings-tab-${active.id}`}
              >
                {/* Keyed by the card's name: stable, unique within the table
                    (the census test checks), and immune to minification —
                    `Card.name` was the key once, and esbuild shortens function
                    names to a letter, so two cards could share one. */}
                {active.cards.map(({ Card, name }) => <Card key={name} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
