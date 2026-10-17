#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#264 包2 件C(故障域聚合)+ 件E(预算/摘要扩容) —— 10-15 真实告警流「前后逐条对照」重放器。

用途(§5.4⑦ 报告数字可独立复现 / RCA §4.2 要求「真实样本前后对照表」):
  把 data/alerts/alert_ledger.jsonl 的 **10-15 全天真实行**逐条喂回 notify.send(), 记录每条
  的判定(直发 / 被域层聚合 / 被 E 层并入 / 非告警群照发 / 台账自身跳过), 打印对照表与汇总。

零外发保证(§18 L48 / memory notify-script-selftest-must-stub):
  · 三个渠道函数(_send_email/send_telegram/send_feishu)全打桩为「只记录、返回 True」;
  · 外层 ZeroOutboundTrap 包裹最底层 urllib/smtplib 出口, 收尾断言 trap.hits == []
    (命中即非零退出 —— 说明沙箱被绕过, 本次重放结果不可采信);
  · 全部落盘面(台账/buffer/state/dedup/latest.md)重定向到临时目录, 绝不碰生产 data/。

时敏: 内部一律用**虚拟时钟**(同时替换 notify.datetime 与 adr.datetime), 故本脚本不写死
  「今天」, 任何日期跑结果一致(2026-10-15 虚拟日)。

跑法:
  python3 scripts/tests/repro_264_alert_domain_20261015.py            # 汇总 + 逐条对照表
  python3 scripts/tests/repro_264_alert_domain_20261015.py --csv      # 只出 CSV(便于粘报告)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(_HERE))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(_HERE.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402

FIXTURE = _HERE / "fixtures" / "alert_264_ledger_20261015.jsonl"
DAY = "2026-10-15"
FLUSH_HM = "23:30:00"

_VERDICT = {
    "direct": "直发",
    "domain": "被聚合(故障域)",
    "notice": "被抑制(E层超预算)",
    "rollover": "被抑制(跨日rollover)",
    "other_group": "照发(非告警群)",
    "digest_self": "跳过(台账自身/摘要行)",
}


class _Clock:
    def __init__(self, dtv):
        self.dtv = dtv


def _patch_clock(clock):
    for _m in (notify, adr):
        class _DT(datetime):  # noqa: N801
            @classmethod
            def now(cls, tz=None):
                return clock.dtv
        _m.datetime = _DT


