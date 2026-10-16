#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#231 H1 证据用例:sentiment R2 上传连续失败 → SEVERE(链尾收口)

被验对象 = 真实生产脚本 `scripts/check_sentiment_r2_upload.py`(不做逻辑模拟)+
`scripts/intraday_snapshot.sh` 链尾调用块。

【打桩纪律(CLAUDE.md §18 L48)】
  本文件**绝不触碰真实 notify.py 外发链路**:
  ① 全部告警路径断言都走 `--notify <桩>`(桩 = tmp 下脚本,只记 argv + 打印「已发出」汇总行);
  ② 「缺省不外发」用例:不传 `--notify-send` 时**连桩都不许被调用**(桩若被调用会写文件,断言其存在性);
  ③ 真 notify.py 的 `--dry-run` 零外发/零落盘另有 L48 证据(手工验证记录见 #231 实施报告,不进本文件
     —— 避免 CI 依赖本机 config)。

【无 now() 依赖】脚本判定只用日志文件名日期 + 正文 ⇒ 本用例不注入时钟也不会「隔天变红」(§18 L51)。

跑法: python3 -m pytest -q scripts/tests/test_231_sentiment_r2_upload_alert_20261017.py
"""
import subprocess
import sys
from pathlib import Path

import check_sentiment_r2_upload as chk  # conftest 已注入 scripts/

REPO_ROOT = Path(__file__).absolute().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_sentiment_r2_upload.py"

DATE = "20261016"
ROUNDS = ["0925", "0940", "0956", "1012", "1028"]

STUB_SRC = '''#!/usr/bin/env python3
import pathlib, sys
pathlib.Path({log!r}).open("a", encoding="utf-8").write(" ".join(sys.argv[1:]) + "\\n")
print("[notify] 汇总：已发出 email/feishu")
'''


def _stub(tmp_path):
    """桩 notify.py:把 argv 追加到调用记录文件,并打印 notify.py 的成功汇总行。"""
    calls = tmp_path / "stub_calls.txt"
    stub = tmp_path / "notify_stub.py"
    stub.write_text(STUB_SRC.format(log=str(calls)), encoding="utf-8")
    return stub, calls


def _logdir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir(exist_ok=True)
    return d


def _round(logdir, hhmm, body, date=DATE):
    (logdir / f"intraday_snapshot_{date}_{hhmm}.log").write_text(body, encoding="utf-8")


def _fail(ok=0, total=6):
    return (
        f"  [intraday] sentiment-3m.json R2上传失败: rc=0 stdout=✗ status=403\n"
        f"  [intraday] sentiment R2上传 {ok}/{total}\n"
    )


def _ok(total=6):
    return f"  [intraday] sentiment R2上传 {total}/{total}\n"


def _exc():
    return "  [intraday] sentiment R2上传异常(不阻断采集): TimeoutExpired 60\n"


def _run(logdir, newest, *, notify=None, notify_send=False, rounds=None, dry_run=False, log=None):
    cmd = [sys.executable, str(CHECKER), "--log", str(log or (logdir / f"intraday_snapshot_{DATE}_{newest}.log")),
           "--logdir", str(logdir)]
    if notify is not None:
        cmd += ["--notify", str(notify)]
    if notify_send:
        cmd.append("--notify-send")
    if dry_run:
        cmd.append("--dry-run")
    if rounds is not None:
        cmd += ["--rounds", str(rounds)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ============================================================
# 一、纯函数层:单轮判定
# ============================================================
def test_parse_round_log_states():
    assert chk.parse_round_log(_ok())[0] == "ok"
    assert chk.parse_round_log(_fail(0, 6))[0] == "fail"
    assert chk.parse_round_log(_fail(5, 6))[0] == "fail"
    assert chk.parse_round_log(_exc())[0] == "fail"
    assert chk.parse_round_log(_fail(0, 0))[0] == "neutral"   # 无可传文件 ≠ 失败
    assert chk.parse_round_log("没有记号的一轮\n")[0] == "unknown"
    # 异常记号优先于可能残留的 x/y 行(异常路径下 x/y 汇总行不会打印)
    assert chk.parse_round_log(_ok() + _exc())[0] == "fail"


def test_streak_counts_consecutive_from_newest(tmp_path):
    d = _logdir(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _fail())
    _round(d, ROUNDS[3], _ok())
    _round(d, ROUNDS[4], _fail())
    # 新→旧:1028 失败、1012 成功即停 ⇒ streak=1(更早的 0925/0940/0956 连败**不跨越成功轮**)
    assert chk.compute_streak(d, DATE, 3)[0] == 1
    # 去掉那条成功轮:末两轮(1012,1028)都失败 ⇒ 连续 3 轮(含 0956)
    d2 = tmp_path / "b"
    d2.mkdir(exist_ok=True)
    for h in (ROUNDS[2], ROUNDS[3], ROUNDS[4]):
        _round(d2, h, _fail())
    assert chk.compute_streak(d2, DATE, 3)[0] == 3


def test_launchd_summary_log_not_counted_as_round(tmp_path):
    """云上实况:intraday_snapshot_launchd.log 也含同样记号(汇总日志),不得当轮日志计数。"""
    d = _logdir(tmp_path)
    _round(d, ROUNDS[2], _fail())
    _round(d, ROUNDS[3], _fail())
    _round(d, ROUNDS[4], _fail())
    (d / "intraday_snapshot_launchd.log").write_text(_fail() * 10, encoding="utf-8")
    (d / "intraday_snapshot.err").write_text(_fail(), encoding="utf-8")
    # 真实轮 = 3 条(汇总日志被排除);若被误计,这里会 >3
    logs = chk._round_logs(d, DATE)
    assert [p.name for p in logs] == [
        f"intraday_snapshot_{DATE}_{h}.log" for h in (ROUNDS[4], ROUNDS[3], ROUNDS[2])]
    assert chk.compute_streak(d, DATE, 3)[0] == 3


def test_cross_day_not_accumulated(tmp_path):
    d = _logdir(tmp_path)
    for h in ("2035",):
        _round(d, h, _fail(), date="20261015")
    _round(d, "0925", _fail(), date=DATE)
    assert chk.compute_streak(d, DATE, 3)[0] == 1


# ============================================================
# 二、CLI 端到端:告警路径(桩 notify)
# ============================================================
def test_three_consecutive_failures_fires(tmp_path):
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _fail())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True)
    assert rc == 0, out
    assert "streak=3/3" in out and "alert=yes" in out, out
    body = calls.read_text(encoding="utf-8")
    # 四元组:severe(critical) / dedup-key / dedup-window 1800 / [告警] 前缀
    assert "--severe" in body and "--from-prefix [告警]" in body
    assert "--dedup-key intraday_sentiment_r2_upload_fail" in body
    assert "--dedup-window 1800" in body
    assert "连续失败 3 轮" in body and "sentiment-3y/5y/all" in body
    assert "notify 判定=sent" in out, out          # 桩打印「已发出」汇总行 → 判 sent
    assert str(REPO_ROOT / "scripts" / "notify.py") not in body   # 真 notify.py 从未被调


def test_two_failures_does_not_fire(tmp_path):
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:2]:
        _round(d, h, _fail())
    _round(d, ROUNDS[2], _ok())
    rc, out = _run(d, ROUNDS[1], notify=stub, notify_send=True)
    assert rc == 0 and "alert=no" in out, out
    assert not calls.exists(), "未达阈值不得调用 notify"


def test_all_success_does_not_fire(tmp_path):
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _ok())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True)
    assert rc == 0 and "streak=0/3" in out and "alert=no" in out, out
    assert not calls.exists()


def test_exception_rounds_count_as_failures(tmp_path):
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    _round(d, ROUNDS[0], _fail())
    _round(d, ROUNDS[1], _exc())
    _round(d, ROUNDS[2], _exc())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True)
    assert rc == 0 and "streak=3/3" in out, out
    assert "异常" in out
    assert calls.exists()


def test_neutral_and_unknown_stop_streak(tmp_path):
    """中性(0/0 无可传文件)与无法判定(无记号)都不算失败、也不累加堆叠出假告警。"""
    d = _logdir(tmp_path)
    for h in (ROUNDS[0], ROUNDS[1]):
        _round(d, h, _fail())
    _round(d, ROUNDS[2], _fail(0, 0))
    assert chk.compute_streak(d, DATE, 3)[0] == 0
    d2 = tmp_path / "c"
    d2.mkdir(exist_ok=True)
    _round(d2, ROUNDS[0], _fail())
    _round(d2, ROUNDS[1], _fail())
    _round(d2, ROUNDS[2], "这轮没跑到 sentiment 段\n")
    assert chk.compute_streak(d2, DATE, 3)[0] == 0


def test_sustained_single_file_failure_fires(tmp_path):
    """残余静默窗场景:每轮只 5/6(3y 单文件持续失败)也要报 —— 这是 #231 的核心目标形态。"""
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _fail(5, 6))
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True)
    assert rc == 0 and "alert=yes" in out, out
    assert "末轮=5/6" in out, out
    assert "连续失败 3 轮" in calls.read_text(encoding="utf-8")


