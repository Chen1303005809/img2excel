# 中国期货市场品种、合约代码与交易所静态映射研究记录

- 研究日期：2026-09-17（Asia/Shanghai）
- 研究目的：为本项目的“交易限额/异常交易监控”提供品种、合约代码、交易所及期货/期权属性的静态身份映射。
- 资料范围：只采用中国境内相关交易所官网的品种页、交易规则、合约资料、官方统计/业务报告等一手来源。
- 重要边界：本文件不是当前交易限额、客户限仓或异常交易阈值表。阈值、适用月份、客户类型和交易关系可能随交易所公告动态变化，执行监控前仍应读取对应交易所最新规则/通知。

## 1. 本仓库 OCR/Excel 优先范围

本次优先从以下已有 OCR/Excel 数据提取品种名，再做官方映射核验：

- [outputs/表4期权限仓.xlsx](outputs/表4期权限仓.xlsx)
- [outputs/表4期权限仓20260609.xlsx](outputs/表4期权限仓20260609.xlsx)
- [outputs/表6异常交易20260415.xlsx](outputs/表6异常交易20260415.xlsx)
- [outputs/表6异常交易20260714.xlsx](outputs/表6异常交易20260714.xlsx)

本地表格中的中文品种名仅用于确定优先级，不作为代码或交易所的权威来源。OCR 中存在“PVC/聚氯乙烯”“丁二烯橡胶/合成橡胶”“集运指数（欧线）/SCFIS 欧线”等显示差异，已在下表或“不确定项”中标注。

## 2. 代码形态约定

- 期货合约通常由“官方品种代码前缀 + 到期年月 YYMM”组成，例如 `M2609`；不同行情接口可能去掉连字符或使用小写。
- 期权在交易所资料中通常表示为“标的代码-YYMM-C/P-行权价”，例如 `IO-YYMM-C/P-EP`；实际行情字段可能采用无连字符形式。`C/P` 分别表示看涨/看跌，`EP` 表示行权价。
- 下面的“常见完整代码形态”是解析/归一化提示，不是对某一时点全部可交易月份的枚举。

## 3. 逐项静态映射

### 3.1 大连商品交易所（DCE）

