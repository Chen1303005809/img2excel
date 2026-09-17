from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import sessionmaker

from .app.artifacts import ArtifactStore
from .app.config import Settings, get_settings
from .app.crawling import Crawl4AIAdapter
from .app.database import build_engine, run_migrations
from .app.models import Base, Run, utc_now
from .app.pipeline import PipelineRunner
from .app.seed import seed_sources
from .app.scheduling import ScheduleManager


class JobQueue:
    """SQLite-backed queue with leases suitable for the local Worker."""

    def __init__(self, session_factory: sessionmaker, settings: Settings):
        self.session_factory = session_factory
        self.settings = settings

    def recover_stale(self) -> int:
        cutoff = utc_now() - timedelta(seconds=self.settings.lease_seconds)
        recovered = 0
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(Run).where(
                        Run.lease_id.is_not(None),
                        or_(Run.heartbeat_at.is_(None), Run.heartbeat_at < cutoff),
                        Run.status.not_in(("succeeded", "failed")),
                    )
                )
            )
            for run in rows:
                run.lease_id = None
                run.status = "queued"
                run.stage = "queued"
                run.progress = min(run.progress, 25)
                run.message = "Worker 已重启，任务重新排队"
                run.heartbeat_at = None
                recovered += 1
            session.commit()
        return recovered

    def claim_job(self) -> "ClaimedJob | None":
        with self.session_factory() as session:
            run_id = session.scalar(
                select(Run.id)
                .where(Run.status == "queued", Run.lease_id.is_(None))
                .order_by(Run.created_at)
                .limit(1)
            )
            if run_id is None:
                return None
            lease_id = str(uuid4())
            now = utc_now()
            result = session.execute(
                update(Run)
                .where(Run.id == run_id, Run.status == "queued", Run.lease_id.is_(None))
                .values(
                    lease_id=lease_id,
                    attempt=Run.attempt + 1,
                    started_at=func.coalesce(Run.started_at, now),
                    heartbeat_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            return ClaimedJob(run_id=run_id, lease_id=lease_id)

    def claim(self) -> str | None:
        job = self.claim_job()
        return job.run_id if job else None

    def touch(self, run_id: str, lease_id: str | None = None) -> None:
        with self.session_factory() as session:
            query = update(Run).where(Run.id == run_id)
            if lease_id:
                query = query.where(Run.lease_id == lease_id)
            session.execute(query.values(heartbeat_at=utc_now()))
            session.commit()

    def release(self, run_id: str, lease_id: str | None = None) -> None:
        with self.session_factory() as session:
            query = update(Run).where(Run.id == run_id)
            if lease_id:
                query = query.where(Run.lease_id == lease_id)
            session.execute(query.values(lease_id=None, heartbeat_at=utc_now()))
            session.commit()


@dataclass(frozen=True)
class ClaimedJob:
    run_id: str
    lease_id: str


async def _heartbeat(queue: JobQueue, run_id: str, lease_id: str, interval: float) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(queue.touch, run_id, lease_id)
    except asyncio.CancelledError:
        return


async def run_worker(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(settings)
    run_migrations(settings)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        seed_sources(session)
    queue = JobQueue(session_factory, settings)
    queue.recover_stale()
    scheduler = ScheduleManager(session_factory)
    store = ArtifactStore(settings.resolved_data_dir)
    crawl_semaphore = asyncio.Semaphore(max(1, settings.effective_crawl_concurrency))
    ocr_semaphore = asyncio.Semaphore(max(1, settings.ocr_concurrency))

    async with Crawl4AIAdapter(settings) as crawler:
        runner = PipelineRunner(
            settings,
            session_factory,
            store,
            crawler,
            ocr_semaphore=ocr_semaphore,
            crawl_semaphore=crawl_semaphore,
        )
        active: dict[str, asyncio.Task[None]] = {}
        leases: dict[str, str] = {}
        heartbeats: dict[str, asyncio.Task[None]] = {}
        try:
            while True:
                await asyncio.to_thread(scheduler.enqueue_due_runs)
                while len(active) < max(1, settings.worker_concurrency):
                    job = await asyncio.to_thread(queue.claim_job)
                    if job is None:
                        break
                    active[job.run_id] = asyncio.create_task(runner.process(job.run_id))
                    leases[job.run_id] = job.lease_id
                    heartbeats[job.run_id] = asyncio.create_task(_heartbeat(queue, job.run_id, job.lease_id, max(1.0, settings.lease_seconds / 3)))

                if active:
                    done, _ = await asyncio.wait(tuple(active.values()), timeout=settings.worker_poll_interval, return_when=asyncio.FIRST_COMPLETED)
                    for run_id, task in list(active.items()):
                        if task not in done:
                            continue
                        active.pop(run_id, None)
                        lease_id = leases.pop(run_id, None)
                        heartbeat = heartbeats.pop(run_id, None)
                        if heartbeat:
                            heartbeat.cancel()
                            await asyncio.gather(heartbeat, return_exceptions=True)
                        await asyncio.gather(task, return_exceptions=True)
                        await asyncio.to_thread(queue.release, run_id, lease_id)
                else:
                    await asyncio.sleep(settings.worker_poll_interval)
        finally:
            for task in active.values():
                task.cancel()
            for task in heartbeats.values():
                task.cancel()
            if active:
                await asyncio.gather(*active.values(), return_exceptions=True)
            if heartbeats:
                await asyncio.gather(*heartbeats.values(), return_exceptions=True)
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the image-table background worker.")
    parser.add_argument("--concurrency", type=int, help="Override worker concurrency for this process.")
    args = parser.parse_args()
    settings = get_settings()
    if args.concurrency:
        settings.worker_concurrency = max(1, args.concurrency)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
