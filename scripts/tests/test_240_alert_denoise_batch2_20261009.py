# -*- coding: utf-8 -*-
"""#240 告警降噪第二批 4 条 —— pytest 自验(2026-10-09)。

权威口径 = docs/ops/alert-triage-1008-20261008.md(10-08 全天 19 条外发 / 9 个独立根因,
其中 5 条 ≈26% 属可降噪面)。四条改动:

  ① finalizer 误报变体(gen_schedule_stats.py): R5 —— 与 Fix A 同根但**无 Finalize 锚行**的
     multiprocessing spawn/SemLock `FileNotFoundError` Traceback 变体未被过滤, 被当真实异常上报。
     修 = 新增 `_mp_infra_traceback_ranges`(帧路径全基础设施 + canonical sem_unlink 文案 双闸)。
     **非 finalizer 的 Traceback 照报**(反例断言)。
  ② failed unit 每 6h 重报(check_failed_units.py): R3 —— 同一集合 09:45/16:00/22:15 三封同文。
     修 = `adr.failed_units_daily_judge`(集合未变+当日已报 → 跳过; 集合有变 → 立即报; 次日首报照报),
     notify 侧 `--dedup-window 0`(窗口自管), dedup-key 保持 `failed_units_patrol`(保 #196③ 升档接线)。
  ③ intraday 碰线(schedule_monitor.sh): R7 —— 928s vs 900s(仅超 3%)判 SEVERE + 15min 后恢复。
     修 = 单轮碰线进 pending 桶, 连续 `DUR_CONTINUOUS_THRESHOLD` 轮才 SEVERE; `>= 2×阈值` 单次立即报。
     **真退化照报**(09-30 盘后 2081s → 反例断言)。
  ④ 公募全 NULL 时滞(check_data_gap_alerts.py): R8 —— 当日刚采、净值未发布也判 severe。
     修 = 「全 NULL 日 == 今日 且发布窗口(>=20:00)内」→ info; **早于今日仍全 NULL → severe**(反例断言)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— ② 用 `ZeroOutboundTrap` 包裹 + monkeypatch `_send_notify`
  记录调用; ①③④ 为纯函数/静态提取块, 无任何发送路径。

第三实现漂移防护(memory repro-script-second-implementation-drift):③ 的判定不重写一份,
  而是从 `schedule_monitor.sh` 内嵌 python heredoc **ast 提取真源码块**后 exec(与
  test_232/test_181/test_228 同法)。`SCHEDULE_MONITOR_SH` 环境变量可覆盖被读脚本(红先验可复现)。

跑法: python3 -m pytest -q scripts/tests/test_240_alert_denoise_batch2_20261009.py
"""
from __future__ import annotations

import ast
import datetime
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402
import check_data_gap_alerts as cdg  # noqa: E402
import check_failed_units as cfu  # noqa: E402
import gen_schedule_stats as gss  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
MONITOR = Path(os.environ.get("SCHEDULE_MONITOR_SH", str(SCRIPTS / "schedule_monitor.sh")))

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#193)
_MIN_ASSERTIONS = 58
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _write_log(tmp: Path, body: str, name: str = "fx.log", exit_code: int = 0) -> Path:
    """构造一个含 start/end 标记的运行窗口 log(与 gen_schedule_stats 切窗同形)。"""
    p = tmp / name
    p.write_text("=== fixture.sh 开始 2026-10-09 21:00:00 ===\n" + body
                 + f"\n=== fixture.sh 结束 2026-10-09 21:01:00 退出码={exit_code} ===\n",
                 encoding="utf-8")
    return p


# ══════════════════════ ① finalizer 误报变体(gen_schedule_stats) ══════════════════════
# 真实样本形态: 2026-10-08 21:00 backfill_evening 轮(云上 backfill_evening_launchd.log 实存)
_MP_NOISE = '''Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/usr/lib/python3.11/multiprocessing/spawn.py", line 122, in spawn_main
  File "/usr/lib/python3.11/multiprocessing/spawn.py", line 132, in _main
  File "/usr/lib/python3.11/multiprocessing/synchronize.py", line 115, in __setstate__
    self._semlock = _multiprocessing.SemLock._rebuild(*state)
FileNotFoundError: [Errno 2] No such file or directory'''

