# -*- coding: utf-8 -*-
"""告警降噪三项(2026-10-11 用户拍板「直接干」)——「降噪生效 + 判别保留」回归套。

三项(逐项双验收: 正常不再吵 / 异常照常响):
  ① 冻结表缺失 report(signal_kelly_backtest._alert_frozen_missing):
     已确认接受的事件(config/signal_kelly_frozen_missing_accepted.json)只写日志不发通知;
     「表外新事件」照常分级告警(判别保留)。
  ② verify-r2 独立链产物脱节 notice(upload_r2.cmd_verify_r2):
     小规模偶发补传仅日志; 规模超常(文件数/字节≥阈)或连续多轮 ⇒ 照常告警(判别保留)。
  ③ fetch_news r2_skip 自愈对恢复通知(schedule_monitor.sh 恢复发送块):
     warning 档(自愈类)恢复仅记 dashboard(--tier info, 不进群/邮件); severe 档恢复照常双通道。

【零外发(§18 L48/L50)】本套全程 static-only + 打桩:
  · 三项 notify 出口一律替换为「记录 argv 的假对象 / 假模块」, 真 subprocess 不起;
  · ③ 发送块用**假 subprocess** 承接, 由真实 `notify_state()`(notify_sent)解析其伪造输出;
  · 全程再套 `_zero_outbound.ZeroOutboundTrap`(urlopen/smtplib 一触即炸)兜底。
  断言收尾 `trap.hits == []` = 本次自测零真实外发。
【防第二份实现漂移】②③ 的判定块/helper 从**真源码** ast 提取后 exec(不抄副本), 与
  test_181/test_228 同法; ① 直接 import 真模块调真函数。
【复现】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \\
          scripts/tests/test_alert_denoise_3x_20261011.py
"""
from __future__ import annotations

import ast
import datetime
import json
import os
import sys
import textwrap
import types
from pathlib import Path

import pytest

import _zero_outbound  # noqa: E402  (conftest 已把 scripts/tests 与 scripts 入 sys.path)

ROOT = Path(__file__).absolute().parent.parent.parent
UPLOAD = ROOT / "scripts" / "upload_r2.py"
MONITOR = ROOT / "scripts" / "schedule_monitor.sh"

# 断言下限(防收集/执行异常致「0 断言假绿」)
_MIN_ASSERTIONS = 40
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _raw_seg(slines, node):
    return "".join(slines[node.lineno - 1:node.end_lineno])


# ════════════════════════════════════════════════════════════════════════════
# ① 冻结表缺失(真模块 + 真函数; notify 出口 = 假 subprocess)
# ════════════════════════════════════════════════════════════════════════════
pytest.importorskip("yaml", reason="CI 需 pyyaml 才能 import signal_kelly_backtest")
sys.path.insert(0, str(ROOT / "scripts"))
try:
    import signal_kelly_backtest as sk  # noqa: E402
except Exception as _e:  # pragma: no cover
    pytest.skip(f"① 依赖不可用: {_e}", allow_module_level=True)

ACCEPTED_8 = [
    ("20260922", "sz_div", "buy"),
    ("20260929", "gz_399395", "buy_aux"),
    ("20261002", "cac40", "buy"),
    ("20261002", "dax", "buy_aux"),
    ("20261005", "hscei", "buy_aux"),
    ("20261005", "hstech", "buy"),
    ("20261006", "cac40", "buy"),
    ("20261006", "hsi", "buy_aux"),
]


