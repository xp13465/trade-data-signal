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
      两端都可跑(mac 本机 / 云上), 见下方 _bootstrap_env_for_selftest 的运行环境说明 ——
      云上: cd ~/code/trade-data-signal && git checkout <该 commit> && python3 scripts/test_188_s06_sync_blindspot.py

E/F 为 reviewer 复审后补(2026-10-05):
  E. P2-2 死键过滤 —— 台账不再收 verify-r2 扫描永远看不到的键(news_digest 子目录键 / feed.xml),
     且台账内每个键都在扫描可达集内(零死键) + 正常键仍被平日对账逐个 HEAD。
  F. P2-1 台账缺失/损坏/为空 → verify-r2 发显式告警(不静默绿)。
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


# ─────────── 运行环境引导(必须早于 upload_r2 导入: 其导入期 load_env() 找不到 .env 就 sys.exit) ───────────
# 为什么需要: upload_r2._find_env() 只认 ROOT/.env、$GIT_REPO/.env、$REPO/.env(+ 一条 mac 硬编码兜底)。
#   · mac 双树: 代码=~/code/trade, 数据/配置=~/code/trade-data(.env) → 靠硬编码兜底侥幸能跑;
#   · 云上双树: 代码=~/code/trade-data-signal(git, 无 .env), 数据/配置=~/code/trade-data(.env);
#   · 云上 shell 里 GIT_REPO=trade-data-signal → $GIT_REPO/.env 不存在;
#     REPO 又被本脚本 test_ledger 置为临时目录(REPO=td) → $REPO/.env 也不存在 ⇒ 导入期 sys.exit
#     (现象: 0 条 PASS + "无 .env: 尝试过 [...]", 会被误读成功能 FAIL)。
# 解法(最小面, 不碰生产代码行为): 在本脚本最早处把 GIT_REPO 指向「确实存在 .env 的那棵树」,
#   让 $GIT_REPO/.env 命中。REPO=td 的测试语义不受影响(测试要的就是临时仓库)。
def _bootstrap_env_for_selftest():
    here = pathlib.Path(__file__).resolve().parent.parent
    cands = []
    for var in ("GIT_REPO", "REPO"):           # 已显式给出的先试
        v = os.environ.get(var)
        if v:
            cands.append(pathlib.Path(v))
    cands += [here,                                          # 单仓: 仓库根就是配置树
              here.parent / "trade-data", here.parent / "trade",   # 双仓: 兄弟数据树
              pathlib.Path.home() / "code" / "trade-data", pathlib.Path.home() / "code" / "trade"]
    for d in cands:
        if (d / ".env").exists():
            os.environ["GIT_REPO"] = str(d)
            return str(d)
    return None


_ENV_BOOTSTRAP_REPO = _bootstrap_env_for_selftest()
print(f"[env] 自测配置树 = {_ENV_BOOTSTRAP_REPO if _ENV_BOOTSTRAP_REPO else '未找到 .env(导入 upload_r2 会报错)'}")


def _ok(cond, label):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fails.append(label)


# ───────────────────────── A/B: upload_r2.py ─────────────────────────
def test_ledger():
    print("[A] 独立链产物 key 台账")
    td = tempfile.mkdtemp(prefix="t188_ledg_")
    os.environ["REPO"] = td
    dd = pathlib.Path(td, "static-site", "data")
    dd.mkdir(parents=True)
    for n in ("kelly_mode_s06_state.json", "overview.json", "schedule_stats.json", "tiny.json"):
        (dd / n).write_text('{"a":1}')
    for m in ("upload_r2", "check_data_integrity", "notify"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(SCRIPTS))
    import upload_r2 as u

    p = u._standalone_keys_path()
    _ok(str(p) == os.path.join(td, "data", ".r2_standalone_keys.json"), "台账路径 = REPO/data/.r2_standalone_keys.json")
    _ok(u._load_standalone_keys() == (set(), u._LEDGER_MISSING), "缺失台账 → 空集 + state=missing")

    u._record_standalone_keys(["data/kelly_mode_s06_state.json", "data/overview.json"])
    u._record_standalone_keys(["data/kelly_mode_s06_state.json", "data/schedule_stats.json"])
    want = {"data/kelly_mode_s06_state.json", "data/overview.json", "data/schedule_stats.json"}
    _ok(u._load_standalone_keys() == (want, u._LEDGER_OK), "去重合并(二次登记不重复) + state=ok")
    _ok(json.loads(p.read_text()) == sorted(want), "落盘 = 排序后的去重集合")

    p.write_text("{坏 json")
    _ok(u._load_standalone_keys() == (set(), u._LEDGER_CORRUPT), "损坏台账 → 空集 + state=corrupt(不抛)")
    p.write_text("[]")
    _ok(u._load_standalone_keys() == (set(), u._LEDGER_MISSING), "空 list 台账 → 空集 + state=missing")
    p.write_text(json.dumps(sorted(want)))
    _ok((p.parent / (p.name + ".lock")).exists(), "flock 锁文件已创建(P3-2)")
    _ok(not list(p.parent.glob(p.name + ".tmp")), "原子写无 .tmp 残留")

    # P3-2 并发写实测: 6 进程 × 5 互异键 → 无丢更新(flock 串行化读-改-写)
    for cid in range(6):
        for i in range(5):
            (dd / f"c{cid}_{i}.json").write_text('{"a":1}')
    worker = pathlib.Path(td, "worker188.py")
    worker.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import upload_r2 as u\n"
        "cid = sys.argv[1]\n"
        "u._record_standalone_keys([f'data/c{cid}_{i}.json' for i in range(5)])\n")
    import subprocess as _sp
    env = dict(os.environ, REPO=td)
    procs = [_sp.Popen([sys.executable, str(worker), str(c)], env=env) for c in range(6)]
    for pr in procs:
        pr.wait()
    got = u._load_standalone_keys()[0]
    expect = want | {f"data/c{c}_{i}.json" for c in range(6) for i in range(5)}
    _ok(got == expect, f"6 进程并发登记 30 键无丢更新(实际 {len(got)} 键)")
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
        name = key.rsplit("/", 1)[-1]
        fp = dd / name
        if not fp.exists():
            return (404, None)
        # 正例只让 s06 那个文件脱节, 其余(台账内 overview/schedule_stats)按真实 md5 → 一致
        if name == "kelly_mode_s06_state.json" and os.environ.get("MATCH") != "1":
            return (200, '"ffffffffffffffffffffffffffffffff"')
        return (200, f'"{hashlib.md5(fp.read_bytes()).hexdigest()}"')

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
        "changed 为空时, 台账内 key 仍被平日对账选中")
    _ok(all(any(k.endswith(lk) for k in seen) for lk in u._load_standalone_keys()[0]),
        "台账内全部键均被平日对账逐个 HEAD(零遗漏 — 无「永远对不上」的死键)")
    if os.environ.get("MATCH") == "1":
        _ok(not repairs and not sent, "反例: R2 一致 → 无补传、无告警")
    else:
        _ok(repairs and "kelly_mode_s06_state.json" in repairs[0], "正例: 脱节 → 补传该文件")
        _ok(any("独立上传链产物" in s for s in sent), "正例: 脱节 → 发外围告警(verify_r2_standalone_stale)")


