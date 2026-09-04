"""The collection as a zip you can hand to someone.

Share links already exist and are the better answer when the recipient can
reach the app — they stay current and can be revoked. This is for when they
can't: the app lives on a Pi at `headroom.local`, which resolves for nobody
off that LAN, so "show someone the collection" otherwise means being in the
house.

Images are re-encoded to 800px WebP at export time from the canonical photo
— not the 320px grid thumbnail, which looks soft the moment anyone opens
the zip on a laptop — and cached on disk so a second export is instant.

A zip of `index.html` + an `images/` folder rather than one HTML file with
base64 images: a self-contained file is neat until it is 8 MB of base64 that
no mail client will preview and every editor chokes on. A zip unpacks to a
folder you double-click, the images stay real files, and the whole thing works
offline forever with no server.

Deliberately a SHOWCASE, not the inventory report. `report_service` renders
the same collection as a valuation table for insurers; this is the version you
send a friend, so prices are opt-in (`include_values`) and off by default.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.config import settings
from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.utils.photo import export_derivative_path, make_export_image

logger = logging.getLogger(__name__)

#: A CSS colour literal, and nothing else.
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _safe_hex(value: str | None) -> str:
    """`value` if it is a plain 6-digit hex colour, otherwise "".

    `hex_value` is written by Claude against a tool schema that already
    specifies this exact shape, and it reached a `style="background:…"`
    attribute through `escape()` — which quotes HTML but knows nothing about
    CSS. So a value that broke its own schema (`red;background-image:url(...)`)
    would land inside a style attribute as CSS rather than as text.

    Not exploitable as shipped: the export's own CSP allows `img-src 'self'`,
    so the fetch that syntax buys is blocked, and it needs the analyzer to
    violate a schema it has never violated. But the export is a zip a person
    opens on some other machine, where this app's CSP does not apply, and
    "the model is well behaved" is not an access control. Validating at the
    sink also covers rows already in the database, which clamping on write
    would not.
    """
    return value if value and _HEX.match(value) else ""


def _image_name(hat: Hat) -> str | None:
    """Filename to use inside `images/`, or None when the hat has no photo.

    Keyed on the hat id, not the display id: an unassigned hat has no display
    id at all, and two hats can briefly share one during a case reshuffle.
    Always `.webp` — every image in the zip is re-encoded to one format, so the
    source extension is irrelevant.
    """
    if not (hat.photo_path or hat.thumb_path):
        return None
    return f"{hat.id}.webp"


def _export_image_path(source_rel: str) -> Path | None:
    """The 800px WebP for one photo, generating and caching it if needed.

    Normally a cache hit: the derivative is written when the photo is
    processed, and a boot-time sweep covers hats that predate that. This is
    the fallback for a photo that has somehow never been through either —
    kept because the alternative is silently omitting a hat from the zip.

    Keyed on the canonical photo's own filename and invalidated by mtime, so a
    re-cut regenerates itself without anything having to remember to clear it.

    Runs on a worker thread (see `_resolve_images`). It decodes a
    full-resolution photo and re-encodes at WebP `method=6`; doing that on the
    event loop, once per hat, is what made a first export of a few hundred
    hats several minutes of an app that answered nothing — and produced a
    download that appeared to do nothing at all.
    """
    source = settings.upload_dir / source_rel
    if not source.exists():
        return None

    cache = export_derivative_path(settings.upload_dir, source_rel)
    try:
        if cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime:
            return cache
    except OSError:
        pass
    return make_export_image(source, cache.with_suffix(""))


def _resolve_images(sources: list[tuple[int, str]]) -> dict[int, Path]:
    """Resolve every hat's export image, on ONE worker thread.

    Takes plain ids and relative paths, never ORM objects: touching a
    SQLAlchemy instance from another thread is how you discover a lazy load at
    the worst possible moment.

    Logs progress, because on a cold cache this is the slow part and a silent
    minute is indistinguishable from a hang — which is precisely the
    complaint that produced this function.
    """
    resolved: dict[int, Path] = {}
    misses = 0
    for index, (hat_id, source_rel) in enumerate(sources, start=1):
        path = _export_image_path(source_rel)
        if path is None or not path.exists():
            misses += 1
            continue
        resolved[hat_id] = path
        if index % 25 == 0:
            logger.info("Export: prepared %d/%d images", index, len(sources))
    if misses:
        # One line for the batch, not one per hat: a collection with a hundred
        # un-photographed hats should not bury the progress lines it needs.
        logger.info("Export: %d of %d hat(s) had no usable photo", misses, len(sources))
    return resolved


def _hat_card(hat: Hat, image_name: str | None, include_values: bool) -> str:
    bits: list[str] = []
    if hat.colorway:
        bits.append(escape(hat.colorway))
    if hat.construction:
        bits.append(escape(hat.construction))
    bits.append(escape(hat.size.replace("_", " ")))
    subtitle = " · ".join(bits)

    swatches = "".join(
        f'<i style="background:{_safe_hex(c.hex_value)}" title="{escape(c.general_color or c.color_name)}"></i>'
        for c in sorted(hat.colors or [], key=lambda c: c.dominance_rank)
        if _safe_hex(c.hex_value)
    )

    img = (
        f'<img src="images/{escape(image_name)}" alt="" loading="lazy">'
        if image_name
        else '<div class="noimg"></div>'
    )

    price = ""
    if include_values and hat.resale_price:
        price = f'<p class="price">${hat.resale_price:,.0f}</p>'

    notes = (
        f'<div class="notes"><h4>Notes</h4><p>{escape(hat.owner_notes)}</p></div>'
        if hat.owner_notes
        else ""
    )

    where = " · ".join(
        p for p in (
            f"Case {escape(hat.case_display_id)}" if hat.case_display_id else None,
            escape(hat.room_name) if hat.room_name else None,
        ) if p
    )

    return f"""<article class="hat">
  <div class="shot">{img}</div>
  <div class="meta">
    <p class="id">{escape(hat.display_id or f"#{hat.id}")}</p>
    <h3>{escape(" ".join(p for p in (hat.brand, hat.model_name) if p) or "Unidentified")}</h3>
    <p class="sub">{subtitle}</p>
    {f'<p class="series">{escape(hat.artist_series)}</p>' if hat.artist_series else ""}
    <div class="sw">{swatches}</div>
    {price}
    {f'<p class="where">{where}</p>' if where else ""}
    {notes}
  </div>