def main() -> int:
    want_csv = "--csv" in sys.argv
    # 口径 = 10-15 **单日解剖**(RCA §1.4): 只重放该日行, 域状态/预算从 00:00 空态起算
    # (台账原件是 10-10~10-15 滚动窗, 整段重放会把前几日的 stale 条目混进当日摘要口径)。
    rows = [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("ts", "")[:10] == DAY]
    tmp = Path(tempfile.mkdtemp(prefix="repro264-"))
    alerts = tmp / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    os.environ["REPO"] = str(tmp)
    notify.REPO = tmp
    notify.ALERTS_DIR = alerts
    notify.ALERTS_FILE = alerts / "latest.md"
    notify.WARNING_BUFFER_FILE = alerts / "warning_buffer.jsonl"
    notify.INFO_LOG_FILE = alerts / "info_log.jsonl"
    notify.WARNING_DEDUP_STATE_FILE = alerts / "warning_dedup_state.json"
    notify.DEDUP_FILE = alerts / "notify_dedup.json"
    notify.ALERT_DIGEST_FILE = alerts / "alert_digest.jsonl"
    notify.ALERT_DIGEST_LOCK_FILE = alerts / "alert_digest.flushlock"
    notify.ALERT_DIGEST_STATE_FILE = alerts / "alert_digest_state.json"
    # 2026-10-17 补齐既存隔离缝(对齐 a182abf73/test_245 先例): 上面 9 个常量漏了 2 个锁常量,
    # 它们同为 **import 期**由 ALERTS_DIR 派生(notify.py:319)⇒ `_dedup_state_lock()` 的
    # `open(WARNING_DEDUP_LOCK_FILE,"a+")` 会 build 到**真实工作树** data/alerts/warning_dedup.lock
    # (实测: 本脚本跑完 rc=0「全绿」但真实树多出该文件)。
    notify.WARNING_DEDUP_LOCK_FILE = alerts / "warning_dedup.lock"
    notify.WARNING_FLUSH_LOCK_FILE = alerts / "warning_buffer.flushlock"
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: notify 落盘面泄漏到真实树 {_leak} ⇒ 会污染生产 data/alerts/"
    for _k in ("ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE", "ALERT_DOMAIN_DISABLE",
               "ALERT_NOTICE_BUDGET_DISABLE"):
        os.environ.pop(_k, None)

    _hits = []

    def _fake(kind):
        def _f(*_a, **_k):
            _hits.append(kind)
            return True
        return _f

    notify._send_email = _fake("email")
    notify.send_telegram = _fake("telegram")
    notify.send_feishu = _fake("feishu")

    clock = _Clock(datetime.strptime(f"{DAY} 00:00:00", "%Y-%m-%d %H:%M:%S"))
    _patch_clock(clock)
    # 层归因: 吞掉「哪一层并的」最可靠办法 = 记录 _absorb_to_digest 的 reason 实参
    # (域层=domain_inhibited / E层=notice_over_budget|rollover_digested / L2=over_budget)
    _last: dict = {}
    _orig_absorb = notify._absorb_to_digest

    def _absorb_spy(subject, body, **kw):
        _last["reason"] = str(kw.get("reason") or "over_budget")
        _last["domain"] = kw.get("domain")
        return _orig_absorb(subject, body, **kw)

    notify._absorb_to_digest = _absorb_spy
    _REASON2V = {adr.DOMAIN_ABSORB_REASON: "domain",
                 adr.NOTICE_OVER_BUDGET_REASON: "notice",
                 adr.ROLLOVER_ABSORB_REASON: "rollover"}
    out = []
    with ZeroOutboundTrap() as trap:
        for r in rows:
            clock.dtv = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
            if r.get("tier") == "digest":
                out.append((r, "digest_self", ""))
                continue
            if r.get("group") != "alert":
                out.append((r, "other_group", ""))
                continue
            _last.clear()
            res = notify.send(r["subject"], r["subject"],
                              severe=(r.get("tier") == "critical"),
                              ledger_key=r.get("key"), ledger_group="alert",
                              source=r.get("source"))
            if res.get("digested"):
                _rs = _last.get("reason") or "over_budget"
                out.append((r, _REASON2V.get(_rs, "notice"), _rs))
            else:
                out.append((r, "direct", ""))
        # 摘要出线一次(复现 23:25 摘要)
        clock.dtv = datetime.strptime(f"{DAY} {FLUSH_HM}", "%Y-%m-%d %H:%M:%S")
        cap = {}
        _real_send = notify.send

        def _rec(subject, body, **k):
            cap["subject"] = subject
            cap["body"] = body
            return {"email": True, "telegram": False, "feishu": True}

        notify.send = _rec
        fl = notify.flush_digest()
        notify.send = _real_send
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"

    # ── 汇总
    from collections import Counter
    cnt = Counter(v for _, v, _ in out)
    _alert_rows = [(r, v, z) for r, v, z in out if v not in ("other_group", "digest_self")]
    _r2 = [x for x in _alert_rows
           if adr.domain_of(x[0].get("key"), x[0]["subject"]) == "r2_deploy"
           and x[0]["ts"] >= f"{DAY} 18:00"]
    if not want_csv:
        print(f"# 10-15 重放对照(真实台账 {len(rows)} 行)")
        print(f"# 告警群行 {len(_alert_rows)} / 非告警群照发 {cnt['other_group']} "
              f"/ 台账自身跳过 {cnt['digest_self']}")
        for k, lab in _VERDICT.items():
            print(f"#   {lab:22s} {cnt.get(k, 0)}")
        print(f"# R2 故障域(18:00 后)域级外发 = {sum(1 for x in _r2 if x[1] == 'direct')} 条 "
              f"/ 域内总 {len(_r2)} 条")
        print(f"# 摘要: n={fl['n']} 标题={cap.get('subject')!r}")
        print("# ts|group|tier|key|verdict|reason|subject")
    for r, v, z in out:
        print("|".join([r["ts"], str(r.get("group")), str(r.get("tier")),
                        str(r.get("key")), _VERDICT.get(v, v), z,
                        str(r.get("subject"))[:80]]))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # `| head` 提前关管道
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(0)