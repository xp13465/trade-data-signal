# -*- coding: utf-8 -*-
"""cov_premium_median 采集列错位回归(2026-10-21 P1)。

根因:akshare `bond_zh_cov_value_analysis` 在 akshare/bond/bond_zh_cov.py:651 按**位置**
写死 13 个中文列名,而东财 `RPTA_WEB_KZZ_LS` 返回字段已扩到 15 个
(新增 FLOORPRICE_PREMIUM_RATIO_CB / BOND_NAME_ABBR)⇒ pandas 抛
`Length mismatch: Expected axis has 15 elements, new values have 13 elements`,
线上 collect_health 常驻 error。

修复:`app/collector/cov_value.py` 按 **API 字段名**解析(接口本来就返回 list[dict],
字段名现成),`fetchers.collect_snapshot` 对该 func 改走本地解析。

本文件覆盖(两版列序夹具 + 边界):
1) 15 字段(新)夹具解析,值/中位数正确;
2) 13 字段(旧)夹具与 15 字段结果逐位一致(向后兼容);
3) 字段顺序打乱仍一致(证「按名不按位置」,防再退化成位置取列);
4) 必需字段 SWAPOR 缺失 → 显式报错(不静默错位);
5) 可选字段(收盘价)缺失 → 该列 NaN,其余照算;
6) 必需字段为空的行 → 跳过,不参与 median;
7) result=None → 结构完整的空表(不炸);
8) 返回行不是 dict → 显式报错(源契约变了不猜);
9) 接线:fetchers.collect_snapshot 走本地解析 + median 取对(monkeypatch 网络,不触网)。

纪律:不写死「当天日期」(夹具日期为固定历史值,被测代码的 today 判定用
last_trading_day() 现算,符合 §5.4⑦/L51 时敏约束);零网络、零通知外发。
"""
import pandas as pd
import pytest

from app.collector import cov_value, fetchers

# ── 夹具:东财 RPTA_WEB_KZZ_LS 真实返回字段(2026-10-21 实拉核对)────────────────
# 15 字段版(当前线上);13 字段版 = 去掉末尾两个新增字段(旧版)。
ROW15 = [
    {
        "DATE": "2024-01-02 00:00:00",
        "ZCODE": "113527",
        "SECURITYVARIETYCODE": "1001746879",
        "SWAPVALUE": 100.0,
        "PUREBONDVALUE": 90.0,
        "PUREBONDOR": 10.0,
        "SWAPOR": 20.0,
        "FCLOSE": 120.0,
        "SWAPPRICE": None,
        "USWAPTVOL": None,
        "USWAPTRATE": None,
        "SYFE": None,
        "SECUCODE": "113527.SH",
        "FLOORPRICE_PREMIUM_RATIO_CB": 0.0944,
        "BOND_NAME_ABBR": "维格转债",
    },
    {
        "DATE": "2024-01-03 00:00:00",
        "ZCODE": "113527",
        "SECURITYVARIETYCODE": "1001746879",
        "SWAPVALUE": 101.0,
        "PUREBONDVALUE": 90.5,
        "PUREBONDOR": 10.5,
        "SWAPOR": 30.0,
        "FCLOSE": 121.0,
        "SWAPPRICE": None,
        "USWAPTVOL": None,
        "USWAPTRATE": None,
        "SYFE": None,
        "SECUCODE": "113527.SH",
        "FLOORPRICE_PREMIUM_RATIO_CB": 0.0951,
        "BOND_NAME_ABBR": "维格转债",
    },
    {  # 必需字段为空的行走「跳过」分支,不参与 median
        "DATE": "2024-01-04 00:00:00",
        "ZCODE": "113527",
        "SECURITYVARIETYCODE": "1001746879",
        "SWAPVALUE": None,
        "PUREBONDVALUE": None,
        "PUREBONDOR": None,
        "SWAPOR": None,
        "FCLOSE": None,
        "SWAPPRICE": None,
        "USWAPTVOL": None,
        "USWAPTRATE": None,
        "SYFE": None,
        "SECUCODE": "113527.SH",
        "FLOORPRICE_PREMIUM_RATIO_CB": None,
        "BOND_NAME_ABBR": "维格转债",
    },
]
NEW_EXTRA_FIELDS = ("FLOORPRICE_PREMIUM_RATIO_CB", "BOND_NAME_ABBR")
ROWS13 = [{k: v for k, v in r.items() if k not in NEW_EXTRA_FIELDS} for r in ROW15]
ROWS15 = [dict(r) for r in ROW15]


