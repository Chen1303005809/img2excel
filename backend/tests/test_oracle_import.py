from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.artifacts import record_artifact
from backend.app.config import Settings
from backend.app.contracts import document_sha256
from backend.app.main import create_app
from backend.app.models import DatabaseImportBatch, Run, Source, utc_now
from backend.app.oracle_import import (
    DatabaseImportRequest,
    ImportPlan,
    OracleImportError,
    OraclePreflightResult,
    OracleWriteResult,
    build_import_plan,
    parse_date_rule,
    parse_limit_rule,
    parse_position_range,
)

from .conftest import make_document


class FakeOracleWriter:
    def __init__(self, *, fail_write: bool = False):
        self.fail_write = fail_write
        self.preflight_calls = 0
        self.write_calls = 0

    def preflight(self, plan: ImportPlan) -> OraclePreflightResult:
        self.preflight_calls += 1
        return OraclePreflightResult(creator_id=42, issues=[])

    def write(self, plan: ImportPlan) -> OracleWriteResult:
        self.write_calls += 1
        if self.fail_write:
            raise OracleImportError("测试明细插入失败")
        if plan.template_type == "TEMP_POSITIONLIMIT_DETAIL":
            return OracleWriteResult("9001", ["9101"], ["9201"], [])
        return OracleWriteResult("9002", [], [], ["9301"])


def _persist_successful_run(app) -> tuple[str, str, dict]:
    store = app.state.artifact_store
    source_id = str(uuid4())
    run_id = str(uuid4())
    document = make_document("100")
    source_url = "https://example.com/import"
    with app.state.session_factory() as session:
        session.add(
            Source(
                id=source_id,
                name="导入测试来源",
                url=source_url,
                normalized_url=source_url,
                profile_key="yafco_image",
                enabled=True,
            )
        )
        session.commit()
        session.add(
            Run(
                id=run_id,
                source_id=source_id,
                requested_url=source_url,
                normalized_url=source_url,
                profile_key="yafco_image",
                status="succeeded",
                stage="succeeded",
                progress=100,
                message="处理完成",
                final_url=source_url,
                finished_at=utc_now(),
            )
        )
        session.commit()
        envelope = {
            "schema_version": 1,
            "run_id": run_id,
            "source_id": source_id,
            "requested_url": source_url,
            "final_url": source_url,
            "image_sha256": "b" * 64,
            "document": document,
        }
        stored = store.write_json(run_id, "recognized.json", envelope)
        record_artifact(session, run_id, stored, "recognized_json")
    return source_id, run_id, document


def _position_request(document: dict) -> dict:
    return {
        "view": "recognized",
        "documentSha256": document_sha256(document),
        "templateType": "TEMP_POSITIONLIMIT_DETAIL",
        "positionRows": [
            {
                "id": "position-1",
                "type": "期货",
                "exchange": "中国金融期货交易所",
                "exchangeCode": "CFFEX",
                "instrument": "AF",
                "productId": "AF",
                "direction": "所有",
                "hedge": "所有",
                "holdingDate": "合约挂牌至交割月份",
                "totalPosition": "0<=持仓量<500000",
                "limitRule": "固定值1000",
                "sourceCells": [],
            }
        ],
        "exceptionRows": [],
    }


def test_import_mapping_rules_are_strict_and_target_oriented():
    assert parse_position_range("0<=持仓量<500000") == (0, 500000)
    assert parse_position_range("500000<=持仓量<+∞") == (500000, -1)
    assert parse_limit_rule("百分比12%") == (0.12, 1)
    assert parse_date_rule("合约挂牌至交割月份").model_dump() == {
        "startmonth": -1,
        "startday": -1,
        "startdaytype": 0,
        "endmonth": -1,
        "endday": -1,
        "enddaytype": 0,
        "startordertype": 0,
        "endordertype": 0,
    }

    settings = Settings(oracle_creator_id=7)
    position = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_POSITIONLIMIT_DETAIL",
        positionRows=[
            {
                "type": "期货",
                "exchange": "中国金融期货交易所",
                "productId": "AF",
                "instrument": "AF",
                "direction": "所有",
                "hedge": "所有",
                "holdingDate": "合约挂牌至交割月份",
                "totalPosition": "0<=持仓量<500000",
                "limitRule": "固定值1000",
            }
        ],
    )
    plan, issues = build_import_plan("run-1", {"sections": []}, position, settings)
    assert issues == []
    assert plan.position_rows == [
        {
            "exchange_id": "CFFEX",
            "product_id": "AF",
            "product_type": 1,
            "position_direction": 2,
            "hedge_flag": 0,
            "startmonth": -1,
            "startday": -1,
            "startdaytype": 0,
            "endmonth": -1,
            "endday": -1,
            "enddaytype": 0,
            "startordertype": 0,
            "endordertype": 0,
            "position_lower": 0,
            "position_upper": 500000,
            "max_position": 1000,
            "max_position_type": 0,
            "source_cells": [],
        }
    ]

    open_total = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_OPENTOTALLIMIT",
        exceptionRows=[
            {
                "exchange": "中国金融期货交易所",
                "instrumentCode": "IO、MO",
                "openTotal": 100,
                "openTotalWarning": 80,
                "instrumentType": "期权",
                "scope": "contract",
                "level": "深度虚值合约",
            }
        ],
    )
    open_plan, open_issues = build_import_plan("run-2", {"sections": []}, open_total, settings)
    assert open_issues == []
    assert open_plan.open_total_rows == [
        {
            "instrument_id": "IO",
            "limit_volume": 100,
            "limit_warn_volume": 80,
            "is_product": 0,
            "is_opt": 1,
            "only_depth": 1,
            "exchange_id": "CFFEX",
            "warning_origin": "derived_80",
            "source_cells": [],
        },
        {
            "instrument_id": "MO",
            "limit_volume": 100,
            "limit_warn_volume": 80,
            "is_product": 0,
            "is_opt": 1,
            "only_depth": 1,
            "exchange_id": "CFFEX",
            "warning_origin": "derived_80",
            "source_cells": [],
        },
    ]
    assert open_plan.used_derived_warning is True


