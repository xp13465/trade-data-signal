# -*- coding: utf-8 -*-
"""a_fund_main 凌晨 45min 误报环根治 pytest(2026-10-12)。

背景(病灶链, 云上实测)
  02:00 槽 `backfill_direct_metrics.py` 把 a_fund_main 的「多源皆败无数据」判为
  **结构性预期缺口**(新浪源 T+1、目标日=last_trading_day()=当日必败), 打印
  「(02:00 槽预期缺口, 静默)」**但旧代码仍 log_collect(status="error")** ⇒
  `retry_failed_metrics.get_failed_metrics`(只取 status='error')每 15min 把它当真实
  失败重试(必败)⇒ 连续 3 轮调 `_notify_repeat_failure` 发邮件+飞书 ⇒ 送达后清零计数
  ⇒ 下一轮又从 0 累计 ⇒ **每 45min 一条无限环**。
  云上证据(2026-10-12): collect_log a_fund_main error@02:17:42;
  retry_failed_metrics_count.json={"a_fund_main":2}; audit log notify 02:52:25 / 06:37:19。

  「为何 10-12 才爆」:该 notify 路径自 2026-09-30(#131)起有 pre-existing NameError
  (`subj` 未定义)在 2026-10-09 17:57 才修(#241 B 波, 192800415)⇒ 10-08/10-09 同环在
  notify 处崩溃故静默, 10-12(修复后首个交易日)首次真正发通知。

修法(单一改动, 治根)
  `scripts/backfill_direct_metrics.py` 凌晨槽分支 `log_collect(..., "error", msg)`
  → `log_collect(..., "warn", msg)`。warn 仍进 collect_health(status!=ok 即计入, 黄点非
  红点), 保留 #84 P1-1「让 collect_health 通道反映」意图; retry 只认 error ⇒ 环被掐断。
  真故障判别维度不变(非凌晨槽 6 源全败 / 配置缺失 / 抛异常仍写 error + 计 fail)。

red-before-green(判别力)
  test_morning_gap_writes_warn_not_error 在**旧代码**(写 error)上必 FAIL(assert 到
  "warn" 而实际 "error")⇒ 用例对本次修复有判别力, 非空转。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub)
  本文件全程不触 notify / 不 spawn 子进程; 仍用 ZeroOutboundTrap 包裹并断言 hits==[],
  证明「本次自测未产生任何真实外发」。

跑法: python3 -m pytest -q scripts/tests/test_fundmain_morning_gap_no_retry_loop_20261012.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))          # scripts/tests (for _zero_outbound)
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))   # scripts (for retry_failed_metrics / bdm)
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

import backfill_direct_metrics as bdm  # noqa: E402
import retry_failed_metrics as rfm  # noqa: E402

GAP_MSG = "direct:market_fund_flow 多源皆败无数据"
REAL_FAIL_MSG = "direct:market_fund_flow error: HTTP 403"
DAY = "20261012"

# 断言计数下限(防收集/执行异常致 0 断言假绿, §18 L49)
_MIN_ASSERTIONS = 12
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── 构造 main() 的确定性环境 ──────────────────────────────────────────────

def _cfg():
    return {"metrics": [{"id": "a_fund_main", "enabled": True, "func": "direct:market_fund_flow"}]}


def _run_bdm(monkeypatch, *, morning, collect_result=None, collect_exc=None, slot="0200"):
    """跑 bdm.main() 一次, 返回 (exit_code, log_calls)。log_calls=[[date,mid,status,msg],...]。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(bdm, "load_config", _cfg)
    monkeypatch.setattr(bdm, "last_trading_day", lambda *a, **k: DAY)
    # 槽位判定本身已被 test_132_morning_slot.py 全覆盖(真 _is_morning_slot), 此处只测分支。
    monkeypatch.setattr(bdm, "_is_morning_slot", lambda now=None: morning)
    if collect_exc is not None:
        def _cd(_m):
            raise collect_exc
        monkeypatch.setattr(bdm, "collect_direct", _cd)
    else:
        monkeypatch.setattr(bdm, "collect_direct", lambda _m: collect_result)
    monkeypatch.setattr(bdm, "log_collect",
                        lambda d, mid, status, msg="": calls.append([d, mid, status, msg]))
    monkeypatch.setenv("BACKFILL_SLOT", slot)
    rc = bdm.main()
    return rc, calls


