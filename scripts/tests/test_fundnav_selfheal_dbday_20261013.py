# -*- coding: utf-8 -*-
"""test_fundnav_selfheal_dbday_20261013.py — nav_bucket「DB 领先产物」自愈(C1) + 第三口径治假绿(C2)。

来源: 2026-10-13 根因根治任务(docs/ops/stale-navbucket-rootcause-20261013.md /
      docs/ops/deploy-fundnav-selfheal-20261013.md)。

CI 挂载: 位于 `scripts/tests/` ⇒ 被 CI 门禁 ⑧(`python3 -m pytest -q scripts/tests/`)收集。
        全部用例**零生产触达**: 自建 SQLite fixture + tmp 目录沙箱, 不读生产 DB、不写仓库文件、
        不跑 `bash scripts/deploy.sh`、不上传 R2(自愈脚本的 R2 重传被 FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0 关掉)。
        真·端到端(真 export_fund_nav + 真校验)在 scripts/tests/repro_fundnav_selfheal_20261013.sh(人工跑)。

§18 L48(通知类先打桩): 本测试 env 一律带 `WITH_LOCK_NOTIFY_DRY_RUN=1`(with_lock 排队超时告警转
  dry-run) + `FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0`; 并静态断言 fund_nav_selfheal.sh 源码**不含**任何
  notify 调用(自愈脚本本身不发通知, 失败由 deploy.sh 原告警链负责)⇒ 结构上不可能外发。

§18 L50(探针 static-only): 只 import check_data_integrity 纯函数 + `bash -n`/subprocess 跑被测 shell
  脚本本体(被测对象就是它, 属白名单); 不 source 任何生产业务脚本(deploy.sh 只做静态文本断言)。

覆盖:
  [A] C2 第三口径 _fund_nav_db_day_coverage / check_fund_nav
      A1 DB 最新显著日全 NULL → FAIL, 且证「同源比对单独看=一致」(修前假绿)
      A2 正常态 → OK
      A3 非最新显著日全 NULL → WARN 不 FAIL
      A4 零星行(默认阈值 1000) → 不判定(不把「新基金无数据」误判成缺口)
  [B] C1 探针 probe_fund_nav_db_ahead
      B1 DB 领先产物 → 3(可自愈)  B2 新鲜 → 0  B3 DB 落后产物 → 0(绝不反向自愈)  B4 产物缺失 → 0
  [C] C1 编排 scripts/fund_nav_selfheal.sh(桩重出命令 + 沙箱)
      C0 17:50 窗口 → 11(不自愈)  C1 新鲜 → 10 且**未调用**重出(负控)  C2 陈旧 → 0 且产物被重出+复核转 0
      C3 dry-run → 13 且未调用重出      C4 重出失败 → 12
      C5 静态断言: 脚本无 notify 调用 / deploy.sh 接入块存在且重跑仍 FAIL 照旧终止

跑法:
  python3 -m pytest -q scripts/tests/test_fundnav_selfheal_dbday_20261013.py
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent   # scripts/tests -> 仓库根
sys.path.insert(0, str(ROOT / "scripts"))
import check_data_integrity as cdi  # noqa: E402


# ── fixture 工具 ────────────────────────────────────────────────────────────────

def _d(offset_days: int) -> str:
    """相对今天的 YYYYMMDD(负=过去)。"""
    return (datetime.now() + timedelta(days=offset_days)).strftime("%Y%m%d")


def _make_db(path: Path, rows) -> None:
    """建 fund_daily_nav fixture(列同生产 schema, 含 PK; 索引不建——量小无需)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fund_daily_nav (date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT, "
        "unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL, "
        "PRIMARY KEY (date, fund_code))"
    )
    conn.execute("DELETE FROM fund_daily_nav")   # 幂等: 同一沙箱重复建 fixture 不炸
    conn.executemany(
        "INSERT INTO fund_daily_nav (date, fund_code, fund_name, unit_nav, acc_nav) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _write_bucket(nav_dir: Path, code: str, payload: dict, bucket: str = "00") -> None:
    nav_dir.mkdir(parents=True, exist_ok=True)
    (nav_dir / f"{bucket}.json").write_text(json.dumps({code: payload}, ensure_ascii=False), encoding="utf-8")


def _payload(code: str, nav: list) -> dict:
    return {
        "date": (nav[-1][0] if nav else ""),
        "code": code,
        "name": f"基金{code}",
        "count": len(nav),
        "source": "fund_daily_nav 表全史日净值(基金公司披露口径, T+1 入图)",
        "nav": nav,
    }


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """tmp 沙箱: data/public_fund.db + static-site/data/nav_bucket/ ; env REPO/GIT_REPO 指向它。"""
    root = tmp_path / "sandbox"
    (root / "data").mkdir(parents=True)
    (root / "static-site" / "data").mkdir(parents=True)
    monkeypatch.setenv("REPO", str(root))
    monkeypatch.setenv("GIT_REPO", str(root))
    return root


def _run(cmd, env=None, cwd=None):
    e = dict(os.environ)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=e, cwd=cwd, timeout=300)


