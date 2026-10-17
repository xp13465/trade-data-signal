# -*- coding: utf-8 -*-
"""#222 治本自测: 全量 trades 撤「每轮必变」元数据(2026-10-11, 用户拍板 §23.7)。

背景(依据 docs/ops/next-steps-w3-datacred-20261011.md §4.3):
  全量 signal_kelly_trades.json / _sdc.json 顶层含 generated_at(每轮必变)+ period_cutoffs(每日变),
  而 data-large 上传判据 = **整文件 md5**(md5 变则真 PUT), verify-r2 对账 = HEAD ETag vs 本地整文件 md5。
  两把尺子本来就同源, 故元数据每轮变 ⇒ 每轮必传 ≈175MB(≈1GB/天跨境)。与 #219 parts 同源病灶
  (生成器元数据污染变更判据), 但**形状不同**(浪费在上传侧, 非 verify 补传侧)⇒ 唯一自洽解 = 让
  上传字节稳定: 生成端撤出这两字段。

本测试覆盖四条硬要求:
  ① 撤键存在性: trades_output 无 generated_at/period_cutoffs, 本体(fields/quadrants)+常量 buy_amount 保留;
     同批 backtest 档(output)仍保留 generated_at(展示链依赖)+ config.period_cutoffs。
  ② md5 稳定: 同一本体 + 两个不同生成时刻 → trades 整文件 md5 逐位一致; 负控=旧格式(带 generated_at)
     两轮 md5 必不同(证明撤键必要), 且 backtest 档两轮 md5 仍不同(证明未过度撤键, 时间源仍活)。
  ③ unique 三表同款(KELLY_UNIQUE_EXPORT, 默认关): 同撤这两字段。
  ④ 登记点守护: 消费方 kelly_posrating 已改源 backtest_doc; check_data_gap_alerts 死常量已清 + B2 仍走 mtime。
"""
import hashlib
import json
import sys
from datetime import datetime as _dt
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # trade/ 仓库根
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

import signal_kelly_backtest as skb  # noqa: E402

TF = list(skb.TRADE_FIELDS)


def _md5(b):
    return hashlib.md5(b).hexdigest()


