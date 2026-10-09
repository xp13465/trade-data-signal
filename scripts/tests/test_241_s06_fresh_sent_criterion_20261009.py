# -*- coding: utf-8 -*-
"""#241 `check_s06_freshness.py` 落签判据同病根(rc 当 sent)—— pytest 自验(2026-10-09)。

病灶: `scripts/check_s06_freshness.py` 旧判据 `sent_ok = proc.returncode == 0`。
`notify.py` 的 `main()` **所有出口恒 return 0** —— 含通用路径「全部渠道未发出」
(notify.py:2371)与 `--tier` 分支 `defer_status='append_failed'`(notify.py:2190)⇒
**通知全失败也 rc=0** ⇒ 若按 rc 落签 ⇒ 该 S06 快照过期告警被后续轮次抑制 = **静默丢失**。
修 = 判 notify.py 子进程输出的**真实路由结果**(唯一实现 `scripts/notify_sent.py`,
与 `check_failed_units` #240 F1 **同一判据**), fail-safe(判不出 ⇒ 不落签 ⇒ 下轮重试)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— e2e 用例 monkeypatch `check_s06_freshness.subprocess.run`
  (notify 子进程整体打桩, 根本不 spawn)+ `ZeroOutboundTrap` 包裹; `test_00` 先证 trap 武装生效。

red-before-green(判别力证明, 见 docs/ops/check-s06-sent-criterion-fix-20261009.md):
  `_run_main` 可用 `sent_fn` 切换判据 —— test_03 用**真判据**(全渠道失败 ⇒ 期望不落签),
  test_04 用**旧 rc 语义**(恒 True, 复现 bug ⇒ 落签)。旧代码跑 test_03 必 FAIL。

跑法: python3 -m pytest -q scripts/tests/test_241_s06_fresh_sent_criterion_20261009.py
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_failed_units as cfu  # noqa: E402
import check_s06_freshness as csf  # noqa: E402
from notify_sent import notify_sent  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240)
_MIN_ASSERTIONS = 40
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── notify.py 真实输出形态(逐字照 notify.py 打点行, 用于判据判别力) ──
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"
ESC_OK = "[notify][196] 升级档路由完成：{'email': True, 'feishu': True}\n"
ESC_FAIL = "[notify][196] 升级档路由完成：{'email': False, 'feishu': False}\n"
# --tier warning 三态(notify.py:2190 res dict + defer_warning 打点行)
TIER_ENQUEUED = ("[notify][warning] 入聚合 buffer（30min 批发）：S06 快照过期 3 日\n"
                 "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                 "'telegram': False, 'feishu': False, 'deferred': True, "
                 "'defer_status': 'enqueued'}\n")
TIER_SUPPRESSED = ("[notify][dedup] 同源抑制(窗口内第 2 次，已通知 1 次，4h 窗)：S06 快照过期 3 日\n"
                   "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                   "'telegram': False, 'feishu': False, 'deferred': True, "
                   "'defer_status': 'suppressed'}\n")
TIER_APPEND_FAILED = ("[notify][warning] buffer 追加失败（未入队，不占窗，后续同源继续尝试）：S06 快照过期 3 日\n"
                      "[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, "
                      "'telegram': False, 'feishu': False, 'deferred': False, "
                      "'defer_status': 'append_failed'}\n")


# ══════════════════════ ⓪ 打桩生效自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数(hits==1)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/")  # noqa: S310 (打桩验证, 必抛)
    _chk(trap.hits == ["urllib.request.urlopen"], f"trap 应计数 1, 实得 {trap.hits}")


# ══════════════════════ ① 判据判别力(单元) ══════════════════════
@pytest.mark.parametrize("out,exp,why", [
    (SUCCESS_GENERAL, True, "#240 通用成功"),
    (FAIL_GENERAL, False, "#240 通用全败 → 不算发出"),
    (ESC_OK, True, "#240 #196③ 升级档成功"),
    (ESC_FAIL, False, "#240 #196③ 升级档全败"),
    (TIER_ENQUEUED, True, "#241 --tier warning 真入聚合 buffer"),
    (TIER_SUPPRESSED, True, "#241 --tier warning 真抑制(已处理)"),
    (TIER_APPEND_FAILED, False, "#241 --tier warning buffer 追加失败 → 不得当发出"),
    ("", False, "无输出 → fail-safe 不落签"),
    ("[notify][warning][dry-run] 模拟入聚合 buffer（不写盘）：X", False, "dry-run → 不落签"),
    ("未知形态 output", False, "未知形态 → fail-safe 不落签"),
])
def test_01_notify_sent_parser(out, exp, why):
    """F1/#241 判据: rc 不参与, 只认输出里的真实路由结果; 未知 → 保守 False。"""
    _chk(notify_sent(out) is exp, f"{why}: 期望 {exp}, 实得 {notify_sent(out)}")


