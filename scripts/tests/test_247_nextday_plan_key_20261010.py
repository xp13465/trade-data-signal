# -*- coding: utf-8 -*-
"""#247 nextday_plan py/sh dedup key 统一 —— 行为级正/负控自验(2026-10-10)。

病灶(见 docs/ops/245-batch2-impl-review-20261010.md §四 决策项 10):
  nextday_plan 链路在 R2 上传失败/超时/异常时, **同一事件秒级两封 SEVERE**:
    · py 侧 `scripts/nextday_plan_generator.py:_severe_alert`
      `--dedup-key nextday_plan_gen_fail`(带明细 stderr)后 `return 1`;
    · sh 侧 `scripts/nextday_plan.sh` RC!=0 → 无条件
      `--dedup-key nextday_plan_fail`(带「次日买入计划未生成」汇总, R2 失败时文案失真)。
  notify dedup 按 **key** 判 ⇒ 两键互不抑制 ⇒ 双发。

修法(同 #245 批2 B4-3 nextday_gap_check 先例, 统一方向 = py 改到 sh 的键):
  py `_severe_alert` 键 `nextday_plan_gen_fail` → `nextday_plan_fail`, 与包装层同键;
  py docstring 删「不同 key 不互吞=双保险」过时论证并写新语义; sh 段文案对齐 B4-3 风格。

本文件覆盖(逐条对验收口径):
  ① 静态机检: py `_severe_alert` 键 == sh 包装 `--dedup-key` == `nextday_plan_fail`(红先验核心);
  ② 行为: R2 失败场景 py 先发(带明细) → sh 同键窗内被抑制 ⇒ **只一封**;
  ③ 行为: py 未发(崩溃/超时/被杀) → sh 同键窗内无已发记录 ⇒ **照发兜底**(不断层);
  ④ 行为: 统一键窗口内互抑制(方向无关, sh→py 亦抑制);
  ⑤ 行为: 窗口过期后可再发(去重非永久);
  ⑥ 反向负控: 若键分歧(回归), 两键互不吞 ⇒ 两封 —— 证明 ②③ 断言有判别力(非同义反复);
  ⑦ 文案/文档静态: sh 段含新语义; py docstring 含「统一为 nextday_plan_fail」。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— 渠道函数(send_feishu / _send_email / send_telegram)
  在 fixture 内整体打桩为「只记录、返回 True」的假函数, 外层再套 `ZeroOutboundTrap`
  包裹最底层 urllib/smtplib 出口; 收尾断言 `trap.hits == []` 即「全程零真实外发」。
  所有落盘面(台账/latest.md/dedup/摘要)全指向 tmp_path, 绝不碰生产 data/。

红先验:GEN_PY / PLAN_SH 可用环境变量覆盖(默认指本仓 scripts/ 下真文件)。
  对 main 版跑(两键不同) → ①④(以及 ②「只一封」) 必失败; 对分支版跑 → 全绿。
  跑法见文件末复现段。

跑法: python3 -m pytest -q scripts/tests/test_247_nextday_plan_key_20261010.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
from notify_sent import notify_state  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
# 源文件路径(可用 env 覆盖, 供红先验对 main 版跑; 默认=本仓真文件)
GEN_PY = Path(os.environ.get("NEXTDAY_PLAN_GEN_PY", str(SCRIPTS / "nextday_plan_generator.py")))
PLAN_SH = Path(os.environ.get("NEXTDAY_PLAN_SH", str(SCRIPTS / "nextday_plan.sh")))

EXPECTED_KEY = "nextday_plan_fail"
OLD_PY_KEY = "nextday_plan_gen_fail"   # 修复前的 py 键(反例负控用)

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240/#245)
_MIN_ASSERTIONS = 18
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════════ 源文件静态提取(ast / 正则, 不 exec 业务脚本) ══════════════════════════
def _py_dedup_key(path: Path, func_name: str) -> str:
    """从 py 指定函数体内提取 `--dedup-key` 后紧跟的字面量(ast, 不 exec)。"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.List):
                    elts = sub.elts
                    for i, e in enumerate(elts):
                        if isinstance(e, ast.Constant) and e.value == "--dedup-key":
                            nxt = elts[i + 1] if i + 1 < len(elts) else None
                            if isinstance(nxt, ast.Constant) and isinstance(nxt.value, str):
                                return nxt.value
    raise AssertionError(f"未在 {path.name}:{func_name} 找到 --dedup-key 字面量")


