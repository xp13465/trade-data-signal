# -*- coding: utf-8 -*-
"""D1 同步「一表一文件·一次导入 + 单语句字节封顶」机检（2026-10-26）。

背景(依据, 实测):
  · 旧做法每 80 行一个 SQL 文件、逐文件 `wrangler d1 execute --file`: 单表 347~354 次调用,
    实测 6.35 秒/次 ⇒ 37~44 分钟; 而 D1 侧真正执行只占 0.19%(其余=进程冷启动+import 握手)。
  · 官方上限: `--file` 单文件 5 GiB, **单条语句 100,000 字节**(超限 `statement too long:
    SQLITE_TOOBIG`)。旧做法只按行数切批 ⇒ 实测最大单条 78,105 字节, 只剩 22% 余量。

本文件守住的四件事:
  ① 单文件: DRY_RUN 产出**只有 1 个 .sql**(默认 single 模式), 语句按字节封顶;
  ② 字节封顶: 每一条非「单行长到无法再拆」的语句 ≤ 软上限(60,000 字节),
     且长度按 **UTF-8 字节**算(中文按 3 字节, 不是字符数);
  ③ 超长单行独立成句(不与其他行混批); 超过硬上限(90,000) ⇒ **生成阶段失败退出**,
     绝不写/传半个包;
  ④ 回退开关 `D1_SPLIT_MODE=legacy` 仍产出旧的多文件结构; 非法值快速失败。

另含 `scripts/lib/d1_execute.sh` 重试语义(假 npx 打桩, 零真实外发 / L48、L50 精神):
  · 网络类失败重试(最多 2 次), 第三次成功 ⇒ rc=0;
  · SQL 类错误(statement too long / syntax error)不重试;
  · 重试用尽 ⇒ 返回非 0(不吞)。

跑法: python3 -m pytest -q scripts/tests/test_pfscore_d1_single_import_20261026.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
LIB_DIR = ROOT / "scripts" / "lib"
SYNC_SCREENER = ROOT / "scripts" / "sync_fund_screener_to_d1.sh"
SYNC_SCORE = ROOT / "scripts" / "sync_fund_score_to_d1.sh"

sys.path.insert(0, str(LIB_DIR))
import d1_sql_bundle as bundle_mod  # noqa: E402

# ---------- 合成 fixture 库（列名取自两个同步脚本实际 SELECT，缺列会在生成期响亮失败） ----------
SCREENER_DDL = """
CREATE TABLE fund_basic (fund_code TEXT, fund_name TEXT, fund_type TEXT, fund_company TEXT,
  fund_manager TEXT, setup_date TEXT, scale REAL, management_fee REAL, custody_fee REAL,
  purchase_fee REAL, service_fee REAL, strategy TEXT, benchmark TEXT, update_date TEXT);
CREATE TABLE fund_performance (fund_code TEXT, update_date TEXT, return_1m REAL, return_3m REAL,
  return_6m REAL, return_1y REAL, return_2y REAL, return_3y REAL, return_ytd REAL,
  return_since_inception REAL);
CREATE TABLE fund_risk_indicator (fund_code TEXT, period TEXT, update_date TEXT,
  annual_volatility REAL, max_drawdown REAL);
CREATE TABLE fund_score (fund_code TEXT, score_date TEXT, composite_score REAL, star_rating INTEGER,
  score_return REAL, score_risk_adjusted REAL, score_drawdown REAL, score_stability REAL,
  score_scale REAL, score_fee REAL, sharpe REAL, sortino REAL, calmar REAL, information_ratio REAL,
  alpha REAL, manager_score REAL, m1_tenure REAL, m2_scale REAL, m3_perf_stability REAL,
  m4_drawdown REAL, m5_coherence REAL, m6_focus REAL, kelly_fraction REAL,
  half_kelly_position REAL, kelly_win_rate REAL, kelly_win_loss_ratio REAL, kelly_tier TEXT,
  market_adjustment REAL, final_suggestion REAL, score_method TEXT, data_completeness REAL,
  update_date TEXT);
CREATE TABLE fund_manager (fund_code TEXT, update_date TEXT, manager_name TEXT,
  appoint_date TEXT, tenure_days INTEGER, work_days INTEGER, managed_scale REAL, best_return REAL);
