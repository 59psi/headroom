/**
 * Every response shape the API returns, mirrored from its Pydantic schema.
 *
 * Each interface carries the SCHEMA'S OWN NAME (`ImportJobRead`, not
 * `ImportJob`), so a mirror can be found from the OpenAPI document by name and
 * checked field by field — eleven used to go by a second name, which made the
 * pairing a lookup table nobody kept. Shapes that only the client builds (the
 * WebAuthn JSON forms below, the write bodies) say so where they are declared.
 *
 * A union spelled out here must name exactly the server's enum values —
 * `tests/test_wire_vocabulary.py` reads this file and compares them. That is
 * why the status fields spell their literals inline rather than through an
 * alias: an alias leaves the test nothing to compare.
 */

/** How prominent a color is on the hat. Mirrors `ColorTier`. */
export type ColorTier = 'primary' | 'secondary' | 'tertiary' | 'accent';

export interface ColorTag {
  color_name: string;
  general_color: string;
  hex_value: string;
  dominance_rank: number;
  tier?: 'primary' | 'secondary' | 'tertiary' | 'accent';
}

/**
 * One color as `PUT /api/hats/{id}/colors` takes it (`ColorTagWrite`).
 *
 * The rank is the position in the list — the server ignores a sent
 * `dominance_rank` — and a blank name or general color is derived from the
 * hex. A read `ColorTag` is assignable to this, so an edit can send the
 * palette it loaded.
 */
export interface ColorTagWrite {
  color_name?: string | null;
  general_color?: string | null;
  hex_value: string;
  tier?: ColorTier;
}

export interface HatSummary {
  id: number;
  display_id: string | null;
  style: string;
  is_beanie: boolean;
  photo_path: string | null;
  thumb_path: string | null;
}

export interface CaseRead {
  id: number;
  case_type: 'archive' | 'daily_wear';
  sequence_number: number;
  display_id: string;
  capacity: number | null;
  /** What the physical case cost new. Same for every case, so it is
   *  published rather than stored per row. */
  retail_price: number;
  hat_count: number;
  beanie_count: number;
  regular_count: number;
  room_id: number;
  /** Null for an orphaned case — its room is gone. It used to arrive as the
   *  placeholder "Unknown", which read as a room of that name. */
  room_name: string | null;
  /** Up to 4 hat photos for the collage the Cases grid renders. */
  hat_thumbs: string[];
  /** Past nominal capacity — a 4th hat in a 3-hat case. Allowed, but shown. */
  overfull: boolean;
  /** The count at which this case reads as FULL (per-case override aware). */
  nominal_capacity: number;
  /** Both type defaults, served so no client restates them. */
  nominal_regular: number;
  nominal_beanie: number;
  /** Computed server-side from the same rule the write path enforces
   *  (`capacity.evaluate`), so the picker can't disagree with what a save will
   *  accept. */
  accepts_regular: boolean;
  accepts_beanie: boolean;
  free_regular: number;
  free_beanie: number;
  created_at: string;
  updated_at: string;
}

export interface CaseDetail extends CaseRead {
  hats: HatSummary[];
}

export interface HatRead {
  id: number;
  case_id: number | null;
  position_in_case: number | null;
  /** Set when the hat lives in a room with NO case. `room_id` resolves either
   *  this or the case's room, so most callers should read that instead. */
  direct_room_id: number | null;
  /** A special or limited run — stated by you, never derived. */
  limited_edition: boolean;
  display_id: string | null;
  case_display_id: string | null;
  case_type: 'archive' | 'daily_wear' | null;
  photo_path: string | null;
  original_path: string | null;
  thumb_path: string | null;
  condition: string;
  date_last_worn: string | null;
  wear_count: number;
  size: string;
  style: string;
  is_beanie: boolean;
  colors: ColorTag[];
  /** "owner" when you set these colors — re-analysis keeps them; null when
   *  analysis wrote them. */
  colors_source: string | null;
  room_id: number | null;
  room_name: string | null;

