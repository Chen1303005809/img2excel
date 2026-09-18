import type { CellChange, CompareResult, Document, MergedCell, Scalar, SourceCellRef, TableSection } from "./types";

export type MergeStart = { rowSpan: number; colSpan: number; score: number | null };
export type CellBounds = { r0: number; r1: number; c0: number; c1: number };
export type CellRange = CellBounds & { sectionId: string };
export type ScoreLevel = "high" | "medium" | "low" | "unknown";
export type DiffKind = CellChange["kind"];
export interface EntityDiffChange {
  sectionId: string;
  change: CellChange;
}
export interface EntityDiff {
  kind: DiffKind;
  changes: EntityDiffChange[];
}

export function cloneDocument(document: Document): Document {
  return structuredClone(document);
}

export function mergeMaps(section: TableSection): { starts: Map<string, MergeStart>; covered: Set<string> } {
  const starts = new Map<string, MergeStart>();
  const covered = new Set<string>();
  for (const merged of section.merged_cells ?? []) {
    starts.set(`${merged.r0}:${merged.c0}`, {
      rowSpan: merged.r1 - merged.r0 + 1,
      colSpan: merged.c1 - merged.c0 + 1,
      score: merged.ocr_min_score ?? null,
    });
    for (let row = merged.r0; row <= merged.r1; row += 1) {
      for (let column = merged.c0; column <= merged.c1; column += 1) {
        if (row !== merged.r0 || column !== merged.c0) covered.add(`${row}:${column}`);
      }
    }
  }
  return { starts, covered };
}

export function cellRangeContains(range: CellBounds, row: number, column: number): boolean {
  return row >= range.r0 && row <= range.r1 && column >= range.c0 && column <= range.c1;
}

export function rangesOverlap(left: CellBounds, right: CellBounds): boolean {
  return !(left.r1 < right.r0 || right.r1 < left.r0 || left.c1 < right.c0 || right.c1 < left.c0);
}

export function findMergeAt(section: TableSection, row: number, column: number): MergedCell | null {
  return section.merged_cells.find((merged) => cellRangeContains(merged, row, column)) ?? null;
}

function sectionColumnCount(section: TableSection): number {
  return Math.max(section.x_edges.length - 1, ...section.cells.map((row) => row.length), 1);
}

export function mergeCellRange(document: Document, range: CellRange): Document {
  const section = document.sections.find((item) => item.id === range.sectionId);
  if (!section) throw new Error("找不到要合并的表格分区");
  const columns = sectionColumnCount(section);
  if (range.r0 < 0 || range.c0 < 0 || range.r1 >= section.cells.length || range.c1 >= columns || range.r0 > range.r1 || range.c0 > range.c1) {
    throw new Error("合并范围超出表格边界");
  }
  if (range.r0 === range.r1 && range.c0 === range.c1) throw new Error("请选择至少两个单元格后再合并");
  if (section.merged_cells.some((merged) => rangesOverlap(range, merged))) {
    throw new Error("合并范围与已有合并单元格重叠，请先取消原合并");
  }

  const next = cloneDocument(document);
  const target = next.sections.find((item) => item.id === range.sectionId);
  if (!target) throw new Error("找不到要合并的表格分区");
  const value = target.cells[range.r0]?.[range.c0] ?? "";
  for (let row = range.r0; row <= range.r1; row += 1) {
    for (let column = range.c0; column <= range.c1; column += 1) {
      if (row === range.r0 && column === range.c0) continue;
      if (column < target.cells[row].length) target.cells[row][column] = "";
    }
  }
  target.merged_cells.push({ r0: range.r0, r1: range.r1, c0: range.c0, c1: range.c1, value, ocr_min_score: null });
  return next;
}

export function unmergeCellAt(document: Document, sectionId: string, row: number, column: number): Document {
  const section = document.sections.find((item) => item.id === sectionId);
  if (!section || !findMergeAt(section, row, column)) throw new Error("请选择一个已合并的单元格");
  const next = cloneDocument(document);
  const target = next.sections.find((item) => item.id === sectionId);
  if (!target) throw new Error("找不到要拆分的表格分区");
  const index = target.merged_cells.findIndex((merged) => cellRangeContains(merged, row, column));
  if (index < 0) throw new Error("请选择一个已合并的单元格");
  target.merged_cells.splice(index, 1);
  return next;
}

export function buildQualityMap(document: Document): Map<string, number> {
  const quality = new Map<string, number>();
  for (const box of document.ocr_boxes ?? []) {
    const sectionIndex = Number(box.section) - 1;
    const row = Number(box.row) - 1;
    const column = Number(box.column) - 1;
    const score = Number(box.score);
    const section = document.sections[sectionIndex];
    if (!section || !Number.isInteger(sectionIndex) || !Number.isFinite(row) || !Number.isFinite(column) || !Number.isFinite(score)) continue;
    const key = `${section.id}:${row}:${column}`;
    const previous = quality.get(key);
    if (previous === undefined || score < previous) quality.set(key, score);
  }
  return quality;
}

export function buildDiffMap(compare: CompareResult | null): Map<string, string> {
  const diffMap = new Map<string, string>();
  for (const section of compare?.sections ?? []) {
    for (const change of section.changes) {
      if (section.section_id) diffMap.set(`${section.section_id}:${change.row - 1}:${change.column - 1}`, change.kind);
    }
  }
  return diffMap;
}

const diffPriority: Record<DiffKind, number> = { removed: 1, added: 2, changed: 3 };

export function findEntityDiff(compare: CompareResult | null, sourceCells: SourceCellRef[] | undefined): EntityDiff | null {
  if (!compare?.has_baseline || !sourceCells?.length) return null;
  const sourceKeys = new Set(sourceCells.map((cell) => cell.sectionId + ":" + cell.row + ":" + cell.column));
  const changes: EntityDiffChange[] = [];
  for (const section of compare.sections) {
    if (!section.section_id) continue;
    for (const change of section.changes) {
      const key = section.section_id + ":" + (change.row - 1) + ":" + (change.column - 1);
      if (sourceKeys.has(key)) changes.push({ sectionId: section.section_id, change });
    }
  }
  if (!changes.length) return null;
  const kind = changes.reduce<DiffKind>(
    (current, item) => (diffPriority[item.change.kind] > diffPriority[current] ? item.change.kind : current),
    changes[0].change.kind,
  );
  return { kind, changes };
}

export function cellDisplay(value: Scalar): string {
  return value === null || value === "" ? "" : String(value);
}

export function parseCellInput(value: string, _previous: Scalar): Scalar {
  // Recognized and manually edited cell content is always text.  Converting
  // percentages here would turn a visible "12%" into 0.12 in the preview.
  return value;
}

export function formatConfidence(score: number | null): string {
  if (score === null || !Number.isFinite(score)) return "—";
  const normalized = Math.max(0, Math.min(1, score));
  return `${(normalized * 100).toFixed(1)}%`;
}

export function scoreLevel(score: number | null): ScoreLevel {
  if (score === null || !Number.isFinite(score)) return "unknown";
  if (score >= 0.9) return "high";
  if (score >= 0.75) return "medium";
  return "low";
}
