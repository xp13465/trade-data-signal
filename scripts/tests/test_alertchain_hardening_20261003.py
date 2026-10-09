#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云体检 D3 告警链加固（feat/alertchain-hardening-20261003）—— 4 条修复的自验 pytest。

覆盖（每条 = 实跑证据 + 反向测）：
  ① brief_push 静默失败（D3 §3-2）：wrapper 失败分支必须产生显式信号（notify --severe
     → 实跑写 latest.md 头部「brief_push 推送失败」；--dry-run 下由 notify 内部 guard
     挡下=只打印不落盘，#184 2026-10-07）。反向：成功路径不触发任何 notify
     （wrapper 退出码恒 0 设计不动）。
  ② latest.md 覆盖区「最近一次 SEVERE」引用（D3 §5）：severe 流水 + 后续普通告警/恢复
     覆盖头部 → 覆盖区固定保留「最近一次 SEVERE」引用行，严重告警不再被恢复消息静默
     盖掉。反向：流水区无 severe 时不产生引用行（不污染头部、不假报严重）。
  ③ schedule-monitor heartbeat 消费方（D3 §6 P0-1）：心跳缺失/陈旧 → notify --severe
     告警（沉默即故障）；告警命令必须带防轰炸 dedup key/window（每窗口 1 封）；健康心跳
     静默零输出、零 notify 调用。

测试隔离：全部在 pytest tmp_path / monkeypatch 内构造状态文件，调**真实判定代码**
（notify.write_alert / check_monitor_heartbeat.main），绝不触发真实邮件/飞书发送、
绝不写生产数据目录。wrapper 用例用子进程 + REPO 指向 tmp_path + --dry-run。

跑法：
  python3 -m pytest -q scripts/tests/test_alertchain_hardening_20261003.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest  # noqa: F401  (保留显式依赖声明)

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402  (conftest 已加 scripts/ 入 sys.path)
import check_monitor_heartbeat as cmh  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"


# ══════════════════════════════════════════════════════════════════
# ② latest.md 覆盖区「最近一次 SEVERE」引用
# ══════════════════════════════════════════════════════════════════
def _make_severe_entry(ts: str, subject: str, summary: str = "严重告警摘要") -> str:
    """与 _mirror_severe 同构的流水条目文本。"""
    return (f"## [severe] {ts} · {subject}\n"
            f"- **级别**: severe\n"
            f"- **来源**: pytest\n"
            f"- **通道**: email=OK feishu=OK\n"
            f"- **摘要**: {summary}")


def _seed_latest(tmp_path: Path, entries: list[str]) -> Path:
    """seed latest.md：纯头部 + 流水条目列表（与 _compose_latest 同构）。"""
    latest = tmp_path / "latest.md"
    head = ("# 严重告警（最新一次）\n\n- **告警时间**：seed\n- **问题**：seed\n"
            "\n## 详情\n\nseed")
    chunks = [head] + [f"---\n{e}" for e in entries]
    latest.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")
    return latest


def test_latest_severe_ref_survives_recovery_overwrite(tmp_path, monkeypatch):
    """核心场景（D3 §5 现场 10-03）：流水区有冻结表 SEVERE，随后「计划任务监控恢复」
    覆盖头部区 → 头部保留「最近一次 SEVERE」引用，严重告警不被恢复消息盖掉。"""
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "latest.md")
    latest = _seed_latest(tmp_path, [
        _make_severe_entry("2026-09-18 10:00:00", "冻结表缺失告警",
                           "backtest 拒绝补冻，注意人工确认")])
    # 模拟 schedule_monitor 恢复消息覆盖头部（不带 --severe）
    notify.write_alert("计划任务监控恢复", "fetch_news 恢复, 无需操作")
    out = latest.read_text(encoding="utf-8")
    assert "最近一次 SEVERE" in out, "覆盖区必须保留最近一次 SEVERE 引用"
    assert "冻结表缺失告警" in out, "引用必须指向冻结表 SEVERE（D3 §5 现场）"
    assert "计划任务监控恢复" in out, "本次 monitor 事件仍显示（原语义不动）"