class _FakeRun:
    """记录 argv 的假 subprocess.run(不真起子进程 = 零真实外发)。

    --result-file 契约(2026-10-28 审查 F1): defer 成功态 = 回写 status "digested";
    不回写的话调用方会按 fail-open 再直发一次, 断言「只 1 条」就失真。
    """

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if "--result-file" in argv:
            p = Path(argv[argv.index("--result-file") + 1])
            p.write_text(json.dumps({"status": "digested"}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture()
def accepted_file(tmp_path):
    p = tmp_path / "accepted.json"
    p.write_text(json.dumps({"accepted": [f"{d}|{i}|{s}" for d, i, s in ACCEPTED_8]}),
                 encoding="utf-8")
    return p


def _run_alert(monkeypatch, events, accepted_path):
    fake = _FakeRun()
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(accepted_path))
    monkeypatch.setattr(sk.subprocess, "run", fake)
    sk._alert_frozen_missing(set(events))
    return fake.calls


def test_1_loader_reads_accepted(monkeypatch, accepted_file):
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(accepted_file))
    got = sk._load_frozen_missing_accepted()
    _chk(got == {f"{d}|{i}|{s}" for d, i, s in ACCEPTED_8}, f"accepted 表读取={sorted(got)}")


def test_1_loader_failsafe_on_missing(monkeypatch, tmp_path):
    """fail-safe: 表缺失 ⇒ 空集(全量告警, 绝不静默)。"""
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(tmp_path / "nope.json"))
    _chk(sk._load_frozen_missing_accepted() == set(), "缺失应返回空集")


def test_1_loader_failsafe_on_corrupt(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(p))
    _chk(sk._load_frozen_missing_accepted() == set(), "损坏应返回空集")


def test_1_denoise_effective_8_accepted_no_notify(monkeypatch, accepted_file):
    """验收①: 已知 8 个事件(全命中接受表)⇒ 不发任何通知。"""
    calls = _run_alert(monkeypatch, ACCEPTED_8, accepted_file)
    _chk(calls == [], f"8 个已接受事件不应触发通知, 实发 {calls}")


def test_1_discriminator_new_event_still_alerts(monkeypatch, accepted_file):
    """验收②(判别保留): 出现表外新事件 ⇒ 照常告警, 且只对新事件计数。"""
    new_ev = ("20261010", "zzz_newindex", "buy")
    calls = _run_alert(monkeypatch, ACCEPTED_8 + [new_ev], accepted_file)
    _chk(len(calls) == 1, f"表外新事件应发 1 条, 实发 {len(calls)}")
    subj = calls[0][2]   # cmd = [python, notify.py, subject, body, ...]
    _chk("1 个" in subj, f"subject 应只计新事件 1 个(不含已接受 8), 实得: {subj}")
    _chk("20261010|zzz_newindex|buy" in " ".join(calls[0]), "告警正文应含新事件键")


def test_1_discriminator_bulk_new_severe(monkeypatch, accepted_file):
    """判别保留加强: 表外新事件达 SEVERE 阈值(>=10)⇒ 走 severe 直发。"""
    news = [("20261010", f"idx{n:02d}", "buy") for n in range(10)]
    calls = _run_alert(monkeypatch, ACCEPTED_8 + news, accepted_file)
    _chk(len(calls) == 1, "批量新事件应发 1 条")
    _chk("--severe" in calls[0], ">=10 应带 --severe")
    _chk("signal_kelly_frozen_missing" in calls[0], "应带 severe dedup key")


def test_1_failsafe_all_alert_when_table_missing(monkeypatch, tmp_path):
    """表缺失 ⇒ 8 个事件全量告警(fail-safe, 不静默)。"""
    calls = _run_alert(monkeypatch, ACCEPTED_8, tmp_path / "nope.json")
    _chk(len(calls) == 1, f"表缺失应告警, 实发 {len(calls)}")
    _chk("8 个" in calls[0][2], "表缺失时应按全量 8 个报")
    # ★4(2026-10-28): <10 不再走 small dedup key 单发, 改为只进当日摘要(--defer-digest)
    _chk("--defer-digest" in calls[0], "<10 应走 --defer-digest(只进摘要, 不单发)")
    _chk("kelly_frozen_missing" in calls[0], "摘要条目应带 digest-category")
    _chk("signal_kelly_frozen_missing_small" not in calls[0], "<10 不应再用 small dedup key 单发")


