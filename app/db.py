"""SQLite 连接与建表。"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sentiment.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metric (
  date TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  value REAL,
  source TEXT,
  updated_at TEXT,
  PRIMARY KEY (date, metric_id)
);
CREATE INDEX IF NOT EXISTS idx_daily_metric_id ON daily_metric(metric_id);

CREATE TABLE IF NOT EXISTS index_daily (
  date TEXT NOT NULL,
  index_id TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  pct_change REAL, amount REAL, net_inflow REAL,
  PRIMARY KEY (date, index_id)
);
CREATE INDEX IF NOT EXISTS idx_index_daily_id ON index_daily(index_id);

CREATE TABLE IF NOT EXISTS board_daily (
  date TEXT NOT NULL,
  board_type TEXT NOT NULL,
  board_name TEXT NOT NULL,
  pct_change REAL,
  net_inflow REAL,
  PRIMARY KEY (date, board_type, board_name)
);

CREATE TABLE IF NOT EXISTS score_daily (
  date TEXT NOT NULL,
  score_id TEXT NOT NULL,
  value REAL,
  is_freeze INTEGER,
  is_overheat INTEGER,
  components TEXT,
  updated_at TEXT,
  PRIMARY KEY (date, score_id)
);

CREATE TABLE IF NOT EXISTS signal_daily (
  date TEXT NOT NULL,
  index_id TEXT NOT NULL,
  signal TEXT NOT NULL,
  reason TEXT,
  PRIMARY KEY (date, index_id, signal)
);

CREATE TABLE IF NOT EXISTS manual_entry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  value REAL,
  note TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS collect_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  metric_id TEXT,
  status TEXT,
  message TEXT,
  run_at TEXT
);

CREATE TABLE IF NOT EXISTS alert_log (
  date TEXT PRIMARY KEY,
  a_sentiment REAL,
  cross_market REAL,
  alert_type TEXT
);

CREATE TABLE IF NOT EXISTS industry_width_daily (
  industry_code TEXT NOT NULL,
  date TEXT NOT NULL,
  up_count INTEGER,
  down_count INTEGER,
  zt_count INTEGER,
  dt_count INTEGER,
  zb_count INTEGER,
  seal_rate REAL,
  amount REAL,
  updated_at TEXT,
  PRIMARY KEY (industry_code, date)
);
CREATE INDEX IF NOT EXISTS idx_industry_width_date ON industry_width_daily(date);
CREATE INDEX IF NOT EXISTS idx_industry_width_ind ON industry_width_daily(industry_code);

CREATE TABLE IF NOT EXISTS futures_position (
  date TEXT NOT NULL,
  variety TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'top20',
  total_long REAL,
  total_short REAL,
  net_position REAL,
  net_ratio REAL,
  long_chg REAL,
  short_chg REAL,
  contract_count INTEGER,
  source TEXT DEFAULT 'akshare',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  PRIMARY KEY (date, variety, role)
);

CREATE TABLE IF NOT EXISTS futures_accuracy (
  date TEXT NOT NULL,
  variety TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'top20',
  index_id TEXT NOT NULL,
  window INTEGER NOT NULL,
  follow_accuracy REAL,
  contrarian_accuracy REAL,
  follow_n INTEGER,
  contrarian_n INTEGER,
  net_direction TEXT,
  actual_return REAL,
  PRIMARY KEY (date, variety, role, index_id, window)
);

-- 盘中实时快照：单行覆盖（id=1 CHECK 强制只保留最新一行）。
-- indices/industries/concepts/us_futures 存 JSON 字符串。每次采集 UPSERT 覆盖，体现"最新快照"语义。
CREATE TABLE IF NOT EXISTS intraday_snapshot (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  collected_at TEXT NOT NULL,
  is_closed INTEGER NOT NULL,
  indices TEXT NOT NULL,
  industries TEXT NOT NULL,
  concepts TEXT,
  us_futures TEXT
);
"""


_schema_ensured = False


def get_conn() -> sqlite3.Connection:
    """统一 DB 连接入口：首次调用时自动建表 + 迁移（幂等），保证 clone 仓库后
    首次跑任何采集/脚本都不会缺列。后续调用仅返回连接（_schema_ensured 标志
    避免重复开销，幂等操作多线程/多进程并发也安全）。
    """
    global _schema_ensured
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    # busy_timeout=30s：多 pipeline 并发写 sentiment.db 时写锁串行化自动重试，
    # 避免立即抛 "database is locked"（WAL 允许并发读 + 单写排队）。
    conn.execute("PRAGMA busy_timeout=30000;")
    if not _schema_ensured:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
        _schema_ensured = True
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """增量迁移：对已存在的旧 DB 补字段（CREATE TABLE IF NOT EXISTS 不会加列）。
    并发首跑容错：多进程同时首次 get_conn 都检测到缺列都跑 ALTER，第二个报
    duplicate column name，忽略即可（另一进程已加列）。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(index_daily)")}
    if "net_inflow" not in cols:
        try:
            conn.execute("ALTER TABLE index_daily ADD COLUMN net_inflow REAL")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                pass  # 并发首跑竞态，另一进程已加列，忽略
            else:
                raise

    # intraday_snapshot.concepts 列（2026-07-15 加，盘中概念实时数据入库）
    snap_cols = {row["name"] for row in conn.execute("PRAGMA table_info(intraday_snapshot)")}
    if "concepts" not in snap_cols:
        try:
            conn.execute("ALTER TABLE intraday_snapshot ADD COLUMN concepts TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                pass  # 并发首跑竞态，忽略
            else:
                raise

    # intraday_snapshot.us_futures 列（2026-07-15 加，美股期货 ES/NQ 预估美股方向入库）
    if "us_futures" not in snap_cols:
        try:
            conn.execute("ALTER TABLE intraday_snapshot ADD COLUMN us_futures TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                pass  # 并发首跑竞态，忽略
            else:
                raise


def init_db() -> None:
    conn = get_conn()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
