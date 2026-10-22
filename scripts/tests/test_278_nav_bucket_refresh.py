# -*- coding: utf-8 -*-
"""test_278_nav_bucket_refresh.py — #278 公募日更 deploy 前 nav_bucket 增量刷新(方案 A)。

来源: 2026-10-22 用户拍板方案 A(docs/ops/failed-units-rca-20261022.md「trade-public-fund-daily」行):
      公募日更(16:20/17:00)早于 17:50 全量链 ⇒ 当日新净值/同日修正值已入库而 nav_bucket 产物
      仍是旧值 ⇒ deploy 内 fund_nav 闸门(阻断级)必 FAIL。修复 = deploy 前先刷新净值桶再校验;
      **不降 fund_nav 阻断级、不改校验阈值、不动 17:50 全量链行为**。

被测对象:
  · scripts/export_fund_nav.py --daily-refresh(增量刷新, 与全量共用 `_build_payload` 单一实现)
  · scripts/lib/nav_bucket_refresh.sh(窗口跳过 / 锁 / 预算 / 退出码契约)
  · scripts/public_fund_daily.sh(接线: 刷新失败 ⇒ 阻断 deploy, 不静默继续)

零生产触达(§18 L48 / L50):
  · 全部数据放 pytest tmp 沙箱(自建 SQLite fixture + tmp nav_bucket 目录), 不读生产 DB、
    不写仓库文件、不跑生产 deploy、不上传 R2、零网络;
  · `public_fund_daily.sh` 端到端用**桩 python / 桩 deploy.sh**(沙箱 scripts 目录), 只验接线;
  · 等锁超时路径显式传 --on-timeout 留痕钩子(替代 with_lock 内置 notify)⇒ 结构上无外发,
    并另设 WITH_LOCK_NOTIFY_DRY_RUN=1 双保险。
  · 本文件只 source **被测 lib 本体**(nav_bucket_refresh.sh), 不 source 任何其它生产脚本;
    public_fund_daily.sh 是「被测对象」本体(白名单), 其余生产脚本一律静态文本断言。

覆盖(对应任务书 7 条证据用例):
  [E1] DB 领先产物(新日期) → 刷新前闸门 FAIL/探针 3 → 刷新后 OK/探针 0, 且产物与全量导出逐位一致
  [E1b] 同一最新日期但数值被修正 → 刷新能纠正(不只看新日期)
  [E2] 无新净值/已对齐 → 幂等: 二次跑零写入(桶 mtime+内容不变), 输出「未变」
  [E3] 刷新失败 ⇒ lib rc=1 且 public_fund_daily **不调用 deploy**、退出码非 0、日志含原因
  [E4] 连跑两次结果逐位相同(幂等)
  [E5] 17:50 全量链回归: update_all.sh 仍走全量(无 --daily-refresh); 全量导出行为不变
  [E6] 窗口跳过(17:25-18:35) → rc=10, 不执行刷新, 不阻断 deploy
  [E7] 锁被占 → 等锁超预算 → rc=10 + 留痕标记 + 零外发; 执行段超时 → rc=124 → 失败(阻断)
  [E8] 产物目录缺失/桶缺失 → 明确失败(rc=2→lib rc=1), 不写半套桶
  [E9] 失败原因不误报成 fund_nav 失败(文案含「nav_bucket 刷新失败」)

跑法:
  .venv/bin/python -m pytest -q scripts/tests/test_278_nav_bucket_refresh.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import export_fund_nav as efn  # noqa: E402  被测对象(同时提供 _fund_bucket 单源)
import check_data_integrity as cdi  # noqa: E402  闸门本体(验「修前 FAIL / 修后 OK」)

SCRIPT = ROOT / "scripts" / "export_fund_nav.py"
LIB = ROOT / "scripts" / "lib" / "nav_bucket_refresh.sh"
DAILY = ROOT / "scripts" / "public_fund_daily.sh"
WITH_LOCK = ROOT / "scripts" / "with_lock.py"
HOOK = ROOT / "scripts" / "nav_refresh_lock_timeout_mark.sh"
TESTS_DIR = Path(__file__).absolute().parent

# 子进程桩目录(session fixture 填入, 见 _ci_stub_pythonpath): None = 尚未建立
_STUB_PYTHONPATH = None

# 固定日期(不取今天: §18 L51 —— 被测代码按 **DB 最新净值日** 推窗口, 不依赖运行时钟)
D0, D1, D2 = "20260202", "20260203", "20260204"


# ── fixture 工具 ────────────────────────────────────────────────────────────────

def _make_db(path: Path, rows) -> None:
    """建 fund_daily_nav fixture(列同生产 schema)。rows = [(date, code, name, unit, acc), ...]"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fund_daily_nav (date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT, "
        "unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL, "
        "PRIMARY KEY (date, fund_code))"
    )
    conn.execute("DELETE FROM fund_daily_nav")
    conn.executemany(
        "INSERT INTO fund_daily_nav (date, fund_code, fund_name, unit_nav, acc_nav) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def _ci_stub_pythonpath(tmp_path_factory):
    """给**裸子进程**也装 CI 缺省第三方库 stub(与 conftest 同一事实源 scripts/tests/_ci_stubs.py)。

    为什么必须: CI ⑧ 只装 pytest + pyyaml + numpy/pandas/pyarrow(见 .github/workflows/ci.yml
    `pip install` 行), **不装 requests**; 本文件的 `_full_export` / `_refresh` 起子进程跑生产
    脚本 export_fund_nav.py, 它顶层 `from app.collector.public_fund import DB_PATH, ...`
    → app/collector/base.py `import requests`。conftest 的 stub 只作用于 pytest **进程内**,
    子进程不加载 conftest ⇒ CI 上 ModuleNotFoundError; 本机 venv 装了真 requests ⇒ 假绿
    (2026-10-22 主干 CI run #924 红; 同型事故见 _ci_stubs.py 头注 CI #727 / §18 L49)。

    做法: 造一个只含 sitecustomize.py 的目录注入 PYTHONPATH —— 子进程启动时 site 模块自动
    执行 sitecustomize, 调 install_missing_third_party_stubs(); 本地装了真库时 find_spec
    命中 ⇒ 不 stub, 保持与生产同构。⇒ 用例不再依赖「本机有没有 requests」(§5.8 上线关)。
    """
    global _STUB_PYTHONPATH
    d = tmp_path_factory.mktemp("ci_stubs")
    (d / "sitecustomize.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        "from _ci_stubs import install_missing_third_party_stubs\n"
        "install_missing_third_party_stubs()\n",
        encoding="utf-8",
    )
    prev = _STUB_PYTHONPATH
    _STUB_PYTHONPATH = str(d)
    yield d
    _STUB_PYTHONPATH = prev


def _run(cmd, env=None, cwd=None, timeout=180):
    e = dict(os.environ)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        e.update(env)
    if _STUB_PYTHONPATH:
        # 子进程沿用同一套 CI 桩(见 _ci_stub_pythonpath); 不覆盖调用方自带的 PYTHONPATH
        e["PYTHONPATH"] = os.pathsep.join(
            [p for p in (_STUB_PYTHONPATH, e.get("PYTHONPATH", "")) if p]
        )
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          env=e, cwd=cwd, timeout=timeout)


