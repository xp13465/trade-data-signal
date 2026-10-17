# -*- coding: utf-8 -*-
"""#231 H3 + 同模式 —— `upload_r2.py` 单文件命令失败改 rc=1 自验(2026-10-17)。

依据 = /tmp/231-h1-report.md §5(同模式静默清单)/§6(H3 提案)/§9。
  · H3:`cmd_upload`(原 L768-774)失败仅 `print ✗` 仍 exit 0 —— 全仓唯一「失败仍 rc=0」的
    单文件上传命令(兄弟 cmd_upload_decommissioned / cmd_upload_claude_backup 均 sys.exit)。
  · 同模式第 5 项:`cmd_delete`(原 L736-744)失败也静默 exit 0。
  · 改法:失败分支追加 `sys.exit(1)`,与兄弟命令对齐。

零真实上传铁律(§18 L48):本文件**不产生任何真实 R2 写/读** —— `upload_r2.s3_request`
  在 fixture 内整体打桩为「按用例给的 (status, data) 返回」的假函数;不触发网络、不读 .env
  凭证后的任何外发。落盘面:cmd_upload/cmd_delete 不写本地文件。

调用方契约(读 `app/collector/intraday_snapshot.py:2179-2180`):判成功 =
  `returncode == 0 and "✓" in stdout` —— 双信号。本文件断言改后**失败时两信号一致为「失败」**
  (rc≠0 且 stdout 无 ✓),成功时两信号一致为「成功」。

同模式未修记录(4 处 log_collect,详见 /tmp/pack2-p1-report.md §T2):
  runner.py:39 alert_notify / app/backfill.py:79 backfill_width / intraday_snapshot.py:1731
  a_amount_forecast / industry_extras.py:523,556 —— 均**非退出码点**,是采集链内 best-effort
  的 per-step/per-item 失败留痕,调用方依赖「不中断」(见 runner.py:356-365 聚合 into fail 计数),
  改 raise/exit 会破坏采集链 ⇒ 按派单「有依赖的跳过并记录」处置。

跑法: python3 -m pytest -q scripts/tests/test_231_h3_upload_exitcode_20261017.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import upload_r2  # noqa: E402

_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


@pytest.fixture(autouse=True)
def _stub_s3(monkeypatch):
    """打桩 s3_request —— 零真实 R2 交互。默认 200 空体, 用例内可覆盖。"""
    state = {"status": 200, "data": b"", "calls": []}

    def _fake(method, key, payload=None, **kw):
        state["calls"].append((method, key, payload, kw))
        return state["status"], state["data"]

    monkeypatch.setattr(upload_r2, "s3_request", _fake)
    yield state


# ══════════════════════ ① cmd_upload 失败 → rc=1(H3 核心) ══════════════════════
def test_01_cmd_upload_failure_exits_nonzero(_stub_s3, capsys, tmp_path):
    src = tmp_path / "x.json"
    src.write_text('{"a":1}', encoding="utf-8")
    _stub_s3["status"] = 403
    _stub_s3["data"] = b'{"error":"NotEntitled"}'
    with pytest.raises(SystemExit) as ei:
        upload_r2.cmd_upload(str(src), "data/x.json")
    _chk(ei.value.code == 1, f"失败应 rc=1, 得 {ei.value.code}")
    out = capsys.readouterr().out
    _chk("✓" not in out, "失败时 stdout 不应含 ✓(调用方双信号一致性)")
    _chk("✗" in out, f"失败应打印 ✗, 得 {out!r}")


def test_02_cmd_upload_success_no_exit(_stub_s3, capsys, tmp_path):
    src = tmp_path / "x.json"
    src.write_text('{"a":1}', encoding="utf-8")
    _stub_s3["status"] = 200
    upload_r2.cmd_upload(str(src), "data/x.json")  # 不应抛 SystemExit
    out = capsys.readouterr().out
    _chk("✓" in out, f"成功应打印 ✓, 得 {out!r}")
    _chk("✗" not in out, "成功不应含 ✗")


# ══════════════════════ ② cmd_delete 失败 → rc=1(同模式第 5 项) ══════════
def test_03_cmd_delete_failure_exits_nonzero(_stub_s3, capsys):
    _stub_s3["status"] = 403
    _stub_s3["data"] = b"denied"
    with pytest.raises(SystemExit) as ei:
        upload_r2.cmd_delete("backup/old.json")
    _chk(ei.value.code == 1, f"失败应 rc=1, 得 {ei.value.code}")
    out = capsys.readouterr().out
    _chk("✗" in out and "✓" not in out, f"stdout 应只含 ✗, 得 {out!r}")


def test_04_cmd_delete_success_no_exit(_stub_s3, capsys):
    _stub_s3["status"] = 204
    upload_r2.cmd_delete("backup/old.json")
    out = capsys.readouterr().out
    _chk("✓" in out, f"成功应打印 ✓, 得 {out!r}")


# ══════════════════════ ③ 调用方契约: 双信号一致(回归锚) ══════════════════════
def test_05_caller_contract_pattern_unchanged(_stub_s3, capsys, tmp_path):
    """复算调用方判定 `rc==0 and "✓" in stdout` 在改后仍把两种情形判对。"""
    src = tmp_path / "x.json"
    src.write_text("{}", encoding="utf-8")

    def _run():
        try:
            upload_r2.cmd_upload(str(src), "data/x.json")
            return 0
        except SystemExit as e:
            return e.code

    # 成功
    _stub_s3["status"] = 200
    rc = _run()
    out = capsys.readouterr().out
    _chk(rc == 0 and "✓" in out, f"成功判定应为 True: rc={rc} out={out!r}")
    # 失败
    _stub_s3["status"] = 500
    rc = _run()
    out = capsys.readouterr().out
    _chk(not (rc == 0 and "✓" in out), f"失败判定应为 False: rc={rc} out={out!r}")


def test_06_caller_source_uses_double_signal():
    """静态锚: 生产调用方仍用「rc==0 且 stdout 含 ✓」双信号(改了这里需同步本测试)。"""
    text = (ROOT / "app" / "collector" / "intraday_snapshot.py").read_text(encoding="utf-8")
    _chk('_r.returncode == 0 and "✓" in _r.stdout' in text,
         "调用方双信号判定已变更 ⇒ 需重新评估 H3 影响面")


# ══════════════════════ ④ 无 `if ! ... upload/delete` shell 链(影响面复算) ═════
def test_07_no_shell_ifbang_chain_for_bare_upload_or_delete():
    """全仓 *.sh 无 `if ! ... upload_r2.py {upload|delete}` 链(改 rc 后不会断定时链)。

    只盯**裸 `upload` / `delete`** 子命令(`upload-index`/`upload-intraday` 等 `upload-*`
    的 `if !` 链是既有设计, 不受本改影响)。"""
    import re
    bad = []
    for sh in sorted((ROOT / "scripts").glob("*.sh")):
        for ln in sh.read_text(encoding="utf-8", errors="replace").splitlines():
            if "upload_r2.py" not in ln:
                continue
            after = ln.split("upload_r2.py", 1)[1]
            # 去掉 $SKIP_OR_EMPTY / --flag 之类 token, 再取第一个子命令词
            toks = [t for t in after.split() if not t.startswith("-") and not t.startswith("$")]
            if not toks or toks[0] not in {"upload", "delete"}:
                continue
            if re.search(r"if\s+!", ln) or "||" in ln:
                bad.append(f"{sh.name}: {ln.strip()}")
    _chk(bad == [], f"发现裸 upload/delete 的 if ! / || 链(需核): {bad}")


# ══════════════════════ ⑤ 断言下限 ══════════════════════
def test_08z_assertion_floor():
    _chk(_N[0] >= 10, f"断言数应 >=10, 实得 {_N[0]}")