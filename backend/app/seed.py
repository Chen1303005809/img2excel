from __future__ import annotations

from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Source, SourceGroup, utc_now
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


def seed_source_groups(session: Session) -> None:
    """Create the synchronized 804/805 schedule from legacy source settings."""
    group_id = "position-limit"
    if session.get(SourceGroup, group_id) is not None:
        return

    sources = list(session.scalars(select(Source)))
    by_page_id = {
        parse_qs(urlsplit(source.normalized_url).query).get("id", [""])[0]: source
        for source in sources
    }
    future = by_page_id.get("804")
    option = by_page_id.get("805")
    if future is None or option is None:
        return

    enabled = future.schedule_enabled and option.schedule_enabled
    interval = max(future.schedule_interval_minutes, option.schedule_interval_minutes)
    due_values = [value for value in (future.next_run_at, option.next_run_at) if value is not None]
    now = utc_now()
    group = SourceGroup(
        id=group_id,
        name="期货与期权限仓",
        future_source_id=future.id,
        option_source_id=option.id,
        schedule_enabled=enabled,
        schedule_interval_minutes=interval,
        next_run_at=(max(due_values) if due_values else now) if enabled else None,
        created_at=now,
        updated_at=now,
    )
    session.add(group)
    # The group owns these timers from this point onward.
    future.schedule_enabled = False
    future.next_run_at = None
    option.schedule_enabled = False
    option.next_run_at = None
    session.commit()
