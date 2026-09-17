from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Run, Source, utc_now


DEFAULT_SCHEDULE_INTERVAL_MINUTES = 60
ACTIVE_RUN_STATUSES = (
    "queued",
    "crawling",
    "downloading",
    "extracting",
    "exporting",
    "awaiting_image_selection",
)


def schedule_next_at(now: datetime, interval_minutes: int) -> datetime:
    """Return the next UTC timestamp for a source schedule."""
    return now + timedelta(minutes=max(1, int(interval_minutes)))


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_due(next_run_at: datetime | None, now: datetime) -> bool:
    return next_run_at is None or _as_aware_utc(next_run_at) <= _as_aware_utc(now)


def latest_successful_run(session: Session, source_id: str, normalized_url: str | None = None) -> Run | None:
    query = select(Run).where(Run.source_id == source_id, Run.status == "succeeded")
    if normalized_url is not None:
        query = query.where(Run.normalized_url == normalized_url)
    return session.scalar(query.order_by(desc(Run.finished_at), desc(Run.created_at)).limit(1))


def create_queued_run(session: Session, source: Source, *, now: datetime | None = None) -> Run:
    """Create a run using the same locked successful baseline as the API."""
    baseline = latest_successful_run(session, source.id, source.normalized_url)
    run = Run(
        id=str(uuid4()),
        source_id=source.id,
        requested_url=source.url,
        normalized_url=source.normalized_url,
        profile_key=source.profile_key,
        baseline_run_id=baseline.id if baseline else None,
        status="queued",
        stage="queued",
        progress=0,
        message="等待 Worker 处理",
        created_at=now or utc_now(),
    )
    session.add(run)
    return run


class ScheduleManager:
    """Persistently turns due source schedules into ordinary queued runs."""

    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    def enqueue_due_runs(self, now: datetime | None = None) -> list[str]:
        current = now or utc_now()
        created_ids: list[str] = []
        with self.session_factory() as session:
            sources = list(
                session.scalars(
                    select(Source)
                    .where(Source.enabled.is_(True), Source.schedule_enabled.is_(True))
                    .order_by(Source.next_run_at, Source.created_at)
                )
            )
            for source in sources:
                if not _is_due(source.next_run_at, current):
                    continue

                active_run_id = session.scalar(
                    select(Run.id)
                    .where(Run.source_id == source.id, Run.status.in_(ACTIVE_RUN_STATUSES))
                    .order_by(desc(Run.created_at))
                    .limit(1)
                )
                if active_run_id is None:
                    run = create_queued_run(session, source, now=current)
                    created_ids.append(run.id)

                # Advance from the current tick rather than repeatedly
                # catching up after the worker has been stopped for a while.
                source.next_run_at = schedule_next_at(current, source.schedule_interval_minutes)
                source.updated_at = current

            session.commit()
        return created_ids
