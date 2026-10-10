# -*- coding: utf-8 -*-
"""test_237_check_preupload_backup_pytest.py — #237 D③ 观测点(check_preupload_backup.py)static-only 单测。

覆盖(对应设计文 §4.0 D③ / §5.1 改点 5 / §5.2 验收 6「门控」):
  ① 判定口径纯函数: parse_log_lines / judge 四分支(NO_RUN / failed!=0 / 护栏空转 / OK);
  ② landed 计数通道: count_landed 先探针(非 200 ⇒ 抛错 ⇒ 上层 exit 2, 不把网络抖动
     误判成「护栏空转」假 FAIL);探针 200 ⇒ 走 _list_keys 全量分页;
  ③ 端到端 --dump dry: 构造样本 → rc/stdout 判定正确;无 --notify ⇒ 零外发(ZeroOutboundTrap);
     有 --notify ⇒ 只调 do_notify(测试内打桩, 不发真告警, §18 L48);
  ④ 看门狗不回归: 判定用的正则**只认** `备份 N/M 已备份 …` 进度行, **不认** `[N/M] …(sizeB)`
     形态(否则会污染 r2_upload_async.sh 的低速判据, 见 §4.5)。
零网络 / 零外发: 全部 R2 与 notify 打桩。
"""
from __future__ import annotations

import json
import sys

import pytest

import check_preupload_backup as cpb  # noqa: E402 (conftest 已注入 scripts/ 到 sys.path)

from _zero_outbound import ZeroOutboundTrap  # noqa: E402


# ── ① 日志解析(纯函数)────────────────────────────────────────────────────────
def test_parse_log_lines_sums():
    lines = [
        "[index] 备份 64/256 已备份 60 跳过 4",
        "[index] 备份完成 copied=60 skipped=4 failed=0",
        "[nav] 备份完成 copied=192 skipped=0 failed=3",
        "无关行 备份完成 copied=x skipped=y failed=z",
        "[nav] 备份 128/256 已备份 100 跳过 28",
    ]
    st = cpb.parse_log_lines(lines)
    assert st == {"runs": 2, "copied": 252, "skipped": 4, "failed": 3, "candidates": 256}


def test_parse_log_lines_empty_is_zero():
    assert cpb.parse_log_lines([]) == {"runs": 0, "copied": 0, "skipped": 0,
                                       "failed": 0, "candidates": 0}


# ── ② judge 四分支 ──────────────────────────────────────────────────────────
def test_judge_no_run_never_alarms():
    rc, verdict, _ = cpb.judge(0, cpb.parse_log_lines([]))
    assert (rc, verdict) == (0, "NO_RUN")


def test_judge_failed_positive_fails():
    rc, verdict, msg = cpb.judge(5, cpb.parse_log_lines(["[a] 备份完成 copied=5 skipped=0 failed=2"]))
    assert rc == 1 and verdict == "FAIL" and "failed=2" in msg


def test_judge_failed_minus_one_fails():
    """异常早退路径打的是 failed=-1(见 upload_r2 调用点 except);它不是「0 失败」。"""
    rc, verdict, _ = cpb.judge(0, cpb.parse_log_lines(["[a] 备份完成 copied=0 skipped=0 failed=-1"]))
    assert rc == 1 and verdict == "FAIL"


def test_judge_empty_spin_fails():
    """护栏空转: 日志自称备了 64 个, 备份桶零对象 ⇒ FAIL(§5.2-7 不许只看日志自证)。"""
    rc, verdict, msg = cpb.judge(0, cpb.parse_log_lines(["[a] 备份 64/256 已备份 64 跳过 0",
                                                         "[a] 备份完成 copied=64 skipped=0 failed=0"]))
    assert rc == 1 and verdict == "FAIL" and "空转" in msg


def test_judge_progress_only_is_no_run_not_false_alarm():
    """只有进度行(无 完成 行)= 在飞/未跑 ⇒ NO_RUN, 不报(防 15min 周期撞在飞窗口假 FAIL)。"""
    rc, verdict, _ = cpb.judge(0, cpb.parse_log_lines(["[a] 备份 64/256 已备份 0 跳过 0"]))
    assert (rc, verdict) == (0, "NO_RUN")


def test_judge_all_new_keys_no_alarm():
    """首次全量: 候选 256 但源侧全 404(无备份必要)⇒ copied=skipped=0, landed=0 ⇒ OK。"""
    stat = cpb.parse_log_lines(["[nav] 备份 64/256 已备份 0 跳过 0",
                                "[nav] 备份完成 copied=0 skipped=0 failed=0"])
    rc, verdict, _ = cpb.judge(0, stat)
    assert (rc, verdict) == (0, "OK")