def test_f_suffix_product_code_is_accepted_by_database_import():
    settings = Settings(oracle_creator_id=7)
    request = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_POSITIONLIMIT_DETAIL",
        positionRows=[
            {
                "type": "期货",
                "exchange": "大连商品交易所",
                "instrument": "V_f",
                "productId": "V_f",
                "direction": "所有",
                "hedge": "所有",
                "holdingDate": "合约挂牌至交割月份",
                "totalPosition": "0<=持仓量<+∞",
                "limitRule": "固定值1000",
            }
        ],
    )

    plan, issues = build_import_plan("run-f-suffix", {"sections": []}, request, settings)

    assert issues == []
    assert plan.position_rows[0]["product_id"] == "V_f"


def test_invalid_date_and_warning_stop_before_oracle(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}")
    fake = FakeOracleWriter()
    app = create_app(settings, oracle_writer=fake)
    with TestClient(app) as client:
        _, run_id, document = _persist_successful_run(app)
        payload = _position_request(document)
        payload["positionRows"][0]["holdingDate"] = "未知日期表达"
        response = client.post(f"/api/runs/{run_id}/database-import/preflight", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "preflight_failed"
        assert any(issue["code"] == "unknown_date_rule" for issue in response.json()["issues"])
        assert fake.preflight_calls == 0


def test_unknown_and_duplicate_codes_are_rejected():
    settings = Settings(oracle_creator_id=7)
    row = {
        "type": "期货",
        "exchange": "中国金融期货交易所",
        "instrument": "ZZ",
        "productId": "ZZ",
        "direction": "所有",
        "hedge": "所有",
        "holdingDate": "合约挂牌至交割月份",
        "totalPosition": "0<=持仓量<500000",
        "limitRule": "固定值1000",
    }
    request = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_POSITIONLIMIT_DETAIL",
        positionRows=[row, {**row, "id": "second"}],
    )
    _, issues = build_import_plan("run-unknown", {"sections": []}, request, settings)
    assert sum(issue.code == "unknown_product_code" for issue in issues) == 2
    assert not any(issue.code == "duplicate_position_row" for issue in issues)

    valid_row = {**row, "productId": "AF", "instrument": "AF"}
    duplicate_request = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_POSITIONLIMIT_DETAIL",
        positionRows=[valid_row, {**valid_row, "id": "second"}],
    )
    _, duplicate_issues = build_import_plan("run-duplicate", {"sections": []}, duplicate_request, settings)
    assert any(issue.code == "duplicate_position_row" for issue in duplicate_issues)


def test_database_import_preflight_commit_and_idempotency(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}")
    fake = FakeOracleWriter()
    app = create_app(settings, oracle_writer=fake)
    with TestClient(app) as client:
        _, run_id, document = _persist_successful_run(app)
        preflight = client.post(f"/api/runs/{run_id}/database-import/preflight", json=_position_request(document))
        assert preflight.status_code == 200
        preflight_payload = preflight.json()
        assert preflight_payload["status"] == "preflight_succeeded"
        assert preflight_payload["counts"]["total_rows"] == 1
        assert fake.preflight_calls == 1

        committed = client.post(f"/api/database-imports/{preflight_payload['batch_id']}/commit")
        assert committed.status_code == 200
        assert committed.json()["status"] == "committed"
        assert committed.json()["target_template_ids"] == ["9001"]
        assert fake.write_calls == 1

        duplicate = client.post(f"/api/runs/{run_id}/database-import/preflight", json=_position_request(document))
        assert duplicate.status_code == 409

        replay = client.post(f"/api/database-imports/{preflight_payload['batch_id']}/commit")
        assert replay.status_code == 200
        assert replay.json()["target_template_ids"] == ["9001"]
        with app.state.session_factory() as session:
            batch = session.get(DatabaseImportBatch, preflight_payload["batch_id"])
            assert batch is not None
            assert batch.status == "committed"


def test_database_import_failure_is_audited_as_rolled_back(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}")
    fake = FakeOracleWriter(fail_write=True)
    app = create_app(settings, oracle_writer=fake)
    with TestClient(app) as client:
        _, run_id, document = _persist_successful_run(app)
        preflight = client.post(f"/api/runs/{run_id}/database-import/preflight", json=_position_request(document)).json()
        failed = client.post(f"/api/database-imports/{preflight['batch_id']}/commit")
        assert failed.status_code == 502
        with app.state.session_factory() as session:
            batch = session.get(DatabaseImportBatch, preflight["batch_id"])
            assert batch is not None
            assert batch.status == "rolled_back"
            assert "测试明细插入失败" in (batch.error_message or "")


def test_open_total_validation_rejects_bad_warning(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'app.db'}")
    request = DatabaseImportRequest(
        documentSha256="a" * 64,
        templateType="TEMP_OPENTOTALLIMIT",
        exceptionRows=[
            {
                "exchange": "中国金融期货交易所",
                "instrumentCode": "IO",
                "openTotal": 100,
                "openTotalWarning": 101,
                "instrumentType": "期权",
                "scope": "product",
                "level": "品种级",
            }
        ],
    )
    _, issues = build_import_plan("run-3", {"sections": []}, request, settings)
    assert any(issue.code == "warning_exceeds_limit" for issue in issues)