  // AI / pricing
  brand: string | null;
  logo_detected: string | null;
  artist_series: string | null;
  /** Free-form construction ("HYDRO", "HYDROLite", "Thermal", …). */
  construction: string | null;
  /** Derived from `construction` server-side — read-only here. */
  hydrolite: boolean;
  hydro: boolean;
  model_name: string | null;
  colorway: string | null;
  purchase_price: number | null;
  purchased_at: string | null;
  model_confidence: string | null;
  style_descriptor: string | null;
  design_notes: string | null;
  /** Yours. Never written by analysis. */
  owner_notes: string | null;
  estimated_new_price: number | null;
  estimated_new_price_source: string | null;
  resale_price: number | null;
  resale_price_source: string | null;
  resale_price_url: string | null;
  resale_checked_at: string | null;
  /** What `resale_price` is a price OF — see `lib/valuation.ts`.
   *  "manual" (a person typed it) · "model" (comparable listings for this
   *  model) · "category" (every listing in the style category — a price level,
   *  not this hat's value) · null (no price). */
  resale_price_scope: 'manual' | 'model' | 'category' | null;
  analysis_status: 'pending' | 'ok' | 'fallback' | 'skipped' | 'error' | null;
  /** Set while analysis (or a re-cut) is in flight — the step it is on. */
  analysis_stage: 'cutout' | 'identifying' | 'pricing' | 'resale' | null;
  /** When `analysis_stage` last changed — lets the UI say "in identifying
   *  for 41 min" instead of an indefinite "Analyzing…". */
  analysis_stage_at: string | null;
  analysis_job_id: number | null;
  analysis_error: string | null;
  analyzed_at: string | null;

  // v0.3 disposition
  disposed_at: string | null;
  disposed_via: 'sold' | 'gifted' | 'lost' | 'trashed' | 'trade' | null;
  disposed_price: number | null;
  disposed_to: string | null;
  disposed_notes: string | null;

  // v0.4 eBay
  ebay_avg_price: number | null;
  ebay_median_price: number | null;
  ebay_listing_count: number | null;
  ebay_search_url: string | null;
  ebay_checked_at: string | null;

  created_at: string;
  updated_at: string;
}

/** Named for reuse; the literals live on `HatRead`, where the parity test reads them. */
export type AnalysisStatus = NonNullable<HatRead['analysis_status']>;
export type AnalysisStage = NonNullable<HatRead['analysis_stage']>;
export type DisposedVia = NonNullable<HatRead['disposed_via']>;

/** What `POST /api/admin/ebay/refresh/{id}` answers with: the
 *  comparable-listing fields as they were persisted on the hat. */
export interface EbayComps {
  ebay_avg_price: number | null;
  ebay_median_price: number | null;
  ebay_listing_count: number | null;
  ebay_search_url: string | null;
  ebay_checked_at: string | null;
}

export interface ImportJobItemRead {
  id: number;
  filename: string;
  status: 'queued' | 'processing' | 'done' | 'error' | 'skipped' | 'canceled';
  hat_id: number | null;
  error: string | null;
  /** Null for an item recorded before sizes were kept. */
  bytes: number | null;
}

export interface ImportJobRead {
  id: number;
  created_at: string | null;
  finished_at: string | null;
  total: number;
  done: number;
  errors: number;
  skipped: number;
  status: 'queued' | 'running' | 'done' | 'canceled';
  items: ImportJobItemRead[];
}

/** `POST /api/hats/import` — the job was queued; poll it by id. */
export interface ImportJobCreated {
  id: number;
  total: number;
  status: ImportJobRead['status'];
}

export interface ActivityRow {
  id: number;
  occurred_at: string;
  kind: string;
  entity_type: string;
  entity_id: number | null;
  summary: string;
  details: string | null;
}

export interface EbayCredsStatus {
  configured: boolean;
  app_id_masked: string | null;
  marketplace: string;
  detected_env: 'production' | 'sandbox' | 'unknown' | null;
}

export interface SearchResult {
  id: number;
  display_id: string | null;
  case_display_id: string | null;
  photo_path: string | null;
  thumb_path: string | null;
  style: string;
  condition: string;
  size: string;
  is_beanie: boolean;
  brand: string | null;
  model_name: string | null;
  /** Projected so the shared filter bar works on this page too. */
  construction: string | null;
  /** A text search matches it, so the row shows it (`HatRow`). */
  colorway: string | null;
  colors: ColorTag[];
  room_id: number | null;
  room_name: string | null;
}

