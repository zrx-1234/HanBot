from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import routes as auth_routes
from app.config import Settings
from app.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(app_settings)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.settings = app_settings
    app.include_router(auth_routes.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
