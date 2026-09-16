from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


Scalar: TypeAlias = str | int | float | None


class MergedCell(BaseModel):
    model_config = ConfigDict(extra="allow")

    r0: int
    r1: int
    c0: int
    c1: int
    value: Scalar = ""
    ocr_item_count: int | None = None
    ocr_min_score: float | None = None
    ocr_max_score: float | None = None


class TableSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str = ""
    bbox: list[int | float] = Field(default_factory=list)
    x_edges: list[int | float] = Field(default_factory=list)
    y_edges: list[int | float] = Field(default_factory=list)
    cells: list[list[Scalar]] = Field(default_factory=list)
    merged_cells: list[MergedCell] = Field(default_factory=list)
    ocr_count: int = 0
    ocr_avg_score: float | None = None
    ocr_low_score_count: int = 0
    strategy: str = ""


class CanonicalDocument(BaseModel):
    """Validated generic document; it intentionally has no domain fields."""

    model_config = ConfigDict(extra="allow")

    version: int = 2
    source: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    bands: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[TableSection] = Field(default_factory=list)
    colored_notes: list[dict[str, Any]] = Field(default_factory=list)
    footer_notes: list[dict[str, Any]] = Field(default_factory=list)
    ocr_boxes: list[dict[str, Any]] = Field(default_factory=list)
    corrections: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class DocumentEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    run_id: str
    source_id: str
    requested_url: str
    final_url: str
    image_sha256: str
    document: CanonicalDocument


def validate_document(data: dict[str, Any]) -> dict[str, Any]:
    return CanonicalDocument.model_validate(data).model_dump(mode="json", exclude_none=False)


def validate_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the persisted application wrapper without narrowing document fields."""
    return DocumentEnvelope.model_validate(data).model_dump(mode="json", exclude_none=False)


def document_json_bytes(data: dict[str, Any]) -> bytes:
    canonical = validate_document(data)
    return json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def document_sha256(data: dict[str, Any]) -> str:
    return hashlib.sha256(document_json_bytes(data)).hexdigest()


def section_column_count(section: dict[str, Any]) -> int:
    rows = section.get("cells", [])
    return max(
        len(section.get("x_edges", [])) - 1,
        *(len(row) for row in rows),
        1,
    )


def structure_signature(data: dict[str, Any]) -> list[dict[str, Any]]:
    signature: list[dict[str, Any]] = []
    for section in data.get("sections", []):
        signature.append(
            {
                "id": section.get("id", ""),
                "label": section.get("label", ""),
                "bbox": section.get("bbox", []),
                "x_edges": section.get("x_edges", []),
                "y_edges": section.get("y_edges", []),
                "row_lengths": [len(row) for row in section.get("cells", [])],
                "merges": sorted(
                    (item.get("r0"), item.get("r1"), item.get("c0"), item.get("c1"))
                    for item in section.get("merged_cells", [])
                ),
            }
        )
    return signature


def _editable_mask(data: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(data)
    for section in masked.get("sections", []):
        for row in section.get("cells", []):
            for index in range(len(row)):
                row[index] = "__EDITABLE_CELL__"
        for merged in section.get("merged_cells", []):
            merged["value"] = "__EDITABLE_CELL__"
    return masked


def validate_revision_document(raw: dict[str, Any], revised: dict[str, Any]) -> dict[str, Any]:
    raw_valid = validate_document(raw)
    revised_valid = validate_document(revised)
    if structure_signature(raw_valid) != structure_signature(revised_valid):
        raise ValueError("only cell values may be edited; table structure must remain unchanged")
    if _editable_mask(raw_valid) != _editable_mask(revised_valid):
        raise ValueError("only cell values may be edited; document metadata must remain unchanged")
    return revised_valid


def cell_value_map(data: dict[str, Any]) -> dict[tuple[str, int, int], Scalar]:
    values: dict[tuple[str, int, int], Scalar] = {}
    for section in data.get("sections", []):
        section_id = str(section.get("id", ""))
        for row_index, row in enumerate(section.get("cells", [])):
            for column_index, value in enumerate(row):
                values[(section_id, row_index, column_index)] = value
    return values


def count_cell_changes(raw: dict[str, Any], revised: dict[str, Any]) -> int:
    before = cell_value_map(raw)
    after = cell_value_map(revised)
    return sum(before.get(key, "") != after.get(key, "") for key in set(before) | set(after))


def sync_merged_values(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the duplicate merge value in sync with its top-left cell."""
    result = copy.deepcopy(data)
    for section in result.get("sections", []):
        cells = section.get("cells", [])
        for merged in section.get("merged_cells", []):
            r0, c0 = int(merged["r0"]), int(merged["c0"])
            if r0 < len(cells) and c0 < len(cells[r0]):
                merged["value"] = cells[r0][c0]
    return result
