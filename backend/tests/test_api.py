from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app.artifacts import record_artifact
from backend.app.contracts import document_sha256
from backend.app.main import create_app
from backend.app.models import Artifact, Run, Source, utc_now

from .conftest import make_document


def _persist_successful_run(app, store, source_url: str = "https://example.com/table") -> tuple[str, str, dict]:
    session_factory = app.state.session_factory
    source_id = str(uuid4())
    run_id = str(uuid4())
    document = make_document("100")
    with session_factory() as session:
        source = Source(
            id=source_id,
            name="测试来源",
            url=source_url,
            normalized_url=source_url,
            profile_key="yafco_image",
            enabled=True,
        )
        run = Run(
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
        session.add(source)
        session.commit()
        session.add(run)
        session.commit()
        envelope = {
            "schema_version": 1,
            "run_id": run_id,
            "source_id": source_id,
            "requested_url": source_url,
            "final_url": source_url,
            "image_sha256": "a" * 64,
            "document": document,
        }
        stored = store.write_json(run_id, "recognized.json", envelope)
        record_artifact(session, run_id, stored, "recognized_json")
        session.refresh(run)
    return source_id, run_id, document


def test_source_lifecycle_and_seeded_sources(tmp_path):
    settings_data = tmp_path / "data"
    from backend.app.config import Settings

    settings = Settings(data_dir=settings_data, database_url=f"sqlite:///{settings_data / 'app.db'}")
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        seeded = client.get("/api/sources").json()
        assert len(seeded) == 3

        response = client.post("/api/sources", json={"url": "https://Example.com/new-page/", "name": "新页面"})
        assert response.status_code == 201
        source = response.json()
        assert source["url"] == "https://Example.com/new-page/"

        duplicate = client.post("/api/sources", json={"url": "https://example.com/new-page#section"})
        assert duplicate.status_code == 409

        disabled = client.patch(f"/api/sources/{source['id']}", json={"enabled": False})
        assert disabled.status_code == 200
        blocked_run = client.post(f"/api/sources/{source['id']}/runs")
        assert blocked_run.status_code == 409

        enabled = client.patch(f"/api/sources/{source['id']}", json={"enabled": True})
        assert enabled.status_code == 200
        queued = client.post(f"/api/sources/{source['id']}/runs")
        assert queued.status_code == 201
        assert queued.json()["source_name"] == "新页面"
        assert queued.json()["status"] == "queued"
        assert queued.json()["baseline_run_id"] is None


def test_source_schedule_can_be_configured_with_a_custom_interval(tmp_path):
    from backend.app.config import Settings

    settings_data = tmp_path / "data"
    settings = Settings(data_dir=settings_data, database_url=f"sqlite:///{settings_data / 'app.db'}")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/sources",
            json={"url": "https://example.com/schedule", "schedule_enabled": True, "schedule_interval_minutes": 15},
        )
        assert response.status_code == 201
        source = response.json()
        assert source["schedule_enabled"] is True
        assert source["schedule_interval_minutes"] == 15
        assert source["next_run_at"] is not None

        updated = client.patch(f"/api/sources/{source['id']}", json={"schedule_interval_minutes": 30}).json()
        assert updated["schedule_interval_minutes"] == 30
        assert updated["next_run_at"] is not None

        disabled = client.patch(f"/api/sources/{source['id']}", json={"schedule_enabled": False}).json()
        assert disabled["schedule_enabled"] is False
        assert disabled["next_run_at"] is None


