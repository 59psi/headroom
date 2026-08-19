"""The collection as a zip you can hand to someone.

Share links already exist and are the better answer when the recipient can
reach the app — they stay current and can be revoked. This is for when they
can't: the app lives on a Pi at `headroom.local`, which resolves for nobody
off that LAN, so "show someone the collection" otherwise means being in the
house.

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

import io
import logging
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

logger = logging.getLogger(__name__)


def _image_name(hat: Hat) -> str | None:
    """Filename to use inside `images/`, or None when the hat has no photo.

    Keyed on the hat id, not the display id: an unassigned hat has no display
    id at all, and two hats can briefly share one during a case reshuffle.
    """
    source = hat.thumb_path or hat.photo_path
    if not source:
        return None
    return f"{hat.id}{Path(source).suffix or '.webp'}"


def _hat_card(hat: Hat, image_name: str | None, include_values: bool) -> str:
    bits: list[str] = []
    if hat.colorway:
        bits.append(escape(hat.colorway))
    if hat.construction:
        bits.append(escape(hat.construction))
    bits.append(escape(hat.size.replace("_", " ")))
    subtitle = " · ".join(bits)

    swatches = "".join(
        f'<i style="background:{escape(c.hex_value)}" title="{escape(c.general_color or c.color_name)}"></i>'
        for c in sorted(hat.colors or [], key=lambda c: c.dominance_rank)
        if c.hex_value
    )

    img = (
        f'<img src="images/{escape(image_name)}" alt="" loading="lazy">'
        if image_name
        else '<div class="noimg"></div>'
    )

    price = ""
    if include_values and hat.resale_price:
        price = f'<p class="price">${hat.resale_price:,.0f}</p>'

    # `story` is the whole reason this export is worth reading rather than
    # scrolling. Rendered as paragraphs because it is written as prose.
    story = ""
    if hat.story:
        paras = "".join(
            f"<p>{escape(p.strip())}</p>"
            for p in hat.story.split("\n")
            if p.strip()
        )
        story = f'<div class="story">{paras}</div>'

    notes = (
        f'<div class="notes"><h4>Notes</h4><p>{escape(hat.owner_notes)}</p></div>'
        if hat.owner_notes
        else ""
    )

    where = " · ".join(
        p for p in (
            f"Case {escape(hat.case.display_id)}" if hat.case else None,
            escape(hat.case.room.name) if hat.case and hat.case.room else None,
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
    {story}
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
  .story {{ margin-top:.9rem; padding-top:.9rem; border-top:1px solid var(--line);
            font-size:.9rem; }}
  .story p {{ margin:0 0 .7rem; }}
  .story p:last-child {{ margin-bottom:0; }}
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

    Built in memory: the images are the gallery thumbnails (320px WebP, tens of
    KB each), so a few hundred hats is single-digit MB — small enough that
    streaming from a temp file would add moving parts for no benefit, and the
    Pi has the headroom. Revisit if a collection ever reaches thousands.
    """
    stmt = (
        select(Hat)
        .options(selectinload(Hat.case).selectinload(Case.room), selectinload(Hat.colors))
        .order_by(Hat.id)
    )
    if not include_disposed:
        stmt = stmt.where(Hat.disposed_at.is_(None))
    hats = list((await db.execute(stmt)).scalars().all())

    buf = io.BytesIO()
    cards: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for hat in hats:
            name = _image_name(hat)
            if name:
                source = settings.upload_dir / (hat.thumb_path or hat.photo_path)
                try:
                    zf.write(source, f"images/{name}")
                except OSError:
                    # A missing file must not cost the whole export — the card
                    # simply renders without a photo.
                    logger.info("Export: photo missing for hat %s (%s)", hat.id, source)
                    name = None
            cards.append(_hat_card(hat, name, include_values))

        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        zf.writestr("index.html", _PAGE.format(
            title=escape(title),
            count=len(hats),
            generated=generated,
            cards="\n".join(cards),
        ))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return buf.getvalue(), f"headroom-collection-{stamp}.zip"