</article>"""


_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; --bg:#0b0710; --card:#170f1f; --line:#2e2140;
           --text:#ece7f2; --dim:#9c8fae; --cyan:#41e0e8; --pink:#ff4fa3; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:2rem 1rem 4rem; background:var(--bg); color:var(--text);
          font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  header {{ max-width:1100px; margin:0 auto 2rem; }}
  h1 {{ font-size:2rem; margin:0 0 .25rem; letter-spacing:.06em;
        background:linear-gradient(90deg,var(--cyan),var(--pink));
        -webkit-background-clip:text; background-clip:text; color:transparent; }}
  header p {{ margin:0; color:var(--dim); font-size:.9rem; }}
  main {{ max-width:1100px; margin:0 auto; display:grid; gap:1.25rem;
          grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); }}
  .hat {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
          overflow:hidden; display:flex; flex-direction:column; }}
  .shot {{ background:#0d0913; display:grid; place-items:center; padding:1rem; }}
  .shot img {{ width:100%; max-width:260px; height:auto; display:block; }}
  .noimg {{ width:100%; height:150px; border:1px dashed var(--line); border-radius:8px; }}
  .meta {{ padding:1rem 1.1rem 1.25rem; }}
  .id {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--cyan);
         margin:0 0 .1rem; font-size:.85rem; }}
  h3 {{ margin:0 0 .15rem; font-size:1.05rem; }}
  .sub {{ margin:0; color:var(--dim); font-size:.85rem; }}
  .series {{ margin:.35rem 0 0; color:var(--pink); font-size:.85rem; }}
  .sw {{ display:flex; gap:.3rem; margin:.6rem 0 0; }}
  .sw i {{ width:14px; height:14px; border-radius:50%; border:1px solid #0006; }}
  .price {{ margin:.5rem 0 0; font-weight:600; }}
  .where {{ margin:.5rem 0 0; color:var(--dim); font-size:.8rem; }}
  .notes {{ margin-top:.9rem; padding:.7rem .8rem; border-left:2px solid var(--cyan);
            background:#ffffff08; font-size:.88rem; }}
  .notes h4 {{ margin:0 0 .3rem; font-size:.75rem; text-transform:uppercase;
               letter-spacing:.08em; color:var(--dim); }}
  .notes p {{ margin:0; }}
  footer {{ max-width:1100px; margin:3rem auto 0; color:var(--dim); font-size:.8rem; }}
  @media print {{ body {{ background:#fff; color:#000; }}
                  .hat {{ break-inside:avoid; border-color:#ccc; }} }}
</style>
</head><body>
<header>
  <h1>{title}</h1>
  <p>{count} hats · exported {generated}</p>
</header>
<main>
{cards}
</main>
<footer>Generated by Headroom. Open <code>index.html</code> in any browser — no internet needed.</footer>
</body></html>
"""


