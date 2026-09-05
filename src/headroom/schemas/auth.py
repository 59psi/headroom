"""I/O models for the auth routes.

These were declared inline in `routes/auth.py`, which is the one convention
this repo states outright ("no schema is declared inline in a route") and the
one place it most matters: these are the request bodies on the unauthenticated
surface, so their validation rules — the password floor especially — should be
readable without opening the transport layer.
"""

from __future__ import annotations

from pydantic import BaseModel, model_serializer, Field

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
    name: str = "Passkey"


class PasskeyLoginVerify(BaseModel):
    state_id: str
    credential: dict
