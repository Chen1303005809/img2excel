from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .artifacts import ArtifactStore, record_artifact
from .contracts import (
    count_cell_changes,
    document_sha256,
    sync_merged_values,
    validate_envelope,
    validate_revision_document,
)
from .config import Settings
from .diffing import compare_documents
from .exporters import ExportContext, ExporterRegistry
from .models import (
    Artifact,
    DatabaseImportBatch,
    DatabaseImportIssue,
    DocumentRevision,
    ImageCandidate,
    Run,
    Source,
    utc_now,
)
from .oracle_import import (
    DatabaseImportRequest,
    ImportIssue,
    ImportPlan,
    OracleImportError,
    OracleTemplateWriter,
    OracleWriter,
    build_import_plan,
)
from .scheduling import DEFAULT_SCHEDULE_INTERVAL_MINUTES, create_queued_run, schedule_next_at
from .url_utils import InvalidSourceUrl, default_source_name, normalize_url, validate_fetch_host


class SourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    url: str
    name: str | None = Field(default=None, max_length=200)
    schedule_enabled: bool = False
    schedule_interval_minutes: int = Field(default=DEFAULT_SCHEDULE_INTERVAL_MINUTES, ge=1, le=43_200)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    url: str | None = None
    name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    schedule_enabled: bool | None = None
    schedule_interval_minutes: int | None = Field(default=None, ge=1, le=43_200)


class ImageSelectionRequest(BaseModel):
    candidate_id: str


class RevisionRequest(BaseModel):
    base_document_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    document: dict[str, Any]


class ExportRequest(BaseModel):
    revision_id: str | None = None
    formats: list[Literal["json", "xlsx"]] = Field(default_factory=lambda: ["json", "xlsx"], min_length=1)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite returns timezone-aware values as naive datetimes. They are stored
    # from utc_now(), so restore the UTC marker before sending them to clients.
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def _source_payload(source: Source, latest_run: Run | None = None) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "url": source.url,
        "profile_key": source.profile_key,
        "enabled": source.enabled,
        "schedule_enabled": source.schedule_enabled,
        "schedule_interval_minutes": source.schedule_interval_minutes,
        "next_run_at": _iso(source.next_run_at),
        "created_at": _iso(source.created_at),
        "updated_at": _iso(source.updated_at),
        "latest_run": _run_summary(latest_run) if latest_run else None,
    }


def _run_summary(run: Run | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "stage": run.stage,
        "progress": run.progress,
        "message": run.message,
        "created_at": _iso(run.created_at),
        "finished_at": _iso(run.finished_at),
        "recognition_skipped": run.recognition_skipped,
        "comparison_summary": run.comparison_summary,
    }


def _candidate_payload(candidate: ImageCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "source_url": candidate.source_url,
        "resolved_url": candidate.resolved_url,
        "ordinal": candidate.ordinal,
        "alt": candidate.alt,
        "width": candidate.width,
        "height": candidate.height,
        "selected": candidate.selected,
        "downloaded": bool(candidate.local_path),
        "sha256": candidate.sha256,
        "mime_type": candidate.mime_type,
    }


def _artifact_payload(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "filename": artifact.filename,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "created_at": _iso(artifact.created_at),
        "download_url": f"/api/artifacts/{artifact.id}/download",
        "revision_id": artifact.revision_id,
    }


