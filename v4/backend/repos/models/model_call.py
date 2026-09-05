"""Model call record (audit)."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String)
    response_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)
    # v4
    model_endpoint_id: Mapped[str | None] = mapped_column(String, index=True)
    config_version: Mapped[str | None] = mapped_column(String)
    capability: Mapped[str | None] = mapped_column(String)
