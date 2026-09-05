"""Shared SQLAlchemy declarative base for the v4 backend."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
