"""Insurance-grade inventory HTML report.

Server-renders a single-page HTML document with a print stylesheet. The
user hits Print → Save as PDF in their browser. Zero new dependencies vs.
WeasyPrint / xhtml2pdf, identical visual output, two-click flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.config import settings
from headroom.models.case import Case
from headroom.models.hat import Hat


def _fmt_dollars(v: float | None) -> str:
    return f"${v:,.0f}" if v is not None else "—"


def _best_value(h: Hat) -> tuple[float | None, str]:
    """Pick the most authoritative current-value figure for the report."""
    if h.ebay_median_price:
        return h.ebay_median_price, "eBay median"
    if h.resale_price:
        return h.resale_price, "manual"
    if h.estimated_new_price:
        return h.estimated_new_price, "Claude estimate"
    return None, "—"


async def render_report(
    db: AsyncSession,
    *,
    include_disposed: bool = False,
    include_photos: bool = True,
) -> str:
    """Return a fully-rendered standalone HTML page."""
    stmt = (
        select(Hat)
        .options(selectinload(Hat.case).selectinload(Case.room))
        .order_by(Hat.id)
    )
    if not include_disposed:
        stmt = stmt.where(Hat.disposed_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()

    total_count = len(rows)
    total_new = sum((h.estimated_new_price or 0) for h in rows)
    total_value = sum(_best_value(h)[0] or 0 for h in rows)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows_html = "\n".join(_row_html(h, include_photos) for h in rows)

    return _PAGE_TEMPLATE.format(
        generated=generated,
        total_count=total_count,
        total_new=_fmt_dollars(total_new),
        total_value=_fmt_dollars(total_value),
        rows=rows_html,
        version_label=escape(_version_label()),
    )


def _version_label() -> str:
    try:
        from importlib.metadata import version
        return f"Headroom v{version('headroom')}"
    except Exception:  # noqa: BLE001
        return "Headroom"


def _row_html(h: Hat, include_photos: bool) -> str:
    value, source = _best_value(h)
    case_label = h.case.display_id if h.case else "—"
    room_label = h.case.room.name if h.case and h.case.room else "—"
    photo_cell = ""
    if include_photos and h.photo_path:
        # Server-relative URL; works when the report is opened from the
        # same origin as the running app (which it is — `<a href="/api/admin/...">`).
        photo_cell = (
            f'<img src="/uploads/{escape(h.photo_path)}" alt="" '
            f'style="width:48px;height:48px;object-fit:contain;background:#f4f4f4;border-radius:4px;" />'
        )
    elif include_photos:
        photo_cell = '<div style="width:48px;height:48px;background:#eee;border-radius:4px"></div>'

    disposed_label = ""
    if h.disposed_at is not None:
        disposed_label = (
            f'<div style="font-size:10px;color:#c00;text-transform:uppercase;'
            f'letter-spacing:0.05em">Disposed: {escape(h.disposed_via or "")}</div>'
        )

    brand_model = " · ".join(p for p in [h.brand, h.model_name] if p) or h.style.replace("_", " ")

    return f"""
<tr>
  <td>{photo_cell}</td>
  <td><strong>{escape(h.case.display_id + '-' + f'{h.position_in_case:02d}') if h.case and h.position_in_case else '#' + str(h.id)}</strong>{disposed_label}</td>
  <td>{escape(brand_model)}</td>
  <td>{escape(h.condition.replace('_', ' '))}</td>
  <td>{escape(h.size.replace('_', ' '))}</td>
  <td>{escape(case_label)} / {escape(room_label)}</td>
  <td style="text-align:right">{_fmt_dollars(h.estimated_new_price)}</td>
  <td style="text-align:right"><strong>{_fmt_dollars(value)}</strong><div style="font-size:9px;color:#888">{escape(source)}</div></td>
</tr>
""".strip()


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Headroom Inventory Report</title>
<style>
  @page {{ size: A4 portrait; margin: 14mm; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    color: #1a1a1a; margin: 0; padding: 24px;
    -webkit-font-smoothing: antialiased;
  }}
  h1 {{ font-size: 22px; margin: 0 0 4px 0; letter-spacing: -0.01em; }}
  .meta {{ color: #555; font-size: 12px; margin-bottom: 24px; }}
  .totals {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
    margin-bottom: 18px;
    page-break-after: avoid;
  }}
  .totals .tile {{
    background: #f7f7f8; border: 1px solid #e3e3e6; border-radius: 8px;
    padding: 12px;
  }}
  .totals .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: #666; }}
  .totals .value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  thead th {{
    text-align: left; padding: 8px 6px; border-bottom: 2px solid #1a1a1a;
    text-transform: uppercase; letter-spacing: 0.04em; font-size: 9px;
  }}
  tbody td {{ padding: 8px 6px; border-bottom: 1px solid #e5e5e5; vertical-align: middle; }}
  tbody tr {{ page-break-inside: avoid; }}
  .footer {{
    margin-top: 28px; padding-top: 12px; border-top: 1px solid #ddd;
    color: #888; font-size: 10px; text-align: center;
  }}
  @media print {{
    body {{ padding: 0; }}
    .print-cta {{ display: none; }}
  }}
  .print-cta {{
    margin-bottom: 16px; padding: 12px 16px; background: #fff7e8;
    border: 1px solid #f0c14b; border-radius: 8px; font-size: 13px;
  }}
  .print-cta button {{
    margin-left: 12px; background: #1a1a1a; color: #fff;
    border: 0; border-radius: 6px; padding: 6px 14px;
    font-size: 12px; cursor: pointer;
  }}
</style>
</head>
<body>
<div class="print-cta">
  Use your browser's <strong>Print → Save as PDF</strong> to export this report.
  <button onclick="window.print()">Print now</button>
</div>

<h1>Hat Collection Inventory</h1>
<div class="meta">Generated {generated} · {version_label}</div>

<div class="totals">
  <div class="tile">
    <div class="label">Hats</div>
    <div class="value">{total_count}</div>
  </div>
  <div class="tile">
    <div class="label">Original Retail (sum)</div>
    <div class="value">{total_new}</div>
  </div>
  <div class="tile">
    <div class="label">Current Value (best estimate)</div>
    <div class="value">{total_value}</div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th></th>
      <th>ID</th>
      <th>Brand / Model</th>
      <th>Condition</th>
      <th>Size</th>
      <th>Case / Room</th>
      <th style="text-align:right">Original</th>
      <th style="text-align:right">Current</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>

<div class="footer">
  Generated by {version_label} for inventory / insurance documentation purposes.
</div>
</body>
</html>"""
