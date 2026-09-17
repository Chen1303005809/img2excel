import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "./api";
import { buildDiffMap, buildQualityMap, cellDisplay, cellRangeContains, cloneDocument, findMergeAt, formatConfidence, mergeCellRange, mergeMaps, parseCellInput, rangesOverlap, scoreLevel, unmergeCellAt, type CellRange } from "./tableModel";
import type { CompareResult, Document, Run, Scalar, Source, TableSection } from "./types";

type View = "sources" | "runs";
type Notice = { kind: "error" | "success"; text: string } | null;

const activeStatuses = new Set(["queued", "crawling", "downloading", "extracting", "exporting", "awaiting_image_selection"]);

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
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

function documentStats(document: Document | null) {
  if (!document) return { sections: 0, cells: 0, lowScore: 0 };
  return {
    sections: document.sections.length,
    cells: document.sections.reduce((total, section) => total + section.cells.flat().filter((value) => value !== "" && value !== null).length, 0),
    lowScore: Number(document.metrics.ocr_low_score_count ?? 0),
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
  const [revisionId, setRevisionId] = useState<string | undefined>();
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedRange, setSelectedRange] = useState<CellRange | null>(null);

  const refreshSources = useCallback(async () => setSources(await api.sources()), []);
  const refreshRuns = useCallback(async () => setRuns(await api.runs(sourceFilter || undefined, statusFilter || undefined)), [sourceFilter, statusFilter]);

  const loadRun = useCallback(async (runId: string) => {
    setSelectedRange(null);
    const run = await api.run(runId);
    setSelectedRun(run);
    setSelectedRunId(runId);
    if (run.status === "succeeded") {
      const [documentResponse, comparison] = await Promise.all([api.document(runId, "revised"), api.compare(runId)]);
      setDocument(documentResponse.document);
      setSavedDocument(cloneDocument(documentResponse.document));
      setRecognizedHash(documentResponse.recognized_document_sha256);
      setRevisionId(documentResponse.revision?.id);
      setCompare(comparison);
    } else {
      setDocument(null);
      setSavedDocument(null);
      setCompare(null);
      setRevisionId(undefined);
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

  async function exportRun() {
    if (!selectedRunId) return;
    try {
      const result = await api.exportRun(selectedRunId, revisionId);
      for (const artifact of result.artifacts) window.open(artifact.download_url, "_blank", "noopener,noreferrer");
    } catch (error) {
      setNotice({ kind: "error", text: (error as Error).message });
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
                <SourceTable sources={sources} onRun={runSource} onToggle={toggleSource} />
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
          <RunDetail run={selectedRun} document={document} compare={compare} stats={stats} dirty={isDirty} selectedRange={selectedRange} onSelectImage={selectImage} onChangeCell={updateCell} onSelectCell={selectCell} onMerge={mergeSelectedCells} onUnmerge={unmergeSelectedCell} onSave={saveRevision} onExport={exportRun} />
        </aside>
      </main>
    </div>
  );
}

function SourceTable({ sources, onRun, onToggle }: { sources: Source[]; onRun: (source: Source) => void; onToggle: (source: Source) => void }) {
  if (!sources.length) return <div className="empty-state">还没有来源，先添加一个网址。</div>;
  return <div className="table-scroll"><table className="list-table"><thead><tr><th>名称</th><th>网址</th><th>状态</th><th>最近运行</th><th /></tr></thead><tbody>{sources.map((source) => <tr key={source.id}><td className="strong">{source.name}</td><td className="url-cell" title={source.url}>{source.url}</td><td><span className={`status-dot ${source.enabled ? "on" : "off"}`}>{source.enabled ? "启用" : "停用"}</span></td><td>{source.latest_run ? <><span className={`status-badge ${source.latest_run.status}`}>{statusText(source.latest_run.status)}</span><small className="table-time">{formatTime(source.latest_run.finished_at || source.latest_run.created_at)}</small></> : "暂无"}</td><td className="actions"><button className="quiet" disabled={!source.enabled} onClick={() => onRun(source)}>立即运行</button><button className="quiet" onClick={() => onToggle(source)}>{source.enabled ? "停用" : "启用"}</button></td></tr>)}</tbody></table></div>;
}

function RunTable({ runs, selectedRunId, onSelect }: { runs: Run[]; selectedRunId: string | null; onSelect: (id: string) => void }) {
  if (!runs.length) return <div className="empty-state">还没有运行记录。</div>;
  return <div className="table-scroll"><table className="list-table"><thead><tr><th>状态</th><th>网址</th><th>进度</th><th>创建时间</th><th>变化</th></tr></thead><tbody>{runs.map((run) => <tr className={run.id === selectedRunId ? "selected-row" : ""} key={run.id} onClick={() => onSelect(run.id)}><td><span className={`status-badge ${run.status}`}>{statusText(run.status)}</span></td><td className="url-cell" title={run.requested_url}>{run.requested_url}</td><td><div className="progress-cell"><div className="progress-track"><span style={{ width: `${run.progress}%` }} /></div><small>{run.progress}%</small></div></td><td>{formatTime(run.created_at)}</td><td>{run.comparison_summary?.has_baseline ? (run.comparison_summary.has_changes ? `${comparisonCount(run.comparison_summary)} 项` : "无变化") : "首次"}</td></tr>)}</tbody></table></div>;
}

function RunDetail({ run, document, compare, stats, dirty, selectedRange, onSelectImage, onChangeCell, onSelectCell, onMerge, onUnmerge, onSave, onExport }: { run: Run | null; document: Document | null; compare: CompareResult | null; stats: { sections: number; cells: number; lowScore: number }; dirty: boolean; selectedRange: CellRange | null; onSelectImage: (candidateId: string) => void; onChangeCell: (sectionId: string, row: number, column: number, value: string) => void; onSelectCell: (sectionId: string, row: number, column: number, extend: boolean) => void; onMerge: () => void; onUnmerge: () => void; onSave: () => void; onExport: () => void }) {
  if (!run) return <section className="panel detail-empty"><div className="empty-illustration">↗</div><h2>选择一次运行</h2><p>从来源页或运行历史中选择记录，这里会显示任务进度、数据表和历史差异。</p></section>;
  return <>
    <section className="panel run-card"><div className="run-card-top"><div><p className="eyebrow">RUN DETAIL</p><h2>{run.status === "succeeded" ? (document?.title || "识别结果") : statusText(run.status)}</h2><p className="muted">{formatTime(run.created_at)} · {run.requested_url}</p></div><span className={`status-badge large ${run.status}`}>{statusText(run.status)}</span></div><div className="progress-track large"><span style={{ width: `${run.progress}%` }} /></div><div className="run-message">{run.message}{run.error_message && <span className="error-text">：{run.error_message}</span>}</div>{run.status === "succeeded" && <div className="stat-row"><Stat label="分区" value={stats.sections} /><Stat label="非空单元格" value={stats.cells} /><Stat label="低分框" value={stats.lowScore} /></div>}{run.status === "succeeded" && <SelectedImageInfo run={run} />}</section>
    {run.status === "awaiting_image_selection" && <CandidatePicker candidates={run.candidates} onSelect={onSelectImage} />}
    {run.status === "succeeded" && document && <>
      <ComparisonPanel compare={compare} />
      <section className="panel data-panel"><div className="panel-heading"><div><p className="eyebrow">DATA PANEL</p><h2>识别数据 {dirty && <span className="unsaved-badge">有未保存修改</span>}</h2><p className="muted">可修改单元格值。合并单元格：先单击起始单元格，再按 Shift 单击结束单元格，然后点击“合并选区”。保存修订后再导出，历史原稿保持不变。</p></div><div className="button-row"><button className={dirty ? "primary" : "quiet"} onClick={onSave}>保存修订</button><button className="primary" onClick={onExport}>导出 JSON / XLSX</button></div></div><div className="data-workspace"><OriginalImageViewer run={run} /><DocumentTables document={document} compare={compare} selectedRange={selectedRange} onChangeCell={onChangeCell} onSelectCell={onSelectCell} onMerge={onMerge} onUnmerge={onUnmerge} /></div></section>
      <Artifacts run={run} />
    </>}
  </>;
}

function Stat({ label, value }: { label: string; value: number }) { return <div className="stat"><strong>{value}</strong><span>{label}</span></div>; }

function SelectedImageInfo({ run }: { run: Run }) {
  const candidate = run.candidates.find((item) => item.selected);
  if (!candidate) return null;
  const dimensions = candidate.width && candidate.height ? `${candidate.width} × ${candidate.height}` : "尺寸未知";
  return <div className="image-info">原图：{dimensions}{candidate.mime_type && <span> · {candidate.mime_type}</span>}{candidate.sha256 && <span> · SHA-256 {candidate.sha256.slice(0, 16)}…</span>}</div>;
}

function OriginalImageViewer({ run }: { run: Run }) {
  const artifact = run.artifacts.find((item) => item.kind === "source_image");
  return <section className="original-image-viewer"><div className="original-image-heading"><div><p className="eyebrow">SOURCE IMAGE</p><h3>原图核对</h3></div>{artifact && <a href={artifact.download_url} target="_blank" rel="noreferrer">打开原图</a>}</div>{artifact ? <div className="original-image-scroll"><img src={artifact.download_url} alt="本次运行下载的原始表格图片" /></div> : <div className="image-empty">暂无原图产物</div>}{artifact && <small className="original-image-meta">{artifact.filename}</small>}</section>;
}

function CandidatePicker({ candidates, onSelect }: { candidates: Run["candidates"]; onSelect: (id: string) => void }) { return <section className="panel candidate-panel"><p className="eyebrow">IMAGE CANDIDATES</p><h2>请选择正文图片</h2><p className="muted">页面发现多张图片。选择正确的表格图片后才会开始识别。</p><div className="candidate-list">{candidates.map((candidate) => <button className="candidate" key={candidate.id} onClick={() => onSelect(candidate.id)}><span className="candidate-number">{candidate.ordinal + 1}</span><span><strong>{candidate.width && candidate.height ? `${candidate.width} × ${candidate.height}` : "尺寸未知"}</strong><small>{candidate.alt || candidate.resolved_url}</small></span></button>)}</div></section>; }

function ComparisonPanel({ compare }: { compare: CompareResult | null }) { if (!compare || !compare.has_baseline) return <section className="panel comparison-panel"><div><p className="eyebrow">COMPARISON</p><h2>暂无历史基线</h2><p className="muted">这是该网址第一次成功识别，下一次运行后会显示差异。</p></div></section>; const { summary } = compare; return <section className={`panel comparison-panel ${compare.has_changes ? "has-changes" : "no-changes"}`}><div><p className="eyebrow">COMPARISON</p><h2>{compare.has_changes ? "发现历史变化" : "与上次相同"}</h2><p className="muted">基线运行于 {formatTime(compare.baseline?.finished_at)}。</p></div><div className="change-summary"><span><strong>{summary.changed_cells}</strong> 修改</span><span><strong>{summary.added_cells}</strong> 新增</span><span><strong>{summary.removed_cells}</strong> 删除</span><span><strong>{summary.merge_changes + summary.dimension_changes}</strong> 结构</span></div>{compare.has_changes && <div className="removed-list">{compare.sections.flatMap((section) => section.changes.filter((change) => change.kind === "removed").map((change) => <span key={`${section.section_id ?? section.baseline_section_id}-${change.row}-${change.column}`}>{section.label || section.section_id || section.baseline_section_id} · 第 {change.row} 行第 {change.column} 列：{cellDisplay(change.before)}</span>))}</div>}</section>; }

function DocumentTables({ document, compare, selectedRange, onChangeCell, onSelectCell, onMerge, onUnmerge }: { document: Document; compare: CompareResult | null; selectedRange: CellRange | null; onChangeCell: (sectionId: string, row: number, column: number, value: string) => void; onSelectCell: (sectionId: string, row: number, column: number, extend: boolean) => void; onMerge: () => void; onUnmerge: () => void }) {
  const diffMap = buildDiffMap(compare);
  const qualityMap = buildQualityMap(document);
  return <div className="document-tables"><ConfidenceGuide />{document.sections.map((section) => <TableSectionView key={section.id} section={section} diffMap={diffMap} qualityMap={qualityMap} selectedRange={selectedRange} onChangeCell={onChangeCell} onSelectCell={onSelectCell} onMerge={onMerge} onUnmerge={onUnmerge} />)}{document.footer_notes?.length > 0 && <div className="notes-block"><strong>页脚说明</strong>{document.footer_notes.map((note, index) => <p key={index}>{String(note.text ?? "")}</p>)}</div>}</div>;
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
      return <td key={columnIndex} rowSpan={merge?.rowSpan} colSpan={merge?.colSpan} className={`${diff ? `diff-${diff}` : ""} ${merge ? "merged-cell" : ""} ${level === "low" ? "low-confidence" : ""} ${selected ? "cell-selected" : ""}`} title={title} onClick={(event) => onSelectCell(section.id, rowIndex, columnIndex, event.shiftKey)}><small className={`cell-score ${level}`}>{scoreDisplay}</small><textarea aria-label={`${section.label || section.id} 第${rowIndex + 1}行第${columnIndex + 1}列`} value={cellDisplay(value)} onChange={(event) => onChangeCell(section.id, rowIndex, columnIndex, event.target.value)} /></td>;
    })}</tr>)}</tbody></table></div>
  </div>;
}

function Artifacts({ run }: { run: Run }) { return <section className="panel artifacts-panel"><div className="panel-heading"><div><p className="eyebrow">ARTIFACTS</p><h2>产物</h2></div></div><div className="artifact-list">{run.artifacts.map((artifact) => <a key={artifact.id} href={artifact.download_url} target="_blank" rel="noreferrer"><span>{artifact.kind === "source_image" ? "原图" : artifact.kind.includes("xlsx") ? "XLSX" : artifact.kind.includes("json") ? "JSON" : artifact.kind}</span><small>{artifact.filename}</small></a>)}</div></section>; }

export default App;