def test_02_cfu_wrapper_delegates_to_shared():
    """#240 已验收的 `cfu._notify_sent` 委托唯一实现(符号保留, 行为不变)。"""
    for out in (SUCCESS_GENERAL, FAIL_GENERAL, ESC_OK, ESC_FAIL, TIER_ENQUEUED, TIER_APPEND_FAILED, ""):
        _chk(cfu._notify_sent(out) == notify_sent(out), f"wrapper 应与共享实现一致: {out!r}")


def test_02b_source_uses_shared_criterion_not_rc():
    """静态锁: check_s06_freshness.py 不得再出现 `returncode == 0` 当 sent, 且用 notify_sent。"""
    src = (SCRIPTS / "check_s06_freshness.py").read_text(encoding="utf-8")
    _chk("returncode == 0" not in src, "#241 不得再用 rc==0 当落签判据")
    _chk("sent_ok = notify_sent(" in src, "#241 落签判据应为 notify_sent(...)")
    _chk("from notify_sent import notify_sent" in src, "#241 应复用唯一实现")


# ══════════════════════ ② e2e(打桩 notify 子进程) ══════════════════════
def _mk_fixtures(tmp: Path) -> tuple[str, str]:
    """构造「S06 快照过期 3 个交易日」样本: index 末日期 - coverage_end = 3 (>1 触发)。"""
    idx = tmp / "csi1000-all.json"
    idx.write_text(json.dumps({"ohlc": [{"date": d} for d in
                                        ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]]}),
                   encoding="utf-8")
    snap = tmp / "kelly_mode_s06_state.json"
    snap.write_text(json.dumps({"daily": [{"date": "2026-09-01"}],
                                "generated_at": "2026-09-01 20:35:00"}), encoding="utf-8")
    return str(snap), str(idx)


