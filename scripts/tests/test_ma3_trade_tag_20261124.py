# -*- coding: utf-8 -*-
"""2026-11-24 MA3(连3日)进信号凯利回测: 打标列/判定/注入单测(§5.4 纯新增字段, 默认关)。

被测 = scripts/signal_kelly_backtest.py(无 DB 写 / 无网络 / 无外发):
- TRADE_FIELDS 第 28 列 ma3: 追加在末尾, 既有 27 列索引/列序零位移
- _ma3_trade_tag: "hit"/"miss"/"na" 状态码映射(判定逻辑单一事实源 = app/ma3.py)
- _classify_buy_rows: ma3 注入全部 10 个卖出模式 + 全部命中象限(基笔级常量)
- _build_unique_tables: ma3 归入共享字段(19+1=20), 无损还原总列数 = 28

硬性覆盖(任务书块 2 验收口径):
① 列数 28 且末列 = ma3, 前 27 列顺序逐位不变
② 抽笔复算: 按 etf/{code}-all.json 前复权 close 手工推 MA3, 与打标结果逐位一致
③ 防前视: T+1 及之后数据写入文件后, T 日打标不变(截断一致性)
④ T 日缺收盘 / 历史不足 / 无文件 → "na"(保守放行, 前端不剔除)
⑤ self ETF 走 index_daily.close 注入的回调分支
⑥ 注入覆盖面: 10 模式 + 多象限全部带同一 ma3 值; 唯一化三表 share_fields 含 ma3

冻结运行日说明: 全部用例喂显式信号日/固定日期键, 被测代码内部不取 today()/now()
(§18 L51); 断言全为逐位等值, 无时间敏感项。
"""
import json
from pathlib import Path

import pytest

import signal_kelly_backtest as skb

# 2026-11-24 前生产 schema 27 列(冻结快照): 新增列必须追加在末尾, 不允许中间插入位移。
_LEGACY_FIELDS = [
    "signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
    "track_tier", "track_score", "match_method", "track_low_confidence",
    "buy_price", "sell_price", "shares", "profit", "return_pct",
    "hold_days", "sell_reason", "current_price", "real_buy_price", "real_buy_date",
    "real_current_price",
    "market_state", "market_tier", "market_tier_all", "market_tier_cyb", "rating",
]


def test_trade_fields_appends_ma3_as_28th_without_shifting():
    assert len(_LEGACY_FIELDS) == 27
    assert len(skb.TRADE_FIELDS) == 28
    assert skb.TRADE_FIELDS[:27] == _LEGACY_FIELDS, "既有 27 列顺序不得位移(下游按索引读)"
    assert skb.TRADE_FIELDS[-1] == "ma3"


# ===== 打标: 数据源 = etf/{code}-all.json 前复权 close =====

def _write_etf_file(dirpath, code, ohlc):
    p = Path(dirpath) / ("%s-all.json" % code)
    p.write_text(json.dumps({
        "date": "20260105", "code": code, "name": "x", "count": len(ohlc),
        "adj": "forward_accum_nav", "ohlc": ohlc,
    }), encoding="utf-8")
    return p


@pytest.fixture
def etf_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MA3_ETF_DATA_DIR", str(tmp_path))
    skb._MA3_BT_ETF_CACHE.clear()
    yield tmp_path
    skb._MA3_BT_ETF_CACHE.clear()


def test_tag_hit_from_forward_adjusted_close(etf_dir):
    # 下降序列: 末 3 日(8,7,6)均低于各自 MA3 → hit
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 6), [10, 9, 8, 7, 6])
    ])
    assert skb._ma3_trade_tag("20260105", "csi300", "510300", "track") == "hit"


def test_tag_miss_when_last_close_above_ma3(etf_dir):
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 6), [10, 1, 2, 3, 4])
    ])
    assert skb._ma3_trade_tag("20260105", "csi300", "510300", "track") == "miss"


def test_tag_strictly_less_than_boundary(etf_dir):
    """判别力(严格小于): 收盘恰好等于 MA3 时不得判 hit。

    全平序列 9,9,9,9,9 → 每日收盘 == 各自 MA3;若误写成 <= 则判 hit,
    正确语义(严格低于)必须判 miss。这是「严格小于」与「小于等于」的唯一边界。
    """
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, 9.0] for d in range(1, 6)
    ])
    assert skb._ma3_trade_tag("20260105", "csi300", "510300", "track") == "miss"


def test_tag_ignores_accum_nav_uses_close_column(etf_dir):
    """判别力: 同一文件里 ohlc 前 3 列(开高低)不是判定源, 第 5 列 close 才是。"""
    # close 序列下降=hit; 若误用第 2 列(开)则横盘/上行 → 结论会不同
    _write_etf_file(etf_dir, "159501", [
        ["20260101", 9.0, 0, 0, 10.0], ["20260102", 9.0, 0, 0, 9.0],
        ["20260103", 9.0, 0, 0, 8.0], ["20260104", 9.0, 0, 0, 7.0],
        ["20260105", 9.0, 0, 0, 6.0],
    ])
    assert skb._ma3_trade_tag("20260105", "us_ndx", "159501", "track") == "hit"


def test_tag_na_when_signal_day_close_missing(etf_dir):
    # 序列只到 T-1 → 不可判(T 日收盘未入库), 保守放行
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 5), [10, 9, 8, 7])
    ])
    assert skb._ma3_trade_tag("20260105", "csi300", "510300", "track") == "na"


