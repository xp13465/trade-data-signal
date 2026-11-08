# -*- coding: utf-8 -*-
"""真脚本生成包重放：非索引变化不更新索引列，全列/哈希及重试保持一致。"""
from __future__ import annotations

import sqlite3

import pytest

import test_d1_index_idempotency_20261109 as base


def _statements(sql):
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement.strip()
            statement = ""
    assert not statement.strip(), statement


def _expected(script, repo, tmp_path, table):
    _, full = base._generate(script, repo, tmp_path, {"INCREMENTAL": "0"})
    with sqlite3.connect(":memory:") as con:
        con.executescript(full)
        return con.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()


def _audit(con, table, indexes):
    con.executescript("CREATE TABLE index_updates (col TEXT); CREATE TABLE row_updates (code TEXT);")
    for column in indexes.values():
        con.executescript(f"CREATE TRIGGER audit_{column} AFTER UPDATE OF {column} ON {table} "
                          f"BEGIN INSERT INTO index_updates VALUES ('{column}'); END;")
    con.executescript(f"CREATE TRIGGER audit_row AFTER UPDATE ON {table} "
                      "BEGIN INSERT INTO row_updates VALUES (NEW.fund_code); END;")


@pytest.mark.parametrize("script,table,ddl,build,indexes", base.CASES)
@pytest.mark.parametrize("change", ["date", "setup", "first_hash"])
def test_nonindexed_changes_never_update_index_columns(tmp_path, script, table, ddl, build, indexes, change):
    repo = base.sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    if change == "first_hash":
        with sqlite3.connect(repo / "data/public_fund.db") as local:
            local.execute("UPDATE fund_basic SET fund_type=NULL,scale=NULL")
            if table == "fund_screener":
                local.execute("UPDATE fund_score SET composite_score=NULL")
    with sqlite3.connect(":memory:") as remote:
        _, first = base._generate(script, repo, tmp_path)
        remote.executescript(first)
        if change == "first_hash":
            remote.execute(f"UPDATE {table} SET row_hash=NULL")
        base._save_hashes(remote, table, mock)
        _audit(remote, table, indexes)
        with sqlite3.connect(repo / "data/public_fund.db") as local:
            if change == "date":
                local.execute("UPDATE fund_score SET score_date='20260914', update_date='20260914'")
                if table == "fund_screener":
                    local.execute("INSERT INTO fund_purchase_status (fund_code,update_date,purchase_status) "
                                  "SELECT fund_code,'20260914','开放申购' FROM fund_basic")
            elif change == "setup":
                # screener 同时改变 setup_years，score 保留正确的 setup_date。
                local.execute("UPDATE fund_basic SET setup_date='20100501',fund_name='新名称'")
        _, sql = base._generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        expected = _expected(script, repo, tmp_path, table)
        remote.executescript(sql)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
        assert remote.execute("SELECT * FROM index_updates").fetchall() == [], \
            "仅非索引列变化/首次哈希初始化仍更新索引列"
        assert remote.execute("SELECT COUNT(*) FROM row_updates").fetchone()[0] == len(expected)
        # 相同 SQL 在失败重试时会重放；哈希已经匹配的行必须不再 UPDATE。
        remote.execute("DELETE FROM row_updates")
        remote.executescript(sql)
        assert remote.execute("SELECT * FROM row_updates").fetchall() == []
        base._assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", base.CASES)