_APP_TRACEBACK = '''Traceback (most recent call last):
  File "/home/ubuntu/code/trade-data/scripts/backfill_indices.py", line 88, in <module>
    main()
  File "/home/ubuntu/code/trade-data/scripts/backfill_indices.py", line 51, in main
    raise RuntimeError("boom")
RuntimeError: boom'''


def test_01_mp_infra_noise_filtered_real_sample():
    """① 真噪音变体(10-08 真实形态) → 不报(降噪后同一真实样本判定: 前=Traceback 误报)。"""
    with tempfile.TemporaryDirectory(prefix="t240_mpnoise_") as td:
        p = _write_log(Path(td), _MP_NOISE)
        got, _skip = gss.scan_log_anomaly(p, "fixture.sh", "standard", last_exit=0)
        _chk(got is None, f"①真噪音变体应不报, 实得 {got}")
        # 源码锚点断言: 新判定函数存在且被 scan_log_anomaly 接线(防改名/失联)
        src = (SCRIPTS / "gen_schedule_stats.py").read_text(encoding="utf-8")
        _chk("_mp_infra_traceback_ranges" in src and
             "finalizer_ranges += _mp_infra_traceback_ranges" in src,
             "① scan_log_anomaly 未接线 _mp_infra_traceback_ranges")


@pytest.mark.parametrize("name,body,why", [
    ("应用帧真Traceback", _APP_TRACEBACK, "非 finalizer 的 Traceback 必须照报(任务铁律)"),
    ("mp帧+带路径FNF", '''Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/usr/lib/python3.11/multiprocessing/spawn.py", line 122, in spawn_main
  File "/usr/lib/python3.11/multiprocessing/spawn.py", line 132, in _main
FileNotFoundError: [Errno 2] No such file or directory: '/data/missing.parquet\'''',
     "带路径=真实文件缺失故障, 照报"),
    ("单帧<str>不足2帧", '''Traceback (most recent call last):
  File "<string>", line 1, in <module>
FileNotFoundError: [Errno 2] No such file or directory''',
     "帧数<2 不判噪音(零开口保守)"),
])
def test_01b_real_traceback_still_reported(name, body, why):
    """① 反向: 任何带应用帧/带路径/帧数不足的 Traceback 一律照报(真故障判别维度保留)。"""
    with tempfile.TemporaryDirectory(prefix="t240_realtb_") as td:
        p = _write_log(Path(td), body)
        got, _skip = gss.scan_log_anomaly(p, "fixture.sh", "standard", last_exit=0)
        _chk(got is not None and got.get("keyword") == "Traceback (most recent call last)",
             f"① {name} 应照报({why}), 实得 {got}")


def test_01c_anchored_finalizer_block_still_filtered():
    """① 回归: Fix A 原有锚行形态仍被过滤(不因新增检测器而回归)。"""
    anchored = '''Exception ignored in: <Finalize object, dead>
Traceback (most recent call last):
  File "/usr/lib/python3.11/multiprocessing/util.py", line 227, in __call__
    res = self._callback(*self._args, **self._kwargs)
  File "/usr/lib/python3.11/multiprocessing/synchronize.py", line 87, in _cleanup
    sem_unlink(name)
FileNotFoundError: [Errno 2] No such file or directory'''
    with tempfile.TemporaryDirectory(prefix="t240_fixa_") as td:
        p = _write_log(Path(td), anchored)
        got, _skip = gss.scan_log_anomaly(p, "fixture.sh", "standard", last_exit=0)
        _chk(got is None, f"① Fix A 锚行形态应仍被过滤, 实得 {got}")


# ══════════════════════ ② failed unit 每日 1 次 / 集合变即报 ══════════════════════

