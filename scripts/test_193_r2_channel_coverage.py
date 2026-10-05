#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#193 R2 通道覆盖缺口根治 —— 自验脚本(2026-10-05)。

覆盖三类断言:
  [A] 通道登记: _R2_CHANNELS 含 offshore-fund / fund-score / news-digest 三新通道,
      且 r2_prefix / patterns / state_name 与上传命令口径逐字一致。
  [B] 可对账集: _reconcilable_keys_for 现在纳入 fund_score/ · offshore_fund/ · data/news_digest/ 键,
      feed.xml 仍为死键(非 .json, 由 upload-feed 轻量校验覆盖)。
  [C] verify-r2 覆盖: 平日 + 周日两种模式下, 三新通道的文件都进入对账集(state_name=None 不崩、
      平日靠全池抽样兜底; news_digest 归档键经独立链台账确定性纳入)。
  [D] 失败 loud: upload 失败时 _notify_channel_upload_fail 发 severe 告警(notify 已打桩, 见下)。

⚠️ §18 L48 / memory notify-script-selftest-must-stub: 本脚本把 sys.modules['notify'] 换成 Fake,
   并给真实 notify.send 挂陷阱函数 —— 一旦真模块被触达立即 AssertionError。本脚本零真实外发、
   零真实 R2 PUT/HEAD(s3_head / _upload_glob 均打桩)。

