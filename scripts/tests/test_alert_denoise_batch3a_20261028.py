# -*- coding: utf-8 -*-
"""告警降噪批次3-A(A2 + A3)回归测试(2026-10-28)。

A2 `scripts/retry_failed_metrics.py`: 重采失败通知补 24h 去重(`--dedup-key retry_failed_<mid>
   --dedup-window 86400 --result-file`); 返回值语义由「已发出」改为「**已处置**」:
   status ∈ {sent, suppressed, digested} ⇒ 已处置(清零计数); failed/noop/unknown/结果文件
   读不到且旧文本判据不认/超时/异常 ⇒ 未处置(不清零, 下轮重试, fail-open)。

A3 `scripts/schedule_monitor.sh`: 主聚合告警 subject 带归一化任务名
   (`[告警] N项计划任务异常 [a/b] MM-DD HH:MM`), 任务串 ≤60 字符、总长 ≤120; 正文 body 一个
   字节不改; 不加 --dedup-key。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub): 本文件所有用例都**不 spawn
   真进程**——`rfm.subprocess` 用模块级替身接管, 外加 `ZeroOutboundTrap` 包裹; `test_00`
   先证 trap 确实武装。时间敏感处不取真实 `today()`: main() 全链路打桩, 日期用固定字面量。

跑法: python -m pytest -q scripts/tests/test_alert_denoise_batch3a_20261028.py
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import types
import urllib.request
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(_TESTS_DIR))                 # scripts/tests (for _zero_outbound)
sys.path.insert(0, str(_TESTS_DIR.parent))          # scripts (for retry_failed_metrics)
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

import retry_failed_metrics as rfm  # noqa: E402

ROOT = _TESTS_DIR.parent.parent
SCHED = ROOT / "scripts" / "schedule_monitor.sh"

# notify.py 通用路径真实输出形态(逐字照 notify.py 打点行)
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49)
_MIN_ASSERTIONS = 45
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════════════════════════════════════════════════════════════
# 公共打桩(A2): 模块属性级 subprocess 替身, 绝不 spawn 真 notify.py
# ══════════════════════════════════════════════════════════════════════════════
def _shim_run(status=None, output="", rc=0, calls=None, raise_exc=None,
              corrupt_json=False, write_file=True):
    """构造 rfm.subprocess 替身。

    status != None ⇒ 在 argv 的 --result-file 路径写 `{"status": <status>}`。
    corrupt_json ⇒ 写非法 JSON(验「解析失败走文本兜底」)。
    raise_exc ⇒ 直接抛(验超时/异常 fail-open)。
    """
    calls = calls if calls is not None else []

    def _run(cmd, *a, **k):
        calls.append(list(cmd))
        if raise_exc is not None:
            raise raise_exc
        if write_file and "--result-file" in cmd:
            p = Path(cmd[cmd.index("--result-file") + 1])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{not-json" if corrupt_json else json.dumps({"status": status}),
                         encoding="utf-8")
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=output)

    return types.SimpleNamespace(run=_run)


def _call(mid="a_fund_main", count=3):
    return rfm._notify_repeat_failure(mid, count, "20261028", "boom")


# ══════════════════════════════════════════════════════════════════════════════
# ⓪ 打桩生效自证(§18 L48)
# ══════════════════════════════════════════════════════════════════════════════
def test_00_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/x")  # noqa: S310
    _chk(trap.hits == ["urllib.request.urlopen"], f"trap 应计数 1, 实得 {trap.hits}")


# ══════════════════════════════════════════════════════════════════════════════
# A2-1 argv: 24h 去重 + 结构化结果文件
# ══════════════════════════════════════════════════════════════════════════════
def test_a2_argv_carries_dedup_key_and_result_file(monkeypatch):
    """notify 调用必须带 --dedup-key retry_failed_<mid> / --dedup-window 86400 / --result-file。"""
    calls = []
    monkeypatch.setattr(rfm, "subprocess", _shim_run("sent", calls=calls))
    with ZeroOutboundTrap() as trap:
        _call("a_fund_north_quarterly")
    _chk(len(calls) == 1, f"应调 notify 一次, got {len(calls)}")
    cmd = calls[0]
    _chk("--dedup-key" in cmd, "缺 --dedup-key(不传=完全不去重, notify.py:3283)")
    _chk(cmd[cmd.index("--dedup-key") + 1] == "retry_failed_a_fund_north_quarterly",
         f"dedup key 不符: {cmd[cmd.index('--dedup-key') + 1]!r}")
    _chk("--dedup-window" in cmd, "缺 --dedup-window")
    _chk(cmd[cmd.index("--dedup-window") + 1] == "86400",
         f"去重窗应为 86400s, got {cmd[cmd.index('--dedup-window') + 1]!r}")
    _chk("--result-file" in cmd, "缺 --result-file(结构化 status 判据)")
    rf = Path(cmd[cmd.index("--result-file") + 1])
    _chk(rf.name == "result.json" and not rf.exists(),
         f"结果文件应落在临时目录且调用后被清理: {rf}")
    _chk(not rf.parent.exists(), f"临时目录未清理: {rf.parent}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ══════════════════════════════════════════════════════════════════════════════
# A2-2 返回值语义: 已处置 vs 未处置
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status,expect", [
    ("sent", True),        # 真发出
    ("suppressed", True),  # 去重窗内主动抑制 = 已处置(关键: 不是失败)
    ("digested", True),    # 已并入当日摘要 buffer(23:25 交付) = 已处置
    ("failed", False),     # 全渠道未发出
    ("noop", False),       # 本轮无内容可发(保守 = 未处置)
    ("dry_run", False),    # 模拟(保守 = 未处置)
    ("weird", False),      # 未知态(保守)
])
def test_a2_disposed_status_matrix(monkeypatch, status, expect):
    """result-file status ⇒ 已处置真值表。"""
    monkeypatch.setattr(rfm, "subprocess", _shim_run(status))
    with ZeroOutboundTrap() as trap:
        got = _call()
    _chk(got is expect, f"status={status} 应返回 {expect}, got {got!r}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_a2_missing_result_file_falls_back_to_text_criterion(monkeypatch):
    """结果文件读不到 ⇒ 退回旧文本判据: 含「已发出」= 已处置, 全失败 = 未处置。"""
    for output, expect in ((SUCCESS_GENERAL, True), (FAIL_GENERAL, False)):
        monkeypatch.setattr(rfm, "subprocess", _shim_run(None, output=output, write_file=False))
        with ZeroOutboundTrap() as trap:
            got = _call()
        _chk(got is expect, f"兜底判据 output={output.strip()!r} 应返回 {expect}, got {got!r}")
        _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_a2_corrupt_result_file_falls_back_to_text(monkeypatch):
    """结果文件 JSON 损坏 ⇒ 文本兜底(不得崩、不得误判)。"""
    monkeypatch.setattr(rfm, "subprocess",
                        _shim_run("sent", output=SUCCESS_GENERAL, corrupt_json=True))
    _chk(_call() is True, "损坏 JSON + 已发出文本 ⇒ 应判已处置")
    monkeypatch.setattr(rfm, "subprocess",
                        _shim_run("sent", output=FAIL_GENERAL, corrupt_json=True))
    _chk(_call() is False, "损坏 JSON + 全失败文本 ⇒ 应判未处置")


def test_a2_exception_and_timeout_are_not_disposed(monkeypatch):
    """子进程抛异常 / 超时 ⇒ 未处置且不崩(fail-open: 下轮重试)。"""
    monkeypatch.setattr(rfm, "subprocess", _shim_run(raise_exc=RuntimeError("spawn failed")))
    _chk(_call() is False, "异常应判未处置")
    monkeypatch.setattr(rfm, "subprocess",
                        _shim_run(raise_exc=subprocess.TimeoutExpired("notify.py", 120)))
    _chk(_call() is False, "超时应判未处置")


def test_a2_result_file_parse_helper_edges(tmp_path):
    """_result_status: 缺失/非 dict/无 status ⇒ None(走兜底); 有 status ⇒ 原样返回。"""
    _chk(rfm._result_status(tmp_path / "nope.json") is None, "缺失文件应 None")
    p = tmp_path / "a.json"
    p.write_text("[]", encoding="utf-8")
    _chk(rfm._result_status(p) is None, "list JSON 应 None")
    p.write_text('{"status": ""}', encoding="utf-8")
    _chk(rfm._result_status(p) is None, "空 status 应 None")
    p.write_text('{"status": "suppressed"}', encoding="utf-8")
    _chk(rfm._result_status(p) == "suppressed", "应读到 suppressed")


# ══════════════════════════════════════════════════════════════════════════════
# A2-3 调用方联动: 已处置才清零, 未处置保留计数
# ══════════════════════════════════════════════════════════════════════════════
def _patch_main(monkeypatch, disposed, seed_counts):
    """打桩 main() 全部外部依赖; 只替换 _notify_repeat_failure 的返回(验清零门控)。"""
    state = dict(seed_counts)
    notify_calls = []

    monkeypatch.setattr(rfm, "is_trading_day", lambda d: True)
    monkeypatch.setattr(rfm, "load_config", lambda: {"metrics": []})
    monkeypatch.setattr(rfm, "get_failed_metrics",
                        lambda date: [{"metric_id": "a_fund_main", "message": "boom"}])
    monkeypatch.setattr(rfm, "retry_metric", lambda mid, date, cfg: (False, "boom"))
    monkeypatch.setattr(rfm, "_load_counts", lambda: dict(state))

    def _save(c):
        state.clear()
        state.update(c)

    monkeypatch.setattr(rfm, "_save_counts", _save)

    def _notify(mid, n, today, msg):
        notify_calls.append((mid, n))
        return disposed

    monkeypatch.setattr(rfm, "_notify_repeat_failure", _notify)
    return state, notify_calls


def test_a2_main_clears_only_when_disposed(monkeypatch):
    """已处置 ⇒ 清零; 未处置 ⇒ 保留并下轮重试(负控: 旧语义只在真发出时清零, 抑制时会反复直发)。"""
    state, calls = _patch_main(monkeypatch, False, {"a_fund_main": 2})
    with ZeroOutboundTrap() as trap:
        rfm.main()
    _chk(len(calls) == 1, f"达标应通知一次, got {calls}")
    _chk(state.get("a_fund_main") == 3, f"未处置必须保留计数(=3), got {state.get('a_fund_main')!r}")

    state, calls = _patch_main(monkeypatch, True, {"a_fund_main": 2})
    with ZeroOutboundTrap() as trap:
        rfm.main()
    _chk("a_fund_main" not in state, f"已处置后应清零, got {state!r}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_a2_main_notify_called_once_per_round_while_not_disposed(monkeypatch):
    """未处置连跑两轮: 每轮都重试(不静默丢告警)。"""
    state, calls = _patch_main(monkeypatch, False, {"a_fund_main": 2})
    rfm.main()
    rfm.main()
    _chk(len(calls) == 2, f"未处置应每轮重试(=2), got {len(calls)}")


def test_a2_source_shape_lock():
    """静态锁: 去重键/结果文件/已处置状态集/兜底判据都在源码里(§18 L49 防假绿)。"""
    src = Path(rfm.__file__).read_text(encoding="utf-8")
    _chk('"--dedup-key", f"retry_failed_{mid}", "--dedup-window", "86400"' in src, "缺 24h 去重参数")
    _chk("--result-file" in src, "缺 --result-file")
    _chk('_DISPOSED_STATUSES = frozenset({"sent", "suppressed", "digested"})' in src,
         "已处置状态集缺失/漂移")
    _chk("disposed = notify_sent(out)" in src, "缺文本兜底判据(不许丢掉旧防线)")
    _chk("shutil.rmtree(tmpdir, ignore_errors=True)" in src, "临时目录清理缺失")


# ══════════════════════════════════════════════════════════════════════════════
# A3: schedule_monitor.sh subject 带任务名(static-only 提取, 绝不 exec 业务主体)
# ══════════════════════════════════════════════════════════════════════════════
# 冻结基线: origin/main(08a8e5e74) 版 `_format_alert_item` 逐字摘录 —— 仅用于「正文一个字节
# 不改」的对照, 不参与生产逻辑。
_OLD_FORMAT_SRC = '''
def _format_alert_item(line):
    """B2: 单条 SEVERE 告警行 -> 4 行模板 HTML。"""
    _text = line[8:] if line.startswith("SEVERE: ") else line  # "SEVERE: "=8字符
    _first = _text.split(" ", 1)[0] if " " in _text else _text
    _task = _first
    if _first.startswith("com.trade."):
        _task = _first.replace("com.trade.", "").replace("-", "_")
    elif _first == "线上":
        _task = "overview"
    _impact = _IMPACT_MAP.get(_task, "对应任务数据可能过期或未更新, 前端可能读到旧数据")
    _sugg = _SUGGEST_MAP.get(_task, "自动恢复中; 若持续异常请人工介入检查")
    _log = _LOG_MAP.get(_task, str(MONITOR_LOG))
    _esc = lambda s: str(s).replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return (
        f"<b>[SEVERE] {_esc(_text)}</b><br>"
        f"影响: {_esc(_impact)}<br>"
        f"日志: {_esc(_log)}<br>"
        f"建议: {_esc(_sugg)}"
    )
'''


def _heredoc_src() -> str:
    src = SCHED.read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'[^\n]*\n(.*?)\nPYEOF\n", src, re.S)
    assert m, "schedule_monitor.sh 未找到 PYEOF heredoc"
    return m.group(1)


def _sm_ns() -> dict:
    """ast 提取 A3 相关纯函数 + 模板字典(不 exec 业务主体, §18 L50)。"""
    tree = ast.parse(_heredoc_src())
    keep = {"_task_name_of", "_task_names_of", "_sm_alert_subject", "_format_alert_item"}
    assigns = {"_IMPACT_MAP", "_SUGGEST_MAP"}
    body = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in keep:
            body.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in assigns for t in n.targets):
            body.append(n)
    ns: dict = {"_LOG_MAP": {}, "MONITOR_LOG": Path("/tmp/schedule_monitor.log")}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<sm-heredoc>", "exec"), ns)
    return ns


def _old_format_ns() -> dict:
    """冻结基线版 `_format_alert_item` + 同一套真实模板字典(对照用)。"""
    ns = _sm_ns()
    exec(compile(_OLD_FORMAT_SRC, "<sm-old>", "exec"), ns)
    return ns


SAMPLE_LINES = [
    "SEVERE: com.trade.lhb-daily 退出失败 last_exit=2",   # com.trade. + 连字符
    "SEVERE: futures_daily 停摆 >4h",                     # 普通任务名
    "线上 overview 滞后 20min",                            # 线上 -> overview
    "unknown_task 未知失败",                               # 未映射任务(默认影响/建议)
    "SEVERE: multi  double_space",                         # 多空格
    "no_space_line",                                       # 无空格(行尾 token)
]


def test_a3_task_name_normalization():
    """归一化规则: 剥 SEVERE 前缀; com.trade.<x> 且 -→_; 线上→overview; 未知原样。"""
    ns = _sm_ns()
    f = ns["_task_name_of"]
    _chk(f("SEVERE: com.trade.lhb-daily x") == "lhb_daily", f("com.trade 归一化错"))
    _chk(f("com.trade.fetch-news y") == "fetch_news", "无 SEVERE 前缀也应归一化")
    _chk(f("线上 overview 滞后") == "overview", "线上应归一化为 overview")
    _chk(f("futures_daily y") == "futures_daily", "普通任务名应原样")
    _chk(f("no_space") == "no_space", "无空格行应整行作名字")


def test_a3_subject_shows_task_names_sorted():
    """两个不同任务 ⇒ subject 两个名字都在, 且按字典序(乱序输入同结果)。"""
    ns = _sm_ns()
    subj = ns["_sm_alert_subject"](["SEVERE: com.trade.lhb_daily x", "SEVERE: futures_daily y"],
                                   "10-28 02:18")
    _chk("lhb_daily" in subj, f"缺 lhb_daily: {subj}")
    _chk("futures_daily" in subj, f"缺 futures_daily: {subj}")
    _chk("[futures_daily/lhb_daily]" in subj, f"应按字典序拼接: {subj}")
    _chk(subj.startswith("[告警] 2项计划任务异常"), f"前缀变了: {subj}")
    _chk(subj.endswith(" 10-28 02:18"), f"时间戳必须保留在末尾: {subj}")
    rev = ns["_sm_alert_subject"](["SEVERE: futures_daily y", "SEVERE: com.trade.lhb_daily x"],
                                  "10-28 02:18")
    _chk(rev == subj, f"乱序输入应得同一 subject:\n{subj}\n{rev}")


def test_a3_duplicate_names_deduped():
    """两条都是同一任务 ⇒ 只出现一次。"""
    ns = _sm_ns()
    subj = ns["_sm_alert_subject"](["SEVERE: com.trade.lhb_daily a", "SEVERE: lhb_daily b"],
                                   "10-28 02:18")
    _chk("[lhb_daily]" in subj, f"重复名应去重: {subj}")
    _chk(subj.count("lhb_daily") == 1, f"lhb_daily 出现次数应 1: {subj}")


def test_a3_线上_normalized_in_subject():
    """`线上` 行在 subject 里归一化成 overview。"""
    ns = _sm_ns()
    subj = ns["_sm_alert_subject"](["线上 overview 滞后"], "10-28 02:18")
    _chk("[overview]" in subj, f"应含 overview: {subj}")
    _chk("线上" not in subj, f"不应出现原始「线上」: {subj}")


def test_a3_truncation_5_long_names():
    """5 个长任务名 ⇒ 截断含「等」, 任务串 ≤60, 总 subject ≤120, 时间戳保留。"""
    ns = _sm_ns()
    names = [f"SEVERE: task_name_number_{i}_with_long_suffix x" for i in range(5)]
    subj = ns["_sm_alert_subject"](names, "10-28 02:18")
    _chk(len(subj) <= 120, f"总长应 ≤120, got {len(subj)}: {subj}")
    _chk("等5个" in subj, f"应含「等5个」: {subj}")
    _chk(subj.endswith(" 10-28 02:18"), f"时间戳必须保留: {subj}")
    inner = subj[subj.index("[") + 1:subj.rindex("]")]
    _chk(len(inner) <= 60, f"任务串应 ≤60, got {len(inner)}: {inner}")
    _chk(subj.count("/") <= 2, f"截断后应最多前 3 个: {subj}")


def test_a3_task_names_of_bounds():
    """_task_names_of 直接边界: 空列表 ⇒ ''; 单名超长 ⇒ 硬截 ≤60。"""
    ns = _sm_ns()
    f = ns["_task_names_of"]
    _chk(f([]) == "", "空列表应返回空串")
    _chk(f(["SEVERE: a x", "SEVERE: b y"]) == "a/b", "应按字典序 '/' 连接")
    long_name = "x" * 80
    out = f([f"SEVERE: {long_name} z"])
    _chk(len(out) <= 60, f"单名超长应硬截 ≤60, got {len(out)}")


def test_a3_body_bytes_unchanged():
    """反例硬约束: `_format_alert_item` 产出与改动前(冻结基线)逐字节一致。"""
    new = _sm_ns()["_format_alert_item"]
    old = _old_format_ns()["_format_alert_item"]
    for line in SAMPLE_LINES:
        _chk(new(line) == old(line), f"body 变了(逐字节不一致), line={line!r}")


def test_a3_source_shape_no_dedup_key():
    """A3 铁律: 主聚合告警不加 --dedup-key(会吞「同集合清了又复发」), body 变量仍在。"""
    src = SCHED.read_text(encoding="utf-8")
    _chk("_sm_alert_subject(alerts, _sm_time)" in src, "subject 未改用生成函数")
    _chk('body = "<br><br>".join(_format_alert_item(a) for a in alerts)' in src,
         "body 拼装行被改动(正文不在本单范围)")
    blk = src[src.index("_sm_alert_subject(alerts, _sm_time)"):]
    blk = blk[:blk.index("_main_out")]
    _chk("--dedup-key" not in blk, "主聚合 notify 不得加 --dedup-key")


def test_99_min_assertions():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}")