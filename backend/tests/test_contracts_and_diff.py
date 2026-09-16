from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.contracts import (
    document_sha256,
    sync_merged_values,
    validate_document,
    validate_revision_document,
)
from backend.app.crawling import extract_content_images
from backend.app.diffing import compare_documents
from backend.app.url_utils import InvalidSourceUrl, normalize_url, validate_fetch_host

from .conftest import make_document


def test_url_normalization_and_content_image_discovery():
    assert normalize_url(" HTTPS://Example.COM/path/?b=2#ignored ") == "https://example.com/path?b=2"
    assert normalize_url("http://example.com:80/") == "http://example.com/"
    with pytest.raises(InvalidSourceUrl):
        normalize_url("ftp://example.com/file")
    with pytest.raises(InvalidSourceUrl):
        validate_fetch_host("http://127.0.0.1/table")

    html = """
    <div class='ya-content'><div class='ya-con'>
      <img src='' /><img src='/table-a.png' width='800' height='300' alt='表 A' />
      <img src='https://cdn.example.com/table-b.webp' alt='表 B' />
    </div></div>
    """
    candidates = extract_content_images(html, "https://example.com/page")
    assert [item.ordinal for item in candidates] == [0, 1]
    assert candidates[0].resolved_url == "https://example.com/table-a.png"
    assert candidates[0].width == 800
    assert candidates[1].alt == "表 B"


def test_revision_contract_allows_cell_values_but_rejects_structure_and_metadata_changes():
    raw = validate_document(make_document())
    revised = deepcopy(raw)
    revised["sections"][0]["cells"][1][1] = "200"
    revised["sections"][0]["merged_cells"][0]["value"] = "独立副本"
    accepted = validate_revision_document(raw, revised)
    synced = sync_merged_values(accepted)
    assert synced["sections"][0]["merged_cells"][0]["value"] == "品种"
    assert document_sha256(raw) != document_sha256(accepted)

    changed_structure = deepcopy(raw)
    changed_structure["sections"][0]["cells"][0].append("非法新增列")
    with pytest.raises(ValueError, match="structure"):
        validate_revision_document(raw, changed_structure)

    changed_metadata = deepcopy(raw)
    changed_metadata["title"] = "非法修改标题"
    with pytest.raises(ValueError, match="metadata"):
        validate_revision_document(raw, changed_metadata)


def test_compare_documents_reports_changes_and_no_baseline():
    first = make_document("100")
    assert compare_documents(first, None) == {
        "has_baseline": False,
        "has_changes": False,
        "summary": {
            "changed_cells": 0,
            "added_cells": 0,
            "removed_cells": 0,
            "added_sections": 0,
            "removed_sections": 0,
            "merge_changes": 0,
            "dimension_changes": 0,
        },
        "sections": [],
    }

    changed = make_document("200")
    changed["sections"][0]["cells"][2][1] = ""
    result = compare_documents(changed, first)
    assert result["has_changes"] is True
    assert result["summary"]["changed_cells"] == 1
    assert result["summary"]["removed_cells"] == 1
    assert {item["kind"] for item in result["sections"][0]["changes"]} == {"changed", "removed"}


def test_compare_documents_reports_added_removed_sections_merge_and_dimensions():
    baseline = make_document("100")
    current = make_document("100", merge=False)
    current["sections"].append({
        "id": "S02",
        "label": "新增表",
        "bbox": [0, 0, 100, 30],
        "x_edges": [0, 100],
        "y_edges": [0, 30],
        "cells": [["新增"]],
        "merged_cells": [],
        "ocr_count": 1,
        "ocr_avg_score": 0.9,
        "ocr_low_score_count": 0,
        "strategy": "line_grid",
    })
    result = compare_documents(current, baseline)
    assert result["summary"]["added_sections"] == 1
    assert result["summary"]["merge_changes"] == 1

    removed = compare_documents(baseline, current)
    assert removed["summary"]["removed_sections"] == 1


def test_duplicate_section_labels_fall_back_to_ordinal_matching():
    baseline = make_document("100", label="重复")
    baseline["sections"].append(deepcopy(baseline["sections"][0]))
    baseline["sections"][1]["id"] = "S02"
    baseline["sections"][1]["cells"][1][1] = "200"
    current = deepcopy(baseline)
    current["sections"][0]["cells"][1][1] = "101"
    result = compare_documents(current, baseline)
    assert result["summary"]["changed_cells"] == 1