export interface ColorSearchResult extends SearchResult {
  matched_hex: string;
  /** Raw CIEDE2000 to the matched swatch — NOT the sort key. See matched_rank. */
  distance: number;
  /** dominance_rank of the matched swatch. 1 is the hat's main color. */
  matched_rank: number;
}

export interface PaletteColor {
  name: string;
  hex: string;
}

/** One dropdown option: the stored value and the label a person reads. The
 *  server types `value` as string-or-integer; each endpoint serves one kind —
 *  enum values are strings, room ids (`/api/meta/rooms`) are numbers. */
export interface MetaOption<V extends string | number = string> {
  value: V;
  label: string;
}

/** A free-text suggestion (colorways, model names) — `{value}` only. */
export interface TextOption {
  value: string;
}

/**
 * A style option, carrying whether that style is a beanie.
 *
 * Served by the API rather than derived here, because this flag decides which
 * cases the picker offers (6 beanies per case vs 3 regular hats). A hardcoded
 * list of beanie styles in TypeScript would be a second definition of the
 * server's `BEANIE_STYLES`, and the day they disagreed the picker would offer
 * a case that the save then rejects with a 409.
 */
export interface StyleOption extends MetaOption {
  is_beanie: boolean;
}

export interface RoomRead {
  id: number;
  name: string;
  case_count: number;
  /** Hats kept in this room with no case — they have no other home in the UI. */
  loose_hat_count: number;
  /** Exactly one room is the default: the fallback for orphaned cases and the
   *  room new cases land in. It's the only room that can't be deleted. */
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

/** A room and what is in it. Loose hats first — see RoomDetailPage. */
export interface RoomDetail extends RoomRead {
  loose_hats: HatRead[];
  cases: CaseRead[];
}

/** One color on a shared hat: its name and swatch, nothing else. */
export interface SharedColor {
  name: string;
  hex: string;
}

/** One hat as an outside viewer sees it — the server's narrowed projection.
 *  No prices, purchase history, disposition, wear counts or notes: they are
 *  not in the payload, so they cannot be rendered by accident. */
export interface SharedHat {
  id: number;
  display_id: string | null;
  brand: string | null;
  model_name: string | null;
  style: string;
  /** The style as every screen prints it ("A-Game") — a guest cannot read
   *  `/api/meta` for the labels, so the server sends the words with the hat. */
  style_label: string;
  photo_url: string | null;
  /** The grid thumbnail on the same public route; the full photo is for the hat page. */
  thumb_url: string | null;
  colors: SharedColor[];
  case: string | null;
  room: string | null;
}

export interface SharedCollection {
  label: string;
  hat_count: number;
  hats: SharedHat[];
}

/** Mirrors `LogoStatus`. `version` changes whenever the logo file does. */
export interface LogoStatus {
  logo_path: string | null;
  /** The file's mtime (ns). The server always sends it; optional so a fixture
   *  that only names the path still type-checks. */
  version?: number | null;
}

export interface ApiKeyStatus {
  configured: boolean;
  /** Where the key came from — the database (set in Settings, which wins) or
   *  the server's environment. Null when there is none. */
  source: 'database' | 'environment' | null;
  masked: string | null;
}

export interface ApiKeyTestResult {
  ok: boolean;
  detail: string;
}

export interface MdnsStatus {
  enabled: boolean;
  advertising: boolean;
  hostname: string;
  port: number;
  ip: string | null;
  /** Global LAN IPv6, advertised beside the v4 address. Null = host has none. */
  ipv6: string | null;
  url: string | null;
  error: string | null;
}

/** The host burned into printed QR labels and NFC tags. */
export interface TagBaseStatus {
  base_url: string;
  /** 'request' = whatever host you're browsing on; 'settings' = pinned. */
  source: 'settings' | 'request';
  example_url: string;
}

export interface ModelStatus {
  model_id: string;
  source: 'database' | 'environment' | 'default';
  /** The built-in default; the picker marks this option "(default)". */
  default_model_id: string;
}

export interface RecentError {
  hat_id: number;
  display_id: string | null;
  analysis_error: string | null;
  analyzed_at: string | null;
  photo_path: string | null;
  /** The 320px tile derivative, so the row's thumbnail is not the full
   *  1200px cutout. Null for a hat analyzed before thumbnails existed;
   *  `tileSrc` falls back to `photo_path`. */
  thumb_path: string | null;
}

export interface BackupInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
}

