#!/usr/bin/env python3
"""#188 s06 链路「同步段」检查侧三层盲区根治 —— 自验脚本(可复现)。

覆盖三处修法的行为验证(不触网、不写生产桶/R2, 全部打桩 + 临时目录):
  A. upload_r2.py 修法①: 独立链产物 key 登记清单(.r2_standalone_keys.json)往返/去重/损坏恢复,
     且 verify-r2 平日在 changed 为空时仍能选中清单内的 key(正例: 脱节→补传+外围告警;
     反例: R2 一致→不补传不告警)。
  B. upload_r2.py 修法②: 补传/不一致清单落「文件名」(不再是只打计数)。
  C. s06_snapshot.sh 修法③a: trap 驱动告警(EXIT 非零 / SIGTERM 各发 1 次且幂等; happy→0 告警)。
  D. check_data_integrity.py 盲区①b: 本地新鲜时追加 R2 coverage_end 比对, 且四种分支均不 FAIL
     (FAIL 会让 deploy.sh L324 abort → R2 永不上传的死锁)。

用法: python3 scripts/test_188_s06_sync_blindspot.py   (从仓库根跑; 全过打印 ALL_PASS)
"""
import os
import sys
import json
import types
import hashlib
import tempfile
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
_fails = []


def _ok(cond, label):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fails.append(label)


# ───────────────────────── A/B: upload_r2.py ─────────────────────────
def test_ledger():
    print("[A] 独立链产物 key 登记清单")
    td = tempfile.mkdtemp(prefix="t188_ledg_")
    os.environ["REPO"] = td
    pathlib.Path(td, "static-site", "data").mkdir(parents=True)
    for m in ("upload_r2", "check_data_integrity", "notify"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(SCRIPTS))
    import upload_r2 as u

    p = u._standalone_keys_path()
    _ok(str(p) == os.path.join(td, "data", ".r2_standalone_keys.json"), "清单路径 = REPO/data/.r2_standalone_keys.json")
    _ok(u._load_standalone_keys() == set(), "缺失清单 → 空集")

    u._record_standalone_keys(["data/kelly_mode_s06_state.json", "data/overview.json"])
    u._record_standalone_keys(["data/kelly_mode_s06_state.json", "data/schedule_stats.json"])
    want = {"data/kelly_mode_s06_state.json", "data/overview.json", "data/schedule_stats.json"}
    _ok(u._load_standalone_keys() == want, "去重合并(二次登记不重复)")
    _ok(json.loads(p.read_text()) == sorted(want), "落盘 = 排序后的去重集合")

    p.write_text("{坏 json")
    _ok(u._load_standalone_keys() == set(), "损坏清单 → 空集(不抛, 打 stderr 告警)")
    return td


def test_verify_r2(td):
    print("[A/B] verify-r2 平日选中独立链产物 + 落文件名 + 外围告警")
    sys.path.insert(0, str(SCRIPTS))
    import upload_r2 as u

    dd = pathlib.Path(td, "static-site", "data")
    (dd / "kelly_mode_s06_state.json").write_text('{"coverage_end":"20260930"}')
    (dd / "tiny.json").write_text('{"a":1}')
    u._record_standalone_keys(["data/kelly_mode_s06_state.json"])

    md5 = lambda n: hashlib.md5((dd / n).read_bytes()).hexdigest()
    seen, repairs, sent = [], [], []

    def fake_head(key, **kw):
        seen.append(key)
        if key.endswith("kelly_mode_s06_state.json"):
            return (200, f'"{md5("kelly_mode_s06_state.json")}"') if os.environ.get("MATCH") == "1" \
                else (200, '"ffffffffffffffffffffffffffffffff"')
        if key.endswith("tiny.json"):
            return (200, f'"{md5("tiny.json")}"')
        return (404, None)

    def fake_upload_glob(local_dir, patterns, r2_prefix, **kw):
        repairs.append([pathlib.Path(f).name for f in (kw.get("only_files") or [])])
        n = len(kw.get("only_files") or [])
        return (n, n, [], [])

    class N:
        check_dedup = staticmethod(lambda k, w: False)
        send = staticmethod(lambda subj, body, **kw: sent.append(subj))
        update_dedup = staticmethod(lambda k: None)

    u.s3_head = fake_head
    u._upload_glob = fake_upload_glob
    u._uniform_sample = lambda files, n: []
    sys.modules["notify"] = N
    u.cmd_verify_r2()

    _ok(any(k.endswith("data/kelly_mode_s06_state.json") for k in seen),
        "changed 为空时, 清单内 key 仍被平日对账选中")
    if os.environ.get("MATCH") == "1":
        _ok(not repairs and not sent, "反例: R2 一致 → 无补传、无告警")
    else:
        _ok(repairs and "kelly_mode_s06_state.json" in repairs[0], "正例: 脱节 → 补传该文件")
        _ok(any("独立上传链产物" in s for s in sent), "正例: 脱节 → 发外围告警(verify_r2_standalone_stale)")