CREATE TABLE fund_rating (fund_code TEXT, rating_date TEXT, shanghai_securities INTEGER,
  cms INTEGER, jajx INTEGER, morningstar INTEGER, five_star_count INTEGER);
CREATE TABLE fund_purchase_status (fund_code TEXT, update_date TEXT, purchase_status TEXT,
  redeem_status TEXT, purchase_min REAL, daily_limit REAL);
CREATE TABLE fund_industry_alloc (fund_code TEXT, report_date TEXT, industry_name TEXT,
  weight_pct REAL);
"""

SCORE_DDL = """
CREATE TABLE fund_basic (fund_code TEXT, fund_name TEXT, fund_type TEXT, fund_company TEXT,
  fund_manager TEXT, setup_date TEXT, scale REAL, management_fee REAL, custody_fee REAL,
  purchase_fee REAL, strategy TEXT, benchmark TEXT);
CREATE TABLE fund_score (fund_code TEXT, score_date TEXT, composite_score REAL,
  star_rating INTEGER, score_return REAL, score_risk_adjusted REAL, score_drawdown REAL,
  score_stability REAL, score_scale REAL, score_fee REAL, sharpe REAL, sortino REAL,
  calmar REAL, information_ratio REAL, alpha REAL, manager_score REAL, m1_tenure REAL,
  m2_scale REAL, m3_perf_stability REAL, m4_drawdown REAL, m5_coherence REAL, m6_focus REAL,
  kelly_fraction REAL, half_kelly_position REAL, kelly_win_rate REAL, kelly_win_loss_ratio REAL,
  kelly_tier TEXT, market_adjustment REAL, final_suggestion REAL, benchmark TEXT,
  score_method TEXT, data_completeness REAL, update_date TEXT);