def test_judge_skip_all_is_ok():
    """全减量跳过(copied=0 但 candidates>0) + landed>0 ⇒ OK(不是空转)。"""
    stat = cpb.parse_log_lines(["[a] 备份 64/256 已备份 0 跳过 256",
                                "[a] 备份完成 copied=0 skipped=256 failed=0"])
    rc, verdict, _ = cpb.judge(256, stat)
    assert (rc, verdict) == (0, "OK")


def test_judge_normal_ok():
    stat = cpb.parse_log_lines(["[a] 备份 64/256 已备份 60 跳过 4",
                                "[a] 备份完成 copied=60 skipped=4 failed=0"])
    rc, verdict, _ = cpb.judge(64, stat)
    assert (rc, verdict) == (0, "OK")


# ── ③ landed 计数通道(探针防假 FAIL)────────────────────────────────────────────
class _FakeUR:
    BACKUP_BUCKET = "bkt-backup-test237"

    def __init__(self, probe_status=200, keys=()):
        self.probe_status = probe_status
        self.keys = list(keys)
        self.calls = []

    def s3_request(self, method, key, query="", bucket=None, **kw):
        self.calls.append((method, key, query, bucket))
        return (self.probe_status, b"<ListBucketResult/>")

    def _list_keys(self, prefix, bucket=None):
        assert prefix.startswith("pre-upload/")
        return list(self.keys)


def test_count_landed_probe_failure_raises():
    """R2 不可达 ⇒ 抛错(上层 exit 2 无法判定), 绝不静默返回 0 触发假「护栏空转」。"""
    with pytest.raises(RuntimeError, match="LIST 探针失败"):
        cpb.count_landed(_FakeUR(probe_status=503), "20261010")


def test_count_landed_ok_counts_keys():
    ur = _FakeUR(probe_status=200, keys=["pre-upload/20261010/a", "pre-upload/20261010/b"])
    assert cpb.count_landed(ur, "20261010") == 2
    assert ur.calls[0][2].startswith("list-type=2&prefix=")   # 探针真的打了 LIST


# ── ④ 端到端 --dump dry(零外发)───────────────────────────────────────────────
def _dump(tmp_path, landed, lines):
    p = tmp_path / "dump.json"
    p.write_text(json.dumps({"landed": landed, "log_lines": lines}), encoding="utf-8")
    return str(p)


def test_dump_end_to_end_no_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_preupload_backup.py", "--dump", _dump(tmp_path, 0, [])])
    with ZeroOutboundTrap() as trap:
        rc = cpb.main()
    assert rc == 0
    assert trap.hits == []


def test_dump_end_to_end_fail_and_no_notify_without_flag(tmp_path, monkeypatch):
    dump = _dump(tmp_path, 0, ["[a] 备份完成 copied=64 skipped=0 failed=0"])
    monkeypatch.setattr(sys, "argv", ["check_preupload_backup.py", "--dump", dump])
    called = []
    monkeypatch.setattr(cpb, "do_notify", lambda *a, **k: called.append(a) or True)
    with ZeroOutboundTrap() as trap:
        rc = cpb.main()
    assert rc == 1
    assert called == []          # 无 --notify ⇒ 绝不外发
    assert trap.hits == []


def test_dump_end_to_end_notify_flag_calls_stub(tmp_path, monkeypatch):
    dump = _dump(tmp_path, 0, ["[a] 备份完成 copied=64 skipped=0 failed=0"])
    monkeypatch.setattr(sys, "argv",
                        ["check_preupload_backup.py", "--dump", dump, "--notify"])
    called = []
    monkeypatch.setattr(cpb, "do_notify", lambda *a, **k: called.append(a) or True)
    with ZeroOutboundTrap() as trap:
        rc = cpb.main()
    assert rc == 1 and len(called) == 1
    assert trap.hits == []       # do_notify 已打桩 ⇒ 零真实外发


def test_dump_bad_json_returns_2(tmp_path, monkeypatch):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_preupload_backup.py", "--dump", str(p)])
    assert cpb.main() == 2


# ── ⑤ 看门狗不回归: 进度行正则不撞低速判据形态 ────────────────────────────────
def test_progress_regex_does_not_match_watchdog_bracket_form():
    assert cpb._RE_PROG.search("[fund-nav] 备份 64/256 已备份 60 跳过 4") is not None
    assert cpb._RE_PROG.search("[fund-nav] [64/256] (1234B)") is None
    assert cpb._RE_DONE.search("[fund-nav] [64/256] (1234B)") is None


# ── ⑥ 挂载点存在(schedule_monitor 子进程调用, 同 check_s06_freshness 先例)─────
def test_wired_into_schedule_monitor():
    from pathlib import Path
    sm = (Path(__file__).absolute().parent.parent / "schedule_monitor.sh").read_text(encoding="utf-8")
    assert "check_preupload_backup.py" in sm
    i = sm.index("check_preupload_backup.py")
    seg = sm[i - 260:i + 700]
    assert '"--notify"' in seg and "capture_output=True" in seg and "timeout=" in seg
    assert '"/tmp"' not in seg   # 不落 /tmp 日志