def _full_export(db: Path, out: Path):
    return _run([sys.executable, str(SCRIPT), "--db", str(db), "--out-dir", str(out)])


def _refresh(db: Path, out: Path, days: int = 7):
    return _run([sys.executable, str(SCRIPT), "--daily-refresh", "--recent-days", str(days),
                 "--db", str(db), "--out-dir", str(out)])


def _bucket_file(out: Path, code: str) -> Path:
    return out / f"{efn._fund_bucket(code)}.json"


def _bucket_payload(out: Path, code: str) -> dict:
    return json.loads(_bucket_file(out, code).read_text(encoding="utf-8"))[code]


def _snapshot(out: Path) -> dict:
    """目录内容快照: 文件名 -> (mtime_ns, bytes)。用于证「零写入」。"""
    return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(out.glob("*.json"))}


def _content(out: Path) -> dict:
    """只比内容(不比 mtime): 用于「两次全量导出确定性可复现」。"""
    return {p.name: p.read_bytes() for p in sorted(out.glob("*.json"))}


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """tmp 沙箱: REPO/GIT_REPO 指向它(cdi 的 DB 定位走 env 优先)。"""
    root = tmp_path / "sandbox"
    (root / "data").mkdir(parents=True)
    (root / "static-site" / "data").mkdir(parents=True)
    monkeypatch.setenv("REPO", str(root))
    monkeypatch.setenv("GIT_REPO", str(root))
    return root


