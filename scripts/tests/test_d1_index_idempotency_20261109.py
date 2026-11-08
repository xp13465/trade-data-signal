# -*- coding: utf-8 -*-
"""真脚本 DRY_RUN → 本地 SQLite 重放：索引不重建，数据/查询语义保留。

复用既有 fixture 和哈希往返工具；不调用 wrangler、不访问生产。
schema_version 能抓到 DROP+CREATE，即使索引名、定义和 rootpage 都没变。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import test_d1_incremental_sync_20261108 as sync


CASES = [
    pytest.param(sync.SYNC_SCORE, "fund_score", sync.SCORE_DDL,
                 sync._build_score_rows,
                 {"idx_fs_composite": "composite_score", "idx_fs_type": "fund_type"},
                 id="score"),
    pytest.param(sync.SYNC_SCREENER, "fund_screener", sync.SCREENER_DDL,
                 sync._build_screener_rows,
                 {"idx_fscr_composite": "composite_score", "idx_fscr_type": "fund_type",
                  "idx_fscr_scale": "scale"}, id="screener"),
]


def _generate(script, repo, tmp_path, extra=None):
    # 固定默认开关，避免调用环境把 single/增量测试悄悄切到回退模式。
    env = {"D1_SPLIT_MODE": "single", "INCREMENTAL": "1",
           "FUND_SCORE_CLEANUP_REMOVED": "0", "D1_EXISTING_HASHES_FILE": ""}
    env.update(extra or {})
    result, gen = sync._run_sync(script, repo, tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout, "\n".join(p.read_text() for p in sync._sql_files(gen))


def _save_hashes(con, table, path):
    hashes = dict(con.execute(f"SELECT fund_code, row_hash FROM {table}"))
    path.write_text(json.dumps(hashes))


def _schema_version(con):
    return con.execute("PRAGMA schema_version").fetchone()[0]


def _assert_indexes(con, table, indexes):
    actual = {name for (name,) in con.execute(
        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,))}
    assert actual == set(indexes)
    for name, column in indexes.items():
        assert [row[2] for row in con.execute(f"PRAGMA index_info({name})")] == [column]
        info = next(r for r in con.execute(f"PRAGMA index_list({table})") if r[1] == name)
        assert info[2] == 0 and info[4] == 0, "仍是非唯一、非部分索引"
        # 默认排序、类型筛选、规模区间的索引访问与强制表扫描结果必须相同。
        query = f"SELECT fund_code, {column} FROM {table} {{access}} ORDER BY {column}, fund_code"
        assert con.execute(query.format(access=f"INDEXED BY {name}")).fetchall() == \
            con.execute(query.format(access="NOT INDEXED")).fetchall()
        plan = con.execute(f"EXPLAIN QUERY PLAN SELECT fund_code FROM {table} "
                           f"WHERE {column}=?", (1,)).fetchall()
        assert any(name in row[3] for row in plan), plan


@pytest.mark.parametrize("script,table,ddl,build,indexes", CASES)
def test_unchanged_sync_preserves_existing_indexes(tmp_path, script, table, ddl, build, indexes):
    repo = sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, first = _generate(script, repo, tmp_path)
        remote.executescript(first)  # 首次建库必须建齐所有索引
        _assert_indexes(remote, table, indexes)
        expected = remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()
        version = _schema_version(remote)
        _save_hashes(remote, table, mock)
        for _ in range(2):
            out, sql = _generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
            assert "changed=0" in out and "new=0" in out and "removed=0" in out
            assert f"unchanged={len(expected)}" in out
            assert f"INSERT INTO {table} " not in sql
            remote.executescript(sql)
            assert _schema_version(remote) == version, "零变化同步仍改变 schema（索引被重建）"
            assert "DROP INDEX" not in sql
            assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
            _assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", CASES)
@pytest.mark.parametrize("mode", [{"INCREMENTAL": "0"}, {"D1_SPLIT_MODE": "legacy"}],
                         ids=["full", "legacy"])
def test_full_and_legacy_replay_preserve_indexes(tmp_path, script, table, ddl, build, indexes, mode):
    repo = sync._make_repo(tmp_path, ddl, build)
    with sqlite3.connect(":memory:") as remote:
        _, sql = _generate(script, repo, tmp_path, mode)
        remote.executescript(sql)
        expected = remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()
        _assert_indexes(remote, table, indexes)
        version = _schema_version(remote)
        _, sql = _generate(script, repo, tmp_path, mode)
        assert f"DELETE FROM {table};" in sql, "保留全量替换的回退语义"
        remote.executescript(sql)
        assert _schema_version(remote) == version, "回退路径仍重复重建索引"
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
        _assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", CASES)
def test_changed_added_removed_rows_keep_indexes_correct(tmp_path, script, table, ddl, build, indexes):
    repo = sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, sql = _generate(script, repo, tmp_path)
        remote.executescript(sql)
        version = _schema_version(remote)
        _save_hashes(remote, table, mock)
        codes = [r[0] for r in remote.execute(f"SELECT fund_code FROM {table} ORDER BY fund_code")]
        changed_code, removed_code = codes[:2]
        with sqlite3.connect(repo / "data/public_fund.db") as local:
            local.execute("UPDATE fund_score SET composite_score=99.5 WHERE fund_code=?", (changed_code,))
            local.execute("UPDATE fund_basic SET fund_type='债券型', scale=99 WHERE fund_code=?",
                          (changed_code,))
            local.execute("DELETE FROM fund_score WHERE fund_code=?", (removed_code,))
            local.execute("DELETE FROM fund_basic WHERE fund_code=?", (removed_code,))
            local.execute("INSERT INTO fund_basic (fund_code,fund_name,fund_type,scale) "
                          "VALUES ('NEW','新增基金','股票型',5)")
            local.execute("INSERT INTO fund_score (fund_code,score_date,composite_score,star_rating) "
                          "VALUES ('NEW','20260913',88,4)")
        # score daily 留 removed；screener 每轮删除。随后 score weekly 清理。
        out, sql = _generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        assert "changed=1" in out and "new=1" in out, out
        remote.executescript(sql)
        assert _schema_version(remote) == version
        assert remote.execute(f"SELECT composite_score,fund_type,scale FROM {table} "
                              "WHERE fund_code=?", (changed_code,)).fetchone() == (99.5, "债券型", 99)
        assert remote.execute(f"SELECT composite_score FROM {table} WHERE fund_code='NEW'").fetchone() == (88,)
        assert bool(remote.execute(f"SELECT 1 FROM {table} WHERE fund_code=?", (removed_code,)).fetchone()) \
            == (table == "fund_score")
        _assert_indexes(remote, table, indexes)
        _save_hashes(remote, table, mock)
        out, sql = _generate(script, repo, tmp_path, {
            "D1_EXISTING_HASHES_FILE": str(mock), "FUND_SCORE_CLEANUP_REMOVED": "1"})
        assert "changed=0" in out and "new=0" in out
        remote.executescript(sql)
        assert remote.execute(f"SELECT 1 FROM {table} WHERE fund_code=?", (removed_code,)).fetchone() is None
        _save_hashes(remote, table, mock)
        expected = remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()
        _, sql = _generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        remote.executescript(sql)
        assert _schema_version(remote) == version
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
        _assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", CASES)
def test_missing_index_is_created_once(tmp_path, script, table, ddl, build, indexes):
    repo = sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, sql = _generate(script, repo, tmp_path)
        remote.executescript(sql)
        _save_hashes(remote, table, mock)
        name = next(iter(indexes))
        remote.execute(f"DROP INDEX {name}")  # 模拟已有表缺索引
        _, sql = _generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        remote.executescript(sql)
        _assert_indexes(remote, table, indexes)
        version = _schema_version(remote)
        remote.executescript(sql)
        assert _schema_version(remote) == version, "补建后第二次仍重建"