# ── [A] C2 第三口径 ────────────────────────────────────────────────────────────

def test_A1_latest_significant_day_all_null_fails_and_proves_old_false_green(sandbox, monkeypatch):
    """A1: DB 最新显著交易日 unit_nav 全 NULL → FAIL; 同时证「同源比对单独看=一致」(修前假绿)。"""
    monkeypatch.setattr(cdi, "FUND_NAV_DBDAY_MIN_ROWS", 1)   # 小 fixture: 1 行即「显著」
    code = "000001"
    d_ok, d_bad = _d(-5), _d(-2)
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(d_ok, code, "基金000001", 1.0, 2.0), (d_bad, code, "基金000001", None, None)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    # 产物按破损 DB 同源重出: 最新非空日 = d_ok
    _write_bucket(nav_dir, code, _payload(code, [[d_ok, 1.0, 2.0]]))

    # 修前「同源比对」单独看: 两侧一致(== __旧口径假绿__ 的证据)
    assert cdi._sample_fund_nav_mismatches(nav_dir, db, 30) == [], "同源比对应一致(证明旧口径会 PASS)"

    res = cdi.check_fund_nav(sandbox / "static-site" / "data")
    assert res.status == cdi.CheckResult.FAIL, f"应 FAIL, 实际 {res.status}: {res.msg}"
    assert "unit_nav 全为 NULL" in res.msg and d_bad in res.msg


def test_A2_normal_state_ok(sandbox, monkeypatch):
    """A2: 正常态(最新日有值 + 产物同源一致) → OK。"""
    monkeypatch.setattr(cdi, "FUND_NAV_DBDAY_MIN_ROWS", 1)
    code = "000001"
    d1, d2 = _d(-5), _d(-2)
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(d1, code, "基金000001", 1.0, 2.0), (d2, code, "基金000001", 1.1, 2.1)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    _write_bucket(nav_dir, code, _payload(code, [[d1, 1.0, 2.0], [d2, 1.1, 2.1]]))

    res = cdi.check_fund_nav(sandbox / "static-site" / "data")
    assert res.status == cdi.CheckResult.OK, f"应 OK, 实际 {res.status}: {res.msg}"


