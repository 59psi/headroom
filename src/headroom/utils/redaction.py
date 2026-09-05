"""Strip bearer credentials out of anything about to be written down.

One definition, because there is more than one sink. A share token reaches
durable storage by at least three routes — uvicorn's access log, the
`error.unhandled` activity row, and the app logger line beside it — and the
first version of this fix covered only the access log. Two of the three were
left leaking by a change whose entire subject was the leak, which is the
argument for a shared helper over a regex applied at whichever call site was
in view at the time.
"""

from __future__ import annotations

import re

#: Any share-link token appearing in a URL path.
#:
#: A share token is a 256-bit bearer credential and it is a PATH parameter
#: (`/api/public/share/{token}`, `/share/{token}`), so every component that
#: records a request path records the credential in clear. This is the same
#: class as the documented `?key=` incident that moved the Google Vision key
#: out of a query string, one layer down — and it defeats the specific
#: mitigation `error_handler` had adopted against it. That handler deliberately
#: stores `path` and never the full URL, on the stated grounds that "query
#: strings carry search terms and tokens"; here the secret is not in the query,
#: so recording the path IS recording the token.
#:
#: The `{16,}` floor keeps this from matching the literal route segments and
#: the SPA's own `/share/` page. Real tokens are `secrets.token_urlsafe(32)`,
#: which is 43 characters.
SHARE_TOKEN_IN_PATH = re.compile(r"(/(?:api/public/)?share/)[A-Za-z0-9_\-]{16,}")

REDACTED = "<redacted>"


def redact_share_tokens(text: str) -> str:
    """Replace any share token in `text` with a marker, leaving the route.

    Redaction rather than dropping the path: which endpoint 500'd is the
    single most useful field on an error row, and a handler that recorded no
    path to protect a token would trade a real diagnostic for it. The route
    stays legible (`/api/public/share/<redacted>`) and the credential does not.
    """
    return SHARE_TOKEN_IN_PATH.sub(rf"\1{REDACTED}", text)