# ───────────────────────── C: s06_snapshot.sh trap ─────────────────────────
def test_s06_traps():
    print("[C] s06_snapshot.sh trap 驱动告警")
    td = tempfile.mkdtemp(prefix="t188_s06_")
    scripts = pathlib.Path(td, "scripts")
    scripts.mkdir(parents=True)
    (pathlib.Path(td, "data", "logs")).mkdir(parents=True)
    fakepy = scripts / "fakepy"
    fakepy.write_text('#!/usr/bin/env bash\necho "CALL: $*" >> "$FAKE_TRACE"\n'
                      'case "${FAKE_MODE:-failgen}" in failgen) exit 1;; ok) exit 0;; '
                      'slow) sleep 5; exit 0;; esac\n')
    fakepy.chmod(0o755)
    target = str(REPO_ROOT / "scripts" / "s06_snapshot.sh")
    env = {"FAKE_TRACE": str(pathlib.Path(td, "trace")), "PY": str(fakepy),
           "REPO": td, "GIT_REPO": td, "PATH": os.environ["PATH"]}

    def run(mode, kill_term=False):
        pathlib.Path(td, "trace").write_text("")
        e = dict(env, FAKE_MODE=mode)
        p = subprocess.Popen(["sh", target, "force"], env=e, cwd=td,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if kill_term:
            import time as _t
            _t.sleep(1)
            p.terminate()
        rc = p.wait()
        trace = pathlib.Path(td, "trace").read_text()
        return rc, trace

    rc, tr = run("failgen")
    _ok(rc == 1 and tr.count("CALL: scripts/notify.py") == 1 and "EXIT rc=1" in tr,
        "EXIT 非零 → 告警恰好 1 次(reason=EXIT rc=1)")

    rc, tr = run("slow", kill_term=True)
    _ok(rc == 143 and tr.count("CALL: scripts/notify.py") == 1 and "SIGTERM" in tr,
        "SIGTERM → 告警恰好 1 次(幂等, 不双发)且 exit 143")

    rc, tr = run("ok")
    _ok(rc == 0 and "CALL: scripts/notify.py" not in tr, "happy path → 无告警, exit 0")


# ───────────────────────── D: check_data_integrity 盲区①b ─────────────────────────
def test_integrity_1b():
    print("[D] check_data_integrity ①b 本地新鲜时追 R2 coverage_end 比对(只 WARN)")
    import datetime
    td = tempfile.mkdtemp(prefix="t188_integ_")
    dd = pathlib.Path(td, "static-site", "data")
    dd.mkdir(parents=True)
    today = datetime.date.today().strftime("%Y%m%d")
    (dd / "kelly_mode_s06_state.json").write_text(json.dumps(
        {"coverage_start": "20250101", "coverage_end": today, "daily": [1], "on_base": 1, "off_base": 2}))
    sys.path.insert(0, str(SCRIPTS))
    import check_data_integrity as ci

    class P:
        returncode, stdout, stderr = 0, "✓ A1-A6 全部通过\n", ""
    ci.subprocess.run = lambda *a, **k: P()

    def probe(r2):
        ci._fetch_r2_json = lambda rel, timeout=20: r2
        r = ci.check_s06_state_snapshot(dd)
        return r.status, r.msg

    s, _ = probe(({"coverage_end": today}, None))
    _ok(s == "ok", "R2 coverage_end 一致 → OK")
    s, _ = probe(({"coverage_end": "20260101"}, None))
    _ok(s == "warn", "R2 落后 → WARN(不 FAIL, 防 deploy 死锁)")
    s, _ = probe((None, "URLError: timeout"))
    _ok(s == "warn", "R2 取回失败 → WARN")
    s, _ = probe(("not-a-dict", None))
    _ok(s == "warn", "R2 结构异常 → WARN")


if __name__ == "__main__":
    os.environ.pop("MATCH", None)
    td = test_ledger()
    test_verify_r2(td)
    os.environ["MATCH"] = "1"
    test_verify_r2(td)
    os.environ.pop("MATCH", None)
    test_s06_traps()
    test_integrity_1b()
    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        sys.exit(1)
    print("ALL_PASS")