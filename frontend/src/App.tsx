import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, type DatabaseImportTemplateType, type ExportFormat } from "./api";
import { EXCEPTION_TRADE_HEADERS, extractExceptionTradeTable, isExceptionMonitoringDocument, type ExceptionTradeRow } from "./exceptionTradeModel";
import { POSITION_LIMIT_HEADERS, extractPositionLimitTable, isPositionLimitDocument, type PositionLimitRow } from "./positionLimitModel";
import { buildDiffMap, buildQualityMap, cellDisplay, cellRangeContains, cloneDocument, findEntityDiff, findMergeAt, formatConfidence, mergeCellRange, mergeMaps, parseCellInput, rangesOverlap, scoreLevel, unmergeCellAt, type CellRange, type EntityDiff } from "./tableModel";
import type { CompareResult, Document, Run, Scalar, Source, TableSection } from "./types";

type View = "sources" | "runs";
type TablePresentation = "ocr" | "entity";
type Notice = { kind: "error" | "success"; text: string } | null;
type ConfidenceCounts = { high: number; medium: number; low: number; unknown: number };
type DocumentStats = { sections: number; cells: number; confidence: ConfidenceCounts };

const activeStatuses = new Set(["queued", "crawling", "downloading", "extracting", "exporting", "awaiting_image_selection"]);

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function AutoResizeTextarea({ value, ariaLabel, onChange }: { value: string; ariaLabel: string; onChange: (value: string) => void }) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const resize = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxHeight = Number.parseFloat(window.getComputedStyle(textarea).maxHeight);
    const availableHeight = Number.isFinite(maxHeight) ? maxHeight : Number.POSITIVE_INFINITY;
    textarea.style.height = `${Math.min(textarea.scrollHeight, availableHeight)}px`;
    textarea.style.overflowY = textarea.scrollHeight > availableHeight ? "auto" : "hidden";
  }, []);

  useLayoutEffect(() => {
    resize();
  }, [resize, value]);

  return <textarea ref={textareaRef} aria-label={ariaLabel} value={value} onInput={resize} onChange={(event) => onChange(event.target.value)} />;
}

