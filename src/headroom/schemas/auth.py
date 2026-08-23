"""I/O models for the auth routes.

These were declared inline in `routes/auth.py`, which is the one convention
this repo states outright ("no schema is declared inline in a route") and the
one place it most matters: these are the request bodies on the unauthenticated
surface, so their validation rules — the password floor especially — should be
readable without opening the transport layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Argon2id makes long passwords cheap to verify, so the ceiling exists only to
# bound what gets hashed, not to constrain the user.
_PASSWORD_MIN = 8
_PASSWORD_MAX = 200


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class AuthStatus(BaseModel):
    needs_setup: bool
    authenticated: bool
    username: str | None = None
    #: Whether the login screen should offer "browse as a guest". Carried here
    #: rather than on its own endpoint because this is the one unauthenticated
    #: call the login page already makes, and a second would be a second
    #: round-trip before anything renders.
    guest_view_enabled: bool = False


class PasswordChange(BaseModel):
    # No floor on the current password: it is checked against the stored hash,
    # not accepted, and a length rule here would reject a legitimate holder of
    # a password that predates the current rules.
    current_password: str
    new_password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class PasskeyRegisterVerify(BaseModel):
    state_id: str
    # `dict` rather than a modelled shape: this is the WebAuthn credential the
    # browser produced, and it is handed to the passkey library verbatim.
    # Re-declaring its structure here would be a second, drifting copy of the
    # spec that the library already implements.
    credential: dict
    name: str = "Passkey"


class PasskeyLoginVerify(BaseModel):
    state_id: str
    credential: dict
