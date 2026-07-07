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
  pct_change REAL, amount REAL,
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
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
