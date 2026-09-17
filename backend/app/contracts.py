from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


# Numbers remain accepted at the input boundary for legacy artifacts, but
# validated document cells and merged-cell values are normalized to strings.
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


def _ocr_text_by_cell(data: dict[str, Any]) -> dict[tuple[int, int, int], list[str]]:
    """Index legacy OCR text by its one-based document coordinates."""
    result: dict[tuple[int, int, int], list[str]] = {}
    for item in data.get("ocr_boxes", []):
        try:
            key = (int(item["section"]), int(item["row"]), int(item["column"]))
        except (KeyError, TypeError, ValueError):
            continue
        text = item.get("text")
        if text is not None:
            result.setdefault(key, []).append(str(text))
    return result


def _stringify_cell_value(value: Scalar, ocr_text: list[str] | None = None) -> str:
    """Return a stable text representation without guessing numeric meaning."""
    if isinstance(value, str):
        return value
    if ocr_text:
        joined = "".join(part for part in ocr_text if part).strip()
        # Existing runs may have already stored 8% as 0.08.  Recover the
        # original percent only when the same cell's OCR evidence contains a
        # numeric percent marker; never infer a percent from the number alone.
        if re.search(r"\d", joined) and ("%" in joined or "％" in joined):
            return joined
    if value is None:
        return ""
    return str(value)


def _normalize_cell_values(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize recognized cells to strings while preserving legacy percents."""
    result = copy.deepcopy(data)
    ocr_text_by_cell = _ocr_text_by_cell(result)
    for section_index, section in enumerate(result.get("sections", []), start=1):
        for row_index, row in enumerate(section.get("cells", []), start=1):
            for column_index, value in enumerate(row, start=1):
                row[column_index - 1] = _stringify_cell_value(
                    value,
                    ocr_text_by_cell.get((section_index, row_index, column_index)),
                )
        for merged in section.get("merged_cells", []):
            try:
                key = (section_index, int(merged["r0"]) + 1, int(merged["c0"]) + 1)
            except (KeyError, TypeError, ValueError):
                key = None
            merged["value"] = _stringify_cell_value(merged.get("value"), ocr_text_by_cell.get(key) if key else None)
    return result


def validate_document(data: dict[str, Any]) -> dict[str, Any]:
    canonical = CanonicalDocument.model_validate(data).model_dump(mode="json", exclude_none=False)
    return _normalize_cell_values(canonical)


def validate_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the persisted application wrapper without narrowing document fields."""
    envelope = DocumentEnvelope.model_validate(data).model_dump(mode="json", exclude_none=False)
    envelope["document"] = _normalize_cell_values(envelope["document"])
    return envelope


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


def _revision_structure_signature(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the immutable grid shape; merge geometry is user-editable."""
    signature = structure_signature(data)
    for section in signature:
        section.pop("merges", None)
    return signature


def _editable_mask(data: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(data)
    for section in masked.get("sections", []):
        for row in section.get("cells", []):
            for index in range(len(row)):
                row[index] = "__EDITABLE_CELL__"
        # Merge geometry and its duplicate top-left value are edited as one
        # user-controlled presentation detail and validated separately.
        section["merged_cells"] = []
    return masked


def _ranges_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    left_r0, left_r1, left_c0, left_c1 = left
    right_r0, right_r1, right_c0, right_c1 = right
    return not (left_r1 < right_r0 or right_r1 < left_r0 or left_c1 < right_c0 or right_c1 < left_c0)


def _validate_merge_geometry(data: dict[str, Any]) -> None:
    for section in data.get("sections", []):
        rows = section.get("cells", [])
        column_count = section_column_count(section)
        seen: list[tuple[int, int, int, int]] = []
        for index, merged in enumerate(section.get("merged_cells", []), start=1):
            current = (int(merged["r0"]), int(merged["r1"]), int(merged["c0"]), int(merged["c1"]))
            r0, r1, c0, c1 = current
            if r0 < 0 or c0 < 0 or r0 > r1 or c0 > c1:
                raise ValueError(f"merged cell {index} has invalid range")
            if r1 >= len(rows) or c1 >= column_count:
                raise ValueError(f"merged cell {index} is outside the table bounds")
            if any(_ranges_overlap(current, previous) for previous in seen):
                raise ValueError(f"merged cell {index} overlaps another merged cell")
            seen.append(current)


def validate_revision_document(raw: dict[str, Any], revised: dict[str, Any]) -> dict[str, Any]:
    raw_valid = validate_document(raw)
    revised_valid = validate_document(revised)
    if _revision_structure_signature(raw_valid) != _revision_structure_signature(revised_valid):
        raise ValueError("only cell values or merged-cell geometry may be edited; table structure must remain unchanged")
    if _editable_mask(raw_valid) != _editable_mask(revised_valid):
        raise ValueError("only cell values or merged-cell geometry may be edited; document metadata must remain unchanged")
    _validate_merge_geometry(revised_valid)
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
