import type { CompareResult, Document, Scalar, TableSection } from "./types";

export type MergeStart = { rowSpan: number; colSpan: number; score: number | null };

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

export function cellDisplay(value: Scalar): string {
  return value === null || value === "" ? "" : String(value);
}

export function parseCellInput(value: string, previous: Scalar): Scalar {
  if (value === "") return "";
  if (/^-?\d+(\.\d+)?%$/.test(value)) return Number(value.slice(0, -1)) / 100;
  if (typeof previous === "number" && /^-?\d+(\.\d+)?$/.test(value)) return Number(value);
  return value;
}

export function formatConfidence(score: number | null): string {
  if (score === null || !Number.isFinite(score)) return "—";
  const normalized = Math.max(0, Math.min(1, score));
  return `${(normalized * 100).toFixed(1)}%`;
}
