import { exchangeCodeForName, INSTRUMENT_MAPPINGS, type InstrumentMapping } from "./exceptionTradeModel";
import type { Document, Scalar, SourceCellRef, TableSection } from "./types";

export type PositionLimitInstrumentType = "期货" | "期权";

export interface PositionDateRule {
  startmonth: number;
  startday: number;
  startdaytype: 0 | 1;
  endmonth: number;
  endday: number;
  enddaytype: 0 | 1;
  startordertype: 0 | 1;
  endordertype: 0 | 1;
}

export interface PositionLimitRow {
  id: string;
  type: PositionLimitInstrumentType;
  exchange: string;
  exchangeCode: string | null;
  instrument: string;
  direction: string;
  hedge: string;
  holdingDate: string;
  dateRule?: PositionDateRule;
  totalPosition: string;
  limitRule: string;
  sourceText: string;
  sourceSectionId: string;
  sourceCells: SourceCellRef[];
  groupId: string;
}

export interface PositionLimitTable {
  rows: PositionLimitRow[];
  unmappedCells: string[];
}

export const POSITION_LIMIT_HEADERS = [
  "类型",
  "交易所名称",
  "品种/合约",
  "持仓方向",
  "投保",
  "持仓日期",
  "总持仓量",
  "限仓规则（最大单边持仓量）",
] as const;

const DEFAULT_TOTAL_POSITION = "0<=持仓量<+∞";

const EXTRA_POSITION_MAPPINGS: readonly InstrumentMapping[] = [
  { name: "早籼稻", code: "RI", exchange: "郑州商品交易所", aliases: ["早籼稻"] },
  { name: "菜籽", code: "RS", exchange: "郑州商品交易所", aliases: ["菜籽"] },
  { name: "粳稻", code: "JR", exchange: "郑州商品交易所", aliases: ["粳稻"] },
  { name: "晚籼稻", code: "LR", exchange: "郑州商品交易所", aliases: ["晚籼稻"] },
  { name: "棉纱", code: "CY", exchange: "郑州商品交易所", aliases: ["棉纱"] },
  { name: "线材", code: "WR", exchange: "上海期货交易所", aliases: ["线材"] },
  { name: "10年期国债", code: "T", exchange: "中国金融期货交易所", aliases: ["10年期国债"] },
  { name: "5年期国债", code: "TF", exchange: "中国金融期货交易所", aliases: ["5年期国债"] },
  { name: "2年期国债", code: "TS", exchange: "中国金融期货交易所", aliases: ["2年期国债"] },
  { name: "30年期国债", code: "TL", exchange: "中国金融期货交易所", aliases: ["30年期国债"] },
];

const POSITION_MAPPINGS = [...INSTRUMENT_MAPPINGS, ...EXTRA_POSITION_MAPPINGS];

// OCR occasionally turns PTA into FTA and 对二甲苯 into 丙烯. Keep these
// corrections local to the presentation model; the raw OCR document remains
// untouched and can still be reviewed or edited by the user.
const OCR_PRODUCT_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  FTA: "PTA",
  丙烯: "对二甲苯",
});

const EXCHANGE_ALIASES: readonly { name: string; aliases: readonly string[] }[] = [
  { name: "大连商品交易所", aliases: ["大连商品交易所", "大商所"] },
  { name: "郑州商品交易所", aliases: ["郑州商品交易所", "郑商所"] },
  { name: "上海期货交易所", aliases: ["上海期货交易所", "上期所"] },
  { name: "上海国际能源交易中心", aliases: ["上海国际能源交易中心", "能源中心"] },
  { name: "中国金融期货交易所", aliases: ["中国金融期货交易所", "中金所"] },
  { name: "广州期货交易所", aliases: ["广州期货交易所", "广期所"] },
];

interface DateGroup {
  c0: number;
  c1: number;
  label: string;
}

interface PositionRange {
  lower: number;
  upper: number | null;
  upperInclusive: boolean;
}

interface ProductGroup {
  name: string;
  rows: string[][];
  rowIndexes: number[];
  startRow: number;
}

interface LimitBlock {
  section: TableSection;
  rows: string[][];
  headerRow: number;
  startRow: number;
  endRow: number;
  dateGroups: DateGroup[];
  scaleColumn: number | null;
}