"""


# ============================ 工具: fixture REPO / 跑真脚本 ============================
def _make_repo(tmp_path, ddl, build):
    """最小 REPO 布局: data/public_fund.db + .venv/bin/python(指向当前解释器)。"""
    repo = tmp_path / "fixture-repo"
    (repo / "data").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    py = repo / ".venv" / "bin" / "python"
    if not py.exists():
        try:
            py.symlink_to(sys.executable)
        except OSError:  # 不支持 symlink 的文件系统 → 退化为包装脚本
            py.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable, encoding="utf-8")
            py.chmod(0o755)
    db = repo / "data" / "public_fund.db"
    con = sqlite3.connect(str(db))
    con.executescript(ddl)
    build(con)
    con.commit()
    con.close()
    return repo


def _build_screener_rows(con, long_chars: int = 0, n_normal: int = 3):
    """n_normal 只普通基金; 若 long_chars>0, 第一只的 strategy 塞长文本(中文, 3 字节/字)。"""
    long_text = ("长" * long_chars) if long_chars else "策略1"
    rows = [(("L00001" if long_chars else "F1"), "基金一", "股票型", "公司A", "经理甲",
             "20150501", 12.5, 1.5, 0.25, 0.15, 0.0, long_text, "基准1", "20260913")]
    for i in range(2, n_normal + 1):
        rows.append((("F%d" % i), "基金%d" % i, "混合型", "公司B", "经理丙",
                     "20180301", 3.2, 1.2, 0.2, 0.1, 0.0, "策略%d" % i, "基准%d" % i,
                     "20260913"))
    con.executemany("INSERT INTO fund_basic VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO fund_score (fund_code, score_date, composite_score, star_rating)"
                    " VALUES (?,?,?,?)",
                    [(r[0], "20260913", 60.0 + i, 3) for i, r in enumerate(rows)])


def _run_script(script, repo, tmp_path, extra=None):
    gen_root = tmp_path / "gen"
    gen_root.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update({"REPO": str(repo), "GIT_REPO": str(repo), "DRY_RUN": "1",
                "TMPDIR": str(gen_root)})
    if extra:
        env.update(extra)
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env,
                       timeout=180)
    dirs = [p for p in gen_root.iterdir() if p.is_dir() and "-d1." in p.name]
    gen_dir = dirs[0] if len(dirs) == 1 else None
    return r, gen_dir


def _sql_files(gen_dir):
    return sorted(gen_dir.glob("*.sql"))


# ============================ ① 单文件 + 字节封顶(打包器单元) ============================
def test_packer_respects_byte_soft_cap_and_keeps_all_rows():
    b = bundle_mod.Bundle(max_stmt_bytes=60000, assert_max_bytes=90000)
    rows = ["('code%04d', '%s')" % (i, "x" * 180) for i in range(500)]
    b.add_inserts("INSERT INTO t (a, b) VALUES", rows, delete_stmt="DELETE FROM t;")
    st = b.stats()
    assert st["max_stmt_bytes"] <= 60000, st
    # 装得满: 500 行 × ~200 字节 ≈ 100KB ⇒ 只该切成个位数条语句, 不是一行一条
    assert st["insert_statements"] <= 5, st
    assert b.statements[0] == "DELETE FROM t;", "DELETE 必须是第一条数据语句"
    text = b.text()
    assert text.count("('code") == 500, "行丢失/重复: %d" % text.count("('code")
    b.assert_limits()  # 不抛


def test_packer_counts_utf8_bytes_not_chars():
    """中文按 3 字节算: 30,000 个汉字 = 90,000 字节 ⇒ 必须触发硬上限(按字符算会漏)。"""
    assert len("汉" * 30000) == 30000
    assert len(("汉" * 30000).encode("utf-8")) == 90000
    b = bundle_mod.Bundle(max_stmt_bytes=60000, assert_max_bytes=90000)
    b.add_inserts("INSERT INTO t (a) VALUES", [("('%s')" % ("汉" * 30000))])
    with pytest.raises(bundle_mod.BundleTooLargeError) as ei:
        b.assert_limits()
    assert "SQLITE_TOOBIG" in str(ei.value)


def test_packer_isolates_oversize_single_row():
    """65KB 单行: 独立成句(不与普通行混批), 总包仍过 <90,000 断言。"""
    big = "('big', '%s')" % ("y" * 64990)          # ≈65KB
    assert 64000 < len(big.encode("utf-8")) < 90000
    rows = ["('n%03d', '%s')" % (i, "z" * 100) for i in range(50)] + [big]
    b = bundle_mod.Bundle(max_stmt_bytes=60000, assert_max_bytes=90000)
    b.add_inserts("INSERT INTO t (a, b) VALUES", rows)
    st = b.stats()
    assert st["oversize_single_row_stmts"] == 1, st
    assert st["max_stmt_bytes"] < 90000, st
    # 含 big 的那条语句必须只有一行(没有 '),(' 分隔符)
    big_stmt = [s for s in b.statements if "'big'" in s]
    assert len(big_stmt) == 1 and "),(" not in big_stmt[0], "超长行和大批混在一起了"
    # 其余语句都 ≤ 软上限
    for s in b.statements:
        if "'big'" not in s:
            assert len(s.encode("utf-8")) <= 60000


def test_packer_assert_fails_when_over_hard_cap():
    b = bundle_mod.Bundle(max_stmt_bytes=60000, assert_max_bytes=90000)
    b.add_inserts("INSERT INTO t (a) VALUES", [("('%s')" % ("q" * 95000))])
    with pytest.raises(bundle_mod.BundleTooLargeError) as ei:
        b.assert_limits()
    msg = str(ei.value)
    assert "硬上限" in msg and "SQLITE_TOOBIG" in msg and "95030" in msg


# ============================ ② 真脚本 DRY_RUN: screener 单文件 ============================
def test_screener_dry_run_produces_exactly_one_file(tmp_path):
    repo = _make_repo(tmp_path, SCREENER_DDL, lambda c: _build_screener_rows(c, n_normal=5))
    r, gen_dir = _run_script(SYNC_SCREENER, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gen_dir is not None, "生成目录不是唯一"
    files = _sql_files(gen_dir)
    assert [f.name for f in files] == ["full_import.sql"], [f.name for f in files]
    assert "files=1" in r.stdout and "mode=single" in r.stdout, r.stdout
    assert "max_stmt_bytes=" in r.stdout
    # 载入 sqlite: 行数 = meta fund_total, 索引 3 个齐
    con = sqlite3.connect(str(tmp_path / "s.db"))
    con.executescript(files[0].read_text(encoding="utf-8"))
    n = con.execute("SELECT COUNT(*) FROM fund_screener").fetchone()[0]
    meta = dict(con.execute("SELECT key, value FROM screener_meta"))
    assert n == json.loads(meta["fund_total"]) == 5, (n, meta["fund_total"])
    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_fscr%'")}
    assert idx == {"idx_fscr_composite", "idx_fscr_type", "idx_fscr_scale"}, idx
    con.close()


def test_screener_dry_run_long_row_isolated_and_passes(tmp_path):
    """65KB 长 strategy: 生成成功; 长行单独成句; 最大语句 < 90,000(硬上限)。"""
    repo = _make_repo(tmp_path, SCREENER_DDL,
                      lambda c: _build_screener_rows(c, long_chars=21660, n_normal=5))  # 64980 字节
    r, gen_dir = _run_script(SYNC_SCREENER, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "oversize_single_row_stmts=1" in r.stdout, r.stdout
    text = _sql_files(gen_dir)[0].read_text(encoding="utf-8")
    big = [s for s in text.split(";\n") if "长" * 100 in s]
    assert len(big) == 1, "长行所在语句数=%d" % len(big)
    assert "),(" not in big[0], "长行和其他行混在同一批(会被 D1 单语句上限打爆)"
    body_bytes = [len(s.encode("utf-8")) for s in text.split(";\n") if s.strip()]
    assert max(body_bytes) < 90000, max(body_bytes)


def test_screener_over_hard_cap_fails_before_writing_package(tmp_path):
    """95KB 长行: 生成阶段失败退出, 且**不落**任何 .sql(不上传半个包)。"""
    repo = _make_repo(tmp_path, SCREENER_DDL,
                      lambda c: _build_screener_rows(c, long_chars=31670, n_normal=3))  # 95010 字节
    r, gen_dir = _run_script(SYNC_SCREENER, repo, tmp_path)
    assert r.returncode != 0, "超限竟然成功了:\n" + r.stdout
    combined = r.stdout + r.stderr
    assert "硬上限" in combined and "SQLITE_TOOBIG" in combined, combined
    assert gen_dir is not None
    assert _sql_files(gen_dir) == [], "超限后仍写了包(会误导上游上传半个包)"


def test_screener_legacy_mode_keeps_old_multi_file_layout(tmp_path):
    """回退开关: D1_SPLIT_MODE=legacy 仍产出 schema + NNN_data + meta 多文件。"""
    repo = _make_repo(tmp_path, SCREENER_DDL, lambda c: _build_screener_rows(c, n_normal=3))
    r, gen_dir = _run_script(SYNC_SCREENER, repo, tmp_path, {"D1_SPLIT_MODE": "legacy"})
    assert r.returncode == 0, r.stdout + r.stderr
    names = [f.name for f in _sql_files(gen_dir)]
    assert names == ["000_schema.sql", "001_data.sql", "999_meta.sql"], names
    first_data = (gen_dir / "001_data.sql").read_text(encoding="utf-8")
    assert first_data.startswith("DELETE FROM fund_screener;\n"), first_data[:80]
    con = sqlite3.connect(str(tmp_path / "legacy.db"))
    for f in _sql_files(gen_dir):
        con.executescript(f.read_text(encoding="utf-8"))
    assert con.execute("SELECT COUNT(*) FROM fund_screener").fetchone()[0] == 3
    con.close()


def test_invalid_split_mode_fails_fast(tmp_path):
    repo = _make_repo(tmp_path, SCREENER_DDL, lambda c: _build_screener_rows(c, n_normal=2))
    r, _ = _run_script(SYNC_SCREENER, repo, tmp_path, {"D1_SPLIT_MODE": "bogus"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "D1_SPLIT_MODE" in (r.stdout + r.stderr)


# ============================ ③ 真脚本 DRY_RUN: score 单文件 ============================
def test_score_dry_run_produces_exactly_one_file(tmp_path):
    def build(con):
        con.executemany(
            "INSERT INTO fund_basic VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [("S1", "基金一", "股票型", "公司A", "经理甲", "20150501", 12.5, 1.5, 0.25, 0.15,
              "策略", "基准")])
        con.executemany(
            "INSERT INTO fund_score (fund_code, score_date, composite_score, star_rating) "
            "VALUES (?,?,?,?)",
            [("S1", "20260913", 70.0, 4), ("S2", "20260913", 60.0, 3)])

    repo = _make_repo(tmp_path, SCORE_DDL, build)
    r, gen_dir = _run_script(SYNC_SCORE, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gen_dir is not None
    files = _sql_files(gen_dir)
    assert [f.name for f in files] == ["full_import.sql"], [f.name for f in files]
    assert "rows=2" in r.stdout and "files=1" in r.stdout, r.stdout
    con = sqlite3.connect(str(tmp_path / "score.db"))
    con.executescript(files[0].read_text(encoding="utf-8"))
    assert con.execute("SELECT COUNT(*) FROM fund_score").fetchone()[0] == 2
    meta = dict(con.execute("SELECT key, value FROM sync_meta"))
    assert meta["score_date"] == "20260913" and meta["rows"] == "2", meta
    con.close()


# ============================ ④ d1_execute.sh 重试语义(假 npx 打桩) ============================
def _fake_npx(tmp_path, mode):
    """造一个假 npx: 记录尝试次数; mode = fail_then_ok | always_net | sql_error。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    counter = tmp_path / "attempts.txt"
    script = bin_dir / "npx"
    script.write_text(
        "#!/bin/bash\n"
        'echo x >> "%s"\n'
        'n=$(wc -l < "%s" | tr -d " ")\n'
        'case "%s" in\n'
        "  fail_then_ok) if [ \"$n\" -lt 3 ]; then echo 'fetch failed' >&2; exit 1; fi ;;\n"
        "  always_net) echo 'Error: fetch failed (ECONNRESET)' >&2; exit 1 ;;\n"
        "  sql_error) echo 'Error: statement too long: SQLITE_TOOBIG' >&2; exit 1 ;;\n"
        "esac\n"
        # 成功时只往 stdout 打一行: 由 lib 的重定向落到调用方指定的输出文件。
        # 注意别按参数位置写文件($3 是子命令 "execute"), 那会在仓库根目录留下垃圾文件。
        'echo "ok"\n' % (counter, counter, mode),
        encoding="utf-8")
    script.chmod(0o755)
    return bin_dir, counter