# ── 1. 凌晨槽结构性缺口: 写 warn(非 error) + exit 0 ──────────────────────

def test_morning_gap_writes_warn_not_error(monkeypatch):
    """核心断言(red-before-green): 凌晨槽 gap 必须写 warn, 旧代码写 error 必 FAIL。"""
    rc, calls = _run_bdm(monkeypatch, morning=True, collect_result=([], GAP_MSG))
    _chk(rc == 0, f"凌晨槽预期缺口不该计 fail, exit 应为 0, 实际 {rc}")
    _chk(len(calls) == 1, f"应只写 1 条 collect_log, 实际 {calls}")
    _chk(calls[0][2] == "warn", f"凌晨槽 gap 应写 warn(环根治), 实际 {calls[0][2]}")
    _chk(calls[0][2] != "error", "绝不能再写 error(retry 会据此形成 45min 环)")
    # 仍进 collect_health(status!=ok 即计入, 黄点非红点)——#84 P1-1 意图保留
    _chk(calls[0][2] != "ok", "仍应被 collect_health 反映(非 ok)")


# ── 2. 非凌晨槽 6 源全败 = 真故障: 写 error + exit 1(判别维度保留) ───────

def test_non_morning_gap_still_error_and_fail(monkeypatch):
    rc, calls = _run_bdm(monkeypatch, morning=False, collect_result=([], GAP_MSG), slot="2100")
    _chk(rc == 1, f"非凌晨槽 6 源全败=真故障须计 fail, exit 应为 1, 实际 {rc}")
    _chk(calls and calls[0][2] == "error", f"非凌晨槽 gap 仍写 error, 实际 {calls}")


# ── 3. 凌晨槽「非 gap」真失败: 写 error + exit 1(判别维度保留) ────────────

def test_morning_non_gap_failure_still_errors(monkeypatch):
    rc, calls = _run_bdm(monkeypatch, morning=True, collect_result=([], REAL_FAIL_MSG))
    _chk(rc == 1, f"凌晨槽采集异常(非 gap)须计 fail, exit 应为 1, 实际 {rc}")
    _chk(calls and calls[0][2] == "error", f"非 gap 失败仍写 error, 实际 {calls}")


def test_morning_exception_still_errors(monkeypatch):
    rc, calls = _run_bdm(monkeypatch, morning=True, collect_exc=RuntimeError("boom"))
    _chk(rc == 1, f"凌晨槽抛异常须计 fail, exit 应为 1, 实际 {rc}")
    _chk(calls and calls[0][2] == "error", f"抛异常仍写 error, 实际 {calls}")


# ── 4. 环被掐断(反证): warn 行不被 retry 拾取; error 行仍被拾取 ───────────

def _tmp_db(tmp_path):
    p = tmp_path / "sentiment.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE collect_log (run_date TEXT, metric_id TEXT, status TEXT, "
              "message TEXT, run_at TEXT)")
    c.commit()
    c.close()
    return p


def _seed(p, status):
    c = sqlite3.connect(str(p))
    c.execute("INSERT INTO collect_log VALUES (?,?,?,?,?)",
              (DAY, "a_fund_main", status, GAP_MSG, "2026-10-12T02:17:42"))
    c.commit()
    c.close()


def _patch_conn(monkeypatch, p):
    def _factory():
        c = sqlite3.connect(str(p))
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(rfm, "get_conn", _factory)


