# Changelog

All notable changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.49.0] — 2026-08-23

The LAN HTTPS front door can answer on more than the `.local` name, so the app
is reachable over a VPN instead of looking like it is down.

### Fixed
- **Over Teleport the app was unreachable in a way that read as an outage, and
  the server was fine the whole time.** Three separate causes stacked up, each
  of which alone is enough to break it:

  1. **`headroom.local` is mDNS, and mDNS is link-local multicast.** It cannot
     cross a VPN, a tunnel, or a routed subnet. Over Teleport the name simply
     does not resolve, and there is nothing to fix in DNS because no DNS is
     involved — no server holds that record, and no forwarder can be pointed at
     one.
  2. **Connecting by IP failed the TLS handshake outright.** Caddy rejects a
     connection whose SNI matches no configured site, and only
     `headroom.local` was configured. The measurement that separates the two:
     `curl --resolve headroom.local:443:10.0.111.4 https://headroom.local/`
     returns **HTTP 200**, while `curl https://10.0.111.4/` returns **HTTP
     000** — no response at all — even with `-k`. The IP was always routable;
     it just was not a site.
  3. **Even had it matched, the certificate would not have.** It carries
     `DNS:headroom.local` and no IP SAN, so the name check fails. `-k` hides
     that one and nothing else.

  What turned this from "does not work" into "the server is down" is Caddy's
  automatic HTTP→HTTPS redirect: `http://10.0.111.4/` answers with a **308 to
  `https://10.0.111.4/`**, which is precisely the address that cannot complete
  a handshake. The one URL a person tries when HTTPS is failing hands them back
  the URL that fails.

  The site address list is now **configurable** —
  `HEADROOM_SITE_ADDRESSES`, comma-separated — and defaults to
  `{HEADROOM_MDNS_HOSTNAME}.local`, so existing installs are byte-identical to
  what they served before. Adding the LAN IP (or a Tailscale/WireGuard name)
  makes Caddy serve it *and* puts it in the certificate as an IP SAN signed by
  **the same root**, so devices that already trust the CA trust the new address
  with no reinstall and no second profile:

  ```bash
  HEADROOM_SITE_ADDRESSES="headroom.local, 10.0.111.4" \
    docker compose -f docker-compose.yml -f docker-compose.https-lan.yml up -d
  ```

  **Passkeys still only work on the origin in `HEADROOM_ORIGIN`.** WebAuthn
  credentials are bound to an origin, so one registered at
  `https://headroom.local` is not offered at `https://10.0.111.4`. That is
  WebAuthn working correctly, not a misconfiguration, and it is not something
  a certificate can fix. Password login works on both.

  **There is also a zero-config remote path that needed none of this:**
  `http://<ip>:8000` reaches uvicorn directly, bypassing Caddy entirely — SPA,
  assets and API all answer 200 over the VPN today. It is plain HTTP, so it is
  not a secure context and passkeys are unavailable there either; it is the
  fallback worth knowing about when the front door is the thing being
  diagnosed.

### Added
- `HEADROOM_SITE_ADDRESSES` documented in the operations environment table and
  in the README's HTTPS section, with a troubleshooting entry for the exact
  presentation — *works on the LAN, dead over the VPN* — since the symptom
  points at the server and the cause is name resolution.
- A test asserting the Caddyfile's site line is env-driven and still defaults
  to a `.local` name. It sits beside the lifetime tests and reads the Caddyfile
  for the same reason they do: a constant in this repo would agree with itself
  while the deployed configuration said something else.

## [2.48.0] — 2026-08-24

The LAN HTTPS certificate now lasts 820 days instead of twelve hours.

### Fixed
- **`https://headroom.local` served a certificate that had expired 37 days
  earlier, and Caddy spent every one of those days trying to fix it.** Caddy's
  internal CA issues **twelve-hour** leaf certificates by default. Twelve hours
  is a good default *if renewal always works* — a short-lived certificate
  limits the blast radius of a stolen key and needs no attention. Here renewal
  stopped: an unclean shutdown destroyed Caddy's stored leaf private key, and
  with no key to sign against, the renewal it queued every ten minutes could
  never complete. It re-queued that renewal for five weeks while continuing to
  serve the dead certificate.

  Leaf certificates are now issued for **820 days**. A certificate that
  outlives the gap between something breaking and somebody noticing is worth
  more on a LAN than a short blast radius, and 2.46's `tls_health` check exists
  precisely because nothing here notices quickly.

  **820 is a ceiling, not a preference.** Safari — and therefore every iPhone
  in the house — rejects a TLS server certificate whose validity exceeds
  **825 days**, even when it chains to a manually installed root. The
  widely-quoted 398-day cap is a different rule that applies only to Apple's
  *preinstalled* roots; user-added roots get 825, verified by binary search
  (825 accepted, 826 rejected). Chrome and Firefox impose no limit here at all,
  which is exactly the trap: "make it ten years" produces a setup that works on
  the laptop you test it from and fails on every phone, with a certificate
  error that reads like a broken trust store rather than a lifetime. 820 leaves
  headroom for clock skew.

  **The root is untouched and still lasts ten years**, so nothing needs
  reinstalling. Raising `intermediate_lifetime` regenerates the *intermediate*,
  which is presented during the handshake; the root is the self-signed trust
  anchor sitting in each device's keychain, and it is not reissued. Devices
  that already trust this CA keep trusting it.

  **This does not repair a device that currently refuses to trust the CA.**
  That is a separate problem — the root was never installed, iOS's Certificate
  Trust Settings toggle is off, or the device holds an *older* Caddy root
  (they all carry the same name, which is why Settings → Trust this device
  publishes the fingerprint). Deploying this release changes what is served,
  not what is trusted.

### Changed
- **The Caddy sidecar runs from a `Caddyfile` instead of `caddy
  reverse-proxy`.** The CLI form cannot express PKI options at all, so the
  twelve-hour default was not something the old configuration could have
  overridden — the file is the only way to say it. New `./Caddyfile`, bind
  mounted read-only, setting `pki { ca local { intermediate_lifetime 3000d } }`
  and `tls { issuer internal { lifetime 820d } }`. Caddy requires the issued
  lifetime to sit under `renewal_window_ratio` (default 1/3) × the
  intermediate's, so an 820-day leaf needs an intermediate of at least ~2460
  days; 3000d clears that and still sits below the 3600d root.

  `docker-compose.https.yml` — the internet-facing overlay — deliberately keeps
  the CLI form. Its certificates come from Let's Encrypt, which sets its own
  90-day lifetime and renews over the public internet, so there is nothing for
  this repo to choose there.

- **`tls_health.RENEWAL_GRACE_DAYS` 2 → 30.** Two days was generous against a
  twelve-hour certificate. Against an 820-day one it is a fire alarm that rings
  as the roof falls in. Thirty days is enough notice to act without becoming
  background noise, and a certificate inside thirty days of expiry still means
  renewal has stopped rather than that expiry is merely approaching.

- The **Trust this device** card and the README's HTTPS troubleshooting both
  said the certificate "lives twelve hours", and the card's warning read
  *expires within hours* — copy that was accurate at the old lifetime and off
  by a month at the new one. The card now names the real number of days
  remaining, and says *ran out* versus *runs out* correctly rather than using
  the past tense for a certificate that has not expired yet.

### Added
- Two tests guarding the ceiling, because the failure mode is invisible on the
  machine you would test it from. One fails if the Caddyfile's leaf lifetime
  reaches 825 days; the other checks Caddy's own constraint — issued lifetime
  under 1/3 of the intermediate, intermediate under the 3600d root — which
  otherwise surfaces as a sidecar that refuses to start after a deploy.

## [2.47.0] — 2026-08-23

Build speed. Nothing about the running app changed.

### Changed
- **A release rebuild on the Pi took 873s, and 490s of it was reinstalling
  dependencies that had not changed.** Cutting a release edits the `version`
  field in `pyproject.toml` — and `pyproject.toml` was the file gating the
  dependency layer. So `COPY pyproject.toml` busted on every release, `uv sync`
  re-ran (237s), and the rembg model layer sitting downstream of it fell with
  it (149s). The uv cache mount meant nothing was re-*downloaded*; uv still
  unpacked and bytecode-compiled thousands of files onto an SD card, every
  release, for a string that has nothing to do with dependencies.

  Dependencies now install from `requirements.txt`, generated by
  `uv export --frozen --no-dev --no-emit-project --format requirements-txt`.
  `--no-emit-project` leaves the project — and therefore its version — out, so
  the file is byte-identical across a version bump and the layer survives one.
  `--require-hashes` keeps the supply-chain guarantee `--frozen` gave here:
  every artifact must match the digest recorded in `uv.lock`, so a compromised
  mirror cannot substitute one.

  The version-bearing `COPY pyproject.toml uv.lock*` moved to **after** the
  dependency install. It is still `uv sync --frozen` with no fallback, and it
  still busts on every release — but installing the project alone against a
  venv that already satisfies the lock costs 6.5s.

  `npm ci` also gained `--no-audit --no-fund`, two registry round trips whose
  output nobody reads during a deploy. Deliberately **not** `--ignore-scripts`:
  rolldown and esbuild fetch their platform binary in a postinstall, so
  skipping scripts produces a build that fails later and further away.

  Measured A/B on the Pi this deploys to:

  | Step | Before | After |
  |---|---|---|
  | `uv sync` (dependencies) | 237s | **cached** |
  | rembg model layer | 149s | **cached** |
  | `npm ci` | 104s | 53s |
  | image export | 276s | 259s |
  | **Total** | **873s** | **531s** |

  A 39% reduction, with cached steps going from 7 to 10. The export line is
  unchanged because it is SD-card write throughput, not work this can remove.

  **The first build after upgrading is slower — measured at 1106s.** The layer
  shape changed, so its cache is cold and everything rebuilds once. Every
  build after that is the 531s.

### Added
- `tests/test_requirements_export.py`, because the two ways this silently
  reverts both leave a green build. The price of the speed is a second file
  describing the same dependency set: a bump can land in `uv.lock` without
  `requirements.txt` being regenerated, and the image then quietly installs the
  **old** set while every test passes against the new one. The other is anyone
  moving `COPY pyproject.toml` back above the dependency install, which brings
  the 490s straight back and says nothing. Four tests pin both, plus the
  hash-pinning and the project's absence from the export.

## [2.46.0] — 2026-08-23

### Added
- **The app now watches its own HTTPS certificate.** `GET /api/settings/tls`
  opens a TLS connection to the app's own origin and reports what is actually
  being **served** — expiry, days remaining, whether the certificate covers the
  name it is served under, and the SHA-256 of the CA this install hands out.
  Surfaced in **Settings → This device → Trust this device**.

  Written because the real deployment served a certificate that had expired
  **37 days earlier** and nothing noticed. Caddy's stored leaf key had vanished,
  so its renewal queued every ten minutes and never completed. The container was
  healthy, the app answered, backups ran — every signal was green, because
  nothing here had ever looked at the certificate in front of it.

  It measures the served chain rather than reading Caddy's storage, because
  those disagree: that failure had a valid certificate **on disk** and an
  expired one in Caddy's memory, so a file check would have reported everything
  fine while browsers refused the connection.

  It is reported, never enforced. The certificate belongs to Caddy, so failing
  readiness on it would restart-loop the app without fixing anything.

- **The CA fingerprint is published**, because a name is not an identity.
  Caddy names every root `Caddy Local Authority - <year> ECC Root`, so two
  installs produce two **different** roots with the **same** name. A browser
  matching by name picks whichever it has and reports *"Peer's certificate has
  an invalid signature"* on a chain that verifies perfectly at the server —
  and nothing in the name, dates or issuer separates them. The card now shows
  the fingerprint and the command to list what a Mac actually trusts.

- **Off-site backups to rsync and Synology.** Three providers now, each a single
  frozen record driving the argv, the validation, the UI copy and the preflight
  check — so adding a transport is one entry rather than four edits that can
  disagree.

  | Provider | Destination | Needs |
  |---|---|---|
  | Cloud storage (rclone) | `box:Headroom-Backups` | `rclone config` + the rclone overlay |
  | rsync over SSH | `pi@nas.local:/volume1/backups/headroom` | an SSH key + the rsync overlay |
  | Synology NAS (rsync service) | `backup@nas.local::NetBackup/headroom` | DSM's rsync service + `HEADROOM_BACKUP_RSYNC_PASSWORD` |

  The two rsync destinations differ by **one colon, and that is the whole
  transport**: `host:/path` is rsync over SSH, `host::module/path` connects
  straight to a daemon on port 873 and reads the first segment as a module
  name. Validation is per provider so a typo cannot silently switch transport
  and fail with credentials nobody configured, looking like a broken NAS.

  `rsync` and `openssh-client` now ship **in the image** (~3 MB). rclone is
  ~50 MB and stays a bind mount. Requiring an overlay whose only job was to
  supply a binary the image could have carried made the two most ordinary
  destinations — another Linux box, a NAS — needlessly hard.

- **The off-site backup card explains how to finish setting up.** Each provider
  carries its host-side steps, its destination shape, an example, and whether
  its binary is actually present in the container. "Configured" and "working"
  are different states and everything between them is host-side work the card
  previously could not name. **Test now** also says outright when the binary is
  missing, instead of surfacing a subprocess's "No such file or directory" —
  a true statement about `argv[0]` that reads as a problem with the destination.

### Fixed
- **The macOS trust instructions**, which stopped at "double-click the file".
  That lands it in whichever keychain Keychain Access last had selected; the
  **iCloud** keychain cannot hold certificates and rejects the import with
  `Error: -26276`, which reads like a bad file rather than a wrong destination.
  Both the card and the README now lead with `security add-trusted-cert`, and
  note that a browser's own export button always hands you the leaf or the
  intermediate and **never** the root — a root is self-signed and never sent
  during a handshake, so it can only come from the server.

## [2.45.0] — 2026-08-23

### Fixed
- **`GET /api/public/ca-certificate` returned 404 on every install that ever
  ran the LAN-HTTPS overlay.** The endpoint exists so a phone can trust
  `https://headroom.local` by opening a URL; instead it reported "No local CA
  certificate on this install. It exists only when running
  docker-compose.https-lan.yml" to operators who were looking directly at
  Caddy serving certificates.

  The route read Caddy's PKI in place. Caddy creates that tree `0700 root`,
  and this app's container runs as a non-root user by policy, so the traversal
  failed — and `Path.is_file()` reports a permission failure as plain `False`,
  which made **"mounted but unreadable" indistinguishable from "not
  installed"** and sent the endpoint's own error message to the wrong
  conclusion. It had never worked, on any release, on any deployment.

  The overlay now runs a `caddy-ca-export` sidecar that copies the public root
  out to its own volume, world-readable, and the app mounts *that* instead of
  the PKI. Copying one file rather than loosening permissions also means the
  app container has no key material in view at all — a stronger guarantee than
  the route's hardcoded filename, since there is now nothing else in the mount
  to serve by mistake. It polls rather than copying once: Caddy mints the CA a
  moment after startup on a first boot and rotates its intermediate
  periodically after that.

  `_unavailable_detail()` now tells the two failures apart, so a still-broken
  install is told what is actually wrong instead of being sent to check an
  overlay that is demonstrably already running.

  **Upgrading:** recreate the stack (`docker compose -f docker-compose.yml -f
  docker-compose.https-lan.yml up -d --build`) to pick up the new service.
  Until you do, the endpoint keeps 404ing — with an accurate message now.

- **README's macOS trust step.** It said to double-click the certificate,
  which lands it in whichever keychain Keychain Access last had selected. The
  **iCloud** keychain cannot hold certificates and refuses with
  `Error: -26276` — an error that reads like a bad file rather than a wrong
  destination. The step now leads with `security add-trusted-cert`, which
  imports and trusts in one command and cannot guess wrong, and the
  troubleshooting list covers both `-26276` and the 404 above.

### Changed
- **The home carousel shows two hats side by side on a desktop**, one on a
  phone. The breakpoint is 992px — the width this app already treats as
  desktop, since it is where the top nav replaces the bottom nav — so it is
  not a new number to keep in step.

  The count is decided in JavaScript (`lib/useMediaQuery.ts`) rather than by
  hiding a second slide in CSS, so a phone never downloads a photo it will not
  display. `useSyncExternalStore` rather than `useState` + an effect: the
  effect version renders one frame at the wrong size and visibly pops from one
  hat to two on every mount.

  Two details that are easy to get wrong and are pinned by tests: the visible
  count is clamped to the number of hats that actually have photos, because a
  one-photo collection rendering the same hat in both panes reads as a bug
  rather than a layout; and the arrows now hide when everything is already on
  screen, since stepping by a screenful through a two-hat list lands back
  where it started.

## [2.44.0] — 2026-08-23

### Added
- **An off-site backup card in Settings.** The feature has existed since 2.38
  and was configurable only by editing `.env` and restarting, with no way to
  learn whether it had ever actually run short of reading container logs. That
  is the wrong shape for the one thing standing between a dead SD card and
  losing the collection.

  The card answers three questions: is a copy configured, did the last one
  work, and does it work *right now* — the last via a **Test now** button that
  performs the real upload against your newest backup. Same command, same
  credentials. A dry run would only prove the form had been filled in.

  **The form does not accept a command, deliberately.** The hook runs an argv
  unattended, as the app user, after every backup, so a free-text command
  field would turn a stolen session into command execution inside the
  container. The browser sends a provider name and a destination; the argv is
  assembled from a template the server owns, and the destination must match
  `remote:path` — a leading `-` is rejected by name, because `--config=…` is
  flag injection wearing an argument's clothes.

  `HEADROOM_BACKUP_UPLOAD_CMD` still works and now **wins** over anything set
  in the UI, which is the opposite precedence to the API keys. That variable
  is settable only with host access; letting a browser override a host-level
  decision about what executes would erase the boundary that makes the raw
  command form acceptable at all. When it is set, the card goes read-only and
  says so.

- **Upload outcomes are recorded** — last attempt, whether it succeeded, the
  error, and running success/failure counts — separately from the backup's own
  health. The two fail independently: a local backup can succeed every night
  while the off-box copy has been failing for a month, and only the second
  means the archive exists nowhere but the card it is protecting against.

## [2.43.0] — 2026-08-23

A test-coverage audit, and the bug it found.

### Fixed
- **Bulk import failed every single item.** `_process_item` reads
  `item.filename` a few lines after calling `create_hat` — and `create_hat`
  ends in `_reload_hat`, which calls `db.expire_all()`. That expires every
  object in the session, the `ImportJobItem` included, so the next attribute
  read triggered a lazy refresh through synchronous attribute access, which an
  async session cannot service: `greenlet_spawn has not been called`. The
  per-item handler caught it and recorded an error, so the feature failed
  completely while presenting as a batch of bad files.

  Found by writing the first test that ever ran the worker. It reads what it
  needs into plain locals before `create_hat` now — the same discipline the
  export service already uses for crossing a thread boundary.

### Added
- **Coverage measurement**, as `pytest --cov` with **branch** coverage. Branch
  rather than statement because this codebase's risk lives in degradation
  paths — Claude unconfigured, rembg failed, worker dead — which are branches,
  and a statement-only number counts them covered the moment the happy path
  runs once.
- **58 new tests** against what the audit found was least covered, which was
  not random: the modules with the strongest docstring promises had the
  weakest coverage.
  - `import_service` **46% → 87%** — the durability claims (`the loop survives
    ANY per-item exception`, the boot sweep healing crash-stranded state, a
    cancelled job never being resurrected) were prose, not tests.
  - `utils/upload` — the 413 cap, a security control whose own docstring says
    an untestable limit "is how the last one went missing".
  - `report_service` **53% → 97%** — the document that goes to an insurer, and
    the only place the valuation rule renders server-side.
  - `claude_analysis` **57% → 84%** — request shape (owner-stated construction
    is sent as ground truth; dropping it is the bug that shipped in 2.17) and
    failure translation.
  - `ebay_service` **53% → 73%**, `melin_recap` **69% → 83%**,
    `google_vision` **72% → 84%** — the degrade-don't-fail paths, which on a
    Pi talking to four third parties are not edge cases.

## [2.42.0] — 2026-08-23

The remainder of the archaeology report, plus build-time work.

### Added
- **`GET /api/admin/config`** — what this deployment is *effectively* configured
  to do. Every toggle is an env var read live, and `env_int` degrades a typo to
  the default rather than crashing, so a misconfigured box looked identical to a
  correct one from outside. Reports worker expected-vs-alive, backup interval
  and keep-count, **whether an off-box upload is configured at all**, the body
  and disk limits, and free space. No secrets.
- **`analysis_stage_at`** — a stage alone can't distinguish a pipeline that is
  working from one that is wedged; both read "identifying". Stamped by the same
  `UPDATE` that sets the stage, so the two can never disagree.
- **ruff**, inside the existing backend CI job rather than a new one — a
  separate lint job would pay a fresh runner and a full `uv sync` to do a second
  of work. It immediately found **16 dead imports** and a genuine forward
  reference (`AnalysisJobRead` used 4 lines before it was defined, working only
  because `from __future__ import annotations` defers resolution). 58 `noqa`
  codes had been written to an authority that was never installed.

### Fixed
- **The Settings tabs fit a phone, on one line.** As a horizontal scroller the
  tabs past the fold were invisible — no scrollbar on touch, last pill flush
  with the gutter — so nothing on screen said the last section existed. The
  real constraint turned out to be the LABELS, not the layout: five names have
  to share ~320px, which "Collection data" and "This device" never could. They
  are **Data**, **Device** and **Upkeep** now, in five equal columns, one row,
  no scrolling and no ellipsis. The 44px tap target is unchanged.
- **Stats, Valuation and Home gate on `isError`.** `?? []` turned a failed
  fetch into "$0 across 0 hats" — a confident wrong answer, and precisely what
  `valueHat` returns `null` rather than 0 to avoid.
- **The nav error badge is labelled.** A bare red dot is unreadable to a screen
  reader and ambiguous to everyone else; it counts hats whose *analysis* failed,
  not errors in general.
- **`melin_recap` logs.** A network service with a declared, never-used logger,
  whose documented failure mode — Treet rotating the anonymous client id —
  presents as the entire collection quietly losing its resale prices.
- **One correlation token.** `hat=%s` everywhere, so `grep 'hat=42'` is a
  complete trace of one run instead of five formats.