def _run_exec_lib(tmp_path, bin_dir, env_extra=None):
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.update({"D1_RETRY_DELAYS": "0 0", "LOG_PREFIX": "[test-d1]"})
    if env_extra:
        env.update(env_extra)
    out = tmp_path / "exec.out"
    cmd = ('source "%s/d1_execute.sh" && d1_execute_sql_file testdb "%s/fake.sql" "%s"'
           % (LIB_DIR, tmp_path, out))
    (tmp_path / "fake.sql").write_text("SELECT 1;", encoding="utf-8")
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env,
                          timeout=60)


def test_retry_on_network_failure_then_success(tmp_path):
    bin_dir, counter = _fake_npx(tmp_path, "fail_then_ok")
    r = _run_exec_lib(tmp_path, bin_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert counter.read_text().count("x") == 3, "应重试 2 次(共 3 次尝试)"
    assert "重试第 2 次成功" in r.stdout, r.stdout


def test_no_retry_on_sql_error(tmp_path):
    bin_dir, counter = _fake_npx(tmp_path, "sql_error")
    r = _run_exec_lib(tmp_path, bin_dir)
    assert r.returncode != 0, "SQL 错误必须非 0(不得吞)"
    assert counter.read_text().count("x") == 1, "SQL 类错误不该重试(重放必同样失败)"
    assert "不重试" in r.stderr, r.stderr


def test_retry_exhausted_returns_nonzero(tmp_path):
    bin_dir, counter = _fake_npx(tmp_path, "always_net")
    r = _run_exec_lib(tmp_path, bin_dir)
    assert r.returncode != 0, "重试用尽必须非 0"
    assert counter.read_text().count("x") == 3, counter.read_text()
    assert "重试已用尽" in r.stderr, r.stderr


def test_retry_respects_deadline_budget(tmp_path):
    """预算已耗尽(D1_SYNC_DEADLINE 设为过去) ⇒ 不再重试, 立刻非 0。"""
    bin_dir, counter = _fake_npx(tmp_path, "always_net")
    r = _run_exec_lib(tmp_path, bin_dir, {"D1_SYNC_DEADLINE": "1"})
    assert r.returncode != 0
    assert counter.read_text().count("x") == 1, counter.read_text()
    assert "预算已用尽" in r.stderr, r.stderr