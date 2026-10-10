#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#204 etf-score 通道上传失败 loud 化 —— 自验脚本(2026-10-06)。

背景: #193 只把 offshore-fund / fund-score 两条通道的「上传失败」接了
_notify_channel_upload_fail; etf-score 走**增量引擎**(_incremental_upload), 引擎自身在
ok!=total 时 sys.exit(1)(调用方拿不到返回值) ⇒ 该通道上传失败只被 update_all.sh:206 的
`|| echo` 吞掉, 用户侧静默。本脚本验证 #204 的接入(引擎 on_fail 回调)正确且与既有一致。

断言:
  [A] helper 层: _notify_channel_upload_fail 对 etf-score 发 1 条 severe 告警, 标题含通道+计数,
      去重键 = r2_channel_upload_fail_etf-score, 「含义」括注 = 本通道自己的 note(非 fund_score)。
  [B] 失败路径: cmd_upload_etf_score 经引擎 on_fail 回调发声 + exit 1(端到端, 引擎真跑)。
  [C] 成功路径: ok==total 不告警(不制造噪音)。
  [D] 回归: 既有 fund-score 调用点文案字节不变(默认 impact_note 保持 #193 历史文案);
      引擎 on_fail 默认 None(其余 11 增量通道零行为变化)。
  [E] §18 L48/L50 硬门: 真实 notify.send 挂陷阱全程零触达 + _upload_glob 打桩零真实 PUT。

⚠️ §18 L48 / memory notify-script-selftest-must-stub / §18 L50: 本脚本**只做 static 打桩**,
   绝不执行任何仓内业务脚本主体; 三重防线保证「任一 cwd 运行均零真实外发 + 零真实 R2 写」:
   ① notify 桩先于任何命令路径安装, 且真实 notify.send 挂陷阱(触达即炸);
   ② _upload_glob / _backup_overwritten_keys / purge_cache 全打桩(引擎真跑但零 PUT/零 COPY);
   ③ STATIC_DIR + ROOT 重定向到临时树(不碰真实仓库树)。

运行: python3 scripts/test_204_etfscore_loud.py   (任一 cwd 均可)
复现: cd <worktree> && python3 scripts/test_204_etfscore_loud.py
"""
import sys
import json
import types
import shutil
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


def _install_notify_stub():
    """sys.modules['notify'] -> Fake; 真实 notify.send 挂陷阱(证打桩生效)。"""
    import notify as real_notify
    trap = []

    def _trap(*a, **k):
        trap.append((a, k))
        raise AssertionError("真实 notify.send 被触达 = 打桩失效(§L48)!")

    real_notify.send = _trap  # 兜底: 任何漏网的真实调用立刻炸

    calls = []
    fake = types.ModuleType("notify")

    def _send(subject, body, **kw):
        calls.append(("send", subject, body, dict(kw)))

    def _check_dedup(key, window):
        calls.append(("check_dedup", key, window))
        return False  # 未发过 -> 允许发

    def _update_dedup(key):
        calls.append(("update_dedup", key))

    fake.send = _send
    fake.check_dedup = _check_dedup
    fake.update_dedup = _update_dedup
    prev = sys.modules.get("notify")
    sys.modules["notify"] = fake
    print(f"  [stub] sys.modules['notify'] -> Fake(prev={'real' if prev is real_notify else prev}); "
          f"真实 send 陷阱已挂 -> 本次自测零真实外发")
    return calls, trap


def _install_engine_stubs():
    """打桩引擎落地动作: _upload_glob / _backup_overwritten_keys / purge_cache。"""
    put_calls = []
    backup_calls = []

    def _fake_upload_glob(local_dir, patterns, r2_prefix, **kw):
        only = kw.get("only_files") or []
        put_calls.append({"r2_prefix": r2_prefix,
                          "only_files": [getattr(p, "name", str(p)) for p in only]})
        # 默认返回「补传成功」占位; 各用例再按需覆盖 (ok/total)。
        n = len(only)
        return (n, n, [], [])

    prev_glob = ur._upload_glob
    prev_backup = ur._backup_overwritten_keys
    prev_purge = ur.purge_cache
    ur._upload_glob = _fake_upload_glob
    # #237(2026-10-10):契约由「返回 copied(int)」改为 4 元组 (copied, skipped, failed, samples),
    # 打桩必须跟随,否则调用点解包 None 抛 TypeError(被 except 兜住 ⇒ 注入多余 ⚠ 行)。
    def _fake_backup(r2_keys, label, md5_map=None):
        backup_calls.append(label)
        return (0, 0, 0, [])

    ur._backup_overwritten_keys = _fake_backup
    ur.purge_cache = lambda *a, **k: None
    return prev_glob, prev_backup, prev_purge, put_calls, backup_calls


def _mk_tree():
    """临时树: static-site/data/etf_score_list_buy.json + 旧状态(使 buy 成待传, mode=增量)。"""
    root = Path(tempfile.mkdtemp(prefix="test204-"))
    sd = root / "static-site"
    data = sd / "data"
    data.mkdir(parents=True)
    (data / "etf_score_list_buy.json").write_text('{"buy":[1,2,3]}', encoding="utf-8")
    st = root / "data"
    st.mkdir(parents=True)
    (st / ".r2_etf_score_state.json").write_text(
        json.dumps({"version": 1, "files": {"etf_score_list_buy.json": {"size": 1, "md5": "deadbeef"}}}),
        encoding="utf-8")
    return root, sd


def main():
    calls, trap = _install_notify_stub()
    prev_glob, prev_backup, prev_purge, put_calls, backup_calls = _install_engine_stubs()
    old_static, old_root = ur.STATIC_DIR, ur.ROOT
    trees = []
    try:
        print("== [A] helper 层文案/severity/dedup(etf-score) ==")
        calls.clear()
        ur._notify_channel_upload_fail(
            "etf-score", "upload-etf-score", "data", 1, 2, ["etf_score_list_hold.json"],
            impact_note="(etf_score_list_* 为 ETF 评分三大榜(buy/sell/hold)前端数据源)")
        sends = [c for c in calls if c[0] == "send"]
        _ok(len(sends) == 1, f"[A] etf-score 告警发 1 条(实得 {len(sends)})")
        if sends:
            subj, body, kw = sends[0][1], sends[0][2], sends[0][3]
            _ok("etf-score" in subj and "1/2" in subj, f"[A] 标题含通道+计数: {subj!r}")
            _ok(kw.get("severe") is True, "[A] severe=True(与 fund-score 同级)")
            _ok("etf-score" in body and "upload_r2.py upload-etf-score" in body,
                "[A] body 含本通道名 + 补传命令 upload-etf-score")
            _ok("etf_score_list_*" in body, "[A] 「含义」括注 = 本通道 note")
            _ok("fund_score 为场外基金评分" not in body, "[A] 未误挂 fund_score 的括注")
        dk = [c for c in calls if c[0] == "check_dedup"]
        _ok(len(dk) == 1 and dk[0][1] == "r2_channel_upload_fail_etf-score" and dk[0][2] == 21600,
            f"[A] 去重键 = r2_channel_upload_fail_etf-score / 窗口 21600(实得 {dk})")
        _ok(any(c[0] == "update_dedup" and c[1] == "r2_channel_upload_fail_etf-score" for c in calls),
            "[A] 发送后 update_dedup 落去重")

        print("== [B] 失败路径(端到端: 引擎真跑, 仅 _upload_glob 打桩返回 ok!=total) ==")
        root, sd = _mk_tree(); trees.append(root)
        ur.STATIC_DIR, ur.ROOT = sd, root
        calls.clear(); put_calls.clear()

        def _b_fail(*a, **k):
            put_calls.append({"r2_prefix": "data", "only_files": ["etf_score_list_buy.json"]})
            return (1, 2, ["etf_score_list_hold.json"], ["data/etf_score_list_buy.json"])

        ur._upload_glob = _b_fail
        rc = None
        try:
            ur.cmd_upload_etf_score()
        except SystemExit as e:
            rc = e.code
        _ok(rc == 1, f"[B] cmd_upload_etf_score 失败 exit 1(实得 {rc})")
        sends = [c for c in calls if c[0] == "send"]
        _ok(len(sends) == 1, f"[B] 失败路径发 1 条告警(实得 {len(sends)})")
        _ok(any(c[0] == "send" and "etf-score" in c[1] and "1/2" in c[1] for c in calls),
            "[B] 告警标题含 etf-score + 1/2(文案/state key 与既有一致)")
        _ok(any(c[0] == "check_dedup" and c[1] == "r2_channel_upload_fail_etf-score" for c in calls),
            "[B] 去重键与既有同族一致")
        _ok(len(put_calls) == 1, f"[B] 引擎真跑到上传步骤(打桩零真实 PUT, 实得 {len(put_calls)} 次桩触达)")

        print("== [C] 成功路径(ok==total)不告警 ==")
        root2, sd2 = _mk_tree(); trees.append(root2)
        ur.STATIC_DIR, ur.ROOT = sd2, root2
        calls.clear()
        ur._upload_glob = lambda *a, **k: (1, 1, [], ["data/etf_score_list_buy.json"])
        rc = None
        try:
            ur.cmd_upload_etf_score()
        except SystemExit as e:
            rc = e.code
        _ok(rc is None, f"[C] 成功不 exit(实得 rc={rc})")
        _ok(not any(c[0] == "send" for c in calls), "[C] 成功路径零告警(不制造噪音)")

        print("== [D] 回归: 既有调用点文案字节不变 + on_fail 默认 None ==")
        calls.clear()
        ur._notify_channel_upload_fail("fund-score", "upload-fund-score",
                                       "fund_score", 0, 2, [])
        fs_body = next(c[2] for c in calls if c[0] == "send")
        _ok("含义: 前端读该 R2 前缀的展示位会停在旧版/缺文件"
            "(fund_score 为场外基金评分 fallback 数据源)。\n" in fs_body,
            "[D] fund-score 既有文案字节不变(默认 impact_note 保持 #193 历史文案)")
        import inspect
        sig = inspect.signature(ur._incremental_upload)
        _ok(sig.parameters["on_fail"].default is None,
            "[D] _incremental_upload.on_fail 默认 None(其余 11 增量通道零行为变化)")
        # 不传 on_fail 的引擎路径: 失败时仍 exit 1(不发告警, 原行为)
        root3, sd3 = _mk_tree(); trees.append(root3)
        ur.STATIC_DIR, ur.ROOT = sd3, root3
        calls.clear()
        ur._upload_glob = lambda *a, **k: (1, 2, ["x.json"], ["data/etf_score_list_buy.json"])
        rc = None
        try:
            ur._incremental_upload(sd3 / "data", ["etf_score_list_*.json"], "data",
                                   ".r2_etf_score_state.json", label="probe-noonfail")
        except SystemExit as e:
            rc = e.code
        _ok(rc == 1, f"[D] 无 on_fail 时引擎失败仍 exit 1(原行为, 实得 {rc})")
        _ok(not any(c[0] == "send" for c in calls), "[D] 无 on_fail 不发告警(默认零行为变化)")

        print("== [E] §18 L48/L50 硬门: 零真实外发 / 零真实 R2 ==")
        _ok(not trap, f"[E] 真实 notify.send 全程零触达(陷阱计数 {len(trap)})")
        _ok(all(c["r2_prefix"] == "data" for c in put_calls),
            "[E] 所有 _upload_glob 触达均走打桩(零真实 PUT)")
        print(f"  [stub] notify send 桩触达 {sum(1 for c in calls if c[0] == 'send')} 次(用例计数), "
              f"真实 trap {len(trap)} 次; _upload_glob 桩触达 {len(put_calls)} 次")
    finally:
        for t in trees:
            shutil.rmtree(t, ignore_errors=True)
        ur.STATIC_DIR, ur.ROOT = old_static, old_root
        ur._upload_glob = prev_glob
        ur._backup_overwritten_keys = prev_backup
        ur.purge_cache = prev_purge

    print(f"\n断言 {PASS} PASS / {FAIL} FAIL")
    print("ALL_PASS" if FAIL == 0 else "HAS_FAIL")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()