- **The Claude prompt stopped teaching a discarded answer.** `construction` is
  owner-only, but the schema demanded it and spent ~200 tokens per analysis on
  identification guidance that ended with a false claim ("your answer is used
  when they left it blank" — it never is). Trimmed and dropped from `required`.
  The **stitching falsifier stays**, reframed around what it actually protects:
  `model_name`, which *is* stored and *is* the name a person reads.

### Changed
- **Docker builds cache their layers in CI.** The image job rebuilt apt, `uv
  sync`, `npm ci` and a full SPA build from scratch on every run — nearly all
  its wall time and none of its value on a branch that touched only Python.
- **`npm ci` caches on the Pi.** Cutting a release edits
  `frontend/package.json`, which busts that layer — so every upgrade
  re-downloaded the entire dependency tree over the Pi's own network, the
  slowest part of `docker compose up -d --build` there. A cache mount survives
  the invalidation, and `--prefer-offline` stops it revalidating each tarball.
- **A docs-only commit no longer re-runs CI on `main`.** A squash-merge fires a
  second full run on the same tree the PR just passed; worth keeping for code,
  pure waste for prose. Excluded on `push` only — `pull_request` still gates
  every change.

## [2.41.0] — 2026-08-23

### Fixed
- **Color search returned most of the collection whatever you asked for.**
  It ranked hats by CIEDE2000 distance and kept everything under a cutoff of
  26 — and ΔE 26 is an enormous distance. At that threshold **51 pairs of
  curated palette colors matched each other**: black with navy, silver with
  beige, white with cream, charcoal with dark brown. Three releases were spent
  moving that number (30, then 22, then 26) and the file's own comment already
  had the answer: a distance threshold cannot answer "is this hat purple?",
  and tuning it will never make it.

  The measurement that ends the argument: within-family distances run up to
  **ΔE 55.8** (light blue to navy, both plainly blue) while cross-family ones
  start at **15.4** (black to navy). The ranges do not overlap, they *invert*
  — the pair that must match is three and a half times further apart than the
  pair that must not, so no threshold exists that separates them.

  Membership is now categorical, decided on the curated palette names where
  the question has an exact answer. Distance keeps the job it is good at:
  ordering hats that are already the right color. Searching purple returns
  purples and lavenders; searching pink returns pinks.

  Two refinements earn their place. A swatch too muted for its name to be
  trustworthy is classified by **hue angle** instead — a dark teal sits
  nearest *charcoal* by ΔE because it is dark, but its hue is 197°, the same
  as a mid teal's — with the existing chroma-*ratio* guard separating the case
  that must match (a dark teal holds 41% of teal's chroma) from the one that
  must not (a blue-grey holds 20% of blue's), since their absolute chromas are
  11.1 and 11.7 and nothing else tells them apart. And blue/purple can never
  be bridged by hue at all, because CIELAB's hue angle is non-linear through
  the blue region — a defect of the color space, not a judgement call.

  A color chip now honours major colors the same way a typed color term has
  since 2.39, with a per-rank distance budget so "the hat with the pink brim"
  still works but a pinkish logo no longer counts as a pink hat.

- **The collection export took longer than a full backup and produced
  nothing.** It generated every hat's 800px derivative inline, in the
  card-rendering loop, **on the event loop** — a full-resolution decode and a
  slow WebP encode each. A few hundred hats is minutes during which the app
  answers no request at all, with a decoded full-res image resident alongside
  rembg's 179 MB model in a 1 GB container.

  Derivatives are now written when the photo is processed, swept in at boot
  for hats that predate the change, and whatever is left resolves on a worker
  thread with progress logging. The export is a zip of files that already
  exist.

- **A legacy hydro/hydrolite flag was dropped when sent with another field.**
  The `elif` handling pre-2.11 clients hung off the `artist_series` test
  rather than the `construction` test, so a flag sent *alongside* an artist
  series was silently ignored while one sent alone worked. Two unrelated
  fields, one `elif`.

- **The purchase importer disagreed with its own preview.** `import_purchases`
  adds a row per unit as it walks a batch, and the dedupe query autoflushed
  those pending rows — so units the batch had just staged were counted as
  already-existing *and* as staged, subtracting the line twice. `preview_import`
  writes nothing, so it had nothing to flush and stayed correct. Equal
  quantities clamp to the right answer by accident, which is why it went
  unnoticed.

- **The case forms advertised the wrong capacity, in both digits.** They read
  "Default: 4 regular / 6 beanies"; a default case is **3 regular (4 at a
  squeeze) / 8 beanies**. Now built from the constants and pinned by a parity
  test, the mechanism this repo already had for exactly this.

## [2.40.0] — 2026-08-23

The three failures this deployment was structurally unable to notice, plus
backups that stop restating themselves.

### Changed
- **Backups are written only when the data has changed**, and retention is now
  a **count** (`HEADROOM_BACKUP_KEEP`, default 5) rather than an age. On an
  untouched collection a daily tarball re-read every photo, wore the SD card,
  and evicted a genuine historical snapshot from a fixed-size window to store
  a restatement of the newest one.

  The two changes are one change. Age-based pruning combined with
  change-gating has a steady state of **zero backups** on an idle system: the
  last one ages out and nothing is written to replace it. Counting cannot do
  that. `HEADROOM_BACKUP_RETENTION_DAYS` is still read — as a count — so an
  existing `.env` keeps meaning something instead of silently reverting.

  Change is judged from the size and mtime of the database, **its WAL
  sidecar** (a commit in WAL mode can leave the main file untouched, so
  watching it alone would call a day of edits "no changes"), and every file
  under uploads. The marker recording the last backed-up state is a file in
  `backups/` and deliberately not a row in the database — the database is part
  of what it measures, so a marker stored there would invalidate itself every
  time it was written.

### Added
- **The app can see the disk filling up.** There was no free-space check
  anywhere, and readiness proved the volume was writable by writing two bytes
  — which succeeds with 8 KB free, while the next backup tarball fails, SQLite
  starts raising `disk I/O error`, and photo uploads stop. Two thresholds,
  because there are two things to say: a warning in the log below 15%, and
  readiness failure below a hard floor of 500 MB. The floor is an absolute
  size rather than a percentage because what matters is whether the next
  backup fits.
- **Readiness fails when a background worker has died.** The Docker
  healthcheck is anonymous and worker liveness was authenticated-only detail,
  so the container could not go unhealthy for a dead analysis or import worker
  — leaving `restart: unless-stopped`, the only automated recovery here, blind
  to the two failures most likely to develop over weeks. Gated on whether the
  worker is *expected* to be running, so a deliberately disabled one is not
  reported as a fault.
- **The Backups card now says whether the scheduler is working.** The endpoint
  that answers this shipped in 2.26 and nothing ever rendered it. It
  distinguishes running-and-idle-because-nothing-changed from failing from not
  running at all — a distinction that matters much more now that an old
  newest-backup is a normal, correct state.
- **Unhandled errors become activity-log rows.** A 500 previously left exactly
  one trace: a stack trace on stdout, inside a container, on a Pi. The one
  in-app error surface queries hats whose analysis failed, so a route 500
  appeared nowhere in the app at all. The traceback still reaches the log —
  the row joins it rather than replacing it.

### Fixed
- **Security headers were missing from every 401.** `add_middleware` prepends,
  so the last one added is outermost — and `SecurityHeadersMiddleware` was
  added first, which put it behind the auth gate. The gate short-circuits an
  unauthenticated `/api/*` request with its own 401, and that response never
  reached the header middleware: no CSP, no `nosniff`, no `X-Frame-Options`,
  on precisely the responses a stranger is most likely to receive. The test
  named for this invariant asserted against `/health`, which the gate lets
  through — the one path where it already held.
- **`last_success_at` no longer forgets on restart.** The health record is
  process-local, and on this deployment restarts are routine, so the endpoint
  named *health* was the one that forgot — and `null` reads as "never
  succeeded". It falls back to the newest backup's mtime, flagged as derived,
  because a file proves a backup was written and not that anything is still
  scheduled to write the next one.
- **A 20 MB JSON body no longer costs ~300 MB of RAM.** Every upload path was
  careful; nothing else was, so the cheapest denial of service against a 1 GB
  Pi was one unauthenticated curl at the login page. Non-multipart bodies over
  2 MB are refused with 413 before the auth gate spends a database lookup on
  them. Multipart is exempt — those routes stream to disk under their own,
  much larger, deliberate caps.
- **A rejected password is no longer echoed back in the 422.** Pydantic puts
  the offending `input` into every validation error and FastAPI serialises the
  list straight into the response body, so a password refused for being too
  short came back in clear text — into the browser's network tab and any proxy
  log on the way. The field and the reason stay; the value was the one part
  the caller already had.
- **The Google Vision API key is no longer printed to the container log.** It
  travelled as `?key=`, and httpx logs the full request URL at INFO on every
  call. It goes in the `X-Goog-Api-Key` header now, which is what Google
  documents it for.
- **A bulk import with no worker running says so at ERROR**, and the check is
  now on the worker rather than on the queue object — a queue with nothing
  draining it accepts work silently, so the old test caught the disabled case
  and missed the crashed one. `stop_worker` clears the queue to match
  `analysis_queue`. Scheduled-backup and upload-hook failures were promoted to
  ERROR as well: nothing in 75 logging call sites was ever logged at ERROR, so
  the disaster-recovery feature failing sat at the same severity as "mDNS: no
  LAN address found".

## [2.39.0] — 2026-08-22

### Fixed
- **The guest grid's tiles were broken, and it was `.card` on an anchor.**
  `.card` never declared a `display`, which was invisible while every card was
  a `<div>` (already block). 2.37 made the guest tiles links, and an `<a>` is
  `display: inline` — so `h-100` was ignored outright and the border broke
  across line boxes. `.card` now says `display: block`; divs are unaffected and
  `.d-flex` is `!important` so flex cards still win. This was latent in five
  other places that already put `.card` on a `<Link>`.

- **A hat is not "pink" because its logo is.** Color terms matched ANY row in
  `hat_colors`, so searching "pink" returned every black cap with a pink
  embroidered mark. On this collection that made color search close to
  useless: a melin hat is a dark crown with a bright logo, and the accent
  colors are exactly the ones that vary. Color terms now match **major
  colors only** by default — dominance rank 1–2, which is the hat's own
  color and its second, not its trim.

- **The guest search didn't survive going to a hat and back.** The term lived
  in component state, which a re-mount discards, so Back returned you to the
  whole collection with an empty box. It lives in the URL now (`/guest?q=…`),
  and the results are cached long enough that the page is its full height when
  the browser restores your scroll position — without that, Back put you at the
  top of a list that was still loading.

### Added
- **A color-match toggle: Main colors / Accents only / Any.** "Accents only"
  is its own question rather than the leftovers of the default — *which of my
  hats has pink on it somewhere* is how you look for a collab mark or a
  contrast underbrim. On the Search page and the guest page; on the latter it
  is in the URL too, so Back restores the whole search rather than half of it.
  An unrecognised value falls back to the default, because it arrives from a
  query string and the safe reading of a typo is not a wider search.

## [2.38.0] — 2026-08-22

### Added
- **The server hands you the certificate to trust.**
  `GET /api/public/ca-certificate` serves Caddy's **root** CA, linked from
  **Settings → This device → Trust this device** (which appears only when a
  local CA exists). Open it on the phone and iOS offers to install it — no
  `docker compose cp` on the Pi and no AirDrop.

  Served as `application/x-x509-ca-cert`, because as `text/plain` a perfectly
  good certificate is displayed rather than installed, which looks like it is
  broken.

  **Only `root.crt` is served, and the filename is hardcoded.** The same
  directory holds `root.key` and `intermediate.key`, so the handler takes no
  path, no filename and no parameter of any kind — there is no input to
  traverse with, which is a stronger guarantee than validating one. The
  overlay mounts Caddy's volume `:ro` so a bug there still cannot write to the
  PKI.

### Documentation
- **The intermediate is the trap, and now the docs say so.** `root.crt` and
  `intermediate.crt` sit side by side and only the root is a trust anchor: a
  root is self-signed and installed out of band, whereas an intermediate is
  presented by the server during the handshake and means nothing until its
  issuer is already trusted. Installing one therefore *appears to succeed and
  changes nothing* — which is exactly what "the certificate won't install"
  looks like from the outside. Called out in the README's step 2 and added to
  its troubleshooting list.

## [2.37.0] — 2026-08-22

### Added
- **Guests can open a hat.** Tiles in the guest view are now links to
  `/guest/hat/:id`, showing the photo, name, style, colors and — given the
  most room, because it is the question a guest actually has — **which room and
  which case** it lives in. A caseless hat says so and still names its room.

  A real endpoint rather than a detail rendered from the listing payload, so
  the link survives being sent to somebody. It returns **exactly** the
  `SharedHat` projection the grid already used: a per-hat endpoint is precisely
  where someone reaches for "just one more field", and this is the surface
  where that costs most, so a test pins the response's key set.

### Fixed
- **`shared_hat` required a photo**, because its only caller was the photo
  endpoint. A hat plainly listed on the page you clicked from would have 404ed
  when you clicked it. It now answers "may an outsider see this hat", which is
  a different question from "does it have a photo to serve" — both photo routes
  check that themselves, and a test pins that share-link photos still 404
  without one.
- **`shared_hat` used `db.get`**, returning a bare instance. `room_name` walks
  `hat.case.room`, a relationship hop that raises rather than lazy-loading
  under asyncio. It now eager-loads what the projection reads.

## [2.36.2] — 2026-08-22

Findings from a two-axis review of 2.34–2.36.1.

### Security
- **Guest search could be used as an oracle for fields the projection
  withholds.** `SharedHat` deliberately omits condition, size, collection and
  construction — but guest search delegated to the owner's search, which
  matches on all four. `?q=worn` returned exactly the worn hats, so a guest
  could read every hat's condition by probing, and its size, collection and
  construction the same way. Verified live during review.

  `search_hats(public_fields_only=True)` now drops those clauses **and the
  hydro/hydrolite flags derived from construction** — closing the front door
  and leaving that window open would have leaked the same fact. The owner's own
  search is unchanged.

- **`/api/auth/status` no longer tells anonymous callers that guest view
  exists.** It returned `guest_view_enabled: false`, which is precisely the
  fact the guest routes' 404-rather-than-403 was written to keep private. The
  field is now absent when off.

### Fixed
- **Guest search reported a capped count.** The response's `hat_count` is its
  own length, and search was bounded to 50 — so a search matching 200 said "50
  hats". The third instance of the same `len()`-of-a-capped-list mistake, after
  the colorway catalog and the analysis queue. Guest search uses its own,
  higher bound.
- **The case-valuation rule was stated a third time**, inside
  `report_service`, where `tests/test_valuation_parity.py` cannot see it — and
  it had already drifted: a flat constant per row, where the browser sums each
  case's served `retail_price`. Moved to `services/valuation.value_cases()`
  beside the hat rule, with a parity test that fails if the renderer restates
  it again.
- **Home and Stats showed a Cases tile beside a hats-only total**, which
  answers "what's it all worth" only if you do the addition yourself. Both now
  carry a combined figure, as the Valuation page and the report already did.

### Changed
- One projection *mapper*, not just one projection type. The share-link and
  guest routes each built `SharedHat` field by field; the type was shared, the
  ten-field mapper was copied — so a field added to the projection would be
  filled in at whichever site the author was looking at, and the copy that fell
  behind would be the one exposed to strangers. `share_link_service.to_shared_hat()`.
- Guest fetching moved into `frontend/src/api/guest.ts`, per the convention
  that API functions live in `api/`.

## [2.36.1] — 2026-08-22

### Fixed
- **"Re-analyse every hat" was re-analysing a fraction of them** — 45 of 234 in
  a real collection.

  A checkbox above the button read *"Leave hand-entered prices alone"* and was
  **on by default**. It mapped to a server filter, `only_priced_by_claude`,
  which restricted the run to hats whose price source was `Claude Vision`.

  Before 2.27 that was very nearly every hat, so the option looked harmless and
  the label looked true. **2.27 moved the majority onto the retail table**
  (`source = "melin retail"`), and the same filter then matched only the
  remainder Claude still prices — Thermal, the Mill straw line, anything the
  table can't name. Nothing announced the change in meaning; the button still
  said "every hat".

  The filter was **redundant from the start**. A Manual price is protected
  unconditionally: `retail_pricing.resolve_retail` returns it untouched, and
  the pipeline bails on `resale_price_scope == "manual"` in two places. So it
  never spared anything that wasn't already safe — it only shrank the run.

  Removed. Re-analysis now covers **every hat with a photo**; disposed hats
  remain the only exclusion, because re-pricing them spends Claude calls on
  inventory you no longer own.

- **The queue's "waiting" count was capped at 50.** `pending_count` was
  `len(hats)` over a list deliberately bounded to 50 for display, so a deeper
  backlog always reported 50 — a count read off a limited feed, the same
  mistake as sizing the colorway catalog from its autocomplete endpoint. The
  list stays bounded; the count is now a `COUNT`.

## [2.36.0] — 2026-08-22

### Added
- **Guest browsing.** A "browse the collection as a guest" link on the login
  screen, letting anyone who can reach Headroom look through the collection and
  search it without an account. Useful on a LAN when people in the house should
  be able to look but shouldn't have a login.

  **Off by default.** Unauthenticated read access to somebody's whole
  collection is not a thing anyone should acquire by upgrading — it is a switch
  in **Settings → Sharing → Guest browsing**, and until it is thrown the
  endpoints behave exactly as if they did not exist.

  **404, not 403, when off.** A 403 confirms the feature is there and merely
  switched off, which is a fact about a private install a stranger has no
  reason to learn. The login screen omits the link entirely rather than
  disabling it, for the same reason.

  **No pricing, and not by hiding it.** Guests get the same `SharedHat`
  projection share links use: photos, brand, model, style, colors and where a
  hat lives. Prices, purchase history, disposition, wear counts, analysis state
  and owner notes are *never sent* — returning the full model and trusting the
  frontend not to render the rest is exactly how that leaks. Disposed hats are
  excluded too: what something sold for is nobody else's business.

  Search is delegated to the real search service rather than reimplemented. A
  guest-only copy would quietly stop matching what the owner's search matches,
  and nobody would notice because nobody runs both. Only a submitted term hits
  the server — a request per keystroke is a lot of load to hand an
  unauthenticated caller.

  Read-only by construction: there are no non-GET routes in the module, and a
  test fails if one is ever added. Turning guest view on does not weaken the
  gate on anything else, which is also tested.

  Flipping the switch is written to the activity log both ways — "when did that
  get turned on" is a question the log should be able to answer.

## [2.35.0] — 2026-08-22

### Added
- **Rooms are viewable, and loose hats come first.** There was no room view at
  all: `/rooms` listed names with rename and delete, and rooms weren't
  clickable. So the room-stored hats added in 2.33 had **nowhere to be seen** —
  the Cases tab reaches a hat through its case, and a hat on a shelf has no
  case to be reached through.

  `/rooms/:id` shows what's actually in a room, with the loose hats **above**
  the cases. That ordering is the point: a cased hat is findable three other
  ways, a loose one is findable here and in search. It also matches a physical
  room — the things sitting out are what you see when you walk in.

  The rooms list gains a loose count too, since a room holding three hats and
  no cases previously read as empty.

  `GET /api/rooms/{id}` now returns `RoomDetail` (loose hats + cases); loose
  hats are newest-first, because a hat set down loose is usually one you just
  handled.

### Fixed
- **`invalidateHatViews` now covers `['room']`.** It is a *sibling* of
  `['rooms']`, not a prefix match — TanStack matches by prefix and "rooms" is
  not a prefix of "room". Without it, moving a hat into or out of a room left
  the room view showing it where it used to be for the full 30s `staleTime`.
  Exactly the shape of trap already documented for
  `['admin','recent-errors']` vs `['admin','recent-errors-count']`.

## [2.34.0] — 2026-08-22

### Fixed
- **The cases were in no total at all.** `CaseRead.retail_price` had been
  served since 2.27 and was read by *nothing* — it existed only in the
  TypeScript type. So "collection value" excluded dozens of $49 travel cases,
  understating the thing it names by four figures, and silently: nothing on
  screen hinted cases were left out rather than counted as worthless.

  They now appear on the Home summary, the Stats "Money" card, the Valuation
  page and the printable inventory report — which matters most, since that is
  the document that goes to an insurer.

  **Reported on their own line, never folded into the hat figures.** Two
  reasons, and both would have been invisible if ignored:

  - A case is not a hat. Quietly adding a couple of thousand to a number
    labelled *market value* would make every comparison on the page — retail
    retention, unrealised gain, cost per hat — wrong in a way nobody could see.
  - The two are different *kinds* of number. Hats are valued from live
    comparable listings; cases have no resale market at all, so $49 is
    replacement cost, not what one would fetch. The Valuation page adds a
    "Everything, together" line so the combined figure is available without
    either number pretending to be the other.

  `valueCases()` sums each case's **served** `retail_price` rather than
  multiplying by a constant declared in TypeScript — the price lives in
  `services/retail_pricing.CASE_RETAIL`, and a second copy is one that can
  drift.

## [2.33.0] — 2026-08-22

### Added
- **A hat can live in a room with no case.** Rooms contain Cases contain Hats
  was the whole model, so `Hat.room` walked `self.case.room` and a caseless hat
  reported no room at all — it was *nowhere*. That is not how a collection
  sits: Caddies and Aviators don't fit a three-hat travel case, special
  editions get displayed rather than packed, and plenty of hats are simply out
  on a shelf.

  Any hat can be placed this way; nothing is restricted by style. A case and a
  direct room are **mutually exclusive** — `assign_hat` clears one when it sets
  the other, because a cased hat's room *is* its case's room and a second
  stored answer is one that can disagree. `room_id` still resolves either, so
  nothing reading it had to change.

  Deleting a room moves its caseless hats to the default room alongside its
  cases. They aren't reachable through any case, so the existing sweep missed
  them entirely — left behind they'd point at a room that no longer exists,
  which reads as the hat vanishing from every room view while still existing.

- **Limited edition** checkbox on the hat form. Nothing can derive this: a hat
  is limited because the drop was, which no photo and no other field can tell
  you.

### Changed
- **Beanie case capacity is 8, up from 6**, and 8 is a *hard* ceiling. They have
  no brim and squash flat, so far more fit in the same shell than the three the
  case is named for. Beanies get **no overfill allowance**: the regular one
  exists because 3 is melin's *name* for the case and a fourth demonstrably
  fits, so the number to be lenient about was never a measurement. 8 is the
  opposite — it is what fits, counted by packing it — and slack on top would
  assert a ninth fits, which nobody has claimed.

### Fixed
- **Search by room could not see room-stored hats** — caught by review before
  release, and the worst kind of bug: `Hat.case.has(Case.room_id == …)` is NULL
  for a caseless hat, so the API filter excluded exactly the hats the feature
  adds, while the Hats page (which filters client-side on the resolved
  `room_id`) kept showing them. Two room filters, disagreeing about the same
  collection. Searching a room by *name* had it too. `search_service._in_room()`
  is now the one disjunction both call sites use — `Hat.room_id` is a Python
  `@property` and cannot appear in a `WHERE`, so each caller would otherwise
  write it out and one would forget half.
- **Creating a hat in a nonexistent room was accepted.** `assign_hat` checked;
  `create_hat` didn't. The migration adds `direct_room_id` without a foreign key
  (SQLite cannot add one to an existing table), so the bad id persisted and the
  hat reported no room at all — looking like the placement simply hadn't taken.
- **The case detail page showed the wrong capacity, twice.** It computed its
  own `capacity ?? 4` / `?? 6` — a second copy of a rule `services/capacity.py`
  owns. `4` is the *overfill limit* rather than nominal, so a full three-hat
  case displayed **"3/4"** (the same bug fixed in the printed case labels in
  2.28, still live here), and the hardcoded `6` would have silently become
  wrong the moment beanie capacity moved. `CaseRead` now publishes
  `nominal_regular` and `nominal_beanie` so no client restates either.

## [2.32.0] — 2026-08-22

### Breaking
- **Analysis no longer decides construction. At all.** It never overwrote a
  stated value, but it filled the field whenever it was *empty* — and
  `_apply_construction`'s own docstring already explained why that was unsafe:
  Claude reads HYDRO vs HYDROLite off a photo unreliably, because the tells are
  bonded seams, a gel-welded logo and a sweatband, none of which survive a
  front-on shot. It was established in 2.11 that letting it *correct* a value
  replaced right answers with wrong ones; filling a blank is the same coin
  toss, with nothing prior to notice being lost.

  Two later changes turned a cosmetic guess into an expensive one:

  - **It moved money.** `retail_pricing` prices HYDRO at $79 and HYDROLite at
    $99, so a guess skewing HYDROLite over-priced the hat by $20.
  - **It hid hats.** 2.29 made construction a filter, so a mislabelled hat is
    absent from a filtered view rather than merely wrong in a detail pane.

  A blank construction is an honest *"nobody has looked yet"*. A guessed one is
  indistinguishable from one you typed. **Construction is now owner-only.**

- **A model name may not assert a construction nobody stated.** melin names
  read `<line> <construction>`, so "A-Game HYDROLite" carries the same guess in
  the field a person actually reads and quotes — and
  `_strip_contradicting_construction` returned early when no construction was
  stated, so a blank protected nothing. With none stated, every construction is
  now stripped from the name. Removed, not rewritten: "A-Game" is less specific
  than "A-Game HYDROLite" and, unlike it, known to be true. State the
  construction and re-analyse and the full name comes back.

### Added
- **Construction audit** (Settings → Construction audit), for undoing what
  analysis already wrote. Nothing in the database records which values came
  from a person, so this deliberately is *not* a startup backfill that decides
  for you: it lists every construction on record with how many hats are priced
  from it, previews exactly what clearing one would do, and acts only on an
  explicit confirmation.

  Clearing a construction also clears what was derived from it — the
  construction word in `model_name`, and a retail price that came from the
  price table. Leaving that price behind would be a number with no derivation,
  indistinguishable from one somebody checked. **A price you entered manually
  is never touched**, the same protection it has everywhere else.

  It **reassigns** rather than only clearing: `to=HYDRO` writes the right
  answer, because the common case is not "I don't know" but "these are all
  actually HYDRO", and clearing would discard a correction you already know how
  to make. The price is then re-looked-up from the new value ($99 → $79) rather
  than dropped.

  And it **leaves your own values alone**. `hat_service` writes an audit row
  naming the fields a client PUT changed, so a `hat.updated` row mentioning
  `construction` is proof a person typed it; those hats are skipped and the
  count is reported so you can see the protection working. This is a proof of
  ownership, not a complete one — audit rows prune after 90 days and
  creation-time values were never logged — so it can say "this one is
  definitely yours", never "this one is definitely not. That asymmetry is the
  right way round: it only ever protects more.

  `GET /api/admin/constructions/audit`, `POST /api/admin/constructions/clear`
  (`dry_run=true` and `skip_owner_set=true` by default).

- **The analyser now knows the one HYDROLite tell that a photo can show.**
  HYDROLite seams are bonded and show no thread, so **visible stitching on the
  panel or crown seams rules HYDROLite out**. That is a falsifier rather than an
  identification, which is what makes it worth having: it can be checked against
  what the photo actually shows, instead of inferred from an overall impression
  — and "looks lightweight and technical" describes HYDRO just as well, which is
  how HYDROLite became the default wrong answer. Stated as a hard exclusion in
  both the system prompt and the tool schema.

### Changed
- **Settings is five sections instead of nineteen cards in a row.** It had
  grown by accretion, ordered by the sequence things were built in — API keys
  next to LAN discovery next to the backup list — so finding anything meant
  scrolling past everything, which on a phone is most of a minute.

  Grouped by **errand**, not by subsystem: *Analysis* (how a photo becomes an
  identified hat) spans two API keys, a worker queue and an error list, and
  that is fine because it is one thing you came to do. Then *Collection data*,
  *Sharing*, *This device*, *Maintenance*.

  The section lives in the URL (`/settings?tab=data`), like the Cases type
  filter, so it survives a reload and can be linked to. The tab strip scrolls
  horizontally rather than wrapping — three rows of small targets is worse on a
  phone than one row you swipe.

  Side effect worth having: only the open section is mounted, so opening
  Settings no longer fires all nineteen cards' queries at once.

## [2.31.1] — 2026-08-22

### Fixed
- **Typing a known value showed the whole list instead of the match.** Typing
  `Links` into Collection offered `'Ohana`, `23XI Racing`, `Adventure Club`,
  `ALOHA 96761` — every option, alphabetically — which reads as the box being
  ignored. The filter skipped itself whenever the typed text exactly matched an
  option, on the theory that "value equals an option" meant "the user picked
  it". It cannot: typing a known value out in full is the normal case. The
  Combobox now tracks whether the value was **typed** or **picked**, which is
  the distinction that check was reaching for. Affects both Construction and
  Collection, which share the component.

- **Matches are ranked exact → prefix → substring.** The list is capped by
  screen height on a phone and a plain filter is alphabetical, so typing
  "Links" put "Cypress Links" above "Links" — the thing you typed, below a
  longer name that merely contains it.

- **The list could not be reopened after picking.** Found while fixing the
  above, not reported. Options call `preventDefault` on mousedown so the field
  keeps focus through a pick; that leaves the input focused with the list
  closed, and tapping it fires no focus event. There was no way back to the
  list except focusing another control first. Fixed in **both** the Combobox
  and the case picker, which had it too.

## [2.31.0] — 2026-08-22

### Added
- **melin's beanie shapes are now models, not one bucket.** Journey,
  Destination and All Day are named and sold like any other melin model (see
  melin's own "Beanie Shape Guide"), so they are `HatStyle` members.
  `beanie` remains as **"Beanie (unspecified)"** — existing hats use it, and a
  shape you haven't identified is a real state.

  Prices come from the order history: **Journey $79** (Dusty Sage #1715774,
  Mustard #1792264) and **Destination $79** (Military #1789227).

  **All Day is deliberately unpriced.** It appears in the order history exactly
  once, at **$0.00** — the "FREE All Day Pom Beanie With Purchase" promo — and
  a giveaway is not a retail price. No melin email states its value, so it
  falls through to Claude's estimate rather than inheriting the $79 that the
  other two establish. Same call already made for Thermal and the Mill straw
  line: `base_retail` returning None is a real answer.

### Changed
- **`is_beanie` now has exactly one definition.** It is a real column — search
  filters query it and case capacity depends on it (6 beanies per case vs 3
  regular hats) — but it is *derived* from style, and that derivation was
  written out separately at each write site. `schemas/hat.BEANIE_STYLES` +
  `is_beanie_style()` is now the single source, the same way
  `Hat.set_construction` is the only writer of `hydro`/`hydrolite`.

  A beanie shape missing from that set would pack 3-to-a-case, disappear from
  the Beanies filter, and make the case picker offer cases the save then
  rejects with a 409 — none of which looks like a bug from the outside.

- **`GET /api/meta/styles` publishes `is_beanie` per option.** The frontend used
  `style === 'beanie'` to decide case availability; with several beanie shapes
  that would have become a hardcoded TypeScript list, i.e. a second definition
  of `BEANIE_STYLES` that eventually disagrees with the server. The flag is
  served instead.

## [2.30.0] — 2026-08-22

### Added
- **The analyser now learns your series.** Entering a collaboration or artist
  series taught the *typing* autocomplete (`GET /api/meta/collections` has
  always returned every value in use, and the Add/Edit form offers it) — but it
  never reached Claude. `analyze_hat_image` was given the owner's style and
  construction and nothing else, so every analysis was asked to recall a collab
  from a photo unaided.

  That is the wrong thing to ask. A series is rarely legible in a photo — it is
  usually a small woven label or an embroidery style — so most were simply
  missed. The names already on record are now sent with the image, turning
  recall into recognition.

  The framing is deliberately careful, because a candidate list invites a
  forced choice and a wrong series looks exactly like a right one. It is stated
  as a record of what the collection contains, **not** a list to choose from,
  with an explicit instruction that `null` beats a wrong match. If the list is
  ever long enough to be truncated the prompt says so, rather than presenting a
  partial list as if it were everything.

### Fixed
- **Analysis-written free text was never canonicalised.** `vocabulary.canonicalize`
  ran on the client write path (`hat_service`) but not the analysis path, so
  Claude returning `skye walker` created a second entry beside your
  `Skye Walker`. Nothing looked wrong afterwards — both hats had *a* series —
  and the split surfaced only as two near-identical rows in the autocomplete,
  the Stats collab chart, and (as of 2.29) the filters. Both paths canonicalise
  now, covering `artist_series` and a construction Claude filled in on a hat
  that had none. Construction goes through `set_construction` so the derived
  `hydro`/`hydrolite` flags cannot drift.

  This is what made the feature above safe to ship: feeding known names into
  the prompt without it would have multiplied the very duplicates it exists to
  prevent.

### Note
Existing hats are not retroactively re-identified — nothing in the database can
invent a series that was never captured. **Settings → Analysis Queue → re-analyse**
picks them up, and a re-analysis never erases a series you typed (`_keep_on_null`).

## [2.29.0] — 2026-08-22

### Added
- **Filter hats by construction.** The Hats and Search pages share one filter
  bar, so both gained a **Construction** select — populated from
  `GET /api/meta/constructions`, which merges the curated list with every value
  actually in use, so a specialty fabric typed once is filterable from then on
  without shipping a migration. Seeds from the URL like the others
  (`/hats?construction=HYDROLite`).

  Matching is **full equality, never substring** — "hydro" is a literal
  substring of "hydrolite", and those are different products at different
  prices ($79 vs $99), so a `contains()` check would silently fold the two
  together in every filtered view. Casing is ignored, only to tolerate rows
  written before `vocabulary.canonicalize` began snapping values to one
  spelling on write.

  There is also a **"Not recorded"** option. The field is nullable by design —
  analysis never fills it in over a stated value, and clearing it is how you
  ask for a re-identification — so "which hats still need this?" is a real
  question that previously had no way to be asked.

### Fixed
- `SearchResult` now carries `construction`. The Search page applies the shared
  predicate client-side to whatever `/api/search` returns, so a field the
  filter reads but the projection omitted would have rendered a fully populated
  dropdown that silently matched nothing. Covered by
  `test_search_results_carry_construction`.

## [2.28.0] — 2026-08-22

### Added
- **QR stickers and NFC tags for hats and cases.** A tag carries one URL and
  nothing else, so both formats are the same feature: print the QR, or write
  the identical URL to an NFC sticker with any tag writer (NFC Tools on iOS,
  NXP TagWriter on Android). No app support is needed beyond the URL — iOS
  reads NFC URI records from the lock screen with nothing installed.

  Tapping a **hat** tag opens a one-tap *"Wore it today"* screen: photo, name,
  and a single oversized button. That is the whole point. Wear logging only
  ever happens at one moment — hat in one hand, phone in the other — and the
  full hat page puts its wear button a scroll below several cards.

  Tapping a **case** tag opens that case's contents.

  New printable sheet at `GET /api/admin/hat-labels`, with `?case=AH-01` to
  narrow it to one case — which is how you actually do this, a case's worth at
  a time with that case open in front of you. Every label prints its URL as
  text underneath, because writing an NFC tag means pasting that URL somewhere
  and a QR you must scan to read back is a poor way to move text between apps.

  Three decisions are load-bearing, all from one fact — **you cannot rewrite a
  sticker that is already on a hat**:

  - **Hat tags key on the immutable `hat.id`, not `display_id`.** A display id
    is derived from case + position, so it changes the moment a hat is
    reshuffled, and is `None` for an unassigned hat — precisely the state a hat
    is in while you are tagging it. A sticker printed with one would keep
    scanning and silently resolve to a *different* hat. Cases are the opposite
    and key on `display_id`: it is painted on the physical case and never
    changes.
  - **Tags point at `/t/...`, not at the real page.** One level of indirection
    that costs nothing now and cannot be added later; if the route table is
    ever reorganised, the landing route absorbs it and the stickers keep
    working.
  - **The host is configurable** (Settings → Tags & labels), defaulting to
    whatever you are browsing on. Browse to the Pi by IP once and every tag
    written that afternoon names a DHCP lease; pinning
    `http://headroom.local:8000` survives the Pi changing address. A base
    without an `http(s)` scheme is rejected — an NDEF URI record needs one, and
    a QR without one is read as plain text, so `headroom.local:8000` looks
    obviously right and produces tags that do nothing.

- **Login returns you where you were** (`?next=`), which physical tags need:
  tapping a tag with an expired session previously dropped you on the home
  page, losing the one piece of information the tap carried. Only same-origin
  paths are honoured — an absolute URL there would make the login screen an
  open redirect.

### Fixed
- **Case labels printed the wrong occupancy, onto adhesive.** The sheet
  computed capacity itself as `c.capacity or (6 if beanie else 4)` — a third
  copy of the rule `services/capacity.py` exists to centralise, and wrong two
  ways. `4` is the *overfill limit*, not nominal capacity, so a full three-hat
  case printed **"3/4"** — reading as room for one more. And `len(hats)`
  counted **disposed** hats, which have already freed their slot. It now defers
  to `capacity.evaluate`, like the picker and the write validator.

### Changed
- The copy-to-clipboard control falls back to `execCommand` outside a secure
  context. `navigator.clipboard` is `undefined` on plain HTTP, which is exactly
  how Headroom is served on a LAN (`docker-compose.http80.yml`) — so without
  the fallback the button would appear to work and copy nothing.
- Frontend tests share one `HatRead` fixture (`src/test/fixtures.ts`) instead
  of each file writing out all ~50 fields, and `renderWithProviders` accepts an
  initial route for components that read `useParams` / `useSearchParams`.

## [2.27.0] — 2026-08-22

### Fixed
- **Base retail prices were wrong for the entire collection, and a comment was
  the cause.** `estimated_new_price` came entirely from Claude Vision, steered
  by a block of price anchors in the analysis prompt. A photo cannot show a
  price, so those anchors *were* the answer — and they read **"HYDRO caps —
  $69 is the common price"** long after the band had moved. Every hat inherited
  it, and so did valuation's retail-share fallback.

  melin prices are now **looked up**, from a table cross-checked against 223
  real order lines:

  | item | table | order history |
  |---|---|---|
  | HYDRO | **$79** | $89×67, $69×30, $79×29 — the band moved over the years |
  | HYDROLite | **$99** | $99×16, $89×1 — unambiguous |
  | Beanie | **$79** | $79×3 (Destination, Journey) |
  | 3 Hat Travel Case | **$49** | $49×34, $39×15 |
  | Aviator | **$99** floor | $179 Scout Thermal, $139 Infinite Thermal |

  What the table deliberately does **not** do is invent the numbers it cannot
  know. Thermal is $79/$89/$99 on caps but $139/$179 on Aviators, and the Mill
  straw line runs $99–$180 — so those fall through to Claude's estimate, which
  is still labelled as a guess. And the table never pulls a *higher* estimate
  down: the base is what a plain example costs, and collabs, artist series and
  premium colorways genuinely exceed it. That is the "some hats are $89" case.

- **An entered retail price is now permanent.** Typing one marks it `Manual`,
  and no analysis, re-analysis or backfill may overwrite it — the same
  protection `resale_price` has had since 2.19. Previously the next analysis
  silently replaced it, which looks like nothing happened.

- **Existing hats are re-priced once on upgrade** (`retail_prices_v2`). Fixing
  the code alone would have left a collection where a hat's price depended on
  *when* it happened to be photographed.

- **A test was pinning the wrong price.** `test_pricing_prompt_keeps_its_anchors`
  asserted `$69` stayed in the prompt — enshrining the stale anchor as a
  requirement. It now asserts the prompt and the table *agree*, since a prompt
  quoting $69 while the table says $79 just produces estimates the table
  discards.

### Changed
- **The analysis prompt stops guessing melin prices** and is told the table
  will override it. Its remaining job is the exceptions the table cannot see —
  collabs, artist series, Mill straw, Thermal Aviators — where an estimate
  *above* the base is real information.
- **Cases publish their retail price** (`CaseRead.retail_price`). Not a column:
  every case is the same product at the same price, so a per-row copy would be
  forty duplicates of one number waiting to disagree.

## [2.26.0] — 2026-08-19

### Fixed
- **Case photos are actually gone.** "Cases show a collage of their hats, not a
  case photo" had been true of exactly one of three surfaces. The grid got the
  collage; the **detail page**, the **edit form** and `POST /api/cases/{id}/photo`
  all kept the feature — so a case with three hats in it rendered a
  screen-filling **"NO PHOTO"** placeholder above its own contents, with a
  Capture/Upload button under it. All three removed; the detail page now shows
  the same collage the grid does, and a test asserts the route returns 405 so it
  cannot come back quietly. `Case.photo_path` and any files on disk are left
  alone — dropping those is destructive and should be a decision.

- **The backup health endpoint was reporting success when the backup failed.**
  `write_scheduled_backup` catches its own exception and returns `None`, and the
  loop called `record_success()` without checking. A backup failing *every*
  cycle reported `last_success_at = now` and `consecutive_failures = 0` — the
  endpoint asserting good health while carrying precisely the blindness it was
  built to remove. An existing test concealed it: its stub returned `None` on
  its **success** path, harmless only because nothing read the return value.

- **The Android share target was broken, not merely uncapped.** `POST /share`
  read whole files into memory and passed `create_job` **bytes** — but that
  function takes **paths** (`source.stat()`, `shutil.copy2(source, …)`), so
  every share raised `AttributeError` on the first file. Nothing covered the
  handler. It now spools to a temp dir in capped chunks and passes paths, like
  the bulk-import route it was always meant to mirror.

- **Tests could make real, billable API calls.** `conftest` neutralised
  Sharetribe only. `config.py` reads `HEADROOM_ANTHROPIC_API_KEY` /
  `HEADROOM_GOOGLE_VISION_API_KEY` at import and the key resolver falls back to
  the environment, so anyone with those exported hit the live APIs. The claim
  "tests never call the Anthropic, Google, eBay, or Sharetribe APIs" held only
  by accident of one machine's shell.

### Added
- **Two hat styles: The Shore and Aviator.** Both confirmed against reality
  rather than guessed — The Shore from 953 live marketplace listings
  (`The Shore Islands Hydro`), Aviator from the order history
  (`Aviator Scout Thermal — Heather Grey / Black`, order #1318309). Aviator is
  seasonal, which is why the resale market carries none and no catalogue sweep
  would ever have found it. Neither is mapped into `STYLE_TO_CATEGORY`: the
  marketplace has no such category, so mapping them would sweep an empty one and
  return no comps, while leaving them out lets resale lookups fall through to
  the keyword branch that does find them.

### Changed
- **CLAUDE.md audited end to end and 15 claims corrected.** The case-photo line
  was not an isolated slip. Also wrong: the rank-penalty budgets (stale since
  the color cutoff moved to 26), "three single-file photo routes" (two), the
  path-traversal description (one shared helper now, not two copies), the
  flicker animation (~5s, not 18s), `protected_namespaces`, `_RETENTION_DAYS`
  (does not exist), the lifespan list (omitted the analysis worker), `auth.py`
  (omitted `SecurityHeadersMiddleware`, which owns the CSP another section
  blames), three undocumented services, the components tree, and the query-key
  list.

## [2.25.0] — 2026-08-19

### Fixed
- **"25 models known" was never the catalogue's size.** The Settings card read
  `len(GET /api/meta/colorways)` — the *autocomplete* feed, which caps at its
  own default `limit=25`. The figure would have said 25 with 1,000 models
  harvested, which is indistinguishable from a harvest that found 25.
  `GET /api/admin/colorways/status` now reports the real totals, and the card
  shows models, colorways and listings.

- **One transient marketplace error abandoned the whole colorway harvest.**
  `query_listings` raises on any non-200 — a 429, a 502, a dropped connection —
  and the only handler was at the very top. The sweep is sequential and commits
  per page, and the endpoint had already returned `202 started`, so a single
  blip left a silently partial catalogue that looked exactly like a complete
  one. Pages now retry with backoff, each category is isolated, and any that
  still fails is reported in `failed_categories` instead of vanishing into a
  log line. For scale: a full sweep is **988 listings across 146 models**.

- **Replacing a hat's photo leaked its export image.** The cleanup loop deletes
  everything named by a Hat column — `photo_path`, `original_path`,
  `thumb_path` — but 2.24.0's export derivative is named after the canonical
  photo's *filename* and lives under `uploads/hats/export/`, so it was
  invisible to that loop. Every re-shot hat left one 800px WebP behind.
  `utils/photo.export_derivative_path` is now the single definition of where
  that file lives, so the code that writes it and the code that deletes it
  cannot drift apart.

- **Two query invalidations bypassed `invalidateHatViews`.** Bulk import
  refreshed only `['hats']` and `['cases']` despite creating hats *into* a
  case, and deleting a case refreshed only `['cases']` despite unassigning
  every hat in it. Both left the case's own contents and the per-room counts
  stale for the 30s `staleTime`.

### Changed
- **`hat.case.room` is no longer walked outside the model.** Five call sites
  rebuilt what `Hat.room_name` / `Hat.case_display_id` / `Hat.display_id`
  already provide.
- **Three unlabelled `<select>`s got their `aria-label`** — Case Type,
  Disposition Type, and color Tier. The visible labels carry no `htmlFor`, so
  nothing else associated them.
- **The purchase-import dedupe is defined once.** Import and preview each had a
  byte-identical copy, so "the preview predicts the import exactly" was a claim
  maintained by hand — in the one place it had already gone wrong once.
- **`CONDITION_LABEL` is no longer declared three times.** Two of the copies
  were identical and differed only by a trailing `s` in the name; the third is
  genuinely different (lowercase, for use inside a sentence) and is now named
  `CONDITION_IN_SENTENCE` so the distinction is deliberate.
- **The payout constants have one home again.** `melin_recap.py` defined
  `CASH_PAYOUT`/`CREDIT_PAYOUT` a third time, unused by anything and outside
  the reach of `tests/test_valuation_parity.py`.
- **README and USAGE now document the zip export and per-hat notes**, which
  2.24.0 shipped into CLAUDE.md and the CHANGELOG only.

## [2.24.0] — 2026-08-19

### Added
- **Download the collection as a zip.** `index.html` plus an `images/` folder:
  open it in any browser, works offline, nothing to host, no login. Every hat
  gets its photo, colors, where it lives, and your notes.

  A zip rather than one self-contained HTML file with base64 images — that is
  neat until it is several MB of base64 no mail client will preview.
  Deliberately a **showcase**, not the inventory report: prices are opt-in and
  off by default, matching what share links already withhold.

  This exists because share links, which are the better answer, only work if
  the recipient can reach the app — and `headroom.local` resolves for nobody
  off your LAN. That is why sharing never worked, and it was never a bug in
  the share-link code.

  Images are **re-encoded to 800px WebP** from the canonical photo rather than
  copied from the 320px grid thumbnail, which looked soft the moment anyone
  opened the zip on a laptop. WebP, which is open and royalty-free rather
  than proprietary, and has worked everywhere since Safari 14 in 2020. The
  alternatives were measured, not assumed: lossless PNG is 137 KB an image
  (40 MB for 300 hats), 256-color PNG is 26 KB but softens the cutout's
  anti-aliased edge, and JPEG is 31 KB with **no alpha at all** — the hats
  would stop floating. AVIF came in at 13.5 KB against WebP's 13.9 on
  photographic content, a few percent rather than the ~30% it manages on flat
  synthetic images, so it buys nothing worth a Safari 16.4 floor.
  Derivatives are cached on disk and invalidated by modification time, so the
  first export pays for the encoding and later ones don't, and a re-cut photo
  regenerates without anything having to remember to clear a cache. The whole
  zip build runs off the event loop, because re-encoding a few hundred
  full-resolution photos is a minute of Pi CPU and the app has to stay
  answerable while someone downloads.

- **Notes of your own, on every hat.** The only free-text field no automated
  path ever writes — not analysis, not a refresh, not a bulk re-analyse. Every
  other prose field on a hat is derived and gets rewritten, so the card says
  outright that this one survives.

## [2.23.1] — 2026-08-18

### Fixed
- **The case part of a hat's ID is now a link back to that case.** `A-029-01`
  reads as "hat 01 of case A-029" and sits at the very top of the page, so it
  looks like a breadcrumb and gets tapped like one. It wasn't one. The
  "View Case" button did already exist, but below the identification card, the
  photo and the specs — a long scroll back to the page you just came from.

  Only the case portion links; the `-01` stays plain text, so which part is
  navigation is visible rather than guessed. A hat with no case still renders
  `Hat #12` as plain text rather than dressing it up as something tappable.

### Documentation
- **A diagram of what happens when you add a hat.** The README now carries a
  Mermaid flowchart of the upload → queue → cutout → Claude → price-lookup
  path, including the branches that matter: the upload returning before any of
  it runs, the inline fallback when no worker is draining the queue, and the
  fact that **eBay and melinrecap only run after Claude succeeds** — both
  fallback paths return early, because without a model name there is nothing
  to look comparables up *for*.
- **The color-search description was two releases stale**, still describing
  plain "ΔE in LAB space" after 2.20 moved to CIEDE2000 and 2.22/2.23 added
  dominance weighting and the hue guard.

## [2.23.0] — 2026-08-18

### Fixed
- **Color search: a grey hat is no longer a purple hat.** Searching purple
  returned **22 of 22** hats, every one matched on a grey swatch at Δ13–19.
  2.22.0 did not fix this and neither would a third attempt at the same
  approach, because the approach was wrong.

  **A distance threshold cannot answer "is this hat purple?"** CIEDE2000
  divides the chroma difference by `S_C = 1 + 0.045·C̄` — correct for the job
  it was designed for, judging whether two nearly-identical samples of a dye
  match, and wrong for this one. A mid grey and a saturated purple differ by
  **55 units of chroma**; that divisor compresses the gap to ~22, and when
  their lightness happens to agree the pair scores **~17**. Two genuinely
  different purples score ~33. There is no cutoff that admits the second and
  rejects the first, which is exactly why lowering it from 30 to 22 in 2.22.0
  changed nothing that mattered.

  The hue question is now answered **before** distance, not with it. A swatch
  with essentially no hue is never matched against a color with plenty of
  one, at any distance.

  Deliberately **not** a general penalty on the chroma gap — that was tried
  first and it killed `navy`/`blue` (41 units apart) and `red`/`maroon` (36)
  along with the bug. Those are the dark and bright versions of one hue and
  must keep matching. What makes grey different isn't the size of the gap but
  that it has no hue to be a darker version *of*.

  The test is a **ratio** rather than an absolute chroma floor, because how
  much color counts as *some* color depends on the color. Teal is itself
  only C=27 where red is C=73, so a slate teal at C=10.5 holds **39%** of
  teal's chroma and is a teal, while the blue-grey that must not match purple
  holds **20%** of its C=59 and is a grey. An absolute floor cannot tell those
  apart — set low enough to keep the teal findable it lets blue-grey match
  purple, set high enough to stop that it discards every dark teal and forest
  green in a collection full of them.

  Worth knowing: the guard is strong for emphatic targets like purple and
  inherently weaker for muted ones. Tapping **teal** still returns some slate
  and blue-grey hats — which is fair, because teal genuinely is a desaturated
  blue-green and those are its neighbours. Tapping purple no longer does.

  Purple now returns **3** hats instead of 22: the purple one, the navy one
  and the pink one.

### Changed
- **The cutoff relaxes back to 26**, because it no longer has a second job.
  It had been tightened to 22 to suppress the neutral blowout, which cost
  real matches — `navy`/`blue` (Δ23.3) and `charcoal`/`gray` (Δ25.3) were both
  casualties. With the hue guard doing that work properly, 26 is the first
  value that keeps all 17 same-family palette pairs; 28 would start admitting
  `navy`/`maroon`. A charcoal hat is a dark grey hat again.

## [2.22.0] — 2026-08-18

### Fixed
- **Color search stops returning the whole collection.** Searching a color
  came back with everything, bunched at near-identical distances — four hats
  all reading "Δ15", the top three matched on grey and the fourth, a green
  hat, matched on its pink logo. Two causes, both mine:

  **A hat was scored on the closest of ALL its swatches, with nothing
  weighting them.** A logo counted exactly as much as the crown, and a hat
  with four colors got four chances to match anything. Every melin hat is a
  dark neutral crown with a bright accent, so searching pink ranked a green
  hat with a pink logo **equal first** — 0.00, identical to a hat that is
  actually pink — with nothing on screen explaining why.

  A hat now scores on `distance + penalty(dominance_rank)`: +0 for its main
  color, +8 for its secondary, +14 for anything deeper. Additive, because a
  multiplier leaves an exact accent match at 0.00 and breaks no tie. Accent
  matches still surface — "find the hat with the pink brim" is the point of
  the feature — but they never outrank a hat that IS the color, and the
  penalty doubles as a budget: a secondary must land within 14 of the target,
  an accent within 8.

  **The Δ30 cutoff was calibrated against the wrong distribution.** It was
  measured on the 26-color palette, whose entries are deliberately spread
  around the wheel. A hat collection is not: these are overwhelmingly black,
  charcoal, navy and grey, and CIEDE2000 places a low-chroma neutral
  moderately near *everything*. At 30, grey was a "match" for **17 of the
  other 25 palette colors** — red, orange, purple and pink included. Every
  hat owns a grey swatch, so every search returned every hat.

  Re-calibrated on the neutrals, where the problem lives, to **22**:

  | target   | within 30 | within 22 |
  |----------|-----------|-----------|
  | gray     | 17        | 4         |
  | charcoal | 11        | 5         |
  | pink     | 4         | 1         |
  | red      | 6         | 1         |

  Saturated searches barely notice — they were never the complaint. Shades of
  one color still match comfortably: a real grey crown is 8.0 from the grey
  chip, well inside.

### Added
- **Results say which swatch they matched.** A hat matched on its accent is
  labelled as such, so a row reading "Δ0 · accent" sitting below a row reading
  "Δ5" is legible rather than looking broken. `ColorSearchResult` gains
  `matched_rank`; `distance` keeps its meaning — the raw CIEDE2000 to the
  matched swatch — and is deliberately **not** the sort key.

## [2.21.0] — 2026-08-18

### Changed
- **Resale values are now real comparables, and they go UP.** Two invented
  numbers are gone: a 15% "ask-to-sold" haircut and a guessed condition
  multiplier.

  The haircut was modelling a negotiation that doesn't happen. melinrecap is a
  fixed-price Treet marketplace with automatic 10% drops — a buyer clicks buy
  at the number shown — so **the listed price is the sale price**, and
  discounting it was simply wrong.

  The multiplier was unnecessary. Every listing carries its own `condition`
  and `size` in the feed, and the code ignored both: it took one median across
  all conditions and multiplied by a guess. Measured against 706 live
  listings those guesses were also wrong — new-without-tags sells at 95% of
  new-with-tags (not 92%), worn at 82% (not 78%).

  Comparability now comes from **filtering, not arithmetic**. A hat is priced
  against listings matching its own model, condition and size, widening only
  when the market has too few of the exact thing, and the source line says
  which — "median of 11 live classic worn model listings" rather than "median
  of 8 live listings".

  Effect on a real hat, a Classic Trenches Icon Hydro, against live data:
  new-with-tags $59.50 → **$77.00**, new $54.74 → **$75.00**, worn $46.41 →
  **$63.00**. Roughly +30%, and each from 5–11 genuinely comparable listings.

### Added
- **What you'd actually receive.** Every listing carries `payoutInfo`: the
  marketplace pays a seller **80% in cash or 110% in brand credit**. Valuation
  reported only the gross figure — the one number that never reaches you.
  There's now a card showing market value, cash, credit, and what choosing
  credit is worth over cash.

389 backend + 82 frontend tests.

## [2.20.0] — 2026-08-18

### Changed
- **A case is full at 3 hats, not 4.** The physical article is a three-hat
  case — melin's own order lines call it a "3 Hat Travel Case" — so 3 is now
  what "full" means. A 4th still fits, so it is accepted and the case is
  reported **overfull** rather than refused or passed off as normal. One over
  is the whole allowance; the 5th is refused, and the 409 quotes the ceiling
  actually enforced instead of the nominal you had already passed.

  Cases hold their hats either way — nothing moves and nothing is rejected on
  upgrade. Any case you already have with 4 hats simply starts saying
  *overfull*, in the Cases grid, the case picker and the Fullest-cases chart.

  A per-case `capacity` you set yourself gets **no** overfill latitude. That
  field exists for a case you don't want to cram, so quietly allowing one more
  than the number you stated would defeat the only reason to set it.

- **Color search is much tighter.** Two separate problems:

  *No cutoff.* Only the result limit bounded it, so every hat was ranked and
  the nearest 30 came back however far away they were — searching a specific
  teal in a collection of a hundred returned thirty hats, six teal and
  twenty-four presented identically beside them. A list that always fills to
  the same length says nothing about whether anything matched. Now capped,
  calibrated against the curated palette so shades of one color still find
  each other while unrelated ones drop out. An empty result is now possible
  and the page says "no hats are close to that color" rather than "no hats".

  *Crude metric.* Distance was ΔE\*76 — plain Euclidean in LAB, which is
  least uniform among saturated blues, i.e. most of this collection. Two
  navies you'd call the same shade scored further apart than a navy and a
  slate. Now CIEDE2000, verified against all 34 published reference pairs.

  Expect a light-blue search to stop returning navies. That is the fix: a
  pale sky blue is 58 lightness points from a near-black navy, and hue family
  alone was never a good reason to call them a match.

### Fixed
- **The hat spec sheet showed the wrong things.** "Type" reported Beanie or
  Regular, which is derived entirely from Style directly above it — a quarter
  of the sheet printing one fact twice. Meanwhile **construction** appeared
  only as a badge beside the title, and **colorway** appeared nowhere on the
  hat page at all, despite a colorway catalog and a purchase matcher whose
  job is filling it in. Specs now lists Style, Size, Construction, Colorway,
  Collection and Last Worn — the fields that actually tell two hats apart.

384 backend + 81 frontend tests.

## [2.19.0] — 2026-08-17

### Added
- **Stats page (`/stats`).** Everything the collection is, as numbers and
  charts: totals, condition/style/size/brand/construction/colorway splits,
  color distribution, hats and value by room, case fill levels, acquisitions
  and spend over time, and leaderboards for most valuable, most expensive,
  most worn and best cost-per-wear. Reachable from the home page's stat rail
  and from Valuation. Charts are hand-rolled SVG/CSS for the same reason this
  app has no UI framework — a charting library brings its own opinions about
  color and type to argue with.
- **Price-paid tracking end to end.** `purchase_price` and `purchased_at` are
  now settable when you *add* a hat, not only when editing one — the receipt
  is in hand at that moment, and it was previously unreachable for anything
  bought secondhand or in person. Valuation gained a "What you've paid" card
  with totals, coverage, average, and a list of hats still missing a price.
- **Home page counts are links.** Hats, Cases and Rooms go to their lists;
  Archive and Daily deep-link into the Cases page's own type filter. The Cases
  type filter now lives in the URL (`/cases?type=archive`), the hat filters
  seed from query params (`/hats?style=a_game`), and Search accepts `?q=` and
  `?color=` — so the stats charts link straight into a filtered view.

### Changed
- **The valuation maths, substantially — read this one.** Previous totals were
  overstated. Both price feeds report *asking* prices — the eBay integration
  reads currently-listed items and the melinrecap figure is a median of live
  listings — and both were being summed at face value. Worse, whenever a
  market price existed, condition was ignored entirely: every copy of a model
  got the same number whether it was tagged or beaten. Market signals are now
  discounted 15% for the gap between ask and sale and then adjusted for the
  hat's actual condition, so headline figures will **drop**. They were wrong
  before, not now.
- **The home page caption said something the code no longer did.** It read
  "Resale = manual override, else condition-based estimate (NWT 65% · New 45%
  · Worn 30%)" long after `resale_price` had become an automatic feed, so
  almost nothing was going through the multipliers it named. Valuation now
  carries a "How the sale estimate is worked out" card that states the method
  and shows how many hats rest on each kind of signal.
- **One valuation rule instead of three.** It was implemented separately in
  the home page, the valuation page and the server's inventory report, and had
  drifted in all three. It now lives in `frontend/src/lib/valuation.ts`, with
  `src/headroom/services/valuation.py` mirroring it for the server-rendered
  report and `tests/test_valuation_parity.py` failing the build if the two
  ever disagree.
- **Home page stats are one panel, not five buttons.** Each was a bordered
  card with a gradient bar — the same recipe this stylesheet uses for a
  primary button — so they read as buttons containing numbers, left "Rooms"
  alone on a fifth row at phone width, and took nearly half the first screen.
- **The home carousel no longer glows.** It carried a pink glow and a pink
  radial behind the photo, the only lit element on the page; it now uses the
  same border, surface and shadow as every other card.
- **Hat page pricing tiles** are two-up rather than three-across (a four-digit
  price and a source line don't fit in 110px), label the feeds as *asks*
  rather than "Resale (manual)", show what you paid, and show the estimated
  sale value with a plain-English note on how it was reached.

### Fixed
- **The app's own CSP had been blocking its own fonts since 2.12.0.** The
  security headers set `style-src 'self'` and `font-src 'self'` while
  `tokens.css` still pulled Audiowide, Orbitron, Inter and JetBrains Mono from
  Google Fonts, so the entire type system was stripped and everything rendered
  in system-ui. It stayed invisible because anyone who had used Headroom
  before 2.12.0 had the fonts cached — only a new device saw it, and there is
  no visible error, just text of the wrong shape. The fonts are now bundled
  from `@fontsource*` packages, which also means the design no longer depends
  on a Google CDN being reachable from your LAN.
- **A hand-entered resale price no longer survives only by luck.** Every
  analysis of a Melin hat reset the price to null and relied on the live feed
  putting a number back; when the marketplace API was unreachable it didn't,
  and a price you had typed was gone with nothing to recover it from — on a
  path that also runs unattended from the bulk re-analyse queue. Prices you
  enter are now marked as yours, used as given, and never overwritten.
- **Cost per wear used the retail estimate** when no purchase price was
  recorded, so a hat bought on sale showed a cost per wear it never had. It
  now appears only when there is a real price to divide.
- **Unpriced hats are excluded from totals rather than counted as $0**, and
  the count of them is shown. "Retention %" is computed only across hats
  present in both totals, instead of dividing two differently-sized
  populations by each other.
- The deprecated `apple-mobile-web-app-capable` meta tag warned on every page
  load; the standard `mobile-web-app-capable` now sits beside it.

### Added — purchase import
- **Order-history import understands size.** Order emails have always carried
  it ("Transit / Classic") and the importer dropped it, so matching went on
  model name alone and bound a purchase to whichever hat came back from the
  database first. Own the same model in two sizes and a Small could be handed
  a Classic's price, with nothing downstream looking wrong because both hats
  ended up with *a* cost basis. Matching now scores candidates — size
  outranks colorway, a stated field that disagrees rules a hat out, and a
  genuine tie is reported rather than resolved by coin flip.
- **A multi-buy line now prices every hat it bought.** "× 2" is two hats and a
  purchase matches one hat, so one row per line meant the second hat of every
  multi-buy silently never got a cost basis — nearly 40% of lines in a real
  order history. Import writes one row per unit, and dedupe counts rows
  instead of testing existence, so re-importing an order still adds nothing.
- **`?dry_run=true` on `/api/admin/purchases/{import,match}`** reports exactly
  what would be imported and which hat each purchase would attach to, writing
  nothing. Importing mutates hats and there is no undo for "every price on the
  shelf is now slightly wrong".
- An explicit `colorway` in the payload now beats one parsed out of the title.
  Plenty of titles have no `" - "` to split on — "Odysea Hydro Indigo Depth"
  yields a model and no colorway, which can then disambiguate nothing.
- **Matching can be undone.** `POST /api/admin/purchases/{id}/unmatch` breaks
  one link and `POST /api/admin/purchases/unmatch-all` breaks every link,
  returning those purchases to the matching pool. Previously there was no undo
  of any kind: matching mutates hats, runs over years of order history in a
  single call, and only ever reconsiders purchases with no hat — so a wrong
  link was permanent *and* invisible, because the hat still came out with a
  price and a colorway, just the wrong ones. Fixing it meant editing the
  database by hand.

  Reverting clears `purchase_price`, `purchased_at` and `colorway` only where
  they still hold the value that match wrote. Anything edited since belongs to
  whoever edited it — a reversal that overwrote a hand-typed price would be a
  worse bug than the mis-match it was undoing. The purchase rows themselves
  survive `unmatch-all`: re-importing years of orders is the expensive part,
  and what was wrong is the matching, not the orders. Both are audited.

### Added (schema)
- `hats.resale_price_scope` — `manual` | `model` | `category`, recording what
  `resale_price` is a price *of*. A category median is the going rate for a
  whole style rather than a valuation of one hat, and valuation needs to tell
  those apart without parsing a display string.
- `purchases.size` — the size on the order line, normalised to the app's
  vocabulary. Also now part of the import dedupe key: one real order bought
  the same model at the same price in Classic ×2 *and* Small ×1, and a key
  without size collapsed the Small.

340 backend + 81 frontend tests.

## [2.18.2] — 2026-08-17

### Fixed
- **`setup.sh` now verifies the npm upgrade actually took.** It only checked
  whether `npm install -g` exited cleanly, which it can do while changing
  nothing you will run — so a setup that printed no error still left npm 11
  building the SPA against an image pinned to 12. It now re-checks the version
  afterwards and reports the mismatch immediately, rather than letting it
  surface later as a build difference.

  On a Homebrew node it says so specifically: the formula owns the `npm`
  symlink into its Cellar, so a global upgrade is undone by the next
  `brew upgrade node` and cannot be made to stick. Telling someone to re-run
  the command would send them round a loop with no exit. This is cosmetic for
  Docker deploys — the image installs its own pinned npm in the build stage —
  and only matters when building the SPA locally for a bare-metal deploy.

307 backend + 66 frontend tests.

## [2.18.1] — 2026-08-17

### Fixed
- **`BUILD_SHA` works again as a name for the build stamp.** v2.0.0 renamed the
  build arg to `HEADROOM_BUILD_SHA` and listed it as breaking — but a build arg
  that doesn't match simply arrives empty, with no warning, so a command using
  the old name kept working and silently stopped stamping. The old name is
  accepted as a fallback.

- **Docs: upgrading with an overlay.** `## Upgrades` said
  `docker compose up --build -d`, which on a host running `http80` (or `mdns`,
  or either HTTPS overlay) is not an upgrade — compose applies only the files
  named, so the sidecar never starts and the app drops back to `:8000`. Now
  states plainly that upgrades must repeat the same `-f` flags, with a worked
  example.

- **Docs: the build stamp was undocumented.** Neither README nor OPERATIONS
  explained why the footer shows no build or how to make it — the one place it
  appeared was a compose comment. OPERATIONS §5 now covers it, including that
  a dirty tree is stamped `-dirty` and that no stamp is not an error.

### Changed
- `scripts/stamp-build.sh --install-hooks` installs the git hooks on its own,
  so a running deployment can pick them up without re-running `setup.sh` —
  which installs Docker, Node and the Python toolchain. `setup.sh` now
  delegates to it rather than carrying a second copy.

307 backend + 66 frontend tests.

## [2.18.0] — 2026-08-17 — _seen it twice_

### Added
- **Find duplicates** (`/duplicates`, linked from Search). Bulk import from a
  camera roll is how this happens: two photos of one hat become two rows that
  both analyse plausibly, and at two hundred hats you don't notice — the
  collection quietly reports more than you own, which flows into the valuation.

  Grouped on identity fields, never pixels: two shots of one hat look different
  enough to defeat image comparison, and two genuinely different hats in the
  same colorway look nearly identical, so photos are the wrong signal in both
  directions. `exact` means every identity field agrees; `likely` means same
  model and size with the colorway missing on one side, which is the usual
  shape of an unanalysed twin.

  Colorways that actively **disagree** are never grouped — "Trenches Black"
  and "Trenches Navy" are two hats somebody deliberately owns, and reporting
  every normal shelf as a mistake is the fastest way to make a report like this
  get ignored. Reports only: nothing is deleted or merged.

- **The three most recently created cases are pinned to the top** of the case
  picker. A hat you're adding now usually belongs in a case you made minutes
  ago, and hunting for it inside a room group is the long way round. Hidden
  once you start typing — at that point you've said what you want, and a
  pinned block is noise in front of the answer.

- **Cases show a collage of the hats inside**, not a photo of the case. Every
  case looks identical from the outside, so that picture carried no
  information at the moment you were scanning for one. The layout follows the
  count — one hat fills the tile, three put the first across the top — rather
  than letterboxing a single hat into a quarter of a forced 2x2.

### Fixed
- **Dropdown lists were being clipped by the card they sat in.** `.card` sets
  `overflow: hidden`, so options past its edge were cut off mid-row and the
  ones below unreachable — no z-index could fix that, because the pixels were
  never drawn. The lists now render into `<body>` via the existing
  `portalToBody`, whose own docstring names this trap, positioned against their
  input. That also clears the two other ancestor traps: `.card-body`'s stacking
  context and the card hover `transform`.

- **The bottom nav no longer jumps to the middle of the screen.** iOS positions
  `fixed` elements against the *visual* viewport, so the nav is lifted with the
  keyboard and lands on top of whatever you're typing into. 2.14.0 hid it while
  a combobox was open, which missed the actual cause: it happens for every
  focused input, including plain dropdowns. Now tracked app-wide via
  `visualViewport` — the only API that reports a keyboard, since no `window`
  resize event fires for one.

- **Picker lists no longer run off the bottom of the screen.** They were sized
  against the layout viewport; with the keyboard up that's roughly double the
  visible area, so the last options were unreachable. Sized in `dvh` now.

- **The footer shows the build again.** `.dockerignore` excludes `.git` and the
  frontend build stage only receives `frontend/`, so nothing inside the image
  could ever learn the commit — and the compose build arg defaulted to empty,
  so `docker compose up -d --build` always produced an unstamped image.
  `scripts/stamp-build.sh` writes it to the `.env` compose already reads, and
  `setup.sh` installs git hooks so a `git pull` keeps it current. A working
  tree with uncommitted changes is marked `-dirty`, so a stamp can be trusted
  to mean exactly that commit.

- Search results now carry `thumb_path`, so the results grid loads thumbnails
  instead of full-size transparent PNGs.

307 backend + 63 frontend tests.

## [2.17.0] — 2026-08-17 — _it already knows_

### Fixed
- **Your construction is now sent to Claude as ground truth.** 2.12 stopped
  analysis *overwriting* a construction you had stated, but never told it what
  you'd said — so a hat you recorded as Thermal still came back named
  "A-Game HYDROLite". The construction field was right and the name you
  actually read was wrong, which reads as the app overruling you.

  The prompt now states both the model line and the construction as facts from
  someone holding the hat, and binds `model_name` to agree with them. HYDRO vs
  HYDROLite vs Thermal turns on bonded seams, a gel-welded logo and the
  sweatband — none reliably legible in one photo — so a guess there is weak
  evidence against your direct observation.

- **A full rescan repairs the hats that already got this wrong.** melin names
  read "&lt;line&gt; &lt;construction&gt;", so a model name asserts a build by itself.
  Any name that contradicts the hat's recorded construction now has the wrong
  build removed on every analysis — so re-running analysis over the collection
  fixes stored rows instead of preserving them, including when Claude returns
  no model name of its own.

  Removed, not rewritten: "A-Game Thermal" would be inventing a product name,
  where "A-Game" is merely less specific and true.

299 backend + 63 frontend tests.

## [2.16.0] — 2026-08-17 — _one Piña_

### Changed
- **Accents fold too.** 2.15.0 deliberately kept "Piña" and "Pina" apart, on
  the theory that two names differing only by a diacritic might genuinely be
  different collections. In this collection they aren't — they are one drop
  typed with and without a long-press on a phone keyboard, and the concrete
  harm is three entries that never find each other in search. `Piña`, `Pina`
  and `PINA` are now one collection.

  When variants disagree the **accented** spelling wins: adding an accent is a
  deliberate act, while dropping one is what happens when you type quickly, so
  it is the better guess at the real name. Typing `Piña` where only `Pina` is
  on record therefore keeps the accent, and the one-time merge pulls the older
  rows across.

  On write, the value already on record still wins a *tie* — otherwise typing
  `NEON` once would rename a collection recorded as `Neon`. It only loses when
  the typed value is strictly better informed.

### Fixed
- Matching moved from SQL to Python. It was a `WHERE lower(col) = lower(?)`,
  and SQLite's `lower()` is ASCII-only: it cannot fold accents, so `Piña` and
  `PIÑA` did not even match *each other*, let alone `Pina`. The candidate set
  is the distinct values of one column on a personal collection — a few dozen
  short strings — so comparing in Python costs nothing and is actually correct.

296 backend + 63 frontend tests.

## [2.15.0] — 2026-08-17 — _one Neon_

### Changed
- **The collection field autocompletes**, like construction — suggestions come
  from `GET /api/meta/collections`, the names already in use. No curated list:
  melin names these for the partner or the drop, so any fixed list is wrong by
  the next release.

- **Typing past a suggestion no longer creates a duplicate.** Autocomplete only
  makes drift *less likely*; a value that case-insensitively matches something
  already recorded is now stored with the existing spelling, so "Neon", "NEON"
  and "neon" converge on one collection instead of three that never find each
  other in search. Applies to `construction` too, where the curated list wins —
  typing "hydrolite" stores "HYDROLite".

  Case and whitespace only. "Piña" and "Pina" stay distinct: collapsing accents
  would be guessing, and merging two collections that genuinely differ is worse
  than keeping two spellings of one.

### Added
- **A one-time merge for variants that already exist.** Canonicalisation covers
  writes, so anything recorded before it — or imported — keeps whatever was
  typed. Runs once on boot behind `vocabulary_merged_v1`, keeping the curated
  spelling where there is one and otherwise the most *common* variant, so a
  single early typo can't rename the collection everything else uses.

294 backend + 63 frontend tests.

## [2.14.0] — 2026-08-17 — _sixty cases_

### Changed
- **The case selector is a searchable picker.** A native `<select>` is fine at
  six cases and unusable at sixty: iOS renders it as a picker wheel with no
  search, so finding one case means spinning past the rest. Type to filter on
  case id, room name or type; cases are grouped under their room with
  occupancy shown.

- **It won't let you pick a case the save would reject.** Cases are
  type-exclusive (beanies or regular hats, never both) and capacity-limited, so
  the old dropdown happily offered a case that came back `409` — at six cases
  you notice, at sixty you won't. Full and wrong-type cases now render dimmed
  and unselectable with the reason ("full", "holds beanies"), rather than
  hidden: a case you expected to see silently missing is its own puzzle, and
  *"A-021 is full"* is the answer you actually wanted.

  Availability is computed server-side in `services/capacity`, the same module
  `_validate_capacity` now uses to enforce it, so the picker cannot disagree
  with what a save will accept.

### Fixed
- **The bottom nav no longer covers an open picker.** It is `position: fixed`
  at `z-index: 100`, above the list — and once the iOS keyboard opens, fixed
  elements are positioned against the visual viewport, so the nav rode up to
  mid-screen and covered the options wherever they were drawn. Raising the
  list's z-index alone does not fix the second half; the nav is now hidden
  while a picker is open, which is also what it should do when the keyboard is
  up and it is unreachable anyway.

- **Case occupancy counted disposed hats.** A disposed hat stays in the
  database but frees its slot — `_validate_capacity` has always filtered them,
  but the read model did not, so a case could display as fuller than the
  validator considered it. With the picker now greying out full cases, that
  discrepancy would have hidden a case you could actually use.

283 backend + 63 frontend tests.

## [2.13.0] — 2026-08-17 — _one place for each thing_

The layering and traceability findings the 2.12.0 release deliberately left,
plus the test gap that let the crash class stay invisible.

### Changed — the layering

- **`share_links.py` has a service layer.** It was the only feature that lived
  entirely in the transport layer — hand-rolled persistence, token-expiry
  rules, and a second copy of the path-traversal check `app.py` already had.
  That put the one surface reachable *without* a session in the hardest place
  to test. Now `services/share_link_service.py` owns token validity and what a
  token may see; the route is transport only.
- **One definition of path containment.** `utils/paths.py::safe_join` is now
  the single implementation, used by the SPA fallback and the share-photo
  streamer. Both copies were correct — which is the problem: two correct copies
  of a security check are two places that must both be fixed when it is wrong,
  and one of them gets missed.
- **No more hand-built dict responses.** `schemas/share.py`,
  `schemas/import_job.py` and `PurchaseRead` replace them, so the public share
  view and the purchase list have declared shapes and appear in the OpenAPI
  document. The shared-collection payload is deliberately a projection, not
  `HatRead` — prices, purchase history, disposition and analysis state are the
  owner's business, and returning the full model while trusting the frontend
  not to render the rest is exactly how that leaks.
- **`schemas/auth.py`** holds the five models `routes/auth.py` declared inline
  — the request bodies on the unauthenticated surface, whose validation rules
  should be readable without opening the transport layer.
- **Admin routes go through `hat_service`**, via `list_by_analysis_status`,
  `count_by_analysis_status` and `ids_for_reanalysis`, rather than querying
  `models.Hat` directly.
- **`Purchase.hat` is a real relationship**, not a bare foreign key every
  caller had to navigate by hand.
- **The colorway harvest runs in the background** and returns `202`. It is up
  to 9 categories × 50 pages of sequential external calls — minutes of work
  inside a request, on an open connection, long enough for any reverse proxy
  in front of it to time out first.
- The three analysis/queue response types moved from `api/settings.ts` to
  `types/index.ts` with every other API shape.

### Added — tests for what the stub was hiding

`tests/test_memory_bounds.py`. The suite stubs `remove_background` out entirely
— rembg's model is 179MB — and that stub is why the crash class stayed
invisible: every precondition sat in the code, green, for releases. The bounds
are plain control flow, so they can be tested without the model. Removing the
semaphore now fails with *"4 inferences ran at once; the bound is 1"*, which is
precisely the pre-2.12 state.

Covers the inference bound and its env override, a bad config value falling
back rather than deadlocking, all three photo routes rejecting oversize before
Pillow decodes anything, a normal photo still working, and bulk import handing
the worker paths rather than bytes.

### Fixed

- `copy_upload_capped` bound its limit at import (`cap: int = MAX_PHOTO_BYTES`),
  so it could never be changed — and an untestable limit is how the last one
  went missing.
- **`docs/AUDIT-HISTORY.md`** records what `R8`, `S2/R9`, `S5/R10`, `S4/S10`,
  `S9/R6` and `R11` actually said. Ten of twelve in-code citations pointed at
  documents that were never committed; a permanent reference to something
  nobody can open is worse than none, because it implies a rationale exists to
  be checked.

### Fixed — the memory limit was being ignored on Pi

Raspberry Pi OS ships with the memory cgroup disabled, so Docker printed
*"Your kernel does not support memory limit capabilities ... Limitation
discarded"* and dropped 2.12.0's `mem_limit` on the floor. The in-app bounds
(upload caps, inference semaphore) were unaffected, but the container ceiling —
the thing that turns a system-wide OOM kill into a diagnosable
`OOMKilled=true` — was not actually in force.

`docs/OPERATIONS.md` §7 now has the one-time fix (`cgroup_enable=memory
cgroup_memory=1` in `cmdline.txt`, reboot), how to verify it took, and how to
tell a memory kill from a Pi brown-out — undervoltage and thermal throttling
during rembg's CPU burst produce an identical sudden death with no logs.

280 backend + 61 frontend tests.

## [2.12.0] — 2026-08-17 — _the owner wins_

A full-repo archaeology pass produced ~45 findings; this is all of them, plus
the two things 2.11.0 got wrong in front of the owner.

### Fixed — the crash

Three independent analyses converged on why the container died mid-upload, and
every structural precondition was confirmed in code:

- **The single-hat photo upload had no size cap at all** — bulk import caps at
  20 MB/file, the route you actually use capped nothing, and Pillow decodes at
  native resolution before the resize. Now capped, streaming, along with the
  case-photo and logo routes. One definition in `utils/upload.py`, used by all
  four.
- **No compose file set a memory limit**, so a spike competed for the whole Pi
  and the kernel picked a victim — possibly sshd — with `SIGKILL`, which logs
  nothing. `mem_limit`/`memswap_limit` default to 1g (`HEADROOM_MEM_LIMIT`), so
  a recurrence is a scoped, diagnosable `OOMKilled=true` against this container.
- **rembg ran unbounded across both workers.** The lock was removed for
  throughput; with only two single-consumer producers that bought a factor of
  two and cost double the peak memory, for the largest allocation the process
  makes. Now a semaphore, default one (`HEADROOM_REMBG_CONCURRENCY`).
- **On-demand backup download buffered the entire tarball in RAM** — the whole
  database plus every photo — and called itself streaming. Now spooled to disk
  and streamed in 1 MB chunks.

### Fixed — the backup scheduler

**It could die once and stay dead for the life of the process.** The startup
age-check ran above its own `try`, and only `CancelledError` was caught inside
it — so one unwritable `/data` at boot, or a single transient
`database is locked`, ended automated backups with no warning while the UI kept
listing the last successful one. The loop now survives everything short of
cancellation, and `GET /api/admin/backups/health` reports last attempt, last
success, consecutive failures and whether the task is still alive — the file
list cannot answer that, since a scheduler dead for weeks and one that ran
minutes ago produce an identical inventory.

A backup that fell back to the raw-file copy (possibly torn) was
byte-indistinguishable from a clean snapshot; it now carries a
`DEGRADED-BACKUP-README.txt` inside the archive, because a file travels with
the backup and a log line does not.

### Changed — analysis no longer overrides you

**Claude only fills a construction that is empty.** 2.11.0 let a named fabric
overwrite what was on record. In practice it reads HYDRO vs HYDROLite off one
photo unreliably — the tells are bonded seams, a gel-welded logo and a
sweatband, none of which survive a front-on shot — so "correcting" meant
replacing a right answer from the person holding the hat with a wrong one from
a picture. Clearing the field makes it eligible again.

`scripts/restore-construction.py` restores values from a backup for hats
already overwritten. Hat edits now record their **previous values** in the
activity log, so this class of change is reversible from history rather than
only from a backup.

### Fixed — 2.11.0 regressions

- **Construction is a real autocomplete**, not a bare `<datalist>` — iOS
  renders those as a thin strip above the keyboard that is easy to miss, so ten
  known values read as a blank text box. Known builds are now visible, tappable
  rows that filter as you type, and anything typed is still accepted.
- **The analysis badge shows the step name again**, alongside the counter:
  `2/4 · Identifying`, one word so it still fits a phone.
- **Edit is in the top action row** on a hat, not only at the foot of the page
  below the colors and disposition sections.
- A legacy client sending `hydro: false` no longer wipes a construction the
  booleans cannot express (a "Waxed Canvas" hat has both flags false already).

### Fixed — correctness

- A photo replaced mid-analysis raised an uncaught `FileNotFoundError` past the
  pipeline's error handling; the queue then stamped the hat `error` and the
  correctly-queued run for the NEW photo found a non-pending status and
  silently did nothing. The correction was dropped permanently. Same shape in
  `google_vision.py`.
- A per-case capacity of exactly `0` fell through to the type default via
  truthiness, letting four hats into a case set to hold none.
- `undispose_hat` restored a hat into a case that may have been deleted.
- `reattach_orphaned_cases` now calls `ensure_default_room` itself rather than
  depending on boot ordering — with no default room its subquery returns NULL
  and it would set every orphan's `room_id` to NULL, making permanent the exact
  state it repairs.
- The activity-log prune slept 24h **before** its first run, so a host that
  reboots daily never pruned at all. It now prunes first, and also sweeps
  expired auth sessions — which were only ever collected lazily, when that
  exact cookie was presented again, so abandoned ones accumulated forever.
- `hat_service`'s six mutating functions committed twice with no shared
  transaction, so a lock timeout on the audit write turned an already-durable
  change into a 500 and invited a duplicate retry.
- Bulk import queued with no worker running now says so instead of sitting at
  0%.

### Added — security & audit

- CSP, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` on
  every response. No HSTS from the app deliberately: the primary deployment is
  `http://` on a LAN, and one HSTS response would pin that hostname to HTTPS in
  the browser and lock the owner out.
- Unauthenticated API probes are logged (login was rate-limited and audited;
  every other endpoint was silent). Never with the credential.
- Case and room mutations are audited — previously only hats, auth, settings,
  backups and share links were.

### Fixed — documentation and naming

- `HatAnalysis.construction` still described the pre-2.11 three-value enum,
  100 lines below the schema that contradicts it.
- `package.json` declared `engines.node >=22.12`, the exact floor `setup.sh`'s
  own comments call insufficient; react-router 8 needs `>=22.22`.
- `CLAUDE.md`'s search field list and `USAGE.md`'s status-pill table were both
  behind the code.
- `melin_recap`'s `_STYLE_TO_CATEGORY` / `_query_listings` are public — a
  second module already depended on them, so the underscore was a lie.
- The two `apiFetch` calls bypassing `api/hats.ts` now go through it.
- `uploads/branding/logo.png` was git-tracked inside an otherwise-ignored tree,
  byte-identical to `seed/branding/logo.png`.

272 backend + 61 frontend tests.

## [2.11.0] — 2026-08-17 — _what the tag says_

### Added
- **Construction is now free-form, with structured suggestions.** It was two
  booleans, HYDRO and HYDROLite, so a hat in any other fabric could not be
  recorded at all — melin ships specialty materials in seasonal and collab
  drops, and every one of them was unrecordable until somebody shipped a
  migration. The field is now text with a datalist: the common builds are one
  tap, anything else you type is stored verbatim, and
  `GET /api/meta/constructions` merges the curated list with every value
  already in use, so a fabric typed once becomes a suggestion after that.

  `hydro` and `hydrolite` survive as columns, because search filters query them
  and a `@property` cannot appear in a `WHERE` clause — but they are now
  *derived*, with `Hat.set_construction()` the only writer of all three. That
  is what stops a hat reading "Thermal" from still matching a HYDRO filter.
  Existing rows are backfilled from their flags on boot.

- **Collection / collab can be set when adding a hat**, not only when editing
  one. It is printed on the box and the hang tag and is frequently invisible in
  a photo of the hat, so the owner knows something the analyser cannot see —
  and withholding the field until the Edit form meant either a second trip or
  hoping Claude guessed. Anything typed still survives a re-analysis.

- Searching a fabric name finds it: `canvas` now returns a Waxed Canvas hat.

### Changed
- **The analysis badge is a step counter (`2/4`), not a spinner.** It used to
  spell the step out — "Removing background…" — which wrapped onto a second
  line on a phone and pushed the badge row down into the photo, and because the
  wording changed every few seconds the layout moved while you were reading it.
  The counter is fixed-width and monotonic; the step name moved to the tooltip
  and the accessible label. The ring it replaces was also missing
  `flex-shrink: 0`, so a squeezed flex row rendered the 10px circle as an egg.

- **Claude may now correct a construction it can identify.** It was
  additive-only, which was right when the field was two booleans and there was
  no way to distinguish "this is not HYDROLite" from "I can't see whether it
  is". Naming a fabric is a positive identification, so it wins; a null still
  changes nothing, and the old enum's "standard" is treated as the non-answer
  it was rather than written down as if it were a material.

### Fixed
- A stale comment on `Hat.analysis_stage` claimed the column is "cleared when
  the run finishes". It never was — `HatRead` masks it instead, deliberately,
  so that eight terminal-status call sites can't each forget to.

259 backend + 54 frontend tests.

## [2.10.0] — 2026-08-16 — _watch the run_

### Added
- **Bulk re-analysis is now a tracked job.** Firing "Re-analyse every hat" used
  to leave you watching a backlog number tick down, with no record that a run
  had happened at all. The Analysis Queue card now shows a progress bar with
  **X of Y**, how long ago it started, a running failure count, and a short
  history of recent runs — enough to answer "did the last one finish, and did
  anything fail?"

  **Progress is derived, never accumulated.** The analysis worker drains hat
  ids and knows nothing about jobs; making it bump a counter per hat would mean
  two writes per item, and a crash between them would leave a progress bar
  permanently disagreeing with the hats it describes. So a job stores only what
  cannot be recomputed — its size and start time — and everything else is a
  COUNT over `hats.analysis_job_id`. That is right by construction, including
  after a restart mid-run.

  A job closes itself once nothing tagged with it is still pending, which is
  computed when the card asks. That keeps the worker ignorant of jobs at the
  cost of a finished job staying "running" until something looks at it — and
  the only thing that reads it is the thing looking.

246 backend + 47 frontend tests.

## [2.9.0] — 2026-08-16 — _redo the cutout, shrink the gallery_

### Added
- **Redo cutout.** The pre-cutout JPEG is now kept instead of being deleted the
  moment rembg succeeded, and the hat page grows a **✂ Redo cutout** button.
  This was the gap behind "my existing hats still look wrong": the stored PNG
  can never be re-segmented — running rembg on an already-transparent image
  eats the alpha and trims the bill a little more each pass — so without the
  original, a poor cutout could only be fixed by re-uploading the photo.

  Implemented by pointing `photo_path` back at the original and queueing, so
  the pipeline sees a `.jpg`, cuts it, and overwrites the old PNG in place. It
  is the upload path run again, with nothing special-cased. Hats analysed
  before this release have no original; the button is hidden for them and the
  endpoint says so rather than failing obscurely.
- **Gallery thumbnails.** A 320px WebP derivative is generated alongside every
  cutout, and the small-tile views (Hats grid and list, Valuation, case detail)
  use it. Measured on a representative 1200px RGBA cutout: **1728 KB → 4.5 KB**,
  so a fifty-hat gallery drops from ~84 MB to ~0.2 MB over the wire, with far
  less decoded bitmap in phone memory. WebP specifically because these are
  transparent — a flattened JPEG thumbnail would put a box behind every
  floating hat.

  Existing hats are backfilled by a background task on startup, off the boot
  path (it is image work over every photo, which would visibly delay the app
  becoming reachable on a Pi) and idempotent, so a restart mid-run resumes.
  Tiles fall back to the full photo until the backfill reaches them.

### Fixed
- **Replacing a hat's photo left its derivatives behind.** Only the cutout was
  deleted, so the old original and thumbnail stayed on disk — and a stale
  `thumb_path` would have shown the *previous* hat in the gallery.

244 backend + 44 frontend tests.

## [2.8.1] — 2026-08-16 — _say what it's doing_

### Fixed
- **The 2.8.0 price anchors were incomplete, and one number was invented.**
  They covered whatever products turned up in a search rather than the model
  lines the app actually enumerates — Trenches, which is in the prompt's own
  list, had no anchor at all — and the stated "$59–$99 band" had no data point
  at $59 behind it.

  Re-researched properly. The finding that matters: **construction drives the
  price, not the model line.** A-Game Hydro, Coronado Anchored Hydro and
  Trenches Icon Hydro are all $69, which is why Trenches never needed its own
  anchor — but **HYDROLite is the premium tier at $89–$99** and had no mention
  at all, despite `hydrolite` being a flag the app already tracks. The prompt
  now carries HYDRO ($69, up to $89), HYDROLite ($89–$99, explicitly priced
  *above* HYDRO), Thermal ($79–$99) and beanies (~$79), tells Claude to read
  the construction rather than the model line, and puts the floor at $60 where
  the evidence actually is. A test pins the anchors so a future prompt edit
  can't quietly drop them.

### Added
- **The analysing spinner now says which step is running** — "Removing
  background…", "Identifying the hat…", "Checking prices…", "Checking resale…"
  — instead of a bare "Analyzing…" for the whole multi-minute run. The queue
  card shows it too, which is what separates the hat actually being worked on
  from the ones queued behind it.

  The stage is written from a **separate** short-lived session rather than by
  committing the pipeline's own. That matters: the pipeline sets `photo_path`
  early and commits only at the end precisely so the queue can throw the whole
  run away if the photo was replaced mid-flight, and a mid-pipeline commit
  would persist that stale path and defeat the guard. It is also not the
  write-lock hazard `no_autoflush` protects against — this takes the lock and
  gives it straight back, before the slow call starts.

  A stage is never shown on a finished analysis. That is derived in `HatRead`
  rather than cleared at each terminal transition: eight separate places set a
  terminal status, and any one of them forgetting would leave a confident label
  on work that had stopped.

237 backend + 44 frontend tests.

## [2.8.0] — 2026-08-16 — _see the queue, fix the prices_

### Fixed
- **Estimated retail was coming in about half of actual.** The prompt asked
  Claude to price hats "using your knowledge of the brand's typical pricing
  tiers" and gave it nothing to anchor on, which for melin meant guesses around
  $35 against real retail of $59–$99. The system prompt now carries verified
  current prices — A-Game Hydro $69, Coronado Anchored Hydro $69, All Day
  Beanie $79, Hydro Odysea Mac $89, Hydro Eagle $89 — plus rough tiers for the
  other brands it knows, and an explicit note that sub-$50 for a melin is
  almost certainly wrong.
- **Rooms page cards jumped around.** "Make default" was *hidden* on the
  default room while Delete was only *disabled*, so cards carried different
  numbers of buttons; with `flex-wrap` some wrapped to a second line and others
  didn't, giving the list ragged heights that re-flowed whenever the default
  moved. Same three buttons on every card now, in a fixed two-row layout, with
  the case count aligned right instead of stacked under the name.

### Added
- **Analysis Queue card in Settings.** The queue was invisible — a hat showed
  "Analyzing…" with no way to tell whether twenty were ahead of it or whether
  anything was draining the queue at all. Shows the backlog, whether the worker
  is running, and the hats currently waiting (each linking to its page). Polls
  only while there's something to watch. A backlog with a stopped worker is
  called out explicitly, because that's the state where nothing will happen
  until a restart.
- **Re-analyse every hat**, from the same card. This is the retroactive half of
  any change to identification or pricing: the anchors above only affect hats
  analysed after them, so without this a collection keeps whatever the old
  prompt produced. Background removal is skipped for stored cutouts, so it's a
  Claude call per hat rather than the full pipeline — and your cutouts are not
  touched. Disposed hats are excluded, and "leave hand-entered prices alone"
  (on by default) limits it to hats Claude priced.
- `GET /api/admin/analysis/queue` and `POST /api/admin/analysis/reanalyze-all`.

235 backend + 44 frontend tests.

## [2.7.1] — 2026-08-16 — _give the bill back_

### Fixed
- **2.6.2's ghosting fix was deleting hat bills.** That release hardened the
  cutout with rembg's `post_process_mask`, which blurs the mask and then
  thresholds it at 127. It did remove the washed-out look — by throwing away
  every pixel the model was less than ~50% confident about, which on a hat is
  precisely the thin bill. Measured against a synthetic brim: at confidence 128
  about 76% survives, at 120 that collapses to 6%, and by 40 the brim is gone
  entirely. So a faint bill became no bill — the same symptom as the
  low-capacity model we switched away from, arriving by a different route.

  Replaced with an alpha *ramp* instead of a threshold: clearly-background
  pixels still go to zero, but anything above that is scaled up to opaque
  rather than judged against a cutoff. A brim the model saw at 39% opacity now
  comes out at 73% — present and solid, instead of ghosted or deleted. Both the
  fading and the missing bills are addressed by the same change.

  Verified against the mechanism (mask confidence in, alpha out) rather than a
  photo, and mutation-checked against both failure modes: reverting to the
  threshold and removing the hardening each fail the test.

  **This applies to photos processed from here on.** Existing cutouts are
  unchanged — the pre-cutout original is not retained, so there is nothing to
  re-cut from. Re-upload a hat's photo to regenerate it.

230 backend + 44 frontend tests.

## [2.7.0] — 2026-08-16 — _the code review release_

A full two-axis review of the codebase (standards + spec) plus wiring, bug and
optimization passes. Everything below was found by that review; nothing here
was reported from use.

### Fixed — data loss and silent truncation

- **Backups omitted the write-ahead log.** The DB runs in WAL mode, so commits
  live in `headroom.db-wal` until a checkpoint folds them into the main file —
  and the tarball contained only the main file. Every commit since the last
  checkpoint was silently absent from the backup, and a checkpoint landing
  during the tar read could produce a torn copy that restores as "database disk
  image is malformed". Both are invisible until a restore. Backups now ask
  SQLite for a proper snapshot (`VACUUM INTO`), which folds in the WAL and
  writes one self-contained file without blocking writers; if that fails it
  falls back to the raw file set *including* the `-wal`/`-shm` sidecars. The
  regression test is stark — with a plain file copy the restored DB doesn't even
  have the table.
- **The hat list stopped at 50.** `GET /api/hats` defaults to `limit=50` and the
  Hats grid, Home carousel and Valuation page all fetched with no limit. Past 50
  hats the grid silently hid them and **every valuation total was wrong**. Those
  three views now request the whole collection explicitly (`listAllHats`), and
  the API ceiling was raised to match.
- **Re-analysis could overwrite a photo you'd just replaced.** The worker held a
  hat for minutes, then wrote back a `photo_path` from before the replacement,
  orphaning the new photo and leaving it unanalysed. The result is now discarded
  if the committed photo changed while the pipeline ran.
- **A hat could sit "Analyzing…" forever.** With the worker disabled there is no
  boot sweep either, so an inline pipeline failure stranded `analysis_status`
  on `pending` with no endpoint able to clear it. Both paths now stamp a
  terminal status.

### Fixed — behaviour

- **New cases ignored the default room, and could be orphaned outright.** The
  frontend hardcoded `room_id: 1` regardless of what the picker showed,
  bypassing the `is_default` flag entirely. Delete the room that happened to be
  id 1 — which that flag exists to permit — and every case created afterwards
  pointed at a room that wasn't there. The symptoms never named the cause: the
  case reported its room as **"Unknown"**, and the room it should have been in
  reported **zero cases**. Three fixes: the picker now defaults to whichever
  room actually carries the flag; `POST /api/cases` rejects an unknown
  `room_id`, as does `PUT /api/cases/{display_id}` — nothing below that
  layer enforces it, there is no `PRAGMA foreign_keys`, and editing a case's
  room is the path used to *repair* an orphan; and
  **existing orphans are reattached to the default room on boot**, alongside
  the `ensure_default_room` check that guarantees there is one.
- **"Cancel" in the photo cropper uploaded the photo.** Cancel, ×, and a stray
  tap on the backdrop were all wired to "use the original", so on the hat page a
  mis-tap replaced the photo and re-ran the pipeline. Cancel now cancels;
  skipping the crop got its own **Use Original** button.
- **Editing a hat discarded what you were typing.** The form re-seeded from the
  server on every refetch, and since 2.6.0 the row changes *while you edit it* —
  so a completing analysis reverted your fields mid-sentence. It now seeds once
  per hat.
- **The hex field couldn't be typed into.** It only accepted input that already
  matched a complete 6-digit value, so every partial keystroke was rejected and
  the box snapped back. You could paste; you could not type.
- **The Home carousel could crash the page.** The active index was never clamped,
  so a list that shrank under it (a hat disposed elsewhere, then a refetch) threw
  and dropped the whole page to the error boundary. It also reshuffled on every
  poll, making the visible hat jump at random.
- **Case occupancy went stale.** Disposing, deleting, adding or re-assigning a
  hat invalidated `['hats']` but not the case-shaped views, so the Cases page and
  case detail kept showing the old contents. All hat mutations now go through one
  `invalidateHatViews` helper.
- **Bulk Import dead-ended on a bad `?job=`.** The upload form is hidden whenever
  a job id is set, so a stale link showed a header and nothing else — while
  polling the 404 every two seconds forever. The error is now shown with a way
  out, and a cancelled job gets an exit button like a finished one does.
- **`hydro` / `hydrolite` searches found nothing.** USAGE promised "`hydro` finds
  every Hydro", but 2.6.0 moved them from `style` values to boolean columns that
  no text match could reach. Both terms match their flag again, and search now
  also covers `artist_series`.
- **Case detail ignored a per-case capacity override**, showing "3/4" for a case
  limited to 3 and inviting an add the API then rejected.
- The login page redirected during render; three-column price tiles never became
  thirds because `.col-4` was used but never defined (along with four other
  utility classes); the settings error-list refresh left the nav badge stale;
  camera images were pinned in memory for the life of the SPA.

### Performance

- **`GET /api/rooms` loaded the entire collection to produce a case count.**
  `selectinload(Room.cases)` cascades through mapper-level eager loads into
  every hat, color and wear-log row — measured 30ms vs 0.3ms for the COUNT that
  replaces it, on a machine several times faster than a Pi.
- Color search converted the target color to LAB once per stored swatch
  instead of once per search.

### Changed

- `logo_detected` aside, analysis no longer erases `brand` / `model_name` /
  `artist_series` (shipped in 2.6.1, noted here for completeness).
- Shutdown no longer aborts if a background task had already died holding an
  exception — the import and analysis workers were left running and mDNS never
  sent its goodbye packets.
- `analysis_queue._queue_depth` / `_mark_failed` are now public
  (`queue_depth` / `mark_failed`); `/health/ready` no longer reaches into a
  private name.
- Removed dead code: the `custom_style_detail` column (unread since the initial
  commit), and three uncalled functions. Existing databases keep the column;
  it is simply no longer mapped.
- Docs no longer quote test counts. That claim has now gone stale twice, so the
  suite is the source of truth and the per-release number lives here.
- `nanoid` bumped to 3.3.18 (GHSA-2v37-7h3g-55p8, build-time only via
  vite → postcss).

229 backend + 44 frontend tests.

## [2.6.2] — 2026-08-16 — _hats that keep their brims_

### Fixed
- **The Docker image was still being built with `u2netp`.** 2.6.0 changed the
  code default to `isnet-general-use` because `u2netp` trims hat bills, but
  `docker-compose.yml` passed `REMBG_MODEL: ${REMBG_MODEL:-u2netp}` as a build
  arg — which bakes the model into the image *and* sets
  `ENV HEADROOM_REMBG_MODEL=u2netp`, beating the code default. So the
  documented install path (`docker compose up -d --build`) never got the fix,
  and the README table still advertised the old default. Compose now defaults
  to `isnet-general-use`; `REMBG_MODEL=u2netp docker compose up -d --build`
  remains the escape hatch, and README matches.
- **Cutouts rendered faded / "ghosted".** Background removal took the model's
  raw mask, so mid-confidence regions came through as semi-transparent alpha
  and the hat looked washed out over the near-black canvas. `remove()` now runs
  with `post_process_mask=True`, which opens the mask, blurs it and thresholds
  at 127 — every pixel ends up fully opaque or fully clear. The blur runs
  before the threshold, so the silhouette stays smooth instead of going jagged.
- **Re-analysis destroyed the cutout a little more each time.** A queued
  Reanalyze called `finalize_hat_photo`, which always ran background removal —
  and for a stored `hats/x.png` the output path resolves to the *input file*.
  rembg re-segmented an already-transparent image and wrote it back over the
  only copy, so every tap ate further into the alpha and trimmed more of the
  bill. Background removal is now skipped when the input is already a cutout;
  uploads are normalised to JPEG first, so a `.png` here can only mean
  "already cut out". This is what made the fading progressive.
- **Navigation kept the previous page's scroll position.** Saving a hat and
  tapping through to add another dropped you at the bottom of an empty form.
  A `<ScrollToTop />` in the app shell resets it on each navigation.
  Back/Forward are deliberately exempt — returning to a list you were halfway
  down should keep your place.

### Note
Existing hats keep the cutouts they were already given; the improvements apply
to photos processed from here on. The pre-cutout JPEG is not retained, so there
is nothing to re-cut from.

## [2.6.1] — 2026-08-16 — _name the collab yourself_

### Added
- **Artist / Collab is editable.** `artist_series` was readable on the hat page
  but there was no way to set or correct it — 2.6.0 shipped it as a Claude-only
  field. It now has an input in the Edit Hat form's AI / Pricing Overrides card,
  which is exactly where "override anything Claude got wrong" belongs. Special
  editions are the hats Claude is least likely to name and the ones most worth
  recording.

### Fixed
- **A re-analysis no longer erases a brand, model or collab you typed.**
  `_apply_analysis` assigned Claude's answer straight through, nulls included,
  so tapping Reanalyze wiped any of those three fields Claude couldn't identify
  — and the tool schema explicitly tells it to answer null rather than guess,
  most forcefully for `artist_series` ("guessing here is worse than leaving it
  empty"). Without this the new field would have been erased by the very
  workflow it exists for. A real answer still wins, so Claude can still correct
  an earlier identification; only erasure is blocked. `logo_detected` is
  deliberately exempt — it records what is visible in *this* photo, so null
  there is an answer, not a gap. Same rule the construction flags already
  followed.

## [2.6.0] — 2026-08-16 — _analysis gets out of your way_

### Added
- **Photo analysis is queued instead of blocking the upload.** `POST /api/hats/
  {id}/photo` now saves the photo, marks the hat `analysis_status='pending'` and
  returns immediately; a background worker (`analysis_queue.py`) runs rembg →
  Claude → eBay → Melin. You can keep adding hats while earlier ones analyse.
  The hat page shows a spinning **Analyzing…** badge and polls until the status
  is terminal. Previously the request stayed open for the whole pipeline —
  Claude alone is a 30s timeout × the SDK's 3 attempts, after tens of seconds of
  rembg — which read as a hang. `reanalyze` queues too when a Claude key is set.
  Durability mirrors the bulk-import worker: the loop survives any per-hat
  exception, a crash mid-analysis is re-queued on boot, and if no worker is
  draining the queue the route runs the pipeline inline rather than dropping it.
- **`logo_detected` field.** Claude Vision now records the mark it actually SAW
  and the brand that owns it ("Melin — M monogram, front panel"), kept apart
  from `brand`, which can be inferred from shape, colorway or a hang tag with
  no logo in frame. The Google Vision fallback fills it too — LOGO_DETECTION
  only fires on a visible mark, so that path is evidence by construction. Shown
  under Identification on the hat page.
- **HYDRO + HYDROLite checkboxes, and Claude sets them.** melin lists HYDRO and
  HYDROLite as separate technologies offered across the model lines, so they are
  two per-hat flags. Claude answers a single `construction` field
  (standard/hydro/hydrolite), which is mapped to the flags — one exclusive value
  rather than two booleans, so it cannot return a hat that is somehow both.
  Applying it is **additive**: analysis turns a flag ON and never off, because
  these are also checkboxes a human ticks and a re-analysis returning "standard"
  (which happens whenever bonded seams or a gel-welded logo aren't legible)
  must not silently un-tick them.
- **`artist_series` field.** Claude names the collaborator on signature
  collaborations / artist series ("Skye Walker", "melin x OluKai"), which the
  `collab` STYLE could not — it only says *some* collab, not which one, and
  which one is what drives collectability. Instructed to leave it null rather
  than guess.
- **HYDROLite checkbox on the hat form.** HYDROLite is melin CONSTRUCTION —
  featherweight build, bonded seams, gel-welded logos, antimicrobial sweatband —
  offered across A-Game, Coronado, Trenches and the rest, so any hat can be one.
  It is a per-hat flag (`hydrolite`), deliberately NOT a `HatStyle` value: as a
  style it would need a second entry per model and would split one model's hats
  across two style buckets. Shown as a badge on the hat page.
- **Clear All** on the hat's Color Palette card wipes the whole palette in one
  call, instead of removing swatches one modal at a time after a bad analysis.

### Changed
- **Default background-removal model is now `isnet-general-use`** (was
  `u2netp`). u2netp is 4.7 MB and was picked for Pi speed, but its low capacity
  loses thin protruding shapes — on a hat that is precisely the **bill**, so
  cutouts came back as brimless crowns. The heavier model costs ~170 MB and
  slower inference, which stopped mattering once analysis left the request path.
  `HEADROOM_REMBG_MODEL=u2netp` restores the old behaviour.

### Fixed
- **The photo button never offered your library.** The file input carried
  `capture="environment"`, which does not *prefer* the camera — it forces it, so
  iOS and Android skipped the picker and opened the rear camera, making an
  existing photo impossible to choose. Removed, so the normal Photo Library /
  Take Photo / Browse sheet appears.
### Fixed
- **Modals were painted over by the page behind them.** The photo cropper's zoom
  slider and "Use This" button ended up underneath the Details card's
  style/size/condition selects. `.modal` is `z-index: 1050`, but z-index only
  ranks siblings *within a stacking context*, and `.card-body` is
  `position: relative; z-index: 1` — so a modal rendered inside a card was
  confined to that card's slot in the page order and any later card covered it.
  All four modals now render through a `<body>` portal, which also immunises
  them against the `overflow: hidden` and `transform` containing-block traps.
- **Editing a mis-detected color silently reverted.** Typing "green" over a
  color Claude had read as grey saved "gray": `PUT /api/hats/{id}/colors`
  re-derived `general_color` from the stored hex whenever one was present, so
  the correction was overwritten by the very value being corrected. An
  explicitly-typed name now wins and is snapped to the palette's spelling (so
  chip search still matches); the hex is consulted only when the field is blank.
- **Color ranks are renumbered server-side.** `PUT /api/hats/{id}/colors`
  stored the client's `dominance_rank` verbatim. The UI edits and removes a
  color BY rank, so a duplicate made one tap hit two rows — and a gap invited
  one, since the add path picks `colors.length + 1` (ranks `[1,3]` + length 2 →
  3). Ranks now follow submitted position, so they are always dense and unique.
- **The SQLite write lock was held across the whole analysis.** Setting
  `photo_path` before the pipeline's first DB read let autoflush open a write
  transaction, which SQLite holds until commit — so the lock stayed held through
  Claude, eBay and Melin. Any concurrent write then waited out `busy_timeout`
  and failed with "database is locked", which the new queue would have made
  routine (adding a hat while another analyses). The network-bound section now
  runs under `no_autoflush`.
- `vite.config.ts` used `__dirname`, which only exists because Vite's current
  config loader wraps the file in CJS shims. The config is ESM
  (`"type": "module"`), and Vite's `configLoader: 'native'` — slated to become
  the default — evaluates it without those shims, where `__dirname` is a
  `ReferenceError` that would break every build. Now `import.meta.dirname`
  (Node 20.11+; `engines` already floors at 22.22), which also silences the
  deprecation warning printed on every build and test run.

### Changed
- CLAUDE.md documents the merge/tag procedure from a git worktree.
  `gh pr merge --delete-branch` merges on the server and *then* fails its local
  cleanup with `fatal: 'main' is already used by worktree`, which reads as "the
  merge failed" when it actually succeeded.

## [2.5.0] — 2026-08-16 — _current Claude models_

### Changed
- **The Claude model list is current again.** The picker offered the 4.5–4.7
  generation and defaulted to `claude-sonnet-4-6`, which Anthropic now
  classifies as legacy. The default is now **`claude-sonnet-5`** — newer *and*
  cheaper than the 4.6 it replaces ($2/$10 per MTok vs $3/$15). The Settings
  picker lists the current lineup (Sonnet 5, Haiku 4.5, Opus 5, Fable 5) under
  a **Current** group, with the superseded ids kept under **Legacy** so an
  install that saved one stays on a named option instead of silently falling
  through to "Other…". Any model id remains enterable by hand.
- **This only changes the default.** If you set a model in Settings, that choice
  is stored in the database and still wins — nothing is migrated or overwritten.
  Installs on the default will start using Sonnet 5 after upgrading; use
  **Test connection** on the Settings page to confirm the key reaches it.

### Added
- Consistency tests (`tests/test_docs_consistency.py`) asserting that the README
  env table, the OPERATIONS env table, and the Settings picker's "(default)"
  label all still match `config.anthropic_model`. Nothing linked those four
  places, which is how the app spent a model generation advertising a superseded
  id with every test green.

### Fixed
- The Claude model `<select>` and its custom-id input had no accessible name —
  the visible `<label>` carries no `htmlFor`, so screen readers announced them
  unlabelled. Both now set `aria-label`.

## [2.4.0] — 2026-08-16 — _any room can be the default_

### Added
- **The default room is now a flag, not a hardcoded id.** Previously room `id=1`
  was permanently undeletable, no matter how you'd since reorganised. Any room
  can now take the role via **Make default** on the Rooms page
  (`POST /api/rooms/{id}/default`), which frees the previous one for deletion.
  The Rooms page shows a **Default** badge and only disables delete on the room
  that actually holds the flag.

### Changed
- `RoomRead` gains `is_default`. `CaseCreate.room_id` is now optional — omitting
  it resolves to whichever room currently holds the flag instead of literally
  room 1. Both changes are backward compatible: an omitted `room_id` still lands
  in the default room.
- **New-hat defaults live in one place.** `condition=new / size=classic /
  style=a_game` were independently hardcoded in the bulk-import endpoint, the
  import worker's fallback, and the Android share target. Changing the default
  meant finding all three, and they could silently disagree — photos shared from
  a phone landing differently than the same photos bulk-imported. All three now
  read `HAT_DEFAULTS` (`schemas/hat.py`), with a test that fails if any drifts.
  The two frontend forms likewise share one `DEFAULT_HAT_BASICS` constant.

### Fixed
- Deleting a room reassigns its cases to the room that currently holds the
  default flag. It previously wrote `room_id=1` unconditionally, which would
  have pointed at a missing row the moment room 1 became deletable.

### Migration
- Adds `rooms.is_default` and backfills the **lowest room id** (not literally 1,
  so a database whose original room was re-keyed still ends up with a usable
  fallback). `ensure_default_room()` now repairs the "exactly one default"
  invariant on every boot — creating a room if the table is empty, flagging the
  lowest id if none is flagged, and clearing extras if several are. No action
  needed on upgrade.

## [2.3.1] — 2026-08-09 — _quiet the build_

The Docker build printed 9 lines of warning/notice noise on every run. None of
it was a failure — every build was green — but noise like this is how a real
failure scrolls past unnoticed.

### Changed
- **npm pinned to 12.0.2 in the frontend build stage.** `node:26` bundles npm
  11.x, which printed *"New major version of npm available! 11.19.0 → 12.0.2"*
  on every image build. Now pinned explicitly (`ARG NPM_VERSION`), matching how
  the uv toolchain is already pinned — bump it alongside the base image.
  Verified npm 12 installs, typechecks, tests and builds this project before
  pinning it.
- `NPM_CONFIG_LOGLEVEL=warn` in that stage — npm 12 logs a notice per script it
  runs. Warnings and errors still print; only the chatter is dropped.

### Fixed
- **onnxruntime device-probe warnings during the image build.** It probes the
  host for GPUs while `import onnxruntime` runs and logs a `[W:onnxruntime…]`
  line per device it can't read — guaranteed noise in a container, which has
  none. The messages come from C++ straight to fd 2 *during the import*, so
  `set_default_logger_severity()` runs too late; the rembg pre-download now
  redirects at the fd level across the import and restores it immediately.
  Scoped to that build step: the **runtime keeps onnxruntime's default
  logging**, so genuine problems still surface in container logs.
- **`StarletteDeprecationWarning` on every backend test run.** starlette's
  `TestClient` deprecated `httpx` in favour of `httpx2`; added `httpx2` to the
  dev group. Test-only — the app's own outbound calls (eBay, Google Vision,
  melinrecap) still use `httpx`, which is current at 0.28.1 and not deprecated
  in its own right.

- **`setup.sh` and CI now use the image's npm.** Pinning npm only in the
  Dockerfile created fresh drift — CI and bare metal stayed on npm 11 while the
  image built on 12, so the frontend CI job was green-lighting a toolchain that
  never ships. `setup.sh` gained `ensure_npm` (a floor check, like `node_ok`),
  and the CI frontend job pins the same version.

Net, measured in CI's own log: image build **9 noise lines → 0**, and
`uv run pytest` from "190 passed, 1 warning" to "190 passed".

## [2.3.0] — 2026-08-09 — _frontend tests, react-router 8, code-review cleanup_

### ⚠️ Requirements
- **`./scripts/setup.sh` now wants Node 22.22+** (was 22.12+). react-router 8
  declares `engines: node >=22.22.0`, which supersedes vite's `>=22.12.0` as the
  highest floor any dependency sets. Node 22.12–22.21 previously *passed* the
  setup check and then failed at `npm ci`; setup.sh now upgrades Node instead of
  waving it through, so nothing breaks — it just does more on that path.
  Docker (`node:26`) and CI (`node 26`) were already above the floor.
- `package.json` now declares `react`/`react-dom` `^19.2.7` (was `^19.1.0`) to
  match react-router 8's peer range. The installed version already satisfied it.

### Security
- **react-router 7.18.2 → 8.3.0**, clearing a HIGH advisory (*RSC Mode CSRF
  Bypass Allows Action Execution Before 400 Response*, vulnerable
  `>=7.12.0 <8.3.0`; 8.3.0 is the only patched release). Headroom is a
  declarative-mode SPA with no RSC, loaders, actions or server rendering, so the
  advisory was not exploitable here — but the version was flagged and the
  upgrade is clean. No Dependabot alerts remain open.

### Added
- **Frontend test suite** — Vitest 4 + Testing Library 16 (jsdom), **35 tests**,
  run in the existing CI frontend job (no new job, no new trigger). The repo had
  no frontend test harness at all. Covers the shared hat filter/form components,
  the 15-card Settings composition, and the routing primitives the route table
  depends on. `npm test` / `npm run test:watch`.
- `tests/test_hats.py::test_hat_read_exposes_every_derived_field` pins the Hat
  read-model fields that come from relationships rather than columns
  (`room_id`, `room_name`, `case_type`, `case_display_id`, `wear_count`) plus
  the unassigned-hat null case. `room_id` had no coverage and is what the Hats
  page filters on — a silent null there would have quietly matched nothing.

### Changed
- **Code-review cleanup — no behaviour change.** Verified by generating the full
  OpenAPI document before and after and diffing it: **90 routes, identical**,
  every response schema byte-identical.
  - The Anthropic and Google-Vision API-key routes were line-for-line twins.
    Both now derive from one `KeyProvider` descriptor — a third provider is one
    dataclass entry plus one line.
  - `_hat_to_read` hand-copied ~45 attributes and walked `hat.case.room` from the
    route layer. The derived values are now properties on the `Hat` model and
    `HatRead` builds itself with `model_validate`.
  - `routes/admin.py` (334 lines, seven reasons to change) is now a package of
    six single-concern modules; the `/api/admin` prefix, tag and `require_admin`
    are applied once, so a submodule cannot ship an unguarded route.
  - `SettingsPage.tsx` 1084 → 44 lines over 15 card modules; the shared hat
    filter and form components take the four hat pages from 1093 → 819 lines.
  - Import-job counters no longer dispatch on a string (the counter was
    `errors` while the item status was `error`); eBay's Browse request block was
    duplicated three times and is now one helper.
- `react-router-dom` is **removed in v8**; every import moves to `react-router`
  (the app uses none of the `react-router/dom` APIs). Dropping the re-export
  shim trimmed ~2 kB off the bundle.
- `rembg[cpu]` floor `>=2.0.50` → `>=2.0.77`.

### Fixed
- **Form controls were not associated with their labels.** The `<label>`
  elements carry no `htmlFor` and do not wrap their inputs, so assistive tech
  announced every filter and hat-form select as unlabelled. All eleven controls
  now carry an `aria-label`. Found by the new tests.
- **`HEADROOM_REMBG_MODEL` was documented as configurable but impossible to
  change.** `ARG` is stage-scoped, so the runtime stage discarded the build arg
  and compose pinned the env var on top; following the docs baked a ~170 MB
  model into the image that was never loaded.

## [2.2.2] — 2026-08-05 — _faster rebuilds, infra cleanup_

### Changed
- **Docker rebuilds are ~40s faster after a code change.** The rembg model
  pre-download sat *after* `COPY src ./src`, so every source edit re-downloaded
  the ONNX weights — measured at 51% of total image build time. It only needs
  `rembg`, so it now runs before the source copy. The two Python stages also
  share one `base` stage instead of repeating the image tag and native-lib list.

### Fixed
- **`./scripts/setup.sh --help` was truncating mid-list.** It printed a
  hardcoded line range that the header outgrew; it now prints the comment block
  itself.

### Docs
- Corrected the `pymatting` constraint rationale in `pyproject.toml`: 1.1.14
  declares `numba!=0.49.0` (*unbounded*, which is why an ancient numba can be
  selected), not "pins numba 0.53.1" as previously written — a maintainer
  checking the old claim would have found it false and dropped the constraint.

## [2.2.1] — 2026-08-05 — _cryptography Bleichenbacher fix_

The automation added in 2.2.0 immediately earned its keep: enabling Dependabot
alerts surfaced a **high**-severity advisory nothing had caught before.

### Security
- **`cryptography` 49.0.0 → 50.0.0** — PKCS#7 `EnvelopedData` decryption exposed
  a Bleichenbacher oracle (vulnerable `>=44.0.0,<50.0.0`). It reaches us through
  `webauthn`, i.e. the passkey path. **`pyopenssl` 26.3.0 → 26.4.0** rides along
  because 26.3 caps `cryptography<50` — upgrading cryptography alone was
  impossible, the resolver just silently backtracked to the vulnerable version.

### Changed
- **`[tool.uv] exclude-newer-package = { cryptography = false, pyopenssl = false }`.**
  The 7-day cooldown exists to dodge freshly published *malicious* packages, but
  for the crypto stack a fresh release is usually the *security fix itself* —
  50.0.0 landed 4 days after the advisory and a plain `uv lock` kept silently
  reverting to the vulnerable 49.0.0. These two are now exempt; everything else
  still waits out the cooldown.

## [2.2.0] — 2026-08-04 — _stop the drift: automated dependency updates + CI_

Answering "why is so much always out of date?": **nothing was automated.** No CI,
no Dependabot, no Renovate — no `.github/` directory at all. Every bump was
manual and reactive, and `package-lock.json` pinned versions that nothing ever
refreshed, so even in-range updates never landed.

### Added
- **`.github/dependabot.yml`** — weekly PRs for **npm**, **uv**, **Docker base
  images** (including the `COPY --from=` toolchain pin that sat at uv 0.5.4 from
  v0.2.0 to v2.0.6) and **GitHub Actions**. Minor/patch are grouped into one PR;
  majors arrive individually so they get a real review. Each ecosystem carries a
  7-day `cooldown`, mirroring `[tool.uv] exclude-newer`. Validated against the
  official schema.
- **`.github/workflows/ci.yml`** — pytest + typecheck + production build on
  every PR, plus a **real Docker build and container health check**. That last
  job is deliberate: the 2.0.6 breakage was config the *image's* toolchain
  couldn't parse, which the test suite could never have caught.
- **Dependabot alerts and automated security fixes are now enabled** on the
  repository (they were off, which is why the Snyk findings had to be found by
  hand).

### Changed
- **Frontend dependencies brought current.** In-range refresh (react, react-dom,
  @tanstack/react-query, @types/*, react-router-dom) plus four majors:
  **vite 6 → 8**, **TypeScript 5.8 → 7**, **@vitejs/plugin-react 4 → 6**,
  **react-easy-crop 5 → 6**. Typecheck and production build verified clean; the
  bundle got *smaller* (446 → 439 kB) and the build faster.
- **Node floor raised to 22.12** in `scripts/setup.sh`, with a real minor-version
  check. vite 8 and @vitejs/plugin-react require `^20.19 || >=22.12`, so a bare
  major comparison would have waved through Node 22.0 and then failed at build
  time — and the Node 20 line reached end-of-life 2026-04-30.

## [2.1.1] — 2026-08-04 — _bare metal catches up to the image_

2.1.0 moved the **Docker** toolchain forward but left the bare-metal path
behind, so `./scripts/setup.sh` still provisioned the old versions.

### Changed
- **`scripts/setup.sh` now installs what the image runs**: NodeSource
  `setup_22.x` → `setup_26.x`, and Python comes from a new committed
  `.python-version` pin (**3.14**) instead of whatever uv defaulted to. An
  existing **Node 20+** is still accepted — that's the real floor our vite and
  react-router require, so working setups aren't broken; only *fresh* installs
  get 26.
- **`.python-version` is now tracked in git.** It was in `.gitignore` under
  "local-only files", which would have made the pin invisible to everyone else
  — the interpreter version is a project decision, not a per-developer one.
- Doc claims corrected where they'd gone stale: README bare-metal prereqs and
  architecture line, CLAUDE.md setup/backend lines.

### Note
`pyproject.toml` keeps `requires-python = ">=3.12"` — verified the suite passes
on **both** 3.12.12 and 3.14, so there's no reason to drop 3.12 for anyone
bringing their own interpreter. There is no `requirements.txt` in this project;
`uv.lock` is the dependency manifest and is updated with every dependency change.

## [2.1.0] — 2026-08-03 — _latest toolchain across the whole build_

Every pinned tool in the image was audited, not just the one that broke in
2.0.7. The `uv` pin had sat at 0.5.4 since v0.2.0 — through a "production
hardening" pass that edited the same file — which is what let the 2.0.6
cooldown regression happen in the first place.

### Changed
- **Node 22 → 26** (SPA build stage), **Python 3.12 → 3.14**, **Debian bookworm
  → trixie**, **uv 0.11.28 → 0.12.1**. Caddy sidecars were already floating on
  latest `2-alpine`.
- Verified by **building and running the image**, not by checking versions
  locally — the exact gap that caused 2.0.7. Confirmed inside the container:
  Python 3.14.6 on Debian 13, `rembg`/`onnxruntime` load and produce a real
  `U2netpSession`, and a full end-to-end run (owner setup → create hat → photo
  upload → auth-gated photo fetch) returns a **transparent PNG**, which only
  happens when background removal genuinely ran. Zero tracebacks in the log.
- Note `fastapi` resolves to 0.139.2 rather than 0.140.x — the 7-day
  `exclude-newer` cooldown from 2.0.6 holding back a just-published release,
  working as designed.

## [2.0.7] — 2026-08-03 — _fix the Docker build's uv pin_

### Fixed
- **`failed to parse year in date "7 days"` during `docker compose build`**, a
  regression from 2.0.6. The image pinned **uv 0.5.4** (Nov 2024), but the
  `exclude-newer = "7 days"` cooldown added in 2.0.6 needs **uv ≥ 0.9.17** —
  relative durations didn't exist before that. The old uv warned and then
  **silently ignored the setting**, so the build still produced an image, but
  **without the supply-chain cooldown 2.0.6 advertised**. The pin is now
  `uv 0.11.28`, which is also the version that writes `uv.lock` (revision 3) —
  the old pin predated that lock format too. Verified by building the image and
  running it: no parse error, `uv lock --check` clean *inside* the container,
  and `/health`, `/health/ready`, the auth gate, and the SPA all respond.

## [2.0.6] — 2026-07-27 — _dependency security updates_

### Security
- **Cleared 74 Python advisories across 11 packages**, including three sitting
  directly in the photo-upload path: **pillow-heif** 1.2.1 → 1.4.0 (CVSS 9.1),
  **Pillow** 12.1.1 → 12.3.0 (8.7, 36 advisories), and **python-multipart**
  0.0.22 → 0.0.32 (7.5, 12 advisories). Also **urllib3** → 2.7.0 (8.9),
  **starlette** 0.52.1 → 1.3.1, **idna** → 3.18, **click** → 8.4.2,
  **pydantic-settings** → 2.14.2, **python-dotenv** → 1.2.2, **pygments** →
  2.20.0, **pytest** → 9.1.1.
- **Frontend: 11 Snyk issues → 1.** `react-router-dom` 7.13.0 → 7.18.1 clears
  a Critical (untrusted deserialization), 6 High (XSS, two open redirects,
  algorithmic-complexity and resource-exhaustion DoS) and the Medium/Low CSRF
  and unsafe-reflection findings. `vite` 6.4.1 → 6.4.3 clears three High
  dev-server issues (path traversal, arbitrary file read over the dev
  WebSocket, `server.fs.deny` bypass); `npm audit fix` cleared the
  postcss/picomatch/babel build-toolchain advisories.
- **Known-accepted, not applicable:** one React Router advisory remains
  (GHSA-qwww-vcr4-c8h2 / SNYK-JS-REACTROUTER-18313151, "RSC Mode CSRF Bypass",
  fixed only in react-router 8.3.0). This app is a pure client-side
  `BrowserRouter` SPA — no RSC mode, no loaders/actions, no `@react-router/*`
  server packages, and zero RSC handlers in the built bundle — so the affected
  code path cannot be reached. Deferred rather than take a major-version
  migration for an unreachable path.

### Changed
- `[tool.uv]` gains a **7-day dependency cooldown** (`exclude-newer`) so a
  compromised or broken package published minutes ago can't be pulled straight
  into a build, plus a `pymatting>=1.1.15` constraint — the resolver otherwise
  picked 1.1.14, which pins `numba` 0.53.1 → `llvmlite` 0.36.0 and only builds
  on Python <3.10, breaking `uv sync` and the Docker image on our 3.12 baseline.

## [2.0.5] — 2026-07-25 — _case-rack top-cap fix (v3.1)_

### Fixed
- **Case-rack top cap didn't seat on the pegs** (`hardware/melin-rack-v3.zip`).
  The v3 staggered legs are C2-*rotation* symmetric but **not mirror** symmetric,
  and the cap installs **flipped** — which mirrors its plan pattern — so the
  cap's bosses/pockets landed at the wrong positions. The cap is now modeled at
  the x-mirrored leg positions (`cap_pos` in the `.scad`) so it seats exactly
  after the flip. **Only the top cap changed**: `melin-rack-rack.stl` and
  `melin-rack-fit_test.stl` are byte-identical to v3, so already-printed bays
  and coupons stay good — reprint just the cap.

### Removed
- `melin-rack-top_cap.3mf` from the model archive. It was sliced from the
  pre-fix geometry, and shipping a ready-to-print project of a part that doesn't
  fit is worse than shipping none — slice the corrected
  `melin-rack-top_cap.stl` instead. The bay and fit-test `.3mf` projects are
  unaffected and still included.

## [2.0.4] — 2026-07-19 — _off-site backups_

### Added
- **Off-site scheduled backups.** New `HEADROOM_BACKUP_UPLOAD_CMD` runs after
  each scheduled backup and ships the new tarball off-box (`{path}`/`{dir}`/
  `{name}` substituted, argv/no-shell, bounded by
  `HEADROOM_BACKUP_UPLOAD_TIMEOUT`, best-effort — a failed or missing uploader
  never breaks the local backup). New `docker-compose.backup-rclone.yml` overlay
  wires it to rclone (Box, S3, Backblaze B2, Google Drive, …); OPERATIONS.md §4
  also documents a host-cron alternative. Box has no native Linux client, so
  rclone's `box` backend is the supported path on a Pi.

### Docs
- **"Start fresh / reset the database" instructions** — how to wipe the
  `headroom-data` volume for a clean install (with the backup-first warning and
  the `https-lan` Caddy-CA caveat), plus keep-the-cert and keep-the-photos
  variants. Added to the README `Updating` section and OPERATIONS.md §4.

## [2.0.3] — 2026-07-17 — _mDNS behind the sidecar_

### Fixed
- **`headroom.local` not resolving in the Docker host-net / sidecar deploys**
  (the raw IP worked, the name didn't). The mDNS responder ran in zeroconf's
  default "all interfaces" mode, so in a host-net container it also bound
  sockets on `docker0`/`veth` (always present once a second container like the
  Caddy sidecar is up): a flaky bridge socket could make registration throw and
  be swallowed (→ never advertises), and even on success the responder leaked
  onto the bridge and multicast could egress the wrong NIC. It now binds the
  **detected LAN interface only**. Escape hatch: `HEADROOM_MDNS_INTERFACE` — an
  IP to pin, or the literal `all` to restore the previous all-interfaces mode.
  `GET /api/settings/mdns` reports the advertised IP and any error.

## [2.0.2] — 2026-07-17 — _case-rack v3_

### Changed
- **Case-rack model → v3** (`hardware/melin-rack-v3.zip`, replaces
  `melin-rack-v2.zip`). Legs are now **staggered** so adjacent stands interleave
  side by side at 235 mm center-to-center (C2 symmetric — orientation-free); the
  side channel is 5 mm tighter for a snugger hold (0.5 mm/side, ~221 mm channel),
  trimming the footprint to ~241 × 258 mm. Every printable part now ships a
  ready-to-slice Bambu Studio `.3mf` (bay + top cap + fit test), not just the bay.

## [2.0.1] — 2026-07-16 — _test hardening_

### Added
- **Plain-HTTP-on-80 deploy overlay** (`docker-compose.http80.yml`) — a Caddy
  sidecar serves `http://headroom.local` (and `http://<host-ip>`) on port 80
  with no HTTPS and no certificate to trust. The app stays non-root on :8000;
  Caddy owns the low port. Password login only (http isn't a secure context —
  use `docker-compose.https-lan.yml` for passkeys/Face ID).
- README "Run it" now opens with an overview table of every deploy mode
  (default / LAN name / LAN port 80 / LAN HTTPS / internet / bare metal / dev)
  with its command, URL, and passkey support.
- **Browser-tab favicon is now the Headroom logo** (`favicon.ico` at 16/32/48 +
  a 32px PNG, generated from the app icon), so tabs no longer fall back to the
  browser default.

### Changed
- **Case-rack model → v2** (`hardware/melin-rack-v2.zip`, replaces
  `melin-stand-slim.zip`). Bay is sized for the case measured **zipped shut**
  (`case_w` 200 → 220 mm, footprint ~246 × 258 mm), print profile bumped to
  4 walls / 20% infill, and a ready-to-slice Bambu Studio `.3mf` is included.

### Tests
- **Assertion-strength pass over the whole suite.** Refined tests whose name
  promised a behavior their assertions never verified — they stayed green even
  when that behavior broke. Replacing a photo now checks the old file actually
  left disk (not just that the path string changed); image conversion decodes
  the output bytes as JPEG/RGB rather than trusting the `.jpg` suffix; the
  backup download is opened as a gzip tar and walked instead of measured by
  length; the `hat.created` audit row is tied to the specific hat; and wear's
  `date_last_worn` is asserted against today's date.
- **New coverage for previously-untested paths.** The token-gated share-photo
  streamer's path-traversal guard, and the eBay comparable-listings service
  (query hierarchy, degrade-to-link-only, and price aggregation with the
  network seam stubbed — no live API, per house rule). A duplicate `/health`
  test was removed.
- Three of these guards are **mutation-verified**: breaking the code (removing
  the photo `unlink`, swapping the JPEG encoder, dropping the traversal check)
  makes the corresponding test fail, proving it catches the real regression.

## [2.0.0] — 2026-07-16 — _production hardening_

A forensic multi-agent review (code-archaeology) gated the v1.x line for
production; this release fixes every finding and folds in the preceding
cleanup pass. Databases upgrade in place — no schema-breaking changes — but
two operational interfaces changed, hence the major bump.

### Breaking
- **`BUILD_SHA` build arg renamed to `HEADROOM_BUILD_SHA`.** Stamp the footer
  with `HEADROOM_BUILD_SHA=$(git rev-parse --short HEAD) docker compose up
  --build`. The old `BUILD_SHA` name is no longer read.
- **The Docker image install is now `uv sync --frozen` only** (no unpinned
  fallback). A `uv.lock` / `pyproject.toml` mismatch fails the build instead
  of silently resolving fresh versions — run `uv lock` and commit if it errors.
- **Changing your password now rotates the API bearer token** as well as
  revoking other sessions. Cookie-less clients (the iOS Shortcut) must copy
  the new token from Settings → Account after a password change.

### Changed (cleanup pass)
- mDNS advertising registers off the boot path (≈1.2 s faster startup) and
  withdraws with a single goodbye broadcast; the Settings LAN card derives its
  state instead of caching it. Shared `env_flag()` replaces three copies of the
  truthy-env idiom.
- README gains a full step-by-step **HTTPS-on-the-LAN / Face ID** walkthrough.

### Fixed — reliability
- **Bulk-import worker can no longer silently die.** The worker loop now
  survives any per-item exception (including a transient `database is locked`),
  and a bug in its own error handler (`item.job_id` on a `None` item) is fixed.
- **Crash recovery for imports.** On boot, items stranded in `processing` are
  re-queued and jobs whose items are all terminal (e.g. every file oversize)
  are closed — no more jobs that poll "running" forever.
- **Backups no longer self-destruct under restart loops.** Retention is now
  age-based (honoring `_RETENTION_DAYS`), the newest snapshot is never pruned,
  and the startup backup is skipped when a recent one already exists.
- **SQLite tuned** with WAL + `busy_timeout` + `synchronous=NORMAL`, shrinking
  the transient-lock error class.

### Fixed — correctness
- **Undispose no longer collides slots.** Restoring a disposed hat reassigns
  its `position_in_case`, so it can't share a slot / display ID / QR label with
  a hat added while it was disposed.
- **Manual color edits stay searchable.** `PUT /hats/{id}/colors` now normalizes
  `general_color` onto the curated palette (as the analysis pipeline does).
- **One wear per hat per day** is enforced by a unique constraint, closing the
  double-tap race.
- Case-photo upload no longer blocks the event loop (async image processing).

### Fixed — security / operability
- **Auth telemetry.** Failed logins, lockouts, and successes are logged and
  audited (IP + username); backup downloads, key/cred changes, and share-link
  create/revoke now write `activity_log` rows.
- **`/health/ready` redacts** filesystem paths, key source, and raw errors for
  anonymous callers; authenticated callers also get an import-worker liveness
  signal.
- **Password change is a complete compromise response** — it now rotates the
  API token alongside revoking other sessions.
- **First-run setup is serialized** against a concurrent second POST (no
  duplicate owners).
- argon2 verify runs off the event loop under a concurrency bound; login
  rate-limiter entries are cleaned up; bulk-upload memory is bounded; the
  Dockerfile install is `--frozen`-only (no silent unpinned fallback).
- Single-process assumption is now warned about at startup when `WEB_CONCURRENCY`
  > 1. Retired `HEADROOM_ADMIN_TOKEN` references removed from docs.

### Added
- **Public branding logo** (`GET /api/public/branding/logo`) — the login page
  now shows the configured logo, not just the wordmark.
- Model↔migration consistency test so a new `Hat` column can never be forgotten
  in the DDL. 14 new hardening regression tests (170 total).

## [1.3.0] — 2026-07-15 — _headroom.local + LAN passkeys + printable case rack_

### Added
- **mDNS LAN discovery.** The app advertises itself as **`headroom.local`**
  (python-zeroconf, best-effort, `HEADROOM_MDNS_ENABLED` / `_HOSTNAME` /
  `_PORT`). Multicast can't cross Docker's bridge network, so the new
  `docker-compose.mdns.yml` overlay switches to host networking (Linux/Pi).
  A read-only **LAN Discovery** card on Settings (`GET /api/settings/mdns`)
  shows the advertised URL, LAN IP, or registration error.
- **LAN HTTPS overlay** (`docker-compose.https-lan.yml`) — Caddy with its
  internal CA on 443 makes `https://headroom.local` a secure context, so
  **Face ID / passkeys work on the LAN name** (Let's Encrypt can't issue
  for `.local`). Trust the exported root cert once per device; passkey
  identity and mDNS port are set automatically. Proxy-header trust scoped
  to loopback since :8000 stays LAN-reachable.
- **3D-printable case rack** (`hardware/melin-stand-slim.zip`) — modular,
  stackable, supports-free slide-in rack for Melin 3-hat travel cases
  (parametric OpenSCAD + STLs, filament-optimized skeleton floor). Print
  notes recommend an H2D-class bed (~222 × 258 mm footprint). Linked from
  the README and the app footer.
- **Build stamp.** The footer shows the git short SHA next to the version:
  baked at build time from `HEADROOM_BUILD_SHA` / local git, injectable in
  Docker via the `BUILD_SHA` build arg.
- README: **Updating** section (upgrade commands + automatic SQLite
  migrations + backup-first advice) and a LAN discovery guide.
- 7 new tests (154 total).

## [1.2.0] — 2026-07-12 — _wear tracking + QR case labels_

### Added
- **Wear tracking.** "🧢 Wearing this today" button on the hat page appends
  to a new `wear_log` table (idempotent per day, undo supported) and bumps
  `date_last_worn`. Hat pages show wear count and **cost-per-wear**
  (purchase price falling back to retail estimate ÷ wears). The Valuation
  page gets a "Wear Rotation" card surfacing the five longest-unworn
  active hats. `POST /api/hats/{id}/wear`, `DELETE /api/hats/{id}/wear/latest`.
- **QR case labels.** `GET /api/admin/case-labels` renders a printable
  sheet — one label per case with an inline-SVG QR (deep link to the case
  page), display id, room, and fill/capacity. "🏷 Labels" button on the
  Cases page. Print, cut, stick; scanning opens the case in the app.
  New dep: `qrcode` (pure Python, SVG output — no raster stack).
- 3 new tests (147 total).

## [1.1.0] — 2026-07-12 — _colorway catalog + purchase history_

### Added
- **Colorway catalog.** `POST /api/admin/colorways/refresh` sweeps every
  style category on the melinrecap marketplace API and parses listing
  titles ("Model - Colorway") into a catalog table — live-verified: 987
  listings → 501 unique entries, including years of sold-out drops absent
  from melin.com. `GET /api/meta/colorways` powers native-datalist
  autocomplete for model + colorway on the Edit Hat form; Settings gets a
  refresh card. New `colorway` column on hats.
- **Purchase history + cost basis.** `purchases` table with
  `POST /api/admin/purchases/import` (structured line items from order
  emails; deduped) and `POST /api/admin/purchases/match`, which links
  purchases to hats by model (+colorway when both sides have one) and sets
  `purchase_price` / `purchased_at` / `colorway` on the hat. Edit Hat form
  exposes colorway + purchase price; Settings shows the purchase list.
  Gmail extraction feeds this via the importer once the connector is
  authorized.
- 5 new tests (144 total).

## [1.0.0] — 2026-07-12 — _auth: accounts, passkeys, share links, HTTPS_

Headroom is now safe to expose to the internet. **Breaking**: accounts are
mandatory — on first boot the app walks you through creating the owner
account; the iOS Shortcut import now needs an `Authorization: Bearer
<api-token>` header (token in Settings → Account). `HEADROOM_ADMIN_TOKEN`
is retired and ignored.

### Added
- **Accounts + sessions.** First-run owner setup, argon2id password
  hashing, server-side revocable sessions (256-bit, 30-day, httpOnly +
  SameSite=Lax cookies, `secure` auto-set over HTTPS), login rate limiting
  (5 fails → 15-min lockout per IP+username), logout, change-password.
- **Everything data-bearing is gated** — all of `/api/*` AND the
  `/uploads/*` photo mount (previously world-readable). Open by design:
  SPA shell/assets, manifest/icons, `/health*`, `/api/auth/*`,
  `/api/public/*`. The Android share-target POST needs a session; the
  public share page does not.
- **Passkeys (WebAuthn).** Add from Settings → Account; sign in with Face
  ID / Touch ID from the login page. py_webauthn on the backend, hand-rolled
  base64url plumbing on the frontend (no new JS deps). `HEADROOM_RP_ID` /
  `HEADROOM_ORIGIN` config; set automatically by the HTTPS overlay.
- **API token per user** (shown/rotated in Settings → Account) for
  cookie-less clients — the iOS Shortcut recipe card now includes the
  header step.
- **Read-only share links.** Settings → Share Links mints `/share/<token>`
  URLs (256-bit, revocable, optional expiry): a public gallery view with
  token-gated photo streaming — photos never leak through the protected
  uploads mount.
- **HTTPS overlay** (`docker-compose.https.yml`): Caddy sidecar with
  automatic Let's Encrypt certs; port 8000 no longer exposed directly;
  uvicorn honors X-Forwarded-Proto (`--proxy-headers`).
- Login page (first-run setup + password + passkey), Account card,
  Share Links card; 401s anywhere in the SPA bounce to /login.
- 9 new auth tests (138 total); full lifecycle also smoke-tested live
  (fresh DB → setup → gated uploads → share link → logout).
- Deps: `argon2-cffi`, `webauthn`.

### Fixed
- Password reset procedure documented for the no-email reality
  (OPERATIONS §6): wipe `users` + `auth_sessions`, first-run setup returns.

## [0.9.0] — 2026-07-11 — _find-the-hat: color-similarity search + capacity_

### Added
- **Search by color.** Tap a palette chip (or pick any color) and every
  active hat is ranked by perceptual closeness — ΔE*76 in LAB space over
  the *stored hex swatches*, so "light blue" finds sky/powder/baby blue
  hats regardless of what the analyzer named them, and a hat whose
  *secondary* color matches still surfaces (matched swatch + Δ shown).
  `GET /api/search/color?hex=`, palette chips from `GET /api/meta/colors`.
- **Normalized color vocabulary.** `general_color` now snaps to the
  curated palette from the hex at analysis time, with a one-time startup
  backfill for existing rows (guarded by an app-setting flag). Default
  color search uses the normalized names; `exact_colors` still matches the
  analyzer's original phrasing.
- **Find-it result cards.** Search results now include brand + model name
  and a location breadcrumb (Case display-id · Room); text search also
  matches brand/model (`hydro` works now — the placeholder always claimed
  brand search, the backend never did it). Disposed hats are excluded from
  search — they're not findable on a shelf.
- **Per-case capacity.** New nullable `capacity` column (inline DDL
  migration) overrides the 4-regular/6-beanie defaults per case, editable
  on the New/Edit Case forms — Melin cases realistically hold 3–4.
- 13 new tests (129 total).

## [0.8.0] — 2026-07-07 — _live Melin Recap resale prices_

### Added
- **Live median resale price from melinrecap.com.** The site is a Treet
  marketplace on Sharetribe Flex; its frontend queries the public Flex
  Marketplace API with an anonymous public-read token whose client id is
  embedded in their JS bundle. `melin_recap.py` now does the same — one
  `listings/query` per analysis (style category, up to 100 listings),
  narrowed to the specific model when ≥3 title matches exist. Median asking
  price lands in `resale_price` with a transparent source label ("Melin
  Recap · median of 83 live model listings"). No scraping, no headless
  browser — Pi-friendly, and verified live (A-Game Hydro → $63.90 across
  83 listings).
- Runs in every analysis path: Claude success, reanalyze, and the v0.7.0
  fallback when logo detection identifies a Melin (which now also gets the
  deep-link pointer).
- `HEADROOM_MELIN_CLIENT_ID` env override in case Treet rotates the id;
  anonymous token cached ~20 min with a retry-once-on-401.
- Conftest guard: the Sharetribe seam is stubbed suite-wide so tests can
  never hit the live marketplace; 7 new tests (116 total) cover median
  math, model-vs-category sampling, persistence, and API-failure degrade
  (which is byte-for-byte the old link-only behavior).
- **Standalone guides**: `docs/OPERATIONS.md` (deployment, configuration,
  health checks, backup/restore with the archive's actual `data/` layout,
  upgrades, security posture, Pi notes, troubleshooting) and
  `docs/USAGE.md` (first-run setup, rooms/cases/hats model, all three
  import paths, analysis status pills, pricing signals, search,
  disposition, reports, PWA install). Linked from the README header.

## [0.7.0] — 2026-07-07 — _analysis fallback: mask colors + Google logo brand_

### Added
- **No-Claude fallback analysis** (`analysis_status="fallback"`). When no
  Anthropic key is configured — or a Claude call fails — hats no longer come
  out blank:
  - **Colors, zero keys required.** Dominant colors are extracted locally
    from the rembg cutout's alpha mask (pixels with alpha ≥ 200 only), so
    **background colors are rejected by construction** — the mask *is* the
    segmentation. Median-cut quantization + a curated ~25-name palette fills
    `color_name`/`general_color`/`hex_value`/`tier` (searchable like the
    Claude-derived colors). If bg-removal failed for a photo, no colors are
    guessed from the contaminated frame.
  - **Brand via Google Cloud Vision logo detection** (optional). New
    Settings card + `GET/PUT/DELETE /api/settings/google-vision-key`
    (masked reads, admin-guarded writes, DB > `HEADROOM_GOOGLE_VISION_API_KEY`
    env — same pattern as the Anthropic key). REST + API key, no Google SDK
    dependency. Logos below 0.6 confidence are ignored.
  - Model name, price, and design notes stay empty — **Reanalyze** with a
    Claude key upgrades a fallback hat to full identification. Reanalyze now
    also *runs* the fallback when no Claude key is set (was a hard 400), and
    Claude-error reanalyzes degrade to fallback data instead of error-only.
  - UI: orange "Basic ID (fallback)" pill + info banner on the hat detail
    page; eBay comps remain Claude-gated (no model name to search with).
- 15 new tests (109 total): background rejection proven against synthetic
  RGBA fixtures with poisoned transparent pixels, Vision JSON parsing, all
  pipeline degradation paths, reanalyze fallback, key-route masking.

### Fixed
- **Test suite no longer writes into the developer's real `uploads/`
  directory.** `settings.upload_dir` is a relative path and conftest never
  redirected it, so every photo-upload test had been depositing tiny
  synthetic images into `uploads/hats/` (177 files accumulated since
  February). New autouse `isolated_upload_dir` fixture points each test at
  a temp dir with the lifespan's directory tree pre-created. Stray
  sub-10KB artifacts in a real uploads folder can be safely removed.

## [0.6.4] — 2026-07-06 — _self-installing setup + fresh-install logo fix_

### Fixed
- **Seeded logo now loads on the very first boot.** `create_app()` only
  mounted `/uploads` if the uploads directory already existed at import
  time — but the lifespan creates and seeds it *after* the factory runs.
  On a fresh install (Docker bind mount, zip distribution, or a cwd
  without `uploads/`) the logo 404'd — or worse, the SPA catch-all served
  `index.html` with a 200 for it — until the server was restarted. The
  mount is now unconditional (`check_dir=False`); the lifespan still owns
  directory creation and runs before the first request. Regression test:
  `test_uploads_mount_survives_missing_dir_at_import`.

### Changed
- **`scripts/setup.sh` now installs its own prerequisites** instead of
  erroring when they're missing. Installs (only what's absent, safe to
  re-run): uv (brew / Astral installer), Node 20+ (brew / NodeSource on
  apt & dnf), Python 3.12 (via uv itself), and — unless `--no-docker` —
  a Docker engine **without Docker Desktop**: colima + docker CLI +
  compose/buildx plugins via brew on macOS, native Docker Engine via
  get.docker.com on Linux (incl. docker group setup + systemd enable).
  Also builds the production SPA by default (`--skip-build` to opt out)
  so `uv run uvicorn` serves the full app straight after setup. Remote
  installers are downloaded to a temp file and executed — never piped
  from curl into a shell. `--docker-only` installs/starts just the
  Docker engine and exits — it's step 2 of the README's Docker quick
  start, so `docker compose up --build` never assumes an engine that
  isn't there.
- **README restructured around "Run it".** Run instructions moved to the
  top (they were buried under five versions of release notes — now a
  short "What's new" that links to this file). First Docker run is shown
  attached so build/boot progress is visible; `-d` is introduced second,
  with a troubleshooting note for the `unknown shorthand flag: 'd'`
  error (= missing Compose v2 plugin → run `./scripts/setup.sh`).
  Placeholder `<repo-url>` replaced with the real clone URL, and the
  Development section now uses the npm scripts that actually exist
  (`npm run build`, `npm run typecheck`).

## [0.6.3] — 2026-05-04 — _eBay env detection + raw error surfacing_

### Added
- **eBay env detection.** `/api/admin/ebay/creds` now returns
  `detected_env: "production" | "sandbox" | "unknown"` by inspecting the
  saved App ID for `-PRD-` or `-SBX-` (eBay's keyset format). Settings
  page renders a colored chip next to the masked App ID — green for
  production, red for sandbox, with an explicit warning banner when
  sandbox keys are saved ("These are SANDBOX keys — they will fail with
  401. Replace with a Production keyset").
- **Defensive paste handling.** PUT /api/admin/ebay/creds now strips
  surrounding quotes (`'`, `"`, `` ` ``) in addition to whitespace, in
  case the user pastes from a code block / env-var docs that included
  delimiters.

### Changed
- **eBay OAuth errors now surface eBay's actual response.** Previously
  any non-200 from the token endpoint just displayed my generic guess.
  Now we parse eBay's structured `{error, error_description}` and lead
  with that — e.g. `"eBay OAuth returned 401 (invalid_client) — client
  authentication failed"`. The "probably sandbox" hint is appended only
  for 401s, not as the only message.
- Server-side: failed OAuth responses are now logged at WARNING with
  the full status code, error code, description, and (truncated) raw
  body so `docker logs headroom` is useful for debugging.

## [0.6.2] — 2026-05-04 — _eBay diagnostics_

### Added
- **"Test connection" button** on the eBay Settings card. Probes OAuth +
  a sample Browse search end-to-end and surfaces a structured
  `{ok, stage, detail}` so the user knows whether OAuth succeeded, the
  Browse query worked, or the creds aren't configured at all.
  Backend: new `POST /api/admin/ebay/test` endpoint and
  `ebay_service.verify_creds()` that runs the full probe and reports
  which stage failed.

### Changed
- **Specific error message for sandbox-vs-production keyset mismatch.**
  When eBay returns 401 on the OAuth call (the most common failure mode —
  user pastes Sandbox keys against the production endpoint), the error
  now reads: "401 Unauthorized from eBay OAuth. Most likely your App ID
  + Cert ID are for the sandbox keyset, but Headroom calls production.
  Generate a PRODUCTION keyset at developer.ebay.com → My Account →
  Application Keysets, then re-paste both values." Previously this
  surfaced as an opaque `502 Bad Gateway`.
- Settings card help text now explicitly calls out **Production**
  (vs Sandbox) as the required keyset type.

## [0.6.1] — 2026-05-03 — _user style is ground truth + tap-to-edit colors_

### Changed
- **Owner-selected style is now ground truth for Claude.** When a hat is
  uploaded with `style=trenches`, the analysis prompt explicitly tells
  Claude that line is authoritative — Claude identifies the specific
  variant within the Trenches line (Hydro / Icon / Infinity / etc.) and
  is told NOT to pick a model from a different line. If the photo seems
  inconsistent, Claude lowers `model_confidence` rather than overriding.
  `analyze_hat_image()` gains a `selected_style` parameter; the upload
  pipeline + reanalyze route both pass `hat.style`. Fixes the case where
  a Trenches snapback was being labeled as an A-Game Hydro.

### Added
- **Tap-to-edit color rows** on the Hat detail page. Every color in the
  palette is now a button that opens a modal with: a big color preview
  that triggers the system color wheel (iOS Safari opens its native
  picker), a hex text field, specific name + general (filter) name
  fields, and a tier dropdown. Save / remove / cancel. New "+ Add Color"
  button at the top of the palette card. Backed by the existing
  `PUT /api/hats/{id}/colors` endpoint.

## [0.6.0] — 2026-05-03 — _Share-to-Headroom + version display_

### Added
- **Web Share Target API** in `manifest.json` — Android Chrome users who
  install Headroom as a PWA get a "Share to Headroom" entry in the system
  share sheet automatically. Selected photos route through the existing
  bulk-import job worker. New backend endpoint `POST /share` accepts the
  multipart payload, queues an import job, and 303-redirects into
  `/hats/import?job=N` so the SPA renders progress.
- **iOS Shortcut recipe** in Settings — step-by-step instructions for
  building a one-time Shortcut that POSTs photos from the iOS Photos
  share sheet to `/api/hats/import`. Auto-fills the URL with the running
  origin so users can copy it as-is.
- **App version in the footer.** `vite.config.ts` reads `package.json`
  and bakes the version into the bundle as `__APP_VERSION__`. Footer
  always shows the running build.
- `BulkImportPage` now reads `?job=N` from the URL so the share-target
  redirect lands on the active job.

### Bumped
- Project version → `0.6.0` (synced across `pyproject.toml` and
  `frontend/package.json`).

## [0.5.0] — 2026-05-03 — _Polish_

PWA install + photo crop on upload. Pure UX wins, no data model touches.

### Added
- **Installable PWA.** Proper `manifest.json` (192px + 512px + maskable
  icons, standalone display, theme color, background color) and
  `apple-touch-icon` link in `index.html`. Generated PNG icons from the
  seed logo via Pillow on every build. iOS "Add to Home Screen" now
  produces a fullscreen Headroom app with the brand icon.
- **Photo edit on upload** via `react-easy-crop` (~30KB gzipped, no peer
  deps). PhotoCapture flow now: pick → crop modal (free aspect, 90°
  rotate, zoom slider) → upload. Cropping happens client-side via canvas;
  backend pipeline is unchanged. Cancelling the crop modal uploads the
  original.

## [0.4.0] — 2026-05-03 — _Real Numbers_

Live eBay comparable-listings prices replace the heuristic resale guess.
Insurance-grade inventory report.

### Added
- **eBay Browse-API integration.** `services/ebay_service.py` does OAuth
  client-credentials → token cache → search by `brand + model + style`,
  returns mean / median / count of currently-listed comparable prices.
  Refreshes automatically when Claude finishes analysis (best-effort,
  never fails the upload). Per-hat refresh button on the detail page.
  New Hat columns: `ebay_avg_price`, `ebay_median_price`,
  `ebay_listing_count`, `ebay_search_url`, `ebay_checked_at`.
- **Settings UI for eBay creds** — admin-gated `app_id` + `cert_id` +
  `marketplace` (default `EBAY_US`), masked on read, env-var fallback
  via `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID`.
- **Inventory Report** — `GET /api/admin/inventory-report?include_disposed=&include_photos=`
  returns a self-contained HTML page with a print stylesheet (A4,
  page-break-inside avoid). Two-column totals tile + per-hat row with
  thumbnail, brand/model, condition, location, original retail, and
  best-available current value. Settings page button opens the report
  in a new tab; user uses browser Print → Save as PDF. Zero new heavy
  deps (vs. WeasyPrint's 200MB cairo / xhtml2pdf).
- **Hat detail Valuation card** now shows three tiles side-by-side:
  New Retail / eBay Median / Resale (manual), plus a refresh button
  and deep-link buttons to both eBay search and the existing Melin
  Recap link.

### Notes
- The free Browse-API tier is 5,000 calls/day; with caching + the rare
  brand/model identifier changes you'll be nowhere near it.
- Browse API surfaces *currently listed* items, not sold prices —
  asking prices skew higher than realized values. Marketplace Insights
  (sold prices) requires partner approval; deferred.

## [0.3.0] — 2026-05-03 — _Inventory Loop_

Hats in fast, hats tracked, hats out, all audited.

### Added
- **Activity log** — append-only `activity_log` table with `kind /
  entity_type / entity_id / summary / details(JSON)`. Hooks at every
  hat-service write path emit rows automatically. `/api/admin/activity-log`
  endpoint with filtering by `kind` and `entity_type`. Daily prune task
  (configurable retention via `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS=90`).
  New "Recent Activity" card on the Settings page.
- **Sale / disposition tracking.** Five new Hat columns: `disposed_at`,
  `disposed_via` (sold/gifted/lost/trashed/trade), `disposed_price`,
  `disposed_to`, `disposed_notes`. Soft-delete only — undoable via
  `DELETE /api/hats/{id}/dispose`. Disposed hats free their case slot
  but remain in the DB (history preserved). `GET /api/hats?status=`
  defaults to `active`; `disposed` and `all` available. Hat detail
  page gets a Disposition card with a modal form for disposing +
  an "Undo — restore" action. Valuation page surfaces realized values.
- **Bulk photo import.** Multipart upload of up to 100 photos creates
  an `import_jobs` row + `import_job_items` per file, queues a single
  background asyncio worker that runs the existing pipeline one-at-a-time
  (resize → bg-remove → Claude → DB). Per-file status, hat-id link
  on completion, cancellation. Survives container restart (queued
  items re-enqueue at boot). New `/hats/import` page with drag-drop
  + per-file progress + defaults (style/size/condition/case) applied
  to every hat.

### Changed
- `_validate_capacity` skips disposed hats — sold/lost hats no longer
  count against case capacity.
- `_get_next_position` excludes disposed hats — the slot reopens.

### Tests: 81 → 93 (+12)
- `tests/test_disposition.py` — dispose + undispose + status filter +
  capacity-respecting-disposed.
- `tests/test_activity_log.py` — log emission, count endpoint, filters.
- `tests/test_import.py` — job creation, item structure, content-type
  rejection, cancellation. Worker disabled in conftest so jobs stay
  queued for assertion.

---

## [0.2.2] — 2026-05-02 — _author-question follow-ups_

Closes the action items from the 10 reviewer questions in the archaeology bundle's
`00-READ-FIRST.md`. Six questions, six fixes.

### Added
- **Configurable Claude model in Settings UI.** New `app_settings.anthropic_model`
  row, `GET/PUT/DELETE /api/settings/model`, datalist of known model ids on the
  Settings page. Resolution: DB > env > built-in default. (`anthropic_model` is
  passed all the way through `analyze_hat_image(model=…)`.)
- **In-app "Recent Analysis Errors" view** (`/api/admin/recent-errors`) listing
  the last 20 hats whose analysis failed, newest first, with thumbnail + error
  message + timestamp. Companion `/api/admin/recent-errors/count` powers a
  pulsing red badge on the Settings nav item — surfaces silent pipeline failures
  without anyone tailing `docker logs`.
- **One-click backup download** (`GET /api/admin/backup`) — streams a gzipped
  tar of `/data/{headroom.db, uploads/}` with an `attachment` content-disposition.
- **Scheduled rolling backups.** Background asyncio task writes a timestamped
  tar.gz to `/data/backups/` every 24 h (configurable: `HEADROOM_BACKUP_INTERVAL_HOURS`,
  `HEADROOM_BACKUP_RETENTION_DAYS=7`, `HEADROOM_BACKUP_ENABLED`). Cancelled
  cleanly on lifespan exit. Initial snapshot at startup so a fresh deploy isn't
  one bad sector away from total loss.
- **"Unassigned / In a Case / All" quick-chips** on the Hats page (auto-shown
  when there are unassigned hats), so case-orphaned hats are never invisible.
- **`/api/admin/*` route group** behind `require_admin` — same Bearer-token gate
  as the api-key endpoints.

### Changed
- `verify_api_key` now takes a model parameter and reports it in the success
  message (`"OK — model 'X' reachable."`) so the test button validates the
  active model+key combo rather than just the key.
- Bumped version to 0.2.2.

### Removed
- Stray dev SQLite files (`headroom.db`, `frontend/headroom.db`) — both were
  gitignored, just disk hygiene.

### Tests: 72 → 81 (+9)
- `tests/test_admin.py` — model setting CRUD + validation, recent-errors
  endpoints, backup gzip download (verifies content-type + payload size +
  attachment header), admin auth gate when token is set.

### Verified
- Live container: `/api/settings/model` GET → default → PUT → database → DELETE → default.
- Backup: GET returns valid gzip (~27 KB on a fresh DB), starts with the right
  Content-Disposition header, `file(1)` confirms gzip integrity.
- Container logs show `basicConfig` working, scheduler started, initial snapshot
  written, and the unset-token warning fires.

---

## [0.2.1] — 2026-05-02 — _post-archaeology hardening_

A focused security + reliability pass driven by a full-repo `/code-archaeology`
run. Closes the critical issues the audit surfaced and lifts the diagnosis
from "ready with conditions" toward "ready."

### Security
- **CRITICAL: Path traversal in SPA fallback handler closed.**
  `app.py:_safe_spa_path` now resolves the requested path and verifies it's
  inside `FRONTEND_DIST` before serving via `is_relative_to`. Previously
  `GET /%2e%2e/data/headroom.db` would return the SQLite database (and the
  Anthropic key inside it) to any caller. Verified against the live
  container: traversal attempts now return the 662-byte `index.html`
  fallback, not the 49KB DB. (`tests/test_security.py`)
- **Optional admin-token guard** on `/api/settings/api-key` PUT/DELETE/test
  via `HEADROOM_ADMIN_TOKEN`. Unset → endpoints stay open (single-user-LAN
  default) with a startup warning. Set → `Authorization: Bearer <token>`
  required, constant-time compare. (`src/headroom/auth.py`)

### Reliability / performance
- **Dropped the upload concurrency footgun.** `background_removal.py` no
  longer wraps `asyncio.to_thread` in a process-global `asyncio.Lock`;
  inference now runs on whatever worker threads asyncio's executor provides.
  A small `_init_lock` still guards the one-shot ONNX session creation.
- **Pillow no longer blocks the event loop.** `utils/photo.process_image_async`
  wraps the existing sync function via `asyncio.to_thread`; the hat upload
  route uses it. Concurrent uploads no longer wedge other requests.
- **Real `/health/ready` endpoint** that probes the DB (`SELECT 1`),
  upload-dir writability, and reports API-key configuration.
  `docker-compose.yml` now points the container `HEALTHCHECK` at it.
- **Default logging is now visible.** `app.py` calls `logging.basicConfig`
  on startup if no root handlers are configured, so `logger.warning` calls
  in `background_removal` and `hat_analysis_pipeline` actually reach
  `docker logs`. Level via `HEADROOM_LOG_LEVEL`.
- **Docker log rotation.** `docker-compose.yml` pins `max-size: 10m` and
  `max-file: 5` on the JSON log driver — no more silent SD-card fill from
  unbounded uvicorn access logs.
- **Function-local imports in `reanalyze_hat` removed.** Routes now have
  clean top-level imports for `analyze_hat_image`, `_apply_analysis`,
  `settings_service`. (`routes/hats.py`)

### Tests
- **+8 tests** covering the gaps the archaeology surfaced (72 total, all green):
  - `tests/test_pipeline_e2e.py` — happy-path Claude analysis with
    structured-response stub, reanalyze, and error-path coverage. The
    test the v0.2.0 release was missing.
  - `tests/test_security.py` — path-traversal regression + admin-token
    enforcement.
  - `tests/test_health.py` — readiness probe.

### Cleanup
- Removed unused `beautifulsoup4` dependency.
- Removed dead duplicate-branch in `utils/photo.py:25-28`.
- Removed vestigial `pending` from the `analysis_status` comment in `models/hat.py`
  (no code path ever wrote it).
- Clarified `anthropic_model` default with an inline comment + pointer to the
  `/api/settings/api-key/test` verification endpoint.

## [0.2.0] — 2026-05-02 — _"Outrun"_

The big one. Full UI rebuild + AI-powered hat identification.

### Added
- **Claude Vision analysis** for every uploaded hat photo. Single tool-use call
  to `claude-sonnet-4-6` returns brand, specific model name, model confidence
  (`high` / `medium` / `low`), style descriptor, design notes, primary /
  secondary / tertiary / accent colors with name + hex + tier, and an estimated
  new retail price in USD. Prompt caching enabled on the system prompt.
  (`src/headroom/services/claude_analysis.py`)
- **Background removal** via [`rembg`](https://github.com/danielgatis/rembg)
  with ONNX runtime. Hat photos save as transparent PNGs and float on the
  synthwave canvas. Default model is `u2netp` (4.7 MB) for Pi-friendliness;
  swap to `u2net` / `isnet-general-use` via `HEADROOM_REMBG_MODEL`.
  (`src/headroom/services/background_removal.py`)
- **Hat record** now stores: `brand`, `model_name`, `model_confidence`,
  `style_descriptor`, `design_notes`, `estimated_new_price`,
  `estimated_new_price_source`, `resale_price`, `resale_price_source`,
  `resale_price_url`, `resale_checked_at`, `analysis_status`, `analysis_error`,
  `analyzed_at`. `HatColor` gets a `tier` column.
- **Melin Recap deep-linking**: hats Claude identifies as Melin get a link to
  the matching filter page on melinrecap.com for live resale comparables.
  (`src/headroom/services/melin_recap.py`)
- **Settings page — Claude API key management.** Get / Set / Delete / Test
  connection endpoints; stored in DB (masked on read) with env-var fallback.
  (`src/headroom/routes/settings.py`, `tests/test_settings_api.py`)
- **`POST /api/hats/{id}/reanalyze`** — re-run Claude on an existing photo
  without re-uploading.
- **AppSetting** key/value model + table for app-level configuration.
  (`src/headroom/models/app_setting.py`)
- **Dockerfile** (multi-stage, multi-arch amd64+arm64, runs as non-root
  `headroom` user, pre-caches rembg model) and **docker-compose.yml** for
  one-command Pi deployment.
- **CHANGELOG.md** (this file) and a real **`.gitignore`**.

### Changed
- **Total frontend rebuild** — dropped Bootstrap 5 entirely. Synthwave / retro-80s
  design system: near-black canvas, neon hot-pink + cyan accents, sunset
  gradients, perspective grid background (desktop), Audiowide / Orbitron /
  Inter / JetBrains Mono typography, glow effects on primary actions, animated
  carousel with swipe gestures, glassmorphic modals + lightbox. CSS bundle
  shrunk from ~250 KB (Bootstrap) to **29 KB**.
- **Mobile / iPad first.** All layouts start single-column and progressively
  enhance. Tap targets ≥ 44 px. Bottom nav is the primary nav on portrait
  devices; top nav only renders at `lg+`. `viewport-fit=cover` and safe-area
  padding for notched devices.
- **Photo upload pipeline** is now: upload → resize/HEIC convert → background
  removal → Claude Vision → persist. Each step degrades gracefully. The
  canonical photo is the transparent PNG when bg-removal succeeds, the JPEG
  otherwise.
- **Search** now indexes brand alongside style/condition/size/colors/room.
- **Hats listing + gallery cards** show brand + model when known.
- **Hat detail page** redesigned with discrete sections: Identification (brand
  / model / confidence / Claude's design notes), Photo + Reanalyze, Valuation
  (new + resale tiles + Melin Recap CTA), Specs, Case, Color palette with
  tiered breakdown.
- **Edit Hat page** lets you override every Claude-derived field manually.
- **Database migrations** extended to add the new hat columns + `tier` on
  `hat_colors` + the new `app_settings` table. Existing DBs upgrade in place.

### Removed
- `colorthief` + `webcolors` dependencies (replaced by Claude Vision).
- `src/headroom/services/color_service.py`.
- Bootstrap CSS + JS imports from the frontend.

### Security
- Dockerfile runs as non-root user `headroom` (uid 1000) — addresses the
  semgrep finding about implicit-root containers.
- Inline-migration DDL is now fully static — no f-string interpolation into
  `text()` even for trusted column names.
- API keys are masked on read; only the prefix and last four characters are
  ever sent over the wire.

### Notes / known limitations
- The pipeline runs synchronously inside the upload request, so a hat upload
  with Claude + bg removal can take 5–15 s on a Pi. A future release may move
  this to a background queue.
- Melin Recap doesn't expose a stable JSON API and the listing page is
  client-rendered, so the resale_price field stays null and we surface a
  browse link instead of fabricating a number.

---

## [0.1.0] — 2026-02-22

Initial release. FastAPI + React SPA. Rooms / Cases / Hats domain. Local
ColorThief-based color detection. Bootstrap 5 navy/gold theme.
