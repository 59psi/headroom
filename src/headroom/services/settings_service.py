from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings as config_settings
from headroom.models.app_setting import AppSetting

ANTHROPIC_MODEL_NAME = "anthropic_model"


@dataclass(frozen=True)
class KeyProvider:
    """An externally-issued API key the app stores on the user's behalf.

    Every provider behaves identically — DB setting wins over env var, the raw
    value never leaves the process — so describing one is enough to generate
    its service accessors *and* its HTTP routes (see `routes/settings.py`).
    Adding a third provider is one entry here plus one line in the mount loop.
    """

    name: str  # python identifier, used for route names
    slug: str  # URL segment under /api/settings
    setting_key: str  # app_settings row key
    env_attr: str  # attribute on config.settings holding the env fallback
    label: str  # human-readable, used in the activity log


ANTHROPIC_KEY = KeyProvider(
    name="anthropic_key",
    slug="api-key",
    setting_key="anthropic_api_key",
    env_attr="anthropic_api_key",
    label="Anthropic API key",
)

GOOGLE_VISION_KEY = KeyProvider(
    name="google_vision_key",
    slug="google-vision-key",
    setting_key="google_vision_api_key",
    env_attr="google_vision_api_key",
    label="Google Vision API key",
)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:5]}…{key[-4:]}"


async def get_setting(db: AsyncSession, key: str) -> str | None:
    """Read a raw app_settings value (public key-value accessor)."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    """Upsert (or delete when value is None) an app_settings value. Commits."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        if value is None:
            return
        db.add(AppSetting(key=key, value=value))
    elif value is None:
        await db.delete(row)
    else:
        row.value = value
    await db.commit()


async def get_key(db: AsyncSession, provider: KeyProvider) -> tuple[str | None, str | None]:
    """Resolve a provider's active key. Returns (key, source).

    Order: database setting > environment variable.
    """
    db_value = await get_setting(db, provider.setting_key)
    if db_value:
        return db_value, "database"
    env_value = getattr(config_settings, provider.env_attr, None)
    if env_value:
        return env_value, "environment"
    return None, None


async def set_key(db: AsyncSession, provider: KeyProvider, value: str) -> None:
    await set_setting(db, provider.setting_key, value.strip())


async def clear_key(db: AsyncSession, provider: KeyProvider) -> None:
    await set_setting(db, provider.setting_key, None)


# Named accessors for the two providers the analysis pipeline reaches for
# directly. They are deliberately NOT collapsed into `get_key` call sites: the
# pipeline and health checks read better this way, and the test suite patches
# each one independently to simulate "Claude configured but Vision isn't".


async def get_anthropic_key(db: AsyncSession) -> tuple[str | None, str | None]:
    return await get_key(db, ANTHROPIC_KEY)


async def get_google_vision_key(db: AsyncSession) -> tuple[str | None, str | None]:
    return await get_key(db, GOOGLE_VISION_KEY)


async def get_anthropic_model(db: AsyncSession) -> tuple[str, str]:
    """Resolve the active Claude model id. Returns (model, source).

    Order: database setting > environment variable > built-in default.
    Always returns a non-empty string.
    """
    db_value = await get_setting(db, ANTHROPIC_MODEL_NAME)
    if db_value:
        return db_value, "database"
    # config_settings.anthropic_model has a built-in default, so we can't tell
    # env-vs-default from the value alone. Inspect __pydantic_fields_set__.
    if "anthropic_model" in config_settings.model_fields_set:
        return config_settings.anthropic_model, "environment"
    return config_settings.anthropic_model, "default"


async def set_anthropic_model(db: AsyncSession, value: str) -> None:
    await set_setting(db, ANTHROPIC_MODEL_NAME, value.strip())


async def clear_anthropic_model(db: AsyncSession) -> None:
    await set_setting(db, ANTHROPIC_MODEL_NAME, None)
