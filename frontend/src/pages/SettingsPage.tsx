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
import { BackupsCard } from '../components/settings/BackupsCard';
import { LogoCard } from '../components/settings/LogoCard';
import { ColorwayCatalogCard } from '../components/settings/ColorwayCatalogCard';
import { PurchasesCard } from '../components/settings/PurchasesCard';
import { AccountCard } from '../components/settings/AccountCard';
import { ShareLinksCard } from '../components/settings/ShareLinksCard';
import { TagsCard } from '../components/settings/TagsCard';

/**
 * Composition root only — every card owns its own queries, mutations and local
 * state, so this file changes when a card is added or reordered and for nothing
 * else. Order is the on-screen order.
 */
export function SettingsPage() {
  return (
    <>
      <h1 className="mb-3">Settings</h1>

      <AnthropicKeyCard />
      <ClaudeModelCard />
      <GoogleVisionKeyCard />
      <AnalysisQueueCard />
      <RecentErrorsCard />
      <EbayCredsCard />
      <MdnsCard />
      <ActivityLogCard />
      <ShareTargetCard />
      <TagsCard />
      <InventoryReportCard />
      <CollectionExportCard />
      <BackupsCard />
      <LogoCard />
      <ColorwayCatalogCard />
      <PurchasesCard />
      <AccountCard />
      <ShareLinksCard />
    </>
  );
}
