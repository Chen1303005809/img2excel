import type { Document, Scalar, SourceCellRef } from "./types";

export type InstrumentKind = "期货" | "期权";
export type ExceptionTradeLevel = "品种级" | "合约级" | "深度虚值合约";

export interface InstrumentMapping {
  name: string;
  code: string;
  exchange: string;
  aliases: readonly string[];
  optionCode?: string;
}

export interface ExceptionTradeRow {
  id: string;
  exchange: string;
  exchangeCode: string | null;
  instrumentName: string;
  instrumentCode: string;
  openTotal: number;
  openTotalWarning: number;
  instrumentType: InstrumentKind;
  scope: "product" | "contract";
  level: ExceptionTradeLevel;
  warningOrigin: "source" | "derived_80";
  sourceText: string;
  sourceCells: SourceCellRef[];
}

export interface ExceptionTradeTable {
  rows: ExceptionTradeRow[];
  unmappedLimitCells: string[];
}

export const EXCEPTION_TRADE_HEADERS = [
  "品种所属交易所",
  "品种/合约名",
  "品种/合约代码",
  "等级",
  "开仓总量",
  "开仓总量预警",
  "是否期货/期权",
] as const;

/**
 * Static product-to-exchange/code dictionary used by the exception monitor.
 * Codes are the exchange trading symbols; contract months are appended when
 * the source cell explicitly lists contracts (for example, AG2607).
 */
