from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, text

from .config import Settings


POSITION_TEMPLATE_TYPE = "TEMP_POSITIONLIMIT_DETAIL"
OPEN_TOTAL_TEMPLATE_TYPE = "TEMP_OPENTOTALLIMIT"
POSITION_TYPES = {"期货": 1, "期权": 2}
POSITION_DIRECTIONS = {"多仓": 0, "空仓": 1, "所有": 2}
HEDGE_FLAGS = {"投机": 1, "套保": 3, "所有": 0}
EXCHANGE_CODES = {
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
}
KNOWN_PRODUCT_CODES = frozenset(
    {
        "A",
        "AD",
        "AF",
        "AG",
        "AL",
        "AO",
        "AP",
        "AU",
        "B",
        "BB",
        "BC",
        "BR",
        "BU",
        "BZ",
        "C",
        "CF",
        "CJ",
        "CS",
        "CU",
        "CY",
        "EC",
        "EB",
        "EG",
        "FB",
        "FG",
        "FU",
        "HC",
        "I",
        "IC",
        "IF",
        "IH",
        "IM",
        "J",
        "JD",
        "JM",
        "JR",
        "L",
        "LC",
        "LG",
        "LH",
        "LR",
        "LU",
        "L_f",
        "M",
        "MA",
        "NI",
        "NR",
        "OI",
        "OP",
        "P",
        "PB",
        "PD",
        "PF",
        "PG",
        "PK",
        "PM",
        "PP",
        "PP_f",
        "PR",
        "PS",
        "PT",
        "PX",
        "RB",
        "RI",
        "RM",
        "RR",
        "RS",
        "RU",
        "SA",
        "SC",
        "SF",
        "SH",
        "SI",
        "SM",
        "SN",
        "SP",
        "SR",
        "SS",
        "T",
        "TA",
        "TF",
        "TL",
        "TS",
        "UR",
        "V",
        "V_f",
        "WH",
        "WR",
        "Y",
        "ZC",
        "ZN",
        "HO",
        "IO",
        "MO",
    }
)


class SourceCellRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    section_id: str = Field(alias="sectionId", min_length=1, max_length=120)
    row: int = Field(ge=0)
    column: int = Field(ge=0)


class PositionDateRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    startmonth: int
    startday: int
    startdaytype: Literal[0, 1]
    endmonth: int
    endday: int
    enddaytype: Literal[0, 1]
    startordertype: Literal[0, 1]
    endordertype: Literal[0, 1]


class PositionLimitRowRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    type: Literal["期货", "期权"]
    exchange: str = Field(min_length=1)
    exchange_code: str | None = Field(default=None, alias="exchangeCode")
    instrument: str = Field(min_length=1)
    product_id: str | None = Field(default=None, alias="productId")
    direction: str = "所有"
    hedge: str = "所有"
    holding_date: str = Field(alias="holdingDate", min_length=1)
    date_rule: PositionDateRule | None = Field(default=None, alias="dateRule")
    total_position: str = Field(alias="totalPosition", min_length=1)
    limit_rule: str = Field(alias="limitRule", min_length=1)
    source_text: str = Field(default="", alias="sourceText")
    source_section_id: str = Field(default="", alias="sourceSectionId")
    source_cells: list[SourceCellRef] = Field(default_factory=list, alias="sourceCells")


class ExceptionTradeRowRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    exchange: str = Field(min_length=1)
    exchange_code: str | None = Field(default=None, alias="exchangeCode")
    instrument_name: str = Field(default="", alias="instrumentName")
    instrument_code: str = Field(alias="instrumentCode", min_length=1)
    open_total: int = Field(alias="openTotal", ge=0)
    open_total_warning: int = Field(alias="openTotalWarning", ge=0)
    instrument_type: Literal["期货", "期权"] = Field(alias="instrumentType")
    scope: Literal["product", "contract"]
    level: Literal["品种级", "合约级", "深度虚值合约"]
    warning_origin: str = Field(default="derived_80", alias="warningOrigin")
    source_text: str = Field(default="", alias="sourceText")
    source_cells: list[SourceCellRef] = Field(default_factory=list, alias="sourceCells")


class DatabaseImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    view: Literal["recognized", "revised"] = "recognized"
    document_sha256: str = Field(alias="documentSha256", min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    template_type: Literal[POSITION_TEMPLATE_TYPE, OPEN_TOTAL_TEMPLATE_TYPE] | None = Field(default=None, alias="templateType")
    template_name: str | None = Field(default=None, alias="templateName", max_length=100)
    remark: str | None = Field(default=None, max_length=500)
    position_rows: list[PositionLimitRowRequest] = Field(default_factory=list, alias="positionRows")
    exception_rows: list[ExceptionTradeRowRequest] = Field(default_factory=list, alias="exceptionRows")
    unmapped_cells: list[str] = Field(default_factory=list, alias="unmappedCells")
    unmapped_limit_cells: list[str] = Field(default_factory=list, alias="unmappedLimitCells")


class ImportIssue(BaseModel):
    entity_type: str
    entity_index: int = -1
    field: str
    code: str
    message: str
    source_cells: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class ImportPlan:
    run_id: str
    view: str
    document_sha256: str
    template_type: str
    template_name: str
    remark: str
    application_version: str
    position_rows: list[dict[str, Any]]
    open_total_rows: list[dict[str, Any]]
    fingerprint: str
    creator_id: int | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {
            "position_details": len(self.position_rows),
            "position_numbers": len(self.position_rows),
            "open_total_rows": len(self.open_total_rows),
            "total_rows": len(self.position_rows) + len(self.open_total_rows),
        }

    @property
    def used_derived_warning(self) -> bool:
        return any(row.get("warning_origin") not in {None, "source"} for row in self.open_total_rows)

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "view": self.view,
            "document_sha256": self.document_sha256,
            "template_type": self.template_type,
            "template_name": self.template_name,
            "remark": self.remark,
            "application_version": self.application_version,
            "position_rows": self.position_rows,
            "open_total_rows": self.open_total_rows,
            "fingerprint": self.fingerprint,
            "creator_id": self.creator_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ImportPlan":
        return cls(
            run_id=str(payload["run_id"]),
            view=str(payload["view"]),
            document_sha256=str(payload["document_sha256"]),
            template_type=str(payload["template_type"]),
            template_name=str(payload["template_name"]),
            remark=str(payload["remark"]),
            application_version=str(payload["application_version"]),
            position_rows=list(payload.get("position_rows", [])),
            open_total_rows=list(payload.get("open_total_rows", [])),
            fingerprint=str(payload["fingerprint"]),
            creator_id=int(payload["creator_id"]) if payload.get("creator_id") is not None else None,
        )


@dataclass(frozen=True)
class OraclePreflightResult:
    creator_id: int | None
    issues: list[ImportIssue]


@dataclass(frozen=True)
class OracleWriteResult:
    template_id: str
    position_detail_ids: list[str]
    position_number_ids: list[str]
    open_total_ids: list[str]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "position_details": len(self.position_detail_ids),
            "position_numbers": len(self.position_number_ids),
            "open_total_rows": len(self.open_total_ids),
            "total_rows": len(self.position_detail_ids) + len(self.open_total_ids),
        }


class OracleWriter(Protocol):
    def preflight(self, plan: ImportPlan) -> OraclePreflightResult:
        ...

    def write(self, plan: ImportPlan) -> OracleWriteResult:
        ...


def _compact(value: str) -> str:
    return value.replace("\u3000", "").replace(" ", "").replace("\n", "").replace("\r", "").strip()


def _source_cells(row: PositionLimitRowRequest | ExceptionTradeRowRequest) -> list[dict[str, Any]]:
    return [cell.model_dump(mode="json", by_alias=True) for cell in row.source_cells]


def _issue(
    entity_type: str,
    entity_index: int,
    field: str,
    code: str,
    message: str,
    source_cells: list[dict[str, Any]] | None = None,
) -> ImportIssue:
    return ImportIssue(
        entity_type=entity_type,
        entity_index=entity_index,
        field=field,
        code=code,
        message=message,
        source_cells=source_cells or [],
    )


def _split_codes(value: str) -> list[str]:
    codes: list[str] = []
    for item in re.split(r"[、,，/;；\s]+", value):
        code = item.strip().upper()
        if not code:
            continue
        # Keep the special product suffix in its canonical lowercase form
        # after normalizing ordinary exchange codes to uppercase.
        codes.append(re.sub(r"_F(?=\d*$)", "_f", code))
    return codes


def _exchange_code(name: str, supplied: str | None) -> str | None:
    mapped_name = EXCHANGE_CODES.get(_compact(name))
    if supplied:
        code = supplied.strip().upper()
        if code in {"DCE", "CZCE", "SHFE", "INE", "CFFEX", "GFEX"} and mapped_name == code:
            return code
    return mapped_name


def _parse_number(value: str, *, allow_decimal: bool = True) -> Decimal | None:
    text_value = _compact(value).replace(",", "").replace("，", "")
    text_value = text_value.replace("手", "")
    if text_value.endswith("万"):
        text_value = text_value[:-1]
        multiplier = Decimal("10000")
    else:
        multiplier = Decimal("1")
    try:
        result = Decimal(text_value) * multiplier
    except InvalidOperation:
        return None
    if not allow_decimal and result != result.to_integral_value():
        return None
    return result


