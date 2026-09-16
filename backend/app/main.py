from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from .api import build_router
from .artifacts import ArtifactStore
from .config import Settings, get_settings
from .database import build_engine, run_migrations
from .models import Base
from .seed import seed_sources


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(settings)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = ArtifactStore(settings.resolved_data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(settings)
        # Keep create_all as a safety net for a brand-new local database when
        # an older developer checkout has no migration state yet.
        Base.metadata.create_all(engine)
        with session_factory() as session:
            seed_sources(session)
        yield
        engine.dispose()

    app = FastAPI(title="网址图片转表格", version="1.0.0", lifespan=lifespan)
    allowed_origins = list(dict.fromkeys([settings.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"]))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.artifact_store = store
    app.include_router(build_router(session_factory, store, settings))
    return app


app = create_app()