def test_02_signature_and_judge_pure():
    """② 纯函数: 签名与顺序无关; 判定四态(empty/changed/daily-first/same-set-same-day)。"""
    a = adr.failed_units_signature(["b.service", "a.service"])
    b = adr.failed_units_signature(["a.service", "b.service"])
    _chk(a == b and len(a) == adr.FAILED_UNITS_SIG_LEN, "② 签名应与顺序无关且定长")
    _chk(adr.failed_units_signature([]) == "" and adr.failed_units_signature(None) == "",
         "② 空集合签名应为空串")
    _chk(adr.failed_units_signature(["a.service"]) != a, "② 集合变 → 签名应变")

    sig = adr.failed_units_signature(["a.service"])
    _chk(adr.failed_units_daily_judge({}, "", "2026-10-09") == (False, "empty"), "② empty 不应发")
    _chk(adr.failed_units_daily_judge({}, sig, "2026-10-09") == (True, "changed"),
         "② 无历史 → 集合变 = 立即报")
    _chk(adr.failed_units_daily_judge({"signature": sig, "last_alert_date": "2026-10-08"},
                                      sig, "2026-10-09") == (True, "daily-first"),
         "② 集合同但跨日 → 次日首报照报")
    _chk(adr.failed_units_daily_judge({"signature": sig, "last_alert_date": "2026-10-09"},
                                      sig, "2026-10-09") == (False, "same-set-same-day"),
         "② 集合同+当日已报 → 跳过(消除 6h 重报)")
    _chk(adr.failed_units_daily_judge({"signature": "deadbeef0000", "last_alert_date": "2026-10-09"},
                                      sig, "2026-10-09") == (True, "changed"),
         "② 当日已报但集合变了 → 立即报")


_HEALTHY_SHOW = {u: {"ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled"}
                 for u, _ in adr.WATCHMAN_UNITS}
_FAILED_LINE = "trade-x.service loaded failed failed Trade X\n"


def _cfu_main(monkeypatch, tmp: Path, failed_text: str, sender=None):
    """跑 check_failed_units.main()(注入样本 + 记录型 _send_notify)。返回 (rc, calls, out)。

    sender 可覆盖打桩实现(F1 负控需模拟「渠道全失败」)。
    """
    fd = tmp / "failed.txt"
    fd.write_text(failed_text, encoding="utf-8")
    sj = tmp / "show.json"
    sj.write_text(json.dumps(_HEALTHY_SHOW), encoding="utf-8")
    calls = []

    def _rec(repo, subject, body):
        calls.append((subject, body))
        return True, "recorder"

    monkeypatch.setattr(cfu, "_send_notify", sender or _rec)
    monkeypatch.setattr(sys, "argv", [
        "check_failed_units.py", "--repo", str(tmp), "--notify",
        "--failed-units-file", str(fd), "--unit-show-json", str(sj)])
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cfu.main()
    return rc, calls, buf.getvalue()


def test_02b_e2e_daily_once_and_change_immediate(monkeypatch, tmp_path):
    """② 端到端(打桩 _send_notify + ZeroOutboundTrap): 首报 / 当日同集合抑制 / 集合变立即报。"""
    with ZeroOutboundTrap() as trap:
        rc1, c1, _ = _cfu_main(monkeypatch, tmp_path, _FAILED_LINE)
        _chk(rc1 == 1 and len(c1) == 1, f"② 首次发现应发 1 封, rc={rc1} n={len(c1)}")

        # 同日同集合(模拟 16:00/22:15 轮): 不再发
        rc2, c2, out2 = _cfu_main(monkeypatch, tmp_path, _FAILED_LINE)
        _chk(rc2 == 1 and len(c2) == 0, f"② 当日同集合应抑制, rc={rc2} n={len(c2)}")
        _chk("same-set-same-day" in out2, f"② 应打印降噪 reason, out={out2[-200:]}")

        # 集合有变(新增 unit): 立即报
        rc3, c3, out3 = _cfu_main(monkeypatch, tmp_path, _FAILED_LINE + "trade-y.service loaded failed failed Trade Y\n")
        _chk(rc3 == 1 and len(c3) == 1, f"② 集合有变应立即报, rc={rc3} n={len(c3)}")
        _chk("reason=changed" in out3, f"② 应变应记 reason=changed, out={out3[-200:]}")

        # 状态落盘可查(下次判定依据)
        st = json.loads((tmp_path / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME).read_text(encoding="utf-8"))
        _chk(st.get("signature") == adr.failed_units_signature(
            ["云上 failed unit: trade-x.service, trade-y.service"]),
            f"② 集合签名状态应落盘, 实得 {st}")
    _chk(trap.hits == [], f"② 零外发被破坏: {trap.hits}")