/** One hat waiting in the analysis queue. Mirrors `PendingHat` in schemas/admin.py. */
export interface PendingHat {
  id: number;
  display_id: string | null;
  label: string | null;
  stage: string | null;
  photo_path: string | null;
}

/** A bulk re-analysis run. Progress is derived server-side, never accumulated. */
export interface AnalysisJobRead {
  id: number;
  total: number;
  done: number;
  failed: number;
  status: 'running' | 'done';
  started_at: string;
  finished_at: string | null;
}

export interface AnalysisQueueStatus {
  worker_alive: boolean;
  queued: number;
  pending_count: number;
  pending: PendingHat[];
  current_job: AnalysisJobRead | null;
  recent_jobs: AnalysisJobRead[];
}

/** A background task's pulse: last attempt, last success, failures in a row. */
export interface TaskHealthRead {
  name: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  /** What the last successful run produced — for the retention prune, rows
   *  removed across both tables. Null before the first run. */
  last_result: number | null;
}

/** Is the daily retention prune still running?
 *
 *  The activity-log row COUNT cannot answer this — a table nobody is writing
 *  to and a prune that died three weeks ago look identical from a count. This
 *  is the only thing bounding `activity_log` and `auth_sessions`, so a silent
 *  death ends in a full disk. */
export interface RetentionStatus {
  retention_days: number;
  health: TaskHealthRead;
}

/** Whether the scheduled-backup task is actually working — last attempt, last
 *  success, consecutive failures — plus the persisted off-box upload record. */
export interface BackupHealthRead {
  enabled: boolean;
  running: boolean;
  last_attempt_at: string | null;
  last_success_at: string | null;
  /** True when `last_success_at` came from a file's mtime, not a recorded run.
   *  The health record is process-local and a restart clears it, so a null
   *  would otherwise read as "never succeeded" after every reboot. */
  last_success_derived: boolean;
  last_error: string | null;
  /** Why the last cycle correctly wrote nothing. Backups only run when the
   *  data changed, so an old snapshot is not by itself a problem. */
  last_skip_reason: string | null;
  consecutive_failures: number;
}

/** The certificate the HTTPS front door is actually serving.
 *
 *  Reported, never enforced: the certificate belongs to Caddy, so failing
 *  readiness on it would restart-loop the app without fixing anything. */
export interface TlsStatusRead {
  /** False on every install without an HTTPS front door — not a problem. */
  applicable: boolean;
  host: string | null;
  port: number;
  not_before: string | null;
  not_after: string | null;
  days_remaining: number | null;
  expired: boolean;
  /** Expired, or close enough that renewal has evidently stopped. */
  needs_attention: boolean;
  hostname_ok: boolean | null;
  /** The trust anchor itself was replaced — Caddy regenerated the authority,
   *  so every device that installed the old root by hand will now refuse the
   *  connection. Categorically worse than an expiry: a leaf reissues itself,
   *  a hand-installed root has to be reinstalled on each device. */
  ca_changed: boolean;
  /** The fingerprint the devices actually trust, when it differs from what is
   *  being served. Meaningless alone — Caddy gives every root the same name,
   *  so only the pair identifies which is which. */
  ca_expected_sha256: string | null;
  /** When the intermediate that signs our leaves runs out. */
  issuer_not_after: string | null;
  /** The served cert is short because it was CLAMPED to a nearly-expired
   *  intermediate, not because it is itself old. Identical on the certificate,
   *  opposite fixes: renewal repairs the first and cannot repair the second,
   *  since every reissue lands on the same issuer ceiling. */
  clamped_by_issuer: boolean;
  /** SHA-256 of the CA this install hands out. Caddy names every root the
   *  same, so two installs give two different roots with one name — a browser
   *  matching by name picks the wrong one and reports "invalid signature" on a
   *  chain that verifies fine at the server. Only the fingerprint separates
   *  them. */
  ca_sha256: string | null;
  /** Whether the chain the front door actually SERVES leads up to
   *  `ca_sha256` (the exported root). False after a CA restore while Caddy
   *  still holds a leaf from the interim authority — every device refuses it.
   *  Null when it cannot be told (no exported root, no handshake,
   *  Python < 3.13). */
  chain_matches_ca: boolean | null;
  error: string | null;
}