def _revision_payload(revision: DocumentRevision | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    return {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "base_document_sha256": revision.base_document_sha256,
        "document_sha256": revision.document_sha256,
        "changed_cell_count": revision.changed_cell_count,
        "created_at": _iso(revision.created_at),
    }


def _run_payload(session: Session, run: Run, store: ArtifactStore) -> dict[str, Any]:
    source = session.get(Source, run.source_id)
    candidates = list(session.scalars(select(ImageCandidate).where(ImageCandidate.run_id == run.id).order_by(ImageCandidate.ordinal)))
    artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run.id).order_by(Artifact.created_at)))
    revision = session.scalar(select(DocumentRevision).where(DocumentRevision.run_id == run.id).order_by(desc(DocumentRevision.revision_number)))
    return {
        "id": run.id,
        "source_id": run.source_id,
        "source_name": source.name if source else run.requested_url,
        "requested_url": run.requested_url,
        "final_url": run.final_url,
        "profile_key": run.profile_key,
        "baseline_run_id": run.baseline_run_id,
        "status": run.status,
        "stage": run.stage,
        "progress": run.progress,
        "message": run.message,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "comparison_summary": run.comparison_summary,
        "recognition_skipped": run.recognition_skipped,
        "attempt": run.attempt,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "candidates": [_candidate_payload(item) for item in candidates],
        "artifacts": [_artifact_payload(item) for item in artifacts],
        "latest_revision": _revision_payload(revision),
    }


def _read_json(store: ArtifactStore, relative_path: str) -> dict[str, Any]:
    path = store.absolute_path(relative_path)
    try:
        return validate_envelope(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail="stored document is unavailable or invalid") from error


def _raw_envelope(session: Session, run_id: str, store: ArtifactStore) -> tuple[Artifact, dict[str, Any]]:
    artifact = session.scalar(
        select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == "recognized_json", Artifact.revision_id.is_(None)).order_by(desc(Artifact.created_at))
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="recognized document is not available")
    return artifact, _read_json(store, artifact.relative_path)


def _selected_document(
    session: Session,
    run_id: str,
    view: Literal["recognized", "revised"],
    store: ArtifactStore,
) -> tuple[Artifact, dict[str, Any], dict[str, Any], DocumentRevision | None]:
    raw_artifact, raw_envelope = _raw_envelope(session, run_id, store)
    envelope = raw_envelope
    revision = None
    if view == "revised":
        revision = session.scalar(select(DocumentRevision).where(DocumentRevision.run_id == run_id).order_by(desc(DocumentRevision.revision_number)))
        if revision is not None:
            envelope = _read_json(store, revision.document_path)
    return raw_artifact, raw_envelope, envelope, revision


def _database_import_payload(session: Session, batch: DatabaseImportBatch) -> dict[str, Any]:
    issues = list(
        session.scalars(
            select(DatabaseImportIssue)
            .where(DatabaseImportIssue.batch_id == batch.id)
            .order_by(DatabaseImportIssue.entity_index, DatabaseImportIssue.id)
        )
    )
    return {
        "batch_id": batch.id,
        "run_id": batch.run_id,
        "revision_id": batch.revision_id,
        "view": batch.view,
        "template_type": batch.template_type,
        "template_name": batch.template_name,
        "source_document_sha256": batch.source_document_sha256,
        "fingerprint": batch.entity_fingerprint,
        "status": batch.status,
        "counts": batch.counts,
        "used_derived_warning": batch.used_derived_warning,
        "target_template_ids": batch.target_template_ids,
        "error_message": batch.error_message,
        "created_at": _iso(batch.created_at),
        "updated_at": _iso(batch.updated_at),
        "committed_at": _iso(batch.committed_at),
        "issues": [
            {
                "entity_type": issue.entity_type,
                "entity_index": issue.entity_index,
                "field": issue.field,
                "code": issue.code,
                "message": issue.message,
                "source_cells": issue.source_cells,
            }
            for issue in issues
        ],
    }


def _store_database_import_issues(session: Session, batch_id: str, issues: list[ImportIssue]) -> None:
    session.add_all(
        [
            DatabaseImportIssue(
                id=str(uuid4()),
                batch_id=batch_id,
                entity_type=issue.entity_type,
                entity_index=issue.entity_index,
                field=issue.field,
                code=issue.code,
                message=issue.message,
                source_cells=issue.source_cells,
            )
            for issue in issues
        ]
    )


