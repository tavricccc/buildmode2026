"""v3 routes (preserved for back-compat; v4 payloads are supersets)."""

from fastapi import FastAPI

from ...services.notification_service import NotificationService
from ...services.observer_service import ObserverService
from ...services.replay_service import ReplayService
from ...services.status_service import StatusService
from .cameras import router as cameras_router
from .demo import router as demo_router
from .events import router as events_router
from .events_analyze import router as events_analyze_router
from .health import router as health_router
from .hydration import router as hydration_router
from .notifications import router as notifications_router
from .observer import router as observer_router
from .replay import router as replay_router
from .sources import router as sources_router
from .status import router as status_router
from .tools import router as tools_router
from .transcripts import router as transcripts_router


def register_v3_routes(
    app: FastAPI,
    *,
    status_service: StatusService,
    notification_service: NotificationService,
    observer_service: ObserverService,
    replay_service: ReplayService,
) -> None:
    app.include_router(status_router(status_service), prefix="/api")
    app.include_router(cameras_router(), prefix="/api")
    app.include_router(sources_router(), prefix="/api")
    app.include_router(events_router(), prefix="/api")
    app.include_router(hydration_router(), prefix="/api")
    app.include_router(health_router(), prefix="/api")
    app.include_router(events_analyze_router(), prefix="/api")
    app.include_router(replay_router(replay_service), prefix="/api")
    app.include_router(demo_router(), prefix="/api")
    app.include_router(transcripts_router(), prefix="/api")
    app.include_router(tools_router(), prefix="/api")
    app.include_router(observer_router(observer_service), prefix="/api")
    app.include_router(notifications_router(notification_service), prefix="/api")