/** One way to get a backup off the box.
 *
 *  The setup steps come from the SERVER, not from a copy in here: they are
 *  facts about what it will run — which binary, which environment variable —
 *  and a second copy in TypeScript is a second thing to keep in step. */
export interface BackupUploadProvider {
  name: string;
  label: string;
  /** Shape of a valid destination, e.g. `user@host::module/path`. */
  destination_hint: string;
  example: string;
  setup: string[];
  /** Env var carrying this transport's secret, where it takes one. Named, not
   *  read — the value never leaves the host. */
  secret_env: string | null;
  binary: string;
  binary_available: boolean;
}

/** Whether the off-box backup copy is configured, and whether it works.
 *
 *  Separate from `BackupHealthRead` because the two fail independently: a local
 *  backup can succeed every night while the upload has been failing for a
 *  month, and only the second means the archive exists nowhere but the card
 *  it is protecting against. */
export interface BackupUploadStatus {
  configured: boolean;
  provider: string | null;
  destination: string | null;
  /** Set from `HEADROOM_BACKUP_UPLOAD_CMD`. That wins over anything set here
   *  and is read-only in the UI: it is settable only with host access, which
   *  is a privilege boundary the browser must not cross. */
  from_environment: boolean;
  available_providers: BackupUploadProvider[];
  /** Whether the CONFIGURED provider's binary exists in the container. None of
   *  them are guaranteed to be, and a missing one fails every unattended
   *  upload while the card would otherwise still read "configured". */
  binary_available: boolean | null;
  /** Survives a restart (persisted beside the backups), so null here means
   *  genuinely never uploaded — not merely "not since the last restart". */
  last_upload_at: string | null;
  last_upload_ok: boolean | null;
  last_upload_error: string | null;
  /** The archive the last attempt shipped. */
  last_upload_name: string | null;
  upload_successes: number;
  upload_failures: number;
}

/** A set of hats that look like the same hat entered more than once. */
export interface DuplicateGroupRead {
  key: string;
  /** "exact" — every identity field agrees. "likely" — same model and size,
   *  with the colorway missing on at least one side (usually an unanalyzed
   *  twin). Colorways that actively disagree are never grouped. */
  confidence: 'exact' | 'likely';
  label: string;
  hats: SearchResult[];
}

/** One construction value on record, and what depends on it. */
export interface ConstructionAuditRow {
  construction: string;
  hat_count: number;
  /** Hats priced from the table — i.e. derived from this construction. */
  priced_from_table: number;
}

/** What clearing a construction did, or would do under `dry_run`. */
export interface ConstructionClearResult {
  construction: string;
  /** What the matched hats become. Null clears the field. */
  to: string | null;
  dry_run: boolean;
  /** Left alone because the audit log proves the owner typed the value. */
  owner_set_skipped: number;
  hats_cleared: number;
  model_names_corrected: number;
  prices_cleared: number;
  manual_prices_kept: number;
  samples: string[];
}

// ---- Purchase history ---------------------------------------------- //

export interface PurchaseRead {
  id: number;
  order_ref: string | null;
  order_date: string | null;
  item_title: string;
  model_name: string | null;
  colorway: string | null;
  size: string | null;
  price: number | null;
  quantity: number | null;
  hat_id: number | null;
  source: string | null;
}

export interface UnmatchOneResult {
  unmatched: number;
  hat_id: number | null;
  cleared: string[];
}

/**
 * One proposed purchase → hat link, from the matcher or the import preview.
 *
 * The matcher names the purchase row (`purchase_id`); the preview scores rows
 * that are not stored yet, so it has no id and says instead which half of the
 * click each row is (`already_on_record`: the backlog, not the new file).
 */
