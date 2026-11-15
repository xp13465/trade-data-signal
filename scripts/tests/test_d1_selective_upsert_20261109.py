# -*- coding: utf-8 -*-
"""真脚本生成包重放：三条互补 upsert 语句的隔离/落库/重试语义。

2026-11-09 建(两语句) → 2026-11-16 写放大瘦身改为三语句(零语义变更):
  A composite 索引语句: fund_type/scale(screener) 或 fund_type(score) 未变、composite_score 变
  B 全列语句        : fund_type 或 scale(screener) 变
  C 非索引语句      : 索引列全未变、其它列变(原语句不变)
断言: 索引列没变不更新索引列; 索引列变走全列; 同一行只被一条语句更新一次; 重试幂等。
"""
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


def _kind(statement, table):
    """按 WHERE 谓词特征给三条 upsert 语句分类(测试侧独立识别, 不依赖生成顺序)。"""
    if "composite_score IS NOT excluded.composite_score" in statement:
        return "A"
    if f"{table}.fund_type IS NOT excluded.fund_type" in statement:
        return "B"
    if "row_hash IS NOT excluded.row_hash" in statement:
        return "C"
    raise AssertionError("未知 upsert 语句: %s" % statement[:120])


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
def test_three_pass_routing_and_mutual_exclusion(tmp_path, script, table, ddl, build, indexes):
    """小样本四态(索引列未变 / 只 composite 变 / fund_type 变 / scale 变):
    C 只写非索引列, A 写非索引列+composite_score, B 写全列; 用 AFTER UPDATE 触发器
    按语句打标, 证明每条命中行只被一条语句写一次(写放大不因多语句翻倍)。"""
    if table == "fund_screener":
        build_fn = lambda c: base.sync._build_screener_rows(c, n_normal=4)
        code_c, code_a, code_b, code_scale = "F1", "F2", "F3", "F4"
    else:
        build_fn = lambda c: base.sync._build_score_rows(c, n=3)
        code_c, code_a, code_b, code_scale = "S1", "S2", "S3", None
    repo = base.sync._make_repo(tmp_path, ddl, build_fn)
    mock = tmp_path / "hashes.json"
    with sqlite3.connect(":memory:") as remote:
        _, first = base._generate(script, repo, tmp_path)
        remote.executescript(first)
        base._save_hashes(remote, table, mock)
        with sqlite3.connect(repo / "data/public_fund.db") as local:
            local.execute("UPDATE fund_basic SET fund_name='改名' WHERE fund_code=?", (code_c,))
            local.execute("UPDATE fund_score SET composite_score=77.5 WHERE fund_code=?", (code_a,))
            local.execute("UPDATE fund_basic SET fund_type='债券型' WHERE fund_code=?", (code_b,))
            if code_scale:
                local.execute("UPDATE fund_basic SET scale=99.0 WHERE fund_code=?", (code_scale,))
        _, sql = base._generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        expected = _expected(script, repo, tmp_path, table)
        data = [s for s in _statements(sql) if s.startswith(f"INSERT INTO {table} ")]
        assert len(data) == 3, "小样应形成 composite / 全列 / 非索引 三条完整语句"
        by_kind = {_kind(s, table): s for s in data}
        assert set(by_kind) == {"A", "B", "C"}, by_kind
        # A 不得 SET 二级索引列(否则写放大不降); B 必须全列; C 不得 SET composite。
        assert "fund_type=excluded.fund_type" not in by_kind["A"]
        if table == "fund_screener":
            assert "scale=excluded.scale" not in by_kind["A"]
        assert "fund_type=excluded.fund_type" in by_kind["B"]
        assert "composite_score=excluded.composite_score" in by_kind["B"]
        assert "composite_score=excluded.composite_score" not in by_kind["C"]
        remote.executescript("CREATE TABLE upd_log (code TEXT, kind TEXT);")
        for kind in ("A", "B", "C"):
            remote.executescript("DROP TRIGGER IF EXISTS log_upd;")
            remote.executescript(
                f"CREATE TRIGGER log_upd AFTER UPDATE ON {table} "
                f"BEGIN INSERT INTO upd_log VALUES (NEW.fund_code, '{kind}'); END;")
            remote.executescript(by_kind[kind])
        log = sorted(remote.execute("SELECT code, kind FROM upd_log").fetchall())
        want = [(code_a, "A"), (code_b, "B"), (code_c, "C")]
        if code_scale:
            want.append((code_scale, "B"))
        assert log == sorted(want), "同一行被重复写/路由错: %s" % (log,)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
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
def test_interrupted_three_pass_retry_and_current_index_guard(tmp_path, script, table, ddl, build, indexes):
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
        assert len(data) == 3, "小样应形成 composite / 全列 / 非索引 三条完整语句"
        by_kind = {_kind(s, table): s for s in data}
        assert set(by_kind) == {"A", "B", "C"}, by_kind
        # 第一阶段(A)成功后连接中断；新行已完整插入，旧行未改变(A 只命中 composite 真变的行)。
        remote.executescript(by_kind["A"])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code!='NEW' ORDER BY fund_code").fetchall() == before
        expected = _expected(script, repo, tmp_path, table)
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code='NEW'").fetchone() == \
            next(r for r in expected if r[0] == "NEW")
        # 第二阶段(C, 非索引列)异常必须逐条语句回滚，不能先写 hash 再留下旧字段。
        remote.executescript(f"CREATE TRIGGER reject_name BEFORE UPDATE OF fund_name ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'injected failure'); END;")
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            remote.executescript(by_kind["C"])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code!='NEW' ORDER BY fund_code").fetchall() == before
        remote.execute("DROP TRIGGER reject_name")
        # B 只命中 fund_type/scale 真变的行；本样本没有 ⇒ 零行变化。
        remote.executescript(by_kind["B"])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code!='NEW' ORDER BY fund_code").fetchall() == before
        # 模拟三条语句之间另一份完整状态修改索引键；C 必须基于当前值拒绝套用旧 hash。
        code = before[0][0]
        columns = [r[1] for r in remote.execute(f"PRAGMA table_info({table})")]
        other = dict(zip(columns, before[0]))
        other["fund_type"] = "其它型"
        other_hash = base.sync.inc.compute_row_hash(other, [c for c in columns if c != "row_hash"])
        remote.execute(f"UPDATE {table} SET fund_type=?,row_hash=? WHERE fund_code=?",
                       (other["fund_type"], other_hash, code))
        intervening = remote.execute(f"SELECT * FROM {table} WHERE fund_code=?", (code,)).fetchone()
        remote.executescript(by_kind["C"])
        assert remote.execute(f"SELECT * FROM {table} WHERE fund_code=?", (code,)).fetchone() == intervening
        # 重试整个包：B 恢复索引不同的行，C 补其余行；全部字段/hash一致。
        remote.executescript(sql)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == expected
        base._assert_indexes(remote, table, indexes)


@pytest.mark.parametrize("script,table,ddl,build,indexes", base.CASES)
def test_three_pass_batching_still_obeys_byte_limits(tmp_path, script, table, ddl, build, indexes):
    repo = base.sync._make_repo(tmp_path, ddl, build)
    _, sql = base._generate(script, repo, tmp_path, {"D1_MAX_STMT_BYTES": "3500"})
    for statement in _statements(sql):
        assert len(statement.encode("utf-8")) < 90000
    with sqlite3.connect(":memory:") as remote:
        remote.executescript(sql)
        assert remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall() == \
            _expected(script, repo, tmp_path, table)
