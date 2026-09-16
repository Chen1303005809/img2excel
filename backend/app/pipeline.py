from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .artifacts import ArtifactStore, record_artifact
from .config import Settings
from .contracts import document_sha256, validate_document, validate_envelope
from .crawling import Crawl4AIAdapter, CrawlFailure, ImageCandidateData
from .diffing import compare_documents
from .exporters import ExportContext, ExporterRegistry
from .models import Artifact, ImageCandidate, Run, utc_now
from .url_utils import InvalidSourceUrl, validate_fetch_host


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Extractor(Protocol):
    def extract(self, image_path: Path) -> dict[str, Any]:
        """Extract a validated generic table document from an image."""


class LocalImageExtractor:
    def __init__(self):
        self._engine = None

    def extract(self, image_path: Path) -> dict[str, Any]:
        from image_to_rows import extract
        from rapidocr import RapidOCR

        if self._engine is None:
            self._engine = RapidOCR()
        return extract(image_path, engine=self._engine)


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    media_type: str
    extension: str
    sha256: str


class ImageDownloader:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def download(self, candidate: ImageCandidateData) -> DownloadedImage:
        try:
            validate_fetch_host(candidate.resolved_url, self.settings.allow_private_hosts)
        except InvalidSourceUrl as error:
            raise PipelineError("image_url_blocked", str(error)) from error
        headers = {
            "User-Agent": "ImageTableApp/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.settings.image_timeout_seconds,
                headers=headers,
            ) as client:
                async with client.stream("GET", candidate.resolved_url) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.settings.max_image_bytes:
                            raise PipelineError("image_too_large", "image exceeds configured size limit")
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        except PipelineError:
            raise
        except Exception as error:
            raise PipelineError("image_download_failed", str(error)) from error

        suffix = Path(urlsplit(candidate.resolved_url).path).suffix.lower()
        if not suffix or len(suffix) > 8:
            suffix = mimetypes.guess_extension(media_type) or ".img"
        if media_type and not media_type.startswith("image/"):
            raise PipelineError("unsupported_image_type", f"downloaded content type is {media_type}")
        digest = hashlib.sha256(content).hexdigest()
        return DownloadedImage(bytes(content), media_type or "application/octet-stream", suffix, digest)


