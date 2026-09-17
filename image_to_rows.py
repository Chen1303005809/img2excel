#!/usr/bin/env python3
"""Template-agnostic local image-to-table extraction.

The pipeline intentionally keeps OCR and table geometry separate:

* OpenCV finds repeated horizontal/vertical rules and candidate table regions.
* RapidOCR + ONNX Runtime (CPU) returns text boxes.
* The geometry layer assigns boxes to cells and infers merged cells from
  partial rules.
* When a table has few or no rules, OCR row/column clustering is used as a
  best-effort fallback.

The JSON written by this file is the stable integration boundary.  An Excel
writer, API service, desktop UI, or batch runner can consume it without
knowing anything about OCR internals.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from rapidocr import RapidOCR


def contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return inclusive runs of True values."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    previous = -2
    for index in np.flatnonzero(mask):
        index = int(index)
        if start is None or index != previous + 1:
            if start is not None:
                runs.append((start, previous))
            start = index
        previous = index
    if start is not None:
        runs.append((start, previous))
    return runs


def merge_near(values: Iterable[float], distance: float = 3.0) -> list[int]:
    values = sorted(float(value) for value in values)
    if not values:
        return []
    merged: list[list[float]] = [[values[0]]]
    for value in values[1:]:
        if value - merged[-1][-1] <= distance:
            merged[-1].append(value)
        else:
            merged.append([value])
    return [int(round(sum(group) / len(group))) for group in merged]


def adaptive_binary(gray: np.ndarray) -> np.ndarray:
    """Make dark text/rules foreground without deleting light gray rules."""
    block = 31 if min(gray.shape) >= 80 else 15
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        block,
        10,
    )


def line_masks(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return horizontal and vertical rule masks at two scale-free lengths."""
    height, width = gray.shape
    binary = adaptive_binary(gray)

    horizontal = np.zeros_like(binary)
    vertical = np.zeros_like(binary)
    horizontal_lengths = {max(8, min(220, width // 60)), max(10, min(220, width // 35))}
    vertical_lengths = {max(8, min(220, height // 60)), max(10, min(220, height // 35))}
    for length in horizontal_lengths:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1))
        horizontal = cv2.bitwise_or(horizontal, cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel))
    for length in vertical_lengths:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, length))
        vertical = cv2.bitwise_or(vertical, cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel))
    return horizontal, vertical


def _merge_horizontal_records(records: list[dict[str, float]]) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for record in sorted(records, key=lambda item: item["y"]):
        if merged and abs(record["y"] - merged[-1]["y"]) <= 3:
            current = merged[-1]
            current["y"] = (current["y"] + record["y"]) / 2
            current["x0"] = min(current["x0"], record["x0"])
            current["x1"] = max(current["x1"], record["x1"])
        else:
            merged.append(dict(record))
    return merged


def _merge_vertical_records(records: list[dict[str, float]]) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for record in sorted(records, key=lambda item: item["x"]):
        if merged and abs(record["x"] - merged[-1]["x"]) <= 3:
            current = merged[-1]
            current["x"] = (current["x"] + record["x"]) / 2
            current["y0"] = min(current["y0"], record["y0"])
            current["y1"] = max(current["y1"], record["y1"])
        else:
            merged.append(dict(record))
    return merged


def horizontal_line_records(mask: np.ndarray, min_span_ratio: float = 0.07) -> list[dict[str, float]]:
    _, width = mask.shape
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    records: list[dict[str, float]] = []
    minimum = max(10, int(round(width * min_span_ratio)))
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w >= minimum and w >= max(4, h * 4):
            records.append({"y": y + (h - 1) / 2, "x0": float(x), "x1": float(x + w - 1)})
    return _merge_horizontal_records(records)


def vertical_line_records(mask: np.ndarray, min_span_ratio: float = 0.07) -> list[dict[str, float]]:
    height, _ = mask.shape
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    records: list[dict[str, float]] = []
    minimum = max(10, int(round(height * min_span_ratio)))
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h >= minimum and h >= max(4, w * 4):
            records.append({"x": x + (w - 1) / 2, "y0": float(y), "y1": float(y + h - 1)})
    return _merge_vertical_records(records)


def _typical_gap(values: list[float], default: float) -> float:
    if len(values) < 2:
        return default
    gaps = np.diff(sorted(values))
    gaps = gaps[(gaps > 3) & (gaps < max(default * 20, 400))]
    if len(gaps) == 0:
        return default
    return float(np.percentile(gaps, 35))


