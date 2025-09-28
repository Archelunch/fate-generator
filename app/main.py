import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import dspy
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.baml_adapter import BAMLAdapter
from app.config.settings import get_settings
from app.routes.pages import router as pages_router

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")


def _configure_logging(level: str) -> None:
    try:
        import logging

        logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    except Exception:
        pass


def _configure_lm() -> None:
    settings = get_settings()
    lm = dspy.LM(
        settings.dspy_model,
        api_key=settings.dspy_api_key,
        temperature=settings.dspy_temperature,
        max_tokens=settings.dspy_max_tokens,
        cache=settings.dspy_cache,
    )
    dspy.configure(lm=lm, adapter=BAMLAdapter())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    settings = get_settings()
    _configure_logging(settings.log_level)
    _configure_lm()
    # Lazy import services to avoid circulars
    from app.services.registry import build_service_registry

    app.state.services = build_service_registry(settings)
    yield
    # Shutdown
    try:
        reg = getattr(app.state, "services", None)
        if reg and hasattr(reg, "close"):
            reg.close()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Static and templates
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app.state.templates = templates

    # Routers
    app.include_router(pages_router)
    # New API routers split by concern
    try:
        from app.routes.skeleton import router as skeleton_router
        from app.routes.remaining import router as remaining_router
        from app.routes.gm_hints import router as gm_hints_router

        app.include_router(skeleton_router)
        app.include_router(remaining_router)
        app.include_router(gm_hints_router)
    except Exception:
        # Fallback to legacy router during transition
        from app.routes.api import router as legacy_api_router

        app.include_router(legacy_api_router)

    return app


app = create_app()
