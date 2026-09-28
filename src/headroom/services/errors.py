"""What a service says when it refuses — in domain terms, not HTTP ones.

Services used to raise `fastapi.HTTPException` directly. That works for a
route and nowhere else: the bulk-import worker calls `hat_service.create_hat`
too, and it recorded a missing case as `"404: Case not found"` — an HTTP
status code leaking into a per-item error the owner reads on the import page.
`_undispose_hat_locked` went further and caught its own 404 and 409 to decide
where a restored hat lands, so an HTTP status stood in for a domain decision.

These carry only the sentence a person should read. The ROUTE layer decides
what each one means on the wire (`routes/_api.DomainErrorRoute`), which is the
layer that knows it is speaking HTTP. `str(exc)` is the sentence, so a
non-HTTP caller that records `str(exc)` records the sentence and nothing else.
"""

from __future__ import annotations


class DomainError(Exception):
    """A request the domain refuses. `detail` is the sentence to show."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(DomainError):
    """The thing named does not exist (or no longer does)."""


class Conflict(DomainError):
    """The request is well-formed but the current state forbids it — a full
    case, a type mix, a hat that is disposed."""


class Invalid(DomainError):
    """The request cannot be carried out as stated — deleting the default
    room, asking for a room when none exists."""
