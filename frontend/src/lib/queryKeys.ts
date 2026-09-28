/**
 * Every TanStack Query key the app uses, defined once.
 *
 * Keys were string-literal arrays retyped at each site — `['admin',
 * 'shared-prices']` six times, `['meta', 'rooms']` seven — and a typo'd copy
 * does not fail: it silently becomes a second cache entry that nothing
 * invalidates. The sibling-key traps this app keeps meeting (`['room']` is
 * not under `['rooms']`, `recent-errors-count` is not under `recent-errors`)
 * came from exactly that: two keys that look related and are not, with
 * nothing putting them side by side. Here they sit next to each other, and a
 * key that has a sibling says so.
 *
 * TanStack matches a key by PREFIX, so the zero-argument forms below double as
 * "every entry of this kind": `qk.hat()` invalidates every cached hat page,
 * `qk.search.all()` every search. Each factory returns a fresh readonly tuple.
 */
export const qk = {
  // ---- Hats and where they live --------------------------------------- //

  /** The active collection (`listAllHats`). Prefix of `hatsDisposed`. */
  hats: () => ['hats'] as const,
  /** Hats that have left the collection — under `hats()`, so a hat change
   *  that invalidates the collection refreshes this list too. */
  hatsDisposed: () => ['hats', 'disposed'] as const,
  /** One hat's page; with no id, the prefix over every cached hat page. */
  hat: (id?: number) => (id === undefined ? ['hat'] as const : ['hat', id] as const),
  cases: () => ['cases'] as const,
  /** One case's page; with no id, every cached case page. */
  case: (displayId?: string) =>
    (displayId === undefined ? ['case'] as const : ['case', displayId] as const),
  /** Every room with its counts. NOT a prefix of `room()`: "rooms" does not
   *  start with "room" as a key segment — invalidate both. */
  rooms: () => ['rooms'] as const,
  room: (id?: number) => (id === undefined ? ['room'] as const : ['room', id] as const),
  /** Text and color searches; `all()` is the prefix over both. */
  search: {
    all: () => ['search'] as const,
    text: (term: string, exactColors: boolean, roomId: number | null, scope: string) =>
      ['search', 'text', term, exactColors, roomId, scope] as const,
    color: (hex: string | null, roomId: number | null) =>
      ['search', 'color', hex, roomId] as const,
  },
  duplicates: () => ['duplicates'] as const,

  // ---- Unauthenticated views ----------------------------------------- //

  /** What a guest sees; `all()` is the prefix over the list and each hat. */
  guest: {
    all: () => ['guest'] as const,
    collection: (query: string, scope: string) => ['guest', 'collection', query, scope] as const,
    hat: (id: number) => ['guest', 'hat', id] as const,
  },
  publicShare: (token?: string) =>
    (token === undefined ? ['public-share'] as const : ['public-share', token] as const),

  // ---- Option lists (`/api/meta/*`) ---------------------------------- //

  meta: {
    styles: () => ['meta', 'styles'] as const,
    sizes: () => ['meta', 'sizes'] as const,
    conditions: () => ['meta', 'conditions'] as const,
    /** Room dropdown options — NOT `rooms()`: a room mutation invalidates both. */
    rooms: () => ['meta', 'rooms'] as const,
    constructions: () => ['meta', 'constructions'] as const,
    collections: () => ['meta', 'collections'] as const,
    colors: () => ['meta', 'colors'] as const,
    /** The colorway catalog; the prefix over the model list and each model's
     *  colorways. The per-model key carries an object so no model name can
     *  collide with the `'models'` segment. */
    colorways: () => ['meta', 'colorways'] as const,
    colorwayModels: () => ['meta', 'colorways', 'models'] as const,
    colorwaysFor: (model: string) => ['meta', 'colorways', { model }] as const,
  },

  // ---- Settings -------------------------------------------------------- //

  settings: {
    apiKey: () => ['settings', 'api-key'] as const,
    googleVisionKey: () => ['settings', 'google-vision-key'] as const,
    model: () => ['settings', 'model'] as const,
    logo: () => ['settings', 'logo'] as const,
    tags: () => ['settings', 'tags'] as const,
    mdns: () => ['settings', 'mdns'] as const,
    tls: () => ['settings', 'tls'] as const,
    guestView: () => ['settings', 'guest-view'] as const,
  },
  caCertificateAvailable: () => ['ca-certificate', 'available'] as const,
  shareLinks: () => ['share-links'] as const,

  // ---- Auth ------------------------------------------------------------ //

  auth: {
    /** Read by the login screen (setup state, the guest-browsing link). */
    status: () => ['auth', 'status'] as const,
    me: () => ['auth', 'me'] as const,
    passkeys: () => ['auth', 'passkeys'] as const,
  },

  // ---- Admin ----------------------------------------------------------- //

  admin: {
    /** The newest failed analyses. SIBLING of `recentErrorsCount` — not a
     *  prefix of it — so a refresh must name both (`invalidateAnalysisViews`). */
    recentErrors: () => ['admin', 'recent-errors'] as const,
    /** The nav badge's count, polled by both navs. */
    recentErrorsCount: () => ['admin', 'recent-errors-count'] as const,
    analysisQueue: () => ['admin', 'analysis-queue'] as const,
    analysisFailures: () => ['admin', 'analysis-failures'] as const,
    /** One run's log; with no id, every open one. */
    analysisJob: (id?: number) =>
      (id === undefined ? ['admin', 'analysis-job'] as const : ['admin', 'analysis-job', id] as const),
    activity: () => ['admin', 'activity'] as const,
    retention: () => ['admin', 'retention'] as const,
    ebay: () => ['admin', 'ebay'] as const,
    repricing: () => ['admin', 'repricing'] as const,
    sharedPrices: () => ['admin', 'shared-prices'] as const,
    unclaimedPurchases: () => ['admin', 'unclaimed-purchases'] as const,
    purchases: () => ['admin', 'purchases'] as const,
    frozenPrices: () => ['admin', 'frozen-prices'] as const,
    constructionAudit: () => ['admin', 'construction-audit'] as const,
    colorwayStatus: () => ['admin', 'colorway-status'] as const,
    backups: () => ['admin', 'backups'] as const,
    backupHealth: () => ['admin', 'backup-health'] as const,
    backupUpload: () => ['admin', 'backup-upload'] as const,
    /** Recent bulk imports. SIBLING of `importJob` — invalidate both. */
    importJobs: () => ['admin', 'import-jobs'] as const,
    importJob: (id: number | null) => ['admin', 'import-job', id] as const,
  },
} as const;

/** Mutation keys — a different namespace from query keys in TanStack. */
export const mk = {
  /** Every write to the Claude model, so each can see another queued behind it. */
  modelWrite: () => ['settings-model-write'] as const,
} as const;
