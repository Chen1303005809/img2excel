import { describe, expect, it } from "vitest";
import { buildDiffMap, buildQualityMap, formatConfidence, mergeMaps, parseCellInput } from "./tableModel";
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

  it("parses explicit percentages while preserving text cells", () => {
    expect(parseCellInput("12.5%", "")).toBe(0.125);
    expect(parseCellInput("42", 0)).toBe(42);
    expect(parseCellInput("42", "编号")).toBe("42");
    expect(parseCellInput("", 42)).toBe("");
  });

  it("formats every cell confidence as a percentage", () => {
    expect(formatConfidence(0.987)).toBe("98.7%");
    expect(formatConfidence(0.61)).toBe("61.0%");
    expect(formatConfidence(null)).toBe("—");
  });
});