def test_02c_e2e_dry_run_no_send_and_key_unchanged():
    """② dry-run(无 --notify)零外发 + notify 调用参数锚点(dedup-window 0 / key 不变)。"""
    src = (SCRIPTS / "check_failed_units.py").read_text(encoding="utf-8")
    _chk('"--dedup-window", "0"' in src, "② 应传 --dedup-window 0(窗口自管的实现前提)")
    _chk('"--dedup-key", adr.FAILED_UNITS_DEDUP_KEY' in src,
         "② dedup-key 必须仍为 FAILED_UNITS_DEDUP_KEY(#196③ 升档接线靠它精确匹配)")
    _chk(adr.FAILED_UNITS_DEDUP_KEY == "failed_units_patrol", "② key 字面量不得漂移")
    with tempfile.TemporaryDirectory(prefix="t240_cfu_dry_") as td:
        tmp = Path(td)
        fd = tmp / "failed.txt"; fd.write_text(_FAILED_LINE, encoding="utf-8")
        sj = tmp / "show.json"; sj.write_text(json.dumps(_HEALTHY_SHOW), encoding="utf-8")
        with ZeroOutboundTrap() as trap:
            p = subprocess.run(
                [sys.executable, str(SCRIPTS / "check_failed_units.py"), "--repo", str(tmp),
                 "--failed-units-file", str(fd), "--unit-show-json", str(sj)],
                capture_output=True, text=True, timeout=120, check=False)
        _chk(p.returncode == 1, f"② dry 应 rc=1(发现异常), 实得 {p.returncode}")
        _chk("dry-run" in (p.stderr + p.stdout) and "send=True" in (p.stderr + p.stdout),
             f"② dry 应打印判定, out={(p.stderr + p.stdout)[-200:]}")
        _chk("告警已发出" not in (p.stderr + p.stdout), "② dry-run 不得真发")
        _chk(trap.hits == [], f"② dry-run 零外发被破坏: {trap.hits}")


@pytest.mark.parametrize("out,exp,why", [
    ("[notify] 汇总：已发出 email/feishu", True, "通用路径成功"),
    ("[notify] 汇总：已发出 email（未发出：feishu）", True, "有任一渠道成功即算已发出"),
    ("[notify] 汇总：全部渠道未发出（email/feishu）", False, "全渠道失败 → 不算发出"),
    ("[notify] 汇总：全部渠道未发出（无渠道）", False, "无渠道 → 不算发出"),
    ("[notify][196] 升级档路由完成：{'email': True, 'feishu': True}", True,
     "#196③ 升级档 early return, 靠 dict 判"),
    ("[notify][196] 升级档路由完成：{'email': False, 'feishu': False}", False,
     "升级档也全败 → 不算发出"),
    ("", False, "无输出 → 保守不算发出(下轮重试)"),
])
def test_02d_notify_sent_parser(out, exp, why):
    """F1: 落签判据 = 输出汇总(notify.py 恒 rc=0, 不能只看 rc)。"""
    _chk(cfu._notify_sent(out) is exp, f"F1 {why}: 期望 {exp}, 实得 {cfu._notify_sent(out)}")


def test_02e_all_channels_failed_writes_no_signature_and_retries(monkeypatch, tmp_path):
    """F1 负控(必修项): 通知渠道全失败 → **不得落签名** → 下一轮仍重试(当天不失报)。

    改前: 落签判据 = 子进程 rc==0, 而 notify.py 恒返回 0(含「全部渠道未发出」)
    ⇒ 渠道故障当天同集合告警被全部抑制 = 当天失报。改后: 看输出 => 不落签 => 重试。
    """
    calls = []

    def _fail(repo, subject, body):
        calls.append(subject)
        return False, "[notify] 汇总：全部渠道未发出（email/feishu）"

    with ZeroOutboundTrap() as trap:
        rc1, _c1, out1 = _cfu_main(monkeypatch, tmp_path, _FAILED_LINE, sender=_fail)
        rc2, _c2, out2 = _cfu_main(monkeypatch, tmp_path, _FAILED_LINE, sender=_fail)
    _chk(rc1 == 1 and rc2 == 1, f"F1 发送失败仍应 rc=1, 实得 {rc1}/{rc2}")
    _chk(len(calls) == 2, f"F1 全渠道失败必须下轮重试(不得落签抑制), 实得调用 {len(calls)} 次")
    _chk("告警未发出" in out1 and "不落抑制" in out1, f"F1 应响亮报未发出, out={out1[-200:]}")
    _chk(not (tmp_path / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME).exists(),
         "F1 全渠道失败不得落签名状态文件")
    _chk("告警已发出" not in out2, "F1 失败轮不得声称已发出")
    _chk(trap.hits == [], f"F1 零外发被破坏: {trap.hits}")


