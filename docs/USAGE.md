# Headroom Usage Guide

How to actually use Headroom day-to-day. For installing and running the
server, see [OPERATIONS.md](OPERATIONS.md).

---

## 1. First run

Open the app (`http://<host>:8000`). The first visit asks you to **create
the owner account** (username + password, 8+ characters) — everything in
the app requires signing in from then on. Once you're in, two things worth
doing immediately from **Settings → Account**:

- **Add a passkey** so future sign-ins are Face ID / Touch ID (works over
  HTTPS or on localhost).
- Note your **API token** — you'll need it if you set up the iOS Shortcut
  import (step: add an `Authorization: Bearer <token>` header).

Then configure the integrations in **Settings**:

1. **Claude API Key** — paste an Anthropic key
   ([console.anthropic.com](https://console.anthropic.com/)) and hit *Test
   connection*. This powers full hat identification: brand, specific model,
   colors, design notes, and an estimated retail price.
2. **Google Vision Key (optional)** — fallback brand detection for whenever
   Claude is unavailable. Colors fall back automatically without any key.
3. **eBay credentials (optional)** — a Production App ID + Cert ID enables
   sold-comparable price tiles.
4. **Logo (optional)** — upload your own; it replaces the default in the
   header and home page.

Nothing is mandatory: with zero keys, photos still upload, backgrounds are
still removed, and fallback color swatches still appear.

## 2. How things are organized

**Rooms → Cases → Hats.**

- **Rooms** are physical locations. The *Default Room* always exists (and
  can't be deleted — deleting another room moves its cases there).
- **Cases** hold hats and are type-exclusive (regular hats or beanies,
  never mixed). Default capacity is **4 regular / 6 beanies**, and each
  case can override it (e.g. 3 for a Melin case you don't want to cram).
  Cases get display IDs like `A-001` (archive) or `D-001` (daily wear),
  auto-sequenced.
- **Hats** can also live unassigned (no case). Sizes: small / classic /
  x-large.

## 3. Adding hats

Three ways, fastest first:

1. **One at a time** — *Hats → + New*. Pick or shoot a photo; a crop/rotate
   modal pops before saving. ~10 seconds per hat.
2. **Bulk import** — *Hats → ⇪* (or `/hats/import`). Select up to 100
   photos; a background worker processes them one at a time through the
   full pipeline. Progress is live; tap a finished row to jump to that hat.
   The queue survives restarts.
3. **Share sheet** —
   - **Android (Chrome)**: install Headroom as a PWA (browser menu →
     *Install app*); "Share to Headroom" then appears in the system share
     sheet. Multi-select works and drops straight into a bulk-import job.
   - **iOS**: Apple doesn't support web share targets, so open *Settings →
     Share Photos to Headroom* for a one-time Shortcut recipe. Afterwards,
     Photos → Share → *Add to Headroom*.

## 4. What happens to a photo

Upload → resized/HEIC-converted → background removed (the hat becomes a
transparent PNG floating on the synthwave canvas) → analyzed → priced.

The status pill on the hat page tells you which path you got:

| Pill | Meaning |
|---|---|
| **Analyzed** (green) | Full Claude identification: brand, model, colors, notes, estimated retail price |
| **Basic ID (fallback)** (orange) | No Claude (or Claude errored). Colors were read from the hat cutout itself — background colors are excluded by design — and, with a Google key, the brand from its logo. Model/price stay empty |
| **No API key** (purple) | No keys and no usable cutout; fill fields manually or add keys later |
| **Analysis failed** (red) | Claude errored and no fallback data was available; the error text is shown |

**Reanalyze** (on the hat page) re-runs the best available analysis against
the existing photo — use it after adding/fixing a key, or to refresh prices.
It upgrades fallback hats to full identification when a Claude key exists.

## 4½. Names & colorways

Melin retires colorways constantly, so **Settings → Colorway Catalog →
Refresh** harvests every model + colorway name currently circulating on the
melinrecap resale market (hundreds of entries, including long-sold-out
drops). After that, the Edit Hat form autocompletes both the model name and
the colorway ("Heather Ocean", "Sand Camo", …).

**Purchase history** (Settings → Purchase History) stores order line items
from your Melin emails; matched purchases automatically set a hat's
colorway and its **cost basis** — the price you actually paid, plus the
order date. Matching links a purchase to a hat when the model names agree
(and colorways don't conflict); re-run it any time after editing hats.

## 5. Colors & style

- Detected colors come as tiered swatches (primary / secondary / tertiary)
  and are searchable.
- **Tap a swatch to edit** — your correction sticks.
- The style you picked at creation (A-Game, Odysea, …) is **ground truth**:
  analysis never overwrites it.

## 6. Prices & valuation

Each hat can show up to three price signals:

- **New retail** — Claude's estimate of original price.
- **eBay median** — live sold-comparable stats when eBay creds are set
  (*Test connection* on the Settings card verifies the keyset; sandbox keys
  are flagged). Per-hat refresh button available.
- **Resale (Melin hats)** — a **live median asking price** from
  melinrecap.com's marketplace API, scoped to your hat's model when enough
  listings match (the label says e.g. "median of 83 live model listings"),
  plus a deep link to browse the actual listings. Refreshes on every
  analysis/reanalyze. You can always override `resale_price` manually.

The **Valuation** page rolls the whole collection up — including realized
value from hats you've sold.

## 7. Search — finding *the* hat

Two ways in, both returning cards with the photo, the hat's name (brand +
model when known), and **where it lives** ("📍 Case A-012 · Office"):

- **Text search** — multi-term AND across name, brand, style, condition,
  size, colors, and room (`navy classic melin` finds navy, classic-size
  Melins; `hydro` finds every Hydro). Color terms match the normalized
  palette vocabulary by default; toggle *exact colors* to match the
  analyzer's original phrasing. Disposed hats never appear — they're not
  findable on a shelf.
- **Search by color** — tap a palette swatch (or pick any color with the
  color-wheel input) and every hat is ranked by *perceptual closeness* to
  it, using the actual stored hex values rather than names. A hat whose
  secondary color matches still surfaces, with the matched swatch and a Δ
  distance shown on the card. This is the "show me light blue options"
  flow — it works no matter what the color was called.

## 8. Selling / disposing

*Dispose* on a hat page records sold / gifted / traded / lost / trashed,
with price + buyer note for sales. Disposal is a **soft delete**: the hat
keeps its history, frees its case slot, and disappears from default lists
(`?status=disposed` / *all* views exist). Sold prices feed the Valuation
page's realized totals. Undo restores the hat — back into its case if
there's still room, unassigned otherwise.

## 9. Reports & backups

- **Inventory report** — Settings → *Inventory report* renders a
  printer-friendly HTML report (thumbnails, totals, best-available value
  per hat). Use the browser's Print → *Save as PDF* for an insurance rider.
- **Backup** — Settings → *Backup* downloads a `tar.gz` of the database +
  photos on demand; scheduled backups run server-side (see
  [OPERATIONS.md §4](OPERATIONS.md#4-backups--restore)).

## 10. Install it like an app

Headroom is a PWA designed mobile-first:

- **iOS**: Safari → Share → *Add to Home Screen* → fullscreen app with
  proper icons.
- **Android**: Chrome → menu → *Install app* — this also unlocks the
  share-sheet import (§3).

## 11. Showing off: share links

**Settings → Share Links** creates read-only links (`/share/<token>`) you
can send to anyone — they see the gallery (photos, names, colors, where
each hat lives) without logging in, and can't change anything. Revoke a
link any time; optionally give it an expiry when creating. Great for the
group chat.

## 12. Audit trail

Every significant change (creates, edits, dispositions, imports, setting
changes) lands in an append-only activity log — the Settings page shows
recent entries. Old entries are pruned automatically after the retention
window (90 days by default).
