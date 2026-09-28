"""The API's route table, and which parts of it demand a signed-in user.

Two layers guard the data-bearing routes. `AuthGateMiddleware` is the first:
it refuses an anonymous caller on every protected PATH before routing runs.
The second is here — `require_user` attached to each protected ROUTER as it is
included — so a route that ends up outside the gate's prefixes (a new
top-level path, a prefix edited by one character, the middleware dropped from
`create_app`) still answers 401 instead of serving the collection. Until this,
`require_admin` was attached to the admin router alone, and its presence there
read as a guard for modules that had none: with the gate out of the picture,
26 routes — deleting a hat, the logo, creating share links, the share target —
answered an anonymous caller. `tests/test_route_layer.py` removes the gate and
enumerates the route table to hold both layers to the same answer.

The open routers are the ones whose whole point is to be reachable signed
out: health probes, the way in (`auth`), and the token- or setting-gated
public views. They are listed apart so an open router is a decision someone
wrote down, not a guard someone forgot.
"""

from fastapi import APIRouter, Depends

from headroom.auth import require_user
from headroom.routes import (
    admin,
    auth,
    ca_cert,
    cases,
    guest,
    hats,
    health,
    import_jobs,
    meta,
    public,
    rooms,
    search,
    settings,
    share,
    share_links,
)

#: Reachable signed out. `auth` guards its own session-only routes per route
#: (`/me`, the token, passkey management), because its login and setup must
#: stay open.
_OPEN = (
    health.router,
    public.router,
    auth.router,
    share_links.public_router,
    guest.router,
    ca_cert.router,
)

#: Everything else. `import_jobs` before `hats` is no longer load-bearing —
#: the hat routes take `{hat_id:int}`, which cannot match `import`, and
#: `tests/test_route_layer.py` holds that collision closed — but it is the
#: order the table has always had.
_PROTECTED = (
    cases.router,
    import_jobs.router,
    hats.router,
    rooms.router,
    meta.router,
    search.router,
    settings.router,
    admin.router,
    share.router,
    share_links.router,
)

api_router = APIRouter()
for _router in _OPEN:
    api_router.include_router(_router)
for _router in _PROTECTED:
    api_router.include_router(_router, dependencies=[Depends(require_user)])
