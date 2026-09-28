"""I/O models for the auth routes.

These were declared inline in `routes/auth.py`. Every response the API returns
has a declared model — `tests/test_api_contract.py` enforces that over the
whole OpenAPI document — and this is the module where it matters most for the
REQUEST side too: these are the bodies on the unauthenticated surface, so
their validation rules — the password floor especially — should be readable
without opening the transport layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from headroom.schemas.common import label_text

# Argon2id makes long passwords cheap to verify, so the ceiling exists only to
# bound what gets hashed, not to constrain the user.
_PASSWORD_MIN = 8
_PASSWORD_MAX = 200


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    #: Only read by `/setup`, and only when `HEADROOM_SETUP_TOKEN` is set.
    #:
    #: On `Credentials` rather than a separate setup model because login and
    #: setup take the same body and splitting them means two schemas that can
    #: drift on the fields that actually matter. Ignored by `/login`, where an
    #: attacker supplying it achieves nothing.
    setup_token: str | None = None


class AuthStatus(BaseModel):
    needs_setup: bool
    authenticated: bool
    username: str | None = None
    #: Whether the login screen should offer "browse as a guest". Carried here
    #: rather than on its own endpoint because this is the one unauthenticated
    #: call the login page already makes, and a second would be a second
    #: round-trip before anything renders.
    #:
    #: `None` when guest view is off, and then EXCLUDED from the response
    #: entirely (`exclude_none`). Returning `false` would tell an anonymous
    #: caller "this install has a guest mode and it is switched off" — which is
    #: exactly the fact the guest routes' 404-rather-than-403 exists to keep to
    #: itself. Absent is what "off" looks like from outside.
    guest_view_enabled: bool | None = None

    @model_serializer(mode="wrap")
    def _hide_guest_view_when_off(self, handler):
        """Drop `guest_view_enabled` from the payload when it is off.

        Precisely this one field — `response_model_exclude_none` would have
        done it, but it would also have dropped `username` on an anonymous
        response, quietly changing a contract this change has no business
        touching.
        """
        data = handler(self)
        if self.guest_view_enabled is None:
            data.pop("guest_view_enabled", None)
        return data


class PasswordChange(BaseModel):
    # No floor on the current password: it is checked against the stored hash,
    # not accepted, and a length rule here would reject a legitimate holder of
    # a password that predates the current rules.
    current_password: str
    new_password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class PasswordConfirm(BaseModel):
    """Re-authentication for an operation a session alone must not authorize.

    Same reasoning as `PasswordChange.current_password` and the same absence of
    a length floor: this is checked against the stored hash, never accepted as
    a new secret.
    """

    current_password: str


class PasskeyRegisterVerify(BaseModel):
    state_id: str
    # `dict` rather than a modeled shape: this is the WebAuthn credential the
    # browser produced, and it is handed to the passkey library verbatim.
    # Re-declaring its structure here would be a second, drifting copy of the
    # spec that the library already implements.
    credential: dict
    # Cleaned and sized to `passkey_credentials.name` HERE, where the route
    # used to do `data.name[:80] or "Passkey"` at each of its two uses — and
    # stored control characters and bidi overrides verbatim. Cut rather than
    # refused: see `label_text`.
    name: label_text(80, default="Passkey") = "Passkey"


#: WebAuthn caps a credential id at 1023 bytes; unpadded base64url of that is
#: 1364 characters. Nothing longer can be a credential any authenticator made.
CREDENTIAL_ID_MAX_CHARS = 1364


class PasskeyLoginVerify(BaseModel):
    state_id: str
    #: Still the browser's object, handed to the passkey library verbatim, for
    #: the reason `PasskeyRegisterVerify.credential` gives — with ONE field
    #: checked here, because the login route reads that one field itself: it
    #: looks up the stored credential by `credential["id"]` before the library
    #: ever sees the assertion.
    #:
    #: Unchecked, that lookup took whatever JSON the anonymous caller sent. A
    #: list or an object as the id reached SQLAlchemy as a bind parameter,
    #: raised, and became a 500 — and every 500 writes a durable
    #: `error.unhandled` activity row, so an unauthenticated loop could write
    #: one row per request. A string of bounded length is what a credential id
    #: IS; anything else is a malformed body, and a 422 is its answer.
    credential: dict

    @field_validator("credential")
    @classmethod
    def _credential_id_is_a_bounded_string(cls, credential: dict) -> dict:
        credential_id = credential.get("id")
        if not isinstance(credential_id, str):
            raise ValueError("credential.id must be a string")
        if not 0 < len(credential_id) <= CREDENTIAL_ID_MAX_CHARS:
            raise ValueError(
                f"credential.id must be 1 to {CREDENTIAL_ID_MAX_CHARS} characters"
            )
        return credential


class MeRead(BaseModel):
    """`GET /api/auth/me`. Profile only — `token_set` says the field exists so
    the Account card can render its controls; the token itself needs the
    password (`ApiTokenRead`)."""

    username: str
    token_set: bool


class ApiTokenRead(BaseModel):
    """The long-lived bearer token, returned only by the two password-gated routes."""

    api_token: str


class PasskeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class PasskeyCeremonyOptions(BaseModel):
    """A WebAuthn ceremony: the server-side state id plus the options blob the
    browser hands to `navigator.credentials`. The blob's shape is the
    library's, so it stays an open dict."""

    state_id: str
    options: dict[str, Any]


class OkRead(BaseModel):
    ok: bool = True
