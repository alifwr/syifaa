from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth as auth_router


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="syifa")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(auth_router.router)
    return app


app = create_app()
