# -*- coding: utf-8 -*-
"""2026-11-21 「MA3连3日」降亏筛选打标单测(§5.4 基准外纯新增字段, 默认关)。

被测 = app/queries.py 三个纯函数(无 DB / 无网络 / 无外发):
- _ma3_consec_below: 连续 3 日收盘 < MA3 判定 + 防前视切片 + 数据不足保守放行(na)
- _ma3_pick_top_etf: top1 选取与前端 _topEtfByScore 同源(_bk_top/_bk_ts 冻结优先)
- _ma3_tag_sig: 单条信号打标(买入类由 overview 循环按 _MA3_BUY_SIGNALS 筛后再调)

硬性覆盖(需求 §5.1⑥ 防前视 + 报告验收口径):
① T+1 及之后数据变化不影响 T 日判定(截断一致性)
② 连续 2 日不算 / 第 3 日才算; 收盘==MA3 不算低于(严格小于)
③ T 日缺收盘 / 历史不足 → status="na"(前端保持亮显, 不误灰)
④ 买入 4 类才打标(卖类不进 _MA3_BUY_SIGNALS); self ETF 走 index_daily.close 分支
⑤ top1 冻结权威优先于 track_score

冻结运行日说明: 被测函数全部接收显式 sig_date 参数, 内部不取 today()/now(),
故本文件不存在跨天红风险(§18 L51); 断言全为逐位等值, 无时间敏感项。
"""
import pytest

from app.queries import (
    _MA3_BUY_SIGNALS,
    _ma3_consec_below,
    _ma3_pick_top_etf,
    _ma3_tag_sig,
)


def _series(vals, start_day=1):
    """把收盘序列映射到 2026-01-DD 日期字符串(YYYYMMDD, 与库内格式一致)。"""
    return {f"202601{d:02d}": float(v) for d, v in enumerate(vals, start=start_day)}


# ===== _ma3_consec_below =====

def test_hit_three_consecutive_days_below_ma3():
    cm = _series([10, 9, 8, 7, 6])  # 下降序列: 末 3 日收盘均低于各自 MA3
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is True
    assert detail["status"] == "ok"
    assert detail["ma3"] == pytest.approx(7.0)   # mean(8,7,6)
    assert detail["close"] == pytest.approx(6.0)
    assert detail["days"] == 3


def test_two_days_below_is_not_hit():
    # 第 3 个交易日收盘 20 > MA3(13), 只有更早的两日低于均线 → 不命中
    cm = _series([10, 9, 20, 21, 22])
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is False
    assert detail["status"] == "ok"


def test_last_day_above_ma3_is_not_hit():
    # 前两日低于、最后一日收盘 4 > MA3(2) → 不命中(逐日都要低于)
    cm = _series([10, 1, 2, 3, 4])
    hit, _ = _ma3_consec_below(cm, "20260105")
    assert hit is False


def test_close_equal_to_ma3_is_not_below():
    # 严格小于: 横盘时 close == MA3 不算 "低于"
    cm = _series([5, 5, 5, 5, 5])
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is False
    assert detail["ma3"] == pytest.approx(5.0)


def test_no_lookahead_future_dates_do_not_change_result():
    """防前视核心用例: 截断到 T 与实际含 T+N 数据算出的结果必须逐位一致。"""
    t_cut = _series([10, 9, 8, 7, 6])
    future = dict(t_cut)
    future.update(_series([100, 200, 300, 400, 500], start_day=6))  # T+1 起单边暴涨
    r1 = _ma3_consec_below(t_cut, "20260105")
    r2 = _ma3_consec_below(future, "20260105")
    assert r1 == r2, f"防前视失败: 未来数据影响了 T 日判定 r1={r1} r2={r2}"
    # 反向对照(证明本用例有判别力): 同样的含未来数据序列, 若把判定日改到 20260110,
    # 末 3 日收盘 300/400/500 均高于各自 MA3 → False, 与 T 日判定结果不同。
    r_bad = _ma3_consec_below(future, "20260110")
    assert r_bad[0] is False


def test_missing_sig_date_close_is_na():
    # 序列只到 T-1, T 日收盘未入库 → 不可判, 保守放行
    cm = _series([10, 9, 8, 7], start_day=1)
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is None
    assert detail["status"] == "na"
    assert detail["reason"] == "no_sig_date_close"


def test_future_only_data_without_sig_date_is_na():
    # 只有 T+1 及之后的数据(极端滞后/错位情形)同样判 na, 绝不拿未来数据凑 T 日
    cm = {"20260106": 1.0, "20260107": 2.0, "20260108": 3.0}
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is None
    assert detail["reason"] == "no_sig_date_close"


def test_short_history_is_na():
    # 含 T 日仅 4 个收盘(< days+2=5), 算不出 3 个完整 MA3 → na
    cm = _series([10, 9, 8, 7])
    hit, detail = _ma3_consec_below(cm, "20260104")
    assert hit is None
    assert detail["reason"] == "short_history"