class PipelineRunner:
    """Deep module that runs one persisted run through crawl, OCR and exports."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker,
        store: ArtifactStore,
        crawler: Crawl4AIAdapter,
        extractor: Extractor | None = None,
        exporters: ExporterRegistry | None = None,
        ocr_semaphore: asyncio.Semaphore | None = None,
        crawl_semaphore: asyncio.Semaphore | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.store = store
        self.crawler = crawler
        self.extractor = extractor or LocalImageExtractor()
        self.exporters = exporters or ExporterRegistry()
        self.downloader = ImageDownloader(settings)
        self.ocr_semaphore = ocr_semaphore or asyncio.Semaphore(max(1, settings.ocr_concurrency))
        self.crawl_semaphore = crawl_semaphore or asyncio.Semaphore(max(1, settings.effective_crawl_concurrency))

    def _update_run(self, run_id: str, **values: Any) -> Run | None:
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                return None
            for key, value in values.items():
                setattr(run, key, value)
            run.heartbeat_at = utc_now()
            session.commit()
            session.refresh(run)
            return run

    def _get_run(self, session: Session, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise PipelineError("run_not_found", f"run not found: {run_id}")
        return run

    def _get_artifact(self, session: Session, run_id: str, kind: str, revision_id: str | None = None) -> Artifact | None:
        query = select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == kind)
        if revision_id is None:
            query = query.where(Artifact.revision_id.is_(None))
        else:
            query = query.where(Artifact.revision_id == revision_id)
        return session.scalar(query.order_by(Artifact.created_at.desc()))

    def _selected_candidate(self, session: Session, run_id: str) -> ImageCandidate | None:
        return session.scalar(
            select(ImageCandidate).where(ImageCandidate.run_id == run_id, ImageCandidate.selected.is_(True)).order_by(ImageCandidate.ordinal)
        )

    def _candidates(self, session: Session, run_id: str) -> list[ImageCandidate]:
        return list(session.scalars(select(ImageCandidate).where(ImageCandidate.run_id == run_id).order_by(ImageCandidate.ordinal)))

    async def process(self, run_id: str) -> None:
        try:
            with self.session_factory() as session:
                run = self._get_run(session, run_id)
                if run.status != "queued":
                    return
                candidates = self._candidates(session, run_id)
                selected = self._selected_candidate(session, run_id)
                crawl_artifact = self._get_artifact(session, run_id, "crawl_metadata")

            if selected is None:
                if not candidates or crawl_artifact is None:
                    selected = await self._crawl(run_id)
                    if selected is None:
                        return
                else:
                    if len(candidates) != 1:
                        self._update_run(
                            run_id,
                            status="awaiting_image_selection",
                            stage="awaiting_image_selection",
                            progress=25,
                            message="发现多张正文图片，请选择一张",
                        )
                        return
                    with self.session_factory() as session:
                        for candidate in self._candidates(session, run_id):
                            candidate.selected = candidate.ordinal == candidates[0].ordinal
                        session.commit()

            await self._extract_and_export(run_id)
        except PipelineError as error:
            self._fail(run_id, error.code, str(error))
        except SystemExit as error:
            self._fail(run_id, "extraction_failed", str(error) or "image extraction failed")
        except Exception as error:
            self._fail(run_id, "pipeline_failed", str(error) or error.__class__.__name__)

    async def _crawl(self, run_id: str) -> ImageCandidate | None:
        run = self._update_run(run_id, status="crawling", stage="crawling", progress=5, message="正在抓取网页")
        if run is None:
            raise PipelineError("run_not_found", run_id)
        try:
            async with self.crawl_semaphore:
                snapshot = await self.crawler.crawl(run.requested_url)
        except CrawlFailure as error:
            if error.metadata:
                stored = self.store.write_json(run_id, "crawl.json", error.metadata)
                with self.session_factory() as session:
                    record_artifact(session, run_id, stored, "crawl_metadata")
            raise PipelineError("crawl_failed", str(error)) from error

        stored = self.store.write_json(run_id, "crawl.json", snapshot.metadata)
        with self.session_factory() as session:
            session.add_all(
                ImageCandidate(
                    id=str(uuid4()),
                    run_id=run_id,
                    source_url=item.source_url,
                    resolved_url=item.resolved_url,
                    ordinal=item.ordinal,
                    alt=item.alt,
                    width=item.width,
                    height=item.height,
                )
                for item in snapshot.candidates
            )
            session.commit()
            record_artifact(session, run_id, stored, "crawl_metadata")
            candidates = self._candidates(session, run_id)

        self._update_run(run_id, final_url=snapshot.final_url)
        if not candidates:
            raise PipelineError("no_content_image", "no image found in the configured content area")
        if len(candidates) > 1:
            self._update_run(
                run_id,
                status="awaiting_image_selection",
                stage="awaiting_image_selection",
                progress=25,
                message=f"发现 {len(candidates)} 张正文图片，请选择一张",
            )
            return None

        with self.session_factory() as session:
            candidates[0].selected = True
            session.add(candidates[0])
            session.commit()
            return candidates[0]

    async def _extract_and_export(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            candidate = self._selected_candidate(session, run_id)
            if candidate is None:
                raise PipelineError("image_not_selected", "no image candidate has been selected")

        if candidate.local_path:
            image_path = self.store.absolute_path(candidate.local_path)
            image_sha = candidate.sha256 or ""
        else:
            self._update_run(run_id, stage="downloading", progress=30, message="正在下载图片")
            downloaded = await self.downloader.download(
                ImageCandidateData(
                    source_url=candidate.source_url,
                    resolved_url=candidate.resolved_url,
                    ordinal=candidate.ordinal,
                    alt=candidate.alt,
                    width=candidate.width,
                    height=candidate.height,
                )
            )
            stored = self.store.write_bytes(run_id, f"source{downloaded.extension}", downloaded.content, downloaded.media_type)
            with self.session_factory() as session:
                candidate_record = session.get(ImageCandidate, candidate.id)
                if candidate_record is not None:
                    candidate_record.local_path = stored.relative_path
                    candidate_record.sha256 = downloaded.sha256
                    candidate_record.mime_type = downloaded.media_type
                    session.commit()
                    record_artifact(session, run_id, stored, "source_image")
            image_path = stored.absolute_path
            image_sha = downloaded.sha256

        self._update_run(run_id, status="extracting", stage="extracting", progress=45, message="正在识别图片表格")
        async with self.ocr_semaphore:
            document = await asyncio.to_thread(self.extractor.extract, image_path)
        document = validate_document(document)

        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            envelope = validate_envelope({
                "schema_version": 1,
                "run_id": run.id,
                "source_id": run.source_id,
                "requested_url": run.requested_url,
                "final_url": run.final_url or run.requested_url,
                "image_sha256": image_sha,
                "document": document,
            })

        self._update_run(run_id, status="exporting", stage="exporting", progress=80, message="正在生成结构化结果和 Excel")
        context = ExportContext(run_id=run_id, filename_stem="recognized")
        json_file = self.exporters.get("json").export(envelope, context)
        xlsx_file = self.exporters.get("xlsx").export(document, context)
        json_stored = self.store.write_bytes(run_id, "recognized.json", json_file.content, json_file.media_type)
        xlsx_stored = self.store.write_bytes(run_id, "recognized.xlsx", xlsx_file.content, xlsx_file.media_type)
        with self.session_factory() as session:
            record_artifact(session, run_id, json_stored, "recognized_json")
            record_artifact(session, run_id, xlsx_stored, "recognized_xlsx")
            run = self._get_run(session, run_id)
            baseline_document = None
            if run.baseline_run_id:
                baseline_artifact = self._get_artifact(session, run.baseline_run_id, "recognized_json")
                if baseline_artifact:
                    baseline_envelope = json.loads(self.store.absolute_path(baseline_artifact.relative_path).read_text(encoding="utf-8"))
                    baseline_document = baseline_envelope.get("document")
            diff = compare_documents(document, baseline_document)
            run.comparison_summary = {"has_baseline": diff["has_baseline"], "has_changes": diff["has_changes"], **diff["summary"]}
            run.status = "succeeded"
            run.stage = "succeeded"
            run.progress = 100
            run.message = "处理完成"
            run.finished_at = utc_now()
            run.heartbeat_at = utc_now()
            session.commit()

    def _fail(self, run_id: str, code: str, message: str) -> None:
        self._update_run(
            run_id,
            status="failed",
            stage="failed",
            progress=100,
            message="处理失败",
            error_code=code,
            error_message=message,
            finished_at=utc_now(),
        )
