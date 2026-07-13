"""FastAPI application factory for BAS Assistant."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from bas_assistant.config import Settings, get_settings
from bas_assistant.core import ApplicationContainer, build_container
from bas_assistant.runtime import configure_logging, ensure_runtime_directories


def create_application(
    *,
    settings: Settings | None = None,
    lifespan_factory: Callable[[ApplicationContainer], object] | None = None,
) -> tuple[FastAPI, ApplicationContainer]:
    """Create the BAS Assistant FastAPI app and service container."""
    resolved_settings = settings or get_settings()
    ensure_runtime_directories(resolved_settings)
    configure_logging(resolved_settings)
    container = build_container(resolved_settings)

    if lifespan_factory is None:
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            yield
    else:
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            async with lifespan_factory(container):
                yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.session_secret,
        session_cookie=resolved_settings.session_cookie_name,
        https_only=resolved_settings.environment == "production",
        same_site="lax",
    )
    app.state.container = container
    return app, container
