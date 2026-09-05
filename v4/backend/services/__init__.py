"""Service layer (commit 1).

Two services are fully wired (status, settings, secret); the rest
expose stable method signatures returning typed stubs so the API
layer and tests have a complete surface to work against.
"""

from .status_service import StatusService
from .settings_service import SettingsService, SettingsError
from .secret_service import SecretService

__all__ = [
    "StatusService",
    "SettingsService",
    "SettingsError",
    "SecretService",
]