function cellText(value: Scalar): string {
  return value === null || value === undefined ? "" : String(value);
}

function compact(value: string): string {
  return value.replace(/[\s\u3000]+/g, "").replace(/[：﹕]/g, ":").trim();
}

function displayText(value: string): string {
  return value.replace(/[\s\u3000]+/g, " ").trim();
}

function normalizedText(value: string): string {
  return compact(value).replace(/[（）]/g, (character) => (character === "（" ? "(" : ")"));
}

function sectionRows(section: TableSection): string[][] {
  const columnCount = Math.max(section.cells.reduce((width, row) => Math.max(width, row.length), 0), section.x_edges.length - 1, 1);
  return section.cells.map((row) => Array.from({ length: columnCount }, (_, column) => cellText(row[column])));
}

function allDocumentText(document: Document): string {
  return [
    document.title,
    ...(document.bands ?? []).map((band) => String(band.text ?? "")),
    ...document.sections.flatMap((section) => [section.label, ...section.cells.flatMap((row) => row.map(cellText))]),
  ]
    .map(normalizedText)
    .join(" ");
}

function exchangeName(section: TableSection, document: Document): string {
  const sectionText = normalizedText(`${section.label} ${section.cells.flat().map(cellText).join(" ")}`);
  const documentText = normalizedText(`${document.title} ${document.bands?.map((band) => String(band.text ?? "")).join(" ") ?? ""}`);
  for (const exchange of EXCHANGE_ALIASES) {
    if (exchange.aliases.some((alias) => sectionText.includes(alias))) return exchange.name;
  }
  for (const exchange of EXCHANGE_ALIASES) {
    if (exchange.aliases.some((alias) => documentText.includes(alias))) return exchange.name;
  }
  return displayText(section.label.replace(/^T\d+\s*/i, "")) || "未识别交易所";
}

function instrumentType(document: Document, productText: string): PositionLimitInstrumentType {
  const title = normalizedText(document.title);
  if (normalizedText(productText).includes("期权")) return "期权";
  if (title.includes("期权限仓") && !title.includes("期货限仓")) return "期权";
  return "期货";
}

function isPositionLimitHeaderText(value: string): boolean {
  const text = normalizedText(value);
  return /合约|交割|挂牌|上市|交易日|日历日|最后交易|一般月份|临近交割月份/.test(text);
}

function isDatePeriodText(value: string): boolean {
  const text = normalizedText(value);
  return /交割|挂牌|上市|最后交易|一般月份|临近交割月份/.test(text);
}

function isCommentText(value: string): boolean {
  const text = normalizedText(value);
  return /^(注[:：]|说明[:：])/.test(text) || /做市商|实际控制关系|期权合约与期货合约|套期保值交易|开仓交易的最大/.test(text);
}

function isLimitValue(value: string): boolean {
  const text = normalizedText(value);
  if (!text || isCommentText(text)) return false;
  return /\d/.test(text) && (/[<>≤≥=]|万手|手|%|％/.test(text) || /^\d[\d,.]*$/.test(text));
}

function isDateHeaderRow(row: string[]): boolean {
  return row.filter(isDatePeriodText).length >= 2;
}

function rowMergeGroups(section: TableSection, rowIndex: number, row: string[]): DateGroup[] {
  const groups: DateGroup[] = [];
  const covered = new Set<number>();
  for (const merged of section.merged_cells ?? []) {
    if (merged.r0 !== rowIndex || merged.r1 !== rowIndex || merged.c0 <= 0) continue;
    const label = displayText(cellText(merged.value) || row[merged.c0] || "");
    if (!label) continue;
    groups.push({ c0: merged.c0, c1: merged.c1, label });
    for (let column = merged.c0; column <= merged.c1; column += 1) covered.add(column);
  }
  for (let column = 1; column < row.length; column += 1) {
    if (covered.has(column) || !row[column]) continue;
    groups.push({ c0: column, c1: column, label: displayText(row[column]) });
  }
  return groups.sort((left, right) => left.c0 - right.c0);
}