def test_exactly_five_closes_is_enough():
    cm = _series([10, 9, 8, 7, 6])
    assert _ma3_consec_below(cm, "20260105")[1]["status"] == "ok"


@pytest.mark.parametrize("cm,sig_date", [(None, "20260105"), ({}, "20260105"), (_series([1, 2]), None)])
def test_no_data_is_na(cm, sig_date):
    hit, detail = _ma3_consec_below(cm, sig_date)
    assert hit is None
    assert detail == {"status": "na", "reason": "no_data"}


def test_non_numeric_close_ignored():
    # 非数值收盘(脏数据/None)按缺失剔除, 不进序列
    cm = {"20260101": 10.0, "20260102": 9.0, "20260103": 8.0,
          "20260104": 7.0, "20260105": 6.0, "20260106": None}
    hit, detail = _ma3_consec_below(cm, "20260105")
    assert hit is True
    assert detail["status"] == "ok"


# ===== _ma3_pick_top_etf =====

def test_bk_top_with_frozen_score_wins():
    etfs = [
        {"code": "510300", "track_score": 0.9, "similarity": 0.9},
        {"code": "159915", "track_score": 0.2, "_bk_top": True, "_bk_ts": 0.1},
    ]
    top = _ma3_pick_top_etf(etfs)
    assert top["code"] == "159915"
    # _bk_ts 覆盖 track_score 后返回, 原列表元素不被改动
    assert top["track_score"] == 0.1
    assert etfs[1]["track_score"] == 0.2


def test_bk_top_without_ts_returned_as_is():
    etfs = [{"code": "A", "track_score": 0.9}, {"code": "B", "_bk_top": True}]
    assert _ma3_pick_top_etf(etfs)["code"] == "B"


def test_max_track_score_then_similarity():
    etfs = [
        {"code": "A", "track_score": 0.5, "similarity": 0.9},
        {"code": "B", "track_score": 0.8, "similarity": 0.1},
        {"code": "C", "track_score": 0.8, "similarity": 0.7},
    ]
    assert _ma3_pick_top_etf(etfs)["code"] == "C"


def test_missing_scores_sort_last():
    etfs = [{"code": "A"}, {"code": "B", "track_score": 0.01}]
    assert _ma3_pick_top_etf(etfs)["code"] == "B"


@pytest.mark.parametrize("etfs", [None, [], ["not-a-dict"], [1, 2]])
def test_no_valid_etf_returns_none(etfs):
    assert _ma3_pick_top_etf(etfs) is None


# ===== _ma3_tag_sig =====

def test_tag_buy_signal_with_etf_cache():
    sig = {"date": "20260105", "index_id": "csi300", "signal": "buy",
           "etfs": [{"code": "510300", "track_score": 0.9, "match_method": "track"}]}
    out = _ma3_tag_sig(sig, {"510300": _series([10, 9, 8, 7, 6])}, lambda _i: {})
    assert out["hit"] is True
    assert out["status"] == "ok"
    assert out["reason"] is None
    assert out["etf"] == "510300"
    assert out["ma3"] == pytest.approx(7.0)
    assert out["close"] == pytest.approx(6.0)


def test_tag_no_etf_is_na():
    out = _ma3_tag_sig({"date": "20260105", "etfs": []}, {}, lambda _i: {})
    assert out == {"hit": None, "status": "na", "reason": "no_etf", "etf": None}


def test_tag_self_etf_uses_index_close_map():
    calls = []

    def _load(index_id):
        calls.append(index_id)
        return _series([10, 9, 8, 7, 6])

    sig = {"date": "20260105", "index_id": "cgb_10y_etf", "signal": "buy",
           "etfs": [{"code": "511260", "match_method": "self", "track_score": 0.3}]}
    out = _ma3_tag_sig(sig, {}, _load)  # ETF 缓存故意为空: 命中只可能来自 index 收盘
    assert calls == ["cgb_10y_etf"]
    assert out["hit"] is True
    assert out["etf"] == "511260"


def test_tag_etf_cache_missing_code_is_na():
    sig = {"date": "20260105", "index_id": "x", "signal": "buy",
           "etfs": [{"code": "999999", "track_score": 0.9, "match_method": "track"}]}
    out = _ma3_tag_sig(sig, {}, lambda _i: {})
    assert out["hit"] is None
    assert out["status"] == "na"
    assert out["reason"] == "no_data"
    assert out["etf"] == "999999"


# ===== 打标范围契约 =====

def test_buy_signal_set_is_exactly_four_buy_classes():
    # 只给买入 4 类打标; 卖类/波段不进入(§23.6 MED3 同精神: 非买不判降亏)
    assert _MA3_BUY_SIGNALS == {"buy", "buy_aux", "buy_special", "buy_backup"}
    for sell in ("sell", "sell_stop_loss", "band_hold", "band_sell"):
        assert sell not in _MA3_BUY_SIGNALS
