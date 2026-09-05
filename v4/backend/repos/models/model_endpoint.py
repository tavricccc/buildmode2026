"""Model endpoint (v4 new)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ModelEndpointRecord(Base):
    __tablename__ = "model_endpoints"
    __table_args__ = (CheckConstraint("deployment_type IN ('local','cloud')"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    deployment_type: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    adapter_mode: Mapped[str] = mapped_column(String)
    secret_ref: Mapped[str | None] = mapped_column(String)
    runtime_id: Mapped[str | None] = mapped_column(String)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