export const INSTRUMENT_MAPPINGS: readonly InstrumentMapping[] = [
  // Zhengzhou Commodity Exchange
  { name: "动力煤", code: "ZC", exchange: "郑州商品交易所", aliases: ["动力煤"] },
  { name: "纯碱", code: "SA", exchange: "郑州商品交易所", aliases: ["纯碱"] },
  { name: "PTA", code: "TA", exchange: "郑州商品交易所", aliases: ["PTA"] },
  { name: "甲醇", code: "MA", exchange: "郑州商品交易所", aliases: ["甲醇"] },
  { name: "玻璃", code: "FG", exchange: "郑州商品交易所", aliases: ["玻璃"] },
  { name: "菜粕", code: "RM", exchange: "郑州商品交易所", aliases: ["菜粕", "菜籽粕"] },
  { name: "菜油", code: "OI", exchange: "郑州商品交易所", aliases: ["菜油", "菜籽油"] },
  { name: "白糖", code: "SR", exchange: "郑州商品交易所", aliases: ["白糖"] },
  { name: "棉花", code: "CF", exchange: "郑州商品交易所", aliases: ["棉花"] },
  { name: "锰硅", code: "SM", exchange: "郑州商品交易所", aliases: ["锰硅"] },
  { name: "花生", code: "PK", exchange: "郑州商品交易所", aliases: ["花生"] },
  { name: "烧碱", code: "SH", exchange: "郑州商品交易所", aliases: ["烧碱"] },
  { name: "瓶片", code: "PR", exchange: "郑州商品交易所", aliases: ["瓶片", "聚酯切片"] },
  { name: "对二甲苯", code: "PX", exchange: "郑州商品交易所", aliases: ["对二甲苯"] },
  { name: "短纤", code: "PF", exchange: "郑州商品交易所", aliases: ["短纤"] },
  { name: "硅铁", code: "SF", exchange: "郑州商品交易所", aliases: ["硅铁"] },
  { name: "尿素", code: "UR", exchange: "郑州商品交易所", aliases: ["尿素"] },
  { name: "苹果", code: "AP", exchange: "郑州商品交易所", aliases: ["苹果"] },
  { name: "红枣", code: "CJ", exchange: "郑州商品交易所", aliases: ["红枣"] },
  { name: "强麦", code: "WH", exchange: "郑州商品交易所", aliases: ["强麦"] },
  { name: "普麦", code: "PM", exchange: "郑州商品交易所", aliases: ["普麦"] },

  // Dalian Commodity Exchange
  { name: "焦煤", code: "JM", exchange: "大连商品交易所", aliases: ["焦煤"] },
  {
    name: "线型低密度聚乙烯月均价",
    code: "L",
    exchange: "大连商品交易所",
    aliases: ["线型低密度聚乙烯月均价", "LLDPE月均价"],
  },
  { name: "聚氯乙烯月均价", code: "V", exchange: "大连商品交易所", aliases: ["聚氯乙烯月均价", "PVC月均价"] },
  { name: "聚丙烯月均价", code: "PP", exchange: "大连商品交易所", aliases: ["聚丙烯月均价", "PP月均价"] },
  { name: "焦炭", code: "J", exchange: "大连商品交易所", aliases: ["焦炭"] },
  { name: "铁矿石", code: "I", exchange: "大连商品交易所", aliases: ["铁矿石"] },
  { name: "液化石油气", code: "PG", exchange: "大连商品交易所", aliases: ["液化石油气", "LPG"] },
  { name: "棕榈油", code: "P", exchange: "大连商品交易所", aliases: ["棕榈油"] },
  { name: "生猪", code: "LH", exchange: "大连商品交易所", aliases: ["生猪"] },
  { name: "豆粕", code: "M", exchange: "大连商品交易所", aliases: ["豆粕"] },
  { name: "聚氯乙烯", code: "V", exchange: "大连商品交易所", aliases: ["聚氯乙烯", "PVC"] },
  { name: "豆油", code: "Y", exchange: "大连商品交易所", aliases: ["豆油"] },
  { name: "聚丙烯", code: "PP", exchange: "大连商品交易所", aliases: ["聚丙烯"] },
  { name: "玉米", code: "C", exchange: "大连商品交易所", aliases: ["玉米"] },
  { name: "聚乙烯", code: "L", exchange: "大连商品交易所", aliases: ["聚乙烯", "线型低密度聚乙烯", "LLDPE"] },
  { name: "黄大豆1号", code: "A", exchange: "大连商品交易所", aliases: ["黄大豆1号", "豆一"] },
  { name: "黄大豆2号", code: "B", exchange: "大连商品交易所", aliases: ["黄大豆2号", "豆二"] },
  { name: "玉米淀粉", code: "CS", exchange: "大连商品交易所", aliases: ["玉米淀粉"] },
  { name: "粳米", code: "RR", exchange: "大连商品交易所", aliases: ["粳米"] },
  { name: "乙二醇", code: "EG", exchange: "大连商品交易所", aliases: ["乙二醇"] },
  { name: "苯乙烯", code: "EB", exchange: "大连商品交易所", aliases: ["苯乙烯"] },
  { name: "鸡蛋", code: "JD", exchange: "大连商品交易所", aliases: ["鸡蛋"] },
  { name: "纤维板", code: "FB", exchange: "大连商品交易所", aliases: ["纤维板"] },
  { name: "胶合板", code: "BB", exchange: "大连商品交易所", aliases: ["胶合板"] },
  { name: "原木", code: "LG", exchange: "大连商品交易所", aliases: ["原木"] },
  { name: "纯苯", code: "BZ", exchange: "大连商品交易所", aliases: ["纯苯"] },

  // Shanghai Futures Exchange
  { name: "螺纹钢", code: "RB", exchange: "上海期货交易所", aliases: ["螺纹钢"] },
  { name: "燃料油", code: "FU", exchange: "上海期货交易所", aliases: ["燃料油"] },
  { name: "白银", code: "AG", exchange: "上海期货交易所", aliases: ["白银"] },
  { name: "热轧卷板", code: "HC", exchange: "上海期货交易所", aliases: ["热轧卷板"] },
  { name: "纸浆", code: "SP", exchange: "上海期货交易所", aliases: ["纸浆"] },
  { name: "天然橡胶", code: "RU", exchange: "上海期货交易所", aliases: ["天然橡胶"] },
  { name: "铝", code: "AL", exchange: "上海期货交易所", aliases: ["铝"] },
  { name: "锌", code: "ZN", exchange: "上海期货交易所", aliases: ["锌"] },
  { name: "锡", code: "SN", exchange: "上海期货交易所", aliases: ["锡"] },
  { name: "镍", code: "NI", exchange: "上海期货交易所", aliases: ["镍"] },
  { name: "黄金", code: "AU", exchange: "上海期货交易所", aliases: ["黄金"] },
  { name: "铜", code: "CU", exchange: "上海期货交易所", aliases: ["铜", "阴极铜"] },
  { name: "铅", code: "PB", exchange: "上海期货交易所", aliases: ["铅"] },
  { name: "氧化铝", code: "AO", exchange: "上海期货交易所", aliases: ["氧化铝"] },
  { name: "铸造铝合金", code: "AD", exchange: "上海期货交易所", aliases: ["铸造铝合金"] },
  { name: "不锈钢", code: "SS", exchange: "上海期货交易所", aliases: ["不锈钢"] },
  { name: "丁二烯橡胶", code: "BR", exchange: "上海期货交易所", aliases: ["丁二烯橡胶", "合成橡胶"] },
  { name: "石油沥青", code: "BU", exchange: "上海期货交易所", aliases: ["石油沥青"] },
  { name: "胶版印刷纸", code: "OP", exchange: "上海期货交易所", aliases: ["胶版印刷纸"] },

  // Shanghai International Energy Exchange
  {
    name: "集运指数（欧线）",
    code: "EC",
    exchange: "上海国际能源交易中心",
    aliases: ["集运指数（欧线）", "集运指数(欧线)", "SCFIS欧线"],
  },
  { name: "低硫燃料油", code: "LU", exchange: "上海国际能源交易中心", aliases: ["低硫燃料油"] },
  { name: "原油", code: "SC", exchange: "上海国际能源交易中心", aliases: ["原油"] },
  { name: "20号胶", code: "NR", exchange: "上海国际能源交易中心", aliases: ["20号胶"] },
  { name: "国际铜", code: "BC", exchange: "上海国际能源交易中心", aliases: ["国际铜"] },

  // Guangzhou Futures Exchange
  { name: "工业硅", code: "SI", exchange: "广州期货交易所", aliases: ["工业硅"] },
  { name: "碳酸锂", code: "LC", exchange: "广州期货交易所", aliases: ["碳酸锂"] },
  { name: "铂", code: "PT", exchange: "广州期货交易所", aliases: ["铂"] },
  { name: "钯", code: "PD", exchange: "广州期货交易所", aliases: ["钯"] },
  { name: "多晶硅", code: "PS", exchange: "广州期货交易所", aliases: ["多晶硅"] },

  // China Financial Futures Exchange
  { name: "AF", code: "AF", exchange: "中国金融期货交易所", aliases: ["AF"] },
  { name: "沪深300", code: "IF", optionCode: "IO", exchange: "中国金融期货交易所", aliases: ["沪深300"] },
  { name: "中证500", code: "IC", exchange: "中国金融期货交易所", aliases: ["中证500"] },
  { name: "中证1000", code: "IM", optionCode: "MO", exchange: "中国金融期货交易所", aliases: ["中证1000"] },
  { name: "上证50", code: "IH", optionCode: "HO", exchange: "中国金融期货交易所", aliases: ["上证50"] },
] as const;

