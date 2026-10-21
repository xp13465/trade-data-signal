"""东财可转债「价值分析-溢价率」采集:按 API 字段名对齐,不依赖 akshare 的位置式列名表。

背景(2026-10-21 P1,cov_premium_median 恒 error):
- akshare 1.18.64(本项目 pin)的 `bond_zh_cov_value_analysis` 在
  `akshare/bond/bond_zh_cov.py:651` 用 `temp_df.columns = [13 个中文名]` **按位置**重命名;
- 东财 datacenter 接口 `RPTA_WEB_KZZ_LS` 的返回字段已由 13 个扩到 15 个
  (新增 FLOORPRICE_PREMIUM_RATIO_CB / BOND_NAME_ABBR),pandas 直接抛
  `Length mismatch: Expected axis has 15 elements, new values have 13 elements`,
  采集恒失败、collect_health 常驻 error。
- §5.1 先例核查:社区同型报错(akshare issue #4910)官方回复「升级到最新版」;但本机核对
  akshare **最新 1.19.1** 源码,该函数仍写死 13 个列名 ⇒ 升级不解决。故在采集层自带
  一份「按 API 字段名取值」的实现(接口本来返回 list[dict],字段名现成,无需位置假设)。

语义约定(字段缺失时明确处理,禁止静默错位):
- 必需字段缺失(`SWAPOR` 转股溢价率):抛 CovValueSchemaError(带实际字段名清单),
  采集层按失败上报(不写错值)。
- 可选字段缺失(收盘价/转股价值/纯债价值/纯债溢价率):该列置 NaN(等价 DB NULL),
  不影响计算。
- 必需字段为空的**行**:跳过(不参与 median),避免 NaN 流入入库链路。
- 接口新增的未知字段:忽略(按名取值天然不受列数变化影响),字段名记在
  `df.attrs["ignored_fields"]` 供排查。

输出列序/类型与 akshare 原实现保持一致(日期为 date 对象,数值列 to_numeric),
消费方 `fetchers.collect_snapshot` + `config/indicators.yaml` 的 `column: 转股溢价率`
无需改动。
"""
from __future__ import annotations

import pandas as pd

from .base import em_get

URL = "https://datacenter-web.eastmoney.com/api/data/get"
# 东财 RPTA_WEB_KZZ_LS 固定参数(p 分页从 1 起,ps 上限取 8000 与 akshare 原实现一致)
BASE_PARAMS = {
    "sty": "ALL",
    "token": "894050c76af8597a853f5b408b759f5d",
    "st": "date",
    "sr": "1",
    "source": "WEB",
    "type": "RPTA_WEB_KZZ_LS",
}

DATE_FIELD = "DATE"
# API 字段名 -> 语义列名(仅映射我们使用的 5 个数值字段 + 日期;其余字段忽略)
FIELD_MAP = {
    "SWAPVALUE": "转股价值",
    "PUREBONDVALUE": "纯债价值",
    "PUREBONDOR": "纯债溢价率",
    "SWAPOR": "转股溢价率",
    "FCLOSE": "收盘价",
}
REQUIRED_FIELDS = ("SWAPOR",)  # 入库计算(median)唯一必需字段
OUTPUT_COLUMNS = ["日期", "收盘价", "纯债价值", "转股价值", "纯债溢价率", "转股溢价率"]


class CovValueSchemaError(ValueError):
    """接口字段缺失(必需字段不在返回里):失败要响亮,不允许静默置空/错位。"""


def parse_value_analysis(data_json: dict) -> pd.DataFrame:
    """把东财 RPTA_WEB_KZZ_LS 的 JSON 解析成 DataFrame(按字段名,纯函数,可离线测试)。

    Args:
        data_json: 接口原始 JSON(`{"result": {"data": [ {...}, ... ]}}` 或 result 为 None)。
    Returns:
        列 = OUTPUT_COLUMNS(空结果也返回同列的空表);数值列 float,日期列 date。
    Raises:
        CovValueSchemaError: 返回行里有必需字段缺失(SWAPOR)。
        ValueError: 返回体结构不是 list[dict](源契约变了,必须显式报错)。
    """
    result = data_json.get("result") if isinstance(data_json, dict) else None
    rows = (result or {}).get("data") or []
    if not rows:
        # 无数据:返回结构完整的空表(采集层据此判 empty,不写值)
        return pd.DataFrame({c: pd.Series(dtype="object") for c in OUTPUT_COLUMNS})

    if not all(isinstance(r, dict) for r in rows):
        raise ValueError(
            f"RPTA_WEB_KZZ_LS 返回不是 list[dict](首行类型={type(rows[0]).__name__}),"
            "源契约已变,拒绝猜测列含义"
        )

    present = set(rows[0].keys())
    missing_required = [f for f in REQUIRED_FIELDS if f not in present]
    if missing_required:
        raise CovValueSchemaError(
            "东财可转债价值分析缺少必需字段 "
            f"{[(f, FIELD_MAP[f]) for f in missing_required]};实际字段={sorted(present)}"
        )

    df = pd.DataFrame(rows)
    out = pd.DataFrame(index=df.index)
    out["日期"] = (
        pd.to_datetime(df[DATE_FIELD], errors="coerce").dt.date
        if DATE_FIELD in df.columns
        else pd.NaT
    )
    for api_field in ("FCLOSE", "PUREBONDVALUE", "SWAPVALUE", "PUREBONDOR", "SWAPOR"):
        col = FIELD_MAP[api_field]
        if api_field in df.columns:
            out[col] = pd.to_numeric(df[api_field], errors="coerce")
        else:
            # 可选字段缺失:明确置 NaN(DB NULL),不猜位置
            out[col] = float("nan")

    # 必需字段为空的行跳过(median 的输入必须可判),不让 NaN 流进入库链路
    out = out[out["转股溢价率"].notna()].reset_index(drop=True)
    out.attrs["ignored_fields"] = sorted(present - set(FIELD_MAP) - {DATE_FIELD})
    return out[OUTPUT_COLUMNS]


def fetch_value_analysis(symbol: str = "113527") -> pd.DataFrame:
    """拉单只可转债价值分析历史(默认 symbol 沿用 akshare 缺省 113527,保持冻结口径)。"""
    params = dict(BASE_PARAMS)
    params.update({"filter": f'(zcode="{symbol}")', "p": "1", "ps": "8000"})
    resp = em_get(URL, params=params, timeout=15)
    resp.raise_for_status()
    return parse_value_analysis(resp.json())