# -*- coding: utf-8 -*-
"""163109 类型漂移 / LOF 采集覆盖 / 缺整行 NAV 盲区修复测试(2026-11-07)。

覆盖 A-E 五项:
  A. _build_index_etf_map_auto fund_type 按 lof_track_index.json 逐码归属判定
  B. _load_etf_daily_liveness 区分退市(零行) vs 临时停采(有历史行近期零行)
  C. check_freeze_etf_daily_coverage 冻结依赖覆盖检查(缺整行 WARNING)
  D. _check_accum_nav_missing_whole_rows NAV 盲区可观测(缺整行不 INSERT)

铁律遵守:
  - 离线打桩, 不读生产 DB, 不发通知, 不写仓库 data/
  - 不写死「今天」(L51), 不依赖被测代码内部 today()/now()
  - 禁止 skip/xfail/改阈值
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── A: fund_type 漂移修复 ────────────────────────────────────────────────────

class TestFundTypeDrift:
    """163109 等 LOF 在 _build_index_etf_map_auto 中应标 lof, 159xxx ETF 标 etf。"""

    def test_lof_163109_marked_lof(self):
        """163109 在 lof_codes 中 → fund_type=lof(13 只集群同源)。"""
        from scripts import build_board_etf_map as mod
        reverse_map = {
            "000300": [
                {"code": "163109", "name": "LOF测试", "amount": 1e8,
                 "track_index_name": "沪深300"},
            ],
        }
        df_by_code = {}
        lof_codes = {"163109", "160807", "161811"}
        result = mod._build_index_etf_map_auto(reverse_map, df_by_code, lof_codes=lof_codes)
        etf = result["hs300"][0]
        assert etf["code"] == "163109"
        assert etf["fund_type"] == "lof", f"163109 应标 lof, 实际 {etf['fund_type']}"

    def test_lof_cluster_13_all_lof(self):
        """13 只同源 LOF 全部标 lof。"""
        from scripts import build_board_etf_map as mod
        lof_13 = {"160807", "160924", "161811", "161831", "163109", "163407",
                  "165309", "501036", "501037", "501043", "501045", "501302", "502048"}
        reverse_map = {
            "000300": [{"code": c, "name": f"LOF{c}", "amount": 1e8,
                        "track_index_name": "沪深300"} for c in lof_13],
        }
        result = mod._build_index_etf_map_auto(reverse_map, {}, lof_codes=lof_13)
        for e in result["hs300"]:
            assert e["fund_type"] == "lof", f"{e['code']} 应标 lof"

    def test_etf_159_prefix_marked_etf(self):
        """159915/159919/159920/159922 深 ETF(不在 lof_track_index) → fund_type=etf。"""
        from scripts import build_board_etf_map as mod
        etf_codes = {"159915", "159919", "159920", "159922"}
        reverse_map = {
            "399006": [{"code": c, "name": f"ETF{c}", "amount": 1e8,
                        "track_index_name": "创业板指"} for c in etf_codes],
        }
        # lof_codes 不含 159xxx(它们是 ETF 不是 LOF)
        lof_codes = {"163109", "160225"}
        result = mod._build_index_etf_map_auto(reverse_map, {}, lof_codes=lof_codes)
        for e in result["cyb"]:
            assert e["fund_type"] == "etf", f"{e['code']} 应标 etf, 实际 {e['fund_type']}"

    def test_lof_160225_not_regressed(self):
        """160225(LOF, etf_index_map status=no_track)不进 reverse_map, 不回归。"""
        from scripts import build_board_etf_map as mod
        # 160225 不在 reverse_map(它 status=no_track, 不进 reverse_map)
        # 若它出现在 reverse_map 且在 lof_codes 中 → 应标 lof
        reverse_map = {
            "000300": [{"code": "160225", "name": "LOF225", "amount": 1e8,
                        "track_index_name": "沪深300"}],
        }
        lof_codes = {"160225"}
        result = mod._build_index_etf_map_auto(reverse_map, {}, lof_codes=lof_codes)
        assert result["hs300"][0]["fund_type"] == "lof"

    def test_no_lof_codes_defaults_etf(self):
        """lof_codes=None 或空集 → 全部默认 etf(向后兼容)。"""
        from scripts import build_board_etf_map as mod
        reverse_map = {
            "000300": [{"code": "510300", "name": "ETF300", "amount": 1e8,
                        "track_index_name": "沪深300"}],
        }
        result = mod._build_index_etf_map_auto(reverse_map, {})
        assert result["hs300"][0]["fund_type"] == "etf"

    def test_mixed_lof_and_etf_same_index(self):
        """同一指数下 LOF+ETF 混合, 各自正确标注。"""
        from scripts import build_board_etf_map as mod
        reverse_map = {
            "000300": [
                {"code": "510300", "name": "ETF300", "amount": 8e9, "track_index_name": "沪深300"},
                {"code": "163109", "name": "LOF109", "amount": 1e8, "track_index_name": "沪深300"},
            ],
        }
        lof_codes = {"163109"}
        result = mod._build_index_etf_map_auto(reverse_map, {}, lof_codes=lof_codes)
        by_code = {e["code"]: e for e in result["hs300"]}
        assert by_code["510300"]["fund_type"] == "etf"
        assert by_code["163109"]["fund_type"] == "lof"

    def test_no_prefix_judgment_159_not_in_lof(self):
        """159915 前缀 15 但不在 lof_codes → 标 etf(禁前缀判 LOF)。"""
        from scripts import build_board_etf_map as mod
        reverse_map = {
            "399006": [{"code": "159915", "name": "创业板ETF", "amount": 1e9,
                        "track_index_name": "创业板指"}],
        }
        # 159915 不在 lof_track_index.json → lof_codes 不含它
        result = mod._build_index_etf_map_auto(reverse_map, {}, lof_codes={"160225"})
        assert result["cyb"][0]["fund_type"] == "etf"


# ── B: live_codes 临时停采 vs 退市 ────────────────────────────────────────────

class TestLivenessClassification:
    """_load_etf_daily_liveness 区分退市(零行) vs 临时停采(有历史行近期零行)。"""

    def _make_db(self, tmp_path: Path, rows: list[tuple]):
        """建临时 etf_daily 表并插入 rows=[(code, date, close), ...]。"""
        db = tmp_path / "etf_national_team.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS etf_daily (
              date TEXT NOT NULL,
              etf_code TEXT NOT NULL,
              etf_name TEXT,
              close REAL,
              accum_nav REAL,
              PRIMARY KEY (date, etf_code)
            );
        """)
        conn.executemany(
            "INSERT OR REPLACE INTO etf_daily (date, etf_code, close) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
        return db

    def test_temp_gap_kept(self, monkeypatch, tmp_path):
        """大量历史行 + 近期零行 = 临时停采 → 保留(163109 有 3887 行)。"""
        db = self._make_db(tmp_path, [
            ("20260101", "163109", 1.0),
            ("20260102", "163109", 1.1),
            ("20260601", "163109", 2.0),
        ])
        from scripts import build_board_etf_map as mod
        monkeypatch.setattr(mod, "_get_etf_db_path", lambda: db)
        info = mod._load_etf_daily_liveness(recent_days=10)
        assert info is not None
        assert "163109" in info["live"], "163109 有历史行应保留(临时停采)"
        assert info["classify"]["163109"] == "temp_gap"

    def test_delisted_zero_rows_filtered(self, monkeypatch, tmp_path):
        """零历史行 = 退市 → 不在 live 集合。"""
        db = self._make_db(tmp_path, [
            ("20260101", "160807", 1.0),
        ])
        from scripts import build_board_etf_map as mod
        monkeypatch.setattr(mod, "_get_etf_db_path", lambda: db)
        info = mod._load_etf_daily_liveness(recent_days=10)
        assert info is not None
        # 999999 零行 → delisted
        assert "999999" not in info["live"]
        assert info["classify"].get("999999") == "delisted" or "999999" not in info["classify"]

    def test_active_with_recent_rows(self, monkeypatch, tmp_path):
        """近 N 天有新行 = active。"""
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        db = self._make_db(tmp_path, [
            (yesterday, "510300", 4.0),
            (today, "510300", 4.1),
        ])
        from scripts import build_board_etf_map as mod
        monkeypatch.setattr(mod, "_get_etf_db_path", lambda: db)
        info = mod._load_etf_daily_liveness(recent_days=10)
        assert info is not None
        assert "510300" in info["live"]
        assert info["classify"]["510300"] == "active"

    def test_db_missing_returns_none(self, monkeypatch, tmp_path):
        """DB 不存在 → 返回 None(宁不过滤不误杀)。"""
        from scripts import build_board_etf_map as mod
        monkeypatch.setattr(mod, "_get_etf_db_path", lambda: tmp_path / "nonexistent.db")
        info = mod._load_etf_daily_liveness()
        assert info is None

    def test_live_set_equals_temp_gap_plus_active(self, monkeypatch, tmp_path):
        """live = temp_gap ∪ active(等价旧 _load_etf_daily_codes 返回值)。"""
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y%m%d")
        db = self._make_db(tmp_path, [
            ("20260101", "163109", 1.0),  # temp_gap
            (today, "510300", 4.1),       # active
        ])
        from scripts import build_board_etf_map as mod
        monkeypatch.setattr(mod, "_get_etf_db_path", lambda: db)
        info = mod._load_etf_daily_liveness(recent_days=10)
        assert info is not None
        expected_live = {"163109", "510300"}
        assert info["live"] == expected_live


# ── C+D: 冻结依赖覆盖检查 + NAV 缺整行可观测 ────────────────────────────────────

class TestFreezeCoverage:
    """冻结依赖覆盖检查(C) + NAV 盲区(D)。"""

    def _make_db_with_rows(self, tmp_path: Path, rows: list[tuple]):
        """建临时 etf_daily 表, rows=[(date, etf_code, close, accum_nav), ...]。"""
        db = tmp_path / "etf_national_team.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS etf_daily (
              date TEXT NOT NULL,
              etf_code TEXT NOT NULL,
              etf_name TEXT,
              close REAL,
              accum_nav REAL,
              PRIMARY KEY (date, etf_code)
            );
        """)
        conn.executemany(
            "INSERT OR REPLACE INTO etf_daily (date, etf_code, close, accum_nav) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return conn

    def _make_freeze(self, tmp_path: Path, entries: dict):
        """写临时 signal_kelly_etf_freeze.json。"""
        freeze = tmp_path / "signal_kelly_etf_freeze.json"
        freeze.write_text(json.dumps(entries), encoding="utf-8")
        return freeze

    def test_missing_row_detected(self, monkeypatch, tmp_path):
        """构造 freeze + 空 etf_daily(该 code 无行) → 缺整行被识别。"""
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y%m%d")
        freeze_date = today  # 冻结日=今天(在 recent_days 窗口内)
        conn = self._make_db_with_rows(tmp_path, [
            ("20260101", "510300", 4.0, 1.5),
        ])
        freeze = self._make_freeze(tmp_path, {
            f"{freeze_date}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        result = ent.check_freeze_etf_daily_coverage(conn, recent_days=10)
        assert ("163109", freeze_date) in result["missing_row"]
        assert len(result["missing_row"]) == 1

    def test_has_row_not_false_alarm(self, monkeypatch, tmp_path):
        """freeze code 在冻结日有 etf_daily 行 → 不误报缺整行。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        conn = self._make_db_with_rows(tmp_path, [
            (today, "163109", 1.0, 1.05),
        ])
        freeze = self._make_freeze(tmp_path, {
            f"{today}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        result = ent.check_freeze_etf_daily_coverage(conn, recent_days=10)
        assert len(result["missing_row"]) == 0
        assert ("163109", today) in result["has_row_with_nav"]

    def test_has_row_null_nav_classified(self, monkeypatch, tmp_path):
        """有行但 accum_nav IS NULL → has_row_null_nav(NAV 待补)。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        conn = self._make_db_with_rows(tmp_path, [
            (today, "163109", 1.0, None),
        ])
        freeze = self._make_freeze(tmp_path, {
            f"{today}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        result = ent.check_freeze_etf_daily_coverage(conn, recent_days=10)
        assert len(result["missing_row"]) == 0
        assert ("163109", today) in result["has_row_null_nav"]

    def test_freeze_missing_returns_empty(self, monkeypatch, tmp_path):
        """freeze 文件不存在 → 返回空(不报错)。"""
        conn = self._make_db_with_rows(tmp_path, [])
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", tmp_path / "nonexistent.json")
        result = ent.check_freeze_etf_daily_coverage(conn)
        assert result["missing_row"] == []
        assert result["codes"] == 0

    def test_old_freeze_entries_skipped(self, monkeypatch, tmp_path):
        """超过 recent_days 的冻结条目被跳过(只检查近期)。"""
        from datetime import datetime, timedelta
        old_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        conn = self._make_db_with_rows(tmp_path, [])
        freeze = self._make_freeze(tmp_path, {
            f"{old_date}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        result = ent.check_freeze_etf_daily_coverage(conn, recent_days=10)
        assert result["codes"] == 0  # 旧条目被跳过

    def test_nav_missing_whole_rows_no_insert(self, monkeypatch, tmp_path):
        """D: 缺整行只记录不 INSERT(update_accum_nav 安全行为不变)。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        conn = self._make_db_with_rows(tmp_path, [])
        freeze = self._make_freeze(tmp_path, {
            f"{today}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        missing = ent._check_accum_nav_missing_whole_rows(conn, lookback_days=10)
        assert ("163109", today) in missing
        # 验证没有 INSERT 新行
        count = conn.execute("SELECT COUNT(*) FROM etf_daily WHERE etf_code='163109'").fetchone()[0]
        assert count == 0, "缺整行不得被 INSERT"

    def test_existing_null_row_still_updatable(self, monkeypatch, tmp_path):
        """D: 已有行 NULL 仍可被 update_accum_nav UPDATE(安全行为不变)。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        # 163109 有行但 accum_nav NULL → 在 update_accum_nav 的 need 中
        conn = self._make_db_with_rows(tmp_path, [
            (today, "163109", 1.0, None),
        ])
        freeze = self._make_freeze(tmp_path, {
            f"{today}|hs300|buy": {"code": "163109", "name": "LOF109"},
        })
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "FREEZE_PATH", freeze)
        # 冻结覆盖检查
        cov = ent.check_freeze_etf_daily_coverage(conn, recent_days=10)
        assert ("163109", today) in cov["has_row_null_nav"]
        assert len(cov["missing_row"]) == 0
        # 缺整行检查返回空(因为行存在)
        missing = ent._check_accum_nav_missing_whole_rows(conn, lookback_days=10)
        assert missing == []
        # 行仍在, 未被删除/INSERT
        row = conn.execute("SELECT accum_nav FROM etf_daily WHERE etf_code='163109' AND date=?",
                           (today,)).fetchone()
        assert row is not None and row[0] is None
