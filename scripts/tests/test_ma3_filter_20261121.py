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
import json
import re
from pathlib import Path

import pytest

from app.queries import (
    _MA3_BUY_SIGNALS,
    _MA3_ETF_CLOSE_CACHE,
    _ma3_consec_below,
    _ma3_etf_close_map,
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


# ===== etf/{code}-all.json 前复权收盘加载(与回测同源, P1-1) =====

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
    _MA3_ETF_CLOSE_CACHE.clear()
    yield tmp_path
    _MA3_ETF_CLOSE_CACHE.clear()


def test_etf_close_map_reads_ohlc_close_column(etf_dir):
    _write_etf_file(etf_dir, "510300", [
        ["20260101", 1.0, 1.1, 0.9, 10.0],
        ["20260102", 1.0, 1.1, 0.9, 9.0],
        ["20260103", 1.0, 1.1, 0.9, None],   # 非数值收盘按缺失剔除
    ])
    m = _ma3_etf_close_map("510300")
    assert m == {"20260101": 10.0, "20260102": 9.0}


def test_etf_close_map_missing_file_is_empty(etf_dir):
    assert _ma3_etf_close_map("999999") == {}


def test_etf_close_map_mtime_cache_invalidation(etf_dir):
    p = _write_etf_file(etf_dir, "510300", [["20260101", 0, 0, 0, 10.0]])
    assert _ma3_etf_close_map("510300") == {"20260101": 10.0}
    # 内容不变时命中缓存(同一 dict 对象)
    assert _ma3_etf_close_map("510300") is _MA3_ETF_CLOSE_CACHE["510300"][1]
    # 重写文件(mtime 变化) -> 自动重载新值
    import os
    import time
    time.sleep(0.01)
    _write_etf_file(etf_dir, "510300", [["20260101", 0, 0, 0, 11.0]])
    os.utime(p, None)
    assert _ma3_etf_close_map("510300") == {"20260101": 11.0}


# ===== _ma3_tag_sig =====

def test_tag_buy_signal_uses_etf_file_close(etf_dir):
    _write_etf_file(etf_dir, "510300", [
        [f"2026010{d}", 0, 0, 0, v] for d, v in zip(range(1, 6), [10, 9, 8, 7, 6])
    ])
    sig = {"date": "20260105", "index_id": "csi300", "signal": "buy",
           "etfs": [{"code": "510300", "track_score": 0.9, "match_method": "track"}]}
    out = _ma3_tag_sig(sig, lambda _i: {})
    assert out["hit"] is True
    assert out["status"] == "ok"
    assert out["reason"] is None
    assert out["etf"] == "510300"
    assert out["ma3"] == pytest.approx(7.0)
    assert out["close"] == pytest.approx(6.0)


def test_tag_does_not_use_accum_nav_source(etf_dir):
    """P1-1 判别力: 文件 close 判命中、若误用 accum_nav 则判不命中, 断言跟随文件。"""
    _write_etf_file(etf_dir, "159501", [
        ["20261019", 0, 0, 0, 2.187], ["20261020", 0, 0, 0, 2.187],
        ["20261021", 0, 0, 0, 2.178], ["20261022", 0, 0, 0, 2.146],
        ["20261023", 0, 0, 0, 2.142],
    ])
    sig = {"date": "20261023", "index_id": "us_ndx", "signal": "buy",
           "etfs": [{"code": "159501", "track_score": 0.9, "match_method": "track"}]}
    out = _ma3_tag_sig(sig, lambda _i: {})
    assert out["hit"] is True, "必须按 etf/{code}-all.json 前复权 close 判定(回测同源)"


def test_tag_no_etf_is_na():
    out = _ma3_tag_sig({"date": "20260105", "etfs": []}, lambda _i: {})
    assert out == {"hit": None, "status": "na", "reason": "no_etf", "etf": None}


def test_tag_self_etf_uses_index_close_map():
    calls = []

    def _load(index_id):
        calls.append(index_id)
        return _series([10, 9, 8, 7, 6])

    sig = {"date": "20260105", "index_id": "cgb_10y_etf", "signal": "buy",
           "etfs": [{"code": "511260", "match_method": "self", "track_score": 0.3}]}
    out = _ma3_tag_sig(sig, _load)  # self 无 etf 文件: 命中只可能来自 index 收盘
    assert calls == ["cgb_10y_etf"]
    assert out["hit"] is True
    assert out["etf"] == "511260"


def test_tag_missing_etf_file_is_na(etf_dir):
    sig = {"date": "20260105", "index_id": "x", "signal": "buy",
           "etfs": [{"code": "999999", "track_score": 0.9, "match_method": "track"}]}
    out = _ma3_tag_sig(sig, lambda _i: {})
    assert out["hit"] is None
    assert out["status"] == "na"
    assert out["reason"] == "no_data"
    assert out["etf"] == "999999"


# ===== QDII 回归: 前复权 close vs etf_daily.accum_nav 在 4 只跨境 ETF 上判定翻转 =====
# 数据逐位取自 2026-11-21 本机实库(审查证据 8/271 条信号翻转):
#   etf/{code}-all.json 前复权 close 与 etf_daily.accum_nav 两条序列, 同一算法结论相反。
# 断言「新口径(close)判 X」+「旧口径(accum_nav)判 非X」= 证明实现确实换了数据源、且翻转方向正确。
_MA3_QDII_FLIPS = [
    # (code, 信号日, close 序列末 5 日, accum_nav 序列末 5 日, close 口径预期, accum 口径预期)
    ("159501", "20261023",
     [2.187, 2.187, 2.178, 2.146, 2.142],
     [1.8571, 1.8544, 1.875, 1.8208, 1.8202], True, False),
    ("159501", "20261019",
     [2.221, 2.229, 2.170, 2.207, 2.187],
     [1.9252, 1.8850, 1.8840, 1.8361, 1.8571], False, True),
    ("513080", "20261009",
     [1.695, 1.696, 1.707, 1.638, 1.655],
     [1.6603, 1.6501, 1.6310, 1.5667, 1.5799], False, True),
    ("159561", "20261009",
     [1.302, 1.300, 1.312, 1.285, 1.283],
     [1.2972, 1.2971, 1.2823, 1.2489, 1.2616], False, True),
    ("159513", "20260929",
     [1.874, 1.891, 1.857, 1.843, 1.851],
     [1.7225, 1.7080, 1.7089, 1.6955, 1.6990], False, True),
]


@pytest.mark.parametrize("code,sig_date,closes,accs,exp_fwd,exp_acc", _MA3_QDII_FLIPS)
def test_qdii_close_vs_accum_nav_flip(code, sig_date, closes, accs, exp_fwd, exp_acc):
    # 5 个交易日键(字符串可排序, 末日==信号日), 与库内 YYYYMMDD 形态一致
    keys = ["20260101", "20260102", "20260103", "20260104", sig_date]
    fwd = dict(zip(keys, closes))
    acc = dict(zip(keys, accs))
    hit_fwd, det = _ma3_consec_below(fwd, sig_date)
    hit_acc, _ = _ma3_consec_below(acc, sig_date)
    assert det["status"] == "ok"
    assert hit_fwd is exp_fwd, f"{code}@{sig_date} 前复权 close 口径应判 {exp_fwd}"
    assert hit_acc is exp_acc, f"{code}@{sig_date} accum_nav 旧口径应为 {exp_acc}(对照)"
    assert hit_fwd != hit_acc, "判别力: 两条序列必须给出相反结论(否则本用例证明不了换源)"


# ===== 打标范围契约 =====

def test_buy_signal_set_is_exactly_four_buy_classes():
    # 只给买入 4 类打标; 卖类/波段不进入(§23.6 MED3 同精神: 非买不判降亏)
    assert _MA3_BUY_SIGNALS == {"buy", "buy_aux", "buy_special", "buy_backup"}
    for sell in ("sell", "sell_stop_loss", "band_hold", "band_sell"):
        assert sell not in _MA3_BUY_SIGNALS


def test_buy_signal_set_matches_frontend_constants():
    """P2-5 常量交叉机检: 后端 _MA3_BUY_SIGNALS 必须与前端买入类常量集合逐键相等。

    前端没有可 import 的模块常量(浏览器全局 IIFE), 用源码形状守卫解析两处既有常量:
    _BUY_UNI_SIGS(首页入样买信号集合) 与 _CONS_BUY(AI 认可度买类集合)。任一处与后端集合
    不一致 = 同一事实多副本漂移(§22), 直接红。
    """
    app_js = Path(__file__).resolve().parents[2] / "static-site" / "app.js"
    src = app_js.read_text(encoding="utf-8")

    def _keys_of(name):
        m = re.search(r"const\s+%s\s*=\s*\{([^}]*)\}" % re.escape(name), src)
        assert m, f"前端 {name} 常量未找到(源码形状变了, 请同步本守卫)"
        return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", m.group(1)))

    assert _keys_of("_BUY_UNI_SIGS") == _MA3_BUY_SIGNALS
    assert _keys_of("_CONS_BUY") == _MA3_BUY_SIGNALS


# ===== P1-3 数据目录解析: 经 trade-data/app symlink 调用不得跳回代码仓 =====

def test_etf_data_dir_via_trade_data_symlink(tmp_path, monkeypatch):
    """从 trade-data/app 链接侧调用, 必须返回 trade-data 下的 etf 目录, 不跳回代码仓 trade。

    复刻生产布局(trade-data/app -> trade/app 软链, 见 scripts/export_etf_hist.py 顶部警告):
    代码仓侧 trade/static-site/data/etf 与数据仓侧 trade-data/static-site/data/etf 都存在,
    只从链接侧路径加载模块, 断言取数据仓(链接侧)。旧实现 Path(__file__).resolve() 会跳回
    代码仓 -> 本用例红。判别力: 两侧都真实存在, 不是「找不到才回退」的假绿。
    """
    import importlib.util

    monkeypatch.delenv("MA3_ETF_DATA_DIR", raising=False)
    _repo_queries = Path(__file__).resolve().parents[2] / "app" / "queries.py"
    _code_root = tmp_path / "code" / "trade"
    _data_root = tmp_path / "code" / "trade-data"
    (_code_root / "app").mkdir(parents=True)
    (_code_root / "app" / "queries.py").write_text(_repo_queries.read_text(encoding="utf-8"), encoding="utf-8")
    _code_etf = _code_root / "static-site" / "data" / "etf"
    _data_etf = _data_root / "static-site" / "data" / "etf"
    _code_etf.mkdir(parents=True)
    _data_etf.mkdir(parents=True)
    (_data_root / "app").mkdir()
    (_data_root / "app" / "queries.py").symlink_to(_code_root / "app" / "queries.py")

    _link_queries = _data_root / "app" / "queries.py"
    _spec = importlib.util.spec_from_file_location("app.queries_symlink_probe", str(_link_queries))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    assert Path(_mod.__file__) == _link_queries, "前置: 模块 __file__ 必须是链接侧路径(未 resolve)"
    assert _mod._ma3_etf_data_dir() == str(_data_etf), "必须读数据仓(trade-data)的 etf 目录"
    # 判别力自证: 旧写法 .resolve() 会落到代码仓目录, 与本实现结果不同
    _legacy = Path(_link_queries).resolve().parent.parent / "static-site" / "data" / "etf"
    assert str(_legacy) == str(_code_etf)
    assert str(_legacy) != _mod._ma3_etf_data_dir()