export interface MatchProposal {
  purchase_id: number | null;
  item_title: string;
  order_ref: string | null;
  price: number | null;
  size: string | null;
  hat_id: number;
  hat_display_id: string | null;
  score: number;
  /** Which fields agreed — "model", "colorway", "size"… */
  matched_on: string[];
  /** Tied between equally good hats; `tied_hat_ids` names the others. */
  ambiguous: boolean;
  tied_hat_ids: number[];
  sets_price: boolean;
  sets_colorway: boolean;
  already_on_record: boolean | null;
}

/** What importing WOULD do. Nothing is written to produce this. */
export interface ImportPreview {
  /** Always true here — the preview is the dry run. */
  dry_run: boolean;
  would_import: number;
  duplicates: number;
  unusable: number;
  likely_accessories: number;
  /** Matches among the lines in the file — what the operator is choosing. */
  would_match: number;
  would_not_match: number;
  /** Purchases ALREADY on record that the same click would also match.
   *  Importing re-runs matching over everything unmatched, so this is the
   *  part nobody asked for and the part that writes prices onto hats. */
  would_match_backlog: number;
  /** What the import will report afterwards: the file's lines plus the
   *  backlog. The number the preview is accountable for. */
  would_match_total: number;
  ambiguous: number;
  /** The links the import would make, row by row. */
  proposals: MatchProposal[];
}

/** The write path of the purchase import: rows imported, then the matching
 *  run that follows — the response that reports prices written onto hats. */
export interface ImportResult {
  imported: number;
  skipped: number;
  matched: number;
  unmatched: number;
  /** Matches that were a tie between equally good hats. */
  ambiguous: number;
}

/** What matching linked, or would link under `dry_run`. */
export interface MatchResult {
  dry_run: boolean;
  matched: number;
  unmatched: number;
  ambiguous: number;
  proposals: MatchProposal[];
}

export interface UnmatchAllResult {
  unmatched: number;
  fields_cleared: number;
}

/** One hat whose price analysis can no longer touch. */
export interface FrozenPriceRow {
  hat_id: number;
  display_id: string | null;
  model_name: string | null;
  resale_price: number | null;
  estimated_new_price: number | null;
  /** Carries marketplace provenance under a manual stamp — the bug's signature. */
  was_market_priced: boolean;
}

export interface PriceReleaseResult {
  dry_run: boolean;
  released: number;
  hats: FrozenPriceRow[];
}

/** One distinct analysis failure and how many hats it hit. */
export interface AnalysisFailureGroup {
  reason: string;
  hat_count: number;
  /** How many of those a retry can actually re-queue — the number the Retry
   *  button is labeled with. Lower than `hat_count` when a hat here has no
   *  photo left to analyze, which is its own failure and cannot be retried. */
  retryable_count: number;
  /** Why the rest cannot be retried: no photo on disk, or no Claude key yet
   *  (the card's one "Add a key" nudge). Null when every hat is retryable. */
  unretryable_reason: 'no_photo' | 'no_api_key' | null;
  sample_hat_ids: number[];
  last_seen: string | null;
  /** Anthropic billing/quota — the failure that looks like a missing key. */
  is_billing: boolean;
}

/** One hat's outcome inside a run — a row in that run's log. */
export interface AnalysisJobHat {
  id: number;
  display_id: string | null;
  label: string | null;
  photo_path: string | null;
  analysis_status: 'pending' | 'ok' | 'fallback' | 'skipped' | 'error' | null;
  /** Verbatim and untruncated. The failures CARD groups on a cleaned key so
   *  one problem reads as one; here the whole string is the point. */
  analysis_error: string | null;
  analyzed_at: string | null;
}

/** A run plus what happened to each hat in it.
 *
 *  `still_tagged` matters: `hats.analysis_job_id` is one column that every
 *  later run overwrites, so an older run's hats drain away as newer runs claim
 *  them. Without it an old run renders an empty list and reads as a run that
 *  did nothing. */
export interface AnalysisJobDetail extends AnalysisJobRead {
  still_tagged: number;
  failed_count: number;
  hats: AnalysisJobHat[];
}

/** What a re-analysis run queued. Shared by the whole-collection run and the
 *  retry-failed run, which differ only in which hats go in. */
export interface ReanalyzeAllResult {
  queued: number;
  worker_alive: boolean;
  job: AnalysisJobRead | null;
}