# ══════════════════════ ③ 执行耗时「单轮碰线」降噪(schedule_monitor.sh) ══════════════════════

def _monitor_src():
    text = MONITOR.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    h0 = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    h1 = next(i for i, l in enumerate(lines) if i > h0 and l.strip() == "PYEOF")
    return "".join(lines[h0 + 1:h1])


_PARTS = None


def _dur_block():
    """ast 提取 run 块(真源码, 不抄副本): `if _dur is not None and ...` 整块 + _in_progress_state + 常量。"""
    global _PARTS
    if _PARTS is not None:
        return _PARTS
    src = _monitor_src()
    tree = ast.parse(src)

    def seg(n):
        return ast.get_source_segment(src, n)

    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "stats"
                and any(isinstance(st, ast.If) and "_dur is not None" in (seg(st.test) or "")
                        for st in n.body))
    dur_if = next(st for st in loop.body
                  if isinstance(st, ast.If) and "_dur is not None" in (seg(st.test) or ""))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_in_progress_state")
    consts = {}
    for name in ("DUR_THRESHOLDS", "DUR_CONTINUOUS_THRESHOLD", "DUR_IMMEDIATE_MULTIPLE",
                 "DUR_BUFFER_MAX_AGE", "STALE_EXIT_THRESHOLD", "IN_PROGRESS_MAX_AGE"):
        node = next((n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", None) == name), None)
        assert node is not None, f"schedule_monitor.sh 缺常量 {name}(被改名/删除? 本测试锚点需同步)"
        exec(seg(node), {"timedelta": datetime.timedelta}, consts)  # noqa: S102
    _chk(consts["DUR_CONTINUOUS_THRESHOLD"] == 2 and consts["DUR_IMMEDIATE_MULTIPLE"] == 2,
         "③ 连续轮阈值/立即倍数常量应为 2/2(改口径须同步本测试)")
    code = compile(textwrap.dedent(seg(fn)) + "\n" + textwrap.dedent(seg(dur_if)), "<dur-block>", "exec")
    _PARTS = (code, consts)
    return _PARTS


def _dur_tick(code, consts, *, dur, last_run, now, state, seen):
    """跑一轮真 dur 判定块(dur / last_run / NOW 注入)。返回本轮 alerts。"""
    # heredoc 头是 `from datetime import datetime, timedelta` → 命名空间里 datetime 是**类**
    g = {"adr": adr, "datetime": datetime.datetime, "timedelta": datetime.timedelta,
         "print": lambda *a, **k: None, "alerts": [], "alert_state": state,
         "seen_keys_this_run": seen, "in_progress_tasks": set(), "NOW": now,
         # `_dur` / `_dur_task` 是块外紧邻上游的两行赋值(块起点是 `if _dur is not None ...`,
         # 不随块提取) → 显式注入, 与生产同形。
         "_dur": dur, "_dur_task": "intraday_snapshot",
         "s": {"task": "intraday_snapshot", "last_duration_sec": dur,
               "last_run": last_run, "last_exit": 0}, **consts}
    exec(code, g)  # noqa: S102  (纯逻辑块: 只 append alerts + 改 alert_state)
    return g["alerts"]


def test_03_single_snap_no_alert_and_degradation_reported():
    """③ 单轮碰线(10-08 15:02 928s 盘中介)降噪; 真退化(盘后 2081s / 极端单次)照报。"""
    code, consts = _dur_block()
    T0 = datetime.datetime(2026, 10, 8, 15, 30)

    # 盘中单轮碰线 928s(超 900 仅 3%)→ pending 不报
    st, seen = {}, set()
    a1 = _dur_tick(code, consts, dur=928, last_run="2026-10-08 15:02", now=T0, state=st, seen=seen)
    _chk(a1 == [], f"③ 单轮碰线 928s 不应报, 实得 {a1}")
    _chk(st.get("intraday_snapshot|dur_buffer|900", {}).get("status") == "pending",
         f"③ 应落 pending 桶, 实得 {st}")

    # 下一轮恢复正常 334s → 桶复位(静默, 无恢复邮件)
    a2 = _dur_tick(code, consts, dur=334, last_run="2026-10-08 15:35", now=T0 + datetime.timedelta(minutes=15),
                   state=st, seen=set())
    _chk(a2 == [] and st.get("intraday_snapshot|dur_buffer|900", {}).get("status") == "recovered",
         f"③ 恢复应复位桶, 实得 {st}")

    # 持续退化(连续两轮不同 run 都超阈 1000s) → 第 2 轮 SEVERE
    st2 = {}
    _dur_tick(code, consts, dur=1000, last_run="2026-10-09 10:00", now=datetime.datetime(2026, 10, 9, 10, 15),
              state=st2, seen=set())
    a3 = _dur_tick(code, consts, dur=1000, last_run="2026-10-09 10:10", now=datetime.datetime(2026, 10, 9, 10, 30),
                   state=st2, seen=set())
    _chk(any("执行耗时 1000s 超阈值 900s" in x for x in a3),
         f"③ 持续退化(连续2轮超阈)应 SEVERE, 实得 {a3}")

    # 单次极端超阈(盘中 dur>=1800) → 立即报, 不等连续轮
    st3 = {}
    a4 = _dur_tick(code, consts, dur=1900, last_run="2026-10-09 11:00", now=datetime.datetime(2026, 10, 9, 11, 15),
                   state=st3, seen=set())
    _chk(any("1900s" in x for x in a4), f"③ 单次极端(>=2×阈值)应立即 SEVERE, 实得 {a4}")

    # 盘后槽真退化 2081s(09-30 实测): 阈值放宽 1800 → 单 run 被后续多轮 tick 连续看到 → 报, 不吞
    st4 = {}
    _dur_tick(code, consts, dur=2081, last_run="2026-09-30 20:35", now=datetime.datetime(2026, 9, 30, 21, 15),
              state=st4, seen=set())
    a5 = _dur_tick(code, consts, dur=2081, last_run="2026-09-30 20:35", now=datetime.datetime(2026, 9, 30, 21, 30),
                   state=st4, seen=set())
    _chk(any("执行耗时 2081s 超阈值 1800s" in x for x in a5),
         f"③ 盘后真退化 2081s 应照报, 实得 {a5}")
    # 盘中桶与盘后桶分离(阈值维度): 昨日盘后 alerted 不得让次日盘中首轮碰线直接达阈
    _chk(st4.get("intraday_snapshot|dur_buffer|900") is None,
         "③ 盘中/盘后计数桶应分离(桶键带阈值维度)")


def test_03b_dur_block_is_wired_and_thresholds_unchanged():
    """③ 阈值未被抬高(只降噪不降灵敏度) + 块内接线锚点在位。"""
    _code, consts = _dur_block()
    _chk(consts["DUR_THRESHOLDS"]["intraday_snapshot"] == 900,
         "③ 盘中阈值必须仍为 900s(禁止靠抬阈值降噪)")
    src = _monitor_src()
    _chk('if _dur_c < DUR_CONTINUOUS_THRESHOLD:' in src and '"status": "pending"' in src,
         "③ 连续轮 pending 判定未接线")
    _chk('_dur_cnt_key = f"{_dur_task}{adr.DUR_BUFFER_KEY_MARK}{_dur_thresh}"' in src,
         "③ 计数桶键缺阈值维度(盘中/盘后会串用) 或未走 adr 单一事实源")


# ── 复审 F2: 恢复环豁免 dur 计数桶(否则 dur=None 轮把 pending 桶静默翻 recovered) ──

def _recovery_loop_code():
    """ast 提取**真恢复检测环**(`for _key, _info in list(alert_state.items()):` 整块)。"""
    src = _monitor_src()
    tree = ast.parse(src)
    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.For) and isinstance(n.iter, ast.Call)
                and isinstance(n.target, ast.Tuple) and len(n.target.elts) == 2
                and getattr(n.target.elts[0], "id", None) == "_key"
                and getattr(n.target.elts[1], "id", None) == "_info")
    return compile(textwrap.dedent(ast.get_source_segment(src, loop)),
                   "<recovery-loop>", "exec")


