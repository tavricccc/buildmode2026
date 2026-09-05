"""Catalog service stub.

Reads the local model catalog from ``data/catalog/local_models.json``
and returns it for the Setup Wizard's "local catalog" step.
"""

from __future__ import annotations

import json
from pathlib import Path


class CatalogService:
    def __init__(self, path: Path) -> None:
        self._path = path

    def list(self) -> list[dict]:
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return data.get("models", [])

    def get(self, catalog_id: str) -> dict | None:
        for entry in self.list():
            if entry.get("id") == catalog_id:
                return entry
        return None
