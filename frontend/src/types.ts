// Numeric values are accepted only for legacy API payloads; normalized
// recognized cells and user edits are persisted as strings.
export type Scalar = string | number | null;

export interface Source {
  id: string;
  name: string;
  url: string;
  profile_key: string;
  enabled: boolean;
  schedule_enabled: boolean;
  schedule_interval_minutes: number;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
  latest_run: RunSummary | null;
}

export interface SourceGroup {
  id: string;
  name: string;
  schedule_enabled: boolean;
  schedule_interval_minutes: number;
  next_run_at: string | null;
  sources: Source[];
}

export interface RunBatch {
  id: string;
  kind: string;
  status: string;
  trigger_type: "manual" | "scheduled";
  auto_import_status: string;
  auto_import_message: string | null;
  import_batch_id: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface RunDatabaseImport {
  batch_id: string;
  template_type: string;
  template_name: string;
  status: string;
  origin: string;
  counts: Record<string, number>;
  target_template_ids: string[];
  replaced_template_ids: string[];
  error_message: string | null;
  issues: { entity_type: string; entity_index: number; field: string; code: string; message: string }[];
}

export interface HistoryPage<T> {
  items: T[];
  next_offset: number | null;
}

export interface DatabaseImportHistoryItem {
  batch_id: string;
  run_id: string;
  source_runs: { run_id: string; source_id: string; source_name: string }[];
  template_type: string;
  template_name: string;
  status: string;
  origin: string;
  counts: Record<string, number>;
  target_template_ids: string[];
  replaced_template_ids: string[];
  error_message: string | null;
  created_at: string;
  committed_at: string | null;
  issues: { entity_type: string; entity_index: number; field: string; code: string; message: string }[];
}

export interface RunBatchHistoryRun {
  id: string;
  source_id: string;
  source_name: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  error_message: string | null;
  recognition_skipped: boolean;
  created_at: string;
  finished_at: string | null;
}

export interface RunBatchHistoryItem {
  id: string;
  kind: string;
  status: string;
  trigger_type: "manual" | "scheduled";
  auto_import_status: string;
  auto_import_message: string | null;
  import_batch_id: string | null;
  created_at: string;
  finished_at: string | null;
  runs: RunBatchHistoryRun[];
}

export interface RunSummary {
  id: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  created_at: string;
  finished_at: string | null;
  recognition_skipped: boolean;
  comparison_summary: RunComparisonSummary | null;
}

export interface Candidate {
  id: string;
  source_url: string;
  resolved_url: string;
  ordinal: number;
  alt: string;
  width: number | null;
  height: number | null;
  selected: boolean;
  downloaded: boolean;
  sha256: string | null;
  mime_type: string | null;
}

export interface Artifact {
  id: string;
  kind: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  download_url: string;
  revision_id: string | null;
}

export interface Revision {
  id: string;
  revision_number: number;
  base_document_sha256: string;
  document_sha256: string;
  changed_cell_count: number;
  created_at: string;
}

export interface Run extends RunSummary {
  source_id: string;
  source_name: string;
  requested_url: string;
  final_url: string | null;
  profile_key: string;
  baseline_run_id: string | null;
  run_batch_id: string | null;
  trigger_type: "manual" | "scheduled";
  run_batch: RunBatch | null;
  database_imports: RunDatabaseImport[];
  error_code: string | null;
  error_message: string | null;
  attempt: number;
  started_at: string | null;
  candidates: Candidate[];
  artifacts: Artifact[];
  latest_revision: Revision | null;
}

export interface MergedCell {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
  value: Scalar;
  ocr_min_score?: number | null;
}

export interface TableSection {
  id: string;
  label: string;
  bbox: number[];
  x_edges: number[];
  y_edges: number[];
  cells: Scalar[][];
  merged_cells: MergedCell[];
  ocr_count: number;
  ocr_avg_score: number | null;
  ocr_low_score_count: number;
  strategy: string;
  [key: string]: unknown;
}

export interface SourceCellRef {
  sectionId: string;
  row: number;
  column: number;
}

export interface Document {
  version: number;
  source: Record<string, unknown>;
  title: string;
  bands: Record<string, unknown>[];
  sections: TableSection[];
  colored_notes: Record<string, unknown>[];
  footer_notes: Record<string, unknown>[];
  ocr_boxes: Record<string, unknown>[];
  corrections: Record<string, unknown>[];
  metrics: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DocumentResponse {
  run_id: string;
  view: "recognized" | "revised";
  recognized_document_sha256: string;
  document_sha256: string;
  revision: Revision | null;
  document: Document;
  raw_artifact: Artifact;
}

export interface ComparisonSummary {
  changed_cells: number;
  added_cells: number;
  removed_cells: number;
  added_sections: number;
  removed_sections: number;
  merge_changes: number;
  dimension_changes: number;
}

export interface RunComparisonSummary extends ComparisonSummary {
  has_baseline: boolean;
  has_changes: boolean;
}

export interface CellChange {
  row: number;
  column: number;
  kind: "changed" | "added" | "removed";
  before: Scalar;
  after: Scalar;
}

export interface DiffSection {
  kind: "changed" | "added" | "removed";
  section_id: string | null;
  baseline_section_id: string | null;
  label: string;
  before_dimensions: [number, number] | null;
  after_dimensions: [number, number] | null;
  changes: CellChange[];
  structure_changes: string[];
}

export interface CompareResult {
  run_id: string;
  baseline: { run_id: string; finished_at: string | null } | null;
  has_baseline: boolean;
  has_changes: boolean;
  summary: ComparisonSummary;
  sections: DiffSection[];
}
