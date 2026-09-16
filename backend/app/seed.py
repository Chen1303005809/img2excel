from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Source
from .url_utils import normalize_url


SEED_SOURCES = (
    ("交易所期货限仓", "https://www.yafco.com/jiaoyidating_show.html?id=804"),
    ("交易所期权限仓", "https://www.yafco.com/jiaoyidating_show.html?id=805"),
    ("期货开仓总量限制", "https://www.yafco.com/jiaoyidating_show.html?id=970"),
)


def seed_sources(session: Session) -> None:
    changed = False
    for name, url in SEED_SOURCES:
        normalized = normalize_url(url)
        existing = session.scalar(select(Source).where(Source.normalized_url == normalized))
        if existing is not None:
            continue
        session.add(
            Source(
                id=str(uuid4()),
                name=name,
                url=url,
                normalized_url=normalized,
                profile_key="yafco_image",
                enabled=True,
            )
        )
        changed = True
    if changed:
        session.commit()