def _sh_dedup_keys(path: Path) -> list[str]:
    """从 sh 提取全部 `--dedup-key <k>` 字面量(正则; 不执行脚本)。"""
    txt = Path(path).read_text(encoding="utf-8")
    return re.findall(r"--dedup-key\s+([^\s\\]+)", txt)


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


# ══════════════════════════ 两通道 notify 参数构造(复刻 py/sh 真实调用形态) ══════════════════════════
def _py_severe_args(key: str, log: str) -> list[str]:
    """复刻 py `_severe_alert` 的 notify.py 参数(键可换, 供统一/分歧两态驱动)。"""
    subject = "[告警] 次日买入计划 R2 上传失败 rc=1 20261010"
    body = ("nextday_plan_generator.py: R2 upload-data-files 退出码 1, "
            "次日买入计划本地已落盘但 R2 未同步(线上 sss/s 备站可能滞后)。")
    return [subject, body, "--severe", "--from-prefix", "[告警]",
            "--alert-issue", subject, "--alert-log", log,
            "--dedup-key", key, "--dedup-window", "3600"]


def _sh_severe_args(key: str, log: str) -> list[str]:
    """复刻 nextday_plan.sh RC!=0 段的 notify.py 参数。"""
    subject = "[告警] 次日买入计划生成失败 10-10 22:31"
    body = ("nextday_plan_generator.py 退出码 1, 次日买入计划未生成。"
            "<br>本条为包装层兜底(py 同 dedup key: py 已发时本条被抑制; py 未发时本条兜底)。")
    return [subject, body, "--severe", "--from-prefix", "[告警]",
            "--alert-issue", "次日买入计划生成失败", "--alert-log", log,
            "--dedup-key", key, "--dedup-window", "3600"]


def _read_state(iso) -> dict:
    import json
    p = iso["alerts"] / "notify_dedup.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ══════════════════════════ ① 静态机检: py/sh 键统一(红先验核心) ══════════════════════════
def test_01_py_sh_key_parity():
    py_key = _py_dedup_key(GEN_PY, "_severe_alert")
    sh_keys = _sh_dedup_keys(PLAN_SH)
    _chk(sh_keys == [EXPECTED_KEY], f"sh --dedup-key 应唯一={EXPECTED_KEY}, 实={sh_keys}")
    _chk(py_key == EXPECTED_KEY, f"py _severe_alert 键应={EXPECTED_KEY}, 实={py_key}")
    _chk(py_key == sh_keys[0],
         f"py/sh dedup key 必须统一(否则同一事件双发): py={py_key} vs sh={sh_keys[0]}")
    _chk(OLD_PY_KEY != py_key, "修复前的 py 键不得残留(且应与统一键不同)")


# ══════════════════════════ ② R2 失败场景: py 先发 → sh 同键被抑制 = 只一封 ══════════════════════════
def test_02_r2_fail_only_one_mail(_iso, capsys):
    py_key = _py_dedup_key(GEN_PY, "_severe_alert")
    sh_key = _sh_dedup_keys(PLAN_SH)[0]
    log = str(_iso["tmp"] / "nextday_plan_launchd.log")

    rc1 = notify.main(_py_severe_args(py_key, log))
    out1 = capsys.readouterr()
    _chk(rc1 == 0, "notify 契约 rc 恒 0")
    _chk(notify_state(out1.err + out1.out) == "sent", "py 侧(带明细)应先真发出")
    n1 = len(_iso["calls"])
    _chk(n1 > 0, "py 侧应有真实渠道调用")
    _chk(py_key in _read_state(_iso), "py 侧发出后应占统一键窗")

    rc2 = notify.main(_sh_severe_args(sh_key, log))
    out2 = capsys.readouterr()
    _chk(rc2 == 0, "notify 契约 rc 恒 0")
    _chk(notify_state(out2.err + out2.out) == "suppressed",
         "sh 侧应被同键窗内抑制(不再双发)")
    _chk(len(_iso["calls"]) == n1,
         f"第二次不得再发渠道(实 {len(_iso['calls'])} vs {n1}) ⇒ 同一事件只一封")


