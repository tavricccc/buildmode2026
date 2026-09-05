"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Request


def get_status_service(request: Request):
    return request.app.state.status_service


def get_broadcaster(request: Request):
    return request.app.state.broadcaster


def get_settings_service(request: Request):
    return request.app.state.settings_service


def get_secret_service(request: Request):
    return request.app.state.secret_service


def get_registry(request: Request):
    return request.app.state.registry


def get_model_endpoint_service(request: Request):
    return request.app.state.model_endpoint_service


def get_catalog_service(request: Request):
    return request.app.state.catalog_service


def get_setup_service(request: Request):
    return request.app.state.setup_service


def get_observer_service(request: Request):
    return request.app.state.observer_service


def get_notification_service(request: Request):
    return request.app.state.notification_service


def get_replay_service(request: Request):
    return request.app.state.replay_service
