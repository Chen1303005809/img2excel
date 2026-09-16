from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from backend.app.models import Run, Source, utc_now
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