def _ser(obj):
    """与 main() 写盘同款序列化(atomic_write_text(json.dumps(...)))"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _trade(sd, idx, sig):
    """构造 _build_outputs/_build_unique_tables 可消费的 trade dict(全字段齐)。"""
    t = {f: "" for f in TF}
    t.update({
        "signal_date": sd, "index_id": idx, "signal": sig,
        "buy_date": sd, "sell_date": sd, "etf_code": "510300", "etf_name": "测试ETF",
        "buy_price": 1.0, "sell_price": 1.05, "shares": 100,
        "real_buy_price": 1.0, "real_buy_date": sd,
        "current_price": 1.0, "real_current_price": 1.0,
        "profit": 5.0, "return_pct": 5.0, "hold_days": 10, "sell_reason": "signal",
        "track_tier": "strong", "track_score": 0.8, "match_method": "x",
        "track_low_confidence": False, "rating": "high",
        "market_state": "a", "market_tier": "a", "market_tier_all": "a", "market_tier_cyb": "a",
    })
    return t


def _quadrants():
    """16 象限 × 全卖出模式 各 1 笔(_build_outputs 遍历 QUADRANT_META 全键)。"""
    return {qk: {mk: [_trade("20260110", "IDX1", "buy")] for mk in skb.SELL_MODES}
            for qk in skb.QUADRANT_META}


def _colrows():
    """列式行输入(供 _build_unique_tables; 它是 main() 里 trades_output['quadrants'] 的消费方)。"""
    _, tr = skb._build_outputs(_quadrants())
    return tr["quadrants"]


class _FixedNow(_dt):
    """替身 datetime: 继承真 datetime(保住 strptime/strftime), 只覆写 now() 钉住生成时刻。"""
    _value = None

    @classmethod
    def now(cls, tz=None):
        return cls._value


def _build_with_now(monkeypatch, ts):
    monkeypatch.setattr(skb, "datetime", _FixedNow)
    _FixedNow._value = ts
    return skb._build_outputs(_quadrants())


# ── ① 撤键存在性 ─────────────────────────────────────────────────────────────
def test_c0_keys_stripped_and_body_kept():
    output, trades_output = skb._build_outputs(_quadrants())
    assert "generated_at" not in trades_output, "trades 顶层应无 generated_at(撤键)"
    assert "period_cutoffs" not in trades_output, "trades 顶层应无 period_cutoffs(撤键)"
    # 本体 + 常量保留
    assert trades_output["fields"] == skb.TRADE_FIELDS
    assert "quadrants" in trades_output and trades_output["buy_amount"] == skb.BUY_AMOUNT
    # backtest 档(展示链依赖)仍保留 generated_at + config.period_cutoffs(不得误撤)
    assert "generated_at" in output
    assert output["config"]["period_cutoffs"], "backtest.config.period_cutoffs 必须保留(前端读它)"
    print("① 撤键 OK: trades 无 gen/cutoffs, backtest 档保留 gen + config.period_cutoffs")


# ── ② md5 稳定(核心) + 负控 ─────────────────────────────────────────────────
def test_c1_two_rounds_md5_stable(monkeypatch):
    t1 = _dt(2026, 10, 11, 16, 47)
    t2 = _dt(2026, 10, 12, 21, 12)          # 次日不同轮
    _, tr1 = _build_with_now(monkeypatch, t1)
    _, tr2 = _build_with_now(monkeypatch, t2)
    assert _md5(_ser(tr1)) == _md5(_ser(tr2)), (
        "本体不变时 trades 整文件 md5 应逐位一致(否则 data-large 每轮仍必传)")
    print(f"② 稳定 OK: 两轮 trades md5 = {_md5(_ser(tr1))}")


def test_c2_neg_control_old_format_changes(monkeypatch):
    """负控 1: 旧格式(带生成的 meta)两轮 md5 必不同 —— 证明撤键的必要性。"""
    t1 = _dt(2026, 10, 11, 16, 47)
    t2 = _dt(2026, 10, 12, 21, 12)
    _, tr1 = _build_with_now(monkeypatch, t1)
    _, tr2 = _build_with_now(monkeypatch, t2)
    old1 = {"generated_at": t1.strftime("%Y-%m-%d %H:%M"),
            "buy_amount": tr1["buy_amount"],
            "period_cutoffs": {"y1": "20251011", "all": "0"},
            "fields": tr1["fields"], "quadrants": tr1["quadrants"]}
    old2 = dict(old1, generated_at=t2.strftime("%Y-%m-%d %H:%M"),
                period_cutoffs={"y1": "20251012", "all": "0"})
    assert _md5(_ser(old1)) != _md5(_ser(old2)), "旧格式两轮 md5 应不同(撤键前病灶)"
    print("② 负控1 OK: 旧格式两轮 md5 不同(撤键前每轮必传)")


def test_c3_neg_control_backtest_still_time_varying(monkeypatch):
    """负控 2: backtest 档(保留 gen)两轮 md5 仍不同 —— 证明未过度撤键。"""
    t1 = _dt(2026, 10, 11, 16, 47)
    t2 = _dt(2026, 10, 12, 21, 12)
    o1, _ = _build_with_now(monkeypatch, t1)
    o2, _ = _build_with_now(monkeypatch, t2)
    assert _md5(_ser(o1)) != _md5(_ser(o2)), "backtest 档含生成的 generated_at, 两轮应不同"
    print("② 负控2 OK: backtest 档两轮 md5 不同(时间源仍活)")


# ── ③ unique 三表同款 ───────────────────────────────────────────────────────
def test_c4_unique_tables_stripped(monkeypatch):
    t1 = _dt(2026, 10, 11, 16, 47)
    t2 = _dt(2026, 10, 12, 21, 12)
    monkeypatch.setattr(skb, "datetime", _FixedNow)
    cols = _colrows()                       # 列式行(与 main() 传参同形)
    _FixedNow._value = t1
    u1 = skb._build_unique_tables(cols)
    _FixedNow._value = t2
    u2 = skb._build_unique_tables(cols)
    assert "generated_at" not in u1 and "period_cutoffs" not in u1
    assert _md5(_ser(u1)) == _md5(_ser(u2)), "unique 三表两轮 md5 应一致"
    print("③ unique OK: 撤键 + 两轮 md5 一致")


# ── ④ 登记点守护(消费方全链) ────────────────────────────────────────────────
def test_c5_registry_guards():
    pos = (SCRIPTS / "kelly_posrating.py").read_text(encoding="utf-8")
    assert '"generated_at": backtest_doc.get("generated_at")' in pos, "posrating 应改源 backtest_doc"
    assert 'trades_doc.get("generated_at")' not in pos, "posrating 不得再读 trades 档 generated_at"

    gap = (SCRIPTS / "check_data_gap_alerts.py").read_text(encoding="utf-8")
    assert "KELLY_BACKTEST_FILE" not in gap, "死常量应已清(实测零引用)"
    assert "fresh_ts = datetime.fromtimestamp(tp.stat().st_mtime)" in gap, "B2 应以 mtime 单源(2026-10-17 P4 已收敛, 双源恒死代码已删)"
    assert "ts_cands" not in gap, "B2 双源死码不得回潮"

    # 唯一写 trades_generated_at 的点仍是 overfit_monitor(其唯一消费者=自身, 撤键后变 "")
    ov = (SCRIPTS / "overfit_monitor.py").read_text(encoding="utf-8")
    assert 'data.get("generated_at", "")' in ov
    print("④ 守护 OK: posrating 改源 / gap-alerts 死码已清 / B2 mtime 单源 / overfit 单写点")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))