function positionHeaderGroups(section: TableSection, rowIndex: number, row: string[]): DateGroup[] {
  const groups = rowMergeGroups(section, rowIndex, row).filter((group) => isDatePeriodText(group.label));
  const normalizedRow = row.map(normalizedText);
  const firstGroup = groups.find((group) => group.c0 === 1);
  const secondGroup = groups.find((group) => group.c0 === 2);
  const hasSyntheticFirstGroup = normalizedRow[1]?.includes("持仓量") && normalizedRow[2]?.includes("限仓");
  if (hasSyntheticFirstGroup && (!firstGroup || (firstGroup.c1 === 1 && secondGroup?.c0 === 2))) {
    if (firstGroup) groups.splice(groups.indexOf(firstGroup), 1);
    if (secondGroup) groups.splice(groups.indexOf(secondGroup), 1);
    groups.unshift({ c0: 1, c1: 2, label: normalizedRow[2].replace(/限仓比例.*$/, "") || "下一交易日" });
  }
  return groups.sort((left, right) => left.c0 - right.c0);
}

function firstProductRow(rows: string[][], start: number, end: number): number {
  for (let rowIndex = start; rowIndex < end; rowIndex += 1) {
    const row = rows[rowIndex];
    const product = normalizedText(row[0] ?? "");
    if (!product || isCommentText(product) || isPositionLimitHeaderText(product)) continue;
    if (row.slice(1).some(isLimitValue)) return rowIndex;
  }
  return end;
}

function hasScaleColumn(rows: string[][], start: number, dataStart: number): boolean {
  return rows.slice(start, dataStart).some((row) =>
    row.some((value) => /合约单边持仓规模|单边持仓量|某一期货合约持仓量|某一合约结算后持仓量/.test(normalizedText(value))),
  );
}

function findDateHeaders(section: TableSection, rows: string[][]): LimitBlock[] {
  const headerIndexes = rows.reduce<number[]>((indexes, row, rowIndex) => {
    if (isDateHeaderRow(row)) indexes.push(rowIndex);
    return indexes;
  }, []);
  const blocks: LimitBlock[] = [];
  for (let index = 0; index < headerIndexes.length; index += 1) {
    const headerIndex = headerIndexes[index];
    const endRow = headerIndexes[index + 1] ?? rows.length;
    const dateGroups = positionHeaderGroups(section, headerIndex, rows[headerIndex]);
    if (!dateGroups.length) continue;
    const dataStart = firstProductRow(rows, headerIndex + 1, endRow);
    if (dataStart >= endRow) continue;
    const inferredScaleColumn = rows.slice(dataStart, endRow).some((row) => thresholdRange(row[1] ?? "") !== null);
    blocks.push({
      section,
      rows,
      headerRow: headerIndex,
      startRow: dataStart,
      endRow,
      dateGroups,
      scaleColumn: hasScaleColumn(rows, headerIndex, dataStart) || inferredScaleColumn ? 1 : null,
    });
  }
  return blocks;
}

function normalizeProductSearchText(value: string): string {
  let text = normalizedText(value).toLocaleUpperCase();
  for (const [from, to] of Object.entries(OCR_PRODUCT_ALIASES)) text = text.replaceAll(from, to.toLocaleUpperCase());
  return text;
}

function mappingAliases(mapping: InstrumentMapping): readonly string[] {
  return [...mapping.aliases, ...(mapping.name === "PTA" ? ["FTA"] : []), ...(mapping.name === "对二甲苯" ? ["丙烯"] : [])];
}

function mappingMatches(text: string): { mapping: InstrumentMapping; start: number; length: number }[] {
  const searchable = normalizeProductSearchText(text);
  const candidates: { mapping: InstrumentMapping; start: number; length: number }[] = [];
  for (const mapping of POSITION_MAPPINGS) {
    for (const alias of mappingAliases(mapping)) {
      const normalizedAlias = normalizeProductSearchText(alias);
      const start = searchable.indexOf(normalizedAlias);
      if (start >= 0) candidates.push({ mapping, start, length: normalizedAlias.length });
    }
  }
  candidates.sort((left, right) => left.start - right.start || right.length - left.length);
  const selected: { mapping: InstrumentMapping; start: number; length: number }[] = [];
  for (const candidate of candidates) {
    if (selected.some((item) => item.mapping.name === candidate.mapping.name)) continue;
    if (selected.some((item) => candidate.start < item.start + item.length && item.start < candidate.start + candidate.length)) continue;
    selected.push(candidate);
  }
  return selected.sort((left, right) => left.start - right.start);
}