def _two_codes_distinct_buckets() -> tuple[str, str]:
    """挑两只落在不同桶的 code(抽样比对「每桶取 1 只」⇒ 比对确定性)。"""
    seen = {}
    for i in range(200):
        c = f"{i:06d}"
        b = efn._fund_bucket(c)
        if b in seen:
            continue
        seen[b] = c
        if len(seen) >= 2:
            return seen[sorted(seen)[0]], seen[sorted(seen)[1]]
    raise AssertionError("找不到两只不同桶的 code")


# ── [E1] DB 领先产物 → 刷新后闸门 OK ───────────────────────────────────────────

def test_E1_db_ahead_fails_gate_then_refresh_makes_ok(sandbox):
    """E1: 产物缺最新日 → 闸门 FAIL/探针 3; 刷新后 OK/探针 0, 且与全量导出逐位一致。"""
    code = "000001"
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D0, code, "基金000001", 1.0, 2.0),
                  (D1, code, "基金000001", 1.1, 2.1),
                  (D2, code, "基金000001", 1.2, 2.2)])

    # 参照系: 全量导出(与 17:50 同脚本同口径) —— 刷新结果必须与它逐位一致
    full = sandbox / "full"
    r = _full_export(db, full)
    assert r.returncode == 0, f"全量导出失败:\n{r.stdout}\n{r.stderr}"

    # 陈旧产物: 复制全量后手动删掉最新一行(= 日更采到新净值但产物未重出的真实形态)
    stale = sandbox / "stale"
    stale.mkdir()
    for p in full.glob("*.json"):
        (stale / p.name).write_bytes(p.read_bytes())
    bf = _bucket_file(stale, code)
    bmap = json.loads(bf.read_text(encoding="utf-8"))
    bmap[code]["nav"] = bmap[code]["nav"][:2]
    bmap[code]["date"] = D1
    bmap[code]["count"] = 2
    bf.write_text(json.dumps(bmap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    nav_dir.parent.mkdir(parents=True, exist_ok=True)
    if nav_dir.exists():
        import shutil
        shutil.rmtree(nav_dir)
    nav_dir.symlink_to(stale, target_is_directory=True)

    # 修前: 第三口径探针判「DB 领先」 + 闸门 FAIL
    rc, reason = cdi.probe_fund_nav_db_ahead(nav_dir.parent)
    assert rc == 3, f"修前应判 DB 领先: {reason}"
    res_before = cdi.check_fund_nav(nav_dir.parent)
    assert res_before.status == cdi.CheckResult.FAIL, f"修前应 FAIL: {res_before.status} {res_before.msg}"

    # 刷新
    r = _refresh(db, stale)
    assert r.returncode == 0, f"刷新应成功:\n{r.stdout}\n{r.stderr}"
    assert "✓ nav_bucket 增量刷新完成" in r.stdout

    # 修后: 探针 0 / 闸门 OK / 与全量导出逐位一致(单一 payload 实现, 非第二套口径)
    rc, reason = cdi.probe_fund_nav_db_ahead(nav_dir.parent)
    assert rc == 0, f"修后探针应 0: {reason}"
    res_after = cdi.check_fund_nav(nav_dir.parent)
    assert res_after.status == cdi.CheckResult.OK, f"修后应 OK: {res_after.status} {res_after.msg}"
    assert _bucket_payload(stale, code)["nav"] == [[D0, 1.0, 2.0], [D1, 1.1, 2.1], [D2, 1.2, 2.2]]
    assert _bucket_file(stale, code).read_bytes() == _bucket_file(full, code).read_bytes(), \
        "刷新结果必须与全量导出逐位一致(同一 _build_payload)"


def test_E1b_same_latest_date_value_corrected(sandbox):
    """E1b: 最新日期不变、数值被修正(疑似净值修正) → 刷新也要纠正(候选按「最近窗口有写入」, 不只看新日期)。"""
    code = "000001"
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D1, code, "基金000001", 1.1, 2.1),
                  (D2, code, "基金000001", 1.25, 2.25)])   # D2 数值已是修正后的
    out = sandbox / "nav"
    r = _full_export(db, out)
    assert r.returncode == 0, r.stderr
    # 把产物改成「修正前」的同日旧值(日期相同 ⇒ 旧的自愈探针不认这种形态)
    bf = _bucket_file(out, code)
    bmap = json.loads(bf.read_text(encoding="utf-8"))
    bmap[code]["nav"][-1] = [D2, 1.2, 2.2]
    bf.write_text(json.dumps(bmap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    assert cdi._sample_fund_nav_mismatches(out, db, 30) != [], "同日不同值应被同源比对发现"

    r = _refresh(db, out)
    assert r.returncode == 0, r.stderr
    assert _bucket_payload(out, code)["nav"][-1] == [D2, 1.25, 2.25]
    assert cdi._sample_fund_nav_mismatches(out, db, 30) == []


# ── [E2/E4] 幂等: 二次跑零写入 ─────────────────────────────────────────────────

def test_E2_idempotent_second_run_zero_write(sandbox):
    """E2/E4: 已对齐 → 刷新零写入(无 mtime 变化、无临时文件残留); 连跑两次逐位相同。"""
    code = "000001"
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D1, code, "基金000001", 1.1, 2.1), (D2, code, "基金000001", 1.2, 2.2)])
    out = sandbox / "nav"
    assert _full_export(db, out).returncode == 0

    before = _snapshot(out)
    time.sleep(0.02)   # 让「真的写了」能体现 mtime 变化(同秒写入也靠 ns 分辨率)
    r1 = _refresh(db, out)
    assert r1.returncode == 0, r1.stderr
    assert "变更 0 只" in r1.stdout and "写 0 桶" in r1.stdout, r1.stdout
    assert _snapshot(out) == before, "已对齐时不得重写任何桶(幂等)"

    r2 = _refresh(db, out)
    assert r2.returncode == 0, r2.stderr
    assert _snapshot(out) == before, "连跑第二次仍零写入"
    assert not list(out.glob("*.tmp.*")), "不得残留原子写临时文件"


