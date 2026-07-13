"""Printable QR label sheet for cases.

One label per case: QR code (deep link to the case page), display id, room,
capacity. Rendered as a print-friendly HTML page — stick the printed labels
on the physical cases; scanning a QR opens that case's contents (login
required, as usual).

QR codes are generated as inline SVG (qrcode's SVG factory — no raster
step, crisp at any print size).
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


def _qr_svg(url: str) -> str:
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


async def render_case_labels(db: AsyncSession, base_url: str) -> str:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.room), selectinload(Case.hats))
        .order_by(Case.display_id)
    )
    cases = list(result.scalars().all())

    labels = []
    for c in cases:
        url = f"{base_url.rstrip('/')}/cases/{c.display_id}"
        hats = c.hats or []
        # Type default when no per-case override: 6 for beanie cases, else 4.
        capacity = c.capacity or (6 if any(h.is_beanie for h in hats) else 4)
        labels.append(f"""
        <div class="label">
          <div class="qr">{_qr_svg(url)}</div>
          <div class="meta">
            <div class="case-id">{escape(c.display_id)}</div>
            <div class="room">{escape(c.room.name if c.room else "")}</div>
            <div class="cap">{len(hats)}/{capacity} hats</div>
          </div>
        </div>""")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Headroom · Case Labels</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 1rem; }}
  .hint {{ color: #666; font-size: 0.85rem; margin-bottom: 1rem; }}
  .sheet {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }}
  .label {{ display: flex; gap: 10px; align-items: center; border: 1px dashed #999;
            border-radius: 8px; padding: 10px; break-inside: avoid; }}
  .qr svg {{ width: 84px; height: 84px; display: block; }}
  .case-id {{ font-size: 1.3rem; font-weight: 700; font-family: ui-monospace, monospace; }}
  .room {{ color: #444; }}
  .cap {{ color: #888; font-size: 0.8rem; }}
  @media print {{ .hint {{ display: none; }} }}
</style></head>
<body>
<p class="hint">Print this page (⌘P), cut along the dashed borders, stick on cases.
Scanning a QR opens that case in Headroom. {len(cases)} labels.</p>
<div class="sheet">{"".join(labels)}</div>
</body></html>"""
