import { describe, expect, it } from "vitest";
import { buildDiffMap, buildQualityMap, cellRangeContains, formatConfidence, mergeCellRange, mergeMaps, parseCellInput, scoreLevel, unmergeCellAt } from "./tableModel";
import type { Document, TableSection } from "./types";

const section: TableSection = {
  id: "S01",
  label: "主表",
  bbox: [],
  x_edges: [0, 50, 100],
  y_edges: [0, 50, 100],
  cells: [["标题", ""], ["甲", 10]],
  merged_cells: [{ r0: 0, r1: 0, c0: 0, c1: 1, value: "标题", ocr_min_score: 0.98 }],
  ocr_count: 2,
  ocr_avg_score: 0.8,
  ocr_low_score_count: 1,
  strategy: "line_grid",
};

const document: Document = {
  version: 2,
  source: {},
  title: "测试",
  bands: [],
  sections: [section],
  colored_notes: [],
  footer_notes: [],
  ocr_boxes: [{ section: 1, row: 2, column: 2, score: 0.61 }],
  corrections: [],
  metrics: {},
};

describe("table view model", () => {
  it("keeps merged-cell geometry and covered coordinates", () => {
    const maps = mergeMaps(section);
    expect(maps.starts.get("0:0")).toEqual({ rowSpan: 1, colSpan: 2, score: 0.98 });
    expect(maps.covered.has("0:1")).toBe(true);
    expect(maps.covered.has("1:1")).toBe(false);
  });

  it("maps one-based OCR boxes to editable zero-based cells", () => {
    expect(buildQualityMap(document).get("S01:1:1")).toBe(0.61);
  });

  it("maps comparison changes to cells for highlighting", () => {
    const map = buildDiffMap({
      run_id: "run",
      baseline: null,
      has_baseline: true,
      has_changes: true,
      summary: { changed_cells: 1, added_cells: 0, removed_cells: 0, added_sections: 0, removed_sections: 0, merge_changes: 0, dimension_changes: 0 },
      sections: [{ kind: "changed", section_id: "S01", baseline_section_id: "S01", label: "主表", before_dimensions: [2, 2], after_dimensions: [2, 2], changes: [{ row: 2, column: 2, kind: "changed", before: 10, after: 11 }], structure_changes: [] }],
    });
    expect(map.get("S01:1:1")).toBe("changed");
  });

  it("keeps recognized and edited cell content as text", () => {
    expect(parseCellInput("12.5%", "")).toBe("12.5%");
    expect(parseCellInput("42", 0)).toBe("42");
    expect(parseCellInput("42", "编号")).toBe("42");
    expect(parseCellInput("", 42)).toBe("");
  });

  it("formats every cell confidence as a percentage", () => {
    expect(formatConfidence(0.987)).toBe("98.7%");
    expect(formatConfidence(0.61)).toBe("61.0%");
    expect(formatConfidence(null)).toBe("—");
  });

  it("assigns score colors to high, medium, and low ranges", () => {
    expect(scoreLevel(0.9)).toBe("high");
    expect(scoreLevel(0.75)).toBe("medium");
    expect(scoreLevel(0.749)).toBe("low");
    expect(scoreLevel(null)).toBe("unknown");
  });

  it("merges a selected range and keeps the top-left value", () => {
    const range = { sectionId: "S01", r0: 1, r1: 1, c0: 0, c1: 1 };
    const merged = mergeCellRange(document, range);
    expect(merged.sections[0].cells[1]).toEqual(["甲", ""]);
    expect(merged.sections[0].merged_cells).toContainEqual({ r0: 1, r1: 1, c0: 0, c1: 1, value: "甲", ocr_min_score: null });
    expect(cellRangeContains(range, 1, 1)).toBe(true);
    expect(cellRangeContains(range, 0, 1)).toBe(false);
    expect(document.sections[0].cells[1][1]).toBe(10);
  });

  it("can remove a manual merge", () => {
    const merged = mergeCellRange(document, { sectionId: "S01", r0: 1, r1: 1, c0: 0, c1: 1 });
    const split = unmergeCellAt(merged, "S01", 1, 0);
    expect(split.sections[0].merged_cells).toEqual(section.merged_cells);
  });
});
