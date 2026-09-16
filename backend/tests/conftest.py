from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.artifacts import ArtifactStore
from backend.app.config import Settings
from backend.app.database import build_engine
from backend.app.models import Base


def make_document(value: str = "100", *, label: str = "主表", merge: bool = True) -> dict:
    return {
        "version": 2,
        "source": {"filename": "source.png", "width": 400, "height": 180},
        "title": "测试表格",
        "bands": [],
        "sections": [
            {
                "id": "S01",
                "label": label,
                "bbox": [0, 0, 400, 180],
                "x_edges": [0, 200, 400],
                "y_edges": [0, 60, 120, 180],
                "cells": [["品种", ""], ["甲", value], ["乙", 0.5]],
                "merged_cells": [
                    {
                        "r0": 0,
                        "r1": 0,
                        "c0": 0,
                        "c1": 1,
                        "value": "品种",
                        "ocr_item_count": 1,
                        "ocr_min_score": 0.98,
                    }
                ]
                if merge
                else [],
                "ocr_count": 3,
                "ocr_avg_score": 0.96,
                "ocr_low_score_count": 0,
                "strategy": "line_grid",
            }
        ],
        "colored_notes": [],
        "footer_notes": [{"text": "仅用于测试"}],
        "ocr_boxes": [],
        "corrections": [],
        "metrics": {"ocr_low_score_count": 0},
    }


def clone_document(document: dict) -> dict:
    return deepcopy(document)


@pytest.fixture
def db_env(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        allow_private_hosts=True,
        worker_poll_interval=0.01,
        lease_seconds=60,
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = ArtifactStore(settings.resolved_data_dir)
    try:
        yield settings, engine, session_factory, store
    finally:
        engine.dispose()