def test_A3_non_latest_broken_day_warns_not_fails(sandbox, monkeypatch):
    """A3: 非最新显著交易日全 NULL → WARN(不阻断); 最新日正常 + 产物同源一致。"""
    monkeypatch.setattr(cdi, "FUND_NAV_DBDAY_MIN_ROWS", 1)
    code = "000001"
    d0, d_bad, d2 = _d(-9), _d(-5), _d(-2)
    db = sandbox / "data" / "public_fund.db"
    _make_db(db, [(d0, code, "基金000001", 1.0, 2.0),
                  (d_bad, code, "基金000001", None, None),
                  (d2, code, "基金000001", 1.2, 2.2)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    _write_bucket(nav_dir, code, _payload(code, [[d0, 1.0, 2.0], [d2, 1.2, 2.2]]))

    res = cdi.check_fund_nav(sandbox / "static-site" / "data")
    assert res.status == cdi.CheckResult.WARN, f"应 WARN, 实际 {res.status}: {res.msg}"
    assert "近邻显著交易日" in res.msg and d_bad in res.msg


def test_A4_sparse_rows_not_judged_with_default_threshold(sandbox):
    """A4: 零星行(默认阈值 1000)不参与判定 —— 不把「本来就没数据的新基金」误判成整日缺口。"""
    db = sandbox / "data" / "public_fund.db"
    code = "000001"
    _make_db(db, [(_d(-5), code, "基金000001", 1.0, 2.0),
                  (_d(-2), code, "基金000001", None, None),
                  (_d(-2), "000002", "新基金", None, None)])
    assert cdi.FUND_NAV_DBDAY_MIN_ROWS == 1000, "默认阈值应为 1000(整日 ~24000 行, 两个数量级余量)"
    fail_msg, warn_msg = cdi._fund_nav_db_day_coverage(db)
    assert (fail_msg, warn_msg) == (None, None), f"零星行不应判定: {fail_msg} / {warn_msg}"


# ── [B] C1 探针 ────────────────────────────────────────────────────────────────

def test_B1_probe_hits_db_ahead(sandbox):
    """B1: DB 领先产物 → 返回 3(可自愈)。"""
    code = "000001"
    d1, d2 = _d(-5), _d(-2)
    _make_db(sandbox / "data" / "public_fund.db",
             [(d1, code, "基金000001", 1.0, 2.0), (d2, code, "基金000001", 1.1, 2.1)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    _write_bucket(nav_dir, code, _payload(code, [[d1, 1.0, 2.0]]))

    rc, reason = cdi.probe_fund_nav_db_ahead(sandbox / "static-site" / "data")
    assert rc == 3, reason
    assert "DB 领先产物" in reason


def test_B2_probe_fresh_returns_zero(sandbox):
    """B2: 产物新鲜 → 0(不误触发重出)。"""
    code = "000001"
    d1, d2 = _d(-5), _d(-2)
    _make_db(sandbox / "data" / "public_fund.db",
             [(d1, code, "基金000001", 1.0, 2.0), (d2, code, "基金000001", 1.1, 2.1)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    _write_bucket(nav_dir, code, _payload(code, [[d1, 1.0, 2.0], [d2, 1.1, 2.1]]))

    rc, reason = cdi.probe_fund_nav_db_ahead(sandbox / "static-site" / "data")
    assert rc == 0, reason


def test_B3_probe_ignores_db_behind(sandbox):
    """B3: **DB 落后产物** → 0 —— 反方向绝不重出(重出=以坏覆盖好, 会把真故障洗成 PASS)。"""
    code = "000001"
    d1 = _d(-5)
    _make_db(sandbox / "data" / "public_fund.db", [(d1, code, "基金000001", 1.0, 2.0)])
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    _write_bucket(nav_dir, code, _payload(code, [[d1, 1.0, 2.0], [_d(-1), 1.9, 2.9]]))

    rc, reason = cdi.probe_fund_nav_db_ahead(sandbox / "static-site" / "data")
    assert rc == 0, reason


def test_B4_probe_no_product_returns_zero(sandbox):
    """B4: 产物目录缺失 → 0(交校验本体处理, 探针不背锅)。"""
    _make_db(sandbox / "data" / "public_fund.db", [(_d(-2), "000001", "x", 1.0, 2.0)])
    rc, reason = cdi.probe_fund_nav_db_ahead(sandbox / "static-site" / "data")
    assert rc == 0, reason


# ── [C] C1 编排(fund_nav_selfheal.sh, 桩重出) ──────────────────────────────────

def _prep_shell_sandbox(sandbox: Path) -> None:
    """补上脚本运行所需: scripts/ 与 .venv/bin/python 软链(沙箱里只有 fixture 数据)。"""
    (sandbox / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (sandbox / ".venv" / "bin").mkdir(parents=True)
    (sandbox / ".venv" / "bin" / "python").symlink_to(Path(sys.executable))
    (sandbox / "data" / "logs").mkdir(parents=True, exist_ok=True)


def _selfheal_env(sandbox: Path, **extra):
    env = {
        "REPO": str(sandbox),
        "GIT_REPO": str(sandbox),
        "WITH_LOCK_NOTIFY_DRY_RUN": "1",          # §18 L48: 任何告警路径必须打桩
        "FUNDNAV_SELFHEAL_ASYNC_UPLOAD": "0",     # 零 R2 触达
        "FUNDNAV_SELFHEAL_LOCK": str(sandbox / "selfheal.lock"),
        "FUNDNAV_SELFHEAL_TIMEOUT": "60",
    }
    env.update(extra)
    return env


def _stale_fixture(sandbox: Path) -> tuple[str, str]:
    code = "000001"
    d1, d2 = _d(-5), _d(-2)
    _make_db(sandbox / "data" / "public_fund.db",
             [(d1, code, "基金000001", 1.0, 2.0), (d2, code, "基金000001", 1.1, 2.1)])
    _write_bucket(sandbox / "static-site" / "data" / "nav_bucket", code, _payload(code, [[d1, 1.0, 2.0]]))
    return code, d2


def _fresh_fixture(sandbox: Path) -> None:
    code = "000001"
    d1, d2 = _d(-5), _d(-2)
    _make_db(sandbox / "data" / "public_fund.db",
             [(d1, code, "基金000001", 1.0, 2.0), (d2, code, "基金000001", 1.1, 2.1)])
    _write_bucket(sandbox / "static-site" / "data" / "nav_bucket",
                  code, _payload(code, [[d1, 1.0, 2.0], [d2, 1.1, 2.1]]))


def _write_stub(sandbox: Path, body: str) -> str:
    """桩重出命令: 写 marker + body(默认: 把产物按 DB 重出 → 复核探针应转 0)。"""
    p = sandbox / "stub_export.sh"
    p.write_text(body, encoding="utf-8")
    return f"bash {p}"


def test_C0_window_skip(sandbox):
    """C0: 17:50 update_all 窗口内 → exit 11(不自愈, 也不探针)。"""
    _prep_shell_sandbox(sandbox)
    _stale_fixture(sandbox)
    marker = sandbox / "regen.marker"
    cmd = _write_stub(sandbox, f"touch {marker}\n")
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1750", FUNDNAV_SELFHEAL_EXPORT_CMD=cmd))
    assert r.returncode == 11, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists(), "窗口内不得重出"


def test_C1_fresh_product_no_false_trigger(sandbox):
    """C1: 产物新鲜 → exit 10, 且**未调用**重出命令(负控: 不构造时不许误触发重出)。"""
    _prep_shell_sandbox(sandbox)
    _fresh_fixture(sandbox)
    marker = sandbox / "regen.marker"
    cmd = _write_stub(sandbox, f"touch {marker}\n")
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1200", FUNDNAV_SELFHEAL_EXPORT_CMD=cmd))
    assert r.returncode == 10, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists(), "未命中时不得重出(负控)"
    assert "未命中" in r.stdout


def test_C2_stale_triggers_regen_and_recheck_flips(sandbox):
    """C2: 构造「DB 领先产物」→ 自愈触发(exit 0), 重出命令被调用, 复核探针转 0。"""
    _prep_shell_sandbox(sandbox)
    code, d2 = _stale_fixture(sandbox)
    marker = sandbox / "regen.marker"
    nav_dir = sandbox / "static-site" / "data" / "nav_bucket"
    # 桩重出 = 按 DB 重出该 code 的产物(等价 export_fund_nav 的最小行为)
    body = (
        f"touch {marker}\n"
        f"python3 - <<'PY'\n"
        f"import json, sqlite3, pathlib\n"
        f"db = sqlite3.connect('{sandbox}/data/public_fund.db')\n"
        f"rows = db.execute(\"SELECT date, unit_nav, acc_nav FROM fund_daily_nav WHERE fund_code=? \"\n"
        f"                  \"AND unit_nav IS NOT NULL ORDER BY date ASC\", ('{code}',)).fetchall()\n"
        f"nav = [[r[0], r[1], r[2]] for r in rows]\n"
        f"p = pathlib.Path('{nav_dir}/00.json')\n"
        f"d = json.loads(p.read_text())\n"
        f"d['{code}'].update(date=nav[-1][0], count=len(nav), nav=nav)\n"
        f"p.write_text(json.dumps(d, ensure_ascii=False))\n"
        f"PY\n"
    )
    cmd = _write_stub(sandbox, body)
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1200", FUNDNAV_SELFHEAL_EXPORT_CMD=cmd))
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert marker.exists(), "命中后必须重出"
    assert "命中「DB 领先产物」" in r.stdout
    assert "探针已转 0" in r.stdout, f"复核应转 0: {r.stdout}"
    assert f'"date": "{d2}"' in (nav_dir / "00.json").read_text(), "产物应已更新到 DB 最新日"
    # 重出后完整校验(调用方的下一步)应 PASS —— 闭环证据
    res = cdi.check_fund_nav(sandbox / "static-site" / "data")
    assert res.status == cdi.CheckResult.OK, f"{res.status}: {res.msg}"


def test_C3_dry_run_does_not_regen(sandbox):
    """C3: dry-run 命中 → exit 13 且不重出/不上传。"""
    _prep_shell_sandbox(sandbox)
    _stale_fixture(sandbox)
    marker = sandbox / "regen.marker"
    cmd = _write_stub(sandbox, f"touch {marker}\n")
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1200",
                               FUNDNAV_SELFHEAL_EXPORT_CMD=cmd, FUNDNAV_SELFHEAL_DRY_RUN="1"))
    assert r.returncode == 13, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists()


def test_C4_regen_failure_returns_12(sandbox):
    """C4: 重出命令失败 → exit 12(上界 1 次, 不重试) → 调用方走原终止逻辑。"""
    _prep_shell_sandbox(sandbox)
    _stale_fixture(sandbox)
    marker = sandbox / "regen.marker"
    cmd = _write_stub(sandbox, f"touch {marker}\nexit 7\n")
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1200", FUNDNAV_SELFHEAL_EXPORT_CMD=cmd))
    assert r.returncode == 12, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert marker.exists(), "应尝试过一次(上界=1)"


def test_C5b_disable_switch_no_regen(sandbox):
    """C5b: FUNDNAV_SELFHEAL_DISABLE=1 → exit 10, 不探针/不重出(生产止血开关)。"""
    _prep_shell_sandbox(sandbox)
    _stale_fixture(sandbox)
    marker = sandbox / "regen.marker"
    cmd = _write_stub(sandbox, f"touch {marker}\n")
    r = _run(["bash", str(ROOT / "scripts" / "fund_nav_selfheal.sh")],
             env=_selfheal_env(sandbox, FUNDNAV_SELFHEAL_NOW="1200",
                               FUNDNAV_SELFHEAL_EXPORT_CMD=cmd, FUNDNAV_SELFHEAL_DISABLE="1"))
    assert r.returncode == 10, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists()
    assert "FUNDNAV_SELFHEAL_DISABLE" in r.stdout


def test_C5_static_contracts_no_notify_and_deploy_wiring():
    """C5: 静态契约 —— 自愈脚本无 notify 调用 + deploy.sh 接入块存在且重跑仍 FAIL 照旧终止。"""
    sh = (ROOT / "scripts" / "fund_nav_selfheal.sh").read_text(encoding="utf-8")
    assert "notify" not in sh, "自愈脚本不得直接发通知(告警归 deploy.sh 原链)"
    assert "with_lock.py" in sh, "必须复用进程互斥"
    assert "fund_nav_upload_async.sh" in sh, "R2 重传走既有异步脚本, 不新写上传链路"

    dep = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert "fund_nav_selfheal.sh" in dep, "deploy.sh 必须接入自愈"
    # 「不放宽阻断语义」: 自愈分支之后原终止块仍在(同函数内 notify + exit)
    heal_idx = dep.index("fund_nav_selfheal.sh")
    tail = dep[heal_idx:heal_idx + 4000]
    assert "check_data_integrity.py" in tail and "CHECK_RC" in tail, "自愈后必须重跑校验并复用 CHECK_RC"
    assert "终止部署（4 类事故拦截）" in dep[heal_idx:], "重跑仍 FAIL 必须照旧终止部署"


def test_C6_probe_cli_contract(sandbox):
    """C6: `--fundnav-stale-probe` CLI 三态退出码(真子进程, 用沙箱 DB)。"""
    _stale_fixture(sandbox)
    r = _run([sys.executable, str(ROOT / "scripts" / "check_data_integrity.py"),
              "--fundnav-stale-probe", "--data-dir", str(sandbox / "static-site" / "data")],
             env={"REPO": str(sandbox), "GIT_REPO": str(sandbox)})
    assert r.returncode == 3, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "[fundnav-stale-probe] rc=3" in r.stdout

    _fresh_fixture(sandbox)
    r = _run([sys.executable, str(ROOT / "scripts" / "check_data_integrity.py"),
              "--fundnav-stale-probe", "--data-dir", str(sandbox / "static-site" / "data")],
             env={"REPO": str(sandbox), "GIT_REPO": str(sandbox)})
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"