/** Answer to "re-price everything": did a sweep start, or was one running?
 *  Two booleans because "not started" has two meanings, and a sweep already in
 *  flight is the normal case when someone presses twice — not a failure. */
export interface RepricingSweepStarted {
  started: boolean;
  already_running: boolean;
}

/** What re-running matching would fill in from orders already imported.
 *  Matching runs at the end of an import and nowhere else, so a better matcher
 *  — or a re-analysis that finally gives a hat a model_name — creates pairs
 *  nothing ever looks at again. */
export interface UnclaimedFromPurchases {
  /** Hats that would gain a colorway. */
  colorways: number;
  /** Hats that would gain a purchase price. Applying does both. */
  prices: number;
  /** How many colorway fills the matcher flagged as tied between equal
   *  candidates — still better than a line median, but worth knowing. */
  ambiguous: number;
}

/** One hat inside a shared-price group. One object rather than parallel
 *  id/label arrays: a hat with no case has no `display_id`, so the two fell
 *  out of step and a label was drawn on the wrong hat's link. */
export interface SharedPriceHat {
  hat_id: number;
  display_id: string | null;
  /** False is the actionable state — no colorway means no product can be
   *  named, and the owner is the only source for it. */
  has_colorway: boolean;
}

/** One resale price and every hat carrying it.
 *  A figure shared by dozens of hats is the going rate for a LINE, not an
 *  appraisal of any one of them — and nothing in the app said so. */
export interface SharedPriceGroup {
  resale_price: number;
  /** A representative sentence, verbatim. Members are grouped on a cleaned
   *  form that neutralizes the live listing count, so another member may
   *  quote a different count. */
  source: string | null;
  hat_count: number;
  /** Hats missing a colorway come first — the truncated sample the card shows
   *  should be the rows worth opening. */
  hats: SharedPriceHat[];
  /** How many carry no colorway — the actionable half, and the one thing only
   *  the owner can supply. */
  missing_colorway: number;
}

/** Live state of a long in-process sweep (re-pricing, colorway harvest).
 *  `pct` is computed server-side so the cards that render it cannot disagree
 *  about how it rounds. */
export interface SweepProgressRead {
  running: boolean;
  done: number;
  total: number;
  /** What it is working on this instant — a count says it is alive, this says
   *  it is not wedged on one item. */
  label: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** Survives `running` going false; nobody is watching when it fails. */
  error: string | null;
  pct: number;
}

/** The colorway catalog's real size, plus any harvest in flight.
 *  The refresh returns 202 and runs in the background, so `progress` is the
 *  only way to tell a running harvest from a button that did nothing. */
export interface CatalogStatus {
  entries: number;
  models: number;
  colorways: number;
  last_harvest: string | null;
  progress: SweepProgressRead;
  /** Claimed OR running. Not the same as `progress.running`: the slot is taken
   *  synchronously in the request while `begin()` happens inside the task, so
   *  `running` is briefly false on a harvest that is definitely queued. */
  in_flight: boolean;
  /** Categories the last harvest could not read. Empty is good news only when
   *  `entries` is not zero — a harvest that lost every category used to report
   *  success with nothing to show for it. */
  failed_categories: string[];
}

/** Periodic re-pricing: is the sweep alive, and what did it last manage?
 *  Process-local by design — the durable answer is `resale_checked_at` on each
 *  hat, so how stale prices are is readable from the hats themselves. */
export interface RepricingStatus {
  enabled: boolean;
  interval_hours: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  /** Hats the last sweep could not consult the marketplace about — the
   *  difference between a flat market and a dead one. Non-zero alongside a
   *  success is a partial outage. */
  last_unreachable: number;
  /** Hats whose price CHANGED, not hats visited. A flat market is a working
   *  sweep, and reporting the visit count would hide a sweep that writes nothing. */
  last_repriced: number;
  last_considered: number;
  /** The sweep in flight, if any. Distinct from the fields above, which
   *  describe the last one that FINISHED. */
  progress: SweepProgressRead;
}

/** `POST /api/admin/repricing/run` — one bounded batch, done while you wait. */
export interface RepricingRunResult {
  repriced: number;
  considered: number;
  /** Still DUE after this batch — press again to continue. */
  remaining: number;
}