def _run_recovery_loop(state, seen, now):
    """跑一轮真恢复环(未 seen 的 key 会被静默置 recovered)。返回 recoveries 列表。"""
    g = {"adr": adr, "NOW": now, "alert_state": state, "seen_keys_this_run": seen,
         "recoveries": [], "in_progress_tasks": set(),
         "print": lambda *a, **k: None,
         "_recovery_cooldown_ok": lambda k, i: True,
         "RECOVERY_COOLDOWN": datetime.timedelta(hours=6)}
    exec(_recovery_loop_code(), g)  # noqa: S102  (真源码块: 只改 alert_state + 追加 recoveries)
    return g["recoveries"]


def test_03c_dur_none_tick_does_not_reset_pending_bucket():
    """F2 核心(必修项): dur=None 轮(最新 run 进行中)不进 dur 块、桶不在 seen —— 恢复环必须
    **豁免 `|dur_buffer|` 键**, 否则 pending 桶被静默翻 recovered、计数从头再来 ⇒
    盘中 D∈[900,1800) 的 run 结构性凑不出「连续 2 轮」而完全静默(旧行为会报)。"""
    now = datetime.datetime(2026, 10, 9, 10, 30)
    bk = "intraday_snapshot|dur_buffer|900"
    state = {bk: {"status": "pending", "first_seen": "2026-10-09 10:00:00",
                  "consecutive_count": 1, "last_run": "2026-10-09 09:55",
                  "last_seen": "2026-10-09 10:00:00"}}
    # 对照: 其他任务的 pending key(dur=null 未 seen)应照旧被静默恢复
    state["other_task|dur>900s"] = {"status": "pending", "first_seen": "2026-10-09 10:00:00",
                                    "consecutive_count": 1}
    _run_recovery_loop(state, seen=set(), now=now)
    _chk(state[bk]["status"] == "pending" and state[bk]["consecutive_count"] == 1,
         f"F2 dur=null 轮不得复位 dur 计数桶, 实得 {state[bk]}")
    _chk(state["other_task|dur>900s"]["status"] == "recovered",
         f"F2 对照: 其他 pending key 仍应被恢复环静默置 recovered, 实得 "
         f"{state['other_task|dur>900s']}")
    # 源码锚点: 豁免必须**在恢复环内部**, 且在 pending 分支之前(位置错=豁免失效)
    src = _monitor_src()
    _i_loop = src.index("for _key, _info in list(alert_state.items()):")
    _i_ex = src.index("if adr.DUR_BUFFER_KEY_MARK in _key:", _i_loop)
    _i_pend = src.index('if _info.get("status") == "pending":', _i_loop)
    _chk(_i_loop < _i_ex < _i_pend, "F2 豁免位置错(须在恢复环内且先于 pending 分支)")