def _payload(rows):
    return {"result": {"data": rows}}


def _median(df):
    return float(df["转股溢价率"].median())


# ── 1/2/3 两版列序 + 顺序无关 ─────────────────────────────────────────────────
def test_new_15_field_payload_parses_and_median_correct():
    df = cov_value.parse_value_analysis(_payload(ROWS15))
    assert list(df.columns) == cov_value.OUTPUT_COLUMNS
    assert len(df) == 2  # 第 3 行必需字段为空被跳过
    assert _median(df) == pytest.approx(25.0)
    assert df["收盘价"].tolist() == [120.0, 121.0]
    assert df["转股价值"].tolist() == [100.0, 101.0]
    # 日期保持 date 对象(与 akshare 原实现一致)
    assert df["日期"].iloc[0].isoformat() == "2024-01-02"


def test_old_13_field_payload_still_parses_same_values():
    df_old = cov_value.parse_value_analysis(_payload(ROWS13))
    df_new = cov_value.parse_value_analysis(_payload(ROWS15))
    pd.testing.assert_frame_equal(df_old, df_new)


def test_field_order_does_not_matter():
    # 把字段顺序整体倒过来:按位置取列的实现会算错/报错,按名取列必须完全一致
    reversed_rows = [dict(reversed(list(r.items()))) for r in ROWS15]
    df_rev = cov_value.parse_value_analysis(_payload(reversed_rows))
    df_norm = cov_value.parse_value_analysis(_payload(ROWS15))
    pd.testing.assert_frame_equal(df_rev, df_norm)


# ── 4/5 字段缺失的明确语义 ───────────────────────────────────────────────────
def test_missing_required_field_raises_explicit_error():
    rows = [{k: v for k, v in r.items() if k != "SWAPOR"} for r in ROWS15]
    with pytest.raises(cov_value.CovValueSchemaError) as ei:
        cov_value.parse_value_analysis(_payload(rows))
    msg = str(ei.value)
    assert "SWAPOR" in msg and "转股溢价率" in msg  # 报错必须点名缺了哪个字段
    assert "ZCODE" in msg  # 带实际字段清单,便于排查源契约变化


def test_missing_optional_field_becomes_nan_not_error():
    rows = [{k: v for k, v in r.items() if k != "FCLOSE"} for r in ROWS15]
    df = cov_value.parse_value_analysis(_payload(rows))
    assert df["收盘价"].isna().all()  # 置 NULL,不猜列
    assert _median(df) == pytest.approx(25.0)  # 其余照算


# ── 6/7/8 空值行 / 空结果 / 结构异常 ─────────────────────────────────────────
def test_rows_with_empty_required_value_are_skipped():
    df = cov_value.parse_value_analysis(_payload(ROWS15))
    assert "2024-01-04" not in df["日期"].astype(str).tolist()


def test_none_result_returns_empty_frame_with_columns():
    df = cov_value.parse_value_analysis({"result": None})
    assert len(df) == 0
    assert list(df.columns) == cov_value.OUTPUT_COLUMNS


def test_non_dict_rows_raise_instead_of_guessing():
    with pytest.raises(ValueError):
        cov_value.parse_value_analysis({"result": {"data": [[1, 2, 3]]}})


# ── 9 接线:collect_snapshot 用本地解析并取到 median ──────────────────────────
def test_collect_snapshot_uses_name_based_parser(monkeypatch):
    from app.calendar import last_trading_day

    def _fake_fetch(symbol="113527"):
        assert symbol == "113527"  # 配置无 params 时沿用 akshare 缺省口径(冻结契约不变)
        return cov_value.parse_value_analysis(_payload(ROWS15))

    monkeypatch.setattr(cov_value, "fetch_value_analysis", _fake_fetch)
    metric = {
        "id": "cov_premium_median",
        "func": "bond_zh_cov_value_analysis",
        "column": "转股溢价率",
        "transform": "median",
        "unit": "%",
    }
    # date 用同一个 last_trading_day() 现算(不写死当天,时敏约束见模块 docstring)
    val, msg = fetchers.collect_snapshot(metric, last_trading_day())
    assert msg == "ok", msg
    assert val == pytest.approx(25.0)