运行: python3 scripts/test_193_r2_channel_coverage.py   (任一 cwd 均可)
复现: cd <worktree> && python3 scripts/test_193_r2_channel_coverage.py
"""
import sys
import types
import shutil
import hashlib
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import upload_r2 as ur  # noqa: E402

PASS = 0
FAIL = 0


def _ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {msg}")
    else:
        FAIL += 1
        print(f"  FAIL  {msg}")


def _mk_temp_tree():
    """建临时 static-site/data 树(含三新通道文件 + feed.xml + 独立链台账)。"""
    root = Path(tempfile.mkdtemp(prefix="test193-"))
    sd = root / "static-site"
    data = sd / "data"
    (data / "news_digest" / "2026").mkdir(parents=True)
    (data / "fund_score.json").write_text('{"k":1}', encoding="utf-8")
    (data / "fund_score_top.json").write_text('{"k":2}', encoding="utf-8")
    (data / "offshore_fund_basic.json").write_text('{"k":3}', encoding="utf-8")
    (data / "news_digest" / "_index.json").write_text('{"k":4}', encoding="utf-8")
    (data / "news_digest" / "2026" / "2026-10-01.json").write_text('{"k":5}', encoding="utf-8")
    (data / "feed.xml").write_text("<rss/>", encoding="utf-8")
    # 独立链台账(与 _standalone_keys_path 同构: STATIC_DIR.parent/data)
    ledger = root / "data" / ".r2_standalone_keys.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('["data/news_digest/2026/2026-10-01.json", "data/news_digest/_index.json"]',
                      encoding="utf-8")
    return root, sd


def _install_notify_stub():
    """替换 sys.modules['notify'] 为 Fake; 真实 notify.send 挂陷阱(证打桩生效)。"""
    import notify as real_notify
    trap = []

    def _trap(*a, **k):
        trap.append((a, k))
        raise AssertionError("真实 notify.send 被触达 = 打桩失效(§L48)!")

    real_notify.send = _trap  # 兜底: 任何漏网的真实调用立刻炸

    calls = []
    fake = types.ModuleType("notify")

    def _send(subject, body, **kw):
        calls.append(("send", subject, dict(kw)))

    def _check_dedup(key, window):
        return False  # 未发过 -> 允许发

    def _update_dedup(key):
        calls.append(("update_dedup", key))

    fake.send = _send
    fake.check_dedup = _check_dedup
    fake.update_dedup = _update_dedup
    prev = sys.modules.get("notify")
    sys.modules["notify"] = fake
    print(f"  [stub] sys.modules['notify'] 已替换为 Fake(prev={'real' if prev is real_notify else prev}); "
          f"真实 send 陷阱已挂 -> 本次自测零真实外发")
    return calls, trap


def main():
    global ur
    print("== [A] 通道登记 ==")
    by_label = {c["label"]: c for c in ur._R2_CHANNELS}
    for lbl, pfx, pats in (("offshore-fund", "offshore_fund", ["offshore_fund*.json"]),
                           ("fund-score", "fund_score", ["fund_score*.json"]),
                           ("news-digest", "data/news_digest", ["*.json", "*/*.json"])):
        ch = by_label.get(lbl)
        _ok(ch is not None, f"{lbl} 通道已登记")
        if ch:
            _ok(ch["r2_prefix"] == pfx, f"{lbl}.r2_prefix == {pfx}(与 cmd_upload_* 实参一致)")
            _ok(ch["patterns"] == pats, f"{lbl}.patterns == {pats}")
            _ok(ch.get("state_name") is None, f"{lbl}.state_name is None(上传走 _upload_glob, 无增量状态)")

    root, sd = _mk_temp_tree()
    old_static = ur.STATIC_DIR
    ur.STATIC_DIR = sd
    try:
        print("== [B] 可对账集(_reconcilable_keys_for) ==")
        keys = {
            "fund_score/fund_score.json", "fund_score/fund_score_top.json",
            "offshore_fund/offshore_fund_basic.json",
            "data/news_digest/2026/2026-10-01.json", "data/news_digest/_index.json",
            "data/feed.xml",
        }
        rec = ur._reconcilable_keys_for(keys)
        for k in ("fund_score/fund_score.json", "offshore_fund/offshore_fund_basic.json",
                  "data/news_digest/2026/2026-10-01.json", "data/news_digest/_index.json"):
            _ok(k in rec, f"可对账: {k}")
        _ok("data/feed.xml" not in rec, "feed.xml 仍为死键(非 .json, 由 upload-feed 轻量校验覆盖)")

        print("== [B2] _channel_files 口径 ==")
        for lbl, want in (("fund-score", {"fund_score/fund_score.json", "fund_score/fund_score_top.json"}),
                          ("offshore-fund", {"offshore_fund/offshore_fund_basic.json"}),
                          ("news-digest", {"data/news_digest/_index.json",
                                           "data/news_digest/2026/2026-10-01.json"})):
            ch = by_label[lbl]
            ld = ch["local_dir"]()
            got = {ur._channel_key(ch, f, ld) for f in ur._channel_files(ch, ld)}
            _ok(got == want, f"{lbl} _channel_files keys == {sorted(want)}  (实得 {sorted(got)})")

        print("== [C] verify-r2 覆盖(平日 + 周日; s3_head 打桩, 零真实 R2) ==")
        # key -> 本地 md5 映射, 供 s3_head 桩返回一致 ETag
        key_md5 = {}
        for lbl in ("fund-score", "offshore-fund", "news-digest", "all-data"):
            ch = by_label[lbl]
            ld = ch["local_dir"]()
            for f in ur._channel_files(ch, ld):
                key_md5[ur._channel_key(ch, f, ld)] = hashlib.md5(f.read_bytes()).hexdigest()
        checked = []

        def _fake_s3_head(key, bucket=None, keep_alive=False, with_len=False):
            checked.append(key)
            if with_len:
                return (200, None, None)
            return (200, key_md5.get(key))

        old_head, old_datetime = ur.s3_head, ur.datetime
        ur.s3_head = _fake_s3_head
        import datetime as _dt

        class _FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 7)  # 2026-10-07 = 周三 -> 平日模式

        ur.datetime = types.SimpleNamespace(date=_FakeDate)
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                ur.cmd_verify_r2()
        finally:
            ur.datetime = old_datetime
            ur.s3_head = old_head
        _ok("fund_score/fund_score.json" in checked, "平日: fund_score 通道被对账(state_name=None 不崩)")
        _ok("offshore_fund/offshore_fund_basic.json" in checked, "平日: offshore_fund 通道被对账")
        _ok("data/news_digest/2026/2026-10-01.json" in checked, "平日: news_digest 归档键被对账(抽样/台账)")

        # 周日全量
        checked.clear()

        class _FakeSunday(_dt.date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 11)  # 2026-10-11 = 周日 -> 全量模式

        ur.s3_head = _fake_s3_head
        ur.datetime = types.SimpleNamespace(date=_FakeSunday)
        buf2 = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf2), contextlib.redirect_stderr(buf2):
                ur.cmd_verify_r2()
        finally:
            ur.datetime = old_datetime
            ur.s3_head = old_head
        _ok("fund_score/fund_score_top.json" in checked, "周日全量: fund_score 全覆盖")
        _ok("data/news_digest/2026/2026-10-01.json" in checked, "周日全量: news_digest 归档全覆盖")
        _ok("data/feed.xml" not in checked, "feed.xml 不被通道误扫")

        print("== [D] 失败 loud(notify 打桩) ==")
        calls, trap = _install_notify_stub()
        # D1: 直接调 helper
        ur._notify_channel_upload_fail("fund-score", "upload-fund-score",
                                       "fund_score", 1, 2, ["fund_score_top.json"])
        _ok(len(calls) >= 1 and calls[0][0] == "send", "helper 发 1 条告警")
        subj = calls[0][1] if calls else ""
        _ok("fund-score" in subj and "1/2" in subj, f"告警标题含通道+计数: {subj!r}")
        _ok(calls[0][2].get("severe") is True, "告警 severe=True")

        # D2: cmd_upload_fund_score 失败路径 -> 发告警 + exit 1
        calls.clear()
        old_glob = ur._upload_glob
        ur._upload_glob = lambda *a, **k: (1, 2, ["fund_score_top.json"], ["fund_score/fund_score.json"])
        rc = None
        try:
            ur.cmd_upload_fund_score()
        except SystemExit as e:
            rc = e.code
        finally:
            ur._upload_glob = old_glob
        _ok(rc == 1, f"cmd_upload_fund_score 失败 exit 1(实得 {rc})")
        _ok(any(c[0] == "send" for c in calls), "cmd 失败路径已发告警")

        # D3: 成功路径 -> 不告警
        calls.clear()
        ur._upload_glob = lambda *a, **k: (2, 2, [], ["fund_score/fund_score.json", "fund_score/fund_score_top.json"])
        ur.purge_cache = lambda *a, **k: None
        try:
            ur.cmd_upload_fund_score()
        finally:
            ur._upload_glob = old_glob
        _ok(not any(c[0] == "send" for c in calls), "成功路径不告警(不制造噪音)")

        # D4/D5: §23.2 同类错误面 —— 其余 _upload_glob 消费者是否本就 loud(只验判据, 不改动)
        calls.clear()
        ur._guard_upload_intraday = lambda: None
        ur._upload_glob = lambda *a, **k: (1, 2, ["overview.json"], ["data/overview.json"])
        rc = None
        try:
            ur.cmd_upload_intraday()
        except SystemExit as e:
            rc = e.code
        _ok(rc == 1, f"同类面: cmd_upload_intraday 失败已 exit 1(本就 loud, 实得 {rc})")

        rc = None
        ur._upload_glob = lambda *a, **k: (1, 2, ["probe_x.json"], ["data/probe_x.json"])
        (sd / "data" / "probe_x.json").write_text('{"x":1}', encoding="utf-8")
        try:
            ur.cmd_upload_data_files(["probe_x.json"])
        except SystemExit as e:
            rc = e.code
        _ok(rc == 1, f"同类面: cmd_upload_data_files 失败已 exit 1(本就 loud, 实得 {rc})")

        _ok(not trap, "真实 notify.send 陷阱从未触发(打桩生效, 零真实外发)")

        print("== [E] §22 通道覆盖机检(check_r2_channel_coverage.py) ==")
        import subprocess
        checker = HERE / "check_r2_channel_coverage.py"
        r = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True)
        _ok(r.returncode == 0, "机检现版 exit 0(产出侧/通道侧全对齐)")
        _ok("ALL_PASS" in r.stdout, "机检现版输出 ALL_PASS")
        _ok("fund_score" in r.stdout and "offshore_fund" in r.stdout,
            "机检确含 #193 两前缀(fund_score/offshore_fund)")
        # 回归对照: 喂修复前版本 → 必须 FAIL(证机检真能抓这类漏配, 非空转)
        old_src = Path(tempfile.mkdtemp(prefix="old193-")) / "upload_r2.py"
        g = subprocess.run(["git", "show", "HEAD:scripts/upload_r2.py"],
                           capture_output=True, text=True, cwd=str(HERE.parent))
        if g.returncode == 0 and g.stdout:
            old_src.write_text(g.stdout, encoding="utf-8")
            r2 = subprocess.run([sys.executable, str(checker), str(old_src)], capture_output=True, text=True)
            _ok(r2.returncode != 0 and "HAS_FAIL" in r2.stdout,
                "机检喂修复前版本 → FAIL(对照: 确实抓到 #193 漏配)")
            _ok("fund_score" in r2.stdout and "offshore_fund" in r2.stdout,
                "对照 FAIL 清单确为 fund_score/offshore_fund")
        else:
            print(f"  [skip] git show HEAD 不可用({g.stderr.strip()[:80]}), 跳过修复前对照")
    finally:
        ur.STATIC_DIR = old_static
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n断言 {PASS} PASS / {FAIL} FAIL")
    print("ALL_PASS" if FAIL == 0 else "HAS_FAIL")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()