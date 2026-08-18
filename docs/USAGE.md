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

- **Rooms** are physical locations. Exactly one is the **default**: new cases
  go there when you don't pick a room, and deleting a room moves its cases
  there. That makes it the only room you can't delete — hit **Make default**
  on another room first, then the original is deletable like any other.
- **Cases** hold hats and are type-exclusive (regular hats or beanies,
  never mixed). A case is **full at 3 hats** (or 6 beanies) — that's what the
  physical case is built for. A 4th still fits, so Headroom accepts it and
  marks the case **overfull** rather than refusing something that works or
  pretending it's normal. One over is the whole allowance; the 5th is
  refused. Each case can override the number (e.g. 2 for one you don't want
  to cram) — **a capacity you set is exact and gets no overfill latitude**,
  since avoiding the cram is the reason to set it.
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

Upload → resized/HEIC-converted → **the request returns straight away**. The
slow part — background removal (the hat becomes a transparent PNG floating on
the synthwave canvas), Claude identification, then pricing — is handed to a
background worker, so you can keep adding hats while earlier ones are still
analysing. The hat page polls until the analysis reaches a final state.

The status pill on the hat page tells you where a hat is:

| Pill | Meaning |
|---|---|
| **2/4 · Identifying** | Queued or in progress — the number is which of the four pipeline steps is running. Nothing to do; the page updates itself when it finishes |
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

For anything the import can't cover — bought secondhand, in person, or from a
shop that doesn't email line items — enter **Price paid** and **Bought on**
directly on the Add Hat or Edit Hat form. Valuation lists the hats still
missing a price so the gap is visible rather than assumed.

**Import order matters.** Matching sets a hat's price *and* fills its
colourway, and a hat that hasn't been analysed yet will accept any colourway
of the right model and size. So add and analyse your hats *first*, then
import once — otherwise a purchase can attach to a stand-in hat and stamp the
wrong colourway on it. Add `?dry_run=true` to the import to see every proposed
match without writing anything.

If a run does go wrong, it's reversible: **unmatch** a single purchase, or
unmatch every one at once, which returns them all to the pool and clears the
values they set (leaving anything you've edited since alone). The purchase
records survive — only the links are broken — so you can re-run matching once
the collection is in better shape.

## 5. Colors & style

- Detected colors come as tiered swatches (primary / secondary / tertiary)
  and are searchable.
- **Tap a swatch to edit** — your correction sticks.
- The style you picked at creation (A-Game, Odysea, …) is **ground truth**:
  analysis never overwrites it.

## 6. Prices & valuation

### What each hat records

- **Paid** — what it actually cost you. The only figure here that's a fact
  rather than an estimate. Set it when adding a hat, on the edit page, or in
  bulk by importing order history (§4½).
- **New retail** — Claude's estimate of the original price.
- **eBay ask** — median of *currently listed* comparable items, when eBay
  creds are set (*Test connection* on the Settings card verifies the keyset;
  sandbox keys are flagged). Per-hat refresh button available.
- **Resale ask (Melin hats)** — median **asking** price across live
  melinrecap.com listings, scoped to your hat's model when enough listings
  match ("median of 83 live model listings") or to the whole style category
  when they don't, plus a deep link to browse them. Refreshes on every
  analysis.
- **Est. sale value** — the single number the collection totals use, derived
  from the above.

### How "est. sale value" is worked out

**Neither price feed knows what anything sold for.** eBay's Browse API returns
items currently for sale, and the melinrecap figure is a median over live
listings. Both are what sellers are *asking*. So each hat is valued from the
best signal it has:

1. **Your price** — if you typed a resale price, it's used exactly as given
   and nothing is applied to it. It's also protected: analysis will never
   overwrite it. Clear the field to hand the hat back to the live feed.
2. **Model comps** — the median ask across listings matching that model, cut
   15% for the gap between asking and selling, then adjusted for condition
   (new with tags 100% · new 92% · worn 78%) because the listings it came from
   are a mix of conditions and yours isn't.
3. **From retail** — no comps, so a share of estimated new retail: new with
   tags 65% · new 45% · worn 30%.
4. **Category average** — the weak one. No listings matched the model, so it
   borrows the median across the whole style category. That's the going rate
   for a hat of that shape, not a valuation of yours.
5. **Not valued** — nothing supports a number. These are counted and shown,
   never quietly totalled as $0.

The Valuation page shows how many hats sit on each basis, so you can see how
much of the total rests on the weaker ones.

> **If your totals dropped in 2.19.0:** they were overstated before. Asking
> prices were being summed at face value, and condition was ignored entirely
> whenever a market price existed — every copy of a model got the same number
> whether it was tagged or beaten.

The **Valuation** page rolls the whole collection up: what you've paid, retail
value, estimated sale value, unrealized gain against cost, and realized
proceeds from hats you've sold. **Stats** (`/stats`) is the full picture —
charts for condition, style, size, brand, construction, colourway, colour,
room, case fill, acquisitions and spend over time, plus leaderboards for most
valuable, most expensive, most worn and best cost-per-wear.

## 7. Search — finding *the* hat

Two ways in, both returning cards with the photo, the hat's name (brand +
model when known), and **where it lives** ("📍 Case A-012 · Office"):

- **Text search** — multi-term AND across name, brand, style, condition,
  size, colors, room, and artist/collab (`navy classic melin` finds navy,
  classic-size Melins; construction is matched as text, so `hydro` finds every
  HYDRO — and HYDROLite, which is a HYDRO-family build — while `hydrolite`
  stays precise and returns only those, and `canvas` finds a hat you recorded
  as Waxed Canvas; `skye walker` finds that signature series). Color terms match the normalized
  palette vocabulary by default; toggle *exact colors* to match the
  analyzer's original phrasing. Disposed hats never appear — they're not
  findable on a shelf.
- **Find duplicates** — the button beside the Search heading (or `/duplicates`).
  Bulk-importing a camera roll can turn two photos of one hat into two hats,
  and past a hundred or so you stop noticing; the collection then reports more
  than you own and the valuation follows it. Grouped on what's *recorded* —
  model, colourway, size — never on the photos, since two shots of one hat look
  different and two different hats in one colourway look the same. **exact**
  means everything matches; **likely** means same model and size with a
  colourway missing on one side, which is what an unanalysed twin looks like.
  Two hats naming *different* colourways are never grouped. Nothing is deleted
  — open a hat and dispose of it, or leave it if you really do own two.
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

## 10½. Wear tracking & QR labels

Tap **🧢 Wearing this today** on a hat's page — that's the whole workflow.
Wear count, last-worn date, and **cost-per-wear** (what you paid ÷ wears)
show under the photo; the Valuation page's *Wear Rotation* card lists the
five hats that have gone longest without sun. Mis-taps: hit *undo*.

**🏷 Labels** (Cases page) opens a printable sheet of QR labels — one per
case with its ID, room, and fill count. Print, cut, stick on the physical
cases; scanning a QR with your phone camera opens that case in Headroom.

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