def detect_colored_bands(image: np.ndarray) -> list[tuple[int, int]]:
    """Find full-width saturated header bars without assuming purple."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    # A band is expected to be a broad colored strip.  This ignores ordinary
    # red annotations and colored characters because their row density is low.
    mask = (saturation >= 60) & (value >= 45)
    density = mask.mean(axis=1)
    runs = contiguous_runs(density >= 0.45)
    return [(start, end) for start, end in runs if end - start + 1 >= 4]


def detect_line_regions(gray: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    """Detect candidate table blocks from repeated horizontal rules."""
    horizontal, vertical = line_masks(gray)
    records = horizontal_line_records(horizontal)
    if not records:
        return [], horizontal, vertical

    typical = _typical_gap([record["y"] for record in records], default=max(12.0, gray.shape[0] / 120))
    # First split on unusually large whitespace.  A second coalescing pass
    # below joins a genuine large merged row when the surrounding spans match.
    gap_limit = max(32.0, min(100.0, typical * 2.5))
    groups: list[list[dict[str, float]]] = []
    current: list[dict[str, float]] = []
    for record in sorted(records, key=lambda item: item["y"]):
        if current and record["y"] - current[-1]["y"] > gap_limit:
            groups.append(current)
            current = []
        current.append(record)
    if current:
        groups.append(current)

    regions: list[dict[str, Any]] = []
    minimum_width = max(40, int(gray.shape[1] * 0.12))
    for group in groups:
        if len(group) < 2:
            continue
        x0 = int(round(min(record["x0"] for record in group)))
        x1 = int(round(max(record["x1"] for record in group)))
        y0 = int(round(min(record["y"] for record in group)))
        y1 = int(round(max(record["y"] for record in group)))
        if x1 - x0 + 1 < minimum_width or y1 <= y0:
            continue
        regions.append({"x0": x0, "x1": x1, "y0": y0, "y1": y1, "line_records": group})
    return regions, horizontal, vertical


def coalesce_line_regions(regions: list[dict[str, Any]], bands: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Join pieces separated by a tall merged row or a blank note row.

    A large row inside one table can contain no horizontal rule for dozens of
    pixels.  Splitting there creates a fake tiny table and makes local line
    detection much less stable.  We only join pieces with almost identical
    horizontal spans and no colored title band between them.
    """
    if not regions:
        return []
    result: list[dict[str, Any]] = []
    for region in sorted(regions, key=lambda item: item["y0"]):
        if result:
            previous = result[-1]
            previous_width = max(1, previous["x1"] - previous["x0"] + 1)
            current_width = max(1, region["x1"] - region["x0"] + 1)
            overlap = max(0, min(previous["x1"], region["x1"]) - max(previous["x0"], region["x0"]) + 1)
            overlap_ratio = overlap / min(previous_width, current_width)
            gap = region["y0"] - previous["y1"]
            band_between = any(previous["y1"] < band[0] and band[1] < region["y0"] for band in bands)
            if overlap_ratio >= 0.80 and gap <= 100 and not band_between:
                previous["x0"] = min(previous["x0"], region["x0"])
                previous["x1"] = max(previous["x1"], region["x1"])
                previous["y1"] = max(previous["y1"], region["y1"])
                previous["line_records"].extend(region["line_records"])
                continue
        result.append(dict(region))
    return result


def _chunk_from_line_records(
    records: list[dict[str, float]], fallback: dict[str, Any], y0: int, y1: int, band: tuple[int, int] | None
) -> dict[str, Any] | None:
    selected = [record for record in records if y0 <= record["y"] <= y1]
    if len(selected) < 2:
        return None
    return {
        "x0": int(round(min(record["x0"] for record in selected))) if selected else fallback["x0"],
        "x1": int(round(max(record["x1"] for record in selected))) if selected else fallback["x1"],
        "y0": int(y0),
        "y1": int(y1),
        "line_records": selected,
        "band": band,
    }


def split_line_regions_by_bands(
    regions: list[dict[str, Any]], bands: list[tuple[int, int]], image_height: int
) -> list[dict[str, Any]]:
    """Split a long grid into independently OCR'd blocks when colored bars exist."""
    result: list[dict[str, Any]] = []
    for region in regions:
        relevant = [band for band in bands if band[1] >= region["y0"] - 2 and band[0] <= region["y1"] + 2]
        if not relevant:
            result.append(region)
            continue
        cursor = region["y0"]
        previous_band: tuple[int, int] | None = None
        for band in relevant:
            before = _chunk_from_line_records(region["line_records"], region, cursor, band[0] - 1, previous_band)
            if before is not None:
                result.append(before)
            cursor = max(cursor, band[1] + 1)
            previous_band = band
        tail_end = region["y1"]
        # The last border of a screenshot table is often antialiased enough
        # to escape morphology.  If the final colored block is close to the
        # image bottom, let the local crop use the image edge as its border.
        if relevant[-1] == bands[-1] and image_height - 1 - region["y1"] <= max(80, int(image_height * 0.03)):
            tail_end = image_height - 1
        after = _chunk_from_line_records(
            region["line_records"], region, cursor, min(image_height - 1, tail_end), previous_band
        )
        if after is not None:
            result.append(after)
    return result or regions


def text_from_output(result: Any) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    items: list[dict[str, Any]] = []
    for box, text, score in zip(boxes, texts, scores):
        points = np.asarray(box, dtype=float)
        x0 = float(points[:, 0].min())
        y0 = float(points[:, 1].min())
        x1 = float(points[:, 0].max())
        y1 = float(points[:, 1].max())
        value = re.sub(r"\s+", "", str(text).replace("\n", "")).strip()
        if not value:
            continue
        items.append(
            {
                "x": round(x0, 2),
                "y": round(y0, 2),
                "w": round(x1 - x0, 2),
                "h": round(y1 - y0, 2),
                "cx": round((x0 + x1) / 2, 2),
                "cy": round((y0 + y1) / 2, 2),
                "text": value,
                "score": round(float(score), 4),
            }
        )
    return items


def recognize(engine: RapidOCR, image: np.ndarray, scale: float = 1.0) -> list[dict[str, Any]]:
    """Run OCR and return coordinates in the input image's coordinate system."""
    if image.size == 0:
        return []
    if scale != 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    items = text_from_output(engine(image))
    if scale == 1.0:
        return items
    for item in items:
        for key in ("x", "y", "w", "h", "cx", "cy"):
            item[key] = round(float(item[key]) / scale, 2)
    return items


