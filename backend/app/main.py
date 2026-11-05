from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.auth import routes as auth_routes
from app.config import Settings
from app.db import init_db

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "XMLHttpRequest"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(app_settings)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.settings = app_settings

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in _MUTATING and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return Response(
                content='{"detail":"缺少 CSRF 头"}', status_code=403, media_type="application/json"
            )
        return await call_next(request)

    app.include_router(auth_routes.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
