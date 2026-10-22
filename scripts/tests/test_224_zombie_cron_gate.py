# -*- coding: utf-8 -*-
"""#224 僵尸巡检 cron 机检: 判定纳入 job 生命周期
(触发前不判僵尸 / 触发后仍判 / recurring 巡检语义维持 / 真故障仍抓)。

样本形态 = **真实生产样本**(§18 L49 教训): 本文件 job dict 的字段集逐字取自
`.claude/scheduled_tasks.json` 真实 job(id/cron/prompt/createdAt/createdBy*), 关键事实:
  ① 一次性 job **没有** `recurring` 键(不是 `recurring=false` —— 别写成 `is False` 判定);
  ② 「兜底巡检」cron 才有 `recurring: True`;
  ③ `createdAt` 是**毫秒** epoch(约 1.79e12);
  ④ 一次性 job 的 cron 是「月+日定点」(如 `12 21 8 10 *`), 巡检 cron 是「分钟列表 + * * *」
     (如 `11,26,41,56 * * * *`);
  ⑤ 调度器**触发后会写运行期键**(如 `lastFiredAt`, 毫秒 epoch) —— 这类键不属于 job 的
     固定 schema 面, 形状对账前先剔除(见 `RUNTIME_VOLATILE_KEYS`), 不要求固定样本包含。
本机若存在真实 `.claude/scheduled_tasks.json`(未跟踪入 git, CI 无)→ 额外跑真实样本对账;
**真实样本优先, 缺失/为空/无巡检类 job 时退回测试自造的固定样本继续跑同一套断言**
(不 skip 核心判定逻辑)—— 本机 cron 状态(巡检 job 在跑 / 已删净 / 只有普通 job)不再
影响用例结论(环境依赖型 flaky, §18 L51 同族)。其余用例不依赖 /tmp 真实进度文件
(monkeypatch PROGRESS_DIR 到 tmp_path)、不依赖 .env、不产生任何外发/生产写。
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import check_task_state as m

# 真实样本路径(默认生产路径; 环境变量仅为测试夹具覆盖用, 不改生产行为)
REAL_TASKS = Path(os.environ.get(
    "TRADE_SCHEDULED_TASKS",
    "/Users/linhuichen/code/trade/.claude/scheduled_tasks.json"))

# 真实形态: 巡检兜底 cron(每小时的 11/26/41/56 分; prompt 含 agent-progress 路径)
PATROL_CRON = "11,26,41,56 * * * *"

# 固定时钟锚(2027-01-15 本地时), 与被测数据日期无关, 用例永久稳定(L51)
FROZEN_NOW = 1_800_000_000.0


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


# 调度器**运行期**写入的易变键(随每次触发变化, 不属于 job 的固定 schema 面):
# 2026-10-22 独立审查实证 —— 真实巡检 job(如 `5b5ce7a9`)触发后带 `lastFiredAt`(共 10 键),
# 固定样本没有; 旧断言 `set(fixture) == set(real) | {"recurring"}` 在「真实文件只剩巡检
# job」时必 AssertionError(与新 docstring 承诺"全巡检样本也合法"自相矛盾)。
# 注意: 只列**已观察到**的运行期键, 不做通配/前缀匹配 —— 通配会把固定 schema 字段改名
# (如 `createdAt` -> `created_at`)一并放过, 形状对账就失去意义。发现新运行期键=形状漂移,
# 显式登记到这里并说明依据。
RUNTIME_VOLATILE_KEYS = frozenset({"lastFiredAt"})


def _stable_keys(job: dict) -> set:
    """job 的「固定 schema 键集」= 全部键 - 调度器运行期易变键。"""
    return set(job) - RUNTIME_VOLATILE_KEYS


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
    """只返回**真 FAIL 行**(排除 pending 说明行)。

    实现在 FAIL 时把 detail_fail 与 detail_pending 拼进同一个 `res.detail`
    (check_task_state.py:515-517), pending 行也带 job id —— 不过滤就会把
    「ready_at 在将来、本就**不应**判僵尸」的 job 误当成「被 FAIL 提及」, 造成假红
    (2026-10-22 时敏假红根因, 同 L51 教训族)。
    """
    if res.status != m.CheckResult.FAIL:
        return ""
    return "\n".join(ln for ln in res.detail if "不判僵尸" not in ln)


def _pending_lines(res) -> str:
    """只取 pending 说明行(含「不判僵尸」), 用于反向断言事故形态确实出现。"""
    return "\n".join(ln for ln in res.detail if "不判僵尸" in ln)


def _pending_text(res) -> str:
    return "\n".join(res.detail)


def _freeze_now(monkeypatch, fixed_epoch: float) -> None:
    """冻结被测模块看到的 now。

    只替换 `check_task_state` 模块里的 `time` 名字, **不动标准库 time 全局**
    (改全局会影响 pytest/其他线程的计时)。`check_zombie_crons` 用 `m.time.time()`
    取当前时刻, `_progress_ready_at` / `_cron_next_fire_after` 用 `m.time.localtime`
    / `mktime` 解释 cron —— 统一走这个桩, 保证「当前时刻」与「cron 解析时区」口径一致。
    用例因此不依赖真实运行时刻(禁写死某天日期字面量: 冻结值由样本数据推导/固定时钟锚)。
    """
    real = m.time
    stub = types.SimpleNamespace(
        time=lambda: fixed_epoch,
        localtime=real.localtime,
        mktime=real.mktime,
        strftime=real.strftime,
    )
    monkeypatch.setattr(m, "time", stub)


def _patrol_relevant(jobs: list[dict]) -> list[tuple[dict, float | None]]:
    """筛出巡检类 job 并算 ready_at(与 check_zombie_crons 同一判据, 顺序保持)。"""
    out: list[tuple[dict, float | None]] = []
    for j in jobs:
        p = (j.get("prompt") or "")
        if "巡检兜底" not in p and "agent-progress" not in p:
            continue
        ready_at, _why = m._progress_ready_at(j)
        out.append((j, ready_at))
    return out


def _fixed_patrol_jobs() -> list[dict]:
    """真实样本无巡检类 job 时的固定兜底样本。

    ≥2 个巡检类 job、createdAt 不同、键集与真实 job 一致(`_job` 逐字取自生产样本),
    且 prompt 含可解析的 /tmp/agent-progress-*.md 路径 —— 保证「pending 侧 + 真 FAIL 侧」
    两条断言路径都能被走到, 不因本机 cron 状态变化而失去判别力。
    """
    return [
        _job("fixed-patrol-old", PATROL_CRON, _patrol_prompt("224-fixed-old"),
             FROZEN_NOW - 3 * 86400, recurring=True),
        _job("fixed-patrol-new", PATROL_CRON, _patrol_prompt("224-fixed-new"),
             FROZEN_NOW - 3600, recurring=True),
    ]


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


# ── ⑩ 真实生产样本对账(真实样本优先; 缺失/空/无巡检类 job 退回固定样本) ─────
def _assert_shape_parity(real_jobs: list[dict]) -> None:
    """固定样本 vs 真实 job 的**固定 schema 键集**对账(L49: 别用"看起来合理"的样本)。

    对账面先剔除 `RUNTIME_VOLATILE_KEYS`(调度器运行期写入的易变键), 否则真实文件
    「只剩巡检 job 且刚触发过」时会误红。真实清单为空 / 只有巡检类 job 都是**合法 cron
    状态**(本机可能刚清空 / 只剩巡检), 不判失败; 空清单时只校验 fixture 制造器契约。
    """
    for j in real_jobs:
        assert set(j) >= {"id", "cron", "prompt", "createdAt"}
        assert isinstance(j["createdAt"], int) and j["createdAt"] > 1e11, "createdAt 应为毫秒 epoch"
        assert isinstance(j["cron"], str) and len(j["cron"].split()) == 5, "真实 cron 为 5 字段"
        assert m._job_created_epoch(j) is not None
    # fixture 制造器的形状契约(不依赖真实文件内容, 空清单/全巡检也能校验)
    patrol_fixture = _job("x", PATROL_CRON, _patrol_prompt("x"), time.time(), recurring=True)
    oneshot_fixture = _job("x", "0 9 * * *", "每日日报, 无进度文件字样", time.time())
    assert patrol_fixture["recurring"] is True
    assert "recurring" not in oneshot_fixture, "一次性 job 不得写 recurring 键"
    if real_jobs:
        # 真实首个 job 可能是一次性(无 recurring 键) -> 并集归一后只比固定 schema 面
        assert _stable_keys(patrol_fixture) == (_stable_keys(real_jobs[0]) | {"recurring"}), (
            f"巡检固定样本与真实 job 的固定键集不一致: fixture={sorted(_stable_keys(patrol_fixture))} "
            f"real={sorted(real_jobs[0])}(运行期键 {sorted(RUNTIME_VOLATILE_KEYS)} 已剔除)")
        # 真实样本含一次性 job 时对账「无 recurring 键」形态; 全巡检样本也合法, 不判失败
        oneshot = [j for j in real_jobs if "recurring" not in j]
        if oneshot:
            assert _stable_keys(oneshot_fixture) == _stable_keys(oneshot[0]), (
                f"一次性固定样本与真实 job 的固定键集不一致: "
                f"fixture={sorted(_stable_keys(oneshot_fixture))} real={sorted(oneshot[0])}")


@pytest.mark.skipif(not REAL_TASKS.exists(), reason="无真实 .claude/scheduled_tasks.json(CI 干净环境)")
def test_real_sample_shape_parity():
    """真实文件存在时的形状对账(内容依赖本机 cron 状态, CI 无真实文件故 skip)。"""
    real = json.loads(REAL_TASKS.read_text(encoding="utf-8"))["tasks"]
    _assert_shape_parity(real)


def test_shape_parity_tolerates_runtime_keys_but_catches_rename():
    """CI 必跑: 形状对账必须容忍运行期易变键, 同时仍能抓住固定字段改名。

    这是 2026-10-22 审查 must-fix 的回归守卫(真实文件缺失时也能守住):
      ① 真实文件只剩巡检 job 且带 `lastFiredAt` -> 不得误红(旧断言此处必 AssertionError);
      ② `createdAt` 改名 `created_at` -> 必须仍红(剔键不得把对账变成恒真)。
    """
    patrol = _job("real-patrol", PATROL_CRON, _patrol_prompt("real-patrol"),
                  time.time(), recurring=True)
    patrol["lastFiredAt"] = int(time.time() * 1000)      # 运行期键(调度器触发后写)
    oneshot = _job("real-oneshot", "0 9 * * *", "每日日报, 无进度文件字样", time.time())
    oneshot["lastFiredAt"] = int(time.time() * 1000)
    _assert_shape_parity([patrol])                        # 只有巡检 job(带运行期键)
    _assert_shape_parity([oneshot, patrol])               # 首个是一次性 job
    _assert_shape_parity([patrol, oneshot])               # 首个是巡检 job
    _assert_shape_parity([])                              # 空清单只校验 fixture 契约
    # 固定 schema 字段改名不得被运行期键剔除逻辑放过
    renamed_required = dict(patrol)                       # createdAt 是必填校验项 -> 早退红
    renamed_required["created_at"] = renamed_required.pop("createdAt")
    with pytest.raises(AssertionError, match="createdAt"):
        _assert_shape_parity([renamed_required])
    renamed_optional = dict(patrol)                       # 非必填固定字段 -> 红在键集对账
    renamed_optional["createdByPidX"] = renamed_optional.pop("createdByPid")
    with pytest.raises(AssertionError, match="固定键集不一致"):
        _assert_shape_parity([renamed_optional])


@pytest.mark.parametrize("shift_secs", [0, 2 * 3600, 86400])
def test_real_jobs_no_false_zombie_when_pending(monkeypatch, tmp_path, shift_secs):
    """真实 job 跑判定: 只有「已过 ready_at」的 job 才允许出现在**真 FAIL 行**里。

    真实样本优先(保留真实 job 的校验价值); **真实文件缺失 / 为空 / 无巡检类 job 时,
    退回固定样本继续跑同一套完整断言**(不 skip 核心逻辑) —— 本机 cron 状态不再影响结论。

    时钟冻结在「样本最晚 ready_at 前 1 秒」= 不管哪天跑, 都必然至少一个 job 处于 pending、
    其余已过 ready_at -> FAIL detail 必然「fail 行 + pending 行」混排
    (2026-10-22 假红正是此形态), 断言与真实运行时刻/本机 cron 状态解耦。
    """
    real = (json.loads(REAL_TASKS.read_text(encoding="utf-8"))["tasks"]
            if REAL_TASKS.exists() else [])
    relevant = _patrol_relevant(real)
    source = "real"
    if relevant:
        for j, ready_at in relevant:
            assert ready_at is not None, f"真实 job {j['id']} 应能算出 ready_at"
        sample = real
    else:
        # 无巡检类 job(巡检已删净 / 只剩普通 job / 文件不存在) -> 固定样本兜底
        source = "fixed"
        sample = _fixed_patrol_jobs()
        relevant = _patrol_relevant(sample)
        assert len(relevant) >= 2, "固定样本应含 ≥2 个巡检类 job(createdAt 不同)"
    now = max(ra for _, ra in relevant) - 1 + shift_secs
    repo, pdir = _setup(monkeypatch, tmp_path, sample)
    pdir.mkdir(exist_ok=True)                 # 空进度目录 = 模拟"文件尚未产生"
    _freeze_now(monkeypatch, now)
    res = m.check_zombie_crons(repo)
    fails = _fails(res)
    pending = _pending_lines(res)
    # 判别力兜底(2026-10-22 审查建议): 不论 shift 多大/样本多少, 都必须真的产生一条
    # 结论性断言 —— 只要存在「可解析进度路径 + 已过 ready_at」的 job, 空进度目录就必须
    # 真 FAIL; 反之全部未到 ready_at 时不得 FAIL 且必须出现 pending 说明。
    decidable = [(j, ready_at) for j, ready_at in relevant
                 if ready_at is not None and (
                     m.PROGRESS_PATH_RE.search(j.get("prompt") or "")
                     or m.PATROL_NAME_RE.search(j.get("prompt") or ""))]
    assert decidable, "样本应至少有一个含可解析进度路径的巡检 job"
    overdue = [j["id"] for j, ready_at in decidable if ready_at <= now]
    if overdue:
        assert res.status == m.CheckResult.FAIL, (
            f"{source} 已过 ready_at 的 job {overdue} + 空进度目录 -> 必须真 FAIL: {res.msg}")
        for jid in overdue:
            assert jid in fails, f"{source} job {jid} 已过 ready_at, 应出现在真 FAIL 行"
    else:
        assert res.status != m.CheckResult.FAIL, (
            f"{source} 全部 job 均未到 ready_at -> 不得 FAIL: {res.msg}")
        assert pending, f"{source} 全部 job 未到 ready_at -> 至少应出现一条 pending 说明"
    for j, ready_at in relevant:
        if ready_at > now:
            assert j["id"] not in fails, (
                f"{source} job {j['id']} ready_at={ready_at} 在将来, 不应被误判僵尸")
            p = j.get("prompt") or ""
            if m.PROGRESS_PATH_RE.search(p) or m.PATROL_NAME_RE.search(p):
                assert j["id"] in pending, (
                    f"{source} job {j['id']} 应作为 pending 说明出现(未到应产生时刻)")
    if source == "fixed":
        # 固定样本判别力: 已过 ready_at + 无进度文件必须真 FAIL(不只 pending 侧生效)
        assert "fixed-patrol-old" in fails, (
            "已过 ready_at + 无进度文件 -> 必须真 FAIL(判别力不得下降)")


# ── ⑪ FAIL 时 detail 里 fail 行与 pending 行混排: pending 不得被当成"被 FAIL 提及" ──
# CI 必跑(不依赖真实文件): 这是 2026-10-22 时敏假红的直接回归守卫。
# 固定时钟锚 FROZEN_NOW 定义在文件头(与固定样本共用, 单一事实源)。


@pytest.mark.parametrize("shift_secs", [0, 2 * 3600, 86400])
def test_pending_lines_not_counted_as_fail_when_mixed(monkeypatch, tmp_path, shift_secs):
    now = FROZEN_NOW + shift_secs
    future_fire = datetime.fromtimestamp(now) + timedelta(days=2)
    jobs = [
        # ① 已过 ready_at + 无进度文件 = 真 FAIL(判别力路径, 必须保留)
        _job("mix-past", PATROL_CRON, _patrol_prompt("224-mix-past"), now - 2 * 86400, recurring=True),
        # ② ready_at 在将来 = 只能出现在 pending 说明里, 不得算 FAIL
        _job("mix-future", _dated_cron(future_fire), _patrol_prompt("224-mix-future"), now - 3600),
    ]
    repo, _ = _setup(monkeypatch, tmp_path, jobs)
    _freeze_now(monkeypatch, now)
    res = m.check_zombie_crons(repo)
    assert res.status == m.CheckResult.FAIL, f"已过 ready_at + 无文件必须真 FAIL: {res.msg}"
    fails = _fails(res)
    assert "mix-past" in fails, "ready_at 已过 + 文件不存在 -> 真 FAIL(判别力不得下降)"
    assert "mix-future" not in fails, "ready_at 在将来 -> 不得出现在真 FAIL 行"
    assert "mix-future" in _pending_lines(res), "该 job 应作为 pending 说明出现(事故形态: fail/pending 混排)"
    assert "mix-future" in _pending_text(res) and "不判僵尸" in _pending_text(res)