def test_1_no_notify_when_all_accepted(monkeypatch, accepted_file):
    """零外发: 全命中接受表时 subprocess.run 一次都不调用。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        calls = _run_alert(monkeypatch, ACCEPTED_8, accepted_file)
    _chk(calls == [], "不应调用 notify")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ════════════════════════════════════════════════════════════════════════════
# ② verify-r2 独立链产物脱节(ast 提取真源码块 + 真 helper)
# ════════════════════════════════════════════════════════════════════════════
_UPLOAD_CONST_NAMES = {
    "_STANDALONE_STALE_STATE_NAME", "_STALE_ALERT_COUNT_THRESHOLD",
    "_STALE_ALERT_BYTES_THRESHOLD", "_STALE_ALERT_CONSECUTIVE_THRESHOLD",
    "_STALE_CONSECUTIVE_WINDOW_HOURS",
}
_UPLOAD_FUNC_NAMES = {
    "_standalone_stale_state_path", "_load_standalone_stale_state",
    "_save_standalone_stale_state", "_compute_stale_consecutive_rounds",
    "_reset_stale_state_if_clean",
}
_UPLOAD_CACHE: dict = {}


def _upload_src():
    """ast 提取 ② 常量 + helper 函数 + `if stale_standalone_names:` 判定块(真源码, 缓存)。"""
    if _UPLOAD_CACHE:
        return _UPLOAD_CACHE["consts"], _UPLOAD_CACHE["funcs"], _UPLOAD_CACHE["block"]
    slines = UPLOAD.read_text(encoding="utf-8").splitlines(keepends=True)
    src = "".join(slines)
    tree = ast.parse(src)
    consts, funcs, block = {}, {}, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in _UPLOAD_CONST_NAMES:
            exec(ast.get_source_segment(src, node), {"Path": Path, "os": os}, consts)  # noqa: S102
        if isinstance(node, ast.FunctionDef) and node.name in _UPLOAD_FUNC_NAMES:
            funcs[node.name] = textwrap.dedent(_raw_seg(slines, node))
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) \
                and node.test.id == "stale_standalone_names":
            block = textwrap.dedent(_raw_seg(slines, node))
    assert set(consts) == _UPLOAD_CONST_NAMES, f"② 常量缺失/改名: {sorted(consts)}"
    assert set(funcs) == _UPLOAD_FUNC_NAMES, f"② helper 缺失/改名: {sorted(funcs)}"
    assert block, "② 未找到 `if stale_standalone_names:` 判定块(锚点漂移?)"
    _UPLOAD_CACHE.update(consts=consts, funcs=funcs, block=block)
    return consts, funcs, block


class _FakeNotifyModule:
    """假 notify 模块(记录 send / update_dedup; check_dedup 可配)。"""

    def __init__(self, suppressed=False):
        self.sends = []
        self.dedup_updated = []
        self._suppressed = suppressed

    def check_dedup(self, key, window):
        return self._suppressed

    def update_dedup(self, key):
        self.dedup_updated.append(key)

    def send(self, subject, body, **kw):
        self.sends.append((subject, body, kw))


def _upload_ns(monkeypatch, tmp_path, suppressed=False):
    consts, funcs, block = _upload_src()
    ns = {
        "os": os, "json": json, "sys": sys, "datetime": datetime,
        "Path": Path, "ROOT": ROOT,
        # 状态文件路径 = STATIC_DIR.parent/"data" ⇒ 用 tmp_path 下的子目录, 保证落点隔离在
        # 本用例 tmp_path 内(不污染 pytest 共享父目录 = 跨用例状态泄漏)。
        "STATIC_DIR": tmp_path / "static-site",
        "print": (lambda *a, **k: None),
        "_fmt_name_list": (lambda xs: ", ".join(xs)),
    }
    ns.update(consts)
    for src in funcs.values():
        exec(compile(src, "<upload-r2-func>", "exec"), ns)  # noqa: S102
    ns["_stale_block"] = compile(block, "<upload-r2-stale-block>", "exec")
    ns["_fake_notify"] = _FakeNotifyModule(suppressed=suppressed)
    # `import notify` → 假模块(只在本用例生效, monkeypatch 收工还原)
    monkeypatch.setitem(sys.modules, "notify", ns["_fake_notify"])
    return ns


def _stale_round(ns, names, nbytes):
    """驱动一轮 ② 判定块(names 空 ⇒ 走 else 清零点)。

    返回**该轮发出的 send 数**(快照; 不返回共享 fake 对象, 防多轮累加误判)。
    """
    ns["stale_standalone_names"] = list(names)
    ns["stale_standalone_bytes"] = nbytes
    ns["repaired_total"] = len(names)
    before = len(ns["_fake_notify"].sends)
    exec(ns["_stale_block"], ns)  # noqa: S102
    return len(ns["_fake_notify"].sends) - before


def test_2_small_single_round_only_logs(monkeypatch, tmp_path):
    """验收①: 正常小规模偶发补传(1 个文件 / 小字节)⇒ 不发通知。"""
    n = _stale_round(_upload_ns(monkeypatch, tmp_path), ["data/overview.json"], 12_345)
    _chk(n == 0, f"小规模不应告警, 实发 {n}")


def test_2_count_threshold_alerts(monkeypatch, tmp_path):
    """验收②(判别保留·数量): 单轮脱节文件数 ≥3 ⇒ 照常告警。"""
    ns = _upload_ns(monkeypatch, tmp_path)
    n = _stale_round(ns, ["a.json", "b.json", "c.json"], 100)
    _chk(n == 1, f"≥3 文件应告警, 实发 {n}")
    _chk(ns["_fake_notify"].dedup_updated == ["verify_r2_standalone_stale"], "应更新 dedup")


def test_2_bytes_threshold_alerts(monkeypatch, tmp_path):
    """验收②(判别保留·字节): 1 个文件但 ≥1MiB ⇒ 照常告警。"""
    n = _stale_round(_upload_ns(monkeypatch, tmp_path), ["data/huge.json"], 1024 * 1024)
    _chk(n == 1, f"≥1MiB 应告警, 实发 {n}")


def test_2_bytes_just_below_threshold_silent(monkeypatch, tmp_path):
    """边界: 恰好低于 1MiB 且 1 个文件 ⇒ 静默(仅日志)。"""
    n = _stale_round(_upload_ns(monkeypatch, tmp_path), ["data/huge.json"], 1024 * 1024 - 1)
    _chk(n == 0, "略低于阈值应静默")


def test_2_consecutive_rounds_alerts(monkeypatch, tmp_path):
    """验收②(判别保留·连续多轮): 连续 3 轮小规模脱节 ⇒ 第 3 轮告警。"""
    ns = _upload_ns(monkeypatch, tmp_path)
    r1 = _stale_round(ns, ["a.json"], 10)
    r2 = _stale_round(ns, ["a.json"], 10)
    r3 = _stale_round(ns, ["a.json"], 10)
    _chk(r1 == 0 and r2 == 0, f"前两轮应静默, 实得 r1={r1} r2={r2}")
    _chk(r3 == 1, f"第 3 轮连续应告警, 实发 {r3}")


def test_2_clean_round_resets_consecutive(monkeypatch, tmp_path):
    """清零: 一轮无脱节后再连续 2 轮小规模 ⇒ 不告警(连续链已断)。"""
    ns = _upload_ns(monkeypatch, tmp_path)
    _stale_round(ns, ["a.json"], 10)
    _stale_round(ns, [], 0)          # 清零
    r_a = _stale_round(ns, ["a.json"], 10)
    r_b = _stale_round(ns, ["a.json"], 10)
    _chk(r_a == 0 and r_b == 0, f"清零后重新计数应仍静默(仅到第2轮), 实得 {r_a}/{r_b}")


def test_2_window_gap_resets_consecutive(monkeypatch, tmp_path):
    """窗口: 上一轮脱节距今 >24h ⇒ 连续链重置(不误判连续)。"""
    ns = _upload_ns(monkeypatch, tmp_path)
    st_path = ns["_standalone_stale_state_path"]()
    st_path.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.datetime.now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    st_path.write_text(json.dumps({"last_round_ts": old, "consecutive_rounds": 5,
                                   "last_count": 1, "last_bytes": 10}), encoding="utf-8")
    n = _stale_round(ns, ["a.json"], 10)
    _chk(n == 0, "超 24h 窗应重置连续计数 ⇒ 静默")


def test_2_dedup_suppresses(monkeypatch, tmp_path):
    """去重: notify.check_dedup 命中 ⇒ 即使超阈也不重发。"""
    ns = _upload_ns(monkeypatch, tmp_path, suppressed=True)
    n = _stale_round(ns, ["a.json", "b.json", "c.json"], 100)
    _chk(n == 0, "dedup 命中不应发")
    _chk(ns["_fake_notify"].dedup_updated == [], "dedup 命中不应 update_dedup")


def test_2_zero_outbound(monkeypatch, tmp_path):
    """零外发: 全流程仅假 notify 模块, 无真实出口。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        _stale_round(_upload_ns(monkeypatch, tmp_path), ["a.json", "b.json", "c.json"], 100)
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ════════════════════════════════════════════════════════════════════════════
# ③ r2_skip 自愈对恢复通知分级(schedule_monitor.sh 恢复发送块)
# ════════════════════════════════════════════════════════════════════════════
def _monitor_lines():
    lines = MONITOR.read_text(encoding="utf-8").splitlines(keepends=True)
    h0 = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    h1 = next(i for i, l in enumerate(lines) if i > h0 and l.strip() == "PYEOF")
    return lines[h0 + 1:h1]