def test_latest_severe_ref_takes_newest(tmp_path, monkeypatch):
    """流水区多条 severe 时引用取最新一条（流水区尾部=最新，与 cap50 滚动同向）。"""
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "latest.md")
    latest = _seed_latest(tmp_path, [
        _make_severe_entry("2026-09-30 17:56:00", "baostock 封禁熔断", "第一重心"),
        _make_severe_entry("2026-10-03 00:30:00", "fetch_news R2 锁跳过", "第二重心"),
    ])
    notify.write_alert("计划任务监控告警", "某任务异常")
    out = latest.read_text(encoding="utf-8")
    assert "fetch_news R2 锁跳过" in out, "引用=最新一条 severe"
    assert "2026-10-03 00:30:00" in out


def test_latest_no_severe_no_ref(tmp_path, monkeypatch):
    """反向测：流水区无 severe 条目 → 覆盖区不产生引用行。"""
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "latest.md")
    latest = _seed_latest(tmp_path, [])
    notify.write_alert("计划任务监控恢复", "一切正常")
    out = latest.read_text(encoding="utf-8")
    assert "最近一次 SEVERE" not in out, "无 severe 时不得出现引用行"


def test_latest_severe_ref_parse_ignores_garbage():
    """_latest_severe_ref 对非 severe/空行/乱行条目免疫（解析准、不崩）。"""
    entries = [
        "## [severe] 2026-09-18 10:00:00 · 冻结表缺失告警\n- **摘要**: abc",
        "## [恢复] 2026-09-18 11:00:00 · 已恢复（不是 severe 格式）",
        "",
        "乱行无 ## 头",
    ]
    ref = notify._latest_severe_ref(entries)
    assert ref.startswith("2026-09-18 10:00:00 · 冻结表缺失告警"), f"got: {ref!r}"


# ══════════════════════════════════════════════════════════════════
# ① brief_push wrapper 失败显式信号
# ══════════════════════════════════════════════════════════════════
def _setup_wrapper_tmp(repo_tmp: Path) -> Path:
    """搭 wrapper 隔离环境：.venv 指向真实 python + 复制脚本 + 空 config。
    不建 daily_brief.json → brief_push.py 必然失败返回 1 → wrapper else 分支。"""
    bin_dir = repo_tmp / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "python").symlink_to(sys.executable)
    scripts_dir = repo_tmp / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for f in ("brief_push.py", "util_atomic.py", "notify.py", "alert_denoise_rules.py"):
        src = SCRIPTS / f
        assert src.exists(), f"{src} 必须存在"
        (scripts_dir / f).write_bytes(src.read_bytes())
    cfg = repo_tmp / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "brief_push.json").write_text('{"api_base": "", "admin_key": ""}',
                                         encoding="utf-8")
    (cfg / "feishu.json").write_text('{"enabled": false}', encoding="utf-8")
    (repo_tmp / "data" / "logs").mkdir(parents=True, exist_ok=True)
    assert (SCRIPTS / "brief_push_wrapper.sh").exists()
    return SCRIPTS / "brief_push_wrapper.sh"


def test_brief_push_failure_produces_alert(tmp_path):
    """①失败场景：wrapper 失败分支调 notify --severe → 显式信号（#184 后 dry-run
    下为占位打印，**不写 latest.md**）；wrapper 恒 exit 0（原设计不动）。

    实跑（无 --dry-run）路径仍写 latest.md——写路径由
    test_184_notify_dryrun_gate_20261007.py 以打桩方式覆盖零外发验证。"""
    env = dict(os.environ, REPO=str(tmp_path))
    wrapper = _setup_wrapper_tmp(tmp_path)
    r = subprocess.run(["bash", str(wrapper), "--dry-run"], env=env,
                       capture_output=True, text=True, timeout=120)
    log = (tmp_path / "data" / "logs" / "brief_push.log").read_text(encoding="utf-8")
    assert "✗ 失败 rc=1" in log, "失败 rc 已记录"
    assert "[告警] brief_push 推送失败 rc=1" in log, "notify --severe 已发起（dry-run 打印）"
    assert "[notify][dry-run]" in log, "notify dry-run 占位输出已打印（外发被挡下）"
    assert "write_alert 跳过写" in log, "#184：dry-run 下 write_alert 被守卫挡下（打印跳过）"
    latest = tmp_path / "data" / "alerts" / "latest.md"
    assert not latest.exists(), "#184：dry-run 不得写 latest.md（零落盘）"
    assert r.returncode == 0, "wrapper 退出码恒 0 设计必须保留"