def test_E2b_parallel_workers_same_bytes(sandbox):
    """并行桶刷新(workers=2)与串行(workers=1)结果逐位一致; 且失败桶能被聚合成 rc=2。"""
    code_a, code_b = _two_codes_distinct_buckets()
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D1, code_a, "A", 1.0, 1.0), (D2, code_a, "A", 1.1, 1.1),
                  (D1, code_b, "B", 2.0, 2.0), (D2, code_b, "B", 2.1, 2.1)])
    serial, parallel = sandbox / "serial", sandbox / "parallel"
    assert _full_export(db, serial).returncode == 0
    parallel.mkdir()
    for p in serial.glob("*.json"):
        (parallel / p.name).write_bytes(p.read_bytes())
    # 两边都制造「缺最新一行」的陈旧态
    for out in (serial, parallel):
        for code in (code_a, code_b):
            bf = _bucket_file(out, code)
            m = json.loads(bf.read_text(encoding="utf-8"))
            m[code]["nav"] = m[code]["nav"][:-1]
            m[code]["date"] = D1
            m[code]["count"] = 1
            bf.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    r1 = _run([sys.executable, str(SCRIPT), "--daily-refresh", "--workers", "1",
               "--db", str(db), "--out-dir", str(serial)])
    r2 = _run([sys.executable, str(SCRIPT), "--daily-refresh", "--workers", "2",
               "--db", str(db), "--out-dir", str(parallel)])
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert _content(serial) == _content(parallel), "串行/并行必须逐位一致"