def test_retry_ignores_warn_row_loop_cut(monkeypatch, tmp_path):
    """反证正面: 修复后凌晨槽写 warn ⇒ retry 不拾取 ⇒ 无重试 ⇒ 无通知(环断)。"""
    p = _tmp_db(tmp_path)
    _seed(p, "warn")
    _patch_conn(monkeypatch, p)
    failed = rfm.get_failed_metrics(DAY)
    _chk(failed == [], f"warn 行不该被 retry 拾取(只取 error), 实际 {failed}")


def test_retry_still_picks_error_row_real_fault(monkeypatch, tmp_path):
    """反证反面: 真故障(非凌晨槽/非 gap)写 error ⇒ retry 照常拾取并重试(判别维度保留)。"""
    p = _tmp_db(tmp_path)
    _seed(p, "error")
    _patch_conn(monkeypatch, p)
    failed = rfm.get_failed_metrics(DAY)
    _chk(len(failed) == 1 and failed[0]["metric_id"] == "a_fund_main",
         f"error 行应被 retry 拾取, 实际 {failed}")


def test_e2e_backfill_output_feeds_retry_directly(monkeypatch, tmp_path):
    """端到端最强反证(red-before-green): bdm 凌晨槽**实际写出**的 status → 直接喂给 retry,
    必须不被拾取。旧代码(bdm 写 error)此例必 FAIL ⇒ 同一用例兼具判别力与「环被掐断」证明。"""
    rc, calls = _run_bdm(monkeypatch, morning=True, collect_result=([], GAP_MSG))
    _chk(rc == 0 and len(calls) == 1, f"bdm 凌晨槽应写 1 行且 exit 0, 实际 rc={rc} calls={calls}")
    p = _tmp_db(tmp_path)
    c = sqlite3.connect(str(p))
    c.execute("INSERT INTO collect_log VALUES (?,?,?,?,?)",
              (calls[0][0], calls[0][1], calls[0][2], calls[0][3], "2026-10-12T02:17:42"))
    c.commit()
    c.close()
    _patch_conn(monkeypatch, p)
    failed = rfm.get_failed_metrics(DAY)
    _chk(failed == [], f"bdm 凌晨槽写出的行不该被 retry 拾取(旧代码写 error 必 FAIL), 实际 {failed}")


def test_full_trading_day_morning_gaps_never_notify(monkeypatch, tmp_path):
    """端到端反证: 一整天凌晨槽反复写 warn ⇒ retry.main() 每轮早退, 计数文件不生成。"""
    p = _tmp_db(tmp_path)
    _seed(p, "warn")
    _patch_conn(monkeypatch, p)
    monkeypatch.setattr(rfm, "is_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(rfm, "load_config", _cfg)
    cnt = tmp_path / "retry_count.json"
    monkeypatch.setattr(rfm, "COUNT_FILE", cnt)
    # 模拟 02:22~16:22 的 57 轮 self_heal: 修复后每轮都应「无 error 指标」直接返回 0
    for _ in range(57):
        _chk(rfm.main() == 0, "warn-only 时 retry.main() 应早退 return 0")
    _chk(not cnt.exists(), "不应产生连续失败计数文件(无重试即无计数)")
    _chk(rfm.get_failed_metrics(DAY) == [], "全天结束仍无 error 指标")


# ── 零外发: 全程不触真实出口 ─────────────────────────────────────────────

def test_zero_outbound(monkeypatch, tmp_path):
    """§18 L48: 本次自测全程未触真实网络/邮件出口。"""
    with ZeroOutboundTrap() as trap:
        p = _tmp_db(tmp_path)
        _seed(p, "warn")
        _patch_conn(monkeypatch, p)
        rfm.get_failed_metrics(DAY)
        rc, _calls = _run_bdm(monkeypatch, morning=True, collect_result=([], GAP_MSG))
        _chk(rc == 0)
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_assertion_floor():
    """§18 L49: 断言计数下限, 防「0 断言假绿」。"""
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(收集/执行异常?)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))