function statusText(status: string): string {
  const labels: Record<string, string> = {
    queued: "排队中",
    crawling: "抓取中",
    downloading: "下载图片",
    extracting: "识别中",
    exporting: "生成文件",
    awaiting_image_selection: "待选图片",
    succeeded: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function comparisonCount(summary: Run["comparison_summary"]): number {
  if (!summary) return 0;
  return summary.changed_cells + summary.added_cells + summary.removed_cells + summary.added_sections + summary.removed_sections + summary.merge_changes + summary.dimension_changes;
}

function diffLabel(kind: EntityDiff["kind"]): string {
  return kind === "changed" ? "修改" : kind === "added" ? "新增" : "删除";
}

function entityDiffTitle(diff: EntityDiff | null): string | undefined {
  if (!diff) return undefined;
  const details = diff.changes.map(({ sectionId, change }) => {
    const before = cellDisplay(change.before);
    const after = cellDisplay(change.after);
    const value = change.kind === "changed"
      ? before + " → " + after
      : change.kind === "added"
        ? "新增「" + after + "」"
        : "删除「" + before + "」";
    return diffLabel(change.kind) + "（" + sectionId + " 第" + change.row + "行第" + change.column + "列）：" + value;
  });
  return details.join("；");
}

function EntityDiffMarker({ diff }: { diff: EntityDiff | null }) {
  if (!diff) return null;
  return <span className={"entity-diff-marker " + diff.kind}>{diffLabel(diff.kind)}</span>;
}

function EntityDiffSummary({ compare }: { compare: CompareResult | null }) {
  if (!compare || !compare.has_baseline) {
    return <div className="entity-diff-summary no-baseline"><strong>暂无历史基线</strong><span>这是该网址第一次成功抓取，下一次运行后会显示实体表差异。</span></div>;
  }
  const { summary } = compare;
  return <div className={"entity-diff-summary " + (compare.has_changes ? "has-changes" : "no-changes")}>
    <div className="entity-diff-summary-main"><strong>{compare.has_changes ? "相对上次抓取有变化" : "相对上次抓取无变化"}</strong><span>基线运行于 {formatTime(compare.baseline?.finished_at)}</span></div>
    <div className="entity-diff-counts"><span className="changed"><strong>{summary.changed_cells}</strong> 修改</span><span className="added"><strong>{summary.added_cells}</strong> 新增</span><span className="removed"><strong>{summary.removed_cells}</strong> 删除</span><span><strong>{summary.merge_changes + summary.dimension_changes}</strong> 结构</span></div>
    {compare.has_changes && <div className="entity-diff-legend"><span><i className="entity-diff-swatch changed" />修改</span><span><i className="entity-diff-swatch added" />新增</span><span><i className="entity-diff-swatch removed" />删除</span>{summary.removed_cells > 0 && <small>删除内容不一定生成当前实体行，必要时可展开原始识别表核对。</small>}</div>}
  </div>;
}

function documentStats(document: Document | null): DocumentStats {
  if (!document) return { sections: 0, cells: 0, confidence: { high: 0, medium: 0, low: 0, unknown: 0 } };
  const confidence: ConfidenceCounts = { high: 0, medium: 0, low: 0, unknown: 0 };
  for (const box of document.ocr_boxes ?? []) {
    const rawScore = box.score;
    const score = typeof rawScore === "number" ? rawScore : typeof rawScore === "string" && rawScore.trim() ? Number(rawScore) : null;
    confidence[scoreLevel(score)] += 1;
  }
  return {
    sections: document.sections.length,
    cells: document.sections.reduce((total, section) => total + section.cells.flat().filter((value) => value !== "" && value !== null).length, 0),
    confidence,
  };
}

function App() {
  const [view, setView] = useState<View>("sources");
  const [sources, setSources] = useState<Source[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [document, setDocument] = useState<Document | null>(null);
  const [savedDocument, setSavedDocument] = useState<Document | null>(null);
  const [recognizedHash, setRecognizedHash] = useState("");
  const [documentHash, setDocumentHash] = useState("");
  const [revisionId, setRevisionId] = useState<string | undefined>();
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedRange, setSelectedRange] = useState<CellRange | null>(null);
  const [tablePresentation, setTablePresentation] = useState<TablePresentation>("ocr");
  const [databaseImportLoading, setDatabaseImportLoading] = useState(false);

  const refreshSources = useCallback(async () => setSources(await api.sources()), []);
  const refreshRuns = useCallback(async () => setRuns(await api.runs(sourceFilter || undefined, statusFilter || undefined)), [sourceFilter, statusFilter]);

  const loadRun = useCallback(async (runId: string) => {
    setSelectedRange(null);
    setTablePresentation("ocr");
    const run = await api.run(runId);
    setSelectedRun(run);
    setSelectedRunId(runId);
    if (run.status === "succeeded") {
      const [documentResponse, comparison] = await Promise.all([api.document(runId, "revised"), api.compare(runId)]);
      setDocument(documentResponse.document);
      setSavedDocument(cloneDocument(documentResponse.document));
      setRecognizedHash(documentResponse.recognized_document_sha256);
      setDocumentHash(documentResponse.document_sha256);
      setRevisionId(documentResponse.revision?.id);
      setCompare(comparison);
    } else {
      setDocument(null);
      setSavedDocument(null);
      setCompare(null);
      setRevisionId(undefined);
      setRecognizedHash("");
      setDocumentHash("");
    }
  }, []);

  useEffect(() => {
    void Promise.all([refreshSources(), refreshRuns()]).catch((error: Error) => setNotice({ kind: "error", text: error.message }));
  }, [refreshRuns, refreshSources]);

  useEffect(() => {
    if (!selectedRunId || !selectedRun || !activeStatuses.has(selectedRun.status)) return;
    const timer = window.setInterval(() => {
      void Promise.all([loadRun(selectedRunId), refreshRuns(), refreshSources()]).catch((error: Error) => setNotice({ kind: "error", text: error.message }));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [loadRun, refreshRuns, refreshSources, selectedRun, selectedRunId]);

  async function addSource(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.createSource({ url: newUrl, name: newName || undefined });
      setNewUrl("");
      setNewName("");
      await refreshSources();
      setNotice({ kind: "success", text: "网址已添加" });
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function runSource(source: Source) {
    try {
      const run = await api.createRun(source.id);
      await Promise.all([refreshRuns(), loadRun(run.id)]);
      setView("runs");
      setNotice({ kind: "success", text: "任务已加入队列" });
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function toggleSource(source: Source) {
    try {
      await api.updateSource(source.id, { enabled: !source.enabled });
      await refreshSources();
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function updateSchedule(source: Source, patch: Partial<Pick<Source, "schedule_enabled" | "schedule_interval_minutes">>) {
    try {
      await api.updateSource(source.id, patch);
      await refreshSources();
      setNotice({ kind: "success", text: patch.schedule_enabled === false ? "已停用定时抓取" : "定时抓取设置已保存" });
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function selectImage(candidateId: string) {
    if (!selectedRunId) return;
    try {
      await api.selectImage(selectedRunId, candidateId);
      await loadRun(selectedRunId);
      await refreshRuns();
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function saveRevision() {
    if (!selectedRunId || !document) return;
    try {
      const revision = await api.saveRevision(selectedRunId, { base_document_sha256: recognizedHash, document });
      setRevisionId(revision.id);
      await Promise.all([loadRun(selectedRunId), refreshRuns()]);
      setNotice({ kind: "success", text: "修订已保存" });
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function exportRun(format: ExportFormat) {
    if (!selectedRunId) return;
    try {
      const result = await api.exportRun(selectedRunId, revisionId, format);
      for (const artifact of result.artifacts) window.open(artifact.download_url, "_blank", "noopener,noreferrer");
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  async function importDatabase() {
    if (!selectedRunId || !document || !documentHash) return;
    if (isDirty) {
      setNotice({ kind: "error", text: "当前有未保存修订，请先保存修订后再写入数据库" });
      return;
    }
    const positionTable = isPositionLimitDocument(document) ? extractPositionLimitTable(document) : null;
    const exceptionTable = !positionTable && isExceptionMonitoringDocument(document) ? extractExceptionTradeTable(document) : null;
    if (!positionTable && !exceptionTable) {
      setNotice({ kind: "error", text: "当前文档不是可导入的期权限仓或开仓总量实体表" });
      return;
    }

    const templateType: DatabaseImportTemplateType = positionTable ? "TEMP_POSITIONLIMIT_DETAIL" : "TEMP_OPENTOTALLIMIT";
    setDatabaseImportLoading(true);
    try {
      const preflight = await api.preflightDatabaseImport(selectedRunId, {
        view: revisionId ? "revised" : "recognized",
        documentSha256: documentHash,
        templateType,
        positionRows: positionTable?.rows,
        exceptionRows: exceptionTable?.rows,
        unmappedCells: positionTable?.unmappedCells,
        unmappedLimitCells: exceptionTable?.unmappedLimitCells,
      });
      if (preflight.status !== "preflight_succeeded") {
        const firstIssues = preflight.issues.slice(0, 3).map((issue) => {
          const rowLabel = issue.entity_index >= 0 ? `第${issue.entity_index + 1}行` : "批次";
          const sourceLabel = issue.source_cells.length ? `（来源 ${issue.source_cells[0].sectionId}[${issue.source_cells[0].row},${issue.source_cells[0].column}]）` : "";
          return `${rowLabel} ${issue.field}：${issue.message}${sourceLabel}`;
        }).join("；");
        setNotice({ kind: "error", text: `预校验未通过（${preflight.issues.length}项）：${firstIssues || "请查看后端审计详情"}` });
        return;
      }

      const totalRows = preflight.counts.total_rows ?? 0;
      const targetName = templateType === "TEMP_POSITIONLIMIT_DETAIL" ? "期权限仓" : "开仓总量限制";
      if (!window.confirm(`预校验通过，将创建 Oracle 草稿模板“${preflight.template_name}”，类型：${targetName}，写入 ${totalRows} 条明细。确认提交吗？`)) {
        setNotice({ kind: "success", text: "预校验已通过，已取消本次提交；可再次点击写入数据库继续提交" });
        return;
      }
      const committed = await api.commitDatabaseImport(preflight.batch_id);
      setNotice({ kind: "success", text: `数据库写入成功：模板 ${committed.target_template_ids[0] ?? "已创建"}，写入 ${committed.counts.total_rows ?? totalRows} 条明细` });
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    } finally {
      setDatabaseImportLoading(false);
    }
  }

  function updateCell(sectionId: string, row: number, column: number, value: string) {
    setDocument((current) => {
      if (!current) return current;
      const next = cloneDocument(current);
      const section = next.sections.find((item) => item.id === sectionId);
      if (!section) return current;
      while (section.cells.length <= row) section.cells.push([]);
      while (section.cells[row].length <= column) section.cells[row].push("");
      const previous = section.cells[row][column];
      const typed: Scalar = parseCellInput(value, previous);
      section.cells[row][column] = typed;
      for (const merged of section.merged_cells) {
        if (merged.r0 === row && merged.c0 === column) merged.value = typed;
      }
      return next;
    });
  }

  function selectCell(sectionId: string, row: number, column: number, extend: boolean) {
    setSelectedRange((current) => {
      if (!extend || !current || current.sectionId !== sectionId) return { sectionId, r0: row, r1: row, c0: column, c1: column };
      return {
        sectionId,
        r0: Math.min(current.r0, row),
        r1: Math.max(current.r1, row),
        c0: Math.min(current.c0, column),
        c1: Math.max(current.c1, column),
      };
    });
  }

  function mergeSelectedCells() {
    if (!document || !selectedRange) return;
    const section = document.sections.find((item) => item.id === selectedRange.sectionId);
    if (!section) return;
    const discardedValues = [];
    for (let row = selectedRange.r0; row <= selectedRange.r1; row += 1) {
      for (let column = selectedRange.c0; column <= selectedRange.c1; column += 1) {
        if (row === selectedRange.r0 && column === selectedRange.c0) continue;
        const value = section.cells[row]?.[column];
        if (value !== null && value !== undefined && value !== "") discardedValues.push(String(value));
      }
    }
    if (discardedValues.length && !window.confirm(`合并后只保留左上角单元格内容，其余 ${discardedValues.length} 个单元格内容将被清空。继续吗？`)) return;
    try {
      setDocument(mergeCellRange(document, selectedRange));
      setSelectedRange(null);
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  function unmergeSelectedCell() {
    if (!document || !selectedRange) return;
    if (selectedRange.r0 !== selectedRange.r1 || selectedRange.c0 !== selectedRange.c1) {
      setNotice({ kind: "error", text: "取消合并时请只选择一个已合并的单元格" });
      return;
    }
    try {
      setDocument(unmergeCellAt(document, selectedRange.sectionId, selectedRange.r0, selectedRange.c0));
      setSelectedRange(null);
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
    }
  }

  const stats = useMemo(() => documentStats(document), [document]);
  const isDirty = useMemo(
    () => Boolean(document && savedDocument && JSON.stringify(document) !== JSON.stringify(savedDocument)),
    [document, savedDocument],
  );

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">IMAGE TABLE WORKSPACE</p>
          <h1>网址图片转表格</h1>
          <p className="subtitle">抓取网页图片，重建为可审阅、可修订、可对比的数据表。</p>
        </div>
        <nav className="nav-tabs" aria-label="主导航">
          <button className={view === "sources" ? "active" : ""} onClick={() => setView("sources")}>来源管理</button>
          <button className={view === "runs" ? "active" : ""} onClick={() => setView("runs")}>运行历史 <span>{runs.length}</span></button>
        </nav>
      </header>

      {notice && <div className={`notice ${notice.kind}`}>{notice.text}<button onClick={() => setNotice(null)}>×</button></div>}

      <main className="content-grid">
        <section className="main-column">
          {view === "sources" ? (
            <>
              <section className="panel intro-panel">
                <div><p className="eyebrow">SOURCES</p><h2>页面来源</h2><p>所有来源使用同一个正文图片位置配置。每次运行都会留下独立历史。</p></div>
                <form className="source-form" onSubmit={addSource}>
                  <input required type="url" placeholder="https://example.com/page" value={newUrl} onChange={(event) => setNewUrl(event.target.value)} />
                  <input placeholder="来源名称（可选）" value={newName} onChange={(event) => setNewName(event.target.value)} />
                  <button className="primary" disabled={loading}>{loading ? "添加中…" : "添加网址"}</button>
                </form>
              </section>
              <section className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SOURCE LIST</p><h2>已添加网址</h2></div><button className="quiet" onClick={() => void refreshSources()}>刷新</button></div>
              <SourceTable sources={sources} onRun={runSource} onToggle={toggleSource} onSchedule={updateSchedule} />
              </section>
            </>
          ) : (
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">RUN HISTORY</p><h2>运行历史</h2></div><div className="panel-actions"><div className="filter-row"><select aria-label="按来源筛选" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">全部来源</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select><select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">全部状态</option><option value="queued">排队中</option><option value="crawling">抓取中</option><option value="awaiting_image_selection">待选图片</option><option value="extracting">识别中</option><option value="exporting">生成文件</option><option value="succeeded">已完成</option><option value="failed">失败</option></select><button className="quiet" onClick={() => void refreshRuns()}>刷新</button></div></div></div>
              <RunTable runs={runs} selectedRunId={selectedRunId} onSelect={(id) => void loadRun(id)} />
            </section>
          )}
        </section>

        <aside className="detail-column">
          <RunDetail run={selectedRun} document={document} compare={compare} stats={stats} dirty={isDirty} databaseImportLoading={databaseImportLoading} selectedRange={selectedRange} tablePresentation={tablePresentation} onTablePresentationChange={setTablePresentation} onSelectImage={selectImage} onChangeCell={updateCell} onSelectCell={selectCell} onMerge={mergeSelectedCells} onUnmerge={unmergeSelectedCell} onSave={saveRevision} onExport={exportRun} onDatabaseImport={importDatabase} />
        </aside>
      </main>
    </div>
  );
}

function SourceTable({ sources, onRun, onToggle, onSchedule }: { sources: Source[]; onRun: (source: Source) => void; onToggle: (source: Source) => void; onSchedule: (source: Source, patch: Partial<Pick<Source, "schedule_enabled" | "schedule_interval_minutes">>) => void }) {
  if (!sources.length) return <div className="empty-state">还没有来源，先添加一个网址。</div>;
  return <div className="table-scroll"><table className="list-table"><thead><tr><th>名称</th><th>网址</th><th>状态</th><th>定时抓取</th><th>最近运行</th><th /></tr></thead><tbody>{sources.map((source) => <tr key={source.id}><td className="strong">{source.name}</td><td className="url-cell" title={source.url}>{source.url}</td><td><span className={`status-dot ${source.enabled ? "on" : "off"}`}>{source.enabled ? "启用" : "停用"}</span></td><td><ScheduleEditor source={source} onChange={(patch) => onSchedule(source, patch)} /></td><td>{source.latest_run ? <><span className={`status-badge ${source.latest_run.status}`}>{statusText(source.latest_run.status)}</span><small className="table-time">{formatTime(source.latest_run.finished_at || source.latest_run.created_at)}</small></> : "暂无"}</td><td className="actions"><button className="quiet" disabled={!source.enabled} onClick={() => onRun(source)}>立即运行</button><button className="quiet" onClick={() => onToggle(source)}>{source.enabled ? "停用" : "启用"}</button></td></tr>)}</tbody></table></div>;
}

function ScheduleEditor({ source, onChange }: { source: Source; onChange: (patch: Partial<Pick<Source, "schedule_enabled" | "schedule_interval_minutes">>) => void }) {
  const [interval, setInterval] = useState(String(source.schedule_interval_minutes || 60));

  useEffect(() => {
    setInterval(String(source.schedule_interval_minutes || 60));
  }, [source.schedule_interval_minutes]);

  function saveInterval() {
    const value = Number.parseInt(interval, 10);
    if (!Number.isInteger(value) || value < 1 || value > 43_200) {
      setInterval(String(source.schedule_interval_minutes || 60));
      return;
    }
    if (value !== source.schedule_interval_minutes) onChange({ schedule_interval_minutes: value });
  }

  return <div className="schedule-editor"><label><input type="checkbox" checked={source.schedule_enabled} onChange={(event) => onChange({ schedule_enabled: event.target.checked })} /> 自动</label><div className="schedule-interval"><input aria-label={`${source.name} 定时间隔（分钟）`} type="number" min="1" max="43200" value={interval} onChange={(event) => setInterval(event.target.value)} onBlur={saveInterval} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }} /><span>分钟</span></div><small>{source.schedule_enabled ? `下次 ${formatTime(source.next_run_at)}` : "未启用"}</small></div>;
}

interface RunHistoryGroup {
  name: string;
  runs: Run[];
}

function groupRunsByName(runs: Run[]): RunHistoryGroup[] {
  const groups = new Map<string, RunHistoryGroup>();
  for (const run of runs) {
    const name = run.source_name || run.requested_url;
    const group = groups.get(name);
    if (group) group.runs.push(run);
    else groups.set(name, { name, runs: [run] });
  }
  return [...groups.values()].map((group) => ({
    ...group,
    runs: [...group.runs].sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
  }));
}

function RunTable({ runs, selectedRunId, onSelect }: { runs: Run[]; selectedRunId: string | null; onSelect: (id: string) => void }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const groups = useMemo(() => groupRunsByName(runs), [runs]);

  if (!runs.length) return <div className="empty-state">还没有运行记录。</div>;
  function toggleGroup(name: string) {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function runSummary(run: Run) {
    return run.comparison_summary?.has_baseline
      ? (run.comparison_summary.has_changes ? `${comparisonCount(run.comparison_summary)} 项` : "无变化")
      : "首次";
  }

  return <div className="table-scroll"><table className="list-table run-history-table"><thead><tr><th>状态</th><th>名称</th><th>进度</th><th>最近运行</th><th>变化</th><th>操作</th></tr></thead><tbody>{groups.map((group) => {
    const latest = group.runs[0];
    const expanded = expandedGroups.has(group.name);
    return <Fragment key={group.name}>
      <tr className={`run-group-row ${latest.id === selectedRunId ? "selected-row" : ""}`} onClick={() => onSelect(latest.id)}>
        <td><span className={`status-badge ${latest.status}`}>{statusText(latest.status)}</span></td>
        <td className="strong" title={latest.requested_url}><span>{group.name}</span><small className="run-count">{group.runs.length} 次运行</small></td>
        <td><div className="progress-cell"><div className="progress-track"><span style={{ width: `${latest.progress}%` }} /></div><small>{latest.progress}%</small></div></td>
        <td>{formatTime(latest.created_at)}</td>
        <td>{runSummary(latest)}</td>
        <td className="actions"><button type="button" className="quiet" aria-expanded={expanded} onClick={(event) => { event.stopPropagation(); toggleGroup(group.name); }}>{expanded ? "收起历史" : "查看历史"}</button></td>
      </tr>
      {expanded && group.runs.map((run) => <tr className={`run-history-row ${run.id === selectedRunId ? "selected-row" : ""}`} key={run.id} onClick={() => onSelect(run.id)}>
        <td><span className={`status-badge ${run.status}`}>{statusText(run.status)}</span></td>
        <td className="run-history-name"><span>↳ {group.name}</span><small>{run.id === latest.id ? "最新记录" : "历史记录"}</small></td>
        <td><div className="progress-cell"><div className="progress-track"><span style={{ width: `${run.progress}%` }} /></div><small>{run.progress}%</small></div></td>
        <td>{formatTime(run.created_at)}</td>
        <td>{runSummary(run)}</td>
        <td />
      </tr>)}
    </Fragment>;
  })}</tbody></table></div>;
}

function RunDetail({ run, document, compare, stats, dirty, databaseImportLoading, selectedRange, tablePresentation, onTablePresentationChange, onSelectImage, onChangeCell, onSelectCell, onMerge, onUnmerge, onSave, onExport, onDatabaseImport }: { run: Run | null; document: Document | null; compare: CompareResult | null; stats: DocumentStats; dirty: boolean; databaseImportLoading: boolean; selectedRange: CellRange | null; tablePresentation: TablePresentation; onTablePresentationChange: (presentation: TablePresentation) => void; onSelectImage: (candidateId: string) => void; onChangeCell: (sectionId: string, row: number, column: number, value: string) => void; onSelectCell: (sectionId: string, row: number, column: number, extend: boolean) => void; onMerge: () => void; onUnmerge: () => void; onSave: () => void; onExport: (format: ExportFormat) => void; onDatabaseImport: () => void }) {
  if (!run) return <section className="panel detail-empty"><div className="empty-illustration">↗</div><h2>选择一次运行</h2><p>从来源页或运行历史中选择记录，这里会显示任务进度、数据表和历史差异。</p></section>;
  const supportsEntityPresentation = Boolean(document && (isPositionLimitDocument(document) || isExceptionMonitoringDocument(document)));
  const showingEntityPresentation = tablePresentation === "entity" && supportsEntityPresentation;
  return <>
    <section className="panel run-card"><div className="run-card-top"><div><p className="eyebrow">RUN DETAIL</p><h2>{run.status === "succeeded" ? (document?.title || "识别结果") : statusText(run.status)}</h2><p className="muted">{formatTime(run.created_at)} · {run.requested_url}</p></div><span className={`status-badge large ${run.status}`}>{statusText(run.status)}</span></div><div className="progress-track large"><span style={{ width: `${run.progress}%` }} /></div><div className="run-message">{run.message}{run.error_message && <span className="error-text">：{run.error_message}</span>}</div>{run.status === "succeeded" && <><div className="stat-row"><Stat label="分区" value={stats.sections} /><Stat label="非空单元格" value={stats.cells} /></div><div className="stat-row confidence-stats" aria-label="不同颜色的识别分数数量"><Stat tone="high" label="高分框" value={stats.confidence.high} /><Stat tone="medium" label="中分框" value={stats.confidence.medium} /><Stat tone="low" label="低分框" value={stats.confidence.low} /><Stat tone="unknown" label="未提供" value={stats.confidence.unknown} /></div></>}{run.status === "succeeded" && <SelectedImageInfo run={run} />}</section>
    {run.status === "awaiting_image_selection" && <CandidatePicker candidates={run.candidates} onSelect={onSelectImage} />}
    {run.status === "succeeded" && document && <>
      {(!showingEntityPresentation || !supportsEntityPresentation) && <ComparisonPanel compare={compare} />}
      <section className={`panel data-panel ${showingEntityPresentation ? "entity-data-panel" : ""}`}><div className="panel-heading"><div><p className="eyebrow">DATA PANEL</p><h2>{showingEntityPresentation ? "实体整理表" : "OCR 识别结果"} {dirty && <span className="unsaved-badge">有未保存修改</span>}</h2><p className="muted">{showingEntityPresentation ? "当前展示由 OCR 结果整理出的业务实体表；如需修订识别文本，请切回 OCR 结果。" : "默认展示 OCR 原始识别结果，可修改单元格值并核对合并关系。整理为实体表后，原始 OCR 结果仍可切回查看。"}</p></div><div className="button-row">{supportsEntityPresentation && <button type="button" className={showingEntityPresentation ? "quiet" : "primary"} onClick={() => onTablePresentationChange(showingEntityPresentation ? "ocr" : "entity")}>{showingEntityPresentation ? "查看 OCR 结果" : "整理为实体表"}</button>}{supportsEntityPresentation && <button type="button" className="primary" disabled={!showingEntityPresentation || dirty || databaseImportLoading} title={dirty ? "请先保存修订" : undefined} onClick={onDatabaseImport}>{databaseImportLoading ? "预校验中…" : "写入数据库"}</button>}<button type="button" className={dirty ? "primary" : "quiet"} onClick={onSave}>保存修订</button><button type="button" className="primary" onClick={() => void onExport("json")}>导出 JSON</button><button type="button" className="primary" onClick={() => void onExport("xlsx")}>导出 XLSX</button></div></div><div className="data-workspace"><OriginalImageViewer run={run} /><div className={`document-results-scroll ${showingEntityPresentation ? "entity-results-scroll" : ""}`}><DocumentTables tablePresentation={showingEntityPresentation ? "entity" : "ocr"} document={document} compare={compare} selectedRange={selectedRange} onChangeCell={onChangeCell} onSelectCell={onSelectCell} onMerge={onMerge} onUnmerge={onUnmerge} /></div></div></section>
      <Artifacts run={run} />
    </>}
  </>;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: keyof ConfidenceCounts }) { return <div className={`stat ${tone ?? ""}`}><strong>{value}</strong><span>{label}</span></div>; }

function SelectedImageInfo({ run }: { run: Run }) {
  const candidate = run.candidates.find((item) => item.selected);
  if (!candidate) return null;
  const dimensions = candidate.width && candidate.height ? `${candidate.width} × ${candidate.height}` : "尺寸未知";
  return <div className="image-info">原图：{dimensions}{candidate.mime_type && <span> · {candidate.mime_type}</span>}{candidate.sha256 && <span> · SHA-256 {candidate.sha256.slice(0, 16)}…</span>}{run.recognition_skipped && <span> · 本次 SHA 未变化，已跳过识别</span>}</div>;
}

function OriginalImageViewer({ run }: { run: Run }) {
  const artifact = run.artifacts.find((item) => item.kind === "source_image");
  return <section className="original-image-viewer"><div className="original-image-heading"><div><p className="eyebrow">SOURCE IMAGE</p><h3>原图核对</h3></div>{artifact && <a href={artifact.download_url} target="_blank" rel="noreferrer">打开原图</a>}</div>{artifact ? <div className="original-image-scroll"><img src={artifact.download_url} alt="本次运行下载的原始表格图片" /></div> : <div className="image-empty">暂无原图产物</div>}{artifact && <small className="original-image-meta">{artifact.filename}</small>}</section>;
}

function CandidatePicker({ candidates, onSelect }: { candidates: Run["candidates"]; onSelect: (id: string) => void }) { return <section className="panel candidate-panel"><p className="eyebrow">IMAGE CANDIDATES</p><h2>请选择正文图片</h2><p className="muted">页面发现多张图片。选择正确的表格图片后才会开始识别。</p><div className="candidate-list">{candidates.map((candidate) => <button className="candidate" key={candidate.id} onClick={() => onSelect(candidate.id)}><span className="candidate-number">{candidate.ordinal + 1}</span><span><strong>{candidate.width && candidate.height ? `${candidate.width} × ${candidate.height}` : "尺寸未知"}</strong><small>{candidate.alt || candidate.resolved_url}</small></span></button>)}</div></section>; }

function ComparisonPanel({ compare }: { compare: CompareResult | null }) { if (!compare || !compare.has_baseline) return <section className="panel comparison-panel"><div><p className="eyebrow">COMPARISON</p><h2>暂无历史基线</h2><p className="muted">这是该网址第一次成功识别，下一次运行后会显示差异。</p></div></section>; const { summary } = compare; return <section className={`panel comparison-panel ${compare.has_changes ? "has-changes" : "no-changes"}`}><div><p className="eyebrow">COMPARISON</p><h2>{compare.has_changes ? "发现历史变化" : "与上次相同"}</h2><p className="muted">基线运行于 {formatTime(compare.baseline?.finished_at)}。</p></div><div className="change-summary"><span><strong>{summary.changed_cells}</strong> 修改</span><span><strong>{summary.added_cells}</strong> 新增</span><span><strong>{summary.removed_cells}</strong> 删除</span><span><strong>{summary.merge_changes + summary.dimension_changes}</strong> 结构</span></div>{compare.has_changes && <div className="removed-list">{compare.sections.flatMap((section) => section.changes.filter((change) => change.kind === "removed").map((change) => <span key={`${section.section_id ?? section.baseline_section_id}-${change.row}-${change.column}`}>{section.label || section.section_id || section.baseline_section_id} · 第 {change.row} 行第 {change.column} 列：{cellDisplay(change.before)}</span>))}</div>}</section>; }

function DocumentTables({ tablePresentation, document, compare, selectedRange, onChangeCell, onSelectCell, onMerge, onUnmerge }: { tablePresentation: TablePresentation; document: Document; compare: CompareResult | null; selectedRange: CellRange | null; onChangeCell: (sectionId: string, row: number, column: number, value: string) => void; onSelectCell: (sectionId: string, row: number, column: number, extend: boolean) => void; onMerge: () => void; onUnmerge: () => void }) {
  const diffMap = tablePresentation === "ocr" ? buildDiffMap(compare) : new Map<string, string>();
  const qualityMap = buildQualityMap(document);
  const isPositionLimit = isPositionLimitDocument(document);
  const positionLimitTable = isPositionLimit ? extractPositionLimitTable(document) : null;
  const isException = isExceptionMonitoringDocument(document);
  const exceptionTable = isException ? extractExceptionTradeTable(document) : null;
  const rawTables = <><ConfidenceGuide />{document.sections.map((section) => <TableSectionView key={section.id} section={section} diffMap={diffMap} qualityMap={qualityMap} selectedRange={selectedRange} onChangeCell={onChangeCell} onSelectCell={onSelectCell} onMerge={onMerge} onUnmerge={onUnmerge} />)}</>;
  const entityTable = positionLimitTable ? <><PositionLimitTable table={positionLimitTable} compare={compare} /><details className="raw-document-details"><summary>查看/修订原始识别表格</summary><div className="raw-document-tables">{rawTables}</div></details></> : exceptionTable ? <><ExceptionTradeTable table={exceptionTable} compare={compare} /><details className="raw-document-details"><summary>查看/修订原始识别表格</summary><div className="raw-document-tables">{rawTables}</div></details></> : rawTables;
  const displayedTable = tablePresentation === "entity" && (positionLimitTable || exceptionTable) ? entityTable : rawTables;
  return <div className="document-tables">{displayedTable}{document.footer_notes?.length > 0 && <div className="notes-block"><strong>页脚说明</strong>{document.footer_notes.map((note, index) => <p key={index}>{String(note.text ?? "")}</p>)}</div>}</div>;
}

function formatQuantity(value: number): string {
  return value.toLocaleString("zh-CN");
}

function ExceptionTradeTable({ table, compare }: { table: { rows: ExceptionTradeRow[]; unmappedLimitCells: string[] }; compare: CompareResult | null }) {
  const exchangeGroups = table.rows.reduce<Array<{ exchange: string; rows: ExceptionTradeRow[] }>>((groups, row) => {
    const group = groups.find((item) => item.exchange === row.exchange);
    if (group) group.rows.push(row);
    else groups.push({ exchange: row.exchange, rows: [row] });
    return groups;
  }, []);

  return <section className="exception-table-panel">
    <div className="exception-table-heading">
      <div><p className="eyebrow">EXCEPTION MONITORING</p><h3>异常交易开仓总量</h3><p className="muted">从识别结果中的“交易限额”单元格提取品种/合约，并通过本地静态映射补全交易所与代码。</p></div>
      <span className="exception-row-count">{table.rows.length} 条限制</span>
    </div>
    <div className="exception-table-note">原图只提供单日最大开仓量，未提供独立预警线；预警值暂按最大开仓量的 80% 计算。中金所股指期权同时区分品种合计、单个月份期权合约和深度虚值合约，已分别整理。</div>
    <EntityDiffSummary compare={compare} />
    {table.rows.length ? <div className="table-scroll"><table className="exception-table"><thead><tr>{EXCEPTION_TRADE_HEADERS.map((header) => <th scope="col" key={header}>{header}</th>)}</tr></thead>{exchangeGroups.map((group, groupIndex) => <tbody key={group.exchange} className={groupIndex > 0 ? "exception-exchange-group" : undefined}>{group.rows.map((row, rowIndex) => {
      const diff = findEntityDiff(compare, row.sourceCells);
      const rowClassName = [rowIndex === 0 && groupIndex > 0 ? "exception-group-start" : "", diff ? "entity-diff-" + diff.kind : ""].filter(Boolean).join(" ");
      return <tr className={rowClassName} key={row.id} title={entityDiffTitle(diff) || row.sourceText}>{rowIndex === 0 && <td className="exception-exchange-cell" rowSpan={group.rows.length}>{group.exchange}</td>}<td><span className="instrument-name">{row.instrumentName}</span><EntityDiffMarker diff={diff} /></td><td><code>{row.instrumentCode}</code></td><td className="exception-level-cell">{row.level}</td><td className="quantity-cell">{formatQuantity(row.openTotal)}</td><td className="quantity-cell warning-cell">{formatQuantity(row.openTotalWarning)}</td><td><span className={"instrument-kind " + (row.instrumentType === "期权" ? "option" : "future")}>{row.instrumentType}</span></td></tr>;
    })}</tbody>)}</table></div> : <div className="exception-empty">未从交易限额单元格中识别到可映射品种，请展开原始表格核对。</div>}
    {table.unmappedLimitCells.length > 0 && <div className="exception-unmapped"><strong>有 {table.unmappedLimitCells.length} 个限额单元格未完成静态映射</strong><span>已保留在原始识别表格中，请补充映射后再使用。</span></div>}
  </section>;
}

function PositionLimitTable({ table, compare }: { table: { rows: PositionLimitRow[]; unmappedCells: string[] }; compare: CompareResult | null }) {
  const groups = table.rows.reduce<Array<{ id: string; rows: PositionLimitRow[] }>>((result, row) => {
    const group = result.find((item) => item.id === row.groupId);
    if (group) group.rows.push(row);
    else result.push({ id: row.groupId, rows: [row] });
    return result;
  }, []);
  const hasFutureRows = table.rows.some((row) => row.type === "期货");
  const hasOptionRows = table.rows.some((row) => row.type === "期权");
  const tableTitle = hasFutureRows && hasOptionRows ? "期货/期权限仓" : hasOptionRows ? "期权限仓" : "期货限仓";

  return <section className="position-limit-panel">
    <div className="position-limit-heading">
      <div><p className="eyebrow">POSITION LIMITS</p><h3>{tableTitle}</h3><p className="muted">从 OCR 识别结果整理交易所、品种/合约、持仓日期、总持仓量和最大单边持仓规则；品种名称按本地交易代码映射。</p></div>
      <span className="position-limit-count">{table.rows.length} 条规则</span>
    </div>
    <div className="position-limit-note">持仓方向和投保未在图片中单独列出时按“所有”展示；固定值与百分比限仓均保留原表含义。原始识别表格可展开核对 OCR 文本和合并关系。</div>
    <EntityDiffSummary compare={compare} />
    {table.rows.length ? <div className="table-scroll"><table className="position-limit-table"><thead><tr>{POSITION_LIMIT_HEADERS.map((header) => <th scope="col" key={header}>{header}</th>)}</tr></thead>{groups.map((group, groupIndex) => <tbody key={group.id} className={groupIndex > 0 ? "position-limit-group" : undefined}>{group.rows.map((row, rowIndex) => {
      const diff = findEntityDiff(compare, row.sourceCells);
      const rowClassName = [rowIndex === 0 && groupIndex > 0 ? "position-group-start" : "", diff ? "entity-diff-" + diff.kind : ""].filter(Boolean).join(" ");
      return <tr key={row.id} className={rowClassName} title={entityDiffTitle(diff) || row.sourceText}>{rowIndex === 0 && <><td className="position-type-cell" rowSpan={group.rows.length}><span className={"position-type " + (row.type === "期权" ? "option" : "future")}>{row.type}</span></td><td className="position-exchange-cell" rowSpan={group.rows.length}>{row.exchange}</td><td className="position-instrument-cell" rowSpan={group.rows.length}><code>{row.instrument}</code></td><td className="position-meta-cell" rowSpan={group.rows.length}>{row.direction}</td><td className="position-meta-cell" rowSpan={group.rows.length}>{row.hedge}</td></>}<td className="position-date-cell">{row.holdingDate}</td><td className="position-range-cell">{row.totalPosition}</td><td className="position-rule-cell"><span>{row.limitRule}</span><EntityDiffMarker diff={diff} /></td></tr>;
    })}</tbody>)}</table></div> : <div className="position-limit-empty">未从识别结果中整理出可用的限仓规则，请展开原始识别表格核对。</div>}
    {table.unmappedCells.length > 0 && <div className="position-limit-unmapped"><strong>有 {table.unmappedCells.length} 个品种未完成交易代码映射</strong><span>{table.unmappedCells.join("；")}</span></div>}
  </section>;
}

function ConfidenceGuide() {
  return <div className="confidence-guide" role="note"><strong>识别分数说明：</strong><span className="confidence-key high">绿色 ≥90%</span><span className="confidence-key medium">黄色 75%–89.9%</span><span className="confidence-key low">红色 &lt;75%</span><span className="confidence-key unknown">— 未提供</span></div>;
}

function TableSectionView({ section, diffMap, qualityMap, selectedRange, onChangeCell, onSelectCell, onMerge, onUnmerge }: { section: TableSection; diffMap: Map<string, string>; qualityMap: Map<string, number>; selectedRange: CellRange | null; onChangeCell: (sectionId: string, row: number, column: number, value: string) => void; onSelectCell: (sectionId: string, row: number, column: number, extend: boolean) => void; onMerge: () => void; onUnmerge: () => void }) {
  const { starts, covered } = mergeMaps(section);
  const columns = Math.max(section.x_edges.length - 1, ...section.cells.map((row) => row.length), 1);
  const sectionSelection = selectedRange?.sectionId === section.id ? selectedRange : null;
  const selectionIsSingleCell = sectionSelection?.r0 === sectionSelection?.r1 && sectionSelection?.c0 === sectionSelection?.c1;
  const selectedMerge = sectionSelection && selectionIsSingleCell ? findMergeAt(section, sectionSelection.r0, sectionSelection.c0) : null;
  const selectionOverlapsMerge = sectionSelection ? section.merged_cells.some((merged) => rangesOverlap(sectionSelection, merged)) : false;
  const selectionSize = sectionSelection ? (sectionSelection.r1 - sectionSelection.r0 + 1) * (sectionSelection.c1 - sectionSelection.c0 + 1) : 0;

  return <div className="table-block">
    <div className="section-band">
      <div><strong>{section.label || section.id}</strong><span>{section.ocr_count} 个 OCR 框 · {section.strategy}</span></div>
      <div className="table-tools">{sectionSelection && <span className="selection-hint">已选 {selectionSize} 个单元格</span>}<button type="button" className="table-action" disabled={!sectionSelection || selectionSize < 2 || selectionOverlapsMerge} onClick={onMerge}>合并选区</button><button type="button" className="table-action" disabled={!selectedMerge} onClick={onUnmerge}>取消合并</button></div>
    </div>
    <div className="table-scroll"><table className="data-table"><tbody>{section.cells.map((row, rowIndex) => <tr key={rowIndex}>{Array.from({ length: columns }, (_, columnIndex) => {
      const key = `${rowIndex}:${columnIndex}`;
      if (covered.has(key)) return null;
      const merge = starts.get(key);
      const value = row[columnIndex] ?? "";
      const diff = diffMap.get(`${section.id}:${rowIndex}:${columnIndex}`);
      const score = qualityMap.get(`${section.id}:${rowIndex}:${columnIndex}`) ?? merge?.score ?? null;
      const level = scoreLevel(score);
      const scoreDisplay = formatConfidence(score);
      const title = [diff ? `相对上次：${diff}` : "", `识别分数：${scoreDisplay}`].filter(Boolean).join("；") || undefined;
      const selected = Boolean(sectionSelection && cellRangeContains(sectionSelection, rowIndex, columnIndex));
      return <td key={columnIndex} rowSpan={merge?.rowSpan} colSpan={merge?.colSpan} className={`${diff ? `diff-${diff}` : ""} ${merge ? "merged-cell" : ""} ${level === "low" ? "low-confidence" : ""} ${selected ? "cell-selected" : ""}`} title={title} onClick={(event) => onSelectCell(section.id, rowIndex, columnIndex, event.shiftKey)}><small className={`cell-score ${level}`}>{scoreDisplay}</small><AutoResizeTextarea ariaLabel={`${section.label || section.id} 第${rowIndex + 1}行第${columnIndex + 1}列`} value={cellDisplay(value)} onChange={(nextValue) => onChangeCell(section.id, rowIndex, columnIndex, nextValue)} /></td>;
    })}</tr>)}</tbody></table></div>
  </div>;
}

function Artifacts({ run }: { run: Run }) { return <section className="panel artifacts-panel"><div className="panel-heading"><div><p className="eyebrow">ARTIFACTS</p><h2>产物</h2></div></div><div className="artifact-list">{run.artifacts.map((artifact) => <a key={artifact.id} href={artifact.download_url} target="_blank" rel="noreferrer"><span>{artifact.kind === "source_image" ? "原图" : artifact.kind.includes("xlsx") ? "XLSX" : artifact.kind.includes("json") ? "JSON" : artifact.kind}</span><small>{artifact.filename}</small></a>)}</div></section>; }

export default App;
