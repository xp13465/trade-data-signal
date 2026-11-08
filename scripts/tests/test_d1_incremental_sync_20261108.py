# -*- coding: utf-8 -*-
"""D1 增量同步 diff/迁移/超时修复的单测（2026-11-08, 复审 F1+F2+F3）。

背景（复审 /tmp/rev-fund-sync-report.md 三项必修, 本文件全部固化）:
  · F1 [P0]: 生产 D1 fund_score 表是 2026-08-22 老 schema 建成（无 score_date 列）,
    新版 INSERT 列清单含 score_date, 而 CREATE TABLE IF NOT EXISTS 对已有表不生效
    ⇒ 首跑 "no such column: score_date" 确定性失败。修复 = 生产步骤 0 幂等
    d1_migrate_column 补列 + DRY_RUN 落盘 migrate_preview.txt 预览（本文件断言预览内容,
    并以源码形状守卫锁住两个生产分支都补列）。
  · F2 [必修]: 增量 diff 核心逻辑（四分类/冲突子句/removed 清理分叉）此前零测试覆盖,
    screener 脚本注释虚指"见 scripts/tests/"。本文件 = 该真单测:
      ① scripts/lib/d1_incremental_sync.py 纯计算单元（哈希/diff/冲突子句/哈希源解析）;
      ② DRY_RUN 端到端 mock 往返: 用 D1_EXISTING_HASHES_FILE 喂"上一轮包提取的哈希",
        断言 unchanged 全跳过 / 微改一只只进 changed / 假 code 进 removed、
        fund_score daily retained 不删 vs weekly(FUND_SCORE_CLEANUP_REMOVED=1) 生成
        DELETE ... IN、screener 直接生成 DELETE ... IN;
      ③ F1 migrate_preview.txt 内容断言 + F3 source 顺序形状守卫。
  · F3 [必修]: source d1_execute.sh 原在步骤 2, 哈希读在步骤 0 ⇒ 恒走裸 npx 无超时,
    _D1_HASH_READ_TIMEOUT=90 死配置（网络挂起→systemd 墙杀→_fail 不执行→告警失明）。
    修复 = 两个 lib 都提前到步骤 0 之前 source; 本文件以形状守卫锁死顺序。

门控（L50 精神）: 全部走 DRY_RUN=1（脚本 DRY_RUN 分支零 wrangler 调用）+ 假 npx 打桩
不存在于本文件 —— 本文件根本不触发任何网络路径, 零真实外发。

跑法: python3 -m pytest -q scripts/tests/test_d1_incremental_sync_20261108.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).absolute().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# 复用既有 DRY_RUN 测试基建（fixture REPO 布局 / 跑真脚本 / 生成包枚举 / DDL）
import test_pfscore_d1_single_import_20261026 as base  # noqa: E402

ROOT = base.ROOT
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import d1_incremental_sync as inc  # noqa: E402

_make_repo = base._make_repo
_run_script = base._run_script
_sql_files = base._sql_files
SCORE_DDL = base.SCORE_DDL
SCREENER_DDL = base.SCREENER_DDL
SYNC_SCORE = base.SYNC_SCORE
SYNC_SCREENER = base.SYNC_SCREENER
_build_screener_rows = base._build_screener_rows


# ============================ 工具 ============================
def _run_sync(script, repo, tmp_path, extra=None):
    """跑一次真脚本（DRY_RUN）。同一测试内多次跑会积累多个 fund-*-d1.$$ 目录,
    先清掉旧的, 保证 _run_script 的"生成目录唯一"判定成立。"""
    gen_root = tmp_path / "gen"
    gen_root.mkdir(exist_ok=True)
    for p in gen_root.iterdir():
        if p.is_dir() and "-d1." in p.name:
            shutil.rmtree(p)
    return _run_script(script, repo, tmp_path, extra)


def _mock_from_package(gen_dir, table, out_file):
    """把上一轮 DRY_RUN 包导入临时 sqlite, 提取 {fund_code: row_hash} 落盘为 mock
    D1 现存哈希源（模拟"D1 表已同步成上一轮的样子"）。"""
    con = sqlite3.connect(":memory:")
    for f in _sql_files(gen_dir):
        con.executescript(f.read_text(encoding="utf-8"))
    hashes = {code: h for code, h in con.execute(
        "SELECT fund_code, row_hash FROM %s" % table)}
    con.close()
    out_file.write_text(json.dumps(hashes), encoding="utf-8")
    return hashes


def _package_text(gen_dir):
    files = _sql_files(gen_dir)
    assert [f.name for f in files] == ["full_import.sql"], [f.name for f in files]
    return files[0].read_text(encoding="utf-8")


def _build_score_rows(con, n=2):
    """n 只基金: fund_basic 各一行 + fund_score 各一行（composite_score 60+i）。"""
    for i in range(1, n + 1):
        con.execute("INSERT INTO fund_basic VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("S%d" % i, "基金%d" % i, "股票型", "公司A", "经理甲",
                     "20150501", 12.5, 1.5, 0.25, 0.15, "策略%d" % i, "基准%d" % i))
        con.execute("INSERT INTO fund_score (fund_code, score_date, composite_score,"
                    " star_rating) VALUES ('S%d','20260913',%s,3)" % (i, 60.0 + i))


# ============================ ① d1_incremental_sync 纯计算单元 ============================
def test_cell_repr_none_is_empty_string():
    """None → ''（非 'None'）: NULL 与空串哈希一致是设计语义（D1/本地 NULL 不误判 changed）,
    但 None 与文本 'None' 绝不撞。"""
    assert inc.cell_repr(None) == ""
    assert inc.cell_repr(None) != "None"
    assert inc.cell_repr("") == ""
    assert inc.cell_repr(12.5) == "12.5"
    assert inc.cell_repr(0) == "0"


def test_compute_row_hash_full_cols_and_date_sensitivity():
    """H1 保守: 全列含日期列。任一列变（含 score_date）⇒ 哈希必变; 同行同列序稳定;
    列缺值按 None→'' 计入。"""
    row = {"fund_code": "S1", "score_date": "20260913", "composite_score": 61.0}
    cols = ["fund_code", "score_date", "composite_score"]
    h1 = inc.compute_row_hash(row, cols)
    assert h1 == inc.compute_row_hash(dict(row), cols)  # 稳定
    assert len(h1) == 16
    row2 = dict(row, score_date="20260914")  # 只动日期列
    assert inc.compute_row_hash(row2, cols) != h1
    row3 = dict(row, composite_score=61.01)  # 只动数值列
    assert inc.compute_row_hash(row3, cols) != h1
    # cols 里有 row 缺的列 → 按 None → '' 计入, 不抛
    h4 = inc.compute_row_hash(row, cols + ["kelly_tier"])
    assert h4 != h1


def test_diff_hashes_four_categories():
    """四分类: unchanged 跳过 / changed 待 upsert / new 待 upsert / removed 待 DELETE;
    主键缺失行跳过不崩。"""
    local = [
        {"fund_code": "A", "row_hash": "ha"},
        {"fund_code": "B", "row_hash": "hb2"},   # D1 是 hb ⇒ changed
        {"fund_code": "C", "row_hash": "hc"},     # D1 无 ⇒ new
        {"name": "no-key"},                       # 主键缺失 ⇒ 跳过
    ]
    d1 = {"A": "ha", "B": "hb", "D": "hd"}       # D ⇒ removed
    changed, new, removed, unchanged = inc.diff_hashes(local, d1)
    assert [r["fund_code"] for r in changed] == ["B"]
    assert [r["fund_code"] for r in new] == ["C"]
    assert removed == ["D"]
    assert unchanged == 1
    # 空哈希源（首跑）⇒ 全 new
    changed, new, removed, unchanged = inc.diff_hashes(local, {})
    assert changed == [] and len(new) == 3 and removed == [] and unchanged == 0


def test_build_conflict_clause():
    """ON CONFLICT(fund_code) DO UPDATE SET 全列=excluded.全列; key 不在 SET 里。"""
    clause = inc.build_conflict_clause(
        "fund_score", ["fund_name", "composite_score", "row_hash"])
    assert clause == ("ON CONFLICT(fund_code) DO UPDATE SET "
                      "fund_name=excluded.fund_name, "
                      "composite_score=excluded.composite_score, "
                      "row_hash=excluded.row_hash")
    assert "fund_code=" not in clause, "主键列不应进 SET"
    # 非默认 key
    c2 = inc.build_conflict_clause("t", ["x"], key_col="k")
    assert c2 == "ON CONFLICT(k) DO UPDATE SET x=excluded.x"


def test_load_d1_hashes_variants(tmp_path):
    """dict 透传(返回副本)/wrangler results 列表/JSON 文件/坏 JSON→{}/缺文件→{}。"""
    d = {"A": "ha"}
    out = inc.load_d1_hashes(d)
    assert out == d and out is not d
    # wrangler --json 的 results 形态(落盘文件): [{"fund_code": "X", "row_hash": "abc"}, ...]
    wr_file = tmp_path / "wr_results.json"
    wr_file.write_text(json.dumps(
        [{"fund_code": "A", "row_hash": "ha"}, {"fund_code": "B", "row_hash": None},
         {"note": "无 fund_code 的行跳过"}]), encoding="utf-8")
    assert inc.load_d1_hashes(wr_file) == {"A": "ha", "B": None}
    f = tmp_path / "hashes.json"
    f.write_text(json.dumps(d), encoding="utf-8")
    assert inc.load_d1_hashes(f) == d
    f.write_text("{oops 坏 JSON", encoding="utf-8")
    assert inc.load_d1_hashes(f) == {}
    assert inc.load_d1_hashes(tmp_path / "not_exist.json") == {}


# ============================ ② DRY_RUN 端到端: fund_score 增量往返 ============================
def test_score_roundtrip_unchanged_changed_removed_retained(tmp_path):
    """一体化往返（复审 F2 verifier 固化）:
    无 mock 首跑(全 new) → 提取哈希 → 复跑(全 unchanged 零数据 INSERT)
    → 微改一只(changed=1, 包含 ON CONFLICT upsert) → 掺假 code:
    daily 默认 retained 不删 / weekly FUND_SCORE_CLEANUP_REMOVED=1 生成 DELETE IN。"""
    repo = _make_repo(tmp_path, SCORE_DDL, lambda c: _build_score_rows(c, n=2))
    mock = tmp_path / "d1_mock_hashes.json"

    # 第 1 轮: 无 mock ⇒ D1 视为空表, 全 new; 顺便产出哈希可提取的包
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "new=2" in r.stdout, r.stdout
    hashes = _mock_from_package(gen, "fund_score", mock)
    assert set(hashes) == {"S1", "S2"}

    # 第 2 轮: mock=D1 已同步成第 1 轮的样子 ⇒ 全 unchanged, 零数据 INSERT
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "changed=0" in r.stdout and "new=0" in r.stdout, r.stdout
    assert "unchanged=2" in r.stdout and "removed=0" in r.stdout, r.stdout
    text = _package_text(gen)
    assert "INSERT INTO fund_score" not in text, "全 unchanged 仍写数据行 = diff 失效"
    assert "ON CONFLICT(key) DO UPDATE SET value=excluded.value" in text  # sync_meta 照写

    # 第 3 轮: 微改 S1 composite_score ⇒ 只有 S1 进 changed, upsert 带 conflict 子句
    con = sqlite3.connect(str(repo / "data" / "public_fund.db"))
    con.execute("UPDATE fund_score SET composite_score=70.5 WHERE fund_code='S1'")
    con.commit(); con.close()
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "changed=1" in r.stdout and "new=0" in r.stdout, r.stdout
    assert "unchanged=1" in r.stdout, r.stdout
    text = _package_text(gen)
    assert "ON CONFLICT(fund_code) DO UPDATE SET" in text, "upsert 缺 conflict 子句"
    assert "70.5" in text and "'S1'" in text
    assert "61.0" not in text or "'S2'" in text, "S2 unchanged 不应重写"
    # 更新 mock 为第 3 轮后的状态(后续 removed 分叉不与 changed 混)
    _mock_from_package(gen, "fund_score", mock)

    # 第 4 轮: mock 掺假 code TESTFAKE(D1 有本地无 ⇒ removed); daily 默认不清
    d = json.loads(mock.read_text(encoding="utf-8"))
    d["TESTFAKE"] = "deadbeefdeadbeef"
    mock.write_text(json.dumps(d), encoding="utf-8")
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "removed=0" in r.stdout and "retained=1" in r.stdout, r.stdout
    text = _package_text(gen)
    assert "DELETE FROM fund_score WHERE fund_code IN" not in text, "daily 不该清 removed"
    meta = json.loads((gen / "meta.json").read_text(encoding="utf-8"))
    assert meta["retained_removed"] == 1, meta

    # 第 5 轮: weekly 开清理(FUND_SCORE_CLEANUP_REMOVED=1) ⇒ 生成批 DELETE IN
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path, {
        "D1_EXISTING_HASHES_FILE": str(mock), "FUND_SCORE_CLEANUP_REMOVED": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "removed=1" in r.stdout and "retained=0" in r.stdout, r.stdout
    text = _package_text(gen)
    assert "DELETE FROM fund_score WHERE fund_code IN ('TESTFAKE');" in text, \
        "weekly 清理未生成批 DELETE IN"
    assert "DELETE FROM fund_score;" not in text, "增量模式不得出现全表 DELETE"
    meta = json.loads((gen / "meta.json").read_text(encoding="utf-8"))
    assert meta["retained_removed"] == 0, meta


# ============================ ② DRY_RUN 端到端: screener removed → DELETE IN ============================
def test_screener_roundtrip_removed_generates_delete_in(tmp_path):
    """screener 无 retained 分叉(removed 即删): 删一只 fund_basic ⇒ removed 进包
    DELETE FROM fund_screener WHERE fund_code IN ('F2'); 不动时全 unchanged。"""
    repo = _make_repo(tmp_path, SCREENER_DDL, lambda c: _build_screener_rows(c, n_normal=3))
    mock = tmp_path / "d1_mock_hashes.json"

    r, gen = _run_sync(SYNC_SCREENER, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    hashes = _mock_from_package(gen, "fund_screener", mock)
    assert set(hashes) == {"F1", "F2", "F3"}, hashes

    r, gen = _run_sync(SYNC_SCREENER, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "changed=0" in r.stdout and "unchanged=3" in r.stdout, r.stdout
    assert "INSERT INTO fund_screener" not in _package_text(gen)

    # 删 fund_basic F2 ⇒ screener 本地行没了 ⇒ removed ⇒ 批 DELETE IN
    con = sqlite3.connect(str(repo / "data" / "public_fund.db"))
    con.execute("DELETE FROM fund_basic WHERE fund_code='F2'")
    con.commit(); con.close()
    r, gen = _run_sync(SYNC_SCREENER, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "removed=1" in r.stdout and "changed=0" in r.stdout, r.stdout
    text = _package_text(gen)
    assert "DELETE FROM fund_screener WHERE fund_code IN ('F2');" in text
    assert "DELETE FROM fund_screener;" not in text, "增量模式不得出现全表 DELETE"
    # screener 无 F1 问题: DRY_RUN 不落列迁移预览(老版 COLS 已含 score_date)
    assert not (gen / "migrate_preview.txt").exists()


# ============================ ③ F1: DRY_RUN 迁移预览 + 源码形状守卫 ============================
def test_score_dry_run_writes_migrate_preview_with_score_date(tmp_path):
    """F1: DRY_RUN 生成目录落 migrate_preview.txt, 两条幂等 ALTER 齐(row_hash + score_date)。"""
    repo = _make_repo(tmp_path, SCORE_DDL, lambda c: _build_score_rows(c, n=1))
    r, gen = _run_sync(SYNC_SCORE, repo, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "列迁移预览已落盘" in r.stdout, r.stdout
    preview = (gen / "migrate_preview.txt").read_text(encoding="utf-8")
    assert "ALTER TABLE fund_score ADD COLUMN row_hash TEXT;" in preview, preview
    assert "ALTER TABLE fund_score ADD COLUMN score_date TEXT;" in preview, preview


def test_source_guards_f1_f3():
    """源码形状守卫(改脚本时忘了这两处 ⇒ 本用例红):
    F1: fund_score 两个生产分支(INCREMENTAL=1/=0)都必须调 d1_migrate_column 补 score_date;
        d1_migrate_row_hash 必须薄包装 d1_migrate_column(改列迁移只有一处实现)。
    F3: source d1_execute.sh 必须在哈希读之前(否则 _D1_HASH_READ_TIMEOUT=90 死配置,
        哈希读恒走裸 npx 无超时 → 网络挂起 → systemd 墙杀 → _fail 不执行 → #275 失明)。"""
    for script, table in ((SYNC_SCORE, "fund_score"), (SYNC_SCREENER, "fund_screener")):
        text = script.read_text(encoding="utf-8")
        src_idx = text.index('source "$SCRIPT_SELF_DIR/lib/d1_execute.sh"')
        hash_idx = text.index('d1_read_hashes "$D1_DB"')
        assert src_idx < hash_idx, \
            "%s: source d1_execute.sh 必须在 d1_read_hashes 之前(F3)" % script.name
    score_text = SYNC_SCORE.read_text(encoding="utf-8")
    assert score_text.count('d1_migrate_column "$D1_DB" "fund_score" "score_date" "TEXT"') == 2, \
        "F1: INCREMENTAL=1 与 =0 两个分支都必须补 score_date 列"
    lib_text = (ROOT / "scripts" / "lib" / "d1_hash_read.sh").read_text(encoding="utf-8")
    body = lib_text[lib_text.index("d1_migrate_row_hash()"):lib_text.index("d1_migrate_column()")]
    assert "d1_migrate_column " in body, "d1_migrate_row_hash 必须走 d1_migrate_column 单一实现"


def test_d1_migrate_column_tolerates_duplicate_and_no_table():
    """F1 幂等性: ALTER 输出含 duplicate column name / no such table ⇒ 跳过返回 0;
    其他错误原样返回非 0。stub 掉 _d1_hash_run, 零网络。"""
    lib = ROOT / "scripts" / "lib" / "d1_hash_read.sh"
    # 用 bash 跑一个只替换 _d1_hash_run 的探针(static-only: 只 source lib 定义, 不跑业务脚本主体)
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for name, out, rc, expect in (
            ("dup", "Error: duplicate column name: score_date", 1, 0),
            ("notable", "Error: no such table: fund_score", 1, 0),
            ("ok", "", 0, 0),
            ("fatal", "Error: network timeout", 1, 1),
        ):
            stub = Path(td) / ("stub_%s.sh" % name)
            stub.write_text(
                "#!/bin/bash\n"
                "_d1_hash_run() { printf '%%s\\n' '%s'; return %d; }\n"
                "PY=python3\n" % (out.replace("'", "'\"'\"'"), rc),
                encoding="utf-8")
            probe = Path(td) / ("probe_%s.sh" % name)
            # 先 source lib(拿 d1_migrate_column), 再 source stub 覆盖 _d1_hash_run,
            # 保证零网络(L50: 探针 static-only, 不跑业务脚本主体)
            probe.write_text(
                "source '%s'\nsource '%s'\n"
                "d1_migrate_column test-db fund_score score_date TEXT\n"
                "echo \"RC=$?\"\n" % (lib, stub),
                encoding="utf-8")
            r = subprocess.run(["bash", str(probe)], capture_output=True, text=True,
                               timeout=30, cwd=td)
            combined = r.stdout + r.stderr
            assert "RC=%d" % expect in combined, (name, combined)
