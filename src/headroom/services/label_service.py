"""Printable QR label sheets for the physical objects: cases and hats.

Both sheets carry the same payload — a QR of the thing's tag URL (see
`tag_service`) plus enough text to identify it by eye — so they share one
renderer and differ only in what goes in the label body.

The URL is printed as text under every QR on purpose. Scanning is how you use
the label day to day, but writing an NFC tag means pasting that URL into a tag
writer, and a QR you have to scan to read back is a poor way to get text into
another app. It also makes a label self-describing if it ever outlives the
install that produced it.

QR codes are generated as inline SVG (qrcode's SVG factory — no raster step,
crisp at any print size).
"""

from __future__ import annotations

import io
from html import escape

import qrcode
import qrcode.image.svg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.services import capacity, tag_service


def _qr_svg(url: str) -> str:
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def _label(url: str, body: str) -> str:
    """One cut-out label: QR, caller's identifying text, and the URL beneath."""
    return f"""
        <div class="label">
          <div class="qr">{_qr_svg(url)}</div>
          <div class="meta">{body}
            <div class="url">{escape(url)}</div>
          </div>
        </div>"""


def _sheet(title: str, hint: str, labels: list[str]) -> str:
    """Print-friendly wrapper. Sizing is in mm because these get cut out and
    stuck on things — a QR below about 20mm stops being reliably scannable by
    a phone at arm's length, which is the only distance that matters here."""
    body = (
        "".join(labels)
        if labels
        else '<p class="empty">Nothing to print yet.</p>'
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Headroom · {escape(title)}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 10mm; }}
  .hint {{ color: #666; font-size: 0.85rem; margin-bottom: 6mm; max-width: 150mm; }}
  .sheet {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(64mm, 1fr)); gap: 4mm; }}
  .label {{ display: flex; gap: 3mm; align-items: center; border: 1px dashed #999;
            border-radius: 2mm; padding: 3mm; break-inside: avoid; }}
  .qr svg {{ width: 22mm; height: 22mm; display: block; }}
  .meta {{ min-width: 0; }}
  .ident {{ font-size: 1.15rem; font-weight: 700; font-family: ui-monospace, monospace; }}
  .name {{ color: #222; font-size: 0.9rem; overflow-wrap: anywhere; }}
  .sub {{ color: #666; font-size: 0.78rem; }}
  .url {{ color: #999; font-size: 0.6rem; font-family: ui-monospace, monospace;
          overflow-wrap: anywhere; margin-top: 1mm; }}
  .empty {{ color: #666; }}
  @media print {{ .hint {{ display: none; }} }}
</style></head>
<body>
<p class="hint">{hint}</p>
<div class="sheet">{body}</div>
</body></html>"""


async def render_case_labels(db: AsyncSession, base_url: str) -> str:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.room), selectinload(Case.hats))
        .order_by(Case.display_id)
    )
    cases = list(result.scalars().all())

    labels = []
    for c in cases:
        url = tag_service.tag_url(base_url, tag_service.CASE, c.display_id)
        # Occupancy comes from the one rule that owns it. This used to be
        # computed inline as `c.capacity or (6 if any beanie else 4)` — a third
        # copy of the rule `capacity.py` exists to centralize, and wrong two
        # ways, printed onto adhesive: 4 is the OVERFILL limit rather than
        # nominal capacity (so a full 3-hat case read "3/4", i.e. room for one
        # more), and `len(hats)` counted disposed hats that had already freed
        # their slot. Deferring also inherits the `capacity is not None` check,
        # though a stated 0 is unreachable while `CaseCreate` bounds it to
        # `ge=1`.
        active = [h for h in (c.hats or []) if h.disposed_at is None]
        beanies = sum(1 for h in active if h.is_beanie)
        regular = len(active) - beanies
        fit = capacity.evaluate(
            capacity=c.capacity, beanie_count=beanies, regular_count=regular
        )
        if beanies:
            used, nominal, kind = beanies, fit.max_beanie, "beanies"
        else:
            used, nominal, kind = regular, fit.max_regular, "hats"
        labels.append(
            _label(
                url,
                f"""
            <div class="ident">{escape(c.display_id)}</div>
            <div class="sub">{escape(c.room.name if c.room else "")}</div>
            <div class="sub">{used}/{nominal} {kind}</div>""",
            )
        )

    return _sheet(
        "Case Labels",
        f"Print this page (⌘P), cut along the dashed borders, stick on cases. "
        f"Scanning a QR opens that case in Headroom. {len(cases)} labels.",
        labels,
    )


async def render_hat_labels(
    db: AsyncSession, base_url: str, *, case_display_id: str | None = None
) -> str:
    """One label per active hat, ordered by where it physically sits.

    `case_display_id` narrows the sheet to a single case, which is how you
    actually do this: you tag a case's worth of hats at a time, with the case
    open in front of you, rather than printing sixty labels and then hunting
    for the hat each one belongs to.
    """
    stmt = (
        select(Hat)
        .options(selectinload(Hat.case))
        .where(Hat.disposed_at.is_(None))
    )
    if case_display_id:
        stmt = stmt.join(Hat.case).where(Case.display_id == case_display_id)
    hats = list((await db.execute(stmt)).scalars().all())

    # Shelf order: by case, then by position within it. Unassigned hats have no
    # case and sort last — they're the ones most likely to need a label, so they
    # must appear on the sheet, but they have no place in the ordering.
    hats.sort(
        key=lambda h: (
            h.case is None,
            h.case.display_id if h.case else "",
            h.position_in_case if h.position_in_case is not None else 0,
        )
    )

    labels = []
    for h in hats:
        url = tag_service.tag_url(base_url, tag_service.HAT, h.id)
        name = h.model_name or "Unidentified"
        detail = " · ".join(x for x in (h.colorway, h.size) if x)
        labels.append(
            _label(
                url,
                f"""
            <div class="ident">{escape(h.display_id or "unassigned")}</div>
            <div class="name">{escape(name)}</div>
            <div class="sub">{escape(detail)}</div>""",
            )
        )

    scope = f"case {case_display_id}" if case_display_id else "the whole collection"
    return _sheet(
        "Hat Labels",
        f"Print this page (⌘P), cut out, and stick each label inside its hat's "
        f"sweatband. Scanning a QR opens that hat's quick-wear screen — one tap "
        f"to log that you wore it. {len(labels)} labels for {escape(scope)}.",
        labels,
    )