大商所官方资料通常按合约说明书、业务细则或品种月报分散发布；玉米资料明确给出期货代码 `C` 及期权代码形态，焦煤/焦炭资料明确给出 `JM`/`J`，生猪、聚丙烯、PVC、LLDPE、玉米淀粉和纯苯资料分别用于交叉核对。对没有单独列出代码的行，仍链接交易所官方资料，并在第 4 节说明复核要求。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 豆粕 | `M` | 期货；期权（本地表4命中） | `M+YYMM`；`M-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 玉米 | `C` | 期货；期权（本地表4命中） | `C+YYMM`；`C-YYMM-C/P-EP` | DCE | [玉米期货和期权宣传页（大商所）](https://www.dce.com.cn/dalianshangpin/resource/cms/article/8536039/489773/240219%E7%8E%89%E7%B1%B3%E6%9C%9F%E8%B4%A7%E5%92%8C%E6%9C%9F%E6%9D%83%E5%AE%A3%E4%BC%A0%E9%A1%B5.pdf) |
| 铁矿石 | `I` | 期货；期权（本地表4/表6命中） | `I+YYMM`；`I-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 液化石油气 | `PG` | 期货；期权（本地表4/表6命中） | `PG+YYMM`；`PG-YYMM-C/P-EP` | DCE | [大商所官方品种资料/统计报告](https://www.dce.com.cn/dalianshangpin/resource/cms/2020/11/2020111209380878948.pdf) |
| 乙二醇 | `EG` | 期货；期权（本地表4命中） | `EG+YYMM`；`EG-YYMM-C/P-EP` | DCE | [大商所官方品种资料/统计报告](https://www.dce.com.cn/dalianshangpin/resource/cms/2020/11/2020111209380878948.pdf) |
| 焦煤 | `JM` | 期货；期权（本地表4/表6命中） | `JM+YYMM`；`JM-YYMM-C/P-EP` | DCE | [焦煤、焦炭官方合约资料（大商所）](https://www.dce.com.cn/dce/file/2026-01-15/17684624156122c9a882b9ae6dcbb289019bc092f6fc1681.pdf) |
| 焦炭 | `J` | 期货；期权（本地表6命中） | `J+YYMM`；`J-YYMM-C/P-EP` | DCE | [焦炭期货业务细则（大商所）](https://www.dce.com.cn/dalianshangpin/fgfz/6142914/6142926/6263837/%E5%A4%A7%E8%BF%9E%E5%95%86%E5%93%81%E4%BA%A4%E6%98%93%E6%89%80%E7%84%A6%E7%82%AD%E6%9C%9F%E8%B4%A7%E4%B8%9A%E5%8A%A1%E7%BB%86%E5%88%99%EF%BC%88%E6%A0%B9%E6%8D%AE2025%E5%B9%B41%E6%9C%8824%E6%97%A5%E3%80%942025%E3%80%956%E5%8F%B7%E6%96%87%E4%BB%B6%E4%BF%AE%E6%94%B9%EF%BC%89.pdf) |
| 聚丙烯 | `PP` | 期货；期权（本地表4/表6命中） | `PP+YYMM`；`PP-YYMM-C/P-EP` | DCE | [聚丙烯期货业务细则（大商所）](https://www.dce.com.cn/dalianshangpin/fgfz/6142914/6142926/6146588/%E5%A4%A7%E8%BF%9E%E5%95%86%E5%93%81%E4%BA%A4%E6%98%93%E6%89%80%E8%81%9A%E4%B8%99%E7%83%AF%E6%9C%9F%E8%B4%A7%E4%B8%9A%E5%8A%A1%E7%BB%86%E5%88%99%EF%BC%88%E6%A0%B9%E6%8D%AE2024%E5%B9%B411%E6%9C%881%E6%97%A5%E3%80%942024%E3%80%95102%E5%8F%B7%E6%96%87%E4%BB%B6%E4%BF%AE%E6%94%B9%EF%BC%89.pdf) |
| 聚氯乙烯（本地 OCR 常写 PVC） | `V` | 期货；期权（本地表4/表6命中） | `V+YYMM`；`V-YYMM-C/P-EP` | DCE | [聚氯乙烯官方品种资料（大商所）](https://www.dce.com.cn/dalianshangpin/resource/cms/article/489932/6304829/2022022411172265649.pdf) |
| 黄大豆2号 | `B` | 期货；期权（本地表4命中） | `B+YYMM`；`B-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 豆油 | `Y` | 期货；期权（本地表4/表6命中） | `Y+YYMM`；`Y-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 聚乙烯（线型低密度聚乙烯，LLDPE） | `L` | 期货；期权（本地表4/表6命中） | `L+YYMM`；`L-YYMM-C/P-EP` | DCE | [LLDPE 官方品种月报（大商所）](https://www.dce.com.cn/dalianshangpin/resource/cms/article/489932/6298011/2021112611121813413.pdf) |
| 棕榈油 | `P` | 期货；期权（本地表4/表6命中） | `P+YYMM`；`P-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 黄大豆1号 | `A` | 期货；期权（本地表4命中） | `A+YYMM`；`A-YYMM-C/P-EP` | DCE | [大商所官方品种/合约资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 玉米淀粉 | `CS` | 期货；期权（本地表4命中） | `CS+YYMM`；`CS-YYMM-C/P-EP` | DCE | [玉米淀粉期货合约设计说明（大商所）](https://www.dce.com.cn/dalianshangpin/resource/cms/2016/11/%E7%8E%89%E7%B1%B3%E6%B7%80%E7%B2%89%E6%9C%9F%E8%B4%A7%E5%90%88%E7%BA%A6%E8%AE%BE%E8%AE%A1%E8%AF%B4%E6%98%8E.pdf) |
| 苯乙烯 | `EB` | 期货；期权（本地表4命中） | `EB+YYMM`；`EB-YYMM-C/P-EP` | DCE | [大商所官方品种/统计资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2020/11/2020111209380878948.pdf) |
| 鸡蛋 | `JD` | 期货；期权（本地表4命中） | `JD+YYMM`；`JD-YYMM-C/P-EP` | DCE | [大商所官方品种/统计资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2019/04/2019042612023697006.pdf) |
| 生猪 | `LH` | 期货；期权（本地表4/表6命中） | `LH+YYMM`；`LH-YYMM-C/P-EP` | DCE | [生猪期货业务细则（大商所）](https://www.dce.com.cn/dalianshangpin/fgfz/6142914/6142926/6262877/%E5%A4%A7%E8%BF%9E%E5%95%86%E5%93%81%E4%BA%A4%E6%98%93%E6%89%80%E7%94%9F%E7%8C%AA%E6%9C%9F%E8%B4%A7%E4%B8%9A%E5%8A%A1%E7%BB%86%E5%88%99%EF%BC%88%E6%A0%B9%E6%8D%AE2025%E5%B9%B46%E6%9C%8824%E6%97%A5%E3%80%942025%E3%80%9559%E5%8F%B7%E6%96%87%E4%BB%B6%E4%BF%AE%E6%94%B9%EF%BC%89.pdf) |
| 原木 | `LG` | 期货；期权（本地表4命中） | `LG+YYMM`；`LG-YYMM-C/P-EP` | DCE | [大商所官方品种/统计资料](https://www.dce.com.cn/dalianshangpin/resource/cms/2020/11/2020111209380878948.pdf) |
| 纯苯 | `BZ` | 期货；期权（本地表4命中） | `BZ+YYMM`；`BZ-YYMM-C/P-EP` | DCE | [纯苯期货、期权官方资料（大商所）](https://www.dce.com.cn/qhxy/file/2025-08-05/17543892971982c9a882b9879b789653019879c0382e003d.pdf) |

### 3.2 郑州商品交易所（ZCE）

郑商所 2026 年 3 月官方月报直接给出当前主要品种代码；2025 年官方品种清单同时列出期货和期权品种覆盖。以下以本地 OCR/Excel 命中的品种为主。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 白糖 | `SR` | 期货；期权（本地表4/表6命中） | `SR+YYMM`；`SR-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 棉花 | `CF` | 期货；期权（本地表4/表6命中） | `CF+YYMM`；`CF-YYMM-C/P-EP` | ZCE | [棉花期货业务细则（郑商所）](https://www.czce.com.cn/cn/flfg/zcjywgz/pzxz/webinfo/2024/02/1708568084281851.htm) |
| PTA | `TA` | 期货；期权（本地表4/表6命中） | `TA+YYMM`；`TA-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 甲醇 | `MA` | 期货；期权（本地表4/表6命中） | `MA+YYMM`；`MA-YYMM-C/P-EP` | ZCE | [郑商所甲醇代码变更公告](https://www.czce.com.cn/cn/rootfiles/2014/06/13/1402482218856803-1402482218858971.pdf) |
| 动力煤 | `ZC` | 期货；期权（本地表4/表6命中） | `ZC+YYMM`；`ZC-YYMM-C/P-EP` | ZCE | [动力煤期货业务细则（郑商所）](https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/pzxz/2025/10/cf887b5b1a904caeb0be8fe72e8bd1ac.pdf) |
| 菜籽粕 | `RM` | 期货；期权（本地表4/表6命中） | `RM+YYMM`；`RM-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 菜籽油 | `OI` | 期货；期权（本地表4/表6命中） | `OI+YYMM`；`OI-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 花生 | `PK` | 期货；期权（本地表4命中） | `PK+YYMM`；`PK-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 烧碱 | `SH` | 期货；期权（本地表4命中） | `SH+YYMM`；`SH-YYMM-C/P-EP` | ZCE | [烧碱期货业务细则（郑商所）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 瓶片（聚酯切片） | `PR` | 期货；期权（本地表4命中） | `PR+YYMM`；`PR-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 对二甲苯 | `PX` | 期货；期权（本地表4命中） | `PX+YYMM`；`PX-YYMM-C/P-EP` | ZCE | [对二甲苯期货业务细则（郑商所）](https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/pzxz/2026/5/c1e9fa9be1094fd5b913f69c5b51be5f.pdf) |
| 短纤 | `PF` | 期货；期权（本地表4命中） | `PF+YYMM`；`PF-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 硅铁 | `SF` | 期货；期权（本地表4命中） | `SF+YYMM`；`SF-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 尿素 | `UR` | 期货；期权（本地表4命中） | `UR+YYMM`；`UR-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 纯碱 | `SA` | 期货；期权（本地表4/表6命中） | `SA+YYMM`；`SA-YYMM-C/P-EP` | ZCE | [纯碱期货业务细则（郑商所）](https://www.czce.com.cn/cn/uploadfile/2023/05/15/20230515110954123.pdf) |
| 锰硅 | `SM` | 期货；期权（本地表4/表6命中） | `SM+YYMM`；`SM-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 苹果 | `AP` | 期货；期权（本地表4命中） | `AP+YYMM`；`AP-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 玻璃 | `FG` | 期货；期权（本地表4/表6命中） | `FG+YYMM`；`FG-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 红枣 | `CJ` | 期货；期权（本地表4命中） | `CJ+YYMM`；`CJ-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |
| 丙烯 | `PL` | 期货；期权（本地表4命中） | `PL+YYMM`；`PL-YYMM-C/P-EP` | ZCE | [郑商所2026年3月月报（代码表）](https://www.czce.com.cn/cn/content_file/jysj/ydscbg/2026/3/d2fcd9faa7834956874967667f0e8dfe.pdf) |

### 3.3 上海期货交易所（SHFE）

上期所官网产品清单覆盖下列期货/期权品种；2026 年官方交易所新闻资料给出了多组当前合约代码示例。`BC`、`NR`、`SC`、`LU`、`EC` 等国际能源交易中心品种虽然出现在上期所网站导航中，但应归属于 INE，已单列在下一节。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 铜 | `CU` | 期货；期权（本地表4/表6命中） | `CU+YYMM`；`CU-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 铝 | `AL` | 期货；期权（本地表4/表6命中） | `AL+YYMM`；`AL-YYMM-C/P-EP` | SHFE | [铝、锌期权专题（上期所）](https://www.shfe.com.cn/content/2020_al_zn_option/index.html) |
| 锌 | `ZN` | 期货；期权（本地表4/表6命中） | `ZN+YYMM`；`ZN-YYMM-C/P-EP` | SHFE | [锌期货业务规则（上期所）](https://www.shfe.com.cn/regulation/exchangerules/historicalversion/202508/t20250807_828530.html) |
| 铅 | `PB` | 期货；期权（本地表4命中） | `PB+YYMM`；`PB-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/) |
| 镍 | `NI` | 期货；期权（本地表4/表6命中） | `NI+YYMM`；`NI-YYMM-C/P-EP` | SHFE | [2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 锡 | `SN` | 期货；期权（本地表4/表6命中） | `SN+YYMM`；`SN-YYMM-C/P-EP` | SHFE | [2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 氧化铝 | `AO` | 期货；期权（本地表4命中） | `AO+YYMM`；`AO-YYMM-C/P-EP` | SHFE | [氧化铝期货合约（上期所）](https://www.shfe.com.cn/products/futures/metal/nonferrousmetal/ao_f/standard_ao_f/202312/t20231205_330053.html) |
| 铸造铝合金 | `AD` | 期货；期权（本地表4命中） | `AD+YYMM`；`AD-YYMM-C/P-EP` | SHFE | [铸造铝合金期货业务规则（上期所）](https://www.shfe.com.cn/regulation/exchangerules/historicalversion/202508/t20250807_828539.html) |
| 黄金 | `AU` | 期货；期权（本地表4命中） | `AU+YYMM`；`AU-YYMM-C/P-EP` | SHFE | [黄金期货业务规则（上期所）](https://www.shfe.com.cn/regulation/exchangerules/productrules/202512/t20251231_829960.html) |
| 白银 | `AG` | 期货；期权（本地表4/表6命中） | `AG+YYMM`；`AG-YYMM-C/P-EP` | SHFE | [白银期权业务手册（上期所）](https://www.shfe.com.cn/content/2022_rb_ag_options/manual-AG.pdf) |
| 螺纹钢 | `RB` | 期货；期权（本地表4/表6命中） | `RB+YYMM`；`RB-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 热轧卷板 | `HC` | 期货；期权（本地表6命中） | `HC+YYMM`；`HC-YYMM-C/P-EP` | SHFE | [热轧卷板专题（上期所，含 HC 代码）](https://www.shfe.com.cn/content/hc/heygz.html) |
| 丁二烯橡胶（上期所官网常称“合成橡胶”） | `BR` | 期货；期权（本地表4命中） | `BR+YYMM`；`BR-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 天然橡胶 | `RU` | 期货；期权（本地表4/表6命中） | `RU+YYMM`；`RU-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 石油沥青 | `BU` | 期货；期权（本地表4命中） | `BU+YYMM`；`BU-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 燃料油 | `FU` | 期货；期权（本地表4/表6命中） | `FU+YYMM`；`FU-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 纸浆 | `SP` | 期货；期权（本地表4/表6命中） | `SP+YYMM`；`SP-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |
| 胶版印刷纸 | `OP` | 期货；期权（本地表4命中） | `OP+YYMM`；`OP-YYMM-C/P-EP` | SHFE | [上期所官网产品清单](https://www.shfe.com.cn/)；[2026年官方合约代码示例](https://www.shfe.com.cn/publicnotice/newsrelease/202605/t20260522_831772.html) |

### 3.4 上海国际能源交易中心（INE）

能源中心官网明确列出原油、低硫燃料油、20号胶、国际铜、集运指数（欧线）等期货品种；原油期权、20号胶期权以及 2026 年新增/挂牌的国际铜期权应与 SHFE 分开识别。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 原油 | `SC` | 期货；期权（本地表6命中） | `SC+YYMM`；`SC-YYMM-C/P-EP` | INE | [原油期货标准合约（能源中心）](https://www.ine.cn/products/futures/energyandchemical/sc_f/standard_sc_f/202312/t20231205_802540.html)；[原油期权产品页](https://www.ine.cn/products/option/) |
| 低硫燃料油 | `LU` | 期货（本地表6命中） | `LU+YYMM` | INE | [低硫燃料油期货标准合约（能源中心）](https://www.ine.cn/products/futures/energyandchemical/lu_f/standard_lu_f/202312/t20231205_802541.html) |
| 20号胶 | `NR` | 期货；期权（本地表4命中，期权需按最新挂牌状态核验） | `NR+YYMM`；`NR-YYMM-C/P-EP` | INE | [20号胶现行规则（能源中心）](https://www.ine.cn/regulation/ineregulation/rules/202205/t20220516_813427.html)；[20号胶期权产品页](https://www.ine.cn/products/option/energyandchemical/nr_o/) |
| 国际铜 | `BC` | 期货；期权（本地表4命中，期权需按最新挂牌状态核验） | `BC+YYMM`；`BC-YYMM-C/P-EP` | INE | [国际铜期货产品页（能源中心）](https://www.ine.cn/products/futures/metal/nonferrousmetal/bc_f/)；[能源中心2026期货/期权资料](https://www.ine.cn/index/othercontents/2026_Futures-Options/) |
| 集运指数（欧线）/SCFIS欧线 | `EC` | 期货（本地表6命中） | `EC+YYMM` | INE | [能源中心期货指数/品种页](https://www.ine.cn/products/futures/index_f/)；[能源中心品种简介](https://www.ine.cn/about/simintro/) |

### 3.5 广州期货交易所（GFEX）

广期所当前品种页列出工业硅、碳酸锂、多晶硅、铂、钯等品种；本地表4命中了多晶硅、铂、钯期权，以及工业硅、碳酸锂期货。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 工业硅 | `SI` | 期货（本地表4/表6命中） | `SI+YYMM` | GFEX | [工业硅期货合约（广期所）](https://www.gfex.com.cn/gfex/llbb/202402/73cd6f4cc26b4dd5b3d127b5462b59a7/files/%E5%B9%BF%E5%B7%9E%E6%9C%9F%E8%B4%A7%E4%BA%A4%E6%98%93%E6%89%80%E5%B7%A5%E4%B8%9A%E7%A1%85%E6%9C%9F%E8%B4%A7%E5%90%88%E7%BA%A6%EF%BC%882022%E5%B9%B412%E6%9C%8812%E6%97%A5%E7%89%88%EF%BC%89.pdf) |
| 碳酸锂 | `LC` | 期货（本地表4/表6命中） | `LC+YYMM` | GFEX | [碳酸锂期货品种页（广期所）](https://www.gfex.com.cn/gfex/sytslqhhy/202307/9ad927b8ec4c458594e172fd1ada2a9b.shtml)；[碳酸锂期权资料](https://www.gfex.com.cn/gfex/tslpzzl/202307/db1ea6ce118342ba886e5ef5b667ebe1/files/e57713398e094ca8af27b7ba49f82259.pdf) |
| 多晶硅 | `PS` | 期货；期权（本地表4命中；表6命中） | `PS+YYMM`；`PS-YYMM-C/P-EP` | GFEX | [广期所当前品种/期权清单](https://www.gfex.com.cn/gfex/sspzb/sspz.shtml)；[广期所2026业务通知（含 PS/LC 代码示例）](https://www.gfex.com.cn/gfex/tzts/202606/e9acdad20ec940baabf3e42b4b7d7066.shtml?t=aged&updatetime=short) |
| 铂 | `PT` | 期货；期权（本地表4命中；表6命中） | `PT+YYMM`；`PT-YYMM-C/P-EP` | GFEX | [广期所当前品种页（含 PT 期货及期权代码形态）](https://www.gfex.com.cn/gfex/sspzb/sspz.shtml) |
| 钯 | `PD` | 期货；期权（本地表4命中；表6命中） | `PD+YYMM`；`PD-YYMM-C/P-EP` | GFEX | [钯期权官方产品资料（广期所）](https://www.gfex.com.cn/gfex/pqqhy/202511/6ee85884edc8497695ccb8adcaea67eb.shtml) |

### 3.6 中国金融期货交易所（CFFEX）

中金所行情页列出股指期货代码 `IF`、`IC`、`IM`、`IH` 以及股指期权代码 `IO`、`MO`、`HO`。期货和期权的标的指数关系不能只靠中文名称匹配，建议同时保存期货代码和期权代码。

| 本项目/官方品种名 | 代码前缀 | 属性 | 常见完整合约代码形态 | 交易所 | 官方一手来源 |
|---|---|---|---|---|---|
| 沪深300股指期货/期权 | `IF` / `IO` | 期货 + 期权（本地表4/表6命中） | `IF+YYMM`；`IO-YYMM-C/P-EP` | CFFEX | [沪深300股指期货产品页](https://www.cffex.com.cn/hs300/)；[沪深300股指期权产品页](https://www.cffex.com.cn/hs300gzqq/) |
| 中证500股指期货 | `IC` | 期货（本地表6命中；本地样本未单独命中 MO） | `IC+YYMM` | CFFEX | [中证500股指期货产品页](https://www.cffex.com.cn/cn/zz500.html)；[中金所行情代码页](https://www.cffex.com.cn/cn/yshq.html) |
| 中证1000股指期货/期权 | `IM` / `MO` | 期货 + 期权（本地表4/表6命中） | `IM+YYMM`；`MO-YYMM-C/P-EP` | CFFEX | [中证1000股指期货合约资料](https://www.cffex.com.cn/u/cms/www/202207/182020307zry.pdf)；[股指期权规则资料（含 IO/MO/HO）](https://www.cffex.com.cn/cn/ssxz/20221214/43100.html) |
| 上证50股指期货/期权 | `IH` / `HO` | 期货 + 期权（本地表4/表6命中） | `IH+YYMM`；`HO-YYMM-C/P-EP` | CFFEX | [上证50股指期权产品页](https://www.cffex.com.cn/sz50gzqq/)；[股指期权规则资料（含 IO/MO/HO）](https://www.cffex.com.cn/cn/ssxz/20221214/43100.html) |

## 4. 面向交易限额/异常交易监控的使用建议

1. 先按交易所分区，再按代码前缀匹配。尤其要避免把 `CU` 与 INE 的 `BC`、SHFE 的 `RU` 与 INE 的 `NR`、SHFE 的 `FU` 与 INE 的 `LU` 混为同一品种。
2. 将“品种代码前缀”和“合约代码”分开存储：例如 `M` 是品种身份，`M2609` 是具体期货合约；期权还需要独立保存方向和行权价。
3. 解析期权时不要把 `C/P` 或行权价当成期货月份；应先识别期权标的前缀，再解析 `YYMM`、看涨/看跌和行权价。
4. DCE 的中文品种名称和代码字段需做别名归一化：聚氯乙烯的产品资料常写 PVC，但合约代码前缀是 `V`；聚乙烯/LLDPE 对应 `L`。
5. ZCE 甲醇当前代码是 `MA`；官方历史公告显示旧代码 `ME` 仅对应历史阶段，历史 OCR 数据若出现 `ME` 不应直接按当前合约匹配。
6. 交易所的“交易限额”“异常交易行为认定”“客户限仓”和“套保/套利额度”是不同规则层。静态映射只能解决“这是什么品种/在哪个交易所”，不能替代最新公告中的阈值和适用条件。

## 5. 不确定项与复核清单

- **DCE 来源分散**：大商所官网公开索引没有稳定地提供一张包含全部当前品种、代码和期权状态的单一表格。本记录使用大商所官方品种资料、业务细则、宣传页和月报交叉核对；对 `A/B/M/Y/P/PG/EG/JD/LG` 等行，建议在正式上线前再读取大商所最新“合约信息/业务参数”页面。
- **期权上市状态是动态字段**：本地表4为 2026-06 左右的 OCR 快照，不能据此保证 2026-09-17 之后仍完全相同。特别是 SHFE 官网当前页面已出现热轧卷板、不锈钢、低硫燃料油期权挂牌信息；这些不属于本地优先样本，未扩展为本次主表的新增优先项。
- **显示名差异**：SHFE 官网使用“合成橡胶”这一产品名时，本地表写作“丁二烯橡胶”，代码均按 `BR` 处理；INE 的 `EC` 官方名称为“集运指数（欧线）/SCFIS欧线”。
- **DCE PVC 归一化**：`PVC` 是常见中文/英文简称，DCE 合约代码前缀应按 `V` 处理；如果输入来自 OCR，应保留原始文本并另存规范化代码。
- **历史代码**：郑商所甲醇的当前代码为 `MA`，历史资料中可见 `ME`。监控历史数据时应根据合约年月和数据来源保留历史别名映射。
- **数据源时效**：本记录截至 2026-09-17，官方页面可能改版、替换历史规则或新增合约。生产监控应以交易所当日公告、交易参数和最新业务规则为准，并记录抓取日期。

