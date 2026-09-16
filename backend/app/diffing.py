from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import Scalar, section_column_count


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _normalized_value(value: Scalar) -> tuple[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        try:
            return ("number", Decimal(str(value)))
        except InvalidOperation:
            return ("number", str(value))
    return ("text", str(value))


def _value_equal(left: Scalar, right: Scalar) -> bool:
    return _normalized_value(left) == _normalized_value(right)


def _section_matches(current: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> list[tuple[int, int | None]]:
    current_by_label: dict[str, list[int]] = defaultdict(list)
    baseline_by_label: dict[str, list[int]] = defaultdict(list)
    for index, section in enumerate(current):
        label = _normalized_label(section.get("label"))
        if label:
            current_by_label[label].append(index)
    for index, section in enumerate(baseline):
        label = _normalized_label(section.get("label"))
        if label:
            baseline_by_label[label].append(index)

    used: set[int] = set()
    matches: list[tuple[int, int | None]] = []
    unmatched_current: list[int] = []
    for current_index, section in enumerate(current):
        label = _normalized_label(section.get("label"))
        # A label is a stable identity only when it is unique on both sides.
        # Duplicate labels fall through to the ordinal matching pass below.
        candidates = (
            baseline_by_label.get(label, [])
            if label and len(current_by_label.get(label, [])) == 1 and len(baseline_by_label.get(label, [])) == 1
            else []
        )
        candidate = next((index for index in candidates if index not in used), None)
        if candidate is None:
            unmatched_current.append(current_index)
        else:
            used.add(candidate)
            matches.append((current_index, candidate))

    for current_index in unmatched_current:
        candidate = current_index if current_index < len(baseline) and current_index not in used else None
        if candidate is None:
            candidate = next((index for index in range(len(baseline)) if index not in used), None)
        if candidate is None:
            matches.append((current_index, None))
        else:
            used.add(candidate)
            matches.append((current_index, candidate))

    matches.extend((index, None) for index in range(len(current)) if index not in {item[0] for item in matches})
    matches.extend((None, index) for index in range(len(baseline)) if index not in used)
    return sorted(matches, key=lambda item: (item[0] is None, item[0] if item[0] is not None else item[1] or 0))


def _section_cell_map(section: dict[str, Any]) -> dict[tuple[int, int], Scalar]:
    return {
        (row_index, column_index): value
        for row_index, row in enumerate(section.get("cells", []))
        for column_index, value in enumerate(row)
    }


def _merge_geometry(section: dict[str, Any]) -> set[tuple[int, int, int, int]]:
    return {
        (int(item.get("r0", 0)), int(item.get("r1", 0)), int(item.get("c0", 0)), int(item.get("c1", 0)))
        for item in section.get("merged_cells", [])
    }


def _section_dimensions(section: dict[str, Any]) -> tuple[int, int]:
    return (len(section.get("cells", [])), section_column_count(section))


def _content_changes(section: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for row, values in enumerate(section.get("cells", [])):
        for column, value in enumerate(values):
            if _normalized_value(value) is None:
                continue
            changes.append(
                {
                    "row": row + 1,
                    "column": column + 1,
                    "kind": kind,
                    "before": value if kind == "removed" else "",
                    "after": value if kind == "added" else "",
                }
            )
    return changes


def compare_documents(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact cell and structure diff for two generic table documents."""
    if baseline is None:
        return {
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

    current_sections = current.get("sections", [])
    baseline_sections = baseline.get("sections", [])
    summary = Counter()
    diff_sections: list[dict[str, Any]] = []

    for current_index, baseline_index in _section_matches(current_sections, baseline_sections):
        if current_index is None:
            section = baseline_sections[baseline_index]
            summary["removed_sections"] += 1
            changes = _content_changes(section, "removed")
            summary["removed_cells"] += len(changes)
            diff_sections.append(
                {
                    "kind": "removed",
                    "section_id": None,
                    "baseline_section_id": section.get("id", ""),
                    "label": section.get("label", ""),
                    "before_dimensions": _section_dimensions(section),
                    "after_dimensions": None,
                    "changes": changes,
                    "structure_changes": ["section_removed"],
                }
            )
            continue
        if baseline_index is None:
            section = current_sections[current_index]
            summary["added_sections"] += 1
            changes = _content_changes(section, "added")
            summary["added_cells"] += len(changes)
            diff_sections.append(
                {
                    "kind": "added",
                    "section_id": section.get("id", ""),
                    "baseline_section_id": None,
                    "label": section.get("label", ""),
                    "before_dimensions": None,
                    "after_dimensions": _section_dimensions(section),
                    "changes": changes,
                    "structure_changes": ["section_added"],
                }
            )
            continue

        current_section = current_sections[current_index]
        baseline_section = baseline_sections[baseline_index]
        current_cells = _section_cell_map(current_section)
        baseline_cells = _section_cell_map(baseline_section)
        changes: list[dict[str, Any]] = []
        for row, column in sorted(set(current_cells) | set(baseline_cells)):
            before = baseline_cells.get((row, column), "")
            after = current_cells.get((row, column), "")
            before_present = _normalized_value(before) is not None
            after_present = _normalized_value(after) is not None
            if _value_equal(before, after):
                continue
            kind = "changed" if before_present and after_present else "added" if after_present else "removed"
            summary[f"{kind}_cells"] += 1
            changes.append(
                {
                    "row": row + 1,
                    "column": column + 1,
                    "kind": kind,
                    "before": before,
                    "after": after,
                }
            )

        before_dimensions = _section_dimensions(baseline_section)
        after_dimensions = _section_dimensions(current_section)
        structure_changes: list[str] = []
        if before_dimensions != after_dimensions:
            summary["dimension_changes"] += 1
            structure_changes.append("dimensions_changed")
        before_merges = _merge_geometry(baseline_section)
        after_merges = _merge_geometry(current_section)
        merge_added = sorted(after_merges - before_merges)
        merge_removed = sorted(before_merges - after_merges)
        if merge_added or merge_removed:
            summary["merge_changes"] += len(merge_added) + len(merge_removed)
            structure_changes.append("merged_cells_changed")
        if changes or structure_changes:
            diff_sections.append(
                {
                    "kind": "changed" if changes or structure_changes else "same",
                    "section_id": current_section.get("id", ""),
                    "baseline_section_id": baseline_section.get("id", ""),
                    "label": current_section.get("label", "") or baseline_section.get("label", ""),
                    "before_dimensions": before_dimensions,
                    "after_dimensions": after_dimensions,
                    "changes": changes,
                    "structure_changes": structure_changes,
                    "merge_added": [list(item) for item in merge_added],
                    "merge_removed": [list(item) for item in merge_removed],
                }
            )

    normalized_summary = {
        "changed_cells": summary["changed_cells"],
        "added_cells": summary["added_cells"],
        "removed_cells": summary["removed_cells"],
        "added_sections": summary["added_sections"],
        "removed_sections": summary["removed_sections"],
        "merge_changes": summary["merge_changes"],
        "dimension_changes": summary["dimension_changes"],
    }
    return {
        "has_baseline": True,
        "has_changes": any(normalized_summary.values()),
        "summary": normalized_summary,
        "sections": diff_sections,
    }
