# -*- coding: utf-8 -*-
"""#241 regression: generic notify_sent parser plus current S06 event delivery.

2026-11-11: producer moved from text/local-consign to structured results and native
incident receipts. Retain generic parser tests for its other callers. Real producer
cases preserve failed transport / queue loss / retries and recovery behavior.
All channels are offline transport fakes with positively checked network traps.
"""
from __future__ import annotations

import contextlib
import http.client
import io
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_failed_units as cfu  # noqa: E402
import check_s06_freshness as csf  # noqa: E402
from notify_sent import notify_sent  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240)
_MIN_ASSERTIONS = 40
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── notify.py 真实输出形态(逐字照 notify.py 打点行, 用于判据判别力) ──
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"
ESC_OK = "[notify][196] 升级档路由完成：{'email': True, 'feishu': True}\n"
ESC_FAIL = "[notify][196] 升级档路由完成：{'email': False, 'feishu': False}\n"
# --tier warning 三态(notify.py:2190 res dict + defer_warning 打点行)
TIER_ENQUEUED = ("[notify][warning] 入聚合 buffer（30min 批发）：S06 快照过期 3 日\n"
                 "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                 "'telegram': False, 'feishu': False, 'deferred': True, "
                 "'defer_status': 'enqueued'}\n")
TIER_SUPPRESSED = ("[notify][dedup] 同源抑制(窗口内第 2 次，已通知 1 次，4h 窗)：S06 快照过期 3 日\n"
                   "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                   "'telegram': False, 'feishu': False, 'deferred': True, "
                   "'defer_status': 'suppressed'}\n")
TIER_APPEND_FAILED = ("[notify][warning] buffer 追加失败（未入队，不占窗，后续同源继续尝试）：S06 快照过期 3 日\n"
                      "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                      "'telegram': False, 'feishu': False, 'deferred': False, "
                      "'defer_status': 'append_failed'}\n")


# ══════════════════════ ⓪ 打桩生效自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数。

    2026-10-25 补(http.client 正控): trap 新增的两个 `connect` 建连点(R2 底座,
    upload_r2 的 s3_head/s3_request 直连 http.client)此前只有声明、没有用例证明它真武装了
    —— 看守卫被改坏/漏挂也没人发现。这里用 **127.0.0.1:1**(回环地址 + 必然拒绝)补正控:
      · trap 武装 ⇒ AssertionError(trap 命中, 计数 +1);
      · trap 未武装 ⇒ 变成**真实的本地建连尝试**(回环, 不碰任何外部地址)⇒ ConnectionRefusedError。
    即「未武装时这条正控会先炸 ConnectionRefusedError 而不是过」, 判别力成立。
    """
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/")  # noqa: S310 (打桩验证, 必抛)
        # R2 底座两个建连点正控(回环地址 127.0.0.1:1, 禁止任何真实外部地址)
        with pytest.raises(AssertionError):
            http.client.HTTPSConnection("127.0.0.1", 1).connect()
        with pytest.raises(AssertionError):
            http.client.HTTPConnection("127.0.0.1", 1).connect()
    _chk(trap.hits == [
        "urllib.request.urlopen",
        "http.client.HTTPSConnection.connect",
        "http.client.HTTPConnection.connect",
    ], f"trap 应计数 3 条出口, 实得 {trap.hits}")


# ══════════════════════ ① 判据判别力(单元) ══════════════════════
@pytest.mark.parametrize("out,exp,why", [
    (SUCCESS_GENERAL, True, "#240 通用成功"),
    (FAIL_GENERAL, False, "#240 通用全败 → 不算发出"),
    (ESC_OK, True, "#240 #196③ 升级档成功"),
    (ESC_FAIL, False, "#240 #196③ 升级档全败"),
    (TIER_ENQUEUED, True, "#241 --tier warning 真入聚合 buffer"),
    (TIER_SUPPRESSED, True, "#241 --tier warning 真抑制(已处理)"),
    (TIER_APPEND_FAILED, False, "#241 --tier warning buffer 追加失败 → 不得当发出"),
    ("", False, "无输出 → fail-safe 不落签"),
    ("[notify][warning][dry-run] 模拟入聚合 buffer（不写盘）：X", False, "dry-run → 不落签"),
    ("未知形态 output", False, "未知形态 → fail-safe 不落签"),
])
def test_01_notify_sent_parser(out, exp, why):
    """F1/#241 判据: rc 不参与, 只认输出里的真实路由结果; 未知 → 保守 False。"""
    _chk(notify_sent(out) is exp, f"{why}: 期望 {exp}, 实得 {notify_sent(out)}")