def _recovery_block_src():
    slines = _monitor_lines()
    tree = ast.parse("".join(slines))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                and isinstance(n.test, ast.Name) and n.test.id == "_combined")
    return textwrap.dedent(_raw_seg(slines, node))


class _FakeSub3:
    """假 subprocess: 按 argv 是否含 `--tier info` 伪造 notify.py 输出(供真 notify_state 解析)。"""

    def __init__(self):
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        if "--tier" in argv and "info" in argv:
            out = ("[notify][tier=info] 路由完成："
                   "{'email': False, 'feishu': False, 'info_logged': True}\n")
        else:
            out = "[notify] 汇总：已发出 email/feishu\n"
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


def _rec_ns(combined, recoveries=None, pend_items=None):
    from notify_sent import notify_state
    ns = {
        "sys": sys, "REPO": ROOT, "MONITOR_LOG": ROOT / "data" / "logs" / "monitor.log",
        "NOW": datetime.datetime(2026, 10, 11, 19, 0, 0),
        "now_str": "2026-10-11 19:00:00",
        "print": (lambda *a, **k: None),
        "notify_state": notify_state,
        "_PEND_KEY": "monitor_recovery|pending",
        "alert_state": {},
        "save_alert_state": (lambda st: None),
    }
    ns["_combined"] = list(combined)
    ns["recoveries"] = list(recoveries if recoveries is not None else combined)
    ns["_pend_items"] = list(pend_items or [])
    ns["_pend_tks"] = {(str(i.get("task", "")), str(i.get("keyword", "")))
                       for i in ns["_pend_items"]}
    ns["_pend_n"] = sum(1 for r in ns["_combined"]
                        if (str(r.get("task", "")), str(r.get("keyword", ""))) in ns["_pend_tks"])
    ns["subprocess"] = _FakeSub3()
    ns["_block"] = compile(_recovery_block_src(), "<recovery-block>", "exec")
    return ns


