# Headroom Usage Guide

How to actually use Headroom day-to-day. For installing and running the
server, see [OPERATIONS.md](OPERATIONS.md).

---

## 1. First run

Open the app (`http://<host>:8000`) and go to **Settings**:

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
- **Cases** hold hats and are type-exclusive: **4 regular hats** or
  **6 beanies**, never mixed. Cases get display IDs like `A-001`
  (archive) or `D-001` (daily wear), auto-sequenced.
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

## 7. Search

Multi-term search across style, condition, size, colors, brand, and room —
terms AND together (`navy classic melin` finds navy, classic-size Melins).
By default color terms match the human-friendly general color; toggle
*exact colors* to match precise CSS names. A room filter narrows scope
server-side.

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

## 11. Audit trail

Every significant change (creates, edits, dispositions, imports, setting
changes) lands in an append-only activity log — the Settings page shows
recent entries. Old entries are pruned automatically after the retention
window (90 days by default).
