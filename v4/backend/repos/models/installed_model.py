"""Installed model (v4 new)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class InstalledModel(Base):
    __tablename__ = "installed_models"
    __table_args__ = (
        CheckConstraint("capability IN ('vision','analysis','transcription','speech','embedding')"),
        CheckConstraint("source_type IN ('local_catalog','cloud_provider')"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(String, ForeignKey("model_endpoints.id"))
    remote_model_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    capability: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    local_artifact_ref: Mapped[str | None] = mapped_column(String)
    probe_status: Mapped[str] = mapped_column(String)
    capability_json: Mapped[str] = mapped_column(Text)
    installed_at: Mapped[str] = mapped_column(String)
    last_probed_at: Mapped[str | None] = mapped_column(String)