def test_document_revision_preserves_raw_document_and_exports_revision(tmp_path):
    from backend.app.config import Settings

    settings_data = tmp_path / "data"
    settings = Settings(data_dir=settings_data, database_url=f"sqlite:///{settings_data / 'app.db'}")
    app = create_app(settings)
    store = app.state.artifact_store
    with TestClient(app) as client:
        _, run_id, raw_document = _persist_successful_run(app, store)
        recognized = client.get(f"/api/runs/{run_id}/document").json()
        assert recognized["view"] == "recognized"
        assert recognized["recognized_document_sha256"] == document_sha256(raw_document)
        assert recognized["document"]["sections"][0]["cells"] == [["品种", ""], ["甲", "100"], ["乙", "0.5"]]

        revised = deepcopy(raw_document)
        revised["sections"][0]["cells"][1][1] = "200"
        save = client.put(
            f"/api/runs/{run_id}/revision",
            json={"base_document_sha256": recognized["recognized_document_sha256"], "document": revised},
        )
        assert save.status_code == 200
        revision = save.json()
        assert revision["revision_number"] == 1
        assert revision["changed_cell_count"] == 1

        revised_response = client.get(f"/api/runs/{run_id}/document?view=revised")
        assert revised_response.status_code == 200
        assert revised_response.json()["view"] == "revised"
        assert revised_response.json()["document"]["sections"][0]["cells"][1][1] == "200"
        assert client.get(f"/api/runs/{run_id}/document").json()["document"]["sections"][0]["cells"][1][1] == "100"

        invalid = deepcopy(revised)
        invalid["sections"][0]["cells"][0].append("非法列")
        rejected = client.put(
            f"/api/runs/{run_id}/revision",
            json={"base_document_sha256": recognized["recognized_document_sha256"], "document": invalid},
        )
        assert rejected.status_code == 422

        exported = client.post(f"/api/runs/{run_id}/exports", json={"revision_id": revision["id"], "formats": ["json", "xlsx"]})
        assert exported.status_code == 200
        assert {item["kind"] for item in exported.json()["artifacts"]} == {"revised_json", "revised_xlsx"}
        assert {item["filename"] for item in exported.json()["artifacts"]} == {"revision-001.json", "revision-001.xlsx"}
        for artifact in exported.json()["artifacts"]:
            downloaded = client.get(artifact["download_url"])
            assert downloaded.status_code == 200
            assert downloaded.content


def test_manual_merge_revision_is_exported_to_xlsx(tmp_path):
    from backend.app.config import Settings

    settings_data = tmp_path / "data"
    settings = Settings(data_dir=settings_data, database_url=f"sqlite:///{settings_data / 'app.db'}")
    app = create_app(settings)
    store = app.state.artifact_store
    with TestClient(app) as client:
        _, run_id, raw_document = _persist_successful_run(app, store)
        recognized = client.get(f"/api/runs/{run_id}/document").json()

        revised = deepcopy(raw_document)
        revised["sections"][0]["cells"][1][0] = ""
        revised["sections"][0]["cells"][1][1] = ""
        revised["sections"][0]["cells"][2][0] = ""
        revised["sections"][0]["cells"][2][1] = ""
        revised["sections"][0]["merged_cells"].append({"r0": 1, "r1": 2, "c0": 0, "c1": 1, "value": ""})
        save = client.put(
            f"/api/runs/{run_id}/revision",
            json={"base_document_sha256": recognized["recognized_document_sha256"], "document": revised},
        )
        assert save.status_code == 200

        exported = client.post(f"/api/runs/{run_id}/exports", json={"revision_id": save.json()["id"], "formats": ["xlsx"]})
        assert exported.status_code == 200
        artifact = exported.json()["artifacts"][0]
        workbook = load_workbook(BytesIO(client.get(artifact["download_url"]).content))
        try:
            assert "A7:B8" in {str(item) for item in workbook["识别结果"].merged_cells.ranges}
        finally:
            workbook.close()


def test_compare_endpoint_uses_locked_successful_baseline(tmp_path):
    from backend.app.config import Settings

    settings_data = tmp_path / "data"
    settings = Settings(data_dir=settings_data, database_url=f"sqlite:///{settings_data / 'app.db'}")
    app = create_app(settings)
    store = app.state.artifact_store
    with TestClient(app) as client:
        source_id, baseline_id, _ = _persist_successful_run(app, store, "https://example.com/compare")
        current_id = str(uuid4())
        current_document = make_document("200")
        with app.state.session_factory() as session:
            current = Run(
                id=current_id,
                source_id=source_id,
                requested_url="https://example.com/compare",
                normalized_url="https://example.com/compare",
                profile_key="yafco_image",
                baseline_run_id=baseline_id,
                status="succeeded",
                stage="succeeded",
                progress=100,
                message="处理完成",
                finished_at=utc_now(),
            )
            session.add(current)
            session.commit()
            envelope = {
                "schema_version": 1,
                "run_id": current_id,
                "source_id": source_id,
                "requested_url": "https://example.com/compare",
                "final_url": "https://example.com/compare",
                "image_sha256": "b" * 64,
                "document": current_document,
            }
            stored = store.write_json(current_id, "recognized.json", envelope)
            record_artifact(session, current_id, stored, "recognized_json")

        result = client.get(f"/api/runs/{current_id}/compare")
        assert result.status_code == 200
        payload = result.json()
        assert payload["baseline"]["run_id"] == baseline_id
        assert payload["summary"]["changed_cells"] == 1