async def build_export(
    db: AsyncSession,
    *,
    title: str = "The Collection",
    include_values: bool = False,
    include_disposed: bool = False,
) -> tuple[bytes, str]:
    """Return (zip_bytes, filename).

    Built in memory: 800px WebP images are tens of KB each, so a few hundred
    hats lands in single-digit MB — small enough that streaming from a temp
    file would add moving parts for no benefit. Revisit at thousands of hats.

    Three phases, in this order for a reason: resolve the images on a worker
    thread, render the HTML on the loop (it needs live ORM objects), then zip
    on a worker thread. The middle phase is pure string formatting and cheap;
    both others are CPU-bound and must not touch the event loop.

    That ordering is the fix for a real complaint — the export took far longer
    than a full database backup and appeared to produce nothing. It was
    generating every hat's 800px derivative inline, on the loop, which on a Pi
    is minutes of an app that answers no requests at all, with a
    full-resolution decode resident alongside rembg's model in a 1 GB
    container. Derivatives are now written when the photo is processed and
    swept in at boot, so this is normally a zip of files that already exist.
    """
    stmt = (
        select(Hat)
        .options(selectinload(Hat.case).selectinload(Case.room), selectinload(Hat.colors))
        .order_by(Hat.id)
    )
    if not include_disposed:
        stmt = stmt.where(Hat.disposed_at.is_(None))
    hats = list((await db.execute(stmt)).scalars().all())

    # Image work first, all of it on one worker thread. This used to run on
    # the event loop inside the card-rendering loop — one full-resolution
    # decode and slow WebP encode per hat — so a first export stopped the
    # whole app for minutes and the download produced nothing for the
    # duration. Only ids and relative paths cross the boundary.
    sources = [
        (hat.id, hat.photo_path or hat.thumb_path)
        for hat in hats
        if (hat.photo_path or hat.thumb_path)
    ]
    resolved = await asyncio.to_thread(_resolve_images, sources)

    # Cards second, on the loop, while the ORM objects are still attached and
    # their relationships loaded. Fast: string formatting only.
    cards: list[tuple[str, Path | None, str]] = []
    for hat in hats:
        path = resolved.get(hat.id)
        name = _image_name(hat) if path is not None else None
        cards.append((_hat_card(hat, name, include_values), path, name or ""))

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page = _PAGE.format(
        title=escape(title),
        count=len(hats),
        generated=generated,
        cards="\n".join(c for c, _p, _n in cards),
    )
    blob = await asyncio.to_thread(_zip_it, cards, page)
    return blob, f"headroom-collection-{generated}.zip"


def _zip_it(cards: list[tuple[str, Path | None, str]], page: str) -> bytes:
    """Pack the rendered page and the images. Pure CPU + disk — no ORM here."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _card, path, name in cards:
            if path is None or not name:
                continue
            try:
                zf.write(path, f"images/{name}")
            except OSError:
                # One unreadable file must not cost the whole download; the
                # card already rendered and simply shows no photo.
                logger.info("Export: could not add %s", path)
        zf.writestr("index.html", page)
    return buf.getvalue()
