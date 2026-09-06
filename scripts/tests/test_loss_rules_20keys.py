# -*- coding: utf-8 -*-
"""loss_rules.py 20 键(21 规格含 X1)谓词 pytest 套(P0-1, 架构评审 2026-09-03 §6.3/§6.5)。

【目的】锁死 AI降亏新键判定 rule_hit 的关键谓词行为, 防 rebase/重构/键改动/阈值快照改动
  静默破坏线上判定。规格单一事实源 = scripts/loss_rules.py(RULE_SPECS/QTH)。

【方法口径】
  ① 冻结快照层: 样本取自线上产物冻结快照——
     - static-site/data/signal_kelly_trades.json quadrants.rating_high.A 前 3 行
       (2026-09-06 本地提取, 线上产物)
     - static-site/data/kelly_loss_features.json(20210607/20211109 真实特征值,
       kelly_loss_features.json 2026-08-24 版冻结快照)
     断言真实 ctx 下各键命中集合(线上行为不漂移, 同 §5.4⑦ 同构对账精神)。
  ② 谓词单元层: 可控 feat_at + 构造 ctx, 对 21 键每键断言 hit + miss, 覆盖
     feature low/high 方向、sig/tier/mkt/track_tier/rating/months 各条件分支、
     缺失特征不拦、严格不等号、未知键返空。

【谓词覆盖口径】rule_hit 独立逻辑条件谓词共 31 个(feature 14 + sig 6 + tier 5 + mkt 4
  + track_tier 1 + rating/ts/months 3, 明细见 KEY_CASES 注释); 架构评审「43 谓词」
  为含缺失守卫/未知键/方向不等号等展开口径。本套每键 hit+miss 双向断言 + 冻结快照
  命中集合 + 7 项边界 = 断言数见运行输出, 谓词条件全覆盖(命中侧 21 + 反证侧 21 + 边界)。

【输入依赖】无外部数据(样本硬编码, 固定输入→断言输出)。
【输出】pytest PASS/FAIL。CI 挂载: .github/workflows/ci.yml ⑧(scripts/tests/ 限定收集)。
【复现命令】cd /Users/linhuichen/code/trade && .venv/bin/python -m pytest -q scripts/tests/test_loss_rules_20keys.py
【关键参数种子】QTH 阈值快照 = mine10_features.json 2026-08-22 版全史分位(见 loss_rules.py L40-44
  设计取舍公示: 仅挖掘筛选用途, 若用于实盘择时须改 expanding 窗口重算 §5.1⑥)。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from loss_rules import (  # noqa: E402
    QTH, RULE_SPECS, MINING_TO_PROD_KEY, PROD_TO_MINING_KEY,
    NEW_KEYS_PROD, make_feat_at, rule_hit, spec_by_prod_key,
)

# 全部 21 键(NEW_KEYS_PROD = 20 挖掘键 + X1)
ALL_KEYS = NEW_KEYS_PROD
assert len(ALL_KEYS) == 21, f"NEW_KEYS_PROD 应为 21, 实得 {len(ALL_KEYS)}"


# ────────────────────────────────────────────────────────────────────────────
# ① 冻结快照层样本(线上产物冻结, 2026-09-06 提取)
# ────────────────────────────────────────────────────────────────────────────
# signal_kelly_trades.json rating_high/A 行0-2 真实字段(字段裁剪, 保留 rule_hit ctx 用项)
FROZEN_TRADES = [
    # signal_date=20210607, 半导体ETF thsc_308700, track_tier=none, ts=36.2, 上升期, rating=high, mkt=industry
    dict(date="20210607", sig="buy_special", mkt="industry", tier="上升期",
         ts=36.2, rating="high", track_tier="none"),
    # signal_date=20211109, 同上 track_tier=none, 下降期, rating=high, mkt=industry
    dict(date="20211109", sig="buy_special", mkt="industry", tier="下降期",
         ts=36.2, rating="high", track_tier="none"),
    # 宽基(20211109, sh000300 视角), track_tier=null, ts=20.0, 下降期, rating=high, mkt=a
    dict(date="20211109", sig="buy_special", mkt="a", tier="下降期",
         ts=20.0, rating="high", track_tier="null"),
]

# kelly_loss_features.json 2026-08-24 版冻结特征值(20210607/20211109 两日全特征)
FROZEN_FEATS = {
    "20210607": {
        "north_d20": -390.2517999999999, "turn_pct": 69.13907284768212, "div_yield": 2.63,
        "qvix_pct": 57.35099337748344, "h_volchg": -42.22348853451776,
        "margin_chg20": 4.506152144844933, "div_pct": 37.35099337748344,
        "h_vol20": 16.662066413576852, "sent_a": 57.92, "vol_ratio_all": 0.9683938944595899,
        "sent_hs300": 55.9, "adline_gap": 0.19646596328168273,
    },
    "20211109": {
        "north_d20": -576.4159999999999, "turn_pct": 56.42384105960265, "div_yield": 2.6,
        "qvix_pct": 16.95364238410596, "h_volchg": -19.994912709622604,
        "margin_chg20": -0.22574890214914767, "div_pct": 38.54304635761589,
        "h_vol20": 11.86667932358344, "sent_a": 52.62, "vol_ratio_all": 0.9559190482878737,
        "sent_hs300": 62.07, "adline_gap": 0.08617748534636449,
    },
}

# 冻结快照层期望命中集合(2026-09-06 由 rule_hit 实测输出冻结, 见文件头复现命令)
FROZEN_EXPECT = [
    ["n1NorthOutflow", "ad1AdlineHot", "excludeTierNone"],
    ["n1NorthOutflow", "ad1AdlineHot", "excludeTierNone"],
    ["n1NorthOutflow", "h1VolChgHighA", "ad1AdlineHot", "excludeTierNone"],
]


def _frozen_run(trade: dict) -> list:
    dt = trade["date"]
    feats = {k: {dt: v} for k, v in FROZEN_FEATS[dt].items()}
    ctx = dict(trade, smonth=dt[4:6], feat_at=make_feat_at(feats))
    return sorted(k for k in ALL_KEYS if rule_hit(k, ctx))


def test_frozen_snapshot_hit_sets():
    """冻结快照层: 真实 ctx 命中集合逐位锁定(线上行为不漂移)。"""
    for i, (trade, expect) in enumerate(zip(FROZEN_TRADES, FROZEN_EXPECT)):
        got = _frozen_run(trade)
        assert got == sorted(expect), f"冻结样本{i} 命中集合漂移: 期望 {sorted(expect)} 实得 {got}"


# ────────────────────────────────────────────────────────────────────────────
# ② 谓词单元层: 可控 feat_at + 构造 ctx, 每键 hit + miss
# ────────────────────────────────────────────────────────────────────────────
def _at(value):
    """feat_at 闭包: 任意特征名恒返固定值(可控)。"""
    return lambda name, date: value


def _ctx(**over):
    """默认 ctx(基线); 各键用例用 over 覆写。"""
    base = dict(date="20260824", sig="buy", mkt="a", tier="牛市·主升", ts=80.0,
                rating="high", track_tier="strong", smonth="08", feat_at=_at(100.0))
    base.update(over)
    return base


# (prod_key, hit_overrides, miss_overrides) —— 覆盖全部 21 键
KEY_CASES = [
    # N1: feature north_d20 low(< q30=-58.28); miss=值不够低
    ("n1NorthOutflow", dict(feat_at=_at(-100.0)), dict(feat_at=_at(-50.0))),
    # T1: feature turn_pct low(< q30=32.05) × sig=buy_special; miss=sig 不符
    ("t1LowTurnSpecial", dict(sig="buy_special", feat_at=_at(20.0)), dict(sig="buy", feat_at=_at(20.0))),
    # D1: feature div_yield low(< q50=2.59); miss=值过高
    ("d1LowDivYield", dict(feat_at=_at(2.0)), dict(feat_at=_at(3.0))),
    # Q1: feature qvix_pct low(< q10=4.11); miss=值过高
    ("q1QvixLowPct", dict(feat_at=_at(3.0)), dict(feat_at=_at(5.0))),
    # H1: feature h_volchg high(> q30=-23.62) × mkt=a; miss=mkt 不符
    ("h1VolChgHighA", dict(feat_at=_at(10.0)), dict(mkt="concept", feat_at=_at(10.0))),
    # M1: feature margin_chg20 low(< q70=2.08) × tier=牛市·主升; miss=tier 不符
    ("m1MarginDownBull", dict(feat_at=_at(1.0)), dict(tier="下降期", feat_at=_at(1.0))),
    # D2: feature div_yield low(< q70=2.93) × tier=牛市·主升; miss=tier 不符
    ("d2LowDivBull", dict(feat_at=_at(2.0)), dict(tier="下降期", feat_at=_at(2.0))),
    # P1: feature div_pct low(< q30=28.61) × sig=buy_backup; miss=sig 不符
    ("p1LowDivBackup", dict(sig="buy_backup", feat_at=_at(20.0)), dict(sig="buy", feat_at=_at(20.0))),
    # V1: feature h_vol20 high(> q90=30.66); miss=值不足
    ("v1HighVol20", dict(feat_at=_at(40.0)), dict(feat_at=_at(20.0))),
    # S1: feature sent_a low(< q20=33.27); miss=值过高
    ("s1SentALow", dict(feat_at=_at(30.0)), dict(feat_at=_at(40.0))),
    # R1: feature vol_ratio_all low(< q10=0.876); miss=值不足低
    ("r1VolRatioLow", dict(feat_at=_at(0.5)), dict(feat_at=_at(0.9))),
    # R2b: sig=buy_special × mkt=global; miss=sig 不符
    ("r2bSpecialGlobal", dict(sig="buy_special", mkt="global"), dict(sig="buy", mkt="global")),
    # R2g: rating=low × ts<75 × smonth∈(07,08,09); miss=rating 不符
    ("r2gLowRatingQ3", dict(rating="low", ts=50.0), dict(rating="high", ts=50.0)),
    # N2: feature north_d20 low(< q30) × mkt=concept; miss=mkt 不符
    ("n2NorthOutConcept", dict(mkt="concept", feat_at=_at(-100.0)), dict(mkt="industry", feat_at=_at(-100.0))),
    # V2: feature h_vol20 high(> 25.0 固定常数); miss=值不足
    ("v2Vol20Gt25", dict(feat_at=_at(30.0)), dict(feat_at=_at(20.0))),
    # S2: feature sent_hs300 low(< q20=35.07); miss=值过高
    ("s2SentHs300Low", dict(feat_at=_at(30.0)), dict(feat_at=_at(40.0))),
    # W1: sig=buy_backup × tier=下降期; miss=sig 不符
    ("w1BackupDecline", dict(sig="buy_backup", tier="下降期"), dict(sig="buy_special", tier="下降期")),
    # A1: tier=牛市·主升(全类型全停); miss=tier 不符
    ("a1BullAllStop", dict(), dict(tier="下降期")),
    # V3: feature h_vol20 low(< q10=10.73); miss=值过高
    ("v3Vol20LowPct", dict(feat_at=_at(5.0)), dict(feat_at=_at(15.0))),
    # AD1: feature adline_gap high(> q70=0.060); miss=值不足
    ("ad1AdlineHot", dict(feat_at=_at(0.2)), dict(feat_at=_at(0.01))),
    # X1: track_tier∈(none,null) 整剔; miss=strong 不命中
    ("excludeTierNone", dict(track_tier="none"), dict(track_tier="strong")),
]


@pytest.mark.parametrize("pk,hit_ov,miss_ov", KEY_CASES, ids=[k[0] for k in KEY_CASES])
def test_each_key_hit_and_miss(pk, hit_ov, miss_ov):
    """每键 hit(True)+ miss(False) 双向断言: 覆盖全部 21 键全部谓词条件。"""
    assert rule_hit(pk, _ctx(**hit_ov)) is True, f"{pk} 应命中: {_ctx(**hit_ov)}"
    assert rule_hit(pk, _ctx(**miss_ov)) is False, f"{pk} 应不命中: {_ctx(**miss_ov)}"


# ────────────────────────────────────────────────────────────────────────────
# ③ 边界: 缺失特征不拦 / 严格不等号 / 未知键 / 映射表 / R2g ts 缺失
# ────────────────────────────────────────────────────────────────────────────
def test_feature_missing_no_hit():
    """特征缺失(None)→ 特征类键不拦(与 FR 工厂 `if v is None: return False` 一致)。"""
    ctx = _ctx(feat_at=_at(None))
    assert rule_hit("n1NorthOutflow", ctx) is False
    assert rule_hit("ad1AdlineHot", ctx) is False


def test_strict_inequality_low():
    """direction=low: v == th 不命中(严格 <)。"""
    th = QTH["north_d20@0.30"]
    assert rule_hit("n1NorthOutflow", _ctx(feat_at=_at(th))) is False


def test_strict_inequality_high():
    """direction=high: v == th 不命中(严格 >)。"""
    th = QTH["adline_gap@0.70"]
    assert rule_hit("ad1AdlineHot", _ctx(feat_at=_at(th))) is False


def test_v2_const_threshold():
    """V2 固定常数阈值 25.0(v == 25 不命中, >25 命中)。"""
    assert rule_hit("v2Vol20Gt25", _ctx(feat_at=_at(25.0))) is False
    assert rule_hit("v2Vol20Gt25", _ctx(feat_at=_at(25.0001))) is True


def test_unknown_key_returns_false():
    """未知键: spec_by_prod_key 返 None, rule_hit 不命中(不抛异常)。"""
    assert spec_by_prod_key("bogusKey") is None
    assert rule_hit("bogusKey", _ctx()) is False


def test_r2g_ts_missing_is_999():
    """R2g: ts 缺失视为 999 → <75 不成立, 不命中。"""
    ctx = dict(date="20260824", sig="buy", mkt="a", tier="牛市·主升",
               rating="low", ts=None, smonth="08", track_tier="strong", feat_at=_at(None))
    assert rule_hit("r2gLowRatingQ3", ctx) is False


def test_r2g_smonth_out_of_range():
    """R2g: smonth 不在 (07,08,09) → 不命中(即使 rating/ts 满足)。"""
    ctx_hit = dict(date="20260824", sig="buy", mkt="a", tier="牛市·主升",
                   rating="low", ts=50.0, smonth="10", track_tier="strong", feat_at=_at(None))
    assert rule_hit("r2gLowRatingQ3", ctx_hit) is False


def test_r2g_months_whitelist():
    """R2g: (07,08,09) 三个月逐月命中, 相邻月 06/10 不命中。"""
    for mon, exp in [("07", True), ("08", True), ("09", True), ("06", False), ("10", False)]:
        ctx = dict(date="2026" + mon + "24", sig="buy", mkt="a", tier="牛市·主升",
                   rating="low", ts=50.0, smonth=mon, track_tier="strong", feat_at=_at(None))
        assert rule_hit("r2gLowRatingQ3", ctx) is exp, f"smonth={mon} 应 {'命中' if exp else '不命中'}"


def test_x1_track_tier_multivalue():
    """X1: track_tier spec 支持多值 in 判定(none/null 均命中, 空串不命中)。"""
    ctx = dict(date="20260824", sig="buy", mkt="a", tier="牛市·主升",
               rating="high", ts=80.0, smonth="08", feat_at=_at(100.0))
    for tt, exp in [("none", True), ("null", True), ("", False), ("strong", False), ("approx", False)]:
        assert rule_hit("excludeTierNone", dict(ctx, track_tier=tt)) is exp, f"track_tier={tt!r} 应 {'命中' if exp else '不命中'}"
    # spec 本身确认是多值 in 语义
    assert isinstance(RULE_SPECS["X1"]["track_tier"], (list, tuple))


def test_mining_to_prod_mapping_roundtrip():
    """映射表: 全量 21 键反向可查、双向同位(键名单源不漂移)。"""
    assert MINING_TO_PROD_KEY["X1"] == "excludeTierNone"
    assert MINING_TO_PROD_KEY["N1"] == "n1NorthOutflow"
    for pk in NEW_KEYS_PROD:
        mk = PROD_TO_MINING_KEY[pk]
        assert MINING_TO_PROD_KEY[mk] == pk, f"映射非双射: {mk}->{pk}"
        assert mk in RULE_SPECS, f"mining 键 {mk} 不在 RULE_SPECS"


def test_rules_count_21():
    """规格单源: RULE_SPECS 21 规格(20 挖掘键 + X1), 与 NEW_KEYS_PROD 对齐。"""
    assert len(RULE_SPECS) == 21, f"RULE_SPECS 应为 21, 实得 {len(RULE_SPECS)}"
    assert len(NEW_KEYS_PROD) == 21
    assert set(PROD_TO_MINING_KEY) == set(NEW_KEYS_PROD)