def test_tag_na_when_history_short(etf_dir):
    # 含 T 日仅 4 个收盘(< days+2=5) → 算不出 3 个完整 MA3
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 5), [10, 9, 8, 7])
    ])
    assert skb._ma3_trade_tag("20260104", "csi300", "510300", "track") == "na"


def test_tag_na_when_file_missing(etf_dir):
    assert skb._ma3_trade_tag("20260105", "csi300", "999999", "track") == "na"


def test_tag_na_when_no_etf_code():
    assert skb._ma3_trade_tag("20260105", "csi300", "", "track") == "na"


def test_tag_no_lookahead_future_rows_do_not_change_t_tag(etf_dir):
    """防前视: 文件里追加 T+1 起的暴涨行后, T 日打标必须逐位不变。"""
    base = [[f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 6), [10, 9, 8, 7, 6])]
    _write_etf_file(etf_dir, "510300", base)
    tag_t = skb._ma3_trade_tag("20260105", "csi300", "510300", "track")
    future = base + [[f"2026011{d}", 0, 0, 0, v] for d, v in zip(range(0, 5), [100, 200, 300, 400, 500])]
    _write_etf_file(etf_dir, "510300", future)
    skb._MA3_BT_ETF_CACHE.clear()  # 强制重读新文件
    assert skb._ma3_trade_tag("20260105", "csi300", "510300", "track") == tag_t == "hit"
    # 判别力: 若把判定日挪到未来末日, 结果确实不同(证明未来行真的在文件里)
    assert skb._ma3_trade_tag("20260114", "csi300", "510300", "track") == "miss"


def test_tag_manual_recompute_bit_identical(etf_dir):
    """抽笔复算(任务书块 2 验收②): 手工按 close 算 MA3 与打标结论逐位一致。"""
    closes = [2.187, 2.187, 2.178, 2.146, 2.142]
    dates = ["20261019", "20261020", "20261021", "20261022", "20261023"]
    _write_etf_file(etf_dir, "159501", [[d, 0, 0, 0, c] for d, c in zip(dates, closes)])
    tagged = skb._ma3_trade_tag("20261023", "us_ndx", "159501", "track")
    # 手工复算: 最后 3 日收盘 2.178/2.146/2.142 与各自 MA3 比较
    manual = all(
        closes[i] < (closes[i - 2] + closes[i - 1] + closes[i]) / 3.0
        for i in (2, 3, 4)
    )
    assert tagged == ("hit" if manual else "miss") == "hit"


def test_tag_self_etf_uses_index_close_map(monkeypatch):
    calls = []

    def fake_index_map(iid):
        calls.append(iid)
        return {f"2026010{d}": v for d, v in zip(range(1, 6), [10, 9, 8, 7, 6])}

    monkeypatch.setattr(skb, "_ma3_bt_index_close_map", fake_index_map)
    assert skb._ma3_trade_tag("20260105", "cgb_10y_etf", "511260", "self") == "hit"
    assert calls == ["cgb_10y_etf"]


# ===== 注入覆盖面: _classify_buy_rows 10 模式 + 多象限 =====

def test_classify_injects_ma3_into_every_mode_and_quadrant(monkeypatch):
    monkeypatch.setattr(skb, "_resolve_etf", lambda *a, **k: (
        dict(code="510300", name="fixture ETF", track_tier="strong", match_method="track"), False))
    monkeypatch.setattr(skb, "_backtest_one", lambda *a, **k: dict(etf_code=a[3], mode=k.get("sell_mode")))
    monkeypatch.setattr(skb, "_is_market_bull", lambda *a, **k: True)
    monkeypatch.setattr(skb, "_market_tier_at", lambda *a, **k: "tier1")
    tag_calls = []

    def tag_fn(date, iid, code, mm):
        tag_calls.append((date, iid, code, mm))
        return "hit"

    quadrants, stats = skb._classify_buy_rows(
        [("20260105", "csi300", "buy")], {}, {},
        {"csi300": {"buy": {"10d": {"score": 0.8}}}}, {"csi300": "a"},
        {}, {}, {}, {"510300": ["20260105", "20260106"]}, {},
        {}, [], {}, [], "20260106", None, ma3_tag_fn=tag_fn,
    )
    assert stats["classified"] == 1
    # 每基笔只打标一次(10 模式共享), 不重复读文件
    assert tag_calls == [("20260105", "csi300", "510300", "track")]
    for qk, mk_map in quadrants.items():
        for mk, rows in mk_map.items():
            for r in rows:
                assert r["ma3"] == "hit", f"{qk}/{mk} 注入缺失或值漂移"


def test_build_unique_tables_ma3_is_shared_field():
    trade = {"etf_code": "510300", "ma3": "hit"}
    for f in skb.TRADE_FIELDS:
        trade.setdefault(f, "")
    row = [trade.get(f, "") for f in skb.TRADE_FIELDS]  # 生产调用形态: trades 列式行(list)
    quadrants = {qk: {mk: [] for mk in skb.SELL_MODES} for qk in skb.QUADRANT_META}
    quadrants["rating_high"]["A"].append(row)
    u = skb._build_unique_tables(quadrants)
    assert "ma3" in u["fields"], "ma3 是基笔级常量, 必须进共享字段(否则每 mode 重复存 10 份)"
    assert "ma3" not in u["variant_fields"]
    assert len(u["fields"]) == 20
    assert len(u["fields"]) + len(u["variant_fields"]) == len(skb.TRADE_FIELDS) == 28
    assert u["base"][0][u["fields"].index("ma3")] == "hit"