export const STATIC_INSTRUMENT_MAPPING: Readonly<Record<string, InstrumentMapping>> = Object.freeze(
  Object.fromEntries(INSTRUMENT_MAPPINGS.map((item) => [item.name, item])),
);

const EXCHANGE_CODE_BY_NAME: Readonly<Record<string, string>> = Object.freeze({
  "大连商品交易所": "DCE",
  "大商所": "DCE",
  "郑州商品交易所": "CZCE",
  "郑商所": "CZCE",
  "上海期货交易所": "SHFE",
  "上期所": "SHFE",
  "上海国际能源交易中心": "INE",
  "能源中心": "INE",
  "中国金融期货交易所": "CFFEX",
  "中金所": "CFFEX",
  "广州期货交易所": "GFEX",
  "广期所": "GFEX",
});

export function exchangeCodeForName(name: string): string | null {
  return EXCHANGE_CODE_BY_NAME[name.trim()] ?? null;
}

export const DEFAULT_WARNING_RATIO = 0.8;

function cellText(value: Scalar): string {
  return value === null || value === undefined ? "" : String(value);
}

function normalizeText(value: string): string {
  return value.replace(/[\s\u3000]+/g, "").replace(/：/g, ":").trim();
}

function normalizedForSearch(value: string): string {
  return normalizeText(value).toLocaleUpperCase();
}

function limitNumber(value: string): number | null {
  const normalized = value.replace(/[，,]/g, "");
  const number = Number(normalized);
  return Number.isSafeInteger(number) && number >= 0 ? number : null;
}

