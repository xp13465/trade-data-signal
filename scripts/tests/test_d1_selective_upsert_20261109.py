# -*- coding: utf-8 -*-
"""真脚本生成包重放：三条互补 upsert 语句的隔离/落库/重试语义。

2026-11-09 建(两语句) → 2026-11-16 写放大瘦身改为三语句(零语义变更):
  A composite 索引语句: fund_type/scale(screener) 或 fund_type(score) 未变、composite_score 变
  B 全列语句        : fund_type 或 scale(screener) 变
  C 非索引语句      : 索引列全未变、其它列变(原语句不变)
断言: 索引列没变不更新索引列; 索引列变走全列; 同一行只被一条语句更新一次; 重试幂等。
2026-11-16 复查: 改为**客户端分流**(每行只生成一条语句, 包体回到每行一份) —— 同一行全包
恰好出现 1 次(E1); 代价是「包生成后被外部改过索引键」的行本轮不会被硬覆盖, 下一轮同步按
读回值走 B 全列 SET 自愈(本文件有断言锁住这条收敛路径)。
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
        # E1 独立复核: 每条参与写入的 fund_code 在整个数据包里恰好出现 1 次(不是 0/2/3 次)。
        expected_codes = [r[0] for r in expected]
        per_code = {code: sum(stmt.count("('%s'," % code) for stmt in data)
                    for code in expected_codes}
        assert all(n == 1 for n in per_code.values()), per_code
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
        # 2026-11-16 客户端路由: 本样本无索引列变化 ⇒ 只有 A(真·新增 NEW 行) + C(改名的存量行)
        # 两条语句; B 桶为空 ⇒ 不生成语句(旧版每行三份才有三条)。
        assert len(data) == 2, "小样应形成 新增(A) / 非索引(C) 两条完整语句"
        by_kind = {_kind(s, table): s for s in data}
        assert set(by_kind) == {"A", "C"}, by_kind
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
        # 模拟包生成与导入之间另一份完整状态修改索引键；C 必须基于当前值拒绝套用旧 hash。
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
        # 重试整个包：其余行由 C 补回; 被外部改过索引键的那一行**本轮不硬覆盖**
        # (客户端路由基于上一次读回的旧值, 包里没有它的 B 语句。旧三份版靠 B 同轮打回;
        # 代价是包体 +50% 撞 300s 墙, 故接受「下一轮同步自愈」——见下面断言)。
        remote.executescript(sql)
        final = remote.execute(f"SELECT * FROM {table} ORDER BY fund_code").fetchall()
        exp_by_code = {r[0]: r for r in expected}
        assert all(r == exp_by_code[r[0]] for r in final if r[0] != code)
        assert next(r for r in final if r[0] == code) == intervening, "本轮不得硬覆盖外部改动"
        # 下一轮同步(生产每日 16:00, 周更周日 03:17; 单写者 + 脚本锁, 外部改索引键的行下一轮自愈,
        # 最长陈旧约 24h): 读回当前 D1 行 ⇒ 该行索引列与本地不同 ⇒ 走 B 全列 SET 收敛。
        base._save_hashes(remote, table, mock)
        _, sql_next = base._generate(script, repo, tmp_path, {"D1_EXISTING_HASHES_FILE": str(mock)})
        remote.executescript(sql_next)
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
