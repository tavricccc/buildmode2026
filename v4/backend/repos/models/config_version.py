"""Config version (v4 new)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    base_version: Mapped[str | None] = mapped_column(String)
    settings_json: Mapped[str] = mapped_column(Text)
    changed_keys_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    activated_at: Mapped[str | None] = mapped_column(String, index=True)
    rolled_back_from: Mapped[str | None] = mapped_column(String)
