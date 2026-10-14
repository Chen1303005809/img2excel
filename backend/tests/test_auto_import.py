from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from backend.app.artifacts import record_artifact
from backend.app.import_service import DatabaseImportService
from backend.app.models import (
    DatabaseImportBatch,
    DatabaseImportBatchRun,
    DatabaseImportIssue,
    Run,
    RunBatch,
    Source,
    SourceGroup,
    utc_now,
)
from backend.app.oracle_import import (
    ImportIssue,
    ImportPlan,
    OraclePreflightResult,
    OracleWriteResult,
    POSITION_TEMPLATE_TYPE,
    source_documents_digest,
)

from .conftest import make_document


def _persist_scheduled_position_pair(session_factory, store):
    future_id = str(uuid4())
    option_id = str(uuid4())
    future_run_id = str(uuid4())
    option_run_id = str(uuid4())
    group_id = "position-limit"
    batch_id = str(uuid4())
    now = utc_now()
    sources = [
        Source(
            id=future_id,
            name="期货限仓",
            url="https://example.com/future",
            normalized_url="https://example.com/future",
            profile_key="yafco_image",
            enabled=True,
        ),
        Source(
            id=option_id,
            name="期权限仓",
            url="https://example.com/option",
            normalized_url="https://example.com/option",
            profile_key="yafco_image",
            enabled=True,
        ),
    ]
    with session_factory() as session:
        session.add_all(sources)
        session.commit()
        session.add(
            SourceGroup(
                id=group_id,
                name="期货与期权限仓",
                future_source_id=future_id,
                option_source_id=option_id,
                schedule_enabled=True,
                schedule_interval_minutes=60,
            )
        )
        session.flush()
        session.add(
            RunBatch(
                id=batch_id,
                source_group_id=group_id,
                kind="position_pair",
                trigger_type="scheduled",
                status="queued",
                auto_import_status="pending",
                created_at=now,
            )
        )
        session.commit()
        runs = [
            Run(
                id=run_id,
                source_id=source.id,
                run_batch_id=batch_id,
                requested_url=source.url,
                normalized_url=source.normalized_url,
                profile_key="yafco_image",
                status="succeeded",
                stage="succeeded",
                progress=100,
                message="处理完成",
                finished_at=now,
            )
            for source, run_id in zip(sources, (future_run_id, option_run_id), strict=True)
        ]
        session.add_all(runs)
        session.commit()
        for source, run in zip(sources, runs, strict=True):
            document = make_document("100")
            document["title"] = source.name
            envelope = {
                "schema_version": 1,
                "run_id": run.id,
                "source_id": source.id,
                "requested_url": source.url,
                "final_url": source.url,
                "image_sha256": "b" * 64,
                "document": document,
            }
            stored = store.write_json(run.id, "recognized.json", envelope)
            record_artifact(session, run.id, stored, "recognized_json")
    return batch_id, (future_run_id, option_run_id), (future_id, option_id)


def _position_entities(documents):
    def row(kind: str) -> dict:
        return {
            "id": f"{kind}-row",
            "type": kind,
            "exchange": "中国金融期货交易所",
            "exchangeCode": "CFFEX",
            "instrument": "AF",
            "productId": "AF",
            "direction": "所有",
            "hedge": "所有",
            "holdingDate": "合约挂牌至交割月份",
            "totalPosition": "0<=持仓量<500000",
            "limitRule": "固定值1000",
            "sourceText": "AF",
            "sourceSectionId": "S01",
            "sourceCells": [],
        }

    return [
        {
            "kind": "position",
            "rows": [row("期权" if "期权" in document["title"] else "期货")],
            "unmappedCells": [],
        }
        for document in documents
    ]


class FakeOracleWriter:
    def __init__(self, blocker_ids: list[str] | None = None, *, fail_write: bool = False):
        self.blocker_ids = blocker_ids or []
        self.fail_write = fail_write
        self.write_plans: list[ImportPlan] = []

    def preflight(self, _plan: ImportPlan) -> OraclePreflightResult:
        issues = (
            [ImportIssue(entity_type="target", field="PUBLISH_STATUS", code="draft_template_conflict", message="存在临时模板")]
            if self.blocker_ids
            else []
        )
        return OraclePreflightResult(creator_id=42, issues=issues, blocking_template_ids=self.blocker_ids)

    def write(self, plan: ImportPlan) -> OracleWriteResult:
        self.write_plans.append(plan)
        if self.fail_write:
            raise RuntimeError("Oracle事务写入失败")
        return OracleWriteResult("9200", ["9201"], ["9202"], [])


