from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth as auth_router
from app.routers import oauth as oauth_router
from app.routers import llm_config as llm_config_router
from app.routers import papers as papers_router
from app.routers import concepts as concepts_router


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
    app.include_router(oauth_router.router)
    app.include_router(llm_config_router.router)
    app.include_router(papers_router.router)
    app.include_router(concepts_router.router)
    return app


app = create_app()
