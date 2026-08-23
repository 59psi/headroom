import { useSearchParams } from 'react-router';
import { AnthropicKeyCard } from '../components/settings/AnthropicKeyCard';
import { ClaudeModelCard } from '../components/settings/ClaudeModelCard';
import { GoogleVisionKeyCard } from '../components/settings/GoogleVisionKeyCard';
import { RecentErrorsCard } from '../components/settings/RecentErrorsCard';
import { AnalysisQueueCard } from '../components/settings/AnalysisQueueCard';
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
import { GuestViewCard } from '../components/settings/GuestViewCard';
import { TrustCertCard } from '../components/settings/TrustCertCard';

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
 */
const SECTIONS = [
  {
    id: 'analysis',
    label: 'Analysis',
    blurb: 'How a photo becomes an identified hat.',
    cards: [
      AnthropicKeyCard,
      ClaudeModelCard,
      GoogleVisionKeyCard,
      AnalysisQueueCard,
      RecentErrorsCard,
    ],
  },
  {
    id: 'data',
    label: 'Data',
    blurb: 'What the app knows about your hats, and where it came from.',
    cards: [ConstructionAuditCard, ColorwayCatalogCard, PurchasesCard, EbayCredsCard],
  },
  {
    id: 'sharing',
    label: 'Sharing',
    blurb: 'Getting the collection out of here — on screen, on paper, or on a tag.',
    cards: [
      GuestViewCard,
      ShareLinksCard,
      CollectionExportCard,
      InventoryReportCard,
      TagsCard,
      ShareTargetCard,
    ],
  },
  {
    id: 'device',
    label: 'Device',
    blurb: 'Reaching Headroom, and who is allowed to.',
    cards: [TrustCertCard, AccountCard, MdnsCard, LogoCard],
  },
  {
    id: 'maintenance',
    label: 'Upkeep',
    blurb: 'Making sure you still have all of this tomorrow.',
    cards: [BackupsCard, OffsiteBackupCard, ActivityLogCard],
  },
] as const;

export function SettingsPage() {
  // In the URL, like the Cases type filter: a section is worth linking to
  // ("open Settings → Construction audit"), and it survives a reload. `replace`
  // so tapping through five tabs doesn't build a back stack you have to unwind
  // one press at a time to leave the page.
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const active = SECTIONS.find(s => s.id === requested) ?? SECTIONS[0];

  return (
    <>
      <h1 className="mb-3">Settings</h1>

      {/* Horizontally scrollable on a phone rather than wrapping to three rows
          of tiny targets — the strip stays one line and you swipe it. */}
      <div className="hr-settings-tabs" role="tablist" aria-label="Settings sections">
        {SECTIONS.map(section => (
          <button
            key={section.id}
            type="button"
            role="tab"
            id={`settings-tab-${section.id}`}
            aria-selected={section.id === active.id}
            aria-controls={`settings-panel-${section.id}`}
            className={`hr-settings-tab${section.id === active.id ? ' is-active' : ''}`}
            onClick={() => setParams({ tab: section.id }, { replace: true })}
          >
            {section.label}
          </button>
        ))}
      </div>

      <p className="text-secondary small hr-settings-blurb">{active.blurb}</p>

      {/* Only the active section is mounted. Each card owns its own query, so
          the flat page fired nineteen requests on open — most for cards you
          were never going to look at. */}
      <div
        role="tabpanel"
        id={`settings-panel-${active.id}`}
        aria-labelledby={`settings-tab-${active.id}`}
      >
        {active.cards.map(Card => <Card key={Card.name} />)}
      </div>
    </>
  );
}
