"""The route class every router here is built with.

Services raise `services.errors.DomainError` subclasses and know nothing about
HTTP; this is where each one becomes a status code. It is a route class rather
than an app-level exception handler because the translation belongs to the
route layer, and a route class is how a router states its own behavior —
`tests/test_route_layer.py` checks every router uses it, so a new router that
forgets reads as a failing test instead of a 500 on its first refusal.

The mapping is by class, most specific first, and deliberately small: a new
kind of refusal is a new subclass in `services/errors`, and forgetting to map
it here fails the census test rather than surfacing as a 500.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from headroom.services import errors

#: Domain refusal → HTTP status. Exhaustive over `errors.DomainError`'s
#: subclasses; `tests/test_route_layer.py` holds it to that.
STATUS_FOR: dict[type[errors.DomainError], int] = {
    errors.NotFound: 404,
    errors.Conflict: 409,
    errors.Invalid: 400,
}


def http_error(exc: errors.DomainError) -> HTTPException:
    """The HTTPException a domain refusal answers as."""
    for cls in type(exc).__mro__:
        status = STATUS_FOR.get(cls)
        if status is not None:
            return HTTPException(status_code=status, detail=exc.detail)
    # An unmapped subclass is a programming error, and it should look like one
    # — the census test exists so this line is never reached in practice.
    raise exc


class DomainErrorRoute(APIRoute):
    """An APIRoute that answers a `DomainError` with its mapped status."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except errors.DomainError as exc:
                raise http_error(exc) from exc

        return handler
