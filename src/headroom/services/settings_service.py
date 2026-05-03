from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings as config_settings
from headroom.models.app_setting import AppSetting

ANTHROPIC_KEY_NAME = "anthropic_api_key"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:5]}…{key[-4:]}"


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str | None) -> None:
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


async def get_anthropic_key(db: AsyncSession) -> tuple[str | None, str | None]:
    """Resolve the active Anthropic key. Returns (key, source).

    Order: database setting > environment variable.
    """
    db_value = await _get_setting(db, ANTHROPIC_KEY_NAME)
    if db_value:
        return db_value, "database"
    if config_settings.anthropic_api_key:
        return config_settings.anthropic_api_key, "environment"
    return None, None


async def set_anthropic_key(db: AsyncSession, value: str) -> None:
    await _set_setting(db, ANTHROPIC_KEY_NAME, value.strip())


async def clear_anthropic_key(db: AsyncSession) -> None:
    await _set_setting(db, ANTHROPIC_KEY_NAME, None)
