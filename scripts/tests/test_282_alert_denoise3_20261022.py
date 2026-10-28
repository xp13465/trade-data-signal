# -*- coding: utf-8 -*-
"""#282 告警降噪三件(A 停摆直发 / B active 升级阶梯 / C 抑制审计台账)自验。

依据(只读评估报告 /tmp/research-alert-denoise-eval.md §4.1/§4.3/§5/§7.3):
  A: scripts/alert_denoise_rules.py 旧 DOMAIN_AGGREGATE_EXEMPT_KEYS 只豁免
     deploy_consecutive_fail; domain_of 把「计划任务异常/锁跳过/deploy/R2/双站一致性」
     都并成 r2_deploy ⇒ 10-20 deploy 连续失败 39 次、15 条 R2/deploy 失败被并进 23:30
     摘要; staticdata 备份停摆 36h 只报一条泛化异常; D1 同步连续失败 39 次零告警。
  B: scripts/schedule_monitor.sh 旧实现无条件静默 status=active, 与 :371 注释
     「真卡死(持续 active >6h)仍响」矛盾; nextday_gap_check|ConnectionError 自
     10-13 active 9 天、1,125 条 suppress 零再提醒。
  C: 旧台账只记「已外发」, 答不了「这条故障为什么没通知我」; alert_domains.json
     的 n_absorbed 是累计值, 日志却写「本日该域已并入 N 条」。

零外发铁律(§18 L48): 渠道函数整体打桩 + 外层 ZeroOutboundTrap 包住
  urllib/smtplib; 收尾断言 trap.hits == []。所有落盘面全指向 tmp_path。
  另有 test_zero_outbound_trap_sandbox_works 先证明「陷阱确实会响」, 防打桩假绿。

跑法: python3 -m pytest -q scripts/tests/test_282_alert_denoise3_20261022.py
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
MONITOR = SCRIPTS / "schedule_monitor.sh"
SUPP_LEDGER = "suppression_ledger.jsonl"

_MIN_ASSERTIONS = 80
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


@pytest.fixture(scope="module", autouse=True)
def _count_guard():
    yield
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < {_MIN_ASSERTIONS}(防假绿)"


# ══════════════════════════ 隔离 fixture(零外发 + 全 tmp) ══════════════════════════
@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DOMAIN_DISABLE",
               "ALERT_DIGEST_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
               "ALERT_LEDGER_DISABLE", "NOTIFY_RESULT_FILE"):
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
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp_path not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: {_leak}"

    calls: list[dict] = []

    def _fake(kind):
        def _f(subject, body, *_a, **_k):
            calls.append({"kind": kind, "subject": subject, "body": body,
                          "args": _a, "kwargs": _k})
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _now_s(dt=None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _seed_ledger(alerts: Path, rows: list[dict]) -> None:
    p = alerts / "alert_ledger.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _seed_domain(alerts: Path, now=None) -> None:
    _write_json(alerts / adr.ALERT_DOMAIN_STATE_FILENAME,
                {"r2_deploy": {"last_ts": _now_s(now), "last_day": _now_s(now)[:10]}})


def _seed_dedup(alerts: Path, key: str, now=None) -> None:
    _write_json(alerts / "notify_dedup.json", {key: {"last_alerted": _now_s(now)}})


def _supp_records(repo: Path) -> list[dict]:
    p = repo / "data" / "alerts" / SUPP_LEDGER
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ═════════════ 真实生产行文/真实函数体取样(§18 L49 禁构造样本) ═════════════
def _monitor_py_src() -> str:
    """schedule_monitor.sh 内嵌 python 源码段(测的就是线上那份代码)。"""
    text = MONITOR.read_text(encoding="utf-8")
    _mark = text.index("<<'PYEOF'")
    start = text.index("\n", _mark) + 1
    end = text.index("\nPYEOF", start)
    return text[start:end]


def _production_line(needle: str, ns: dict) -> str:
    """从 monitor 源码里取**真实告警行 f-string**, 用给定变量值原样渲染。

    禁在测试里手抄近似行: 生产行文一改(如 4h 阈值/后缀), 本函数取到的就是改后的真实行,
    断言随之失效/生效 —— 防「构造一个看起来合理的样本」养绿(§18 L49)。
    """
    tree = ast.parse(_monitor_py_src())
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            consts = "".join(v.value for v in node.values
                             if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if needle in consts:
                return eval(compile(ast.Expression(node), "<prod-line>", "eval"),
                            {"__builtins__": {}, "int": int, "str": str}, ns)
    raise AssertionError(f"生产源码中找不到含 {needle!r} 的告警行模板(行文已漂移, 请更新用例)")


def _real_extra_line(task: str, hours: int) -> str:
    return _production_line("停摆(超", {"_et": task,
                                       "_eloop": timedelta(hours=hours),
                                       "_elr": "2026-10-22 06:00"})


def _real_staticdata_line() -> str:
    return _production_line("异步备份停摆", {
        "_hb_result": "ok", "_hb_age_h": 40,
        "STATICDATA_HB_STALE": timedelta(hours=36),
        "_hb_ts": "2026-10-20 12:00:00"})


def _load_stall_direct_block() -> str:
    """抽取 monitor 里「停摆行独立直发」那段真实代码(模块级语句, 非函数)。"""
    py_src = _monitor_py_src()
    start = py_src.index("_stall_batch = []")
    end = py_src.index("alerts, _absorbed = adr.alert_budget_process(")
    return py_src[start:end]


class _TmpDirUnavailable:
    """MF5 打桩: 模拟磁盘满(ENOSPC) —— mkdtemp 直接抛 OSError。"""

    @staticmethod
    def mkdtemp(prefix=""):
        raise OSError(28, "No space left on device")


def _run_stall_direct(lines: list[str], state: dict, state_pre: dict,
                      status: dict, mkdtemp_raises: bool = False) -> dict:
    """执行真实停摆直发块; subprocess.run 打桩为「按 status 写 --result-file」。

    返回 {alerts, alert_state, stderr, cmds}。status={"v": "sent"/"suppressed"/"failed"/""}
    —— "" 表示不写结果文件(模拟旧版 notify/写失败)。
    mkdtemp_raises=True: tempfile.mkdtemp 抛 OSError(ENOSPC), 验 MF5 fail-open。
    """
    import contextlib
    import io
    import tempfile as _tempfile

    cmds: list[list[str]] = []

    def _run(cmd, **kw):
        cmds.append([str(c) for c in cmd])
        rf = None
        if "--result-file" in cmd:
            rf = Path(cmd[cmd.index("--result-file") + 1])
        if rf is not None and status.get("v"):
            rf.parent.mkdir(parents=True, exist_ok=True)
            rf.write_text(json.dumps({"status": status["v"]}, ensure_ascii=False),
                          encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    from notify_sent import notify_sent as _ns
    ns = {
        "adr": adr, "sys": sys, "json": json, "shutil": __import__("shutil"),
        "tempfile": (_TmpDirUnavailable if mkdtemp_raises else _tempfile),
        "Path": Path, "REPO": ROOT,
        "MONITOR_LOG": ROOT / "data" / "logs" / "schedule_monitor_launchd.log",
        "subprocess": types.SimpleNamespace(run=_run, SubprocessError=Exception),
        "notify_sent": _ns, "alerts": list(lines), "alert_state": state,
        "_STATE_PRE": state_pre,
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        exec(compile(_load_stall_direct_block(), "<monitor:stall-direct>", "exec"), ns)
    return {"alerts": ns["alerts"], "alert_state": ns["alert_state"],
            "stderr": buf.getvalue(), "cmds": cmds}


class _AdrShim:
    """adr 的薄代理: 只需覆写 alert_budget_process(避免测试触碰真实台账/预算)。"""

    def __getattr__(self, name):
        return getattr(adr, name)

    @staticmethod
    def alert_budget_process(state, alerts, now, repo):
        return (list(alerts), [])


def _run_stall_direct_with_save(lines: list[str], state: dict, state_pre: dict,
                                mkdtemp_raises: bool = False) -> dict:
    """MF5: 执行「真实直发块 + 紧随的 save_alert_state」, 验证异常时后续落盘仍执行。

    与 _run_stall_direct 的区别: 抽取范围延伸到 `save_alert_state(alert_state)`,
    用桩记录落盘调用 —— 断言「磁盘满时 save 仍被调用 + 告警仍回批」。
    """
    import contextlib
    import io
    import tempfile as _tempfile

    py_src = _monitor_py_src()
    start = py_src.index("_stall_batch = []")
    _tail = "save_alert_state(alert_state)"
    end = py_src.index(_tail, start) + len(_tail)
    block = py_src[start:end]

    cmds: list[list[str]] = []
    saved: list[dict] = []

    def _run(cmd, **kw):
        cmds.append([str(c) for c in cmd])
        rf = Path(cmd[cmd.index("--result-file") + 1])
        rf.parent.mkdir(parents=True, exist_ok=True)
        rf.write_text(json.dumps({"status": "sent"}, ensure_ascii=False), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def _save(st):
        saved.append({k: dict(v) if isinstance(v, dict) else v for k, v in st.items()})

    from notify_sent import notify_sent as _ns
    ns = {
        "adr": _AdrShim(), "sys": sys, "json": json, "shutil": __import__("shutil"),
        "tempfile": (_TmpDirUnavailable if mkdtemp_raises else _tempfile),
        "Path": Path, "REPO": ROOT,
        "MONITOR_LOG": ROOT / "data" / "logs" / "schedule_monitor_launchd.log",
        "subprocess": types.SimpleNamespace(run=_run, SubprocessError=Exception),
        "notify_sent": _ns, "alerts": list(lines), "alert_state": state,
        "NOW": datetime.now(), "_STATE_PRE": state_pre, "save_alert_state": _save,
        # #309 F2(2026-10-26): 直发块真发出时累加告警邮件数(本用例不关心计数, 只需名字存在)
        "_ALERT_MAIL_COUNTER": {"sent": 0},
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        exec(compile(block, "<monitor:stall-direct+save>", "exec"), ns)
    return {"alerts": ns["alerts"], "alert_state": ns["alert_state"],
            "stderr": buf.getvalue(), "cmds": cmds, "saved": saved}


def _load_active_escalate_inprocess(tmp_path: Path):
    """取线上 `_active_escalate` 真函数体, subprocess.run 打桩为**进程内真跑 notify.main**。

    这样断言的是「升级提醒经真实 notify 路由后的结局」(键/去重窗/正文), 不是在测一份模拟。
    """
    import contextlib
    import io

    text = MONITOR.read_text(encoding="utf-8")
    _mark = text.index("<<'PYEOF'")
    start = text.index("\n", _mark) + 1
    end = text.index("\nPYEOF", start)
    py_src = text[start:end]
    tree = ast.parse(py_src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_active_escalate")
    code = ast.get_source_segment(py_src, node)
    events: list[list[str]] = []

    def _run(cmd, **kw):
        events.append([str(c) for c in cmd])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = notify.main([str(c) for c in cmd[2:]])  # cmd[0]=python, cmd[1]=notify.py
        return types.SimpleNamespace(returncode=rc, stdout="", stderr=buf.getvalue())

    from notify_sent import notify_sent as _ns
    ns = {
        "adr": adr, "NOW": datetime.now(), "sys": sys,
        "hashlib": __import__("hashlib"), "REPO": tmp_path,
        "MONITOR_LOG": tmp_path / "monitor.log",
        "subprocess": types.SimpleNamespace(run=_run, SubprocessError=Exception),
        "notify_sent": _ns,
        # 批次3-D: 真函数体用 tempfile/json/os/Path 读 --result-file
        "tempfile": tempfile, "json": json, "os": os, "Path": Path,
        # #309 F2(2026-10-26): 升级真发出时累加告警邮件数(本用例不关心计数, 只需名字存在)
        "_ALERT_MAIL_COUNTER": {"sent": 0},
    }
    exec(compile(code, "<monitor:_active_escalate>", "exec"), ns)
    return ns["_active_escalate"], events


def _load_extra_stale_loop() -> str:
    """取 monitor 里 EXTRA 任务停摆检测循环的**真实源码段**(模块级 for, 非函数)。"""
    src = _monitor_py_src()
    tree = ast.parse(src)
    # 循环嵌在模块级 with/try 块内, 不能用 tree.body(只扫顶层)
    for node in ast.walk(tree):
        seg = ast.get_source_segment(src, node)
        if (isinstance(node, ast.For) and seg
                and "EXTRA_MARKER_STALE_LOOPS[_et]" in seg):
            return seg
    raise AssertionError("monitor 源码中找不到 EXTRA 停摆循环(行文/结构已漂移)")


def _run_extra_stale_loop(state: dict, stats: list[dict], now: datetime,
                          loops: dict) -> tuple:
    """跑真实 EXTRA 停摆循环; _active_escalate 打桩记录调用(零外发)。"""
    escalates: list[tuple] = []
    ns = {
        "stats": stats,
        "EXTRA_MARKER_STALE_LOOPS": loops,
        "NOW": now,
        "datetime": datetime,
        "alerts": [],
        "alert_state": state,
        "seen_keys_this_run": set(),
        "_active_escalate": lambda entry, key, label: escalates.append((key, label)),
    }
    exec(compile(_load_extra_stale_loop(), "<monitor:extra-stale>", "exec"), ns)
    return ns, escalates


# ══════════════════════════ 0. 先证明沙箱判定生效 ══════════════════════════
def test_zero_outbound_trap_sandbox_works():
    import urllib.request
    with ZeroOutboundTrap() as t:
        try:
            urllib.request.urlopen("https://example.invalid/")
            _chk(False, "陷阱未拦截真实外发")
        except AssertionError as e:
            _chk("零外发被破坏" in str(e))
        except Exception as e:  # noqa: BLE001
            _chk(False, f"陷阱行为异常: {type(e).__name__}: {e}")
    _chk(len(t.hits) == 1, f"陷阱命中数应为 1, 实际 {t.hits}")


# ══════════════════════════ A. 停摆级独立通道 ══════════════════════════
def test_a_registry_covers_five_classes_and_is_disjoint():
    five = {
        "deploy 连续失败": {"deploy_consecutive_fail", "deploy_r2_upload_fail",
                            "deploy_purge_low_freq_fail"},
        "staticdata 备份失败/停摆": {"staticdata_backup_fail",
                                    "staticdata_backup_trigger_fail",
                                    "staticdata_backup_stale"},
        "R2 上传失败/超时": {"r2_upload_trigger_fail"},
        "D1 同步连续失败": {"d1_sync_fail"},
        "unit 连续失败": {"failed_units_patrol", "cloud_unit_patrol_drift"},
    }
    for label, keys in five.items():
        _chk(keys & adr.STALL_KEYS == keys, f"{label} 未在 STALL_KEYS 登记: {keys - adr.STALL_KEYS}")
    _chk(not (adr.STALL_KEYS & adr.NON_STALL_KEYS), "两张登记表不得重叠")
    _chk(adr.is_stall_key("deploy_consecutive_fail"), "deploy 连续失败必须仍为停摆级(不回退)")
    _chk(adr.is_stall_key("stall|consecutive_fail"), "monitor 合成键应识别为停摆")
    _chk(not adr.is_stall_key("r2_consistency_fail"), "三站一致性语义未收口, 不得误升停摆")
    _chk(not adr.is_stall_key("deploy_check_version_fail"), "单次闸门失败不得误升停摆")


def test_a_stall_line_markers_real_lines(iso):
    """MF1: 直接喂 schedule_monitor.sh:1397/:1743 的**真实行文**(源码 f-string 原样渲染)。

    修复前泛化 marker「停摆」把 EXTRA 行也判成 staticdata 停摆 ⇒ 两者共用去重键互相抑制、
    正文张冠李戴; 本用例同时守住「EXTRA→extra 键 / staticdata→staticdata 键 / 互不抑制」。
    """
    extra = _real_extra_line("fetch_news", 4)
    brief = _real_extra_line("gen_daily_brief", 26)
    sd = _real_staticdata_line()

    for line, task in ((extra, "fetch_news"), (brief, "gen_daily_brief")):
        key = adr.stall_line_key(line)
        _chk(key == f"stall|extra_stale|{task}", f"EXTRA 真实行 → {key}, 期望独立键族")
        _chk(key != "staticdata_backup_stale",
             f"EXTRA 停摆不得被判成 staticdata 停摆(修复前正是此误判): {key}")
        _chk(adr.is_stall_line(line))
        _chk(adr.stall_state_key(line) == f"{task}|extra_stale",
             f"EXTRA 回滚状态键应对齐 monitor 写法: {adr.stall_state_key(line)}")

    # R2 建议(2026-10-22): 新任务名格式/行文变体不得静默降级进普通批次。
    # 原正则 `[A-Za-z0-9_.\-]+` + 精确 `停摆(超Nh 未运行)` 会把下列行漏判成普通告警。
    variants = [
        ("fetch_news_v2.beta-1", "超4h"),
        ("采集-新闻@v2", "超 4.5h"),
        ("gen_daily_brief:night", "超26h"),
        ("intraday_snapshot", "超2.5h"),
    ]
    for task, threshold in variants:
        line = f"SEVERE: {task} 停摆({threshold} 未运行) last_run=2026-10-22 06:00"
        _chk(adr.stall_line_key(line) == f"stall|extra_stale|{task}",
             f"新任务名/行文变体被降级: {line!r} → {adr.stall_line_key(line)}")
        _chk(adr.stall_state_key(line) == f"{task}|extra_stale",
             f"新任务名变体的状态键须与 monitor 写法一致: {task}")

    _chk(adr.stall_line_key(sd) == "staticdata_backup_stale",
         f"真实 staticdata 心跳停摆行 → {adr.stall_line_key(sd)}")
    _chk(adr.stall_state_key(sd) == "staticdata_backup_stale")

    # 其余登记键(非 EXTRA/staticdata)行为不变
    cases = {
        "SEVERE: D1 同步连续失败 39 次": "d1_sync_fail",
        "SEVERE: cloud_unit_patrol_drift 缺 2 个 unit": "cloud_unit_patrol_drift",
        "SEVERE: failed_units_patrol 3 个 unit failed": "failed_units_patrol",
    }
    for line, canon in cases.items():
        _chk(adr.stall_line_key(line) == canon, f"{line} → {adr.stall_line_key(line)}, 期望 {canon}")
        _chk(adr.is_stall_line(line), f"{line} 应判停摆级")
    _chk(adr.stall_line_key("SEVERE: deploy 连续失败 39 次").startswith("stall|"),
         "泛化连续失败应合成 stall| 键")
    _chk(adr.stall_line_key("SEVERE: 某脚本单次失败 rc=1") is None, "普通单次失败不得判停摆")

    # 同一 2h 窗内各发各的: EXTRA 行与 staticdata 行互不抑制(真实 notify.send 路径)
    _write_json(iso["tmp"] / "data" / "alert_state.json", {})
    before = len(iso["calls"])
    r1 = notify.send("[告警] 计划任务停摆告警", extra, severe=True,
                     from_prefix="[告警]", ledger_key=adr.stall_line_key(extra))
    r2 = notify.send("[告警] 计划任务停摆告警", sd, severe=True,
                     from_prefix="[告警]", ledger_key=adr.stall_line_key(sd))
    _chk(r1.get("email") and r2.get("email"), f"两条停摆行必须各发各的: {r1} / {r2}")
    _chk(len(iso["calls"]) == before + 6, f"应各发 3 渠道(共 6), 实际 {len(iso['calls']) - before}")
    extra_body = [c for c in iso["calls"] if "fetch_news" in c["body"]][0]["body"]
    _chk("fetch_news 生成器停摆" in extra_body,
         f"EXTRA 正文必须按任务名说明影响(不得写成 staticdata 心跳): {extra_body[:300]}")
    _chk("staticdata 备份心跳超 36h" not in extra_body,
         f"EXTRA 正文张冠李戴成 staticdata 影响产物: {extra_body[:300]}")


def test_a_extra_context_reads_task_state(iso):
    """MF1: EXTRA 停摆正文三字段从 `{task}|extra_stale` 状态回查(不是合成去重键)。"""
    _write_json(iso["tmp"] / "data" / "alert_state.json", {
        "fetch_news|extra_stale": {"first_seen": "2026-10-21 03:00:00",
                                   "consecutive_count": 2,
                                   "suppress_count": 2},
    })
    ctx = adr.stall_context("stall|extra_stale|fetch_news", iso["tmp"])
    _chk(ctx["first_seen"] == "2026-10-21 03:00:00", f"首次发生应取任务状态: {ctx}")
    # MF6(2026-10-22): 连续失败次数必须读状态里的 consecutive_count, 不许恒「未知」
    _chk(ctx["consecutive"] == 2, f"连续失败次数应取任务状态 2: {ctx}")
    _chk("fetch_news" in ctx["impact"], f"影响产物必须点名任务: {ctx}")
    _chk("staticdata" not in ctx["impact"], f"不得串成 staticdata 影响: {ctx}")


def test_a_omission_guard_all_producer_keys_classified():
    """防遗漏: 扫 scripts/ 全部生产方 --dedup-key 字面量, 必须落在两张表其一。

    动态键(f-string/变量)无法静态取值, 用显式前缀白名单 + 理由登记(见 DYNAMIC_PREFIXES);
    新增键若既不登记也不是已知动态前缀 ⇒ 本用例红, 逼人做「是否停摆级」判定。
    """
    dynamic_prefixes = {
        "nextday_plan_": "按交易日每日一个键, 生成计划失败单轮自愈(非停摆)",
        "nextday_gap_excluded_": "按日排除清单键, 非故障链",
        "with_lock_block_timeout:": "锁等待超时键, 按锁路径动态",
        "agent_done_": "agent 完成通知按键名动态, 非告警",
        "r2_upload_async_skip:": "按锁路径动态跳过键, 非停摆",
        "p0_smoke_": "测试用键",
        "self_heal_repeat_fail_": "自愈连续失败提醒按任务动态(self_heal.sh 自愈通道, 非发布/备份停摆)",
        # 2026-10-28 告警降噪批次3-A(A2): retry_failed_metrics 的重采失败通知按 metric_id
        # 动态键; 单指标失败下一轮重采即可能自愈(非发布/备份产物停摆), 显式 24h 窗 ⇒ 非停摆级。
        "retry_failed_": "按 metric_id 动态的重采连续失败键(单指标自愈, 24h 窗, 非停摆)",
    }
    pats = [
        r'--dedup-key"?\s*,\s*"([A-Za-z0-9_|.:-]+)"',
        r'--dedup-key[ =]+"([A-Za-z0-9_|.:-]+)"',
        r"--dedup-key[ =]+'([A-Za-z0-9_|.:-]+)'",
        r"--dedup-key[ =]+([A-Za-z0-9_|.-]+)",
    ]
    found, dynamic = set(), set()
    fpat = re.compile(r'--dedup-key"?\s*,\s*f"([A-Za-z0-9_|.:-]+)\{')
    for p in sorted(SCRIPTS.glob("*")):
        if p.suffix not in (".py", ".sh") or not p.is_file():
            continue
        if p.name.startswith("test_") or p.name == "alert_weekly_review.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in fpat.finditer(text):
            dynamic.add(m.group(1))
            dynamic.add("r2_upload_async_skip:")
        for pat in pats:
            for m in re.finditer(pat, text):
                k = m.group(1).rstrip(":")
                if "_" in k:
                    found.add(k)
    # 文档串里写作 `<task>` 的动态键会被静态正则当成字面量收进来(self_heal_core.py docstring
    # 的 `--dedup-key self_heal_repeat_fail_<task>`): 已登记动态前缀的一律按动态键处理。
    unclassified = {k for k in found
                    if k not in adr.STALL_KEYS and k not in adr.NON_STALL_KEYS
                    and not any(k.startswith(x) for x in dynamic_prefixes)}
    _chk(not unclassified, f"未登记的新 dedup key(必须判停摆/非停摆): {sorted(unclassified)}")
    for pre in dynamic:
        _chk(any(pre.startswith(x) for x in dynamic_prefixes),
             f"动态键前缀 {pre!r} 未在防遗漏白名单登记")
    _chk(len(found) >= 40, f"扫描到的生产键过少({len(found)}), 防遗漏网可能失效")


def test_a_stall_bypasses_budget_and_domain_and_2h_dedup(iso):
    """构造 10-20 场景同款: 预算已满 + 同域 2h 窗内, 停摆级仍首报直发; 2h 内同键只发一次。"""
    alerts, calls = iso["alerts"], iso["calls"]
    keys = ["deploy_consecutive_fail", "staticdata_backup_stale",
            "r2_upload_trigger_fail", "d1_sync_fail",
            "failed_units_patrol", "cloud_unit_patrol_drift"]
    _write_json(iso["tmp"] / "data" / "alert_state.json", {
        "deploy_consecutive_fail": {"first_seen": "2026-10-20 12:00:00",
                                    "consecutive_count": 39},
        "staticdata_backup_stale": {"first_seen": "2026-10-20 09:00:00"},
    })
    _write_json(iso["tmp"] / "data" / "deploy_fail_state.json",
                {"consecutive_fail": 39, "last_fail_at": _now_s()})
    _write_json(iso["tmp"] / "data" / "staticdata_backup_fail_state.json",
                {"first_fail_date": "2026-10-20", "consecutive_days": 3})
    (iso["tmp"] / "data" / "d1_sync_state").mkdir(parents=True, exist_ok=True)
    _write_json(iso["tmp"] / "data" / "d1_sync_state" / "sync_a.json",
                {"script": "sync_a", "first_failure_at": "2026-10-20 10:00:00",
                 "consecutive_failures": 39})
    _write_json(iso["tmp"] / "data" / "failed_units_patrol_state.json",
                {"first_fail_date": "2026-10-20", "consecutive_days": 3})

    for key in keys:
        _seed_ledger(alerts, [{"ts": _now_s(), "group": "alert", "tier": "critical",
                               "key": key, "subject": key}])
        _seed_domain(alerts)
        _seed_dedup(alerts, "other_key")
        before = len(calls)
        res = notify.send(f"[告警] 计划任务异常: {key}", "原始正文",
                          severe=True, from_prefix="[告警]", ledger_key=key)
        _chk(res.get("email") and res.get("telegram") and res.get("feishu"),
             f"{key} 应三渠道直发(停摆绕过预算/域聚合), 实际 {res}")
        _chk(len(calls) == before + 3, f"{key} 应发出 3 次渠道调用")
        subj = calls[before]["subject"]
        body = calls[before]["body"]
        _chk(subj.startswith(adr.STALL_PREFIX), f"{key} 标题缺停摆前缀: {subj}")
        _chk("首次发生" in body and "连续失败" in body and "影响产物" in body,
             f"{key} 正文缺三字段: {body[:200]}")
        # 第二次(2h 内同键)只 suppress, 不再外发
        before2 = len(calls)
        res2 = notify.send(f"[告警] 计划任务异常: {key}", "原始正文",
                           severe=True, from_prefix="[告警]", ledger_key=key)
        _chk(res2.get("suppressed") is True, f"{key} 2h 内应 suppress, 实际 {res2}")
        _chk(len(calls) == before2, f"{key} 2h 内不得再次外发")
    recs = _supp_records(iso["tmp"])
    _chk(sum(1 for r in recs if r["mechanism"] == "stall_dedup") == len(keys),
         f"stall_dedup 审计记录应 {len(keys)} 条, 实际 {len(recs)}")


def test_a_context_three_fields_real_state(iso):
    _write_json(iso["tmp"] / "data" / "alert_state.json", {
        "deploy_consecutive_fail": {"first_seen": "2026-10-20 12:00:00"},
    })
    _write_json(iso["tmp"] / "data" / "deploy_fail_state.json",
                {"consecutive_fail": 39, "last_fail_at": "2026-10-22 11:00:00"})
    ctx = adr.stall_context("deploy_consecutive_fail", iso["tmp"])
    _chk(ctx["first_seen"] == "2026-10-20 12:00:00", f"首次发生应取 alert_state: {ctx}")
    _chk(ctx["consecutive"] == 39, f"连续失败应取真实状态 39: {ctx}")
    _chk("线上静态站" in ctx["impact"] or "发布链" in ctx["impact"], f"影响产物: {ctx}")
    ctx2 = adr.stall_context("r2_upload_trigger_fail", iso["tmp"])
    _chk(ctx2["first_seen"] == "未知" and ctx2["consecutive"] == "未知",
         f"无状态文件必须显式写未知: {ctx2}")


def test_a_stall_window_policy():
    """停摆通道窗径: 非零窗 2h 地板; 显式 0(脚本自管闸门)原样保留, 不吞新增立即报。"""
    _chk(adr.stall_dedup_window(None) == adr.STALL_DEDUP_WINDOW)
    _chk(adr.stall_dedup_window(0) == 0, "显式 0 必须保留(check_failed_units/d1_sync 自管闸门)")
    _chk(adr.stall_dedup_window(-1) == 0)
    _chk(adr.stall_dedup_window(3600) == adr.STALL_DEDUP_WINDOW, "1h 调用窗应抬到 2h 地板")
    _chk(adr.stall_dedup_window(21600) == 21600, "deploy 现网 6h 窗不得被缩短成 2h")


def test_a_stall_window_2h_discriminates_3h_ago(iso, monkeypatch):
    """MF4 判别力用例: 「3h 前占窗」是 2h 窗与 6h 窗的**分界线**。

    2h 窗 ⇒ 已过期必须重发; 把窗改回 6h(变异) ⇒ 同场景必须抑制。
    修复前只有「立即第二次 suppress」用例(2h/6h 都绿) ⇒ 窗口回退测不出来(§18 L49 同族)。
    """
    key = "staticdata_backup_stale"  # 走通用停摆路径(非 R4 分支)
    now = datetime.now()
    _seed_dedup(iso["alerts"], key, now=now - timedelta(hours=3))
    before = len(iso["calls"])
    res = notify.send("[告警] 计划任务异常: 备份停摆", "正文", severe=True,
                      from_prefix="[告警]", ledger_key=key)
    _chk(res.get("email") is True and len(iso["calls"]) == before + 3,
         f"2h 窗下 3h 前占窗应重发, 实际 {res}")

    # 变异对照(窗口回退探测): 同样 3h 前占窗, 6h 窗内 ⇒ 必须 suppress
    _seed_dedup(iso["alerts"], key, now=now - timedelta(hours=3))
    monkeypatch.setattr(adr, "STALL_DEDUP_WINDOW", 21600)
    before = len(iso["calls"])
    res2 = notify.send("[告警] 计划任务异常: 备份停摆", "正文", severe=True,
                       from_prefix="[告警]", ledger_key=key)
    _chk(res2.get("suppressed") is True and len(iso["calls"]) == before,
         f"6h 窗下 3h 前占窗必须抑制(否则本用例失去判别力), 实际 {res2}")


def test_a_cli_staticdata_r4_window_is_6h(iso):
    """R4 staticdata_backup_fail 窗 = 6h(21600s, 低频高危不跟 2h 地板)。

    MF(主控拍板): 该键两次失败间隔 3h ⇒ 仍抑制; 间隔 6h+ ⇒ 重发。
    """
    calls = iso["calls"]
    _write_json(iso["tmp"] / "data" / "staticdata_backup_fail_state.json",
                {"last_fail_date": "2026-10-20", "consecutive_days": 2})

    def _run(rf_name, window="3600"):
        rf = iso["tmp"] / rf_name
        rc = notify.main(["[告警] staticdata 备份失败(连续 3 天)", "备份正文", "--severe",
                          "--from-prefix", "[告警]", "--dedup-key", "staticdata_backup_fail",
                          "--dedup-window", window, "--result-file", str(rf)])
        return rc, json.loads(rf.read_text(encoding="utf-8"))["status"]

    rc, st = _run("r4a.json")
    _chk(rc == 0 and st == "sent", f"R4 停摆首报应直发, 实际 rc={rc} status={st}")
    _chk(len(calls) == 3, f"R4 停摆应直发三渠道, 实际 {calls}")
    _chk(calls[0]["subject"].startswith(adr.STALL_PREFIX), calls[0]["subject"])
    _chk("首次发生" in calls[0]["body"] and "影响产物" in calls[0]["body"])

    rc, st = _run("r4b.json")
    _chk(st == "suppressed", f"窗内第二轮应抑制, 实际 {st}")

    # 3h 前占窗: 6h 窗内 ⇒ 仍抑制(与 2h 地板的差异点)
    _seed_dedup(iso["alerts"], "staticdata_backup_fail",
                now=datetime.now() - timedelta(hours=3))
    before = len(calls)
    rc, st = _run("r4c.json")
    _chk(st == "suppressed" and len(calls) == before,
         f"3h 间隔必须仍抑制(6h 窗), 实际 {st}")
    # 6h+ 前占窗 ⇒ 必须重发
    _seed_dedup(iso["alerts"], "staticdata_backup_fail",
                now=datetime.now() - timedelta(hours=7))
    rc, st = _run("r4d.json")
    _chk(st == "sent" and len(calls) == before + 3,
         f"7h 间隔必须重发(6h 窗已过), 实际 {st}")
    _chk(any(r["mechanism"] == "stall_dedup" for r in _supp_records(iso["tmp"])))


def test_a_ordinary_event_still_aggregated(iso):
    """普通事件行为不回退: 日预算满或同域 2h 窗内仍并入摘要, 不外发。"""
    alerts, calls = iso["alerts"], iso["calls"]
    key = "r2_consistency_fail"  # 非停摆级(语义待 #279 收口), 预算类别 r2
    _chk(not adr.is_stall_key(key))
    _chk(adr.category_of(key, "") == "r2" and adr.domain_of(key, "") == "r2_deploy")
    _seed_ledger(alerts, [{"ts": _now_s(), "group": "alert", "tier": "critical",
                           "key": key, "subject": key}])
    _seed_domain(alerts)
    res = notify.send(f"[告警] {key} R2 上传失败", "正文", severe=True,
                      from_prefix="[告警]", ledger_key=key)
    _chk(res.get("digested") is True, f"普通键预算满应并入摘要, 实际 {res}")
    _chk(calls == [], f"普通键被聚合时不得外发, 实际 {calls}")
    _chk(any(r["mechanism"] == "budget" for r in _supp_records(iso["tmp"])),
         "预算吸收必须写审计台账")


def test_a_domain_aggregation_record_and_n_absorbed_today(iso):
    alerts, calls = iso["alerts"], iso["calls"]
    key = "intraday_upload_index_r2_fail"
    _seed_domain(alerts)
    res = notify.send(f"[告警] {key} R2 上传失败", "正文", severe=True,
                      from_prefix="[告警]", ledger_key=key)
    _chk(res.get("digested") is True, f"同域 2h 窗内应并入摘要, 实际 {res}")
    _chk(calls == [])
    recs = [r for r in _supp_records(iso["tmp"]) if r["mechanism"] == "domain_aggregate"]
    _chk(len(recs) == 1, f"应写 1 条 domain_aggregate, 实际 {recs}")
    _chk(recs[0]["domain"] == "r2_deploy" and recs[0]["key"] == key)
    # 口径: n_absorbed(累计) vs n_absorbed_today(本日)
    st = json.loads((alerts / adr.ALERT_DOMAIN_STATE_FILENAME).read_text(encoding="utf-8"))
    entry = st["r2_deploy"]
    _chk(entry["n_absorbed_today"] == 1 and entry["n_absorbed"] >= 1,
         f"域状态口径字段缺失: {entry}")


# ══════════════════════════ B. active 升级阶梯 ══════════════════════════
def test_b_active_judge_three_states_and_old_state():
    now = datetime(2026, 10, 22, 12, 0, 0)
    fresh = {"first_alerted": _now_s(now - timedelta(hours=1)), "last_alerted": _now_s(now)}
    ok, info = adr.active_escalation_judge(fresh, now)
    _chk(ok is False and info["elapsed_hours"] == 1.0, f"1h 不应升级: {ok} {info}")

    old = {"first_alerted": _now_s(now - timedelta(hours=25)), "suppress_count": 7}
    ok, info = adr.active_escalation_judge(old, now)
    _chk(ok is True and info["elapsed_hours"] == 25.0 and info["suppress_count"] == 7,
         f"25h 应升级: {ok} {info}")

    just = dict(old, last_escalated=_now_s(now))
    ok, info = adr.active_escalation_judge(just, now)
    _chk(ok is False and "距上次升级" in info["reason"], f"刚升级不应重复: {ok} {info}")

    later = dict(old, last_escalated=_now_s(now - timedelta(hours=25)))
    ok, _ = adr.active_escalation_judge(later, now)
    _chk(ok is True, "距上次升级满 24h 应再提醒")

    # 老状态向后兼容: 没有 first_alerted
    ok, info = adr.active_escalation_judge(
        {"first_seen": _now_s(now - timedelta(hours=30))}, now)
    _chk(ok is True and info["first_alerted"].startswith("2026-10-21"), f"{info}")
    ok, info = adr.active_escalation_judge(
        {"last_alerted": _now_s(now - timedelta(hours=1))}, now)
    _chk(ok is False, f"老状态回填 last_alerted 后不应立刻升级: {info}")
    ok, info = adr.active_escalation_judge({}, now)
    _chk(ok is False and info["reason"].startswith("无首次时间"), f"空状态不得崩: {info}")


def _load_active_escalate(tmp_path: Path):
    """从 schedule_monitor.sh 内嵌 python heredoc ast 提取 _active_escalate 真源码执行。

    不重写副本(防第三实现漂移): 测的就是线上那个函数体。
    """
    text = MONITOR.read_text(encoding="utf-8")
    _mark = text.index("<<'PYEOF'")
    start = text.index("\n", _mark) + 1
    end = text.index("\nPYEOF", start)
    py_src = text[start:end]
    tree = ast.parse(py_src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_active_escalate")
    code = ast.get_source_segment(py_src, node)
    events = []

    def _run(cmd, **kw):
        events.append({"cmd": cmd, "kw": kw})
        # 批次3-D(#321): 升级档改读 --result-file 的结构化 status; 桩必须写结果文件,
        # 否则 _active_escalate 按「未确认送达」返回 False(本用例的 sent 场景)。
        if "--result-file" in cmd:
            Path(cmd[cmd.index("--result-file") + 1]).write_text(
                json.dumps({"status": "sent"}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="[notify] sent", stderr="")

    ns = {
        "adr": adr, "NOW": datetime.now(), "sys": sys, "hashlib": __import__("hashlib"),
        "REPO": tmp_path, "MONITOR_LOG": tmp_path / "monitor.log",
        "subprocess": types.SimpleNamespace(run=_run),
        "notify_sent": lambda out: "sent" in out,
        # 批次3-D: 真函数体用 tempfile/json/os/Path 读 --result-file
        "tempfile": tempfile, "json": json, "os": os, "Path": Path,
        # #309 F2(2026-10-26): 升级真发出时累加告警邮件数(本用例不关心计数, 只需名字存在)
        "_ALERT_MAIL_COUNTER": {"sent": 0},
    }
    exec(compile(code, "<monitor:_active_escalate>", "exec"), ns)
    return ns["_active_escalate"], events


def test_b_active_escalate_helper_outbound_counts(iso):
    fn, events = _load_active_escalate(iso["tmp"])
    now = datetime.now()
    fresh = {"first_alerted": _now_s(now - timedelta(hours=1))}
    _chk(fn(fresh, "key|ConnectionError", "nextday_gap_check") is False)
    _chk(len(events) == 0, "1h 持续只抑制不外发")
    _chk(fresh["suppress_count"] == 1, "抑制轮次必须累计")

    old = {"first_alerted": _now_s(now - timedelta(hours=25))}
    _chk(fn(old, "key|ConnectionError", "nextday_gap_check") is True)
    _chk(len(events) == 1, "满 24h 必须发一次升级")
    body = events[0]["kw"].get("capture_output") is not None  # subprocess 调用形态
    _chk(body, "升级提醒必须走 notify 子进程")
    _chk("last_escalated" in old and old["n_escalated"] == 1, f"状态未记升级: {old}")
    _chk(fn(old, "key|ConnectionError", "nextday_gap_check") is False)
    _chk(len(events) == 1, "刚升级 24h 内不得重复")

    legacy = {"last_alerted": _now_s(now - timedelta(hours=1))}
    _chk(fn(legacy, "k2", "legacy") is False, "老状态不得崩")
    _chk(len(events) == 1)
    legacy2 = {"first_seen": _now_s(now - timedelta(hours=26))}
    _chk(fn(legacy2, "k3", "legacy2") is True, "老状态 first_seen 满 24h 应升级")
    _chk(len(events) == 2 and legacy2["first_alerted"] == legacy2["first_seen"],
         "first_alerted 应回填")

    recs = [r for r in _supp_records(iso["tmp"]) if r["mechanism"] == "active"]
    _chk(len(recs) == 5, f"每次 active 抑制都要留审计(5 次), 实际 {len(recs)}")
    _chk(all(r["source"] == "schedule_monitor" for r in recs))
    _chk(all(r["first_seen"] for r in recs))


def test_b_escalate_keeps_own_key_despite_r4(iso):
    """MF2: 预置真实 R4 键后, 25h 升级提醒必须仍被处置(修复前被改写成
    staticdata_backup_fail, 与 R4 共用 86400s 窗 ⇒ 永久发不出); 连续两轮(25h/26h)
    只提醒 1 次。批次3-D(#321)起「处置」= 并入当日摘要(digest_only), 不再是即时直发。"""
    fn, events = _load_active_escalate_inprocess(iso["tmp"])
    now = datetime.now()
    _seed_dedup(iso["alerts"], "staticdata_backup_fail", now=now)
    st0 = json.loads(notify.DEDUP_FILE.read_text(encoding="utf-8"))
    r4_ts = st0["staticdata_backup_fail"]["last_alerted"]

    entry = {"first_alerted": _now_s(now - timedelta(hours=25))}
    ok = fn(entry, "staticdata_backup_stale", "staticdata_backup 异步备份停摆")
    _chk(ok is True, "真实 R4 键已存在时, 25h 升级提醒必须仍能被处置(并入摘要也算)")
    _chk(len(events) == 1, f"本轮应只走一次 notify, 实际 {len(events)}")
    # 批次3-D(#321): 升级档改 digest_only ⇒ 不即时直发, 并入当日摘要(report 群+邮件)。
    _chk(len(iso["calls"]) == 0,
         f"升级档不得即时直发(应并入摘要), 实际直发 {iso['calls']}")
    cmd = [str(c) for c in events[0]]
    _chk("--digest-only" in cmd, f"升级档必须走摘要吸收: {cmd}")
    _chk("--severe" not in cmd, f"升级档不得再带 --severe(否则摘要吸收不可达): {cmd}")
    _chk("--result-file" in cmd, "升级档必须读结构化 status(否则 absorbed 被判未送达)")
    digest_entries = [json.loads(ln) for ln in
                      (iso["alerts"] / "alert_digest.jsonl").read_text(
                          encoding="utf-8").splitlines() if ln.strip()]
    _chk(len(digest_entries) == 1, f"摘要 buffer 应有 1 条, 实际 {digest_entries}")
    de = digest_entries[0]
    subj = str(de.get("subject") or "")
    body = str(de.get("body") or "")
    _chk(subj.startswith("[告警] 【持续故障升级】"), f"标题不得被改写成停摆: {subj}")
    _chk(not subj.startswith(adr.STALL_PREFIX), f"升级消息不得带停摆前缀: {subj}")
    _chk("持续故障升级提醒" in body, f"正文应是升级模板: {body[:200]}")
    _chk(de.get("category") == "escalation"
         and de.get("reason") == notify.DIGEST_ESCALATION_REASON,
         f"摘要条目分类/原因不符: {de}")
    _chk("staticdata 备份心跳超 36h" not in body,
         f"升级正文被改写成 staticdata 影响产物(修复前症状): {body[:300]}")
    _chk(entry.get("last_escalated") is not None and entry.get("n_escalated") == 1,
         f"升级处置成功必须记 last_escalated: {entry}")
    st1 = json.loads(notify.DEDUP_FILE.read_text(encoding="utf-8"))
    _chk(len([k for k in st1 if k.startswith("active_escalate|")]) == 0,
         f"吸收路径不占 dedup 窗(24h 闸门由 monitor last_escalated 记): {sorted(st1)}")
    _chk(st1["staticdata_backup_fail"]["last_alerted"] == r4_ts,
         "R4 键时间戳不得被升级消息改写(共用键即 MF2 病灶)")

    # 第二轮(26h): 刚升级 <24h ⇒ 不再发, notify 调用数与摘要条数都不变
    entry["first_alerted"] = _now_s(now - timedelta(hours=26))
    ok2 = fn(entry, "staticdata_backup_stale", "staticdata_backup 异步备份停摆")
    _chk(ok2 is False, "连续两轮(25h/26h)应只提醒 1 次")
    _chk(len(events) == 1, f"第二轮不得外发: {events}")

    # 键/标题兜底双保险(单独断言)
    _chk(adr.stall_canonical_key(
        "active_escalate|deadbeef", "[告警] 【持续故障升级】staticdata_backup 异步备份停摆") is None,
        "active_escalate| 键禁止被 subject 兜底改写成停摆键")
    _chk(adr.stall_canonical_key(
        None, "[告警] 【持续故障升级】staticdata_backup 异步备份停摆") is None,
        "升级标题标记本身也必须阻断 subject 兜底")


def test_b_escalate_suppressed_by_24h_dedup_counts_as_handled(iso):
    """#321 边界: monitor 状态回滚/丢失而 dedup 台账仍在(24h 窗内) ⇒ notify 返回
    suppressed。此时升级提醒**窗内确已送过一次**, 必须与 sent/digested 同判「已处置」
    (落 last_escalated), 否则每 15min 重试、连续 24h(96 轮)刷日志且一封都发不出。
    判别力: 把 suppressed 从已处置集合删掉 ⇒ 本用例红(ok 为 False、last_escalated 缺失)。"""
    fn, events = _load_active_escalate_inprocess(iso["tmp"])
    now = datetime.now()
    key = "staticdata_backup_stale"
    esc_key = "active_escalate|" + __import__("hashlib").sha1(
        key.encode("utf-8")).hexdigest()[:12]
    _seed_dedup(iso["alerts"], esc_key, now=now)  # 窗内已发过

    entry = {"first_alerted": _now_s(now - timedelta(hours=25))}
    ok = fn(entry, key, "staticdata_backup 异步备份停摆")
    _chk(ok is True, "24h 去重窗内已发过 ⇒ 也算已处置(不是未送达重试)")
    _chk(len(events) == 1, f"本轮应只走一次 notify, 实际 {len(events)}")
    _chk(len(iso["calls"]) == 0, f"去重窗内不得再直发, 实际 {iso['calls']}")
    _chk(entry.get("last_escalated") is not None and entry.get("n_escalated") == 1,
         f"处置成功必须记 last_escalated(防 15min 重试风暴): {entry}")
    dg = iso["alerts"] / "alert_digest.jsonl"
    _chk(not dg.exists() or not dg.read_text(encoding="utf-8").strip(),
         "去重窗内不应再追加摘要条目(窗内已有一条)")


def test_b_monitor_wiring_and_comment_consistency():
    src = MONITOR.read_text(encoding="utf-8")
    _chk("def _active_escalate(" in src)
    _chk(src.count("_active_escalate(") >= 21,
         f"active 抑制点应全部收敛到 _active_escalate, 实际 {src.count('_active_escalate(')}")
    _chk(src.count("[suppress]") == 1, "只允许升级函数内部打印一次抑制日志")
    _chk("原注释声称「真卡死仍响」但实现无条件静默" in src, "注释须如实说明旧口径矛盾")
    _chk("首次告警满 24h 且距上次升级满 24h" in src, "新口径须写清")
    # A 的 monitor 接线: 停摆行必须在批次预算之前被拆出
    _chk("_stall_batch = []" in src and "adr.stall_line_key" in src)
    _chk(src.index("_stall_batch = []")
         < src.index("alerts, _absorbed = adr.alert_budget_process("),
         "停摆行拆分必须早于批次预算(否则仍会被预算吸收)")
    _chk('"--dedup-window", str(adr.STALL_DEDUP_WINDOW)' in src, "停摆直发必须带 2h 窗")
    # 边界④上下游依赖(失败路径): 停摆直发未确认送达必须 fail-open 回批 + 回滚本轮状态,
    # 否则一次发送故障 = 该条停摆告警被静默吞掉(不能因新增通道制造新黑洞)。
    _chk("alerts.append(_line)" in src, "直发失败必须把行放回普通批次(fail-open)")
    _chk("alert_state[_st_state_key] = dict(_STATE_PRE[_st_state_key])" in src,
         "直发失败须回滚本轮新写的 active 状态(否则下轮被当持续中抑制)")
    _chk("alert_state.pop(_st_state_key, None)" in src,
         "直发失败须清掉本轮新建的状态键(原状态不存在时)")
    # MF3(2026-10-22): 直发判据必须是结构化的 status(suppressed=已处置), 不是输出文本
    _chk('"--result-file"' in src, "停摆直发必须传 --result-file 读结构化 status")
    _chk('_st_status in ("sent", "suppressed")' in src,
         "suppressed 必须视为已处置(不回批/不回滚)")
    _chk("adr.stall_state_key(_line)" in src,
         "回滚状态键必须走 adr.stall_state_key(EXTRA 任务键才会被正确回滚)")
    # MF5(2026-10-22): mkdtemp 必须在 try 内 + _st_rf 先置 None + finally 空值守卫,
    # 否则磁盘满(ENOSPC)时 OSError 逃逸整块 ⇒ 本轮全部告警(含磁盘告警自己)全丢。
    _chk("_st_rf = None" in src, "MF5: _st_rf 必须先置 None(清理守卫用)")
    _chk('        _st_rf = Path(tempfile.mkdtemp(prefix="stall-direct-"))'
         in src, "MF5: mkdtemp 必须在 try 内(缩进 8 空格)")
    _chk(src.index("_st_rf = None") < src.index('_st_rf = Path(tempfile.mkdtemp('),
         "MF5: 初始化必须早于 mkdtemp")
    _chk("if _st_rf is not None:" in src, "MF5: finally 清理必须先判 _st_rf 非空")
    _chk('_st_status = "failed"' in src and
         src.index('_st_status = "failed"') < src.index('_st_rf = Path(tempfile.mkdtemp('),
         "MF5: mkdtemp 失败必须落到 fail-open 回批(默认 failed)")
    # MF6(2026-10-22): EXTRA 停摆状态首建记 consecutive_count=1, active 分支递增
    _ext_start = src.index("alert_state[_stale_key] = {")
    _chk('"consecutive_count": 1,' in src[_ext_start:_ext_start + 700],
         "MF6: EXTRA 停摆状态须首建 consecutive_count=1")
    _chk('_ex_stale["consecutive_count"] = int(_ex_stale.get("consecutive_count") or 0) + 1'
         in src, "MF6: EXTRA active 分支须递增连续次数")


# ══════════════════════════ D. 停摆直发 status 语义(MF3) ══════════════════════════
def test_d_notify_result_file_status_suppressed(iso):
    """真实 notify.main: 第二轮同键 = status suppressed(不是 failed) —— 直发判据的地基。"""
    rf = iso["tmp"] / "nd_result.json"
    base = ["[告警] 计划任务停摆", "正文", "--severe", "--from-prefix", "[告警]",
            "--dedup-key", "staticdata_backup_stale", "--dedup-window", "7200",
            "--result-file", str(rf)]
    notify.main(list(base))
    _chk(json.loads(rf.read_text(encoding="utf-8"))["status"] == "sent")
    notify.main(list(base))
    _chk(json.loads(rf.read_text(encoding="utf-8"))["status"] == "suppressed",
         "2h 窗内第二轮必须是 suppressed(修复前文本判据会把它当未送达)")


def test_d_stall_direct_suppressed_not_rebatched(iso):
    """MF3: 真 monitor 直发块 —— suppressed ⇒ 不进回批、不打 warn、不回滚 active。"""
    line = _real_extra_line("fetch_news", 4)
    state = {"fetch_news|extra_stale": {"status": "active", "first_seen": "2026-10-21 00:00:00"}}
    out = _run_stall_direct([line], state, {}, {"v": "suppressed"})
    _chk(out["alerts"] == [], f"suppressed=已处置, 不得回批(回批无 dedup key ⇒ 去重失效): {out['alerts']}")
    _chk("fetch_news|extra_stale" in out["alert_state"],
         "suppressed 不得回滚本轮新写的 active 状态")
    _chk("[warn]" not in out["stderr"], f"suppressed 不应打 warn: {out['stderr']}")
    _chk(len(out["cmds"]) == 1 and "--result-file" in out["cmds"][0],
         f"必须带 --result-file: {out['cmds']}")


def test_d_stall_direct_failed_fail_open(iso):
    """MF3 反向: failed ⇒ 仍 fail-open 回批 + 回滚(宁多勿吞, 不制造新黑洞)。"""
    line = _real_extra_line("fetch_news", 4)
    state = {"fetch_news|extra_stale": {"status": "active"}}
    out = _run_stall_direct([line], state, {}, {"v": "failed"})
    _chk(out["alerts"] == [line], "failed 必须回批")
    _chk("fetch_news|extra_stale" not in out["alert_state"], "失败须回滚本轮新建状态键")
    _chk("[warn]" in out["stderr"], "失败要打 warn 留痕")


def test_d_stall_direct_missing_result_file_fail_open(iso):
    """结果文件缺失(旧版 notify/写失败) ⇒ 文本判据判不出 ⇒ 保守回批。"""
    line = _real_extra_line("fetch_news", 4)
    out = _run_stall_direct([line], {}, {}, {"v": ""})
    _chk(out["alerts"] == [line], "结果文件缺失且文本判据判不出, 必须保守回批")


def test_d_ordinary_line_untouched_by_stall_block(iso):
    """回归: 普通(非停摆)行不触发直发, 原样留在批次里走原逻辑。"""
    line = "SEVERE: backfill_evening exit=1 单次失败"
    out = _run_stall_direct([line], {}, {}, {"v": "sent"})
    _chk(out["alerts"] == [line], "普通行必须原样留在普通批次")
    _chk(out["cmds"] == [], "普通行不得触发停摆直发子进程")


# ══════════════════════════ E. MF5/MF6 磁盘满与连续次数 ══════════════════════════
def test_e_mkdtemp_enospc_keeps_whole_round(iso):
    """MF5: 磁盘满(ENOSPC)注入 —— 直发块不逃逸, 普通告警与停摆告警都仍回批。"""
    stall_line = _real_extra_line("fetch_news", 4)
    ordinary = "SEVERE: 主机磁盘 / 使用率 98%(SEVERE 阈值)"
    state = {"fetch_news|extra_stale": {"status": "active"}}
    out = _run_stall_direct([stall_line, ordinary], state, {}, {"v": "sent"},
                            mkdtemp_raises=True)
    _chk(len(out["alerts"]) == 2,
         f"mkdtemp 失败不得丢任何一行(本轮整轮告警全丢=MF5): {out['alerts']}")
    _chk(stall_line in out["alerts"], "停摆行必须 fail-open 回批")
    _chk(ordinary in out["alerts"], "同批普通告警(含磁盘告警本身)不得被吞")
    _chk(out["cmds"] == [], f"mkdtemp 已失败, 不应再起子进程: {out['cmds']}")
    _chk("[warn]" in out["stderr"], "必须打 warn 留痕(磁盘满)")
    _chk("fetch_news|extra_stale" not in out["alert_state"],
         "回批后须回滚本轮新写状态(下轮重试)")

    # 真实行文反证: 同轮磁盘满告警本身也必须仍能被识别为普通批次行
    _chk(adr.stall_line_key(ordinary) is None, "普通磁盘告警不得被误判成停摆级")


def test_e_enospc_still_saves_state_and_sends(iso):
    """MF5: mkdtemp 抛 OSError 时, 后续 save_alert_state 仍执行、普通行仍留在批次发送。"""
    stall_line = _real_extra_line("fetch_news", 4)
    ordinary = "SEVERE: backfill_evening exit=1 单次失败"
    state = {"fetch_news|extra_stale": {"status": "active"}}
    out = _run_stall_direct_with_save([stall_line, ordinary], state, {}, mkdtemp_raises=True)
    _chk(len(out["saved"]) == 1, f"save_alert_state 必须仍被调用(异常不得逃逸整块): {out['saved']}")
    _chk(out["alerts"] == [ordinary, stall_line],
         f"普通行 + 回批停摆行都须进入后续批次: {out['alerts']}")
    _chk(out["cmds"] == [], "mkdtemp 失败时不得起发送子进程")


def test_e_enospc_absent_control_still_direct_sends(iso):
    """MF5 判别力: mkdtemp 正常时 sent ⇒ 不回批(证明上两条红不是恒真)。"""
    stall_line = _real_extra_line("fetch_news", 4)
    ordinary = "SEVERE: backfill_evening exit=1 单次失败"
    state = {"fetch_news|extra_stale": {"status": "active"}}
    out = _run_stall_direct_with_save([stall_line, ordinary], state, {}, mkdtemp_raises=False)
    _chk(out["alerts"] == [ordinary], f"正常直发成功不得回批: {out['alerts']}")
    _chk(len(out["saved"]) == 1 and len(out["cmds"]) == 1,
         f"正常路径: 一次发送 + 一次落盘, 实得 {out['cmds']} / {out['saved']}")


def test_e_extra_stall_consecutive_count_real_loop(iso):
    """MF6: 跑真实 EXTRA 停摆循环 —— 首报 1、持续递增、恢复重建从 1 起, 正文不再「未知」。"""
    now = datetime(2026, 10, 22, 12, 0, 0)
    loops = {"fetch_news": timedelta(hours=4)}
    stats = [{"task": "fetch_news", "last_run": "2026-10-22 01:00"}]
    key = "fetch_news|extra_stale"
    state: dict = {}

    ns1, esc1 = _run_extra_stale_loop(state, stats, now, loops)
    _chk(len(ns1["alerts"]) == 1 and "fetch_news 停摆" in ns1["alerts"][0],
         f"首轮须发停摆告警: {ns1['alerts']}")
    _chk(key in ns1["seen_keys_this_run"], "首轮须标 seen(防误恢复)")
    _chk(state[key]["consecutive_count"] == 1, f"首报连续次数应为 1: {state[key]}")
    _chk(esc1 == [], "首报不走 active 升级(还没 active)")

    ns2, esc2 = _run_extra_stale_loop(state, stats, now + timedelta(minutes=15), loops)
    _chk(ns2["alerts"] == [], "持续中不重发普通告警")
    _chk(state[key]["consecutive_count"] == 2, f"第二轮连续次数应递增为 2: {state[key]}")
    _chk(len(esc2) == 1 and esc2[0][0] == key, f"active 分支须走 _active_escalate: {esc2}")

    _run_extra_stale_loop(state, stats, now + timedelta(minutes=30), loops)
    _chk(state[key]["consecutive_count"] == 3, f"第三轮应为 3: {state[key]}")

    # 正文三字段: 连续失败次数读真实状态(不许「未知」)
    _write_json(iso["tmp"] / "data" / "alert_state.json", {key: state[key]})
    ctx = adr.stall_context("stall|extra_stale|fetch_news", iso["tmp"])
    _chk(ctx["consecutive"] == 3, f"正文应显示连续 3 轮: {ctx}")
    body = adr.format_stall_body("原始正文", ctx)
    _chk("连续失败: 3" in body, f"正文连续失败不得为「未知」: {body[:200]}")

    # 任务恢复 ⇒ 状态键被主恢复循环删除; 再停摆 = 重建从 1 起
    state.clear()
    _run_extra_stale_loop(state, stats, now + timedelta(hours=6), loops)
    _chk(state[key]["consecutive_count"] == 1, f"恢复后重建应从 1 起: {state[key]}")


# ══════════════════════════ C. 抑制/合并审计台账 ══════════════════════════
def test_c_records_have_complete_fields(iso):
    now = datetime(2026, 10, 22, 12, 0, 0)
    ok = adr.record_suppression(mechanism="budget", key="k_demo", reason="演示",
                                source="test_282", repo=iso["tmp"], now=now,
                                first_seen="2026-10-20 09:00:00", event_id="evt1")
    _chk(ok is True)
    rec = _supp_records(iso["tmp"])[-1]
    for f in ("ts", "day", "mechanism", "key", "fingerprint", "domain", "reason",
              "source", "first_seen", "event_id"):
        _chk(f in rec, f"审计字段缺失: {f} ({rec})")
    _chk(rec["day"] == "2026-10-22" and len(rec["fingerprint"]) == 12)
    _chk(adr.SUPPRESSION_LEDGER_RETAIN_DAYS == 30)
    for m in ("budget", "domain_aggregate", "dedup", "active", "recurrence",
              "stall_dedup", "escalation_window", "monitor_budget"):
        _chk(m in adr.SUPPRESS_MECHANISMS, f"机制枚举缺 {m}")


def test_c_unwritable_ledger_does_not_break_main_path(iso, monkeypatch):
    alerts, calls = iso["alerts"], iso["calls"]
    blocker = iso["tmp"] / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setattr(adr, "suppression_ledger_path",
                        lambda repo=None: blocker / "x" / SUPP_LEDGER)
    _chk(adr.record_suppression(mechanism="budget", key="k", repo=iso["tmp"]) is False,
         "不可写时应安静返回 False")
    _seed_domain(alerts)
    res = notify.send("[告警] intraday_upload_index_r2_fail R2 上传失败", "正文",
                      severe=True, from_prefix="[告警]",
                      ledger_key="intraday_upload_index_r2_fail")
    _chk(res.get("digested") is True, f"台账写失败不得改变聚合行为: {res}")
    _chk(calls == [], "台账写失败不得触发外发")


def test_c_ledger_30day_rotation(iso):
    p = iso["tmp"] / "data" / "alerts" / SUPP_LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    keep_ts = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": old_ts, "mechanism": "budget"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": keep_ts, "mechanism": "budget"}, ensure_ascii=False) + "\n")
    _chk(adr.record_suppression(mechanism="dedup", key="fresh", repo=iso["tmp"]) is True)
    recs = _supp_records(iso["tmp"])
    _chk(all(r.get("ts") != old_ts for r in recs), "40 天前记录应被轮转清理")
    _chk(any(r.get("ts") == keep_ts for r in recs), "3 天前记录必须保留")
    _chk(any(r.get("key") == "fresh" for r in recs))
    _chk((p.parent / adr.SUPPRESSION_LEDGER_PRUNE_MARKER).exists(), "轮转须留当日标记防重复重写")