# ─────────────── E: P2-2 死键过滤(台账不收「永远对不上」的键) ───────────────
def test_dead_key_filter(td):
    print("[E] P2-2 死键过滤")
    import upload_r2 as u
    dd = pathlib.Path(td, "static-site", "data")
    (dd / "news_digest" / "2026").mkdir(parents=True, exist_ok=True)
    (dd / "news_digest" / "2026" / "2026-10-05.json").write_text('{"d":1}')
    (dd / "news_digest" / "_index.json").write_text('{"i":1}')
    (dd / "feed.xml").write_text("<rss/>")
    dead = ["data/news_digest/2026/2026-10-05.json", "data/news_digest/_index.json", "data/feed.xml"]

    p = u._standalone_keys_path()
    p.write_text("[]")                                  # 隔离: 从空台账起
    u._record_standalone_keys(dead)                     # 全死键 → 一个都不登记
    _ok(u._load_standalone_keys()[0] == set(), "全死键登记 → 台账仍为空(零死键)")

    u._record_standalone_keys(dead + ["data/overview.json"])
    keys, st = u._load_standalone_keys()
    _ok(keys == {"data/overview.json"}, f"混合登记 → 只留可对账键(实际={sorted(keys)})")
    _ok(st == u._LEDGER_OK, "混合登记后 state=ok")

    _ok(u._reconcilable_keys_for(set(dead)) == set(), "死键确为扫描不可达(过滤非空转)")
    _ok(u._reconcilable_keys_for(keys) == keys, "台账内每个键都在扫描可达集内(零死键)")
    p.write_text(json.dumps(sorted(keys)))


# ─────────────── F: P2-1 台账缺失/损坏 → 显式告警 ───────────────
def test_ledger_gap_alert(td):
    print("[F] P2-1 台账缺失/损坏 → verify-r2 显式告警(不静默绿)")
    import datetime as _dt
    import upload_r2 as u

    class _FakeDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 5)      # 周一(非周日) → 走平日增量分支

    class _FakeDT:
        date = _FakeDate
        datetime = _dt.datetime
        timedelta = _dt.timedelta
        timezone = _dt.timezone

    u.datetime = _FakeDT
    p = u._standalone_keys_path()
    if p.exists():
        p.unlink()
    sent = []

    class N:
        check_dedup = staticmethod(lambda k, w: False)
        send = staticmethod(lambda subj, body, **kw: sent.append(subj))
        update_dedup = staticmethod(lambda k: None)

    u.s3_head = lambda key, **kw: (200, '"deadbeefdeadbeefdeadbeefdeadbeef"')
    u._upload_glob = lambda *a, **k: (0, 0, [], [])
    u._uniform_sample = lambda files, n: []
    sys.modules["notify"] = N
    u.cmd_verify_r2()
    _ok(any("台账缺失" in s for s in sent), "台账缺失 → 发 dedup 告警(verify_r2_standalone_ledger_gap)")

    sent.clear()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{坏 json")
    u.cmd_verify_r2()
    _ok(any("台账缺失" in s for s in sent), "台账损坏 → 同样发告警")


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
    test_dead_key_filter(td)
    test_ledger_gap_alert(td)
    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        sys.exit(1)
    print("ALL_PASS")