# ══════════════════════════ ③ py 未发(崩溃/超时) → sh 兜底照发 ══════════════════════════
def test_03_sh_fallback_when_py_silent(_iso, capsys):
    sh_key = _sh_dedup_keys(PLAN_SH)[0]
    log = str(_iso["tmp"] / "nextday_plan_launchd.log")
    rc = notify.main(_sh_severe_args(sh_key, log))
    out = capsys.readouterr()
    _chk(rc == 0, "notify 契约 rc 恒 0")
    _chk(notify_state(out.err + out.out) == "sent",
         "py 未发时(窗内无已发记录) sh 应照发兜底")
    _chk(len(_iso["calls"]) > 0, "sh 兜底应真发(兜底不断层)")


# ══════════════════════════ ④ 统一键窗口内互抑制(方向无关) ══════════════════════════
def test_04_mutual_suppress_sh_then_py(_iso, capsys):
    py_key = _py_dedup_key(GEN_PY, "_severe_alert")
    sh_key = _sh_dedup_keys(PLAN_SH)[0]
    log = str(_iso["tmp"] / "nextday_plan_launchd.log")
    # 先 sh 后 py(实际时序为 py 先, 此为正反方向对称验证: 同键 ⇒ 双向互抑制)
    notify.main(_sh_severe_args(sh_key, log))
    out1 = capsys.readouterr()
    _chk(notify_state(out1.err + out1.out) == "sent", "sh 先发")
    n1 = len(_iso["calls"])
    notify.main(_py_severe_args(py_key, log))
    out2 = capsys.readouterr()
    _chk(notify_state(out2.err + out2.out) == "suppressed", "py 后发应被同键抑制")
    _chk(len(_iso["calls"]) == n1, "后发者不得再发渠道 ⇒ 单向事件仍只一封")


def test_05_window_expiry_allows_resend(_iso, capsys):
    """窗口过期后可再发(去重非永久)。"""
    import json
    sh_key = _sh_dedup_keys(PLAN_SH)[0]
    log = str(_iso["tmp"] / "nextday_plan_launchd.log")
    notify.main(_sh_severe_args(sh_key, log))
    capsys.readouterr()
    # 手动把 last_alerted 改到窗口(3600s)之外
    p = _iso["alerts"] / "notify_dedup.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    st[sh_key] = {"last_alerted": "2020-01-01 00:00:00"}
    p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    n1 = len(_iso["calls"])
    notify.main(_sh_severe_args(sh_key, log))
    out = capsys.readouterr()
    _chk(notify_state(out.err + out.out) == "sent", "窗口过期后应可再发")
    _chk(len(_iso["calls"]) > n1, "过期后真发渠道")


# ══════════════════════════ ⑥ 反向负控: 键分歧 ⇒ 双发(证明 ②③ 断言有判别力) ══════════════════════════
def test_06_divergent_keys_double_send_negative_control(_iso, capsys):
    log = str(_iso["tmp"] / "nextday_plan_launchd.log")
    notify.main(_py_severe_args(OLD_PY_KEY, log))       # 修复前 py 键
    out1 = capsys.readouterr()
    n1 = len(_iso["calls"])
    _chk(notify_state(out1.err + out1.out) == "sent", "键 A(py 旧键)发出")
    notify.main(_sh_severe_args(EXPECTED_KEY, log))     # sh 键
    out2 = capsys.readouterr()
    n2 = len(_iso["calls"])
    _chk(notify_state(out2.err + out2.out) == "sent", "键 B(sh 键)亦发出(不同键不互吞)")
    _chk(n2 > n1, "键分歧时应双发 ⇒ 负控证明统一后的「只一封」断言有判别力")


# ══════════════════════════ ⑦ 文案/文档静态对齐 ══════════════════════════
def test_07_text_alignment_static():
    sh_txt = PLAN_SH.read_text(encoding="utf-8")
    _chk("py 同 dedup key" in sh_txt,
         "sh 段文案应对齐 B4-3 风格(写明 py 已发被抑制 / py 未发兜底)")
    py_txt = GEN_PY.read_text(encoding="utf-8")
    _chk("统一为 nextday_plan_fail" in py_txt,
         "py docstring 应写明新语义(键统一为 nextday_plan_fail)")
    _chk("已废止" in py_txt, "py docstring 应标注旧「不同 key 不互吞」论证已废止")


# ══════════════════════════ 断言下限兜底(防假绿) ══════════════════════════
def test_zz_assertion_floor():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑收集/执行异常)")