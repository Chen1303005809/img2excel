from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from .artifacts import ArtifactStore
from .contracts import document_sha256, validate_envelope
from .entity_extraction import extract_import_entities
from .models import Artifact, DatabaseImportBatch, DatabaseImportBatchRun, DatabaseImportIssue, Run, RunBatch, Source, SourceGroup, utc_now
from .oracle_import import (
    DatabaseImportRequest,
    ImportIssue,
    ImportPlan,
    OracleWriter,
    POSITION_TEMPLATE_TYPE,
    OPEN_TOTAL_TEMPLATE_TYPE,
    build_import_plan,
)
from .config import Settings


class DatabaseImportService:
    """Owns the local audit and Oracle flow shared by scheduled worker imports."""

    def __init__(
        self,
        session_factory: sessionmaker,
        store: ArtifactStore,
        settings: Settings,
        writer: OracleWriter,
    ):
        self.session_factory = session_factory
        self.store = store
        self.settings = settings
        self.writer = writer

    def on_run_finished(self, run_batch_id: str) -> None:
        batch = self._claim_import_attempt(run_batch_id)
        if batch is None:
            return
        try:
            with self.session_factory() as session:
                run_batch = session.get(RunBatch, run_batch_id)
                if run_batch is None:
                    return
                runs = list(session.scalars(select(Run).where(Run.run_batch_id == run_batch_id).order_by(Run.source_id)))
                failed = [run for run in runs if run.status == "failed"]
                waiting = [run for run in runs if run.status not in {"succeeded", "failed"}]
                if waiting:
                    run_batch.status = "processing"
                    run_batch.auto_import_status = "waiting_for_runs"
                    run_batch.auto_import_message = "等待同批次抓取与识别完成"
                    session.commit()
                    return
                if failed:
                    run_batch.status = "failed"
                    run_batch.auto_import_status = "skipped"
                    run_batch.auto_import_message = "同批次存在抓取或识别失败的来源，未执行数据库导入"
                    run_batch.finished_at = utc_now()
                    session.commit()
                    return
                if not runs:
                    run_batch.status = "failed"
                    run_batch.auto_import_status = "skipped"
                    run_batch.auto_import_message = "运行批次没有关联来源运行"
                    run_batch.finished_at = utc_now()
                    session.commit()
                    return
                run_records = [(run.id, run.source_id) for run in runs]

            self._run_preflight_and_commit(run_batch_id, run_records)
        except Exception as error:
            with self.session_factory() as session:
                run_batch = session.get(RunBatch, run_batch_id)
                if run_batch is not None and run_batch.auto_import_status not in {"committed", "preflight_failed", "blocked_by_external_template"}:
                    run_batch.status = "failed"
                    run_batch.auto_import_status = "preflight_failed"
                    run_batch.auto_import_message = str(error) or error.__class__.__name__
                    run_batch.finished_at = utc_now()
                    session.commit()

    def _claim_import_attempt(self, run_batch_id: str) -> RunBatch | None:
        with self.session_factory() as session:
            batch = session.get(RunBatch, run_batch_id)
            if batch is None:
                return None
            if batch.trigger_type != "scheduled":
                runs = list(session.scalars(select(Run).where(Run.run_batch_id == run_batch_id)))
                if runs and all(run.status in {"succeeded", "failed"} for run in runs):
                    batch.status = "failed" if any(run.status == "failed" for run in runs) else "succeeded"
                    batch.finished_at = utc_now()
                    session.commit()
                return None
            if batch.auto_import_status not in {"pending", "waiting_for_runs"}:
                return None
            runs = list(session.scalars(select(Run).where(Run.run_batch_id == run_batch_id)))
            if not runs or any(run.status not in {"succeeded", "failed"} for run in runs):
                session.execute(
                    update(RunBatch)
                    .where(
                        RunBatch.id == run_batch_id,
                        RunBatch.trigger_type == "scheduled",
                        RunBatch.auto_import_status.in_(("pending", "waiting_for_runs")),
                    )
                    .values(
                        status="processing",
                        auto_import_status="waiting_for_runs",
                        auto_import_message="等待同批次抓取与识别完成",
                    )
                )
                session.commit()
                return None
            claim = session.execute(
                update(RunBatch)
                .where(
                    RunBatch.id == run_batch_id,
                    RunBatch.trigger_type == "scheduled",
                    RunBatch.auto_import_status.in_(("pending", "waiting_for_runs")),
                )
                .values(
                    status="processing",
                    auto_import_status="preflighting",
                    auto_import_message="正在执行数据库预校验",
                )
            )
            if claim.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            return session.get(RunBatch, run_batch_id)

    def _recognized_document(self, session: Session, run: Run) -> dict[str, Any]:
        artifact = session.scalar(
            select(Artifact)
            .where(
                Artifact.run_id == run.id,
                Artifact.kind == "recognized_json",
                Artifact.revision_id.is_(None),
            )
            .order_by(Artifact.created_at.desc())
        )
        if artifact is None:
            raise ValueError(f"运行 {run.id} 缺少识别结果")
        path = self.store.absolute_path(artifact.relative_path)
        envelope = validate_envelope(json.loads(path.read_text(encoding="utf-8")))
        return envelope["document"]

    def _run_preflight_and_commit(self, run_batch_id: str, run_records: list[tuple[str, str]]) -> None:
        with self.session_factory() as session:
            run_batch = session.get(RunBatch, run_batch_id)
            if run_batch is None:
                return
            runs = [session.get(Run, run_id) for run_id, _ in run_records]
            if any(run is None for run in runs):
                raise ValueError("导入批次的运行记录不存在")
            documents = [self._recognized_document(session, run) for run in runs if run is not None]
            concrete_runs = [item for item in runs if item is not None]
            sources = []
            for run, document in zip(concrete_runs, documents, strict=True):
                source = session.get(Source, run.source_id)
                sources.append(
                    {
                        "run_id": run.id,
                        "source_name": source.name if source else run.requested_url,
                        "view": "recognized",
                        "document_sha256": document_sha256(document),
                        "revision_id": None,
                    }
                )
            run_batch_kind = run_batch.kind
            source_group = session.get(SourceGroup, run_batch.source_group_id) if run_batch.source_group_id else None
            expected_kind_by_source = (
                {
                    source_group.future_source_id: "future",
                    source_group.option_source_id: "option",
                }
                if source_group is not None
                else {}
            )

        extracted = extract_import_entities(documents)
        plan, issues = self._build_plan(
            run_batch_id,
            run_records,
            documents,
            sources,
            extracted,
            expected_kind_by_source=expected_kind_by_source,
            run_batch_kind=run_batch_kind,
        )
        if plan is None:
            self._finish_without_import(run_batch_id, "skipped", issues[0].message if issues else "文档不支持自动导入")
            return

        target_result = self.writer.preflight(plan)
        issues.extend(target_result.issues)
        if target_result.creator_id is not None:
            plan.creator_id = target_result.creator_id
        replaceable_ids = self._automated_template_ids(plan.template_type, target_result.blocking_template_ids)
        if target_result.blocking_template_ids and set(replaceable_ids) == set(target_result.blocking_template_ids):
            plan.replace_template_ids = sorted(replaceable_ids)
            issues = [issue for issue in issues if issue.code != "draft_template_conflict"]
        elif target_result.blocking_template_ids:
            untrusted_ids = sorted(set(target_result.blocking_template_ids) - set(replaceable_ids))
            issues = [
                ImportIssue(
                    entity_type="target",
                    entity_index=-1,
                    field="PUBLISH_STATUS",
                    code="external_template_conflict",
                    message=f"目标库存在人工创建或无法确认来源的临时模板（ID：{', '.join(untrusted_ids)}），本次不导入",
                )
                if issue.code == "draft_template_conflict"
                else issue
                for issue in issues
            ]

        saved = self._save_preflight(run_batch_id, plan, issues, replaceable_ids=plan.replace_template_ids)
        if saved.origin != "scheduled":
            self._finish_without_import(
                run_batch_id,
                "skipped",
                "同一识别数据已有人工导入记录，定时任务不会代替人工确认提交",
                import_batch_id=saved.id,
            )
            return
        if saved.status == "committed":
            with self.session_factory() as session:
                run_batch = session.get(RunBatch, run_batch_id)
                if run_batch is not None:
                    run_batch.status = "succeeded"
                    run_batch.auto_import_status = "committed"
                    run_batch.auto_import_message = "数据库导入已完成"
                    run_batch.import_batch_id = saved.id
                    run_batch.finished_at = utc_now()
                    session.commit()
            return
        if saved.status != "preflight_succeeded":
            self._finish_without_import(
                run_batch_id,
                "blocked_by_external_template" if any(issue.code == "external_template_conflict" for issue in issues) else "preflight_failed",
                next((issue.message for issue in issues), "自动导入预校验未通过"),
                import_batch_id=saved.id,
            )
            return
        self._commit(run_batch_id, saved.id, plan)

    def _build_plan(
        self,
        run_batch_id: str,
        run_records: list[tuple[str, str]],
        documents: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        extracted: list[dict[str, Any]],
        *,
        expected_kind_by_source: dict[str, str],
        run_batch_kind: str,
    ) -> tuple[ImportPlan | None, list[ImportIssue]]:
        issues: list[ImportIssue] = []
        run_ids = [run_id for run_id, _ in run_records]
        is_pair = len(run_ids) == 2
        if is_pair:
            if any(item.get("kind") != "position" for item in extracted):
                return None, [ImportIssue(entity_type="batch", field="sourceDocuments", code="unsupported_pair", message="限仓批次需要期货与期权两份可识别的限仓表")]
            combined_rows: list[dict[str, Any]] = []
            unmapped: list[str] = []
            for (run_id, source_id), item in zip(run_records, extracted, strict=True):
                expected_kind = expected_kind_by_source.get(source_id)
                expected_type = "期货" if expected_kind == "future" else "期权" if expected_kind == "option" else None
                if expected_type and any(row.get("type") != expected_type for row in item.get("rows", [])):
                    return None, [ImportIssue(entity_type="batch", field="positionRows", code="source_type_mismatch", message=f"来源运行 {run_id} 的限仓表类型与来源配置不匹配")]
                combined_rows.extend({**row, "sourceRunId": run_id} for row in item.get("rows", []))
                unmapped.extend(str(value) for value in item.get("unmappedCells", []))
            body = DatabaseImportRequest.model_validate(
                {
                    "view": "recognized",
                    "documentSha256": sources[0]["document_sha256"],
                    "templateType": POSITION_TEMPLATE_TYPE,
                    "positionRows": combined_rows,
                    "unmappedCells": unmapped,
                    "sourceDocuments": sources,
                }
            )
            documents_by_run_id = dict(zip(run_ids, documents, strict=True))
            plan, issues = build_import_plan(
                min(run_ids),
                documents[0],
                body,
                self.settings,
                source_documents=sources,
                documents_by_run_id=documents_by_run_id,
            )
            return plan, issues

        only = extracted[0]
        run_id = run_ids[0]
        if run_batch_kind == "position_pair":
            return None, [ImportIssue(entity_type="batch", field="sourceDocuments", code="incomplete_pair", message="限仓批次缺少期货或期权限仓来源，未执行自动导入")]
        if only.get("kind") == "position":
            return None, [ImportIssue(entity_type="batch", field="sourceDocuments", code="position_pair_required", message="单来源限仓任务不能自动导入，期货与期权限仓需要同批次配对")]
        if only.get("kind") != "open_total":
            return None, [ImportIssue(entity_type="batch", field="rows", code="unsupported_document", message="识别结果不是支持自动导入的业务表")]
        body = DatabaseImportRequest.model_validate(
            {
                "view": "recognized",
                "documentSha256": sources[0]["document_sha256"],
                "templateType": OPEN_TOTAL_TEMPLATE_TYPE,
                "exceptionRows": only.get("rows", []),
                "unmappedLimitCells": only.get("unmappedLimitCells", []),
            }
        )
        plan, issues = build_import_plan(run_id, documents[0], body, self.settings, source_documents=sources)
        return plan, issues

    def _automated_template_ids(self, template_type: str, blocker_ids: list[str]) -> list[str]:
        if not blocker_ids:
            return []
        with self.session_factory() as session:
            batches = list(
                session.scalars(
                    select(DatabaseImportBatch).where(
                        DatabaseImportBatch.origin == "scheduled",
                        DatabaseImportBatch.status == "committed",
                        DatabaseImportBatch.template_type == template_type,
                    )
                )
            )
        known = {str(template_id) for batch in batches for template_id in batch.target_template_ids}
        return [template_id for template_id in blocker_ids if str(template_id) in known]

    def _save_preflight(
        self,
        run_batch_id: str,
        plan: ImportPlan,
        issues: list[ImportIssue],
        *,
        replaceable_ids: list[str],
    ) -> DatabaseImportBatch:
        plan.replace_template_ids = sorted(str(value) for value in replaceable_ids)
        with self.session_factory() as session:
            run_batch = session.get(RunBatch, run_batch_id)
            if run_batch is None:
                raise ValueError("自动导入运行批次不存在")
            duplicate = session.scalar(
                select(DatabaseImportBatch).where(
                    DatabaseImportBatch.run_id == plan.run_id,
                    DatabaseImportBatch.source_document_sha256 == plan.document_sha256,
                    DatabaseImportBatch.template_type == plan.template_type,
                    DatabaseImportBatch.entity_fingerprint == plan.fingerprint,
                )
            )
            if duplicate is not None and duplicate.origin != "scheduled":
                return duplicate
            batch = session.scalar(
                select(DatabaseImportBatch).where(
                    DatabaseImportBatch.run_batch_id == run_batch_id,
                    DatabaseImportBatch.origin == "scheduled",
                )
            )
            if batch is not None and batch.status == "committed":
                return batch
            if batch is None:
                batch = DatabaseImportBatch(
                    id=str(uuid4()),
                    run_id=plan.run_id,
                    run_batch_id=run_batch_id,
                    origin="scheduled",
                    revision_id=None,
                    view=plan.view,
                    template_type=plan.template_type,
                    template_name=plan.template_name,
                    source_document_sha256=plan.document_sha256,
                    entity_fingerprint=plan.fingerprint,
                    status="preflight_succeeded" if not issues else "preflight_failed",
                    payload=plan.payload(),
                    counts=plan.counts,
                    used_derived_warning=plan.used_derived_warning,
                    target_template_ids=[],
                    replaced_template_ids=plan.replace_template_ids,
                )
                session.add(batch)
            else:
                batch.view = plan.view
                batch.template_type = plan.template_type
                batch.template_name = plan.template_name
                batch.source_document_sha256 = plan.document_sha256
                batch.entity_fingerprint = plan.fingerprint
                batch.status = "preflight_succeeded" if not issues else "preflight_failed"
                batch.payload = plan.payload()
                batch.counts = plan.counts
                batch.used_derived_warning = plan.used_derived_warning
                batch.replaced_template_ids = plan.replace_template_ids
                batch.error_message = None
                batch.updated_at = utc_now()
                session.execute(delete(DatabaseImportIssue).where(DatabaseImportIssue.batch_id == batch.id))
            source_run_ids = [str(source["run_id"]) for source in plan.source_documents]
            linked = set(
                session.scalars(
                    select(DatabaseImportBatchRun.run_id).where(
                        DatabaseImportBatchRun.batch_id == batch.id,
                        DatabaseImportBatchRun.run_id.in_(source_run_ids),
                    )
                )
            ) if source_run_ids else set()
            session.add_all(
                DatabaseImportBatchRun(batch_id=batch.id, run_id=run_id)
                for run_id in dict.fromkeys(source_run_ids)
                if run_id not in linked
            )
            session.add_all(
                DatabaseImportIssue(
                    id=str(uuid4()),
                    batch_id=batch.id,
                    entity_type=issue.entity_type,
                    entity_index=issue.entity_index,
                    field=issue.field,
                    code=issue.code,
                    message=issue.message,
                    source_cells=issue.source_cells,
                )
                for issue in issues
            )
            run_batch.import_batch_id = batch.id
            run_batch.auto_import_status = batch.status
            run_batch.auto_import_message = issues[0].message if issues else "预校验通过，正在提交数据库"
            session.commit()
            session.refresh(batch)
            return batch

    def _finish_without_import(
        self,
        run_batch_id: str,
        status: str,
        message: str,
        *,
        import_batch_id: str | None = None,
    ) -> None:
        with self.session_factory() as session:
            batch = session.get(RunBatch, run_batch_id)
            if batch is None:
                return
            batch.status = "succeeded" if status == "skipped" else "failed"
            batch.auto_import_status = status
            batch.auto_import_message = message
            if import_batch_id:
                batch.import_batch_id = import_batch_id
            batch.finished_at = utc_now()
            session.commit()

    def _commit(self, run_batch_id: str, batch_id: str, plan: ImportPlan) -> None:
        with self.session_factory() as session:
            batch = session.get(DatabaseImportBatch, batch_id)
            run_batch = session.get(RunBatch, run_batch_id)
            if batch is None or run_batch is None:
                raise ValueError("自动导入审计批次不存在")
            if batch.status == "committed":
                run_batch.status = "succeeded"
                run_batch.auto_import_status = "committed"
                run_batch.auto_import_message = "数据库导入已完成"
                session.commit()
                return
            batch.status = "committing"
            batch.error_message = None
            batch.updated_at = utc_now()
            run_batch.auto_import_status = "committing"
            run_batch.auto_import_message = "正在写入数据库"
            session.commit()

        try:
            result = self.writer.write(plan)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            with self.session_factory() as session:
                batch = session.get(DatabaseImportBatch, batch_id)
                run_batch = session.get(RunBatch, run_batch_id)
                if batch is not None:
                    batch.status = "rolled_back"
                    batch.error_message = message
                    batch.updated_at = utc_now()
                if run_batch is not None:
                    run_batch.status = "failed"
                    run_batch.auto_import_status = "rolled_back"
                    run_batch.auto_import_message = message
                    run_batch.finished_at = utc_now()
                session.commit()
            return

        with self.session_factory() as session:
            batch = session.get(DatabaseImportBatch, batch_id)
            run_batch = session.get(RunBatch, run_batch_id)
            if batch is None or run_batch is None:
                return
            batch.status = "committed"
            batch.target_template_ids = [result.template_id]
            batch.replaced_template_ids = plan.replace_template_ids
            batch.counts = result.counts
            batch.error_message = None
            batch.committed_at = utc_now()
            batch.updated_at = utc_now()
            run_batch.status = "succeeded"
            run_batch.auto_import_status = "committed"
            run_batch.auto_import_message = f"数据库导入成功，模板 {result.template_id}"
            run_batch.import_batch_id = batch.id
            run_batch.finished_at = utc_now()
            session.commit()