def box_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx0, ly0 = left["x"], left["y"]
    lx1, ly1 = lx0 + left["w"], ly0 + left["h"]
    rx0, ry0 = right["x"], right["y"]
    rx1, ry1 = rx0 + right["w"], ry0 + right["h"]
    ix0, iy0 = max(lx0, rx0), max(ly0, ry0)
    ix1, iy1 = min(lx1, rx1), min(ly1, ry1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = left["w"] * left["h"] + right["w"] * right["h"] - intersection
    return intersection / union if union else 0.0


def dedupe_ocr_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate boxes created by overlapping OCR tiles."""
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value["score"], reverse=True):
        duplicate = False
        for existing in kept:
            distance = math.hypot(item["cx"] - existing["cx"], item["cy"] - existing["cy"])
            close_center = distance <= max(8.0, min(item["h"], existing["h"]) * 0.8)
            if box_iou(item, existing) >= 0.25 or (close_center and item["text"] == existing["text"]):
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return sorted(kept, key=lambda value: (value["y"], value["x"]))


def recognize_tiled(
    engine: RapidOCR, image: np.ndarray, max_tile_height: int = 1600, overlap: int = 90, scale: float = 1.0
) -> list[dict[str, Any]]:
    """OCR long images in overlapping tiles so tiny text is not globally shrunk."""
    height = image.shape[0]
    if height <= max_tile_height:
        return recognize(engine, image, scale=scale)
    step = max(600, max_tile_height - overlap)
    all_items: list[dict[str, Any]] = []
    start = 0
    while start < height:
        end = min(height, start + max_tile_height)
        tile_items = recognize(engine, image[start:end], scale=scale)
        for item in tile_items:
            item = dict(item)
            item["y"] = round(item["y"] + start, 2)
            item["cy"] = round(item["cy"] + start, 2)
            all_items.append(item)
        if end == height:
            break
        start += step
    return dedupe_ocr_items(all_items)


def group_cell_text(items: list[dict[str, Any]]) -> str:
    """Join OCR fragments in reading order while retaining multi-line cells."""
    if not items:
        return ""
    ordered = sorted(items, key=lambda item: (item["cy"], item["cx"]))
    lines: list[list[dict[str, Any]]] = []
    for item in ordered:
        height = max(1.0, item["h"])
        placed = False
        for line in lines:
            center = sum(part["cy"] for part in line) / len(line)
            # A small horizontal OCR drift must not reorder stacked text in a
            # narrow cell.  Cap the same-line tolerance so vertically stacked
            # header fragments stay on separate lines.
            if abs(item["cy"] - center) <= max(4.0, min(12.0, height * 0.65)):
                line.append(item)
                placed = True
                break
        if not placed:
            lines.append([item])
    rendered: list[str] = []
    for line in lines:
        line.sort(key=lambda item: item["cx"])
        rendered.append("".join(item["text"] for item in line))
    return "\n".join(part for part in rendered if part)


def typed_value(text: str) -> str:
    """Keep OCR cell content lossless and text-based.

    Spreadsheet numeric coercion is deliberately left to neither OCR nor the
    web preview.  In particular, ``12%`` must remain ``"12%"`` instead of
    becoming the numeric value ``0.12``.  The exporter can still format
    quality metrics as numbers because those metrics are not recognized cell
    content.
    """
    return text


def locate_cell(cx: float, cy: float, x_edges: list[int], y_edges: list[int]) -> tuple[int, int]:
    column = int(np.searchsorted(x_edges, cx, side="right") - 1)
    row = int(np.searchsorted(y_edges, cy, side="right") - 1)
    return max(0, min(column, len(x_edges) - 2)), max(0, min(row, len(y_edges) - 2))


def horizontal_present(
    gray: np.ndarray, y: int, x0: int, x1: int, horizontal_mask: np.ndarray | None = None
) -> bool:
    """Decide whether a horizontal rule actually crosses one column."""
    if horizontal_mask is not None:
        x0 = min(max(0, x0 + 2), horizontal_mask.shape[1])
        x1 = min(max(x0, x1 - 2), horizontal_mask.shape[1])
        region = horizontal_mask[max(0, y - 2) : min(horizontal_mask.shape[0], y + 3), x0:x1]
        if region.size:
            # Morphological opening keeps long rules and removes individual
            # glyph strokes.  A real rule occupies most of one scanline.
            return float((region > 0).mean(axis=1).max()) >= 0.55
        return False
    y0 = max(0, y - 1)
    y1 = min(gray.shape[0], y + 2)
    x0 = min(max(0, x0 + 2), gray.shape[1])
    x1 = min(max(x0, x1 - 2), gray.shape[1])
    if x1 <= x0:
        return False
    coverage = float((gray[y0:y1, x0:x1] < 240).mean())
    return coverage >= 0.22


def vertical_present(
    gray: np.ndarray, x: int, y0: int, y1: int, vertical_mask: np.ndarray | None = None
) -> bool:
    """Decide whether a vertical rule actually crosses one row."""
    if vertical_mask is not None:
        y0 = min(max(0, y0 + 2), vertical_mask.shape[0])
        y1 = min(max(y0, y1 - 2), vertical_mask.shape[0])
        region = vertical_mask[y0:y1, max(0, x - 2) : min(vertical_mask.shape[1], x + 3)]
        if region.size:
            return float((region > 0).mean(axis=0).max()) >= 0.55
        return False
    x0 = max(0, x - 1)
    x1 = min(gray.shape[1], x + 2)
    y0 = min(max(0, y0 + 2), gray.shape[0])
    y1 = min(max(y0, y1 - 2), gray.shape[0])
    if y1 <= y0:
        return False
    coverage = float((gray[y0:y1, x0:x1] < 240).mean())
    return coverage >= 0.22


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _longest_true_run(values: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _vertical_rule_is_real(gray: np.ndarray, x: int) -> bool:
    """Reject vertical OCR strokes that only look persistent after morphology."""
    left = max(0, x - 1)
    right = min(gray.shape[1], x + 2)
    dark = (gray[:, left:right] < 240).any(axis=1)
    return _longest_true_run(dark) >= max(16, int(round(gray.shape[0] * 0.10)))


def axis_edges(mask: np.ndarray, horizontal: bool, gray: np.ndarray | None = None) -> list[int]:
    if horizontal:
        records = horizontal_line_records(mask, min_span_ratio=0.045)
        values = [record["y"] for record in records]
        length = mask.shape[0]
        return merge_near([0, *values, max(0, length - 1)], distance=3)

    # Text glyphs can contain short vertical strokes, especially in a small
    # table crop.  True column rules persist through a meaningful fraction of
    # the crop, so projection persistence is safer than accepting every
    # vertical contour.  A lower threshold is used only when the strict pass
    # cannot recover a usable grid.
    strength = (mask > 0).sum(axis=0)
    ratios = (0.30, 0.15)
    values: list[float] = []
    for ratio in ratios:
        threshold = max(10, int(round(mask.shape[0] * ratio)))
        candidate = contiguous_runs(strength >= threshold)
        candidate_values = [(start + end) / 2 for start, end in candidate]
        if gray is not None:
            candidate_values = [
                value for value in candidate_values if _vertical_rule_is_real(gray, int(round(value)))
            ]
        if ratio == ratios[0] or len(candidate_values) >= 3:
            values = candidate_values
            if len(candidate_values) >= 3:
                break
    length = mask.shape[1]
    return merge_near([0, *values, max(0, length - 1)], distance=3)


def detect_grid(gray: np.ndarray) -> tuple[list[int], list[int]]:
    horizontal, vertical = line_masks(gray)
    return axis_edges(vertical, horizontal=False, gray=gray), axis_edges(horizontal, horizontal=True)


def _is_document_title_band(band: tuple[int, int], image_height: int) -> bool:
    return band[0] <= max(3, int(round(image_height * 0.01)))


def colored_band_regions(
    gray: np.ndarray,
    bands: list[tuple[int, int]],
    band_labels: list[str],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Build table regions from colored section boundaries when available."""
    if len(bands) < 2:
        return [], []

    first_section = 1 if _is_document_title_band(bands[0], gray.shape[0]) else 0
    regions: list[dict[str, Any]] = []
    note_indices: list[int] = []
    for index in range(first_section, len(bands)):
        band = bands[index]
        y0 = band[1] + 1
        y1 = bands[index + 1][0] - 1 if index + 1 < len(bands) else gray.shape[0] - 1
        if y1 <= y0:
            continue

        local_gray = gray[y0 : y1 + 1]
        x_edges, y_edges = detect_grid(local_gray)
        grid_ok = len(x_edges) >= 3 and len(y_edges) >= 3
        # A final colored band followed only by a plain footer is a note, not
        # another table.  Other intervals remain regions so borderless tables
        # can still use the OCR layout fallback.
        if not grid_ok and index == len(bands) - 1:
            note_indices.append(index)
            continue

        regions.append(
            {
                "x0": 0,
                "x1": gray.shape[1] - 1,
                "y0": y0,
                "y1": y1,
                "line_records": [],
                "band": band,
                "band_index": index,
                "band_label": band_labels[index] if index < len(band_labels) else "",
            }
        )
    return regions, note_indices


def expand_first_region_after_title(
    regions: list[dict[str, Any]],
    title_band: tuple[int, int] | None,
    image_width: int,
) -> list[dict[str, Any]]:
    """Include a table header that line detection separated from its body."""
    if not title_band:
        return regions
    full_width = max(40, int(round(image_width * 0.90)))
    candidates = [
        region
        for region in regions
        if region["y0"] > title_band[1]
        and region["x1"] - region["x0"] + 1 >= full_width
    ]
    if not candidates:
        return regions
    first = min(candidates, key=lambda region: region["y0"])
    first["y0"] = title_band[1] + 1
    return regions


def document_title_regions(
    gray: np.ndarray, title_band: tuple[int, int]
) -> tuple[list[dict[str, Any]], int | None]:
    """Recover table blocks below a single document-level colored title.

    Long tables can contain tall merged rows with only a few local rules.  The
    line-region detector then returns fragments.  A new persistent vertical
    rule is a stronger signal that the column layout changed, so use it to
    split the document into real table blocks and keep the footer outside the
    last grid.
    """
    height, width = gray.shape
    start = title_band[1] + 1
    if start >= height:
        return [], None

    horizontal, vertical = line_masks(gray)
    base_end = min(height, start + max(480, min(700, height - start)))
    base_edges, _ = detect_grid(gray[start:base_end])
    tolerance = max(10, int(round(width * 0.01)))
    minimum_span = max(80, int(round(height * 0.08)))
    extra_rules = [
        record
        for record in vertical_line_records(vertical, min_span_ratio=0.08)
        if record["y1"] - record["y0"] + 1 >= minimum_span
        and record["y0"] > start
        and min(abs(record["x"] - edge) for edge in base_edges) > tolerance
    ]
    if not extra_rules:
        return [], None

    layout_start = int(round(min(record["y0"] for record in extra_rules)))
    full_width_rules = [
        int(round(record["y"]))
        for record in horizontal_line_records(horizontal, min_span_ratio=0.04)
        if record["x0"] <= width * 0.05 and record["x1"] >= width * 0.95
    ]
    table_end = next(
        (line for line in sorted(full_width_rules) if line > layout_start + max(80, int(round(height * 0.03)))),
        height - 1,
    )
    if table_end <= layout_start:
        return [], None

    regions = [
        {
            "x0": 0,
            "x1": width - 1,
            "y0": start,
            "y1": layout_start,
            "line_records": [],
            "band": None,
        },
        {
            "x0": 0,
            "x1": width - 1,
            "y0": layout_start + 1,
            "y1": table_end,
            "line_records": [],
            "band": None,
        },
    ]
    footer_start = table_end + 1 if table_end < height - 1 else None
    return regions, footer_start


def build_merged_cells(
    gray: np.ndarray,
    x_edges: list[int],
    y_edges: list[int],
    items: list[dict[str, Any]],
    horizontal_mask: np.ndarray | None = None,
    vertical_mask: np.ndarray | None = None,
) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """Recover rectangular row/column spans from partial rules around cells."""
    row_count = len(y_edges) - 1
    column_count = len(x_edges) - 1
    if row_count <= 0 or column_count <= 0:
        return [], []
    if horizontal_mask is None or vertical_mask is None:
        detected_horizontal, detected_vertical = line_masks(gray)
        horizontal_mask = horizontal_mask if horizontal_mask is not None else detected_horizontal
        vertical_mask = vertical_mask if vertical_mask is not None else detected_vertical
    uf = UnionFind(row_count * column_count)
    node = lambda row, column: row * column_count + column

    for row in range(row_count - 1):
        y = y_edges[row + 1]
        for column in range(column_count):
            if not horizontal_present(gray, y, x_edges[column], x_edges[column + 1], horizontal_mask):
                uf.union(node(row, column), node(row + 1, column))

    for column in range(column_count - 1):
        x = x_edges[column + 1]
        for row in range(row_count):
            if not vertical_present(gray, x, y_edges[row], y_edges[row + 1], vertical_mask):
                uf.union(node(row, column), node(row, column + 1))

    group_members: dict[int, list[tuple[int, int]]] = {}
    for row in range(row_count):
        for column in range(column_count):
            group_members.setdefault(uf.find(node(row, column)), []).append((row, column))

    groups: dict[int, dict[str, Any]] = {}
    for root, members in group_members.items():
        rows = [member[0] for member in members]
        columns = [member[1] for member in members]
        r0, r1 = min(rows), max(rows)
        c0, c1 = min(columns), max(columns)
        # A union-find group should be rectangular.  If noisy line evidence
        # creates an L-shape, keep those cells separate rather than exporting
        # a merge over unrelated cells.
        if len(members) != (r1 - r0 + 1) * (c1 - c0 + 1):
            for row, column in members:
                groups[node(row, column)] = {"r0": row, "r1": row, "c0": column, "c1": column, "items": []}
        else:
            groups[root] = {"r0": r0, "r1": r1, "c0": c0, "c1": c1, "items": []}

    for item in items:
        column, row = locate_cell(item["cx"], item["cy"], x_edges, y_edges)
        root = uf.find(node(row, column))
        group = groups.get(root)
        if group is None:
            group = groups[node(row, column)]
        group["items"].append(item)

    cells: list[list[Any]] = [["" for _ in range(column_count)] for _ in range(row_count)]
    merged: list[dict[str, Any]] = []
    for group in sorted(groups.values(), key=lambda value: (value["r0"], value["c0"])):
        value_text = group_cell_text(group["items"])
        value = typed_value(value_text)
        cells[group["r0"]][group["c0"]] = value
        scores = [float(item["score"]) for item in group["items"]]
        merged.append(
            {
                "r0": group["r0"],
                "r1": group["r1"],
                "c0": group["c0"],
                "c1": group["c1"],
                "value": value,
                "ocr_item_count": len(group["items"]),
                "ocr_min_score": round(min(scores), 4) if scores else None,
                "ocr_max_score": round(max(scores), 4) if scores else None,
            }
        )
    return cells, merged


def _is_blank_cell(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _merge_is_nontrivial(merged: dict[str, Any]) -> bool:
    return merged["r0"] != merged["r1"] or merged["c0"] != merged["c1"]


def merge_adjacent_empty_cells(
    cells: list[list[Any]], merged_cells: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge adjacent empty cells into non-overlapping rectangular ranges.

    Existing non-trivial merges take precedence.  Empty singleton entries are
    dropped because they do not describe a visible merge and otherwise make
    it impossible to discover adjacent blank cells.
    """
    column_count = max((len(row) for row in cells), default=0)
    if not cells or column_count == 0:
        return [merged for merged in merged_cells if not _is_blank_cell(merged.get("value")) or _merge_is_nontrivial(merged)]

    occupied: set[tuple[int, int]] = set()
    kept: list[dict[str, Any]] = []
    for merged in merged_cells:
        if not _is_blank_cell(merged.get("value")) or _merge_is_nontrivial(merged):
            kept.append(merged)
        if _merge_is_nontrivial(merged):
            for row in range(merged["r0"], merged["r1"] + 1):
                for column in range(merged["c0"], merged["c1"] + 1):
                    occupied.add((row, column))

    candidates = {
        (row, column)
        for row in range(len(cells))
        for column in range(column_count)
        if (row, column) not in occupied and _is_blank_cell(cells[row][column] if column < len(cells[row]) else "")
    }
    if len(candidates) < 2:
        return sorted(kept, key=lambda item: (item["r0"], item["c0"], item["r1"], item["c1"]))

    row_runs: dict[int, list[tuple[int, int]]] = {}
    for row in range(len(cells)):
        runs: list[tuple[int, int]] = []
        column = 0
        while column < column_count:
            if (row, column) not in candidates:
                column += 1
                continue
            start = column
            while column + 1 < column_count and (row, column + 1) in candidates:
                column += 1
            if column - start + 1 >= 2:
                runs.append((start, column))
            column += 1
        row_runs[row] = runs

    run_keys = {(row, run) for row, runs in row_runs.items() for run in runs}
    consumed_runs: set[tuple[int, tuple[int, int]]] = set()
    covered: set[tuple[int, int]] = set()
    additions: list[dict[str, Any]] = []
    for row in range(len(cells)):
        for run in row_runs[row]:
            if (row, run) in consumed_runs:
                continue
            end_row = row
            while (end_row + 1, run) in run_keys:
                end_row += 1
            for covered_row in range(row, end_row + 1):
                consumed_runs.add((covered_row, run))
                covered.update((covered_row, column) for column in range(run[0], run[1] + 1))
            additions.append(
                {
                    "r0": row,
                    "r1": end_row,
                    "c0": run[0],
                    "c1": run[1],
                    "value": "",
                    "ocr_item_count": 0,
                    "ocr_min_score": None,
                    "ocr_max_score": None,
                }
            )

    remaining = candidates - covered
    for column in range(column_count):
        row = 0
        while row < len(cells):
            if (row, column) not in remaining:
                row += 1
                continue
            start = row
            while row + 1 < len(cells) and (row + 1, column) in remaining:
                row += 1
            if row - start + 1 >= 2:
                additions.append(
                    {
                        "r0": start,
                        "r1": row,
                        "c0": column,
                        "c1": column,
                        "value": "",
                        "ocr_item_count": 0,
                        "ocr_min_score": None,
                        "ocr_max_score": None,
                    }
                )
            row += 1

    return sorted(kept + additions, key=lambda item: (item["r0"], item["c0"], item["r1"], item["c1"]))


def cluster_rows(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not items:
        return []
    median_height = float(np.median([max(3.0, item["h"]) for item in items]))
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: value["cy"]):
        threshold = max(5.0, min(24.0, max(item["h"], median_height) * 0.72))
        best: list[dict[str, Any]] | None = None
        best_distance = float("inf")
        for row in rows:
            center = float(np.mean([part["cy"] for part in row]))
            distance = abs(item["cy"] - center)
            if distance <= threshold and distance < best_distance:
                best = row
                best_distance = distance
        if best is None:
            rows.append([item])
        else:
            best.append(item)
    return [sorted(row, key=lambda value: value["x"]) for row in sorted(rows, key=lambda row: np.mean([item["cy"] for item in row]))]


def infer_text_grid(
    items: list[dict[str, Any]], width: int, height: int
) -> tuple[list[list[Any]], list[dict[str, Any]], list[int], list[int]]:
    """Best-effort structure recovery for borderless or broken-line tables."""
    rows = cluster_rows(items)
    if not rows:
        return [], [], [0, max(0, width - 1)], [0, max(0, height - 1)]
    median_height = float(np.median([max(3.0, item["h"]) for item in items]))
    x_starts = [item["x"] for item in items]
    tolerance = max(8.0, min(30.0, median_height * 2.0))
    clusters: list[list[float]] = []
    for value in sorted(x_starts):
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    centers = [float(np.mean(cluster)) for cluster in clusters]
    if not centers:
        centers = [float(width) / 2]
    x_edges = merge_near([0, *[(left + right) / 2 for left, right in zip(centers, centers[1:])], width - 1], distance=2)
    y_centers = [float(np.mean([item["cy"] for item in row])) for row in rows]
    y_edges = merge_near([0, *[(top + bottom) / 2 for top, bottom in zip(y_centers, y_centers[1:])], height - 1], distance=2)
    cells: list[list[Any]] = [["" for _ in range(max(1, len(x_edges) - 1))] for _ in rows]
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row_index, row in enumerate(rows):
        for item in row:
            column = int(np.argmin([abs(item["x"] - center) for center in centers]))
            grouped.setdefault((row_index, column), []).append(item)
    merged: list[dict[str, Any]] = []
    for (row_index, column), cell_items in sorted(grouped.items()):
        value = typed_value(group_cell_text(cell_items))
        cells[row_index][column] = value
        scores = [float(item["score"]) for item in cell_items]
        merged.append(
            {
                "r0": row_index,
                "r1": row_index,
                "c0": column,
                "c1": column,
                "value": value,
                "ocr_min_score": round(min(scores), 4) if scores else None,
                "ocr_max_score": round(max(scores), 4) if scores else None,
            }
        )
    return cells, merged, x_edges, y_edges


def detect_text_regions(items: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    rows = cluster_rows(items)
    if not rows:
        return []
    centers = [float(np.mean([item["cy"] for item in row])) for row in rows]
    typical = _typical_gap(centers, default=18.0)
    gap_limit = max(36.0, min(220.0, typical * 3.5))
    groups: list[list[list[dict[str, Any]]]] = []
    current: list[list[dict[str, Any]]] = []
    previous = None
    for row, center in zip(rows, centers):
        if current and previous is not None and center - previous > gap_limit:
            groups.append(current)
            current = []
        current.append(row)
        previous = center
    if current:
        groups.append(current)

    regions: list[dict[str, Any]] = []
    for group in groups:
        group_items = [item for row in group for item in row]
        if len(group) < 2 and len(group_items) < 4:
            continue
        margin = max(4, int(np.median([item["h"] for item in group_items])))
        regions.append(
            {
                "x0": max(0, int(min(item["x"] for item in group_items)) - margin),
                "x1": min(width - 1, int(max(item["x"] + item["w"] for item in group_items)) + margin),
                "y0": max(0, int(min(item["y"] for item in group_items)) - margin),
                "y1": min(height - 1, int(max(item["y"] + item["h"] for item in group_items)) + margin),
                "line_records": [],
                "band": None,
                "fallback_items": group_items,
            }
        )
    return regions


def _meaningful_band_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop punctuation-only OCR noise from colored bands."""
    return [
        item
        for item in items
        if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", str(item.get("text", "")))
    ]


def _band_label_from_items(items: list[dict[str, Any]]) -> str:
    items = _meaningful_band_items(items)
    if not items:
        return ""
    best = sorted(items, key=lambda item: (len(item["text"]), item["score"]), reverse=True)[0]
    return best["text"]


def _band_text_from_items(items: list[dict[str, Any]]) -> str:
    return group_cell_text(_meaningful_band_items(items)).strip()


def band_label(engine: RapidOCR, image: np.ndarray, band: tuple[int, int]) -> str:
    start, end = band
    return _band_label_from_items(recognize(engine, image[start : end + 1], scale=2.0))


def band_text(engine: RapidOCR, image: np.ndarray, band: tuple[int, int]) -> str:
    """Read all lines in a colored band, retaining multi-line notes."""
    start, end = band
    return _band_text_from_items(recognize(engine, image[start : end + 1], scale=2.0))


def title_from_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    candidates = [item for item in items if item["score"] >= 0.45]
    if not candidates:
        candidates = items
    return sorted(candidates, key=lambda item: (len(item["text"]), item["score"]), reverse=True)[0]["text"]


def reread_cell(engine: RapidOCR, crop: np.ndarray, cell: dict[str, Any]) -> str | None:
    """Re-read only suspicious cells, using a margin-free 2x crop."""
    x0 = min(max(0, int(cell["x0"]) + 2), crop.shape[1])
    x1 = min(max(x0, int(cell["x1"]) - 2), crop.shape[1])
    y0 = min(max(0, int(cell["y0"]) + 2), crop.shape[0])
    y1 = min(max(y0, int(cell["y1"]) - 2), crop.shape[0])
    if x1 <= x0 or y1 <= y0:
        return None
    variants = [crop[y0:y1, x0:x1]]
    gray = cv2.cvtColor(variants[0], cv2.COLOR_BGR2GRAY)
    thresholded = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    variants.append(cv2.cvtColor(thresholded, cv2.COLOR_GRAY2BGR))
    candidates: list[tuple[str, float]] = []
    for variant in variants:
        items = recognize(engine, variant, scale=2.0)
        if not items:
            continue
        text = group_cell_text(items).strip()
        if text:
            candidates.append((text, float(np.mean([item["score"] for item in items]))))
    if not candidates:
        return None
    best_score = max(score for _, score in candidates)
    # Thresholding can raise the average score while dropping punctuation or
    # a whole narrow line.  Among nearly equivalent reads, keep the one with
    # more recognized characters so a crop does not silently lose content.
    eligible = [item for item in candidates if item[1] >= best_score - 0.01]
    return max(eligible, key=lambda item: (len(re.sub(r"\s+", "", item[0])), item[1]))[0]


def needs_reread(value: str, score: float | None) -> bool:
    if not value:
        return False
    suspicious = any(token in value for token in ("%G", "G%", "？", "?", "口"))
    return suspicious or (score is not None and score < 0.78)


def needs_merge_reread(merged: dict[str, Any]) -> bool:
    """Re-read sparse non-trivial merges whose narrow text is easy to miss."""
    if merged["r0"] == merged["r1"] and merged["c0"] == merged["c1"]:
        return False
    return int(merged.get("ocr_item_count", 0)) <= 1


def offset_item(item: dict[str, Any], x_offset: int, y_offset: int) -> dict[str, Any]:
    shifted = dict(item)
    shifted["x"] = round(item["x"] + x_offset, 2)
    shifted["y"] = round(item["y"] + y_offset, 2)
    shifted["cx"] = round(item["cx"] + x_offset, 2)
    shifted["cy"] = round(item["cy"] + y_offset, 2)
    return shifted


def extract(input_path: Path, engine: RapidOCR | None = None) -> dict[str, Any]:
    """Extract one image, optionally reusing an OCR engine owned by a Worker."""
    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"cannot read image: {input_path}")
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    engine = engine or RapidOCR()

    bands = detect_colored_bands(image)
    band_labels: list[str] = []
    band_texts: list[str] = []
    for start, end in bands:
        items = recognize(engine, image[start : end + 1], scale=2.0)
        band_labels.append(_band_label_from_items(items))
        band_texts.append(_band_text_from_items(items))

    colored_regions, note_indices = colored_band_regions(gray, bands, band_labels)
    title_band = bands[0] if bands and _is_document_title_band(bands[0], height) else None
    footer_start: int | None = None
    if colored_regions:
        regions = colored_regions
    else:
        regions = []
        if title_band and len(bands) == 1:
            regions, footer_start = document_title_regions(gray, title_band)
        if not regions:
            line_regions, _, _ = detect_line_regions(gray)
            line_regions = coalesce_line_regions(line_regions, bands)
            regions = split_line_regions_by_bands(line_regions, bands, height)
            regions = expand_first_region_after_title(regions, title_band, width)
    full_ocr: list[dict[str, Any]] = []
    if not regions:
        full_ocr = recognize_tiled(engine, image)
        regions = detect_text_regions(full_ocr, width, height)
        if not regions and full_ocr:
            regions = [{
                "x0": 0,
                "x1": width - 1,
                "y0": 0,
                "y1": height - 1,
                "line_records": [],
                "band": None,
                "fallback_items": full_ocr,
            }]

    if bands and _is_document_title_band(bands[0], height) and band_texts[0]:
        title = band_texts[0]
    elif height > 700:
        title_items = recognize_tiled(engine, image[: min(height, 300)])
        title = title_from_items(title_items)
    else:
        title_items = recognize(engine, image[: min(height, max(120, height // 3))], scale=1.5)
        title = title_from_items(title_items)

    sections: list[dict[str, Any]] = []
    all_boxes: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    strategies: dict[str, int] = {}
    for index, region in enumerate(regions, start=1):
        x0 = max(0, min(width - 1, int(region["x0"])))
        x1 = max(x0 + 1, min(width - 1, int(region["x1"])))
        y0 = max(0, min(height - 1, int(region["y0"])))
        y1 = max(y0 + 1, min(height - 1, int(region["y1"])))
        crop = image[y0 : y1 + 1, x0 : x1 + 1]
        local_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        local_items = dedupe_ocr_items(recognize_tiled(engine, crop))
        x_edges, y_edges = detect_grid(local_gray)
        horizontal_mask, vertical_mask = line_masks(local_gray)
        grid_ok = len(x_edges) >= 3 and len(y_edges) >= 3
        if grid_ok:
            cells, merged_cells = build_merged_cells(
                local_gray, x_edges, y_edges, local_items, horizontal_mask, vertical_mask
            )
            strategy = "opencv_grid"
        else:
            cells, merged_cells, x_edges, y_edges = infer_text_grid(local_items, crop.shape[1], crop.shape[0])
            strategy = "ocr_layout_fallback"
        strategies[strategy] = strategies.get(strategy, 0) + 1

        for item in local_items:
            column, row = locate_cell(item["cx"], item["cy"], x_edges, y_edges)
            item["row"] = row + 1
            item["column"] = column + 1
            item["section"] = index
            all_boxes.append(offset_item(item, x0, y0))

        # Targeted rereads are deliberately conservative.  They improve tiny
        # percentages/numbers without multiplying OCR work for every cell.
        for merged in merged_cells:
            value = str(merged.get("value", ""))
            score = merged.get("ocr_min_score")
            standard_reread = needs_reread(value, score)
            merge_reread = needs_merge_reread(merged)
            if not standard_reread and not merge_reread:
                continue
            cell = {
                "x0": x_edges[merged["c0"]],
                "x1": x_edges[merged["c1"] + 1],
                "y0": y_edges[merged["r0"]],
                "y1": y_edges[merged["r1"] + 1],
            }
            reread = reread_cell(engine, crop, cell)
            if not reread or reread == value:
                continue
            if merge_reread and not standard_reread:
                old_length = len(re.sub(r"\s+", "", value))
                new_length = len(re.sub(r"\s+", "", reread))
                if new_length <= old_length:
                    continue
            merged["value"] = typed_value(reread)
            cells[merged["r0"]][merged["c0"]] = merged["value"]
            corrections.append({"section": index, "from": value, "to": reread, "row": merged["r0"] + 1, "column": merged["c0"] + 1})

        # Preserve blank structural groups and merge adjacent blank cells so
        # the generated preview and XLSX retain the table's empty spans.
        merged_cells = merge_adjacent_empty_cells(cells, merged_cells)
        scores = [float(item["score"]) for item in local_items]
        label = str(region.get("band_label", ""))
        if not label and region.get("band"):
            label = band_label(engine, image, region["band"])
        sections.append(
            {
                "id": f"T{index:02d}",
                "label": label,
                "bbox": [x0, y0, x1, y1],
                "x_edges": [x0 + edge for edge in x_edges],
                "y_edges": [y0 + edge for edge in y_edges],
                "cells": cells,
                "merged_cells": merged_cells,
                "ocr_count": len(local_items),
                "ocr_avg_score": round(float(np.mean(scores)), 4) if scores else None,
                "ocr_low_score_count": sum(score < 0.75 for score in scores),
                "strategy": strategy,
            }
        )

    footer_notes: list[dict[str, Any]] = []
    if footer_start is None and note_indices and max(note_indices) == len(bands) - 1:
        footer_start = bands[max(note_indices)][1] + 1
    if footer_start is not None:
        footer_items = dedupe_ocr_items(recognize_tiled(engine, image[footer_start:]))
        footer_text = group_cell_text(footer_items).strip()
        if footer_text:
            footer_notes.append({"text": footer_text})

    if not full_ocr and not sections:
        full_ocr = recognize_tiled(engine, image)
    return {
        "version": 2,
        "source": {"filename": input_path.name, "width": width, "height": height},
        "title": title,
        "bands": [
            {"y0": start, "y1": end, "text": band_texts[index] if index < len(band_texts) else ""}
            for index, (start, end) in enumerate(bands)
        ],
        "sections": sections,
        "colored_notes": [
            {"band": [bands[index][0], bands[index][1]], "text": band_texts[index]}
            for index in note_indices
            if index < len(band_texts) and band_texts[index]
        ],
        "footer_notes": footer_notes,
        "ocr_boxes": all_boxes,
        "corrections": corrections,
        "metrics": {
            "section_count": len(sections),
            "ocr_box_count": len(all_boxes),
            "ocr_avg_score": round(float(np.mean([item["score"] for item in all_boxes])), 4) if all_boxes else None,
            "ocr_low_score_count": sum(item["score"] < 0.75 for item in all_boxes),
            "strategy_counts": strategies,
            "colored_band_count": len(bands),
            "fallback_used": any(key != "opencv_grid" for key in strategies),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatically extract varied grid tables from a local image.")
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = extract(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], ensure_ascii=False))
    print("sections", [(section["id"], section["label"], len(section["cells"]), section["strategy"]) for section in payload["sections"]])


if __name__ == "__main__":
    main()
