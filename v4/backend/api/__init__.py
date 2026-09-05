"""FastAPI routers for the v4 backend."""

from fastapi import FastAPI

from ..adapters.model_gateway import ModelEndpointRegistry
from ..realtime import RealtimeBroadcaster
from ..services.catalog_service import CatalogService
from ..services.model_endpoint_service import ModelEndpointService
from ..services.notification_service import NotificationService
from ..services.observer_service import ObserverService
from ..services.replay_service import ReplayService
from ..services.secret_service import SecretService
from ..services.settings_service import SettingsService
from ..services.setup_service import SetupService
from ..services.status_service import StatusService
from .integrations import router as integrations_router
from .model_endpoints import router as model_endpoints_router
from .models_catalog import router as models_catalog_router
from .models_install import router as models_install_router
from .settings import router as settings_router
from .setup import router as setup_router
from .v3_routes import register_v3_routes


def register_routers(app: FastAPI) -> None:
    settings = app.state.settings
    broadcaster: RealtimeBroadcaster = app.state.broadcaster

    registry = ModelEndpointRegistry()
    settings_service = SettingsService(broadcaster=broadcaster)
    secret_service = SecretService(path=settings.secret_store_path)
    setup_service = SetupService(settings=settings)
    model_endpoint_service = ModelEndpointService(registry=registry)
    catalog_service = CatalogService(path=settings.catalog_path)
    notification_service = NotificationService()
    observer_service = ObserverService(broadcaster=broadcaster)
    replay_service = ReplayService(settings=settings)

    app.state.registry = registry
    app.state.settings_service = settings_service
    app.state.secret_service = secret_service
    app.state.setup_service = setup_service
    app.state.model_endpoint_service = model_endpoint_service
    app.state.catalog_service = catalog_service
    app.state.notification_service = notification_service
    app.state.observer_service = observer_service
    app.state.replay_service = replay_service

    register_v3_routes(
        app,
        status_service=app.state.status_service,
        notification_service=notification_service,
        observer_service=observer_service,
        replay_service=replay_service,
    )

    app.include_router(setup_router(setup_service), prefix="/api")
    app.include_router(settings_router(settings_service, secret_service), prefix="/api")
    app.include_router(model_endpoints_router(model_endpoint_service, registry), prefix="/api")
    app.include_router(models_catalog_router(catalog_service, model_endpoint_service), prefix="/api")
    app.include_router(models_install_router(model_endpoint_service), prefix="/api")
    app.include_router(integrations_router(), prefix="/api")
