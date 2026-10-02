"""Application entry point: builds the FastAPI app and registers routers."""

from fastapi import FastAPI

from paritylens_api.routers import health

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="ParityLens API", version="0.1.0")
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
