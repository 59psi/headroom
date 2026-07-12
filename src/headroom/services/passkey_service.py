"""WebAuthn passkeys via py_webauthn — thin, test-stubbable seams.

RP identity comes from config: HEADROOM_RP_ID must equal the domain the app
is served on (e.g. "hats.example.com"; "localhost" for dev) and
HEADROOM_ORIGIN the full origin ("https://hats.example.com"). Browsers only
offer passkeys in secure contexts — HTTPS or localhost — which the Caddy
overlay provides.

Challenges are held in-memory keyed by a one-time state id (single-process
app); they expire after 5 minutes.
"""

from __future__ import annotations

import json
import secrets
import time

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json

from headroom.config import settings
from headroom.models.user import PasskeyCredential, User

_CHALLENGE_TTL_S = 300
_challenges: dict[str, tuple[bytes, int | None, float]] = {}


def _store_challenge(challenge: bytes, user_id: int | None) -> str:
    now = time.monotonic()
    for key in [k for k, (_, _, exp) in _challenges.items() if exp < now]:
        _challenges.pop(key, None)
    state_id = secrets.token_urlsafe(16)
    _challenges[state_id] = (challenge, user_id, now + _CHALLENGE_TTL_S)
    return state_id


def pop_challenge(state_id: str) -> tuple[bytes, int | None] | None:
    entry = _challenges.pop(state_id, None)
    if entry is None or entry[2] < time.monotonic():
        return None
    return entry[0], entry[1]


def registration_options(user: User, existing: list[PasskeyCredential]) -> tuple[str, dict]:
    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name="Headroom",
        user_id=str(user.id).encode(),
        user_name=user.username,
        exclude_credentials=[
            {"id": base64url_to_bytes(c.credential_id)} for c in existing
        ]
        or None,
    )
    state_id = _store_challenge(options.challenge, user.id)
    return state_id, json.loads(options_to_json(options))


def verify_registration(credential: dict, challenge: bytes) -> dict:
    """Returns {credential_id, public_key, sign_count} (base64url strings)."""
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_origin=settings.origin,
        expected_rp_id=settings.rp_id,
    )
    return {
        "credential_id": bytes_to_base64url(verified.credential_id),
        "public_key": bytes_to_base64url(verified.credential_public_key),
        "sign_count": verified.sign_count,
    }


def authentication_options() -> tuple[str, dict]:
    """Discoverable-credential flow: the authenticator tells us who it is."""
    options = generate_authentication_options(rp_id=settings.rp_id)
    state_id = _store_challenge(options.challenge, None)
    return state_id, json.loads(options_to_json(options))


def verify_authentication(
    credential: dict, challenge: bytes, stored: PasskeyCredential
) -> int:
    """Returns the new sign count on success; raises on failure."""
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_origin=settings.origin,
        expected_rp_id=settings.rp_id,
        credential_public_key=base64url_to_bytes(stored.public_key),
        credential_current_sign_count=stored.sign_count,
    )
    return verified.new_sign_count
