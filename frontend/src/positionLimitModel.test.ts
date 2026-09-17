import { describe, expect, it } from "vitest";
import { extractPositionLimitTable, isPositionLimitDocument } from "./positionLimitModel";
import type { Document, TableSection } from "./types";

function section(id: string, label: string, cells: string[][], merged_cells: TableSection["merged_cells"] = []): TableSection {
  return {
    id,
    label,
    bbox: [],
    x_edges: [0, 1, 2, 3, 4, 5],
    y_edges: cells.map((_, index) => index),
    cells,
    merged_cells,
    ocr_count: 0,
    ocr_avg_score: null,
    ocr_low_score_count: 0,
    strategy: "opencv_grid",
  };
}

function fixtureDocument(): Document {
  return {
    version: 2,
    source: {},
    title: "各交易所期货限仓汇编",
    bands: [],
    sections: [
      section(
        "T01",
        "T01 大连商品交易所",
        [
          ["", "合约上市至交割月前一个月第十四个交易日", "", "交割月前一个月第十五个交易日起", "交割月"],
          ["", "合约单边持仓规模", "限仓", "限仓数额（手）", "限仓数额（手）"],
          ["聚氯乙烯\n聚丙烯\n聚乙烯", ">20万手", "0.08", "4000", "2500"],
          ["", "≤20万手", "16000", "", ""],
        ],
        [
          { r0: 0, r1: 0, c0: 1, c1: 2, value: "合约上市至交割月前一个月第十四个交易日" },
          { r0: 1, r1: 1, c0: 1, c1: 1, value: "合约单边持仓规模" },
          { r0: 2, r1: 3, c0: 0, c1: 0, value: "聚氯乙烯\n聚丙烯\n聚乙烯" },
        ],
      ),
      section(
        "T02",
        "T02 郑州商品交易所",
        [
          ["", "自合约挂牌至交割月前一个月第15个日历日期间的交易日", "", "交割月前一个月第16个日历日至交割月前一个月最后一个日历日期间的交易日", "交割月"],
          ["", "单边持仓量X", "客户单边最大持仓", "客户单边最大持仓", "客户单边最大持仓"],
          ["FTA", "X<50万", "50000", "10000", "5000"],
          ["", "x≥50万", "0.1", "", ""],
          ["尿素", "", "5000", "1000", "300"],
        ],
        [{ r0: 0, r1: 0, c0: 1, c1: 2, value: "自合约挂牌至交割月前一个月第15个日历日期间的交易日" }],
      ),
    ],
    colored_notes: [],
    footer_notes: [],
    ocr_boxes: [],
    corrections: [],
    metrics: {},
  };
}

describe("position limit table", () => {
  it("recognizes the position-limit document and derives exchange names", () => {
    const table = extractPositionLimitTable(fixtureDocument());
    expect(isPositionLimitDocument(fixtureDocument())).toBe(true);
    expect(table.rows.length).toBeGreaterThan(5);
    expect(table.unmappedCells).toEqual([]);
    expect(table.rows.some((row) => row.exchange === "大连商品交易所" && row.instrument === "V、PP、L")).toBe(true);
    expect(table.rows.some((row) => row.exchange === "郑州商品交易所" && row.instrument === "TA")).toBe(true);
  });

  it("keeps threshold ranges and percentage rules as separate rows", () => {
    const table = extractPositionLimitTable(fixtureDocument());
    const taRows = table.rows.filter((row) => row.exchange === "郑州商品交易所" && row.instrument === "TA");
    expect(taRows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ totalPosition: "0<=持仓量<500000", limitRule: "固定值50000" }),
        expect.objectContaining({ totalPosition: "500000<=持仓量<+∞", limitRule: "百分比10%" }),
        expect.objectContaining({ totalPosition: "0<=持仓量<+∞", limitRule: "固定值10000" }),
        expect.objectContaining({ totalPosition: "0<=持仓量<+∞", limitRule: "固定值5000" }),
      ]),
    );
  });

  it("does not classify an exception-monitoring document as position limits", () => {
    const document = fixtureDocument();
    document.title = "各交易所异常交易监管阈值";
    document.sections = [];
    expect(isPositionLimitDocument(document)).toBe(false);
  });

  it("supports compact option-limit tables without date header rows", () => {
    const document = fixtureDocument();
    document.title = "各交易所期权限仓汇编";
    document.bands = [{ text: "限仓数额（手）" }];
    document.sections = [
      section("T01", "T01 大连商品交易所", [["丙烯期权", "40000"]]),
      section("T02", "T02 中国金融期货交易所", [["沪深300股指期权", "5000"]]),
    ];
    const table = extractPositionLimitTable(document);
    expect(table.rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: "期权", exchange: "大连商品交易所", instrument: "PX", limitRule: "固定值40000" }),
        expect.objectContaining({ type: "期权", exchange: "中国金融期货交易所", instrument: "IO", limitRule: "固定值5000" }),
      ]),
    );
  });
});