def _fake_import_plan(run_records, source_documents):
    return ImportPlan(
        run_id=min(run_id for run_id, _ in run_records),
        view="combined",
        document_sha256=source_documents_digest(source_documents),
        template_type=POSITION_TEMPLATE_TYPE,
        template_name="自动导入-持仓限仓",
        remark="scheduled import",
        application_version="V260123",
        position_rows=[{"product_id": "AF"}],
        open_total_rows=[],
        fingerprint="f" * 64,
        creator_id=42,
        source_documents=source_documents,
    )


def _service(db_env, monkeypatch, writer):
    from backend.app import import_service

    settings, _, session_factory, store = db_env
    monkeypatch.setattr(import_service, "extract_import_entities", _position_entities)
    monkeypatch.setattr(
        import_service,
        "build_import_plan",
        lambda run_id, _document, _body, _settings, *, source_documents, documents_by_run_id=None: (
            _fake_import_plan([(source["run_id"], "") for source in source_documents], source_documents),
            [],
        ),
    )
    return DatabaseImportService(session_factory, store, settings, writer)


def test_scheduled_pair_import_replaces_only_audited_templates_and_is_idempotent(db_env, monkeypatch):
    _, _, session_factory, store = db_env
    run_batch_id, run_ids, _source_ids = _persist_scheduled_position_pair(session_factory, store)
    writer = FakeOracleWriter(["9100"])
    old_run_id = run_ids[0]
    with session_factory() as session:
        session.add(
            DatabaseImportBatch(
                id=str(uuid4()),
                run_id=old_run_id,
                origin="scheduled",
                view="combined",
                template_type=POSITION_TEMPLATE_TYPE,
                template_name="旧定时模板",
                source_document_sha256="a" * 64,
                entity_fingerprint="e" * 64,
                status="committed",
                payload={},
                counts={},
                target_template_ids=["9100"],
            )
        )
        session.commit()

    service = _service(db_env, monkeypatch, writer)
    service.on_run_finished(run_batch_id)
    service.on_run_finished(run_batch_id)

    with session_factory() as session:
        run_batch = session.get(RunBatch, run_batch_id)
        current_batch = session.scalar(
            select(DatabaseImportBatch).where(DatabaseImportBatch.run_batch_id == run_batch_id)
        )
        linked_run_ids = set(
            session.scalars(
                select(DatabaseImportBatchRun.run_id).where(
                    DatabaseImportBatchRun.batch_id == current_batch.id
                )
            )
        )
        runs = [session.get(Run, run_id) for run_id in run_ids]
        assert run_batch is not None and run_batch.auto_import_status == "committed"
        assert current_batch is not None and current_batch.status == "committed"
        assert current_batch.origin == "scheduled"
        assert current_batch.target_template_ids == ["9200"]
        assert current_batch.replaced_template_ids == ["9100"]
        assert linked_run_ids == set(run_ids)
        assert all(run is not None and run.status == "succeeded" for run in runs)
    assert len(writer.write_plans) == 1
    assert writer.write_plans[0].replace_template_ids == ["9100"]


def test_scheduled_pair_keeps_unrecognized_template_and_records_block(db_env, monkeypatch):
    _, _, session_factory, store = db_env
    run_batch_id, _run_ids, _source_ids = _persist_scheduled_position_pair(session_factory, store)
    writer = FakeOracleWriter(["9300"])
    service = _service(db_env, monkeypatch, writer)
    service.on_run_finished(run_batch_id)

    with session_factory() as session:
        run_batch = session.get(RunBatch, run_batch_id)
        audit = session.scalar(
            select(DatabaseImportBatch).where(DatabaseImportBatch.run_batch_id == run_batch_id)
        )
        issue = session.scalar(
            select(DatabaseImportIssue).where(DatabaseImportIssue.batch_id == audit.id)
        )
        assert run_batch is not None and run_batch.auto_import_status == "blocked_by_external_template"
        assert audit is not None and audit.status == "preflight_failed"
        assert issue is not None and issue.code == "external_template_conflict" and "9300" in issue.message
    assert not writer.write_plans


def test_oracle_write_failure_keeps_recognition_success_and_records_error(db_env, monkeypatch):
    _, _, session_factory, store = db_env
    run_batch_id, run_ids, _source_ids = _persist_scheduled_position_pair(session_factory, store)
    writer = FakeOracleWriter(fail_write=True)
    service = _service(db_env, monkeypatch, writer)
    service.on_run_finished(run_batch_id)

    with session_factory() as session:
        run_batch = session.get(RunBatch, run_batch_id)
        audit = session.scalar(select(DatabaseImportBatch).where(DatabaseImportBatch.run_batch_id == run_batch_id))
        runs = [session.get(Run, run_id) for run_id in run_ids]
        assert run_batch is not None and run_batch.auto_import_status == "rolled_back"
        assert audit is not None and audit.status == "rolled_back"
        assert audit.error_message == "Oracle事务写入失败"
        assert all(run is not None and run.status == "succeeded" for run in runs)