def test_index_changes_and_nulls_match_full_snapshot(tmp_path, script, table, ddl, build, indexes):
    repo = base.sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, first = base._generate(script, repo, tmp_path)
        remote.executescript(first)
        _audit(remote, table, indexes)
        for fund_type in (None, "债券型", None, "股票型"):
            base._save_hashes(remote, table, mock)
            with sqlite3.connect(repo / "data/public_fund.db") as local:
                local.execute("UPDATE fund_basic SET fund_type=?,scale=?",
                              (fund_type, None if fund_type is None else 90))
                # score 的有效评分不允许 composite_score=NULL；screener 可以缺评分。
                if table == "fund_screener" and fund_type is None:
                    local.execute("UPDATE fund_score SET composite_score=NULL")
                else:
                    local.execute("UPDATE fund_score SET composite_score=80")
            _, sql = base._generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
            remote.execute("DELETE FROM index_updates")
            remote.execute("DELETE FROM row_updates")
            remote.executescript(sql)
            expected = _expected(script, repo, tmp_path, table)
            assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
            assert remote.execute("SELECT COUNT(*) FROM index_updates").fetchone()[0] > 0
            assert remote.execute("SELECT COUNT(*) FROM row_updates").fetchone()[0] == len(expected)
            base._assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", base.CASES)
def test_interrupted_pair_retry_and_current_index_guard(tmp_path, script, table, ddl, build, indexes):
    repo = base.sync._make_repo(tmp_path, ddl, build)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, first = base._generate(script, repo, tmp_path)
        remote.executescript(first)
        base._save_hashes(remote, table, mock)
        before = remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()
        with sqlite3.connect(repo / "data/public_fund.db") as local:
            local.execute("UPDATE fund_basic SET fund_name='修改后'")
            local.execute("INSERT INTO fund_basic (fund_code,fund_name,fund_type,scale) "
                          "VALUES ('NEW','新基金','股票型',5)")
            local.execute("INSERT INTO fund_score (fund_code,score_date,composite_score) "
                          "VALUES ('NEW','20260913',88)")
        _, sql = base._generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        data = [s for s in _statements(sql) if s.startswith(f"INSERT INTO {table} ")]
        assert len(data) == 2, "小样应形成索引/非索引各一条完整语句"
        remote.executescript(data[0])  # 第一阶段成功后连接中断；新行已完整插入，旧行未改变。
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code!='NEW' ORDER BY fund_code").fetchall() == before
        expected = _expected(script, repo, tmp_path, table)
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code='NEW'").fetchone() == \
            next(r for r in expected if r[0] == "NEW")
        # 第二阶段异常必须逐条语句回滚，不能先写 hash 再留下旧字段。
        remote.executescript(f"CREATE TRIGGER reject_name BEFORE UPDATE OF fund_name ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'injected failure'); END;")
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            remote.executescript(data[1])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code!='NEW' ORDER BY fund_code").fetchall() == before
        remote.execute("DROP TRIGGER reject_name")
        # 模拟两阶段之间另一份完整状态修改索引键；必须基于当前值拒绝套用旧 hash。
        code = before[0][0]
        columns = [r[1] for r in remote.execute(f"PRAGMA table_info({table})")]
        other = dict(zip(columns, before[0]))
        other["fund_type"] = "其它型"
        other_hash = base.sync.inc.compute_row_hash(other, [c for c in columns if c != "row_hash"])
        remote.execute(f"UPDATE {table} SET fund_type=?,row_hash=? WHERE fund_code=?",
                       (other["fund_type"], other_hash, code))
        intervening = remote.execute(f"SELECT * FROM {table} WHERE fund_code=?", (code,)).fetchone()
        remote.executescript(data[1])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code=?", (code,)).fetchone() == intervening
        # 重试整个包：第一阶段恢复索引不同的行，第二阶段补其余行；全部字段/hash一致。
        remote.executescript(sql)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
        base._assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", base.CASES)
def test_two_pass_batching_still_obeys_byte_limits(tmp_path, script, table, ddl, build, indexes):
    repo = base.sync._make_repo(tmp_path, ddl, build)
    _, sql = base._generate(script, repo, tmp_path, {"D1_MAX_STMT_BYTES": "3500"})
    for statement in _statements(sql):
        assert len(statement.encode("utf-8")) < 90000
    with sqlite3.connect(":memory:") as remote:
        remote.executescript(sql)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == \
            _expected(script, repo, tmp_path, table)