def test_brief_push_success_silent(tmp_path):
    """反向测：成功路径不触发失败分支（✓ 完成、latest.md 不被写）。"""
    env = dict(os.environ, REPO=str(tmp_path))
    wrapper = _setup_wrapper_tmp(tmp_path)
    data_dir = tmp_path / "static-site" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "daily_brief.json").write_text(
        '{"meta": {"date": "20261009", "direction": "震荡", "range": "3000-3100"},'
        ' "header": "h", "sections": [], "disclaimer": "d"}', encoding="utf-8")
    r = subprocess.run(["bash", str(wrapper), "--date=20261009", "--dry-run"],
                       env=env, capture_output=True, text=True, timeout=120)
    log = (tmp_path / "data" / "logs" / "brief_push.log").read_text(encoding="utf-8")
    assert "✓ 完成" in log
    assert "✗ 失败" not in log, "成功路径不得进入失败分支"
    latest = tmp_path / "data" / "alerts" / "latest.md"
    assert not latest.exists(), "成功路径不写告警 latest.md"
    assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════
# ③ schedule-monitor heartbeat 消费方
# ══════════════════════════════════════════════════════════════════
def _run_heartbeat(args, monkeypatch, captured, output: str = None) -> int:
    """跑 cmh.main，把 subprocess.run patch 成记录器（返回成功，绝不真调 notify）。

    #241 Pattern B / W2(2026-10-10): cmh 判据由「rc」改为「notify 输出三态」(notify_state)。
    故 fake 必须回**真实汇总行**(sent), 否则空输出 ⇒ failed ⇒ rc 2(旧空输出的人造假样本作废)。
    """
    if output is None:
        output = "[notify] 汇总：已发出 email/feishu\n"  # 真实通用路径成功行(notify.py:2359)

    def fake_run(cmd, *a, **k):
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=output)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return cmh.main(args)


def test_heartbeat_fresh_silent(tmp_path, monkeypatch):
    """反向测：健康心跳（1min 前更新）→ 静默退出 0，零 notify 调用、零告警输出。"""
    hb = tmp_path / "heartbeat.txt"
    now = time.time()
    hb.write_text("2026-10-03 10:00:00\nalerts=0\n", encoding="utf-8")
    os.utime(hb, (now - 60, now - 60))  # 60s 前=新鲜
    captured = []
    rc = _run_heartbeat(["--heartbeat-path", str(hb), "--stale-seconds", "1800",
                         "--repo", str(ROOT)], monkeypatch, captured)
    assert rc == 0
    assert captured == [], "健康路径不得调用 notify"


def test_heartbeat_missing_stale_alerts(tmp_path, monkeypatch):
    """③超时场景：心跳文件缺失 → notify --severe 告警发起（沉默即故障），命令带
    dedup key/window 防轰炸。"""
    missing = tmp_path / "nope-heartbeat.txt"
    captured = []
    rc = _run_heartbeat(["--heartbeat-path", str(missing), "--stale-seconds", "1800",
                         "--repo", str(ROOT)], monkeypatch, captured)
    assert rc == 0, "告警已由 notify 独立通道发起，脚本正常完成"
    assert len(captured) == 1, "缺失场景必须调用 notify 一次"
    joined = " ".join(str(c) for c in captured[0])
    assert "--severe" in joined
    assert "--dedup-key" in joined and "schedule_monitor_heartbeat" in joined
    assert "--dedup-window" in joined and str(cmh.DEDUP_WINDOW) in joined
    assert "schedule-monitor 心跳超时" in joined


def test_heartbeat_stale_old_file_alerts(tmp_path, monkeypatch):
    """③陈旧心跳（2h 前 mtime）→ 同样告警发起（沉默即故障语义覆盖"有文件但停更"）。"""
    hb = tmp_path / "stale-heartbeat.txt"
    now = time.time()
    hb.write_text("2026-10-03 08:00:00\nalerts=0\n", encoding="utf-8")
    os.utime(hb, (now - 7200, now - 7200))  # 2h 前=陈旧
    captured = []
    rc = _run_heartbeat(["--heartbeat-path", str(hb), "--stale-seconds", "1800",
                         "--repo", str(ROOT)], monkeypatch, captured)
    assert rc == 0
    assert len(captured) == 1
    assert "--severe" in " ".join(str(c) for c in captured[0])