/** 202 body for the colorway harvest. `started` false with `already_running`
 *  is a refusal, not a start: another harvest holds the slot. */
export interface CatalogRefreshStarted {
  started: boolean;
  already_running: boolean;
  detail: string;
}

// ---- Settings and admin results ------------------------------------- //

/** `POST /api/admin/ebay/test`. `stage` says how far the check got (OAuth,
 *  then Browse), which is what tells a bad keyset from a bad marketplace. */
export interface EbayTestResult {
  ok: boolean;
  stage: string;
  detail: string;
}

/** `POST /api/admin/backups/upload/test`. */
export interface BackupUploadTestResult {
  ok: boolean;
  detail: string;
}

export interface GuestViewStatus {
  enabled: boolean;
}

/** A bare count — `GET /api/admin/recent-errors/count`. */
export interface CountRead {
  count: number;
}

// ---- Auth --------------------------------------------------------------- //

export interface AuthStatus {
  needs_setup: boolean;
  authenticated: boolean;
  username: string | null;
  /** Whether to offer "browse as a guest" on the login screen. Rides along on
   *  the one unauthenticated call the page already makes; null or absent on
   *  the responses that do not carry it. */
  guest_view_enabled?: boolean | null;
}

/** Profile only. The bearer token needs the password — see `ApiTokenRead`. */
export interface MeRead {
  username: string;
  token_set: boolean;
}

/** The long-lived bearer token, answered only on proof of the password. */
export interface ApiTokenRead {
  api_token: string;
}

export interface OkRead {
  ok: boolean;
}

export interface PasskeyRead {
  id: number;
  name: string;
  created_at: string;
}

/**
 * The first half of a passkey ceremony: a state id to hand back, and the
 * options py_webauthn serialized for the browser. The schema types `options`
 * as an object; the two JSON shapes below are what it holds for each
 * ceremony, as `lib/webauthn` reads them.
 */
export interface PasskeyCeremonyOptions<O = Record<string, unknown>> {
  state_id: string;
  options: O;
}

/** A credential descriptor as py_webauthn serializes it: the id is base64url.
 *  Client-side shape (inside `PasskeyCeremonyOptions.options`), no schema of
 *  its own. */
export interface CredentialDescriptorJSON {
  id: string;
  type: PublicKeyCredentialType;
  transports?: AuthenticatorTransport[];
}

/** `PublicKeyCredentialCreationOptions` with every binary field as base64url. */
export interface CredentialCreationOptionsJSON
  extends Omit<PublicKeyCredentialCreationOptions, 'challenge' | 'user' | 'excludeCredentials'> {
  challenge: string;
  user: Omit<PublicKeyCredentialUserEntity, 'id'> & { id: string };
  excludeCredentials?: CredentialDescriptorJSON[];
}

/** `PublicKeyCredentialRequestOptions` with every binary field as base64url. */
export interface CredentialRequestOptionsJSON
  extends Omit<PublicKeyCredentialRequestOptions, 'challenge' | 'allowCredentials'> {
  challenge: string;
  allowCredentials?: CredentialDescriptorJSON[];
}

/** A new passkey as the register-verify endpoint reads it (binary as base64url). */
export interface RegistrationCredentialJSON {
  id: string;
  rawId: string;
  type: string;
  response: { clientDataJSON: string; attestationObject: string };
  clientExtensionResults: AuthenticationExtensionsClientOutputs;
}

/** A passkey assertion as the login-verify endpoint reads it. */
export interface AuthenticationCredentialJSON {
  id: string;
  rawId: string;
  type: string;
  response: {
    clientDataJSON: string;
    authenticatorData: string;
    signature: string;
    userHandle: string | null;
  };
  clientExtensionResults: AuthenticationExtensionsClientOutputs;
}

// ---- Share links -------------------------------------------------------- //

export interface ShareLinkRead {
  id: number;
  token: string;
  label: string;
  url_path: string;
  created_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

/** `POST /api/share-links` — the new link; the list refetch fills the rest. */
export interface ShareLinkCreated {
  id: number;
  token: string;
  url_path: string;
}
