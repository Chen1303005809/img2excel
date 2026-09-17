from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from backend.app.models import Run, Source, utc_now
from backend.app.scheduling import ScheduleManager
from backend.worker import JobQueue


def test_worker_queue_claim_heartbeat_release_and_stale_recovery(db_env):
    settings, _, session_factory, _ = db_env
    source_id = str(uuid4())
    run_id = str(uuid4())
    with session_factory() as session:
        session.add(
            Source(
                id=source_id,
                name="队列来源",
                url="https://example.com/queue",
                normalized_url="https://example.com/queue",
                profile_key="yafco_image",
                enabled=True,
            )
        )
        session.commit()
        session.add(
            Run(
                id=run_id,
                source_id=source_id,
                requested_url="https://example.com/queue",
                normalized_url="https://example.com/queue",
                profile_key="yafco_image",
                status="queued",
                stage="queued",
                progress=0,
                message="等待 Worker 处理",
            )
        )
        session.commit()

    queue = JobQueue(session_factory, settings)
    assert queue.claim() == run_id
    with session_factory() as session:
        claimed = session.get(Run, run_id)
        assert claimed is not None
        assert claimed.lease_id is not None
        assert claimed.attempt == 1

    queue.touch(run_id)
    with session_factory() as session:
        claimed = session.get(Run, run_id)
        assert claimed is not None
        claimed.heartbeat_at = utc_now() - timedelta(seconds=settings.lease_seconds + 1)
        claimed.status = "extracting"
        session.commit()

    assert queue.recover_stale() == 1
    with session_factory() as session:
        recovered = session.get(Run, run_id)
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.lease_id is None

    assert queue.claim() == run_id
    queue.release(run_id)
    with session_factory() as session:
        released = session.get(Run, run_id)
        assert released is not None
        assert released.lease_id is None


def test_schedule_manager_enqueues_due_sources_once(db_env):
    settings, _, session_factory, _ = db_env
    source_id = str(uuid4())
    now = utc_now()
    with session_factory() as session:
        session.add(
            Source(
                id=source_id,
                name="定时来源",
                url="https://example.com/scheduled",
                normalized_url="https://example.com/scheduled",
                profile_key="yafco_image",
                enabled=True,
                schedule_enabled=True,
                schedule_interval_minutes=15,
                next_run_at=now - timedelta(seconds=1),
            )
        )
        session.commit()

    scheduler = ScheduleManager(session_factory)
    created = scheduler.enqueue_due_runs(now)
    assert len(created) == 1
    assert scheduler.enqueue_due_runs(now) == []

    with session_factory() as session:
        source = session.get(Source, source_id)
        run = session.get(Run, created[0])
        assert source is not None
        assert source.next_run_at is not None
        next_run = source.next_run_at.replace(tzinfo=now.tzinfo) if source.next_run_at.tzinfo is None else source.next_run_at
        assert next_run > now
        assert run is not None
        assert run.status == "queued"
        assert run.baseline_run_id is None
