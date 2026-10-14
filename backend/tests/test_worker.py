from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from backend.app.models import Run, RunBatch, Source, SourceGroup, utc_now
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


def test_schedule_manager_enqueues_limit_pair_and_open_total_independently(db_env):
    _, _, session_factory, _ = db_env
    now = utc_now()
    sources = [
        Source(
            id=str(uuid4()),
            name=name,
            url=f"https://example.com/{key}",
            normalized_url=f"https://example.com/{key}",
            profile_key="yafco_image",
            enabled=True,
            schedule_enabled=key == "open-total",
            schedule_interval_minutes=30,
            next_run_at=now - timedelta(seconds=1) if key == "open-total" else None,
        )
        for key, name in (("future", "期货限仓"), ("option", "期权限仓"), ("open-total", "开仓总量"))
    ]
    with session_factory() as session:
        session.add_all(sources)
        session.commit()
        session.add(
            SourceGroup(
                id="position-limit",
                name="期货与期权限仓",
                future_source_id=sources[0].id,
                option_source_id=sources[1].id,
                schedule_enabled=True,
                schedule_interval_minutes=45,
                next_run_at=now - timedelta(seconds=1),
            )
        )
        session.commit()

    created = ScheduleManager(session_factory).enqueue_due_runs(now)
    assert len(created) == 3

    with session_factory() as session:
        runs = [session.get(Run, run_id) for run_id in created]
        assert all(run is not None for run in runs)
        run_by_source = {run.source_id: run for run in runs if run is not None}
        future_run = run_by_source[sources[0].id]
        option_run = run_by_source[sources[1].id]
        open_total_run = run_by_source[sources[2].id]
        assert future_run.run_batch_id == option_run.run_batch_id
        assert future_run.run_batch_id != open_total_run.run_batch_id
        pair_batch = session.get(RunBatch, future_run.run_batch_id)
        open_total_batch = session.get(RunBatch, open_total_run.run_batch_id)
        assert pair_batch is not None and pair_batch.kind == "position_pair"
        assert pair_batch.trigger_type == "scheduled"
        assert open_total_batch is not None and open_total_batch.kind == "single_source"