def build_router(
    session_factory: sessionmaker,
    store: ArtifactStore,
    settings: Settings | None = None,
    oracle_writer: OracleWriter | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    exporters = ExporterRegistry()
    runtime_settings = settings or Settings()
    database_writer = oracle_writer or OracleTemplateWriter(runtime_settings)

    def db() -> Any:
        with session_factory() as session:
            yield session

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/sources")
    def list_sources(session: Session = Depends(db)) -> list[dict[str, Any]]:
        sources = list(session.scalars(select(Source).order_by(Source.created_at)))
        payload = []
        for source in sources:
            latest = session.scalar(select(Run).where(Run.source_id == source.id).order_by(desc(Run.created_at)).limit(1))
            payload.append(_source_payload(source, latest))
        return payload

    @router.post("/sources", status_code=201)
    def create_source(body: SourceCreate, session: Session = Depends(db)) -> dict[str, Any]:
        try:
            normalized = normalize_url(body.url)
            validate_fetch_host(body.url, runtime_settings.allow_private_hosts)
        except InvalidSourceUrl as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if session.scalar(select(Source).where(Source.normalized_url == normalized)) is not None:
            raise HTTPException(status_code=409, detail="source URL already exists")
        now = utc_now()
        source = Source(
            id=str(uuid4()),
            name=body.name or default_source_name(normalized),
            url=body.url.strip(),
            normalized_url=normalized,
            profile_key="yafco_image",
            enabled=True,
            schedule_enabled=body.schedule_enabled,
            schedule_interval_minutes=body.schedule_interval_minutes,
            next_run_at=schedule_next_at(now, body.schedule_interval_minutes) if body.schedule_enabled else None,
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return _source_payload(source)

    @router.patch("/sources/{source_id}")
    def update_source(source_id: str, body: SourceUpdate, session: Session = Depends(db)) -> dict[str, Any]:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="source not found")
        schedule_changed = body.schedule_enabled is not None or body.schedule_interval_minutes is not None
        if body.url is not None:
            try:
                normalized = normalize_url(body.url)
                validate_fetch_host(body.url, runtime_settings.allow_private_hosts)
            except InvalidSourceUrl as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            duplicate = session.scalar(select(Source).where(Source.normalized_url == normalized, Source.id != source_id))
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="source URL already exists")
            source.url = body.url.strip()
            source.normalized_url = normalized
            schedule_changed = True
        if body.name is not None:
            source.name = body.name or default_source_name(source.url)
        if body.enabled is not None:
            source.enabled = body.enabled
        if body.schedule_enabled is not None:
            source.schedule_enabled = body.schedule_enabled
        if body.schedule_interval_minutes is not None:
            source.schedule_interval_minutes = body.schedule_interval_minutes

        now = utc_now()
        if not source.schedule_enabled:
            source.next_run_at = None
        elif schedule_changed or source.next_run_at is None:
            source.next_run_at = schedule_next_at(now, source.schedule_interval_minutes)
        source.updated_at = now
        session.commit()
        return _source_payload(source)

    @router.post("/sources/{source_id}/runs", status_code=201)
    def create_run(source_id: str, session: Session = Depends(db)) -> dict[str, Any]:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="source not found")
        if not source.enabled:
            raise HTTPException(status_code=409, detail="source is disabled")
        run = create_queued_run(session, source)
        session.commit()
        session.refresh(run)
        return _run_payload(session, run, store)

    @router.get("/runs")
    def list_runs(
        source_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(db),
    ) -> list[dict[str, Any]]:
        query = select(Run).order_by(desc(Run.created_at)).offset(offset).limit(limit)
        if source_id:
            query = query.where(Run.source_id == source_id)
        if status:
            query = query.where(Run.status == status)
        return [_run_payload(session, run, store) for run in session.scalars(query)]

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_payload(session, run, store)

    @router.post("/runs/{run_id}/image-selection")
    def select_image(run_id: str, body: ImageSelectionRequest, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "awaiting_image_selection":
            raise HTTPException(status_code=409, detail="run is not waiting for image selection")
        candidate = session.scalar(select(ImageCandidate).where(ImageCandidate.id == body.candidate_id, ImageCandidate.run_id == run_id))
        if candidate is None:
            raise HTTPException(status_code=404, detail="image candidate not found")
        for item in session.scalars(select(ImageCandidate).where(ImageCandidate.run_id == run_id)):
            item.selected = item.id == candidate.id
        run.status = "queued"
        run.stage = "queued"
        run.progress = 25
        run.message = "已选择图片，等待识别"
        run.error_code = None
        run.error_message = None
        run.finished_at = None
        session.commit()
        return _run_payload(session, run, store)

    @router.get("/runs/{run_id}/document")
    def get_document(run_id: str, view: Literal["recognized", "revised"] = "recognized", session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        raw_artifact, raw_envelope, envelope, revision = _selected_document(session, run_id, view, store)
        return {
            "run_id": run_id,
            "view": "revised" if revision else "recognized",
            "recognized_document_sha256": document_sha256(raw_envelope["document"]),
            "document_sha256": document_sha256(envelope["document"]),
            "revision": _revision_payload(revision),
            "document": envelope["document"],
            "raw_artifact": _artifact_payload(raw_artifact),
        }

    @router.post("/runs/{run_id}/database-import/preflight")
    def database_import_preflight(run_id: str, body: DatabaseImportRequest, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "succeeded":
            raise HTTPException(status_code=409, detail="only a successful run can be imported")

        _, raw_envelope, envelope, revision = _selected_document(session, run_id, body.view, store)
        current_document_hash = document_sha256(envelope["document"])
        if body.document_sha256 != current_document_hash:
            raise HTTPException(status_code=409, detail="document changed; reload the entity table before importing")

        actual_view = "revised" if revision else "recognized"
        request = body if body.view == actual_view else body.model_copy(update={"view": actual_view})
        plan, issues = build_import_plan(run_id, envelope["document"], request, runtime_settings)

        duplicate = session.scalar(
            select(DatabaseImportBatch)
            .where(
                DatabaseImportBatch.run_id == run_id,
                DatabaseImportBatch.source_document_sha256 == plan.document_sha256,
                DatabaseImportBatch.template_type == plan.template_type,
                DatabaseImportBatch.entity_fingerprint == plan.fingerprint,
            )
            .order_by(desc(DatabaseImportBatch.created_at))
        )
        if duplicate is not None:
            if duplicate.status == "committed":
                raise HTTPException(status_code=409, detail="相同运行、文档和实体指纹已经成功导入")
            if duplicate.status in {"preflight_succeeded", "committing"}:
                return _database_import_payload(session, duplicate)

        if not issues:
            target_result = database_writer.preflight(plan)
            issues.extend(target_result.issues)
            if target_result.creator_id is not None:
                plan.creator_id = target_result.creator_id

        if duplicate is not None:
            duplicate.revision_id = revision.id if revision else None
            duplicate.view = actual_view
            duplicate.template_type = plan.template_type
            duplicate.template_name = plan.template_name
            duplicate.source_document_sha256 = plan.document_sha256
            duplicate.entity_fingerprint = plan.fingerprint
            duplicate.status = "preflight_succeeded" if not issues else "preflight_failed"
            duplicate.payload = plan.payload()
            duplicate.counts = plan.counts
            duplicate.used_derived_warning = plan.used_derived_warning
            duplicate.target_template_ids = []
            duplicate.error_message = None
            duplicate.committed_at = None
            duplicate.updated_at = utc_now()
            session.execute(delete(DatabaseImportIssue).where(DatabaseImportIssue.batch_id == duplicate.id))
            _store_database_import_issues(session, duplicate.id, issues)
            session.commit()
            session.refresh(duplicate)
            return _database_import_payload(session, duplicate)

        batch = DatabaseImportBatch(
            id=str(uuid4()),
            run_id=run_id,
            revision_id=revision.id if revision else None,
            view=actual_view,
            template_type=plan.template_type,
            template_name=plan.template_name,
            source_document_sha256=plan.document_sha256,
            entity_fingerprint=plan.fingerprint,
            status="preflight_succeeded" if not issues else "preflight_failed",
            payload=plan.payload(),
            counts=plan.counts,
            used_derived_warning=plan.used_derived_warning,
            target_template_ids=[],
        )
        session.add(batch)
        _store_database_import_issues(session, batch.id, issues)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            duplicate = session.scalar(
                select(DatabaseImportBatch)
                .where(
                    DatabaseImportBatch.run_id == run_id,
                    DatabaseImportBatch.source_document_sha256 == plan.document_sha256,
                    DatabaseImportBatch.template_type == plan.template_type,
                    DatabaseImportBatch.entity_fingerprint == plan.fingerprint,
                )
                .order_by(desc(DatabaseImportBatch.created_at))
            )
            if duplicate is not None:
                if duplicate.status == "committed":
                    raise HTTPException(status_code=409, detail="相同运行、文档和实体指纹已经成功导入")
                return _database_import_payload(session, duplicate)
            raise HTTPException(status_code=500, detail="无法保存导入审计批次") from error
        session.refresh(batch)
        return _database_import_payload(session, batch)

    @router.post("/database-imports/{batch_id}/commit")
    def database_import_commit(batch_id: str, session: Session = Depends(db)) -> dict[str, Any]:
        batch = session.get(DatabaseImportBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="database import batch not found")
        if batch.status == "committed":
            return _database_import_payload(session, batch)
        if batch.status != "preflight_succeeded":
            raise HTTPException(status_code=409, detail=f"导入批次当前状态不可提交：{batch.status}")

        run = session.get(Run, batch.run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "succeeded":
            raise HTTPException(status_code=409, detail="only a successful run can be imported")

        _, raw_envelope, envelope, revision = _selected_document(session, batch.run_id, batch.view, store)
        current_document_hash = document_sha256(envelope["document"])
        if current_document_hash != batch.source_document_sha256:
            issue = ImportIssue(
                entity_type="batch",
                entity_index=-1,
                field="documentSha256",
                code="document_changed",
                message="预校验后文档内容发生变化，请重新预校验",
            )
            batch.status = "failed"
            batch.error_message = issue.message
            _store_database_import_issues(session, batch.id, [issue])
            session.commit()
            raise HTTPException(status_code=409, detail=issue.message)
        if (revision is None) != (batch.revision_id is None) or (revision is not None and revision.id != batch.revision_id):
            raise HTTPException(status_code=409, detail="文档修订版本发生变化，请重新预校验")

        plan = ImportPlan.from_payload(batch.payload)
        batch.status = "committing"
        batch.error_message = None
        batch.updated_at = utc_now()
        session.commit()

        try:
            result = database_writer.write(plan)
        except OracleImportError as error:
            session.rollback()
            failed_batch = session.get(DatabaseImportBatch, batch_id)
            if failed_batch is not None:
                failed_batch.status = "rolled_back"
                failed_batch.error_message = str(error)
                failed_batch.updated_at = utc_now()
                session.commit()
            raise HTTPException(status_code=502, detail=str(error)) from error
        except Exception as error:
            session.rollback()
            failed_batch = session.get(DatabaseImportBatch, batch_id)
            if failed_batch is not None:
                failed_batch.status = "rolled_back"
                failed_batch.error_message = f"数据库导入失败，事务已回滚：{error}"
                failed_batch.updated_at = utc_now()
                session.commit()
            raise HTTPException(status_code=502, detail=f"数据库导入失败，事务已回滚：{error}") from error

        committed_batch = session.get(DatabaseImportBatch, batch_id)
        if committed_batch is None:
            raise HTTPException(status_code=500, detail="导入审计批次不存在")
        committed_batch.status = "committed"
        committed_batch.target_template_ids = [result.template_id]
        committed_batch.counts = result.counts
        committed_batch.error_message = None
        committed_batch.committed_at = utc_now()
        committed_batch.updated_at = utc_now()
        session.commit()
        session.refresh(committed_batch)
        return _database_import_payload(session, committed_batch)

    @router.put("/runs/{run_id}/revision")
    def save_revision(run_id: str, body: RevisionRequest, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "succeeded":
            raise HTTPException(status_code=409, detail="only a successful run can be edited")
        _, raw_envelope = _raw_envelope(session, run_id, store)
        raw_document = raw_envelope["document"]
        if body.base_document_sha256 != document_sha256(raw_document):
            raise HTTPException(status_code=409, detail="recognized document changed; reload before saving")
        try:
            revised = sync_merged_values(validate_revision_document(raw_document, body.document))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        previous = session.scalar(select(DocumentRevision).where(DocumentRevision.run_id == run_id).order_by(desc(DocumentRevision.revision_number)))
        revision_number = (previous.revision_number + 1) if previous else 1
        revision_id = str(uuid4())
        payload = copy.deepcopy(raw_envelope)
        payload["revision_id"] = revision_id
        payload["revision_number"] = revision_number
        payload["document"] = revised
        stored = store.write_json(run_id, f"revisions/revision-{revision_number:03d}.json", payload)
        revision = DocumentRevision(
            id=revision_id,
            run_id=run_id,
            revision_number=revision_number,
            base_document_sha256=document_sha256(raw_document),
            document_path=stored.relative_path,
            document_sha256=document_sha256(revised),
            changed_cell_count=count_cell_changes(raw_document, revised),
        )
        session.add(revision)
        session.commit()
        record_artifact(session, run_id, stored, "revised_json", revision_id=revision_id)
        return _revision_payload(revision) or {}

    @router.get("/runs/{run_id}/compare")
    def compare_run(run_id: str, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        _, current_envelope = _raw_envelope(session, run_id, store)
        baseline_run = session.get(Run, run.baseline_run_id) if run.baseline_run_id else None
        baseline_envelope = None
        if baseline_run:
            try:
                _, baseline_envelope = _raw_envelope(session, baseline_run.id, store)
            except HTTPException:
                baseline_run = None
        diff = compare_documents(current_envelope["document"], baseline_envelope["document"] if baseline_envelope else None)
        return {
            "run_id": run_id,
            "baseline": {
                "run_id": baseline_run.id,
                "finished_at": _iso(baseline_run.finished_at),
            }
            if baseline_run
            else None,
            **diff,
        }

    @router.post("/runs/{run_id}/exports")
    def export_run(run_id: str, body: ExportRequest, session: Session = Depends(db)) -> dict[str, Any]:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "succeeded":
            raise HTTPException(status_code=409, detail="only a successful run can be exported")
        _, raw_envelope = _raw_envelope(session, run_id, store)
        revision = None
        envelope = raw_envelope
        if body.revision_id:
            revision = session.scalar(select(DocumentRevision).where(DocumentRevision.id == body.revision_id, DocumentRevision.run_id == run_id))
            if revision is None:
                raise HTTPException(status_code=404, detail="revision not found")
            envelope = _read_json(store, revision.document_path)

        result: list[dict[str, Any]] = []
        for format_name in dict.fromkeys(body.formats):
            kind = ("revised_" if revision else "recognized_") + format_name
            existing = None
            if revision:
                existing = session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.revision_id == revision.id, Artifact.kind == kind).order_by(desc(Artifact.created_at)))
            else:
                existing = session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.revision_id.is_(None), Artifact.kind == kind).order_by(desc(Artifact.created_at)))
            if existing:
                result.append(_artifact_payload(existing))
                continue
            context = ExportContext(run_id=run_id, filename_stem="revision" if revision else "recognized", revision_number=revision.revision_number if revision else None)
            document = envelope["document"]
            exported = exporters.get(format_name).export(envelope if format_name == "json" else document, context)
            relative = f"revisions/{exported.filename}" if revision else exported.filename
            stored = store.write_bytes(run_id, relative, exported.content, exported.media_type)
            artifact = record_artifact(session, run_id, stored, kind, revision_id=revision.id if revision else None)
            result.append(_artifact_payload(artifact))
        return {"run_id": run_id, "revision": _revision_payload(revision), "artifacts": result}

    @router.get("/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str, session: Session = Depends(db)) -> FileResponse:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        path = store.absolute_path(artifact.relative_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact file not found")
        return FileResponse(path, media_type=artifact.media_type, filename=artifact.filename)

    return router
