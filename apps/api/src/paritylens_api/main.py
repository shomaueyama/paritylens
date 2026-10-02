"""Application entry point: builds the FastAPI app and registers routers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from paritylens_api import db
from paritylens_api.core.errors import install_error_handlers
from paritylens_api.core.limits import BodySizeLimitMiddleware, RequestLogMiddleware
from paritylens_api.core.logging import configure_logging
from paritylens_api.routers import api_tokens, auth, health, projects, runs

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Runs once around the app's lifetime: setup before `yield`, cleanup after."""
    configure_logging()
    yield
    if db._engine is not None:
        await db._engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="ParityLens API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    app.add_middleware(RequestLogMiddleware)
    # Added last, so it wraps everything above: an oversized body is
    # refused before any other code sees the request.
    app.add_middleware(BodySizeLimitMiddleware)

    for router in (health.router, auth.router, api_tokens.router, projects.router, runs.router):
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