def test_03d_dur_buffer_accumulates_when_bucket_survives():
    """F2 回归: 桶未被复位时, 下一轮超阈观测应使计数达 2 → SEVERE(灵敏度不降)。"""
    code, consts = _dur_block()
    st = {"intraday_snapshot|dur_buffer|900": {
        "status": "pending", "first_seen": "2026-10-09 10:00:00",
        "consecutive_count": 1, "last_run": "2026-10-09 09:55",
        "last_seen": "2026-10-09 10:00:00"}}
    a = _dur_tick(code, consts, dur=1000, last_run="2026-10-09 10:10",
                  now=datetime.datetime(2026, 10, 9, 10, 15), state=st, seen=set())
    _chk(any("执行耗时 1000s 超阈值 900s" in x for x in a),
         f"F2 桶保留后第 2 轮观测应 SEVERE, 实得 {a}")


def test_03e_stale_bucket_does_not_carry_count():
    """F2 陈旧保护: 上次观测 >24h(任务已停跑, 桶不再被复位)按新建处理 → 单轮碰线仍不报。"""
    code, consts = _dur_block()
    bk = "intraday_snapshot|dur_buffer|900"
    st = {bk: {"status": "pending", "first_seen": "2026-10-05 10:00:00",
               "consecutive_count": 1, "last_run": "2026-10-05 09:55",
               "last_seen": "2026-10-05 10:00:00"}}
    a = _dur_tick(code, consts, dur=1000, last_run="2026-10-09 10:10",
                  now=datetime.datetime(2026, 10, 9, 10, 15), state=st, seen=set())
    _chk(a == [], f"F2 陈旧桶不得让单轮碰线假达阈, 实得 {a}")
    _chk(st[bk]["consecutive_count"] == 1, f"F2 陈旧桶应按新建处理(count=1), 实得 {st[bk]}")
    _chk(st[bk]["last_seen"] == "2026-10-09 10:15:00", "F2 陈旧桶应刷新 last_seen")
    _chk(adr.DUR_BUFFER_KEY_MARK == "|dur_buffer|",
         "F2 桶键标记常量不得漂移(构造与豁免共用)")