function explicitContractCodes(text: string): string[] {
  return [...new Set([...text.matchAll(/([A-Za-z]{1,3}\d{4})/g)].map((match) => match[1].toLocaleUpperCase()))];
}

function resolveInstrumentCodes(
  productText: string,
  kind: PositionLimitInstrumentType = "期货",
): { codes: string[]; mapped: boolean } {
  const matches = mappingMatches(productText);
  const explicitCodes = explicitContractCodes(productText);
  if (explicitCodes.length) {
    const mappedCodes = explicitCodes.filter((code) => {
      const prefix = code.replace(/\d{4}$/, "");
      return POSITION_MAPPINGS.some((mapping) => [mapping.code, mapping.optionCode].filter(Boolean).includes(prefix));
    });
    if (mappedCodes.length) return { codes: mappedCodes, mapped: true };
  }
  if (matches.length) {
    return {
      codes: [...new Set(matches.map(({ mapping }) => (kind === "期权" ? mapping.optionCode ?? mapping.code : mapping.code)))],
      mapped: true,
    };
  }

  const fallback = displayText(productText)
    .split(/[\n、,，/]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .join("、");
  return { codes: fallback ? [fallback] : [], mapped: false };
}

function parseThreshold(value: string): { relation: string; bound: number } | null {
  const text = normalizedText(value).replace(/[＝﹦]/g, "=");
  const match = text.match(/[xX]?\s*(<=|>=|<|>|≤|≥)\s*(\d+(?:\.\d+)?)\s*(万)?/);
  if (!match) return null;
  const bound = Number(match[2]) * (match[3] ? 10_000 : 1);
  return Number.isFinite(bound) ? { relation: match[1], bound } : null;
}

function thresholdRange(value: string): PositionRange | null {
  const threshold = parseThreshold(value);
  if (!threshold) return null;
  const isLowerRange = ["<", "≤", "<="].includes(threshold.relation);
  return isLowerRange
    ? { lower: 0, upper: threshold.bound, upperInclusive: threshold.relation === "≤" || threshold.relation === "<=" }
    : { lower: threshold.bound, upper: null, upperInclusive: false };
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

function formatPositionRange(range: PositionRange | null): string {
  if (!range) return DEFAULT_TOTAL_POSITION;
  if (range.upper === null) return `${formatNumber(range.lower)}<=持仓量<+∞`;
  return `0<=持仓量${range.upperInclusive ? "<=" : "<"}${formatNumber(range.upper)}`;
}

function rawValueNumber(value: string): number | null {
  const text = normalizedText(value).replace(/[，,]/g, "");
  const match = text.match(/\d+(?:\.\d+)?/);
  if (!match) return null;
  const number = Number(match[0]);
  return Number.isFinite(number) ? number : null;
}

function isPercentageValue(value: string): boolean {
  const text = normalizedText(value);
  if (text.includes("%") || text.includes("％") || text.includes("比例")) return true;
  const number = rawValueNumber(text);
  return number !== null && number > 0 && number <= 1;
}

function formatLimitRule(value: string): string | null {
  const text = displayText(value);
  if (!text || isCommentText(text)) return null;
  const number = rawValueNumber(text);
  if (number === null) return null;
  if (isPercentageValue(text)) {
    const percent = text.includes("%") || text.includes("％") || text.includes("比例") ? number : number * 100;
    return `百分比${formatNumber(percent)}%`;
  }
  return `固定值${formatNumber(number)}`;
}

function valueForDate(row: string[], group: DateGroup, scaleColumn: number | null): string {
  if (scaleColumn !== null && group.c0 === scaleColumn) {
    const primary = row[group.c1] ?? "";
    if (primary && !parseThreshold(primary)) return primary;
    if (!primary) {
      const direct = row[scaleColumn] ?? "";
      if (direct && !parseThreshold(direct)) return direct;
    }
    return primary;
  }
  for (let column = group.c0; column <= group.c1; column += 1) {
    if (row[column]) return row[column];
  }
  return "";
}

function productGroups(block: LimitBlock): ProductGroup[] {
  const groups: ProductGroup[] = [];
  let current: ProductGroup | null = null;
  for (let rowIndex = block.startRow; rowIndex < block.endRow; rowIndex += 1) {
    const row = block.rows[rowIndex];
    const product = displayText(row[0] ?? "");
    if (product && !isCommentText(product) && !isPositionLimitHeaderText(product)) {
      if (current) groups.push(current);
      current = { name: product, rows: [row], rowIndexes: [rowIndex], startRow: rowIndex };
      continue;
    }
    if (!current || product || !row.some(isLimitValue)) continue;
    current.rows.push(row);
    current.rowIndexes.push(rowIndex);
  }
  if (current) groups.push(current);
  return groups;
}

function groupSourceText(group: ProductGroup): string {
  return group.rows
    .flatMap((row) => row.filter(Boolean))
    .map(displayText)
    .filter(Boolean)
    .join("；");
}

function uniqueSourceCells(cells: SourceCellRef[]): SourceCellRef[] {
  return [...new Map(cells.map((cell) => [cell.sectionId + ":" + cell.row + ":" + cell.column, cell])).values()];
}

function positionRowSourceCells(block: LimitBlock, group: ProductGroup, date: DateGroup, rowIndexes = group.rowIndexes): SourceCellRef[] {
  const cells = rowIndexes.flatMap((row) =>
    block.rows[row].map((_, column) => ({ sectionId: block.section.id, row, column })),
  );
  for (let column = date.c0; column <= date.c1; column += 1) {
    cells.push({ sectionId: block.section.id, row: block.headerRow, column });
  }
  return uniqueSourceCells(cells);
}

const SMALL_CHINESE_NUMBERS: Readonly<Record<string, number>> = Object.freeze({
  零: 0,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
});

function smallChineseNumber(value: string): number | null {
  if (/^\d+$/.test(value)) return Number(value);
  if (value in SMALL_CHINESE_NUMBERS) return SMALL_CHINESE_NUMBERS[value];
  if (value.startsWith("十")) return 10 + (SMALL_CHINESE_NUMBERS[value.slice(1)] ?? 0);
  const [left, right] = value.split("十");
  if (!right && !left) return null;
  if (value.includes("十")) return (SMALL_CHINESE_NUMBERS[left] ?? 0) * 10 + (SMALL_CHINESE_NUMBERS[right] ?? 0);
  return null;
}

function parseDateEndpoint(value: string, start: boolean): { month: number; day: number; daytype: 0 | 1; ordertype: 0 | 1 } | null {
  let text = compact(value).replace(/^[自从]/, "").replace(/期间.*$/, "").replace(/(起|开始)$/, "");
  if (text.includes("合约挂牌") || text.includes("合约上市")) return { month: -1, day: -1, daytype: 0, ordertype: 0 };
  if (text.includes("最后交易日")) return { month: -3, day: -1, daytype: 0, ordertype: 0 };
  if (text === "交割月" || text === "交割月份") return { month: start ? -2 : -1, day: start ? -2 : -1, daytype: 0, ordertype: 0 };

  const monthMatch = text.match(/交割月(?:前|之前)?([0-9一二两三四五六七八九十]+)个?月/);
  const month = monthMatch
    ? (smallChineseNumber(monthMatch[1]) ?? -999)
    : text.includes("交割月")
      ? (start ? -2 : -1)
      : -999;
  if (month === -999) return null;

  const daytype: 0 | 1 = text.includes("日历") ? 1 : 0;
  let ordertype: 0 | 1 = text.includes("最后一个") || text.includes("最后") ? 1 : 0;
  const dayMatch = text.match(/第(最后一个|[0-9一二两三四五六七八九十]+)个?(?:交易日|日历日|日)/);
  if (!dayMatch) return null;
  const day = dayMatch[1] === "最后一个" ? 1 : smallChineseNumber(dayMatch[1]);
  if (day === null) return null;
  if (dayMatch[1] === "最后一个") ordertype = 1;
  return { month, day, daytype, ordertype };
}

function parsePositionDateRule(value: string): PositionDateRule | undefined {
  const text = compact(value);
  if (text === "合约挂牌至交割月份" || text === "合约上市至交割月份") {
    return { startmonth: -1, startday: -1, startdaytype: 0, endmonth: -1, endday: -1, enddaytype: 0, startordertype: 0, endordertype: 0 };
  }
  let start: ReturnType<typeof parseDateEndpoint>;
  let end: ReturnType<typeof parseDateEndpoint>;
  if (text.includes("至")) {
    const [startText, endText] = text.split("至", 2);
    start = parseDateEndpoint(startText, true);
    end = parseDateEndpoint(endText, false);
  } else if (text.includes("起")) {
    start = parseDateEndpoint(text, true);
    end = parseDateEndpoint("交割月", false);
  } else {
    return undefined;
  }
  if (!start || !end) return undefined;
  return {
    startmonth: start.month,
    startday: start.day,
    startdaytype: start.daytype,
    endmonth: end.month,
    endday: end.day,
    enddaytype: end.daytype,
    startordertype: start.ordertype,
    endordertype: end.ordertype,
  };
}

function makePositionRow(
  block: LimitBlock,
  group: ProductGroup,
  instrumentTypeValue: PositionLimitInstrumentType,
  exchange: string,
  instrument: string,
  date: DateGroup,
  totalPosition: string,
  limitRule: string,
  dateIndex: number,
  ruleIndex: number,
  sourceCells = positionRowSourceCells(block, group, date),
): PositionLimitRow {
  const groupId = `${block.section.id}:${group.startRow}:${instrumentTypeValue}:${instrument}`;
  return {
    id: `${groupId}:${dateIndex}:${ruleIndex}:${totalPosition}:${limitRule}`,
    type: instrumentTypeValue,
    exchange,
    exchangeCode: exchangeCodeForName(exchange),
    instrument,
    direction: "所有",
    hedge: "所有",
    holdingDate: normalizeDateLabel(date.label),
    dateRule: parsePositionDateRule(normalizeDateLabel(date.label)),
    totalPosition,
    limitRule,
    sourceText: groupSourceText(group),
    sourceSectionId: block.section.id,
    sourceCells,
    groupId,
  };
}

function normalizeDateLabel(value: string): string {
  let text = compact(value);
  text = text.replace(/^自(?=合约)/, "");
  text = text.replace(/交割月[（(]自然人客户限仓为0[）)]/g, "交割月");
  text = text.replace(/交割月份[（(]自然人客户限仓为0[）)]/g, "交割月份");
  text = text.replace(/限仓比例.*$/, "").replace(/限仓数额.*$/, "");
  return text || "未识别日期区间";
}

function isSimplePositionProduct(value: string): boolean {
  const text = normalizedText(value);
  if (!text || isCommentText(text)) return false;
  return !/^(按|某一|某月|同一|非期货|限仓|做市商|客户|一般月份|临近交割)/.test(text);
}

function simplePositionRows(
  section: TableSection,
  rows: string[][],
  document: Document,
  exchange: string,
): { rows: PositionLimitRow[]; unmapped: string[] } {
  const result: PositionLimitRow[] = [];
  const unmapped: string[] = [];
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const product = displayText(rows[rowIndex][0] ?? "");
    if (!isSimplePositionProduct(product)) continue;
    const type = instrumentType(document, product);
    const resolved = resolveInstrumentCodes(product, type);
    const instrument = resolved.codes.join("、");
    if (!instrument || !rows[rowIndex].slice(1).some(isLimitValue)) continue;
    if (!resolved.mapped) unmapped.push(product);

    const ruleValue = rows[rowIndex].slice(1).find((value) => formatLimitRule(value));
    const limitRule = ruleValue ? formatLimitRule(ruleValue) : null;
    if (!limitRule) continue;
    const groupId = `${section.id}:${rowIndex}:${type}:${instrument}`;
    result.push({
      id: `${groupId}:0:${DEFAULT_TOTAL_POSITION}:${limitRule}`,
      type,
      exchange,
      exchangeCode: exchangeCodeForName(exchange),
      instrument,
      direction: "所有",
      hedge: "所有",
      holdingDate: "合约挂牌至交割月份",
      dateRule: parsePositionDateRule("合约挂牌至交割月份"),
      totalPosition: DEFAULT_TOTAL_POSITION,
      limitRule,
      sourceText: rows[rowIndex].filter(Boolean).map(displayText).join("；"),
      sourceSectionId: section.id,
      sourceCells: rows[rowIndex].map((_, column) => ({ sectionId: section.id, row: rowIndex, column })),
      groupId,
    });
  }
  return { rows: result, unmapped };
}

function rowsForProduct(
  block: LimitBlock,
  group: ProductGroup,
  document: Document,
  exchange: string,
): { rows: PositionLimitRow[]; unmapped: string[] } {
  const type = instrumentType(document, group.name);
  const resolved = resolveInstrumentCodes(group.name, type);
  const instrument = resolved.codes.join("、");
  const unmapped = resolved.mapped ? [] : [group.name];
  if (!instrument) return { rows: [], unmapped };

  const result: PositionLimitRow[] = [];
  const thresholdRows =
    block.scaleColumn === null
      ? []
      : group.rows
          .map((row, index) => ({ row, index, range: thresholdRange(row[block.scaleColumn!] ?? "") }))
          .filter((item): item is { row: string[]; index: number; range: PositionRange } => item.range !== null);

  for (let dateIndex = 0; dateIndex < block.dateGroups.length; dateIndex += 1) {
    const date = block.dateGroups[dateIndex];
    if (thresholdRows.length && dateIndex === 0) {
      thresholdRows.forEach(({ row, index, range }, ruleIndex) => {
        const limitRule = formatLimitRule(valueForDate(row, date, block.scaleColumn));
        if (!limitRule) return;
        result.push(makePositionRow(block, group, type, exchange, instrument, date, formatPositionRange(range), limitRule, dateIndex, ruleIndex, positionRowSourceCells(block, group, date, [group.rowIndexes[0], group.rowIndexes[index]])));
      });
      continue;
    }

    const rawLimitIndex = group.rows.findIndex((row) => formatLimitRule(valueForDate(row, date, block.scaleColumn)));
    const rawLimit = rawLimitIndex >= 0 ? valueForDate(group.rows[rawLimitIndex], date, block.scaleColumn) : "";
    const limitRule = rawLimit ? formatLimitRule(rawLimit) : null;
    if (!limitRule) continue;
    result.push(makePositionRow(block, group, type, exchange, instrument, date, DEFAULT_TOTAL_POSITION, limitRule, dateIndex, 0, positionRowSourceCells(block, group, date, [group.rowIndexes[0], group.rowIndexes[rawLimitIndex]])));
  }
  return { rows: result, unmapped };
}

function dedupeRows(rows: PositionLimitRow[]): PositionLimitRow[] {
  const unique = new Map<string, PositionLimitRow>();
  for (const row of rows) {
    const key = [row.type, row.exchange, row.instrument, row.direction, row.hedge, row.holdingDate, row.totalPosition, row.limitRule].join("|");
    const existing = unique.get(key);
    if (existing) {
      existing.sourceCells = uniqueSourceCells([...existing.sourceCells, ...row.sourceCells]);
    } else {
      unique.set(key, row);
    }
  }
  return [...unique.values()];
}

export function isPositionLimitDocument(document: Document): boolean {
  const text = allDocumentText(document);
  return (
    (text.includes("期货限仓") || text.includes("期权限仓") || text.includes("各交易所期货限仓") || (text.includes("限仓规则") && text.includes("持仓方向"))) &&
    (text.includes("持仓量") || text.includes("持仓规模") || text.includes("限仓数额"))
  );
}

export function extractPositionLimitTable(document: Document): PositionLimitTable {
  const rows: PositionLimitRow[] = [];
  const unmappedCells: string[] = [];
  for (const section of document.sections) {
    const sectionRowsValue = sectionRows(section);
    const blocks = findDateHeaders(section, sectionRowsValue);
    for (const block of blocks) {
      for (const group of productGroups(block)) {
        const parsed = rowsForProduct(block, group, document, exchangeName(section, document));
        rows.push(...parsed.rows);
        unmappedCells.push(...parsed.unmapped);
      }
    }
    if (!blocks.length) {
      const simple = simplePositionRows(section, sectionRowsValue, document, exchangeName(section, document));
      rows.push(...simple.rows);
      unmappedCells.push(...simple.unmapped);
    }
  }
  return { rows: dedupeRows(rows), unmappedCells: [...new Set(unmappedCells)] };
}
