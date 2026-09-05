"""Config version repository (v4 new)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ConfigVersion


class ConfigVersionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        version_id: str,
        base_version: str | None,
        settings: dict[str, Any],
        changed_keys: list[str],
        created_by: str,
        created_at: str,
        activated_at: str | None,
        rolled_back_from: str | None,
    ) -> ConfigVersion:
        record = ConfigVersion(
            id=version_id,
            base_version=base_version,
            settings_json=json.dumps(settings, default=str),
            changed_keys_json=json.dumps(changed_keys),
            created_by=created_by,
            created_at=created_at,
            activated_at=activated_at,
            rolled_back_from=rolled_back_from,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get(self, version_id: str) -> ConfigVersion | None:
        return await self._session.get(ConfigVersion, version_id)

    async def latest_activated(self) -> ConfigVersion | None:
        stmt = (
            select(ConfigVersion)
            .where(ConfigVersion.activated_at.is_not(None))
            .order_by(ConfigVersion.activated_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> list[ConfigVersion]:
        stmt = select(ConfigVersion).order_by(ConfigVersion.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
