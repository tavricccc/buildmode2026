"""Pure-function state machines.

The repository holds transitions as plain functions. Tests can call
them directly; production code wraps them in async services that
persist the resulting state.
"""

from .fall import FallContext, fall_transition
from .hydration import HydrationContext, hydration_transition
from .model_install import InstallContext, install_transition
from .notification import NotificationContext, notification_transition
from .config_apply import ConfigApplyContext, config_apply_transition

__all__ = [
    "FallContext",
    "fall_transition",
    "HydrationContext",
    "hydration_transition",
    "InstallContext",
    "install_transition",
    "NotificationContext",
    "notification_transition",
    "ConfigApplyContext",
    "config_apply_transition",
]