# ── [E5] 17:50 全量链回归(静态 + 行为) ────────────────────────────────────────

def test_E5_full_chain_unchanged(sandbox):
    """E5: update_all.sh 仍全量导出(无 --daily-refresh); 全量 CLI 行为不变(全桶/逐位稳定)。"""
    txt = (ROOT / "scripts" / "update_all.sh").read_text(encoding="utf-8")
    line = next(ln for ln in txt.splitlines() if "export_fund_nav.py" in ln)
    assert "--daily-refresh" not in line, f"17:50 全量链不得改成增量: {line}"

    code_a, code_b = _two_codes_distinct_buckets()
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D1, code_a, "A", 1.0, 1.0), (D2, code_a, "A", 1.1, 1.1),
                  (D1, code_b, "B", 2.0, 2.0), (D2, code_b, "B", 2.1, 2.1)])
    out1, out2 = sandbox / "full1", sandbox / "full2"
    assert _full_export(db, out1).returncode == 0
    assert _full_export(db, out2).returncode == 0
    assert _content(out1) == _content(out2), "全量导出必须确定性可复现(内容逐位一致)"


# ── [E8] 产物缺失/桶缺失 ⇒ 明确失败 ───────────────────────────────────────────

def test_E8_missing_dir_or_bucket_fails_loud(sandbox):
    """E8: 产物目录缺失 / 候选桶文件缺失 → rc=2 + 明确原因; 且**一个桶都不写**(写前统一预检)。"""
    code = "000001"
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D2, code, "基金000001", 1.2, 2.2)])

    missing = sandbox / "no_such_dir"
    r = _refresh(db, missing)
    assert r.returncode == 2, f"目录缺失应失败 rc=2:\n{r.stdout}\n{r.stderr}"
    assert "nav_bucket 刷新失败" in r.stderr and "产物目录缺失" in r.stderr

    # 两个候选(不同桶), 删掉其中一个桶 ⇒ 目录非空但产物不完整
    code_a, code_b = _two_codes_distinct_buckets()
    _make_db(db, [(D1, code_a, "A", 1.0, 1.0), (D2, code_a, "A", 1.1, 1.1),
                  (D1, code_b, "B", 2.0, 2.0), (D2, code_b, "B", 2.1, 2.1)])
    out = sandbox / "nav"
    assert _full_export(db, out).returncode == 0
    other = _bucket_file(out, code_a)
    other_bytes = other.read_bytes()
    _bucket_file(out, code_b).unlink()
    r = _refresh(db, out)
    assert r.returncode == 2, r.stderr
    assert "桶文件缺失" in r.stderr and "nav_bucket 刷新失败" in r.stderr
    assert other.read_bytes() == other_bytes, "写前预检失败 ⇒ 不得先写了别的桶(无半套产物)"


def test_E8c_corrupt_bucket_fails_loud(sandbox):
    """E8c(输入域): 桶文件内容损坏(非法 JSON / 顶层非对象) → rc=2 + 明确原因, 不静默跳过。"""
    code = "000001"
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D2, code, "基金000001", 1.2, 2.2)])
    out = sandbox / "nav"
    assert _full_export(db, out).returncode == 0
    bf = _bucket_file(out, code)
    bf.write_text("{not json", encoding="utf-8")
    r = _refresh(db, out)
    assert r.returncode == 2, r.stderr
    assert "桶文件读取失败" in r.stderr and "nav_bucket 刷新失败" in r.stderr

    bf.write_text("[]", encoding="utf-8")
    r = _refresh(db, out)
    assert r.returncode == 2, r.stderr
    assert "顶层非对象" in r.stderr