def _run_rec(ns):
    exec(ns["_block"], ns)  # noqa: S102
    return ns["subprocess"].calls


def test_3_warning_tier_recovery_info_only():
    """验收①: warning 档(自愈类)恢复 ⇒ 走 notify --tier info(不带到 --alert-issue)。"""
    rec = {"task": "fetch_news", "keyword": "r2_skip_continuous",
           "first_seen": "2026-10-11 05:00:00", "tier": "warning"}
    calls = _run_rec(_rec_ns([rec]))
    _chk(len(calls) == 1, f"应发 1 次, 实发 {len(calls)}")
    argv = calls[0]
    _chk("--tier" in argv and "info" in argv, f"warning 档应 --tier info, 实得 {argv}")
    _chk("--alert-issue" not in argv, "info 档不应写 latest.md(不带 --alert-issue)")


def test_3_severe_tier_recovery_full_channels():
    """验收②(判别保留): severe 档恢复 ⇒ 照常双通道(--alert-issue + recovery dedup)。"""
    rec = {"task": "update_all", "keyword": "exit", "first_seen": "2026-10-11 01:00:00",
           "tier": "severe"}
    calls = _run_rec(_rec_ns([rec]))
    _chk(len(calls) == 1, f"应发 1 次, 实发 {len(calls)}")
    argv = calls[0]
    _chk("--tier" not in argv, f"severe 档不应带 --tier(默认双通道), 实得 {argv}")
    _chk("--alert-issue" in argv, "severe 档恢复应写 latest.md")
    _chk("schedule_monitor_recovery" in argv, "应带恢复汇总 dedup key")