# ============================================================
# 三、打桩生效证明(缺省不外发 / 参数生效 / 非法输入不炸链)
# ============================================================
def test_default_without_flag_never_invokes_notify(tmp_path):
    """沙箱生效证明:达阈值但**未传 --notify-send** ⇒ 连桩都不许被调用(零外发、零调用)。"""
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _fail())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=False)
    assert rc == 0, out
    assert "alert=yes" in out and "dry(未传 --notify-send)" in out, out
    assert not calls.exists(), "缺省必须零调用"


def test_dry_run_flag_passthrough(tmp_path):
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    for h in ROUNDS[:3]:
        _round(d, h, _fail())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True, dry_run=True)
    assert rc == 0, out
    assert "--dry-run" in calls.read_text(encoding="utf-8"), "--dry-run 须透传 notify.py"


def test_rounds_threshold_is_parameterized(tmp_path):
    """判别力锚点:阈值可调(防「阈值写死」),且 1 轮失败在 --rounds 1 下应触发。"""
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    _round(d, ROUNDS[2], _fail())
    rc, out = _run(d, ROUNDS[2], notify=stub, notify_send=True, rounds=1)
    assert rc == 0 and "alert=yes" in out, out
    assert calls.exists()


def test_bad_log_name_does_not_crash_chain(tmp_path):
    """非法日志名(如汇总日志)⇒ exit 0 不阻塞链,不误判不发。"""
    d = _logdir(tmp_path)
    stub, calls = _stub(tmp_path)
    bad = d / "intraday_snapshot_launchd.log"
    bad.write_text(_fail(), encoding="utf-8")
    rc, out = _run(d, "0000", notify=stub, notify_send=True, log=bad)
    assert rc == 0, out
    assert "非法轮日志名" in out
    assert not calls.exists()


def test_shell_tail_wiring(tmp_path):
    """链尾接线静态检查:intraday_snapshot.sh 必须调用本脚本 + 传 --log/--logdir/--notify-send + 恒不阻塞。"""
    sh = (REPO_ROOT / "scripts" / "intraday_snapshot.sh").read_text(encoding="utf-8")
    assert "check_sentiment_r2_upload.py" in sh
    line = [l for l in sh.splitlines() if "check_sentiment_r2_upload.py" in l and l.lstrip().startswith('"$PY"')]
    assert line, "链尾须以 $PY 调用本脚本"
    assert '--log "$LOG"' in line[0] and '--logdir "$LOGDIR"' in line[0] and "--notify-send" in line[0]
    tail = sh[sh.index(line[0]):][:300]
    assert "|| echo" in tail, "失败不得阻塞快照链"