function warningNumber(limit: number): number {
  return Math.floor(limit * DEFAULT_WARNING_RATIO);
}

function limitValues(text: string): number[] {
  const values: number[] = [];
  for (const match of text.matchAll(/(\d[\d,]*)手/g)) {
    const value = limitNumber(match[1]);
    if (value !== null) values.push(value);
  }
  return values;
}

function splitLimitClauses(value: string): string[] {
  return normalizeText(value)
    .split(/[。；;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

interface MappingMatch {
  mapping: InstrumentMapping;
  start: number;
  length: number;
}

function resolveMappings(text: string): InstrumentMapping[] {
  const searchable = normalizedForSearch(text);
  const candidates: MappingMatch[] = [];
  for (const mapping of INSTRUMENT_MAPPINGS) {
    for (const alias of mapping.aliases) {
      const normalizedAlias = normalizedForSearch(alias);
      const start = searchable.indexOf(normalizedAlias);
      if (start >= 0) candidates.push({ mapping, start, length: normalizedAlias.length });
    }
  }

  candidates.sort((left, right) => left.start - right.start || right.length - left.length);
  const selected: MappingMatch[] = [];
  for (const candidate of candidates) {
    const overlaps = selected.some(
      (item) => candidate.start < item.start + item.length && item.start < candidate.start + candidate.length,
    );
    if (!overlaps && !selected.some((item) => item.mapping.name === candidate.mapping.name)) selected.push(candidate);
  }
  return selected.map((item) => item.mapping);
}

function explicitContractCodes(text: string, mapping: InstrumentMapping, kind: InstrumentKind): string[] {
  const acceptedPrefixes = [mapping.code, kind === "期权" ? mapping.optionCode : undefined].filter(Boolean).map((item) => item!.toLocaleUpperCase());
  if (!acceptedPrefixes.length) return [];
  const codes: string[] = [];
  for (const match of text.matchAll(/([A-Za-z]{1,3}\d{4})/g)) {
    const code = match[1].toLocaleUpperCase();
    const prefix = code.replace(/\d{4}$/, "");
    if (acceptedPrefixes.includes(prefix)) codes.push(code);
  }
  return [...new Set(codes)];
}

function monthOnlyContractCodes(text: string, mapping: InstrumentMapping): string[] {
  const searchable = normalizedForSearch(text);
  const mappingPosition = Math.min(
    ...mapping.aliases
      .map((alias) => searchable.indexOf(normalizedForSearch(alias)))
      .filter((position) => position >= 0),
    Number.POSITIVE_INFINITY,
  );
  if (!Number.isFinite(mappingPosition)) return [];

  const codes: string[] = [];
  for (const match of text.matchAll(/期货((?:\d{4}[、,，\s]*)+)/g)) {
    if ((match.index ?? Number.POSITIVE_INFINITY) < mappingPosition) continue;
    for (const month of match[1].match(/\d{4}/g) ?? []) codes.push(`${mapping.code}${month}`);
  }
  return [...new Set(codes)];
}

function codesForMapping(text: string, mapping: InstrumentMapping, kind: InstrumentKind): string[] {
  const explicit = explicitContractCodes(text, mapping, kind);
  return explicit.length ? explicit : monthOnlyContractCodes(text, mapping);
}

function defaultCodes(mapping: InstrumentMapping, kind: InstrumentKind): string {
  return kind === "期权" && mapping.optionCode ? mapping.optionCode : mapping.code;
}

function makeRow(
  mappings: InstrumentMapping[],
  codes: string[],
  openTotal: number,
  kind: InstrumentKind,
  scope: "product" | "contract",
  sourceText: string,
  sourceCells: SourceCellRef[] = [],
  level: ExceptionTradeLevel = "合约级",
): ExceptionTradeRow {
  const instrumentName = mappings.map((item) => item.name).join("、");
  const instrumentCode = [...new Set(codes)].join("、");
  const id = [mappings.map((item) => item.name).join(","), instrumentCode, openTotal, kind, level].join("|");
  return {
    id,
    exchange: mappings[0].exchange,
    exchangeCode: exchangeCodeForName(mappings[0].exchange),
    instrumentName,
    instrumentCode,
    openTotal,
    openTotalWarning: warningNumber(openTotal),
    instrumentType: kind,
    scope,
    level,
    warningOrigin: "derived_80",
    sourceText,
    sourceCells,
  };
}

function parseLimitClause(clause: string, sourceCells: SourceCellRef[] = []): ExceptionTradeRow[] {
  const values = limitValues(clause);
  if (!values.length) return [];
  const mappings = resolveMappings(clause);
  if (!mappings.length) return [];

  const kind: InstrumentKind = clause.includes("期权") ? "期权" : "期货";
  const contractCodesByMapping = mappings.map((mapping) => codesForMapping(clause, mapping, kind));
  const contractCodes = contractCodesByMapping.flat();
  const hasGeneralQualifier = /各合约|各月份合约|已上市合约|所有月份/.test(clause);
  const rows: ExceptionTradeRow[] = [];

  if (contractCodes.length && values.length > 1 && hasGeneralQualifier) {
    rows.push(
      makeRow(
        mappings,
        mappings.map((mapping) => defaultCodes(mapping, kind)),
        values[0],
        kind,
        "product",
        clause,
        sourceCells,
      ),
    );
    rows.push(makeRow(mappings, contractCodes, values[values.length - 1], kind, "contract", clause, sourceCells));
    return rows;
  }

  if (contractCodes.length) {
    rows.push(makeRow(mappings, contractCodes, values[values.length - 1], kind, "contract", clause, sourceCells));
    return rows;
  }

  rows.push(
    makeRow(
      mappings,
      mappings.map((mapping) => defaultCodes(mapping, kind)),
      values[0],
      kind,
      "product",
      clause,
      sourceCells,
    ),
  );
  return rows;
}

function exactInteger(value: Scalar): number | null {
  const text = cellText(value).replace(/[，,\s]/g, "");
  return /^\d+$/.test(text) ? limitNumber(text) : null;
}

function documentRows(document: Document): Scalar[][] {
  return document.sections.flatMap((section) => section.cells);
}

interface CffexLimits {
  future: number;
  optionProduct: number;
  optionContract: number;
  optionDeepOutOfMoney: number;
}

function cffexLimits(document: Document): CffexLimits {
  const limits: CffexLimits = {
    future: 500,
    optionProduct: 200,
    optionContract: 100,
    optionDeepOutOfMoney: 30,
  };
  const rows = documentRows(document);
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const header = rows[rowIndex].map(cellText);
    const futureColumn = header.findIndex((value) => value.includes("某一合约"));
    const optionProductColumn = header.findIndex((value) => value.includes("品种合计"));
    const optionContractColumn = header.findIndex((value) => value.includes("单个月份期权合约"));
    const optionDeepOutOfMoneyColumn = header.findIndex((value) => value.includes("深度虚值合约"));
    if (futureColumn < 0 && optionProductColumn < 0 && optionContractColumn < 0 && optionDeepOutOfMoneyColumn < 0) continue;
    for (const valueRow of rows.slice(rowIndex + 1, rowIndex + 4)) {
      const future = futureColumn >= 0 ? exactInteger(valueRow[futureColumn]) : null;
      const optionProduct = optionProductColumn >= 0 ? exactInteger(valueRow[optionProductColumn]) : null;
      const optionContract = optionContractColumn >= 0 ? exactInteger(valueRow[optionContractColumn]) : null;
      const optionDeepOutOfMoney = optionDeepOutOfMoneyColumn >= 0 ? exactInteger(valueRow[optionDeepOutOfMoneyColumn]) : null;
      if (future !== null) limits.future = future;
      if (optionProduct !== null) limits.optionProduct = optionProduct;
      if (optionContract !== null) limits.optionContract = optionContract;
      if (optionDeepOutOfMoney !== null) limits.optionDeepOutOfMoney = optionDeepOutOfMoney;
    }
  }
  return limits;
}

function cffexRows(document: Document): ExceptionTradeRow[] {
  const cells = document.sections.flatMap((section) => section.cells.flatMap((row, rowIndex) => row.map((value, column) => ({
    value: cellText(value),
    ref: { sectionId: section.id, row: rowIndex, column },
  }))));
  const text = cells.map((cell) => cell.value).join(" ");
  if (!text.includes("股指期货") && !text.includes("股指期权")) return [];

  const cffexSectionIds = new Set(
    cells.filter((cell) => cell.value.includes("股指期货") || cell.value.includes("股指期权")).map((cell) => cell.ref.sectionId),
  );
  const cffexSourceCells = cells.filter((cell) => cffexSectionIds.has(cell.ref.sectionId)).map((cell) => cell.ref);

  const { future: futureLimit, optionProduct, optionContract, optionDeepOutOfMoney } = cffexLimits(document);

  const rows: ExceptionTradeRow[] = [];
  const cffex = STATIC_INSTRUMENT_MAPPING;
  const futureNames = ["沪深300", "中证500", "中证1000", "上证50"];
  const optionNames = ["沪深300", "中证1000", "上证50"];
  if (text.includes("股指期货")) {
    const mappings = futureNames.map((name) => cffex[name]);
    rows.push(
      makeRow(
        mappings,
        mappings.map((mapping) => mapping.code),
        futureLimit,
        "期货",
        "product",
        "股指期货（沪深300、中证500、中证1000、上证50股指期货）",
        cffexSourceCells,
        "合约级",
      ),
    );
  }
  if (text.includes("股指期权")) {
    const mappings = optionNames.map((name) => cffex[name]);
    rows.push(
      makeRow(
        mappings,
        mappings.map((mapping) => mapping.optionCode ?? mapping.code),
        optionProduct,
        "期权",
        "product",
        "股指期权（沪深300、中证1000、上证50股指期权）",
        cffexSourceCells,
        "品种级",
      ),
      makeRow(
        mappings,
        mappings.map((mapping) => mapping.optionCode ?? mapping.code),
        optionContract,
        "期权",
        "contract",
        "股指期权（沪深300、中证1000、上证50股指期权）",
        cffexSourceCells,
        "合约级",
      ),
      makeRow(
        mappings,
        mappings.map((mapping) => mapping.optionCode ?? mapping.code),
        optionDeepOutOfMoney,
        "期权",
        "contract",
        "股指期权（沪深300、中证1000、上证50股指期权）",
        cffexSourceCells,
        "深度虚值合约",
      ),
    );
  }
  return rows;
}

function rowKey(row: ExceptionTradeRow): string {
  return [row.exchange, row.instrumentName, row.instrumentCode, row.openTotal, row.instrumentType, row.level].join("|");
}

export function isExceptionMonitoringDocument(document: Document): boolean {
  const title = normalizeText(document.title);
  const cellContent = documentRows(document).flat().map(cellText).join(" ");
  const text = `${title} ${cellContent}`;
  return text.includes("异常交易") && (text.includes("交易限额") || text.includes("开仓交易"));
}

export function extractExceptionTradeTable(document: Document): ExceptionTradeTable {
  const rows: ExceptionTradeRow[] = [];
  const unmappedLimitCells: string[] = [];

  for (const section of document.sections) {
    for (let rowIndex = 0; rowIndex < section.cells.length; rowIndex += 1) {
      const row = section.cells[rowIndex];
      for (let column = 0; column < row.length; column += 1) {
        const sourceText = cellText(row[column]);
        if (!sourceText.includes("手") || (!sourceText.includes("开仓") && !sourceText.includes("交易限额"))) continue;
        const clauses = splitLimitClauses(sourceText);
        const sourceCells = [{ sectionId: section.id, row: rowIndex, column }];
        for (const clause of clauses) {
          const parsed = parseLimitClause(clause, sourceCells);
          if (!parsed.length && limitValues(clause).length) unmappedLimitCells.push(clause);
          rows.push(...parsed);
        }
      }
    }
  }

  rows.push(...cffexRows(document));
  const uniqueRows = new Map<string, ExceptionTradeRow>();
  for (const row of rows) {
    const key = rowKey(row);
    const existing = uniqueRows.get(key);
    if (existing) {
      existing.sourceCells = [...new Map([...existing.sourceCells, ...row.sourceCells].map((cell) => [
        cell.sectionId + ":" + cell.row + ":" + cell.column,
        cell,
      ])).values()];
    } else {
      uniqueRows.set(key, row);
    }
  }
  return { rows: [...uniqueRows.values()], unmappedLimitCells: [...new Set(unmappedLimitCells)] };
}

export function extractExceptionTradeRows(document: Document): ExceptionTradeRow[] {
  return extractExceptionTradeTable(document).rows;
}