# ══════════════════════ ④ 公募全 NULL 首日时滞降噪(check_data_gap_alerts) ══════════════════════

def _mk_fundnav(base: Path, groups):
    (base / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(base / "data" / "public_fund.db")
    c.execute("DROP TABLE IF EXISTS fund_daily_nav")
    c.execute("""CREATE TABLE IF NOT EXISTS fund_daily_nav (
        date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT,
        unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL,
        PRIMARY KEY (date, fund_code))""")
    c.executemany("INSERT OR REPLACE INTO fund_daily_nav VALUES (?,?,?,?,?,?,?)",
                  [t for gp in groups for t in gp])
    c.commit(); c.close()


def _nav_rows(d, null, n=1500):
    return [(d, f"{i:06d}", f"f{i}", None if null else 1.1, 1.1, None, None) for i in range(n)]


@pytest.mark.parametrize("name,groups,now,exp", [
    ("今日全NULL+窗口内", [("20261009", True)], datetime.datetime(2026, 10, 9, 22, 35), "info"),
    ("今日+昨日均全NULL", [("20261009", True), ("20261008", True)], datetime.datetime(2026, 10, 9, 22, 35), "severe"),
    ("仅昨日全NULL", [("20261008", True), ("20261009", False)], datetime.datetime(2026, 10, 9, 22, 35), "severe"),
    ("今日全NULL但窗口外(白天手跑)", [("20261009", True)], datetime.datetime(2026, 10, 9, 10, 0), "severe"),
    ("今日有值", [("20261009", False)], datetime.datetime(2026, 10, 9, 22, 35), None),
])
def test_04_allnull_tiering(name, groups, now, exp):
    """④ 两级判定: 首日时滞 → info; 次日仍全 NULL / 窗口外 → severe(真断供照报)。"""
    with tempfile.TemporaryDirectory(prefix="t240_allnull_") as td:
        b = Path(td)
        _mk_fundnav(b, [_nav_rows(d, null) for d, null in groups])
        got = cdg.check_fund_nav_allnull(b, now)
        lv = got[0].level if got else None
        _chk(lv == exp, f"④ {name}: 期望 {exp}, 实得 {[(f.level, f.title) for f in got]}")
        if exp == "info":
            _chk("首日净值时滞" in got[0].title and "不告警" in got[0].detail
                 or "首日净值时滞" in got[0].title, f"④ info 文案应点明时滞: {got[0].title}")
        if exp == "severe":
            _chk("采集全 NULL" in got[0].title and "backfill-nav" in got[0].detail,
                 "④ severe 文案应保留原处置建议")


def test_04b_info_level_is_silent_but_keeps_key_active():
    """④ info 只记日志不发通知, 且同 key 仍算「活跃」→ 不误发 [恢复] 邮件(出口层口径)。"""
    src = (SCRIPTS / "check_data_gap_alerts.py").read_text(encoding="utf-8")
    _chk("FUND_NAV_PUBLISH_WINDOW_HOUR = 20" in src, "④ 发布窗口常量缺失")
    _chk("active_keys = {f.key for f in findings}" in src and "if sev < 1:" in src,
         "④ 出口层 info 静默/活跃口径应保持(不因本改动破坏)")
    _chk(adr.__file__ and cdg.FUND_NAV_ALLNULL_KEY == "data_gap:fund_nav_allnull",
         "④ key 字面量不得漂移(下游 state/dedup 依赖)")


def test_99_min_assertions():
    """断言计数下限兜底(防收集/执行异常致假绿)。"""
    assert _N[0] >= _MIN_ASSERTIONS, f"仅 {_N[0]} 条断言(<{_MIN_ASSERTIONS}, 疑收集异常)"