def test_02_cfu_uses_result_file_not_string_parser():
    """2026-10-22 审查 D7: check_failed_units 已改用 `--result-file` 结构化 status,
    字符串判据 wrapper 已删除(旧版 notify 不认 --result-file ⇒ 回退分支不可达 = 死代码)。
    本用例锁住「不得回潮」: cfu 里不得再出现 `_notify_sent` 符号/导入。"""
    _chk(not hasattr(cfu, "_notify_sent"), "cfu._notify_sent 应已删除(结构化结果判据唯一)")
    src = (SCRIPTS / "check_failed_units.py").read_text(encoding="utf-8")
    _chk("notify_sent" not in src, "cfu 不得再引用字符串判据(死代码回潮)")
    _chk("--result-file" in src and 'payload.get("status")' in src, "cfu 应读结构化 status 字段")
    _chk('_status in ("sent", "digested")' in src, "digested 必须算已处置(BLOCK-2)")


def test_02b_source_uses_structured_result_and_shared_events():
    """New contract: no rc/text/local-consign decision can suppress retries."""
    src = (SCRIPTS / "check_s06_freshness.py").read_text()
    adapter = (SCRIPTS / "ops_legacy_events.py").read_text()
    _chk("returncode == 0" not in src, "rc cannot certify delivery")
    _chk("from ops_legacy_events import observe, dispatch" in src, "shared event contract")
    _chk("--result-file" in adapter, "structured notify result")
    _chk("_state_matches" not in src, "local consign cannot mute retries")


# Real producer->notify integration fixtures; only transport boundaries are faked.
from test_legacy_ops_lifecycle_20261111 import box, producers, flush, own_entry


def test_03_negative_control_all_channels_failed_no_receipt_and_retries(producers):
    b, snap, run, *_ = producers
    snap(False)
    b[4].update(dict.fromkeys(b[4], False))
    _chk(run() == 1, "fault still visible")
    flush(b)
    _chk(len(b[3]) == 3, "all three channels attempted")
    key, entry = own_entry(b, "producer_s06|")
    _chk(not entry.get("notified_event_id"), "no false delivery receipt")
    _chk(run() == 1, "same failure retry remains eligible")
    b[4].update(dict.fromkeys(b[4], True))
    flush(b)
    _chk(len(b[3]) == 6, "all failed channels retried")
    _chk(b[6]()[key]["notified_event_id"] == entry["event_id"], "actual receipt stored")


def test_03b_negative_control_queue_loss_requeues(producers):
    b, snap, run, *_ = producers
    snap(False)
    _chk(run() == 1, "first fault enqueued")
    key, old = own_entry(b, "producer_s06|")
    _chk(b[0].WARNING_BUFFER_FILE.exists(), "actual warning file")
    b[0].WARNING_BUFFER_FILE.unlink()
    _chk(run() == 1, "lost queue cannot be treated as delivered")
    _chk(b[0].WARNING_BUFFER_FILE.exists(), "recreated queue")
    _chk(b[6]()[key]["event_id"] == old["event_id"], "same incident reused")
    flush(b)
    _chk(len(b[3]) == 3, "fault delivered after retry")


def test_04_actual_receipts_suppress_repeat_but_not_new_fault(producers):
    b, snap, run, *_ = producers
    snap(False)
    _chk(run() == 1, "first fault")
    flush(b)
    _chk(len(b[3]) == 3, "three actual transport acceptances")
    key, old = own_entry(b, "producer_s06|")
    _chk(run() == 1, "still unhealthy")
    flush(b)
    _chk(len(b[3]) == 3, "same incident not repeated")
    snap(True)
    _chk(run() == 0, "real recovery")
    snap(False)
    _chk(run() == 1, "new fault")
    flush(b)
    _chk(b[6]()[key]["event_id"] != old["event_id"], "new incident identity")
    _chk(len(b[3]) == 6, "new fault not muted")


def test_05_recovery_cancels_queued_event(producers):
    b, snap, run, *_ = producers
    snap(False)
    _chk(run() == 1, "first fault")
    _chk(not b[3], "warning queued, not delivered")
    snap(True)
    _chk(run() == 0, "recovery observed")
    flush(b)
    _chk(not b[3], "recovered event not delivered")


def test_99_min_assertions():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}")
