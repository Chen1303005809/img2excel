import { describe, expect, it } from "vitest";
import { DEFAULT_WARNING_RATIO, extractExceptionTradeTable, isExceptionMonitoringDocument, STATIC_INSTRUMENT_MAPPING } from "./exceptionTradeModel";
import type { Document } from "./types";

function makeDocument(cells: Array<Array<string | number | null>>): Document {
  return {
    version: 2,
    source: {},
    title: "各交易所异常交易监管阈值（2026.07.14）",
    bands: [],
    sections: [{
      id: "T01",
      label: "",
      bbox: [],
      x_edges: Array.from({ length: 8 }, (_, index) => index),
      y_edges: Array.from({ length: cells.length + 1 }, (_, index) => index),
      cells,
      merged_cells: [],
      ocr_count: 0,
      ocr_avg_score: null,
      ocr_low_score_count: 0,
      strategy: "line_grid",
    }],
    colored_notes: [],
    footer_notes: [],
    ocr_boxes: [],
    corrections: [],
    metrics: {},
  };
}

describe("exception trade table view model", () => {
  it("uses the static mapping to expand product and listed contract codes", () => {
    const result = extractExceptionTradeTable(makeDocument([
      ["郑商所", "动力煤期货2607、2608、2701合约上单日开仓交易的最大数量为20手"],
      ["大商所", "聚氯乙烯月均价期货各合约的交易限额为18000手"],
      ["上期所", "白银期货各合约的日内开仓交易的最大数量为7000手。白银期货AG2607、AG2608合约的日内开仓交易的最大数量为800手"],
    ]));

    expect(result.unmappedLimitCells).toEqual([]);
    expect(result.rows).toEqual(expect.arrayContaining([
      expect.objectContaining({
        exchange: "郑州商品交易所",
        instrumentName: "动力煤",
        instrumentCode: "ZC2607、ZC2608、ZC2701",
        openTotal: 20,
        openTotalWarning: 16,
        instrumentType: "期货",
        scope: "contract",
      }),
      expect.objectContaining({
        exchange: "大连商品交易所",
        instrumentName: "聚氯乙烯月均价",
        instrumentCode: "V",
        openTotal: 18000,
        openTotalWarning: 14400,
        scope: "product",
      }),
      expect.objectContaining({ instrumentName: "白银", instrumentCode: "AG", openTotal: 7000, scope: "product" }),
      expect.objectContaining({ instrumentName: "白银", instrumentCode: "AG2607、AG2608", openTotal: 800, scope: "contract" }),
    ]));
  });

  it("adds the two CFFEX rows whose limits are represented by a numeric subtable", () => {
    const result = extractExceptionTradeTable(makeDocument([
      ["中金所", "股指期货（沪深300、中证500、中证1000、上证50股指期货）"],
      ["", "股指期权（沪深300、中证1000、上证50股指期权）"],
      ["", "某一合约", "品种合计", "单个月份期权合约", "深度虚值合约"],
      ["", 500, 200, 100, 30],
    ]));

    expect(result.rows).toEqual(expect.arrayContaining([
      expect.objectContaining({ instrumentName: "沪深300、中证500、中证1000、上证50", instrumentCode: "IF、IC、IM、IH", openTotal: 500, instrumentType: "期货" }),
      expect.objectContaining({ instrumentName: "沪深300、中证1000、上证50", instrumentCode: "IO、MO、HO", openTotal: 100, instrumentType: "期权" }),
    ]));
  });

  it("maps every limit product in the July sample without dropping a cell", () => {
    const limitCells = [
      "动力煤期货2607、2608、2609、2610、2611、2612、2701、2702、2703、2704、2705、2706、2707合约上单日开仓交易的最大数量为20手。",
      "纯碱期货各合约上单日开仓交易的最大数量为10000手。",
      "PTA期货各合约上单日开仓交易的最大数量为30000手。",
      "甲醇期货各合约上单日开仓交易的最大数量为25000手。",
      "玻璃期货各合约上单日开仓交易的最大数量为25000手。",
      "菜粕期货各合约上单日开仓交易的最大数量为15000手。",
      "菜油期货各合约上单日开仓交易的最大数量为10000手。",
      "白糖期货各合约上单日开仓交易的最大数量为10000手。",
      "棉花期货各合约上单日开仓交易的最大数量为10000手。",
      "锰硅期货各合约上单日开仓交易的最大数量为10000手。",
      "焦煤期货各合约上单日开仓量不得超过2,000手。",
      "线型低密度聚乙烯月均价期货各合约的交易限额为8000手。",
      "聚氯乙烯月均价期货各合约的交易限额为18000手。",
      "聚丙烯月均价期货各合约的交易限额为10000手。",
      "焦炭期货各月份合约单日开仓量不得超过500手。",
      "铁矿石期货合约上单日开仓量不得超过2,000手。",
      "液化石油气期货各月份合约上单日开仓量不得超过10,000手。",
      "棕榈油期货各月份合约上单日开仓量不得超过10,000手。",
      "生猪期货各月份合约上单日开仓量不得超过1,000手。",
      "豆粕期货各月份合约上单日开仓量不得超过20,000手。",
      "聚氯乙烯期货各月份合约上单日开仓量不得超过18,000手。",
      "豆油期货各月份合约上单日开仓量不得超过15,000手。",
      "聚丙烯期货各月份合约上单日开仓量不得超过10,000手。",
      "玉米期货各月份合约上单日开仓量不得超过8,000手。",
      "聚乙烯期货各月份合约上单日开仓量不得超过8,000手。",
      "螺纹钢期货各月份合约上单日开仓量不得超过32,000手。",
      "燃料油期货各合约的日内开仓交易的最大数量为1500手。燃料油期货FU2608、FU2609、FU2610、FU2611、FU2612、FU2701、FU2702、FU2703、FU2704、FU2705、FU2706合约及后续新上市合约的日内开仓交易的最大数量为6000手。",
      "白银期货各合约的日内开仓交易的最大数量为7000手。白银期货AG2607、AG2608、AG2609、AG2610、AG2611、AG2612、AG2701合约的日内开仓交易的最大数量为800手。",
      "热轧卷板期货各月份合约上单日开仓量不得超过10,000手。",
      "纸浆期货各月份合约上单日开仓量不得超过8,000手。",
      "天然橡胶期货各月份合约上单日开仓量不得超过6,000手。",
      "铝期货各月份合约上单日开仓量不得超过4,000手。",
      "锌期货各月份合约上单日开仓量不得超过3,000手。",
      "锡期货各合约的日内开仓交易的最大数量为800手。锡期货SN2607、SN2608、SN2609、SN2610、SN2611、SN2612、SN2701合约的日内开仓交易的最大数量为200手。",
      "镍期货NI2607、NI2608、NI2609、NI2610、NI2611、NI2612、NI2701合约的日内开仓交易的最大数量为2500手。",
      "黄金期货各月份合约上单日开仓量不得超过2800手。",
      "铜期货各月份合约上单日开仓量不得超过2000手。",
      "集运指数（欧线）期货已上市合约的日内开仓交易的最大数量为50手。",
      "低硫燃料油期货各合约的日内开仓交易的最大数量为1500手。低硫燃料油期货LU2608、LU2609、LU2610、LU2611、LU2612、LU2701、LU2702、LU2703、LU2704、LU2705、LU2706合约及后续新上市合约的日内开仓交易的最大数量为6000手。",
      "原油期货各合约的日内开仓交易的最大数量为400手。原油期货SC2608、SC2609、SC2610、SC2611、SC2612、SC2701、SC2702、SC2703、SC2704、SC2705、SC2706、SC2709、SC2712、SC2803、SC2806、SC2809、SC2812、SC2903、SC2906合约及后续新上市合约的日内开仓交易的最大数量为1600手。",
      "工业硅期货各合约上单日开仓量不得超过10000手。",
      "碳酸锂期货各合约上单日开仓量不得超过10,000手。在碳酸锂期货LC2607、LC2608、LC2609、LC2610、LC2611、LC2612、LC2701、LC2702、LC2703、LC2704、LC2705、LC2706、LC2707合约上单日开仓量分别不得超过400手。",
      "铂期货PT2608、PT2610、PT2612、PT2702合约上单日开仓量分别不得超过300手。",
      "钯期货PD2608、PD2610、PD2612、PD2702合约上单日开仓量分别不得超过300手。",
      "多晶硅期货各合约上单日开仓量不得超过10000手。多晶硅期货PS2607、PS2608、PS2609、PS2610、PS2611、PS2612、PS2701、PS2702、PS2703、PS2704、PS2705、PS2706、PS2707合约上单日开仓量分别不得超过200手。",
    ];
    const result = extractExceptionTradeTable(makeDocument(limitCells.map((cell) => ["", cell])));

    expect(result.unmappedLimitCells).toEqual([]);
    expect(result.rows).toHaveLength(52);
    expect(result.rows.find((row) => row.instrumentCode === "SC")).toMatchObject({ openTotal: 400, openTotalWarning: 320 });
    expect(result.rows.find((row) => row.instrumentCode === "PS2607、PS2608、PS2609、PS2610、PS2611、PS2612、PS2701、PS2702、PS2703、PS2704、PS2705、PS2706、PS2707")?.openTotal).toBe(200);
  });

  it("recognizes exception documents without relying on OCR section labels", () => {
    expect(isExceptionMonitoringDocument(makeDocument([["交易所", "交易限额"]]))).toBe(true);
    expect(STATIC_INSTRUMENT_MAPPING["动力煤"].code).toBe("ZC");
    expect(DEFAULT_WARNING_RATIO).toBe(0.8);
  });
});
