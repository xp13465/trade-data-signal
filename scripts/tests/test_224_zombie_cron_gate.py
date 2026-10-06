# -*- coding: utf-8 -*-
"""#224 僵尸巡检 cron 机检: 判定纳入 job 生命周期
(触发前不判僵尸 / 触发后仍判 / recurring 巡检语义维持 / 真故障仍抓)。

样本形态 = **真实生产样本**(§18 L49 教训): 本文件 job dict 的字段集逐字取自
`.claude/scheduled_tasks.json` 真实 job(id/cron/prompt/createdAt/createdBy*), 关键事实:
  ① 一次性 job **没有** `recurring` 键(不是 `recurring=false` —— 别写成 `is False` 判定);
  ② 「兜底巡检」cron 才有 `recurring: True`;
  ③ `createdAt` 是**毫秒** epoch(约 1.79e12);
  ④ 一次性 job 的 cron 是「月+日定点」(如 `12 21 8 10 *`), 巡检 cron 是「分钟列表 + * * *」
     (如 `11,26,41,56 * * * *`)。
本机若存在真实 `.claude/scheduled_tasks.json`(未跟踪入 git, CI 无)→ 额外跑真实样本对账
(skipif); 其余用例不依赖 /tmp 真实进度文件(monkeypatch PROGRESS_DIR 到 tmp_path)、
不依赖 .env、不产生任何外发/生产写。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import check_task_state as m

REAL_TASKS = Path("/Users/linhuichen/code/trade/.claude/scheduled_tasks.json")

# 真实形态: 巡检兜底 cron(每小时的 11/26/41/56 分; prompt 含 agent-progress 路径)
PATROL_CRON = "11,26,41,56 * * * *"


def _patrol_prompt(name: str) -> str:
    return (f"兜底巡检({name}):读 /tmp/agent-progress-{name}.md 的 mtime;若距现在 >20 分钟未更新、"
            f"且该 agent 仍在 ListAgents 名册中,则先核它的转录 mtime;全部完成后 CronDelete")


def _oneshot_prompt(name: str) -> str:
    """一次性派单 cron 的真实形态 prompt(§0.2 三件套必然写到进度文件路径 → 被识别为巡检)。"""
    return (f"【一次性:派 #217 告警降噪 §0 上线观察(节后首个交易日盘后)】三项只读核对,只回结论。"
            f"进度 /tmp/agent-progress-{name}.md;兜底 cron 已在位。")


def _job(cid: str, cron: str, prompt: str, created_epoch: float, recurring: bool | None = None) -> dict:
    """按真实生产样本字段集构造 job(键集与真实文件逐字一致; recurring 仅真值时才写键)。"""
    j = {
        "id": cid,
        "cron": cron,
        "prompt": prompt,
        "createdAt": int(created_epoch * 1000),          # 真实形态 = 毫秒 epoch
        "createdBySessionId": "d08c47ab-19eb-44fb-85c4-4b62d4809072",
        "createdByPid": 9789,
        "createdByProcStart": "Tue Oct  6 09:47:01 2026",
        "createdInProject": "/Users/linhuichen/code/trade",
    }
    if recurring is not None:
        j["recurring"] = recurring
    return j


def _dated_cron(dt: datetime) -> str:
    """一次性 job 的真实形态 cron: 月+日定点(如 `12 21 8 10 *`)。"""
    return f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"


def _setup(monkeypatch, tmp_path, jobs: list[dict]):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "scheduled_tasks.json").write_text(
        json.dumps({"tasks": jobs}, ensure_ascii=False), encoding="utf-8")
    pdir = tmp_path / "progress"
    pdir.mkdir(exist_ok=True)
    monkeypatch.setattr(m, "PROGRESS_DIR", pdir)   # 隔离: 不碰真实 /tmp
    return repo, pdir


def _touch(pdir: Path, name: str, age_secs: float = 0.0) -> Path:
    p = pdir / f"agent-progress-{name}.md"
    p.write_text("STEP 1\n", encoding="utf-8")
    if age_secs:
        ts = time.time() - age_secs
        import os
        os.utime(p, (ts, ts))
    return p


def _fails(res) -> str:
    return "\n".join(res.detail) if res.status == m.CheckResult.FAIL else ""


def _pending_text(res) -> str:
    return "\n".join(res.detail)


# ── ① 一次性 job: 触发前不判僵尸(事故一根治) ────────────────────────────────
def test_oneshot_before_trigger_not_zombie(monkeypatch, tmp_path):
    fire = datetime.now() + timedelta(days=2)
    jobs = [_job("oneshot-future", _dated_cron(fire), _oneshot_prompt("224-oneshot"), time.time() - 86400)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.OK, f"触发前不应 FAIL/告警: {res.status} {res.msg} {res.detail}"
    assert "待观察" in res.msg and "不计僵尸" in res.msg
    assert "不判僵尸" in _pending_text(res)


# ── ② 巡检 cron 冷启动空窗期(事故二根治) ────────────────────────────────────
def test_patrol_cold_start_window_not_zombie(monkeypatch, tmp_path):
    """建 cron -> agent 写下首条进度 之前的空窗期(数分钟), 不判僵尸。"""
    now = time.time()
    for delta_min in (0.5, 5, 30, 59):     # 宽限 60min 内
        jobs = [_job("patrol-new", PATROL_CRON, _patrol_prompt("224-cold"), now - delta_min * 60,
                     recurring=True)]
        repo, _ = _setup(monkeypatch, tmp_path, jobs)
        res = m.check_zombie_crons(repo)
        assert res.status == m.CheckResult.OK, f"冷启动 {delta_min}min 不应 FAIL: {res.msg} {res.detail}"


# ── ③ 触发后仍判: 一次性 job 过 ready_at 无文件 = 真故障(agent 从未 echo) ──
def test_oneshot_after_trigger_missing_file_fails(monkeypatch, tmp_path):
    fire = datetime.now() - timedelta(days=3)
    jobs = [_job("oneshot-past", _dated_cron(fire), _oneshot_prompt("224-oneshot-past"),
                 (fire - timedelta(days=2)).timestamp())]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.FAIL
    assert "巡检进度文件不存在" in _fails(res)


# ── ④ recurring 巡检 cron: 宽限后仍无文件 = 僵尸(现行语义维持) ─────────────
def test_patrol_after_grace_missing_file_fails(monkeypatch, tmp_path):
    jobs = [_job("patrol-old", PATROL_CRON, _patrol_prompt("224-old"), time.time() - 2 * 86400,
                 recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.FAIL
    assert "巡检进度文件不存在" in _fails(res)


# ── ⑤ 真·已结束 agent 的 cron: 文件还在但 >7 天未更新 = 僵尸 ─────────────────
def test_stale_progress_file_fails(monkeypatch, tmp_path):
    jobs = [_job("patrol-stale", PATROL_CRON, _patrol_prompt("224-stale"), time.time() - 30 * 86400,
                 recurring=True)]
    repo, pdir = _setup(monkeypatch, tmp_path, jobs)
    _touch(pdir, "224-stale", age_secs=10 * 86400)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.FAIL
    assert "天未更新" in _fails(res)


def test_fresh_progress_file_ok(monkeypatch, tmp_path):
    jobs = [_job("patrol-ok", PATROL_CRON, _patrol_prompt("224-ok"), time.time() - 30 * 86400,
                 recurring=True)]
    repo, pdir = _setup(monkeypatch, tmp_path, jobs)
    _touch(pdir, "224-ok", age_secs=30)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.OK


# ── ⑥ 判据不依赖 `recurring` 字段(真实样本 fe1005df: recurring=True 但一次性) ──
def test_recurring_flag_is_not_the_discriminator(monkeypatch, tmp_path):
    now = time.time()
    far = datetime.now() + timedelta(days=1)
    # (a) recurring=True 但语义一次性、触发日在将来 -> 仍不判僵尸(真实样本同形态)
    jobs = [_job("oneshot-flagged", _dated_cron(far), _oneshot_prompt("224-flagged"), now - 3600,
                 recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    assert m.check_zombie_crons(repo).status == m.CheckResult.OK
    # (b) 无 recurring 键 + 巡检形态 cron + 建于 2 天前 + 无文件 -> 照样 FAIL(不放行真故障)
    jobs = [_job("patrol-unflagged", PATROL_CRON, _patrol_prompt("224-unflagged"), now - 2 * 86400)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.FAIL


# ── ⑦ cron 不可解析 -> 如实退化按 createdAt(不静默放过) ─────────────────────
def test_unparseable_cron_falls_back_to_created_at(monkeypatch, tmp_path):
    now = time.time()
    bad = "0 0 1 1 * * *"          # 7 字段(含秒), 非本项目真实形态 -> 不可解析
    jobs = [_job("bad-recent", bad, _patrol_prompt("224-bad-new"), now - 300, recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.OK
    assert "退化按 createdAt" in _pending_text(res)
    jobs = [_job("bad-old", bad, _patrol_prompt("224-bad-old"), now - 2 * 86400, recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    assert m.check_zombie_crons(repo).status == m.CheckResult.FAIL


# ── ⑧ 既有兜底语义未被削弱 ───────────────────────────────────────────────────
def test_missing_json_warns_not_fails(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(m, "PROGRESS_DIR", tmp_path / "progress")
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.WARN and "不存在" in res.msg


def test_patrol_without_parseable_path_warns(monkeypatch, tmp_path):
    # 命中"巡检兜底"字样但 prompt 内无可解析的进度文件路径 -> 告警(既有语义保留)
    jobs = [_job("no-path", PATROL_CRON, "巡检兜底:读进度文件,本轮无路径", time.time() - 2 * 86400,
                 recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.WARN and "未含可解析" in res.detail[0]


def test_non_patrol_jobs_ignored(monkeypatch, tmp_path):
    jobs = [_job("plain", "0 9 * * *", "每日日报, 无进度文件字样", time.time() - 30 * 86400)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.OK and "无巡检兜底 cron" in res.msg


# ── ⑨ 闸门位置与威力不动: --deploy-mode FAIL 仍阻断; --skip-zombie-crons 语义不变 ──
def _stub_ab(monkeypatch):
    monkeypatch.setattr(m, "check_pending_index", lambda repo: m._ok("pending_index", "stub"))
    monkeypatch.setattr(m, "check_tasks_references", lambda repo: m._ok("tasks_refs", "stub"))


def test_deploy_mode_still_blocks_on_zombie(monkeypatch, tmp_path, capsys):
    jobs = [_job("patrol-zombie", PATROL_CRON, _patrol_prompt("224-zombie"), time.time() - 2 * 86400,
                 recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    _stub_ab(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_task_state.py", "--repo", str(repo), "--deploy-mode"])
    assert m.main() == 1                      # FAIL 仍阻断(deploy 链威力不变)
    assert "zombie_crons" in capsys.readouterr().out


def test_skip_zombie_crons_semantics_unchanged(monkeypatch, tmp_path, capsys):
    jobs = [_job("patrol-zombie", PATROL_CRON, _patrol_prompt("224-zombie"), time.time() - 2 * 86400,
                 recurring=True)]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    _stub_ab(monkeypatch)
    monkeypatch.setattr(sys, "argv",
                        ["check_task_state.py", "--repo", str(repo), "--deploy-mode", "--skip-zombie-crons"])
    assert m.main() == 0                      # CI 干净环境跳过 C 维度(语义不变)
    out = capsys.readouterr().out
    assert "僵尸巡检" not in out and "✗" not in out   # C 维度整段未跑, 无任何 FAIL


# ── ⑩ 真实生产样本对账(本机有真实文件才跑; CI 自动 skip) ────────────────────
@pytest.mark.skipif(not REAL_TASKS.exists(), reason="无真实 .claude/scheduled_tasks.json(CI 干净环境)")
def test_real_sample_shape_parity():
    """fixture 的键集/类型必须与真实 job 逐字一致(L49: 别用"看起来合理"的样本)。"""
    real = json.loads(REAL_TASKS.read_text(encoding="utf-8"))["tasks"]
    assert real, "真实 cron 清单为空?"
    for j in real:
        assert set(j) >= {"id", "cron", "prompt", "createdAt"}
        assert isinstance(j["createdAt"], int) and j["createdAt"] > 1e11, "createdAt 应为毫秒 epoch"
        assert isinstance(j["cron"], str) and len(j["cron"].split()) == 5, "真实 cron 为 5 字段"
        assert m._job_created_epoch(j) is not None
    # fixture 形状与真实一致(同键集 + 同类 job 的 recurring 键行为一致)
    fixture = _job("x", PATROL_CRON, _patrol_prompt("x"), time.time(), recurring=True)
    assert set(fixture) == (set(real[0]) | {"recurring"})
    oneshot = [j for j in real if "recurring" not in j]
    assert oneshot, "真实样本应含一次性 job(无 recurring 键)"


@pytest.mark.skipif(not REAL_TASKS.exists(), reason="无真实 .claude/scheduled_tasks.json(CI 干净环境)")
def test_real_jobs_no_false_zombie_when_pending(monkeypatch, tmp_path):
    """真实 job 跑判定: 只有「已过 ready_at」的 job 才允许出现在 FAIL 里(其余必须不误报)。"""
    real = json.loads(REAL_TASKS.read_text(encoding="utf-8"))["tasks"]
    repo, pdir = _setup(monkeypatch, tmp_path, real)
    pdir.mkdir(exist_ok=True)                 # 空进度目录 = 模拟"文件尚未产生"
    res = m.check_zombie_crons(repo)
    now = time.time()
    for j in real:
        p = (j.get("prompt") or "")
        if "巡检兜底" not in p and "agent-progress" not in p:
            continue
        ready_at, _why = m._progress_ready_at(j)
        assert ready_at is not None, f"真实 job {j['id']} 应能算出 ready_at"
        mentioned = j["id"] in _fails(res)
        if ready_at > now:
            assert not mentioned, f"真实 job {j['id']} ready_at={ready_at} 在将来, 不应被误判僵尸"