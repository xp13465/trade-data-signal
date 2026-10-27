# -*- coding: utf-8 -*-
"""告警降噪批次 2(★2 停摆跨日重发 + ★5 摘要合并/状态说明归一化)自验 —— 2026-10-28。

验收对照(任务书 /tmp/task-alert-batch2-20261028.md 验收第 1 条):
  E2-1 `failed_units_daily_judge` 四种 reason 纯函数(same-set-prev-day / daily-first /
       added / changed, 含「签名变」与「last_alert_date 空」; added 必须优先于日判定)
  E2-2 `check_failed_units --dry-run` 两轮: 跨日同集合两轮都不直发、reason 稳定、state 不改
  E2-3 `notify --escalation-only --dry-run` 升级档仍判 critical(硬点: 升级档不许被杀),
       且 dry-run 不推进滚动窗、不占窗、不外发
  E2-4 `--defer-digest` 真返回 `digested` 且 `_send_notify` 认 `digested`;
       2b 集成: same-set-prev-day ⇒ 只跑升级档 + 摘要吸收 + 写 state + rc=1;
       吸收失败(回滚态 ALERT_BUDGET_DISABLE=1)⇒ fail-open 退回直发
  E5-1 同任务集 / 不同时间戳 → 同一 digest
  E5-2 任务集 {A} → {A,B} → digest 变(漏跑个数也进签名)
  E5-3 同签名 active: 25h → 再发(remind_24h); 6h → 不发; 本轮有告警邮件门保留; 6h 复发冷却保留
  E5-4 buffer「前日 2 条 + 当日 0 条」: 00:00 不发; 次日 23:30 发 1 条且 subject 含
       「(含前日遗留 2 条)」; 发送失败不清理 buffer 契约不变

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):
  `_send_email` / `send_telegram` / `send_feishu` 在 fixture 内整体打桩为「只记录、返回 True」,
  外层再套 `ZeroOutboundTrap` 包裹最底层 urllib/smtplib/http.client 出口; 收尾断言
  `trap.hits == []`。所有落盘面(台账/buffer/state/dedup)全指向 tmp_path, 绝不碰生产 data/alerts/。

时钟冻结(L51): 被测代码内部取 `datetime.now()` 的地方, 本文件一律替换该模块的 `datetime`
  为固定 `now()` 的替身(notify / check_failed_units), 禁写死日期字面量当「今天」;
  E5-4 的「隔天」用同一替身平移 +24h 验证, 不依赖真实运行日。

跑法: python3 -m pytest -q scripts/tests/test_alert_denoise_batch2_20261028.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402
from _monitor_conclusion_309 import namespace as _conclusion_ns  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402
import check_failed_units as cfu  # noqa: E402
import notify  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#193/#240)
_MIN_ASSERTIONS = 45
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════════ 隔离 fixture(零外发 + 全 tmp) ══════════════════════════
@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE",
               "ALERT_BUDGET_TASK_FAMILY"):
        monkeypatch.delenv(_v, raising=False)
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", alerts / "latest.md")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", alerts / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", alerts / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", alerts / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "DEDUP_FILE", alerts / "notify_dedup.json")
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", alerts / "alert_digest.jsonl")
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", alerts / "alert_digest.flushlock")
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", alerts / "alert_digest_state.json")
    # notify.py:319 附近这两个锁常量同为 import 期派生 ⇒ 不 patch 会写回真实工作树(假绿)
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp_path not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: notify 落盘面泄漏到真实树 {_leak} ⇒ 会污染生产 data/alerts/"

    calls: list[str] = []

    def _fake(kind):
        def _f(*_a, **_k):
            calls.append(kind)
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _freeze(monkeypatch, dtv: datetime, mod=notify) -> None:
    """把 `mod.datetime` 换成固定 `now()` 的替身(必须是 datetime 子类: strptime 仍可用)。"""
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dtv
    monkeypatch.setattr(mod, "datetime", _DT)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def _digest_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ══════════════════ E2-1 纯函数四种 reason(★2a) ══════════════════
def test_e2_1_judge_reasons(_iso):
    yest, today = "2026-10-27", "2026-10-28"
    p_a = ["云上 failed unit: a.service"]
    sig_a = adr.failed_units_signature(p_a)
    items_a = adr.failed_units_identity(["a.service"])
    p_b = ["云上 failed unit: b.service"]
    sig_b = adr.failed_units_signature(p_b)
    items_b = adr.failed_units_identity(["b.service"])
    items_ab = adr.failed_units_identity(["a.service", "b.service"])
    sig_ab = adr.failed_units_signature(["云上 failed unit: a.service, b.service"])

    # ① same-set-prev-day: 跨日 + 本次签名 == 最近一次真发出的 signature
    st = {"prev_signature": sig_a, "signature": sig_a, "items": items_a,
          "last_alert_date": yest}
    _chk(adr.failed_units_daily_judge(st, sig_a, items_a, today)
         == (True, "same-set-prev-day"), "跨日同集合应为 same-set-prev-day")

    # ② daily-first: 跨日、无增无减, 但「上次真发出」的集合与本次不同
    #    (真实形态: 昨天发出 {a,b}; 今天早些时候缩小到 {a} 静默; 再次观测 {a} ⇒ 今天必须报)
    st_shift = {"prev_signature": sig_a, "signature": sig_ab, "items": items_a,
                "last_alert_date": yest}
    _chk(adr.failed_units_daily_judge(st_shift, sig_a, items_a, today)
         == (True, "daily-first"), "跨日且与上次真发出集合不同 ⇒ daily-first")

    # ②b last_alert_date 空(= 从未真发出) ⇒ daily-first, 不能误判 same-set-prev-day
    st_never = {"prev_signature": sig_a, "signature": sig_a, "items": items_a,
                "last_alert_date": ""}
    _chk(adr.failed_units_daily_judge(st_never, sig_a, items_a, today)
         == (True, "daily-first"), "从未发出过 ⇒ 首报必须仍发(daily-first)")

    # ③ added: 集合新增成员 → 立即报(且必须优先于跨日判定)
    _chk(adr.failed_units_daily_judge(st, sig_ab, items_ab, today)
         == (True, "added"), "新增 failed unit 必须立即报")
    # ③b 迁移期无成员快照时, 新增只体现为签名变 ⇒ changed(保守照报), 仍不得被吞
    st_mig = {"prev_signature": sig_a, "signature": sig_a, "last_alert_date": yest}
    _chk(adr.failed_units_daily_judge(st_mig, sig_ab, items_ab, today)
         == (True, "changed"), "无 items 快照且签名变 ⇒ changed(保守照报)")

    # ④ 同日同集合仍静默(回归保护)
    st_today = {"prev_signature": sig_a, "signature": sig_a, "items": items_a,
                "last_alert_date": today}
    _chk(adr.failed_units_daily_judge(st_today, sig_a, items_a, today)
         == (False, "same-set-same-day"), "同日同集合必须静默")
    # ⑤ 集合缩小仍静默(回归保护)
    st_ab = {"prev_signature": sig_ab, "signature": sig_ab, "items": items_ab,
             "last_alert_date": yest}
    _chk(adr.failed_units_daily_judge(st_ab, sig_a, items_a, today)
         == (False, "shrunk"), "集合缩小=恢复进展, 必须静默")
    # ⑥ 空集合短路
    _chk(adr.failed_units_daily_judge(st, "", [], today) == (False, "empty"))


# ══════════════════ 2b/2c 集成桩: 造 check_failed_units 的真实输入 ══════════════════
def _cfu_setup(tmp: Path, monkeypatch, *, units: list[str], state: dict | None,
               now: datetime):
    """造 cfu 的注入样本 + tmp repo + state; 返回 (repo, argv, sig, items)。"""
    repo = tmp / "repo"
    (repo / "data").mkdir(parents=True, exist_ok=True)
    allow = tmp / "allowlist.txt"
    allow.write_text("", encoding="utf-8")
    fu = tmp / "failed_units.txt"
    fu.write_text("".join(f"{u} loaded failed failed Trade X\n" for u in units),
                  encoding="utf-8")
    # watchman 全部 healthy(否则额外 problems 进签名, 干扰本用例的断言目标)
    show = {u: {"ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled"}
            for u, _ in cfu.WATCHMAN_UNITS}
    sh = tmp / "unit_show.json"
    sh.write_text(json.dumps(show, ensure_ascii=False), encoding="utf-8")
    state_path = repo / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME
    if state is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    argv = ["check_failed_units.py", "--repo", str(repo),
            "--failed-units-file", str(fu), "--unit-show-json", str(sh),
            "--allowlist-file", str(allow), "--stats-file", str(tmp / "no_stats.json")]
    sig = adr.failed_units_signature(["云上 failed unit: " + ", ".join(units)])
    items = adr.failed_units_identity(units)
    _freeze(monkeypatch, now, cfu)
    monkeypatch.setattr(cfu, "_check_d1_sync", lambda repo_, do_notify_: 0)
    return repo, argv, sig, items, state_path


def _state_for(sig: str, items: list[str], last_alert_date: str) -> dict:
    return {"signature": sig, "prev_signature": sig, "items": list(items),
            "last_alert_date": last_alert_date,
            "last_added_signature": "", "last_added_at": "",
            "updated_at": f"{last_alert_date} 09:00:00"}


def _send_stub(monkeypatch):
    """打桩 _send_notify: 记录 (escalation_only, subject); 普通发送=True, 升级档=False(未命中)。"""
    rec: list[dict] = []

    def _fake(repo, subject, body, dedup_key=None, escalation_only=False):
        rec.append({"escalation_only": escalation_only, "dedup_key": dedup_key,
                    "subject": subject})
        return (False, "status=noop(升级未命中)") if escalation_only else (True, "status=sent")

    monkeypatch.setattr(cfu, "_send_notify", _fake)
    return rec


# ══════════════════ E2-2 dry-run 两轮(★2b 干跑不落盘/不直发) ══════════════════
def test_e2_2_dry_run_two_rounds(_iso, monkeypatch, capsys):
    tmp, today = _iso["tmp"], datetime(2026, 10, 28, 10, 0, 0)
    yest = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    units = ["trade-x.service"]
    # 先算签名(与 _cfu_setup 同口径), 再落 state
    sig = adr.failed_units_signature(["云上 failed unit: trade-x.service"])
    items = adr.failed_units_identity(units)
    repo, argv, _sig, _items, state_path = _cfu_setup(
        tmp, monkeypatch, units=units, state=_state_for(sig, items, yest), now=today)
    before = state_path.read_bytes()

    def _boom(*_a, **_k):
        raise AssertionError("dry-run 不得调用发送/摘要吸收")
    monkeypatch.setattr(cfu, "_send_notify", _boom)
    monkeypatch.setattr(cfu, "_defer_digest", _boom)

    monkeypatch.setattr(sys, "argv", argv + ["--dry-run"])
    rc1 = cfu._main_impl()
    err1 = capsys.readouterr().err
    rc2 = cfu._main_impl()
    err2 = capsys.readouterr().err

    _chk(rc1 == 1 and rc2 == 1, f"dry-run 发现异常 rc 应为 1, 实得 {rc1}/{rc2}")
    for i, err in enumerate((err1, err2), 1):
        _chk("send=True" in err, f"第{i}轮 dry-run 应判 send=True")
        _chk("reason=same-set-prev-day" in err,
             f"第{i}轮 reason 应为 same-set-prev-day(集合没变, 两轮一致)")
        _chk("dry-run: 未真发通知" in err, f"第{i}轮必须走 dry-run 分支")
    _chk(state_path.read_bytes() == before, "dry-run 不得改 state(否则会吞掉下轮真实判定)")


# ══════════════════ E2-3 升级档不被 --escalation-only 杀掉 ══════════════════
def _seed_escalate_state(tmp: Path, days: list[str]) -> Path:
    p = tmp / "data" / "failed_units_patrol_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "seen_dates": list(days),
        "last_fail_date": days[-1],
        "consecutive_days": len(days),
        "first_fail_date": days[0],
        "last_grade_time": "",
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_e2_3_escalation_only_dry_run_hits_critical(_iso, monkeypatch, capsys):
    tmp = _iso["tmp"]
    now = datetime(2026, 10, 28, 10, 0, 0)
    _freeze(monkeypatch, now, notify)
    st = _seed_escalate_state(tmp, ["2026-10-26", "2026-10-27", "2026-10-28"])
    before = st.read_bytes()
    rc = notify.main(["[告警] 云上 unit 巡检发现异常(1 项)",
                      "body", "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                      "--escalation-only", "--dry-run"])
    err = capsys.readouterr().err
    _chk(rc == 0, f"dry-run 升级档 rc 应为 0, 实得 {rc}")
    _chk("[notify][196]" in err, "升级档判定必须跑到(stderr 缺 [notify][196])")
    _chk("分级=critical" in err, "E2-3 硬点: 升级档不许被杀, 必须判 critical")
    _chk("dry-run: 升级档将发 critical" in err, "dry-run 只打印、不真发")
    _chk(st.read_bytes() == before, "dry-run 不得推进滚动窗(persist=False)")
    _chk(_iso["calls"] == [], f"零外发: 不得触达任何渠道 {_iso['calls']}")
    _chk(not (tmp / "data" / "alerts" / "notify_dedup.json").exists()
         or "failed_units_patrol_escalated" not in
         (tmp / "data" / "alerts" / "notify_dedup.json").read_text(encoding="utf-8"),
         "dry-run 不得占升级档去重窗")


def test_e2_3b_escalation_only_no_hit_noop_not_direct(_iso, monkeypatch, capsys):
    """非升级命中: --escalation-only 必须 return noop(落在通用 dedup 之前), 绝不直发。"""
    tmp = _iso["tmp"]
    _freeze(monkeypatch, datetime(2026, 10, 28, 10, 0, 0), notify)
    _seed_escalate_state(tmp, ["2026-10-28"])  # 只出现 1 天 < 3 天
    rf = tmp / "result.json"
    rc = notify.main(["[告警] x", "body", "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                      "--escalation-only", "--result-file", str(rf)])
    err = capsys.readouterr().err
    _chk(rc == 0)
    _chk("[notify][escalation-only] 仅跑升级判定, 未直发" in err)
    _chk(_iso["calls"] == [], f"零外发: escalation-only 不得直发 {_iso['calls']}")
    payload = json.loads(rf.read_text(encoding="utf-8"))
    _chk(payload.get("status") == "noop", f"非升级命中 status 应为 noop, 实得 {payload}")


# ══════════════════ E2-4 --defer-digest 返回 digested + _send_notify 认它 ══════════════════
def test_e2_4_defer_digest_returns_digested(_iso):
    """真子进程跑 notify.py --defer-digest: status 必须 digested, 且条目真进 tmp buffer。

    子进程继承 REPO=tmp_path(fixture setenv)⇒ 落盘面全在 tmp, 不外发(defer 模式本身不发送)。
    """
    tmp = _iso["tmp"]
    ok, detail = cfu._defer_digest(tmp, "[告警] 跨日同集合(测试)", "body")
    _chk(ok is True, f"_defer_digest 应判已吸收, 实得 {detail}")
    _chk("status=digested" in detail, f"status 必须为 digested(旧 noop 陷阱), 实得 {detail}")
    rows = _digest_rows(tmp / "data" / "alerts" / "alert_digest.jsonl")
    _chk(len(rows) == 1, f"摘要 buffer 应有 1 条, 实得 {len(rows)}")
    _chk(rows[0].get("category") == "unit", f"类别应为 unit, 实得 {rows[0].get('category')}")


def test_e2_4_send_notify_accepts_digested(_iso, monkeypatch):
    """_send_notify 只认 {sent,digested}; 2d 改后 defer 复用它不会被判「未送达」。

    用 subprocess.run 打桩写结果文件(不真跑 notify ⇒ 零外发风险)。
    """
    seen = {}

    class _P:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        rp = Path(cmd[cmd.index("--result-file") + 1])
        rp.write_text(json.dumps({"status": "digested", "channels": {}}), encoding="utf-8")
        return _P()

    monkeypatch.setattr(cfu.subprocess, "run", _fake_run)
    sent, detail = cfu._send_notify(_iso["tmp"], "[告警] x", "body", escalation_only=True)
    _chk(sent is True, f"status=digested 必须认作已送达, 实得 {detail}")
    _chk("status=digested" in detail)
    _chk("--escalation-only" in seen["cmd"], "escalation_only=True 必须拼出 --escalation-only")
    # 对照: 未传 escalation_only 时不得拼该 flag(防误伤首报通道)
    cfu._send_notify(_iso["tmp"], "[告警] x", "body")
    _chk("--escalation-only" not in seen["cmd"], "普通首报不得带 --escalation-only")


def test_e2_4b_same_set_prev_day_escalate_plus_digest(_iso, monkeypatch):
    """★2b 集成: same-set-prev-day ⇒ ①只跑升级档 ②并入摘要 ③写 state ④rc=1。"""
    tmp, now = _iso["tmp"], datetime(2026, 10, 28, 10, 0, 0)
    yest = "2026-10-27"
    units = ["trade-x.service"]
    sig = adr.failed_units_signature(["云上 failed unit: trade-x.service"])
    items = adr.failed_units_identity(units)
    repo, argv, _sig, _items, state_path = _cfu_setup(
        tmp, monkeypatch, units=units, state=_state_for(sig, items, yest), now=now)
    sends = _send_stub(monkeypatch)
    defer_rec = []
    monkeypatch.setattr(cfu, "_defer_digest",
                        lambda repo_, s, b: (defer_rec.append(s), (True, "status=digested"))[1])

    monkeypatch.setattr(sys, "argv", argv + ["--notify"])
    rc = cfu._main_impl()

    _chk(rc == 1, f"按设计处置完毕 rc=1, 实得 {rc}")
    _chk(len(sends) == 1, f"应只调 1 次 _send_notify(升级档), 实得 {len(sends)}")
    _chk(sends[0]["escalation_only"] is True, "same-set-prev-day 必须只跑升级档")
    _chk(len(defer_rec) == 1, f"必须并入摘要 1 次, 实得 {len(defer_rec)}")
    st = json.loads(state_path.read_text(encoding="utf-8"))
    _chk(st.get("signature") == sig, "state.signature 应刷新为本轮集合(下轮同日静默)")
    _chk(st.get("last_alert_date") == now.strftime("%Y-%m-%d"),
         "state.last_alert_date 应为今天(一天只做一次)")


def test_e2_4c_digest_absorb_fail_open_to_direct(_iso, monkeypatch):
    """摘要吸收未生效(回滚态)⇒ fail-open 退回直发, 绝不静默丢条目。"""
    tmp, now = _iso["tmp"], datetime(2026, 10, 28, 10, 0, 0)
    units = ["trade-x.service"]
    sig = adr.failed_units_signature(["云上 failed unit: trade-x.service"])
    items = adr.failed_units_identity(units)
    repo, argv, _sig, _items, state_path = _cfu_setup(
        tmp, monkeypatch, units=units, state=_state_for(sig, items, "2026-10-27"), now=now)
    sends = _send_stub(monkeypatch)
    monkeypatch.setattr(cfu, "_defer_digest",
                        lambda repo_, s, b: (False, "status=noop(ALERT_BUDGET_DISABLE=1)"))

    monkeypatch.setattr(sys, "argv", argv + ["--notify"])
    rc = cfu._main_impl()

    _chk(rc == 1, f"fail-open 直发成功 ⇒ rc=1, 实得 {rc}")
    _chk(len(sends) == 2, f"应先升级档再退回直发 = 2 次, 实得 {len(sends)}")
    _chk(sends[0]["escalation_only"] is True)
    _chk(sends[1]["escalation_only"] is False, "fail-open 必须走普通直发(escalation_only=False)")
    st = json.loads(state_path.read_text(encoding="utf-8"))
    _chk(st.get("signature") == sig and st.get("last_alert_date") == "2026-10-28")


def test_e2_4d_added_still_direct(_iso, monkeypatch):
    """对照(回归): added 仍立即直发, 不得被 ★2 的新分支吞。"""
    tmp, now = _iso["tmp"], datetime(2026, 10, 28, 10, 0, 0)
    units = ["trade-a.service", "trade-b.service"]
    sig = adr.failed_units_signature(["云上 failed unit: trade-a.service"])
    items = adr.failed_units_identity(["trade-a.service"])  # 上轮只有 a
    repo, argv, _sig, _items, state_path = _cfu_setup(
        tmp, monkeypatch, units=units, state=_state_for(sig, items, "2026-10-27"), now=now)
    sends = _send_stub(monkeypatch)
    defer_rec = []
    monkeypatch.setattr(cfu, "_defer_digest",
                        lambda repo_, s, b: (defer_rec.append(s), (True, "status=digested"))[1])
    monkeypatch.setattr(sys, "argv", argv + ["--notify"])
    rc = cfu._main_impl()
    _chk(rc == 1)
    _chk(len(sends) == 1 and sends[0]["escalation_only"] is False,
         "added 必须直发(不得走升级档分流)")
    _chk(defer_rec == [], "added 不得被并入摘要")


# ══════════════════ E5-1/E5-2 结论签名归一化(★5b) ══════════════════
def _concl_funcs():
    ns = _conclusion_ns()
    return ns["_conclusion_signature"], ns["_conclusion_digest"], ns


def test_e5_1_same_task_set_different_timestamps_same_digest():
    sig, dig, _ns = _concl_funcs()
    a = ("非 OK: 1 个任务失败: foo.service(Result=failed, exit=1, 09:26:00→09:41:00); "
         "漏跑 1 个任务")
    b = ("非 OK: 1 个任务失败: foo.service(Result=failed, exit=1, 21:05:00→21:20:00); "
         "漏跑 1 个任务")
    c = ("非 OK: 1 个任务失败: foo.service(Result=failed, exit=1, 03:00:00→03:15:00); "
         "漏跑 1 个任务")
    _chk(sig(a) == sig(b) == sig(c), f"时间戳不同不应改签名: {sig(a)!r} / {sig(b)!r} / {sig(c)!r}")
    _chk(dig(a) == dig(b) == dig(c), "同任务集 → 同一 digest(否则每轮都发状态说明)")
    _chk("09:26" not in sig(a) and "09:41" not in sig(a), "签名不得含起止时间")
    _chk("foo.service|Result=failed|exit=1" in sig(a), "签名必须保留 任务名+Result+exit 三元组")


def test_e5_2_task_set_change_changes_digest():
    sig, dig, _ns = _concl_funcs()
    a = "非 OK: 1 个任务失败: foo.service(Result=failed, exit=1, 09:26:00→09:41:00)"
    ab = ("非 OK: 2 个任务失败: foo.service(Result=failed, exit=1, 09:26:00→09:41:00); "
          "bar.socket(Result=failed, exit=2, 09:26:00→09:41:00)")
    _chk(dig(a) != dig(ab), "{A} → {A,B} digest 必须变")
    _chk("bar.socket|Result=failed|exit=2" in sig(ab))
    # 漏跑个数也是判别维度(防「漏跑 1 → 漏跑 3」被同一签名吞)
    m1 = "非 OK: 漏跑 1 个任务: x.sh"
    m3 = "非 OK: 漏跑 3 个任务: x.sh, y.sh, z.sh"
    _chk(dig(m1) != dig(m3), "漏跑个数变化 digest 必须变")
    # 另一形态: live exit + 源 / 无 Result 的 exit 形态也要进签名
    live = "非 OK: bar(live exit=1, 源=systemd)"
    _chk("bar|live|exit=1|源=systemd" in sig(live))
    # fallback: 完全匹配不上三元组 ⇒ 原文(当前行为), 不静默丢
    weird = "非 OK: 某种全新文案 without pairs 2026-10-28"
    _chk(sig(weird) == weird.strip(), "正则不匹配必须回退原文")


# ══════════════════ E5-3 24h 再提醒(★5c) ══════════════════
def test_e5_3_remind_after_24h_not_6h():
    _sig, dig, ns = _concl_funcs()
    decision = ns["_conclusion_status_decision"]
    prefix = ns["CONCLUSION_STATUS_KEY_PREFIX"]
    concl = "非 OK: 1 个任务失败: foo.service(Result=failed, exit=1, 09:26:00→09:41:00)"
    key = prefix + dig(concl)
    now = datetime(2026, 10, 28, 10, 0, 0)

    # 6h 前发过 ⇒ 同一内容不再发
    st6 = {key: {"status": "active", "last_alerted": "2026-10-28 04:00:00"}}
    d6 = decision(concl, 0, st6, now)
    _chk(d6["send"] is False and d6["reason"] == "same_content_sent",
         f"6h 内应静默, 实得 {d6}")

    # 25h 前发过 ⇒ 再提醒
    st25 = {key: {"status": "active", "last_alerted": "2026-10-27 08:30:00"}}
    d25 = decision(concl, 0, st25, now)
    _chk(d25["send"] is True and d25["reason"] == "remind_24h",
         f"25h 应再提醒, 实得 {d25}")
    _chk(d25["key"] == key, "再提醒必须复用同一签名 key")

    # 保留门: 本轮已有告警邮件 ⇒ 不发(即使 25h)
    dmail = decision(concl, 1, st25, now)
    _chk(dmail["send"] is False and dmail["reason"] == "has_alert_mail",
         f"有告警邮件时不得补发状态说明, 实得 {dmail}")

    # 保留门: 6h 复发冷却(恢复后 2h 内再异常 ⇒ 不发)
    st_rec = {key: {"status": "recovered", "last_recovered": "2026-10-28 08:00:00"}}
    drec = decision(concl, 0, st_rec, now)
    _chk(drec["send"] is False and drec["reason"] == "recurrence_cooldown",
         f"恢复后 6h 内复发应静默, 实得 {drec}")

    # 无记录 ⇒ 正常发
    dn = decision(concl, 0, {}, now)
    _chk(dn["send"] is True and dn["reason"] == "send")


# ══════════════════ E5-4 摘要合并: 00:00 不发, 次日 23:30 并前日遗留(★5a) ══════════════════
def _seed_digest_buffer(alerts_dir: Path, day: str, n: int = 2) -> None:
    rows = [{"ts": f"{day} 23:1{i}:00", "rid": f"r{i}", "day": day, "key": f"k{i}",
             "category": "unit", "subject": f"sub{i}", "body": "b",
             "from_prefix": "[告警]", "source": "check_failed_units.py",
             "reason": "over_budget", "hits": 1} for i in range(n)]
    _write_jsonl(alerts_dir / "alert_digest.jsonl", rows)


def test_e5_4_digest_no_0000_and_stale_merged_at_2330(_iso, monkeypatch):
    tmp, alerts = _iso["tmp"], _iso["alerts"]
    _seed_digest_buffer(alerts, "2026-10-27", n=2)
    sent: list[str] = []
    orig_send = notify.send

    def _wrap(subject, body, **kw):
        sent.append(subject)
        return orig_send(subject, body, **kw)

    monkeypatch.setattr(notify, "send", _wrap)

    # ① 00:05(跨日: 前日 2 条 stale, 当日 0 条)⇒ 不发, buffer 一条不删
    _freeze(monkeypatch, datetime(2026, 10, 28, 0, 5, 0))
    r0 = notify.flush_digest()
    _chk(r0["sent"] is False, f"00:00 不得再单发摘要, 实得 {r0}")
    _chk(len(sent) == 0, f"00:00 不得真发, 实得 {sent}")
    _chk(len(_digest_rows(alerts / "alert_digest.jsonl")) == 2, "不发时 buffer 必须原样保留")

    # ② 次日 23:30 ⇒ 发 1 条, 前日遗留并入(subject 自带可见性)
    _freeze(monkeypatch, datetime(2026, 10, 29, 23, 30, 0))
    r1 = notify.flush_digest()
    _chk(r1["sent"] is True, f"23:30 应发摘要, 实得 {r1}")
    _chk(len(sent) == 1, f"只发 1 条, 实得 {len(sent)}")
    _chk("(含前日遗留 2 条)" in sent[0], f"subject 必须标注前日遗留, 实得 {sent[0]!r}")
    _chk(r1["n"] == 2, f"被合并条数应为 2, 实得 {r1}")
    _chk(len(_digest_rows(alerts / "alert_digest.jsonl")) == 0, "发送成功后 buffer 应清空")
    st = json.loads((alerts / "alert_digest_state.json").read_text(encoding="utf-8"))
    _chk(st.get("last_sent_day") == "2026-10-27", "水位线 = 已发条目所属最大 day")


def test_e5_4b_send_fail_keeps_buffer(_iso, monkeypatch):
    """★5a 契约: 发送失败**不清理** buffer(条目绝不丢)。"""
    alerts = _iso["alerts"]
    _seed_digest_buffer(alerts, "2026-10-27", n=2)
    monkeypatch.setattr(notify, "send", lambda *a, **k: {})
    _freeze(monkeypatch, datetime(2026, 10, 28, 23, 30, 0))
    r = notify.flush_digest()
    _chk(r["sent"] is False, f"全渠道失败 ⇒ sent=False, 实得 {r}")
    _chk(len(_digest_rows(alerts / "alert_digest.jsonl")) == 2, "发送失败必须保留全部条目")
    _chk(not (alerts / "alert_digest_state.json").exists(), "发送失败不得写水位线(下轮重试)")


# ══════════════════ 断言计数下限(定义顺序最后;防假绿) ══════════════════
def test_zz_assertion_floor():
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS} ⇒ 有用例被跳过/收集异常"