def test_3_missing_tier_defaults_full_channels():
    """未带 tier 的恢复(存量/其它来源)⇒ 默认双通道(向后兼容, 不误降级)。"""
    rec = {"task": "backfill_evening", "keyword": "exit", "first_seen": "?"}
    calls = _run_rec(_rec_ns([rec]))
    _chk(len(calls) == 1 and "--alert-issue" in calls[0], "无 tier 应默认双通道(保守)")


def test_3_mixed_batches_split():
    """混合: warning 与 severe 各 1 条 ⇒ 拆成 2 批(1 info + 1 alert)。"""
    w = {"task": "fetch_news", "keyword": "r2_skip_continuous", "first_seen": "?",
         "tier": "warning"}
    s = {"task": "update_all", "keyword": "exit", "first_seen": "?", "tier": "severe"}
    calls = _run_rec(_rec_ns([w, s]))
    _chk(len(calls) == 2, f"应拆 2 批, 实发 {len(calls)}")
    tiers = [("--tier" in c) for c in calls]
    _chk(sorted(tiers) == [False, True], f"应一批 info 一批 alert, 实得 {tiers}")


def test_3_pending_retains_tier():
    """pending 桶: 发送失败 ⇒ 并入 pending 且保留 tier(补列时仍走原档)。"""
    w = {"task": "fetch_news", "keyword": "r2_skip_continuous", "first_seen": "?",
         "tier": "warning"}
    ns = _rec_ns([w])

    def _fail_run(argv, **kw):
        ns["subprocess"].calls.append(list(argv))
        return types.SimpleNamespace(
            returncode=0,
            stdout="[notify][tier=info] 路由完成：{'info_logged': False}\n", stderr="")

    ns["subprocess"].run = _fail_run
    ns["save_alert_state"] = (lambda st: ns.__setitem__("_saved", st))
    exec(ns["_block"], ns)  # noqa: S102
    pend = ns["alert_state"].get("monitor_recovery|pending")
    _chk(pend is not None, "失败应入 pending 桶")
    _chk(pend["items"] and pend["items"][0].get("tier") == "warning",
         "pending 条目应保留 tier")


def test_3_zero_outbound():
    """零外发: 发送块全程假 subprocess, 无真实外发。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        w = {"task": "fetch_news", "keyword": "r2_skip_continuous", "first_seen": "?",
             "tier": "warning"}
        s = {"task": "update_all", "keyword": "exit", "first_seen": "?", "tier": "severe"}
        _run_rec(_rec_ns([w, s]))
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ════════════════════════════════════════════════════════════════════════════
def test_zz_min_assertions():
    """防「0 断言假绿」。"""
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}"