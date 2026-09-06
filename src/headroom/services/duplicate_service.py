"""Finding hats that are probably the same hat, entered twice.

Bulk import from a camera roll is the main way this happens: two photos of one
hat, taken from slightly different angles, become two rows that both analyze
plausibly. At forty hats you notice; at two hundred you don't, and the
collection quietly reports more than you own — which then flows into the
valuation.

Grouping is on the IDENTITY fields, never the photo. Two shots of one hat look
different enough to defeat naive image comparison, and two genuinely different
hats in the same colorway look nearly identical — so pixels are the wrong
signal in both directions. What a person actually uses is "same model, same
colorway, same size", which is exactly what these fields hold.

Nothing is deleted here. This reports candidates; disposing or deleting stays a
deliberate act, because a real pair — the same cap bought twice, one kept new
in the box — is a perfectly normal thing to own.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat
from headroom.services.hat_service import hat_loads
from headroom.services.vocabulary import fold

# A group whose members agree on every identity field we have. Reported first.
EXACT = "exact"
# Same model and size, but the colorway differs or is missing on one side.
# Worth surfacing — an unanalyzed twin usually has no colorway yet.
LIKELY = "likely"


@dataclass(frozen=True)
class DuplicateGroup:
    key: str
    confidence: str
    label: str
    hats: list[Hat]


def _norm(value: str | None) -> str:
    """Fold a field for comparison. Empty for anything not stated."""
    return fold(value) if value else ""


def _identity(hat: Hat) -> tuple[str, str, str, str, str]:
    return (
        _norm(hat.brand),
        _norm(hat.model_name),
        _norm(hat.colorway),
        _norm(hat.construction),
        _norm(hat.size),
    )


def _is_identifiable(hat: Hat) -> bool:
    """Whether a hat has enough recorded to be worth comparing at all.

    Without this, every un-analyzed hat matches every other un-analyzed hat on
    "same size, same style" and the report is one enormous useless group. A
    model name — or a brand plus a colorway — is the least that makes two rows
    meaningfully the same thing.
    """
    return bool(hat.model_name) or bool(hat.brand and hat.colorway)


def _label(hat: Hat) -> str:
    parts = [p for p in (hat.brand, hat.model_name, hat.colorway) if p]
    return " · ".join(parts) if parts else f"Hat #{hat.id}"


async def find_duplicates(db: AsyncSession) -> list[DuplicateGroup]:
    """Groups of active hats that look like the same hat entered more than once.

    Disposed hats are excluded: one sold and one kept is not a duplicate, it is
    a record of what happened.
    """
    hats = (
        (
            await db.execute(
                select(Hat)
                .options(*hat_loads())
                .where(Hat.disposed_at.is_(None))
                .order_by(Hat.id)
            )
        )
        .scalars()
        .all()
    )
    candidates = [h for h in hats if _is_identifiable(h)]

    exact: dict[tuple, list[Hat]] = {}
    for hat in candidates:
        exact.setdefault(_identity(hat), []).append(hat)

    groups: list[DuplicateGroup] = []
    grouped_ids: set[int] = set()
    for key, members in exact.items():
        if len(members) < 2:
            continue
        grouped_ids.update(h.id for h in members)
        groups.append(
            DuplicateGroup(
                key="|".join(key),
                confidence=EXACT,
                label=_label(members[0]),
                hats=members,
            )
        )

    # Second, looser pass over what the first didn't claim: same model and
    # size, colorway not agreeing. Usually a twin that hasn't been analyzed
    # yet, so it has the model but no colorway.
    loose: dict[tuple, list[Hat]] = {}
    for hat in candidates:
        if hat.id in grouped_ids or not hat.model_name:
            continue
        loose.setdefault((_norm(hat.model_name), _norm(hat.size)), []).append(hat)

    for key, members in loose.items():
        if len(members) < 2:
            continue
        # Only when the colorways don't actively disagree. Two hats that each
        # name a DIFFERENT colorway are two hats someone deliberately owns —
        # grouping "Trenches Icon Black" with "Trenches Icon Navy" would report
        # every collector's normal shelf as a mistake, which is the fastest way
        # to make a report like this get ignored. At most one distinct
        # colorway means the rest simply haven't been analyzed yet.
        stated = {_norm(h.colorway) for h in members if h.colorway}
        if len(stated) > 1:
            continue
        groups.append(
            DuplicateGroup(
                key="likely|" + "|".join(key),
                confidence=LIKELY,
                label=_label(members[0]),
                hats=members,
            )
        )

    # Exact first, then biggest groups — the ones most worth acting on lead.
    groups.sort(key=lambda g: (g.confidence != EXACT, -len(g.hats), g.label))
    return groups