def _decimal_value(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def parse_position_range(value: str) -> tuple[int, int] | None:
    text_value = _compact(value).replace("≤", "<=")
    match = re.fullmatch(
        r"(?P<lower>[0-9]+(?:\.[0-9]+)?)<=持仓量(?P<operator><=|<)(?P<upper>\+?∞|[0-9][0-9,]*(?:\.[0-9]+)?万?)",
        text_value,
    )
    if match:
        lower = _parse_number(match.group("lower"), allow_decimal=False)
        upper = -1 if match.group("upper") in {"∞", "+∞"} else _parse_number(match.group("upper"), allow_decimal=False)
        if lower is None or upper is None:
            return None
        lower_int = int(lower)
        upper_int = int(upper)
        if upper_int != -1 and upper_int < lower_int:
            return None
        return lower_int, upper_int

    match = re.fullmatch(r">(?P<lower>[0-9][0-9,]*(?:\.[0-9]+)?万?)", text_value)
    if match:
        lower = _parse_number(match.group("lower"), allow_decimal=False)
        return (int(lower), -1) if lower is not None else None
    return None


def parse_limit_rule(value: str) -> tuple[int | float, int] | None:
    text_value = _compact(value)
    is_percentage = "百分比" in text_value or "%" in text_value or "％" in text_value
    text_value = text_value.replace("固定值", "").replace("百分比", "").replace("%", "").replace("％", "")
    number = _parse_number(text_value)
    if number is None or number < 0:
        return None
    if is_percentage:
        if number > 1:
            number = number / Decimal("100")
        if number > 1:
            return None
        return _decimal_value(number), 1
    return _decimal_value(number), 0


_CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _small_chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if value in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[value]
    if value.startswith("十"):
        return 10 + (_CHINESE_DIGITS.get(value[1:], 0) if len(value) > 1 else 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return _CHINESE_DIGITS.get(left, 0) * 10 + (_CHINESE_DIGITS.get(right, 0) if right else 0)
    return None


def _parse_date_endpoint(value: str, *, start: bool) -> dict[str, int] | None:
    text_value = _compact(value).replace("自", "").replace("从", "").replace("期间", "")
    text_value = re.sub(r"(起|开始)$", "", text_value)

    if "合约挂牌" in text_value or "合约上市" in text_value:
        return {"month": -1, "day": -1, "daytype": 0, "ordertype": 0}
    if "最后交易日" in text_value:
        return {"month": -3, "day": -1, "daytype": 0, "ordertype": 0}
    if text_value in {"交割月", "交割月份"}:
        return {"month": -2 if start else -1, "day": -2 if start else -1, "daytype": 0, "ordertype": 0}

    month_match = re.search(r"交割月(?:前|之前)?(?P<months>[0-9一二两三四五六七八九十]+)个?月", text_value)
    if not month_match and "交割月" in text_value:
        month_value = -2 if start else -1
    elif month_match:
        month_count = _small_chinese_number(month_match.group("months"))
        if month_count is None:
            return None
        month_value = month_count if "前" in text_value or "之前" in text_value else -2
    else:
        return None

    day_type = 1 if "日历" in text_value else 0
    order_type = 1 if "最后一个" in text_value or "最后" in text_value else 0
    day_match = re.search(r"第(?P<day>最后一个|[0-9一二两三四五六七八九十]+)个?(?:交易日|日历日|日)", text_value)
    if day_match:
        if day_match.group("day") == "最后一个":
            day = 1
            order_type = 1
        else:
            day = _small_chinese_number(day_match.group("day"))
            if day is None:
                return None
        return {"month": month_value, "day": day, "daytype": day_type, "ordertype": order_type}
    if "最后一个日历日" in text_value:
        return {"month": month_value, "day": 1, "daytype": 1, "ordertype": 1}
    return None


def parse_date_rule(value: str) -> PositionDateRule | None:
    text_value = _compact(value)
    if text_value == "合约挂牌至交割月份" or text_value == "合约上市至交割月份":
        return PositionDateRule(
            startmonth=-1,
            startday=-1,
            startdaytype=0,
            endmonth=-1,
            endday=-1,
            enddaytype=0,
            startordertype=0,
            endordertype=0,
        )

    if "至" in text_value:
        start_text, end_text = text_value.split("至", 1)
        start = _parse_date_endpoint(start_text, start=True)
        end = _parse_date_endpoint(end_text, start=False)
    elif "起" in text_value:
        start = _parse_date_endpoint(text_value, start=True)
        end = _parse_date_endpoint("交割月", start=False)
    elif text_value in {"交割月", "交割月份"}:
        start = _parse_date_endpoint(text_value, start=True)
        end = _parse_date_endpoint(text_value, start=False)
    else:
        return None

    if start is None or end is None:
        return None
    return PositionDateRule(
        startmonth=start["month"],
        startday=start["day"],
        startdaytype=start["daytype"],
        endmonth=end["month"],
        endday=end["day"],
        enddaytype=end["daytype"],
        startordertype=start["ordertype"],
        endordertype=end["ordertype"],
    )


def _valid_instrument_code(value: str) -> bool:
    return re.fullmatch(r"[A-Z]{1,5}(?:_[Ff])?[0-9]{0,8}", value) is not None


def _known_instrument_code(value: str) -> bool:
    prefix = re.sub(r"[0-9]+$", "", value)
    base_prefix = re.sub(r"_[Ff]$", "", prefix)
    return prefix in KNOWN_PRODUCT_CODES or base_prefix in KNOWN_PRODUCT_CODES


def _valid_date_rule(rule: PositionDateRule) -> bool:
    valid_months = {-3, -2, -1} | set(range(1, 13))
    valid_days = {-2, -1} | set(range(1, 32))
    return (
        rule.startmonth in valid_months
        and rule.endmonth in valid_months
        and rule.startday in valid_days
        and rule.endday in valid_days
        and rule.startdaytype in {0, 1}
        and rule.enddaytype in {0, 1}
        and rule.startordertype in {0, 1}
        and rule.endordertype in {0, 1}
    )


def _validate_source_cells(document: dict[str, Any], cells: list[SourceCellRef], entity_type: str, index: int) -> list[ImportIssue]:
    sections = {str(section.get("id", "")): section for section in document.get("sections", [])}
    issues: list[ImportIssue] = []
    for cell in cells:
        section = sections.get(cell.section_id)
        if section is None:
            issues.append(_issue(entity_type, index, "sourceCells", "source_section_not_found", f"来源分区不存在：{cell.section_id}"))
            continue
        rows = section.get("cells", [])
        if cell.row >= len(rows) or cell.column >= len(rows[cell.row]):
            issues.append(
                _issue(
                    entity_type,
                    index,
                    "sourceCells",
                    "source_cell_out_of_range",
                    f"来源单元格越界：{cell.section_id}[{cell.row},{cell.column}]",
                )
            )
    return issues


def _normalized_position_rows(
    rows: list[PositionLimitRowRequest], document: dict[str, Any], issues: list[ImportIssue]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows):
        source_cells = _source_cells(row)
        issues.extend(_validate_source_cells(document, row.source_cells, "position", index))
        exchange_code = _exchange_code(row.exchange, row.exchange_code)
        if exchange_code is None:
            issues.append(_issue("position", index, "exchange", "unknown_exchange", f"无法映射交易所：{row.exchange}", source_cells))

        product_ids = _split_codes(row.product_id or row.instrument)
        if not product_ids:
            issues.append(_issue("position", index, "instrument", "empty_product_id", "品种/合约代码为空", source_cells))
        for product_id in product_ids:
            if not _valid_instrument_code(product_id):
                issues.append(_issue("position", index, "instrument", "invalid_product_id", f"品种/合约代码非法：{product_id}", source_cells))
            elif not _known_instrument_code(product_id):
                issues.append(_issue("position", index, "instrument", "unknown_product_code", f"品种/合约代码未完成唯一映射：{product_id}", source_cells))

        product_type = POSITION_TYPES[row.type]
        direction = POSITION_DIRECTIONS.get(_compact(row.direction))
        if direction is None:
            issues.append(_issue("position", index, "direction", "invalid_position_direction", f"持仓方向非法：{row.direction}", source_cells))
        hedge_flag = HEDGE_FLAGS.get(_compact(row.hedge))
        if hedge_flag is None:
            issues.append(_issue("position", index, "hedge", "invalid_hedge_flag", f"投保类型非法：{row.hedge}", source_cells))

        parsed_date_rule = parse_date_rule(row.holding_date)
        date_rule = row.date_rule or parsed_date_rule
        date_rule_valid = date_rule is not None and _valid_date_rule(date_rule)
        if row.date_rule is not None and parsed_date_rule is None:
            date_rule_valid = False
            issues.append(_issue("position", index, "holdingDate", "unknown_date_rule", f"无法严格映射持仓日期：{row.holding_date}", source_cells))
        elif row.date_rule is not None and parsed_date_rule is not None and row.date_rule.model_dump() != parsed_date_rule.model_dump():
            date_rule_valid = False
            issues.append(_issue("position", index, "dateRule", "date_rule_mismatch", "结构化日期规则与日期文本不一致", source_cells))
        if date_rule is None and not row.date_rule:
            issues.append(_issue("position", index, "holdingDate", "unknown_date_rule", f"无法严格映射持仓日期：{row.holding_date}", source_cells))
        elif date_rule is not None and not _valid_date_rule(date_rule):
            issues.append(_issue("position", index, "dateRule", "invalid_date_rule", "结构化日期规则超出允许的哨兵或日期范围", source_cells))

        position_range = parse_position_range(row.total_position)
        if position_range is None:
            issues.append(_issue("position", index, "totalPosition", "invalid_position_range", f"持仓量区间非法：{row.total_position}", source_cells))
        limit_rule = parse_limit_rule(row.limit_rule)
        if limit_rule is None:
            issues.append(_issue("position", index, "limitRule", "invalid_limit_rule", f"限仓规则非法：{row.limit_rule}", source_cells))

        if (
            exchange_code is None
            or not product_ids
            or any(not _valid_instrument_code(product_id) or not _known_instrument_code(product_id) for product_id in product_ids)
            or direction is None
            or hedge_flag is None
            or not date_rule_valid
            or position_range is None
            or limit_rule is None
        ):
            continue

        lower, upper = position_range
        max_position, max_position_type = limit_rule
        for product_id in product_ids:
            key = (
                exchange_code,
                product_id,
                product_type,
                direction,
                hedge_flag,
                tuple(date_rule.model_dump().values()),
                lower,
                upper,
                max_position,
                max_position_type,
            )
            if key in seen:
                issues.append(_issue("position", index, "instrument", "duplicate_position_row", f"重复的限仓实体：{product_id}", source_cells))
                continue
            seen.add(key)
            result.append(
                {
                    "exchange_id": exchange_code,
                    "product_id": product_id,
                    "product_type": product_type,
                    "position_direction": direction,
                    "hedge_flag": hedge_flag,
                    **date_rule.model_dump(),
                    "position_lower": lower,
                    "position_upper": upper,
                    "max_position": max_position,
                    "max_position_type": max_position_type,
                    "source_cells": source_cells,
                }
            )
    return result


def _normalized_open_total_rows(
    rows: list[ExceptionTradeRowRequest], document: dict[str, Any], issues: list[ImportIssue]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows):
        source_cells = _source_cells(row)
        issues.extend(_validate_source_cells(document, row.source_cells, "open_total", index))
        exchange_code = _exchange_code(row.exchange, row.exchange_code)
        if exchange_code is None:
            issues.append(_issue("open_total", index, "exchange", "unknown_exchange", f"无法映射交易所：{row.exchange}", source_cells))
        instrument_ids = _split_codes(row.instrument_code)
        if not instrument_ids:
            issues.append(_issue("open_total", index, "instrumentCode", "empty_instrument_id", "品种/合约代码为空", source_cells))
        for instrument_id in instrument_ids:
            if not _valid_instrument_code(instrument_id):
                issues.append(_issue("open_total", index, "instrumentCode", "invalid_instrument_id", f"品种/合约代码非法：{instrument_id}", source_cells))
            elif not _known_instrument_code(instrument_id):
                issues.append(_issue("open_total", index, "instrumentCode", "unknown_instrument_code", f"品种/合约代码未完成唯一映射：{instrument_id}", source_cells))
        if row.open_total_warning > row.open_total:
            issues.append(_issue("open_total", index, "openTotalWarning", "warning_exceeds_limit", "开仓总量预警值不能大于开仓总量", source_cells))
        if (
            exchange_code is None
            or not instrument_ids
            or any(not _valid_instrument_code(instrument_id) or not _known_instrument_code(instrument_id) for instrument_id in instrument_ids)
            or row.open_total_warning > row.open_total
        ):
            continue

        is_product = 1 if row.scope == "product" else 0
        is_opt = 1 if row.instrument_type == "期权" else 0
        only_depth = 1 if row.level == "深度虚值合约" else 0
        for instrument_id in instrument_ids:
            key = (exchange_code, instrument_id, row.open_total, row.open_total_warning, is_product, is_opt, only_depth)
            if key in seen:
                issues.append(_issue("open_total", index, "instrumentCode", "duplicate_open_total_row", f"重复的开仓总量实体：{instrument_id}", source_cells))
                continue
            seen.add(key)
            result.append(
                {
                    "instrument_id": instrument_id,
                    "limit_volume": row.open_total,
                    "limit_warn_volume": row.open_total_warning,
                    "is_product": is_product,
                    "is_opt": is_opt,
                    "only_depth": only_depth,
                    "exchange_id": exchange_code,
                    "warning_origin": row.warning_origin,
                    "source_cells": source_cells,
                }
            )
    return result


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_import_plan(
    run_id: str,
    document: dict[str, Any],
    body: DatabaseImportRequest,
    settings: Settings,
) -> tuple[ImportPlan, list[ImportIssue]]:
    issues: list[ImportIssue] = []
    has_position = bool(body.position_rows)
    has_open_total = bool(body.exception_rows)
    if has_position and has_open_total:
        issues.append(_issue("batch", -1, "templateType", "mixed_template_types", "一次导入只能对应一种模板类型"))
    if not has_position and not has_open_total:
        issues.append(_issue("batch", -1, "rows", "empty_entity_table", "实体整理表没有可导入的数据"))

    inferred_type = POSITION_TEMPLATE_TYPE if has_position else OPEN_TOTAL_TEMPLATE_TYPE
    template_type = body.template_type or inferred_type
    if has_position and template_type != POSITION_TEMPLATE_TYPE:
        issues.append(_issue("batch", -1, "templateType", "template_type_mismatch", "期权限仓实体与模板类型不匹配"))
    if has_open_total and template_type != OPEN_TOTAL_TEMPLATE_TYPE:
        issues.append(_issue("batch", -1, "templateType", "template_type_mismatch", "开仓总量实体与模板类型不匹配"))

    for cell in body.unmapped_cells:
        issues.append(_issue("position", -1, "instrument", "unmapped_entity", f"未完成品种映射：{cell}"))
    for cell in body.unmapped_limit_cells:
        issues.append(_issue("open_total", -1, "instrumentCode", "unmapped_limit_cell", f"未完成交易限额映射：{cell}"))

    position_rows = _normalized_position_rows(body.position_rows, document, issues)
    open_total_rows = _normalized_open_total_rows(body.exception_rows, document, issues)
    if template_type == POSITION_TEMPLATE_TYPE and not position_rows and not issues:
        issues.append(_issue("batch", -1, "rows", "empty_position_rows", "没有可写入的期权限仓实体"))
    if template_type == OPEN_TOTAL_TEMPLATE_TYPE and not open_total_rows and not issues:
        issues.append(_issue("batch", -1, "rows", "empty_open_total_rows", "没有可写入的开仓总量实体"))

    business_name = "期权限仓" if template_type == POSITION_TEMPLATE_TYPE else "开仓总量"
    template_name = (body.template_name or f"自动导入-{business_name}-{datetime.now(ZoneInfo('Asia/Shanghai')):%Y%m%d}-{run_id[:8]}").strip()
    if not template_name or len(template_name) > 100:
        issues.append(_issue("batch", -1, "templateName", "invalid_template_name", "模板名称不能为空且不能超过100个字符"))
    remark = (body.remark or f"结构化实体表导入，运行ID={run_id}，文档哈希={body.document_sha256}").strip()

    canonical = {
        "template_type": template_type,
        "position_rows": position_rows,
        "open_total_rows": open_total_rows,
    }
    plan = ImportPlan(
        run_id=run_id,
        view=body.view,
        document_sha256=body.document_sha256,
        template_type=template_type,
        template_name=template_name,
        remark=remark,
        application_version=settings.oracle_application_version,
        position_rows=position_rows,
        open_total_rows=open_total_rows,
        fingerprint=_fingerprint(canonical),
        creator_id=settings.oracle_creator_id,
    )
    return plan, issues


class OracleImportError(RuntimeError):
    pass


class OracleTemplateWriter:
    """Direct writer for the existing Oracle template tables.

    The target tables are deliberately not part of the local SQLAlchemy model.
    This class uses explicit, parameterized SQL so the local SQLite metadata
    cannot create or mutate the business schema by accident.
    """

    def __init__(self, settings: Settings, engine: Engine | None = None):
        self.settings = settings
        self._engine = engine

    def _engine_or_raise(self) -> Engine:
        if self._engine is not None:
            return self._engine
        if not self.settings.oracle_database_url:
            raise OracleImportError("Oracle连接未配置，请设置IMAGE_TABLE_ORACLE_DATABASE_URL")
        try:
            self._engine = create_engine(
                self.settings.oracle_database_url,
                pool_pre_ping=True,
                pool_timeout=self.settings.oracle_import_timeout_seconds,
                connect_args={
                    "tcp_connect_timeout": self.settings.oracle_import_timeout_seconds,
                    "call_timeout": self.settings.oracle_import_timeout_seconds * 1000,
                },
            )
        except Exception as error:
            raise OracleImportError(f"创建Oracle连接失败：{error}") from error
        return self._engine

    @staticmethod
    def _status_conflict(connection: Any, template_type: str) -> bool:
        statement = text(
            "SELECT ID FROM TEMP_RELEASE_RECORD "
            "WHERE TEMPLATE_TYPE = :template_type "
            "AND PUBLISH_STATUS IN (0, 1, 2) AND ROWNUM = 1"
        )
        return connection.execute(statement, {"template_type": template_type}).first() is not None

    def _resolve_creator(self, connection: Any) -> int | None:
        if self.settings.oracle_creator_id is not None:
            creator_id = int(self.settings.oracle_creator_id)
            return creator_id if creator_id > 0 else None
        if not self.settings.oracle_creator_lookup_sql:
            return None
        session_user = connection.execute(text("SELECT SYS_CONTEXT('USERENV', 'SESSION_USER') FROM DUAL")).scalar_one()
        value = connection.execute(text(self.settings.oracle_creator_lookup_sql), {"session_user": session_user}).scalar_one_or_none()
        if value is None:
            return None
        try:
            creator_id = int(value)
        except (TypeError, ValueError):
            return None
        return creator_id if creator_id > 0 else None

    def preflight(self, plan: ImportPlan) -> OraclePreflightResult:
        try:
            engine = self._engine_or_raise()
        except OracleImportError as error:
            return OraclePreflightResult(
                creator_id=None,
                issues=[_issue("target", -1, "oracle", "oracle_not_configured", str(error))],
            )

        issues: list[ImportIssue] = []
        try:
            with engine.connect() as connection:
                required_tables = {"TEMP_RELEASE_RECORD"}
                required_sequences = {"TEMP_RELEASE_RECORD_SEQ"}
                if plan.template_type == POSITION_TEMPLATE_TYPE:
                    required_tables.update({"TEMP_POSITIONLIMIT_DETAIL", "TEMP_POSITIONLIMIT_NUMBER"})
                    required_sequences.update({"TEMP_POSITIONLIMIT_DETAIL_SEQ", "TEMP_POSITIONLIMIT_NUMBER_SEQ"})
                else:
                    required_tables.add("TEMP_OPENTOTALLIMIT")
                    required_sequences.add("TEMP_OPENTOTALLIMIT_SEQ")

                for table_name in sorted(required_tables):
                    try:
                        connection.execute(text(f"SELECT 1 FROM {table_name} WHERE 1 = 0"))
                    except Exception as error:
                        issues.append(_issue("target", -1, table_name, "target_table_unavailable", f"目标表不可用：{error}"))
                for sequence_name in sorted(required_sequences):
                    try:
                        exists = connection.execute(
                            text("SELECT SEQUENCE_NAME FROM ALL_SEQUENCES WHERE SEQUENCE_NAME = :sequence_name"),
                            {"sequence_name": sequence_name},
                        ).first()
                    except Exception as error:
                        issues.append(_issue("target", -1, sequence_name, "target_sequence_check_failed", f"目标序列检查失败：{error}"))
                        continue
                    if exists is None:
                        issues.append(_issue("target", -1, sequence_name, "target_sequence_unavailable", f"目标序列不存在或无权限：{sequence_name}"))

                creator_id = self._resolve_creator(connection)
                if creator_id is None:
                    issues.append(_issue("target", -1, "CREATOR", "creator_mapping_missing", "Oracle当前用户无法映射到业务用户ID"))
                if not issues and self._status_conflict(connection, plan.template_type):
                    issues.append(_issue("target", -1, "PUBLISH_STATUS", "draft_template_conflict", "该模板类型已有编制中、待审核或已拒绝模板"))
                return OraclePreflightResult(creator_id=creator_id, issues=issues)
        except Exception as error:
            return OraclePreflightResult(
                creator_id=None,
                issues=[_issue("target", -1, "oracle", "oracle_connection_failed", f"Oracle预校验失败：{error}")],
            )

    @staticmethod
    def _next_value(connection: Any, sequence_name: str) -> int:
        return int(connection.execute(text(f"SELECT {sequence_name}.NEXTVAL FROM DUAL")).scalar_one())

    def write(self, plan: ImportPlan) -> OracleWriteResult:
        engine = self._engine_or_raise()
        creator_id = plan.creator_id
        position_detail_ids: list[str] = []
        position_number_ids: list[str] = []
        open_total_ids: list[str] = []
        try:
            with engine.begin() as connection:
                if self._status_conflict(connection, plan.template_type):
                    raise OracleImportError("目标库已有未完成的同类型临时模板")
                if creator_id is None:
                    creator_id = self._resolve_creator(connection)
                if creator_id is None:
                    raise OracleImportError("Oracle当前用户无法映射到业务用户ID")

                template_id_value = self._next_value(connection, "TEMP_RELEASE_RECORD_SEQ")
                template_id = str(template_id_value)
                connection.execute(
                    text(
                        "INSERT INTO TEMP_RELEASE_RECORD "
                        "(ID, TEMPLATE_TYPE, TEMPLATE_NAME, PUBLISH_STATUS, REMARK, APPLICATION_VERSION, CREATOR) "
                        "VALUES (:id, :template_type, :template_name, :publish_status, :remark, :application_version, :creator)"
                    ),
                    {
                        "id": template_id_value,
                        "template_type": plan.template_type,
                        "template_name": plan.template_name,
                        "publish_status": 0,
                        "remark": plan.remark,
                        "application_version": plan.application_version,
                        "creator": creator_id,
                    },
                )

                if plan.template_type == POSITION_TEMPLATE_TYPE:
                    for detail_order, row in enumerate(plan.position_rows, start=1):
                        detail_id_value = self._next_value(connection, "TEMP_POSITIONLIMIT_DETAIL_SEQ")
                        detail_id = str(detail_id_value)
                        position_detail_ids.append(detail_id)
                        connection.execute(
                            text(
                                "INSERT INTO TEMP_POSITIONLIMIT_DETAIL "
                                "(ID, TEMPLATEID, EXCHANGEID, PRODUCTID, POSITIONDIRECTION, HEDGEFLAG, "
                                "STARTMONTH, STARTDAY, STARTDAYTYPE, ENDMONTH, ENDDAY, ENDDAYTYPE, "
                                "DETAILORDER, ISDELETE, STARTORDERTYPE, ENDORDERTYPE, PRODUCTTYPE, CREATOR) "
                                "VALUES (:id, :template_id, :exchange_id, :product_id, :position_direction, :hedge_flag, "
                                ":startmonth, :startday, :startdaytype, :endmonth, :endday, :enddaytype, "
                                ":detail_order, 0, :startordertype, :endordertype, :product_type, :creator)"
                            ),
                            {
                                "id": detail_id_value,
                                "template_id": template_id_value,
                                "exchange_id": row["exchange_id"],
                                "product_id": row["product_id"],
                                "position_direction": row["position_direction"],
                                "hedge_flag": row["hedge_flag"],
                                "startmonth": row["startmonth"],
                                "startday": row["startday"],
                                "startdaytype": row["startdaytype"],
                                "endmonth": row["endmonth"],
                                "endday": row["endday"],
                                "enddaytype": row["enddaytype"],
                                "detail_order": detail_order,
                                "startordertype": row["startordertype"],
                                "endordertype": row["endordertype"],
                                "product_type": row["product_type"],
                                "creator": creator_id,
                            },
                        )
                        number_id_value = self._next_value(connection, "TEMP_POSITIONLIMIT_NUMBER_SEQ")
                        number_id = str(number_id_value)
                        position_number_ids.append(number_id)
                        connection.execute(
                            text(
                                "INSERT INTO TEMP_POSITIONLIMIT_NUMBER "
                                "(ID, TEMPLATEDETAILID, POSITIONUPPER, POSITIONLOWER, MAXPOSITION, MAXPOSITIONTYPE, "
                                "NUMBERORDER, ISDELETE, CREATOR) "
                                "VALUES (:id, :detail_id, :position_upper, :position_lower, :max_position, :max_position_type, "
                                ":number_order, 0, :creator)"
                            ),
                            {
                                "id": number_id_value,
                                "detail_id": detail_id_value,
                                "position_upper": row["position_upper"],
                                "position_lower": row["position_lower"],
                                "max_position": row["max_position"],
                                "max_position_type": row["max_position_type"],
                                "number_order": 1,
                                "creator": creator_id,
                            },
                        )
                else:
                    for row in plan.open_total_rows:
                        row_id_value = self._next_value(connection, "TEMP_OPENTOTALLIMIT_SEQ")
                        row_id = str(row_id_value)
                        open_total_ids.append(row_id)
                        connection.execute(
                            text(
                                "INSERT INTO TEMP_OPENTOTALLIMIT "
                                "(ID, TEMPLATEID, INSTRUMENTID, LIMITVOLUME, LIMITWARNVOLUME, ISPRODUCT, ISOPT, ONLYDEPTH, CREATOR) "
                                "VALUES (:id, :template_id, :instrument_id, :limit_volume, :limit_warn_volume, :is_product, :is_opt, :only_depth, :creator)"
                            ),
                            {
                                "id": row_id_value,
                                "template_id": template_id_value,
                                "instrument_id": row["instrument_id"],
                                "limit_volume": row["limit_volume"],
                                "limit_warn_volume": row["limit_warn_volume"],
                                "is_product": row["is_product"],
                                "is_opt": row["is_opt"],
                                "only_depth": row["only_depth"],
                                "creator": creator_id,
                            },
                        )
                return OracleWriteResult(template_id, position_detail_ids, position_number_ids, open_total_ids)
        except OracleImportError:
            raise
        except Exception as error:
            raise OracleImportError(f"Oracle事务写入失败，事务已回滚：{error}") from error