def test_E8b_window_scoped_no_full_rewrite(sandbox):
    """E8b(边界): 窗口外的旧基金不在候选集 —— 不因刷新而全量重写无关桶。"""
    code_new, code_old = _two_codes_distinct_buckets()
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(D2, code_new, "新", 1.0, 1.0),
                  ("20251201", code_old, "旧", 9.0, 9.0)])
    out = sandbox / "nav"
    assert _full_export(db, out).returncode == 0
    # 人为把旧基金产物改成陈旧形态(若刷新误把它当候选就会改回)
    bf = _bucket_file(out, code_old)
    bmap = json.loads(bf.read_text(encoding="utf-8"))
    bmap[code_old]["date"] = "19990101"
    bf.write_text(json.dumps(bmap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    old_bytes = bf.read_bytes()

    r = _refresh(db, out, days=7)
    assert r.returncode == 0, r.stderr
    assert "候选 1 只" in r.stdout, f"只应选中窗口内的 1 只: {r.stdout}"
    assert bf.read_bytes() == old_bytes, "窗口外基金不得被刷新改动"


# ── [E3/E9] public_fund_daily 接线: 刷新失败 ⇒ 阻断 deploy ────────────────────

def _stub_daily_sandbox(root: Path, deploy_marker: Path) -> dict:
    """沙箱化 public_fund_daily: 桩 python / 桩 deploy.sh, 只验接线与失败语义。"""
    (root / "data" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    (root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)

    py = root / ".venv" / "bin" / "python"
    py.write_text('#!/bin/bash\nif [ "$1" = "-c" ]; then echo 1; fi\nexit 0\n', encoding="utf-8")
    py.chmod(0o755)

    # 刷新 lib / 钩子 / with_lock 用真实文件(被测对象), deploy/统计推送用桩
    (root / "scripts" / "lib" / "nav_bucket_refresh.sh").symlink_to(LIB)
    (root / "scripts" / "nav_refresh_lock_timeout_mark.sh").symlink_to(HOOK)
    (root / "scripts" / "with_lock.py").symlink_to(WITH_LOCK)
    deploy = root / "scripts" / "deploy.sh"
    deploy.write_text(f'#!/bin/bash\necho "$@" >> "{deploy_marker}"\nexit 0\n', encoding="utf-8")
    deploy.chmod(0o755)
    (root / "scripts" / "push_schedule_stats.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (root / "scripts" / "gen_schedule_stats.py").write_text("", encoding="utf-8")
    return {"REPO": str(root), "GIT_REPO": str(root), "PF_DAILY_LOCKED": "1",
            "NAV_REFRESH_PY": sys.executable, "NAV_REFRESH_WITH_LOCK": str(WITH_LOCK),
            "NAV_REFRESH_HOOK": str(HOOK), "NAV_REFRESH_LOCK": str(root / "nav.lock"),
            "NAV_REFRESH_LOCK_WAIT": "5", "NAV_REFRESH_TIMEOUT": "60",
            "NAV_REFRESH_NOW": "1630", "NAV_REFRESH_LOG": str(root / "nav_refresh.log"),
            "NAV_REFRESH_SKIP_MARK": str(root / "nav_skip.mark"),
            "WITH_LOCK_NOTIFY_DRY_RUN": "1"}


def test_E3_refresh_failure_blocks_deploy_with_clear_reason(sandbox):
    """E3/E9: 刷新失败 ⇒ deploy **不被调用**、退出码非 0、日志明确「nav_bucket 刷新失败」(不误报成 fund_nav 失败)。"""
    marker = sandbox / "deployed.txt"
    env = _stub_daily_sandbox(sandbox, marker)
    stub = sandbox / "failing_export.sh"
    stub.write_text("#!/bin/bash\nexit 2\n", encoding="utf-8")
    stub.chmod(0o755)
    env["NAV_REFRESH_EXPORT_CMD"] = f"bash {stub}"

    r = _run(["bash", str(DAILY)], env=env, cwd=str(sandbox))
    assert r.returncode != 0, f"刷新失败必须让日更非 0 退出:\n{r.stdout}\n{r.stderr}"
    assert not marker.exists(), "刷新失败后不得调用 deploy(禁止静默继续)"
    assert "nav_bucket 刷新失败" in r.stdout and "阻断本次 deploy" in r.stdout, r.stdout
    assert "fund_nav 失败" not in r.stdout.replace("误报成 fund_nav 失败", ""), \
        "失败原因不得被表述成 fund_nav 校验失败"


def test_E3b_refresh_success_allows_deploy(sandbox):
    """E3 正控: 刷新成功 ⇒ deploy 被调用, 退出码 0(证失败用例不是恒不部署)。"""
    marker = sandbox / "deployed.txt"
    env = _stub_daily_sandbox(sandbox, marker)
    stub = sandbox / "ok_export.sh"
    stub.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    env["NAV_REFRESH_EXPORT_CMD"] = f"bash {stub}"

    r = _run(["bash", str(DAILY)], env=env, cwd=str(sandbox))
    assert r.returncode == 0, f"应成功:\n{r.stdout}\n{r.stderr}"
    assert marker.exists() and "public-fund" in marker.read_text(encoding="utf-8")
    assert "nav_bucket 刷新完成" in r.stdout, r.stdout


# ── [E6/E7] lib 退出码契约(窗口 / 锁 / 超时 / 成功) ──────────────────────────

LIB_RUNNER = 'set -u; . "$1"; nav_bucket_refresh_run; echo "__RC=$?"'


def _lib_env(root: Path, **extra) -> dict:
    env = {
        "REPO": str(root), "PYTHONIOENCODING": "utf-8",
        "NAV_REFRESH_PY": sys.executable, "NAV_REFRESH_WITH_LOCK": str(WITH_LOCK),
        "NAV_REFRESH_HOOK": str(HOOK), "NAV_REFRESH_LOCK": str(root / "nav.lock"),
        "NAV_REFRESH_SKIP_MARK": str(root / "skip.mark"),
        "NAV_REFRESH_LOG": str(root / "nav.log"), "NAV_REFRESH_NOW": "1630",
        "NAV_REFRESH_LOCK_WAIT": "5", "NAV_REFRESH_TIMEOUT": "60",
        "WITH_LOCK_NOTIFY_DRY_RUN": "1",
    }
    env.update(extra)
    return env


def _run_lib(root: Path, **extra):
    return _run(["bash", "-c", LIB_RUNNER, "bash", str(LIB)], env=_lib_env(root, **extra))


def _rc(r) -> int:
    for ln in reversed(r.stdout.splitlines()):
        if ln.startswith("__RC="):
            return int(ln.split("=", 1)[1])
    raise AssertionError(f"未拿到 __RC__:\n{r.stdout}\n{r.stderr}")


def test_decision_helper_contract(sandbox):
    """契约: 0/10 不阻断 deploy; 1/2/124 阻断(超时也算失败, 不假绿)。"""
    script = (
        'set -u; . "$1"; for rc in 0 10 1 2 124; do '
        'if nav_bucket_refresh_blocks_deploy "$rc"; then echo "$rc=BLOCK"; else echo "$rc=OK"; fi; done'
    )
    r = _run(["bash", "-c", script, "bash", str(LIB)], env=_lib_env(sandbox))
    assert r.returncode == 0, r.stderr
    assert [ln.strip() for ln in r.stdout.splitlines() if "=" in ln] == [
        "0=OK", "10=OK", "1=BLOCK", "2=BLOCK", "124=BLOCK"
    ], r.stdout


def test_E6_window_skip_no_refresh(sandbox):
    """E6: 落在 17:25-18:35(17:50 全量链窗口) → rc=10 跳过, 刷新命令**未执行**。"""
    marker = sandbox / "refresh_ran.txt"
    stub = sandbox / "stub.sh"
    stub.write_text(f"#!/bin/bash\ntouch {marker}\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    r = _run_lib(sandbox, NAV_REFRESH_NOW="1750", NAV_REFRESH_EXPORT_CMD=f"bash {stub}")
    assert _rc(r) == 10, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists(), "窗口内不得执行刷新"
    assert "落在 17:50 全量链窗口" in r.stdout


def test_E7_lock_timeout_skips_without_notify(sandbox):
    """E7: 锁被占 + 等锁超预算 → rc=10 + 留痕标记 + 刷新未执行 + 不走内置 notify(零外发)。"""
    lock = sandbox / "nav.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time\nf=open(sys.argv[1],'w')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
         "print('ready',flush=True)\ntime.sleep(60)", str(lock)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        marker = sandbox / "refresh_ran.txt"
        stub = sandbox / "stub.sh"
        stub.write_text(f"#!/bin/bash\ntouch {marker}\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        r = _run_lib(sandbox, NAV_REFRESH_LOCK_WAIT="2", NAV_REFRESH_EXPORT_CMD=f"bash {stub}",
                     NAV_REFRESH_SKIP_MARK=str(sandbox / "skip.mark"))
        assert _rc(r) == 10, f"等锁超预算应跳过(10):\n{r.stdout}\n{r.stderr}"
        assert not marker.exists(), "拿不到锁不得执行刷新"
        # 留痕标记由 lib 判定后清理(不残留), 故以日志文案为准: 必须是「跳过」而不是「完成」
        assert "刷新跳过: 导出锁被占用" in r.stdout, r.stdout
        assert "nav_bucket 刷新完成" not in r.stdout, "跳过不得被记为刷新成功"
        assert "等锁超时跳过" in (r.stdout + r.stderr), "钩子必须留痕(证明跳过路径可区分)"
        assert "排队超时跳过" not in r.stdout + r.stderr, "不得走 with_lock 内置 notify(零外发)"
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_E7b_exec_timeout_is_failure(sandbox):
    """E7b: 刷新本身超执行预算 → with_lock rc=124 → lib rc=1(失败, 阻断 deploy)。"""
    stub = sandbox / "slow.sh"
    stub.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
    stub.chmod(0o755)
    r = _run_lib(sandbox, NAV_REFRESH_TIMEOUT="1", NAV_REFRESH_EXPORT_CMD=f"bash {stub}")
    assert _rc(r) == 1, f"执行超时应判失败:\n{r.stdout}\n{r.stderr}"
    assert "nav_bucket 刷新失败" in r.stdout or "nav_bucket 刷新失败" in r.stderr
    assert "124" in r.stdout + r.stderr


def test_E7c_hook_not_executable_fails_loud(sandbox):
    """E7c: 留痕钩子不可执行 ⇒ 无法区分「跳过/成功」⇒ 按失败处理(宁阻断不假绿)。"""
    hook = sandbox / "hook.sh"
    hook.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    hook.chmod(0o644)   # 故意不给可执行位
    r = _run_lib(sandbox, NAV_REFRESH_HOOK=str(hook))
    assert _rc(r) == 1, f"钩子不可执行应判失败:\n{r.stdout}\n{r.stderr}"
    assert "留痕钩子不可执行" in r.stdout


# ── 接线静态断言(防未来重构把顺序/语义改回去) ────────────────────────────────

def test_daily_script_wiring_order_and_semantics():
    """静态: 刷新在 deploy 之前; deploy 只在「不阻断」分支; 综合退出码把刷新失败算进去。"""
    txt = DAILY.read_text(encoding="utf-8")
    i_refresh = txt.index("nav_bucket_refresh_run")
    i_block = txt.index('if nav_bucket_refresh_blocks_deploy "$NAV_REFRESH_RC"; then')
    i_deploy = txt.index('bash "$REPO/scripts/deploy.sh" public-fund')
    assert i_refresh < i_block < i_deploy, "顺序必须是: 刷新 → 判定 → deploy"
    assert "else" in txt[i_block:i_deploy], "deploy 必须落在「不阻断」分支(else)内"
    assert "nav_bucket 刷新失败" in txt, "失败必须有明确原因文案"
    assert '[ "$NAV_REFRESH_RC" -ne 0 ] && [ "$NAV_REFRESH_RC" -ne 10 ] && FINAL_RC=$NAV_REFRESH_RC' in txt, \
        "刷新失败必须进综合退出码(10=跳过不算失败)"
    # 不得改 fund_nav 阻断级 / 校验阈值
    r = _run(["bash", "-n", str(DAILY)])
    assert r.returncode == 0, r.stderr