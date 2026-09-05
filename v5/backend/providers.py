"""The failure contract every model provider shares.

``L2Service`` and ``L3Service`` are written against a contract rather than
against a vendor: build the parts, call ``generate``, and turn a provider
failure into a recorded :class:`ModelCall` so the window still reaches
SQLite. v5 00 item 10 depends on that — every pipeline window must stay
answerable after the fact, and "we tried to look at the resident and the
call failed" is exactly the window a caregiver needs to find later.

The contract held while there were two providers and each service caught
its own vendor's exception. It broke silently when a third arrived with
its own hierarchy: ``LocalVllmError`` was not a ``GeminiError``, so it
escaped ``observe()`` entirely and those windows left no pipeline_run at
all — indistinguishable, on the Dashboard, from an empty room.

A shared base is what the services are allowed to know about. Adding a
provider means inheriting from it, not editing every ``except`` clause.
"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """A model provider call failed. ``code`` is stable enough to branch on."""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