def _run_main(monkeypatch, tmp: Path, notify_out: str, rc: int = 0, sent_fn=None):
    """跑 csf.main()(--notify); notify 子进程整体打桩, 全程零真实 spawn/外发。

    sent_fn 非 None 时 monkeypatch `csf.notify_sent`(用于 red-before-green 切换判据;
    不传则用真判据)。返回 (main_rc, notify 调用次数, 捕获输出)。
    """
    snap, idx = _mk_fixtures(tmp)
    calls = []

    def _fake_run(cmd, *a, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=notify_out)

    monkeypatch.setattr(csf.subprocess, "run", _fake_run)
    if sent_fn is not None:
        monkeypatch.setattr(csf, "notify_sent", sent_fn)
    monkeypatch.setattr(sys, "argv", [
        "check_s06_freshness.py", "--repo", str(tmp),
        "--snap", snap, "--index", idx, "--notify"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        main_rc = csf.main()
    return main_rc, len(calls), buf.getvalue()


def _state_file(tmp: Path) -> Path:
    return tmp / "data" / "s06_fresh_alert_state.json"


def test_03_negative_control_all_channels_failed_no_consign_and_retries(monkeypatch, tmp_path):
    """负控(必修): notify **全渠道失败 / append_failed** ⇒ **不得落签** ⇒ 下轮重试。

    旧代码(rc==0)在 notify 恒 return 0 下会落签 ⇒ 下轮被抑制 = 真告警丢失;
    本用例在旧代码上必 FAIL(red-before-green 判别力证据, 见报告)。
    """
    with ZeroOutboundTrap() as trap:
        rc1, n1, out1 = _run_main(monkeypatch, tmp_path, FAIL_GENERAL)
        _chk(rc1 == 1, f"过期应 rc=1, 实得 {rc1}")           # 判定仍出来(告警确实该报)
        _chk(n1 == 1, f"应尝试 notify 1 次, 实得 {n1}")
        _chk(not _state_file(tmp_path).exists(), "全渠道失败**不得**落签状态文件")
        _chk("未真发出" in out1, f"应响亮报「未真发出」, out={out1[-200:]}")

        # 下轮同一状态仍过期: 因未落签 ⇒ 必须**再次**尝试 notify(不吞真告警)
        rc2, n2, out2 = _run_main(monkeypatch, tmp_path, FAIL_GENERAL)
        _chk(rc2 == 1 and n2 == 1, f"未落签 ⇒ 下轮必须重试 notify, 实得 rc={rc2} n={n2}")
        _chk(not _state_file(tmp_path).exists(), "重试轮仍不得落签")
        _chk("同状态已成功告警过" not in out2, "未落签不得走抑制分支")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_03b_negative_control_append_failed_tier(monkeypatch, tmp_path):
    """负控 2: --tier warning 的 buffer 追加失败(append_failed, rc=0)同样**不得落签**。"""
    with ZeroOutboundTrap() as trap:
        _, n1, out1 = _run_main(monkeypatch, tmp_path, TIER_APPEND_FAILED)
        _chk(n1 == 1, f"应尝试 notify 1 次, 实得 {n1}")
        _chk(not _state_file(tmp_path).exists(), "append_failed 不得落签")
        _chk("未真发出" in out1, f"应报未真发出, out={out1[-200:]}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_04_positive_control_enqueued_consigns_and_suppresses(monkeypatch, tmp_path):
    """正控: notify 真入聚合 buffer(deferred=True)⇒ 落签 ⇒ 下轮同状态被抑制(不重发)。"""
    with ZeroOutboundTrap() as trap:
        rc1, n1, _ = _run_main(monkeypatch, tmp_path, TIER_ENQUEUED)
        st = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        _chk(rc1 == 1 and n1 == 1, f"首报应发 1 次, rc={rc1} n={n1}")
        _chk(st.get("coverage_end") == "2026-09-01" and st.get("n") == 3,
             f"落签内容应含 (coverage_end, n), 实得 {st}")

        # 同状态再跑: 已成功告警过 ⇒ 抑制重复(不再调 notify)
        rc2, n2, out2 = _run_main(monkeypatch, tmp_path, TIER_ENQUEUED)
        _chk(rc2 == 1 and n2 == 0, f"同状态应抑制重发, 实得 rc={rc2} n={n2}")
        _chk("同状态已成功告警过" in out2, f"应走抑制分支, out={out2[-200:]}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_04b_positive_control_suppressed_tier_consigns(monkeypatch, tmp_path):
    """正控 2: --tier warning 真抑制(deferred=True)也算已处理 ⇒ 落签。"""
    with ZeroOutboundTrap() as trap:
        _, n1, _ = _run_main(monkeypatch, tmp_path, TIER_SUPPRESSED)
        _chk(n1 == 1 and _state_file(tmp_path).exists(), "真抑制应落签")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_05_red_before_green_old_rc_semantics_would_consign(monkeypatch, tmp_path):
    """red-before-green 证据: 用**旧 rc 语义**(notify 恒 return 0 ⇒ 判 True)跑同一负控场景,
    复现 bug —— 全渠道失败却落签 ⇒ 下轮被抑制。

    证明 test_03 有判别力: 判据从 rc 换成 notify_sent 才让 test_03 PASS。
    (notify.py 所有出口 rc=0, 故旧判据在本 case 恒 True, 与 `lambda out: True` 等价。)
    """
    with ZeroOutboundTrap() as trap:
        rc1, n1, _ = _run_main(monkeypatch, tmp_path, FAIL_GENERAL, sent_fn=lambda out: True)
        _chk(rc1 == 1 and n1 == 1, f"首报应发 1 次, rc={rc1} n={n1}")
        _chk(_state_file(tmp_path).exists(),
             "旧 rc 语义(恒 True)在全渠道失败时**会**落签 —— 复现 #241 bug")
        rc2, n2, out2 = _run_main(monkeypatch, tmp_path, FAIL_GENERAL, sent_fn=lambda out: True)
        _chk(rc2 == 1 and n2 == 0, f"旧语义下同状态被抑制(真告警丢失), 实得 rc={rc2} n={n2}")
        _chk("同状态已成功告警过" in out2, "旧语义下走抑制分支=吞真告警")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")