"""SQLite 连接与建表。"""
import os
import sqlite3
from pathlib import Path

# 仓库根。刻意**不**用 resolve():从 trade-data/ 运行(__file__ 落在 trade-data/app/,
# 该目录是 trade/app 的 symlink)时,只有保留 symlink 路径才能把本仓定位到实时数据树;
# realpath 会把它折回 trade/,读到的是陈旧镜像。
_HERE = Path(__file__).absolute().parent.parent

# #335 根因:旧版直接把 DB_PATH 定死成「本仓 data/sentiment.db」,路径推导错(worktree /
# 非 trade-data 树 / symlink 视角)时会 mkdir + sqlite3.connect 静默建出 0 字节空库,
# 之后所有查询返回空结果集而不报错,读方拿不到「库不在」的信号。
# 现在改为:首次 get_conn() 时按 resolve_db_path() 的解析阶梯找真实库,全都不存在就
# 明确报错;DB_PATH 仅作为「尚未解析」的哨兵(兼容既有 from app.db import DB_PATH 的读方,
# 也兼容测试 monkeypatch.setattr(app.db, "DB_PATH", tmp) 的显式覆盖)。
_DEFAULT_DB_PATH = _HERE / "data" / "sentiment.db"
DB_PATH = _DEFAULT_DB_PATH

_resolved_db_path: Path | None = None

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

-- 期货同向准确度每日趋势（2026-07-20 加）：追踪 compute_role_ih_detail 的15日窗口
-- accuracy/dominant_dir 恒>=50%（取 same/contrarian 较大者为基准），看不出"同向失效"；
-- follow_ratio = same_count/total*100 可跌破50%，直接反映"同向越来越不准=风格转逆向"。
-- 每日每角色一行（INSERT OR REPLACE 按 date+role 去重，同日重算覆盖）。
CREATE TABLE IF NOT EXISTS futures_ih_detail_acc (
  date TEXT NOT NULL,
  role TEXT NOT NULL,
  dominant_dir TEXT,
  total INTEGER,
  same_count INTEGER,
  contrarian_count INTEGER,
  correct_count INTEGER,
  wrong_count INTEGER,
  accuracy REAL,
  follow_ratio REAL,
  sample_start TEXT,
  sample_end TEXT,
  PRIMARY KEY (date, role)
);
CREATE INDEX IF NOT EXISTS idx_futures_ih_detail_acc_date ON futures_ih_detail_acc(date);

-- 盘中实时快照：单行覆盖（id=1 CHECK 强制只保留最新一行）。
-- indices/industries/concepts/us_futures/global_realtime 存 JSON 字符串。每次采集 UPSERT 覆盖，体现"最新快照"语义。
-- global_realtime (2026-07-31 加)：全球指数实时报价(德法DAX/CAC40等)，防 export.py reload 丢失致前端角标无实时数据。
CREATE TABLE IF NOT EXISTS intraday_snapshot (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  collected_at TEXT NOT NULL,
  is_closed INTEGER NOT NULL,
  indices TEXT NOT NULL,
  industries TEXT NOT NULL,
  concepts TEXT,
  us_futures TEXT,
  global_realtime TEXT
);

-- 盘中信号生命周期日志（2026-08-10 加）：intraday_snapshot._recompute_signals 每轮
-- 重算后追加当日 (time, index_id, signal, reason) 快照（HH:MM 时间戳），
-- 供收盘邮件（check_signals.py 收盘模式）生成"每个信号几点出现/几点消失"时间线。
-- 每轮 append 不覆盖（signal_daily 是 DELETE+INSERT 覆盖只存最终态，本表保留过程历史）。
CREATE TABLE IF NOT EXISTS signal_intraday_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  time TEXT NOT NULL,
  index_id TEXT NOT NULL,
  signal TEXT NOT NULL,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_signal_intraday_log_date ON signal_intraday_log(date);

-- 历史行改写审计（2026-10-14 加，根治「重算抹除历史行」不可见）：记录 signal_daily /
-- index_daily 的「历史行(date < 运行日)在重算/整段重写前后发生消失 / 出现 / 值改写」事件。
-- 写方 app/history_audit.py；只留痕 + 告警，不阻断任何重算/采集（见该模块 docstring）。
CREATE TABLE IF NOT EXISTS history_overwrite_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  detected_at TEXT NOT NULL,
  run_date TEXT NOT NULL,        -- 触发本次审计的运行日(本地 YYYYMMDD)
  src_table TEXT NOT NULL,       -- signal_daily / index_daily
  kind TEXT NOT NULL,            -- disappeared / appeared / changed
  date TEXT NOT NULL,            -- 被改写的历史行日期(date < run_date)
  index_id TEXT NOT NULL,
  signal TEXT,                   -- 仅 signal_daily 有
  before_val TEXT,
  after_val TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_overwrite_audit_date ON history_overwrite_audit(date);
CREATE INDEX IF NOT EXISTS idx_history_overwrite_audit_run ON history_overwrite_audit(run_date);
"""


_schema_ensured = False


def _is_usable_db(p: Path) -> bool:
    """候选是否是一个真正可用的库文件。

    0 字节文件也算「不可用」:那正是旧版静默建空库留下的残骸,打开它查询只会得到
    空结果集,必须当缺库处理(#335)。
    """
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _db_candidates() -> list[tuple[str, Path]]:
    """解析阶梯候选(按优先级,去重保序)。"""
    cands: list[tuple[str, Path]] = []
    for var in ("TRADE_SENTIMENT_DB", "REPO", "MAIN_REPO"):
        raw = os.environ.get(var)
        if not raw:
            continue
        p = Path(raw).expanduser()
        # TRADE_SENTIMENT_DB 是「库文件路径」;REPO/MAIN_REPO 是「仓库根」。
        cands.append((var, p if var == "TRADE_SENTIMENT_DB" else p / "data" / "sentiment.db"))
    cands.append(("兄弟仓 ../trade-data", _HERE.parent / "trade-data" / "data" / "sentiment.db"))
    cands.append(("本仓 data", _DEFAULT_DB_PATH))
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for src, p in cands:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append((src, p))
    return out


def resolve_db_path() -> Path:
    """按解析阶梯找真实的 sentiment.db;全都不存在则明确报错(#335)。

    阶梯(按序,第一个「存在且非空的普通文件」胜出):
      ① TRADE_SENTIMENT_DB —— 显式指定的库文件路径(最高优先;设了但无效 → 直接报错,
         绝不静默回退到别的库,免得读错数据)
      ② REPO/data/sentiment.db —— 云上 systemd unit 全量注入 REPO,本机手动跑也可显式指定
      ③ MAIN_REPO/data/sentiment.db —— 云上同规注入(双仓布局)
      ④ 兄弟仓 ../trade-data/data/sentiment.db —— 本机 trade/ 与 trade-data/ 双树布局
      ⑤ 本仓 data/sentiment.db
    全部不存在 ⇒ raise SystemExit 明说「找不到库」并列出每个候选的状态与修法,**绝不建空库**。
    """
    global _resolved_db_path
    if _resolved_db_path is not None:
        return _resolved_db_path

    explicit = os.environ.get("TRADE_SENTIMENT_DB")
    if explicit:
        p = Path(explicit).expanduser()
        if _is_usable_db(p):
            _resolved_db_path = p
            return p
        raise SystemExit(
            f"TRADE_SENTIMENT_DB={p} 指向的 sentiment.db 不存在 / 不是普通文件 / 为 0 字节。\n"
            "已停止:不会创建空库(#335)。请把它指向真实的 sentiment.db。"
        )

    candidates = _db_candidates()
    for _src, p in candidates:
        if _is_usable_db(p):
            _resolved_db_path = p
            return p

    lines = ["找不到 sentiment.db,已停止(拒绝静默创建 0 字节空库,#335)。候选清单:"]
    for src, p in candidates:
        if not p.exists():
            state = "不存在"
        elif not p.is_file():
            state = "不是普通文件"
        elif p.stat().st_size == 0:
            state = "0 字节空库(旧版静默建库的残骸,视为缺库)"
        else:
            state = "不可用"
        lines.append(f"  - {src}: {p} → {state}")
    lines.append("修法:把真实库放到上述任一位置,或显式指定其一:")
    lines.append("  export TRADE_SENTIMENT_DB=/path/to/sentiment.db")
    lines.append("  export REPO=/path/to/repo   # 该仓 data/sentiment.db")
    raise SystemExit("\n".join(lines))


def get_conn() -> sqlite3.Connection:
    """统一 DB 连接入口：首次调用时按 resolve_db_path() 解析真实库(找不到直接报错,
    绝不建空库,#335),再自动建表 + 迁移(幂等),保证 clone 仓库后首次跑任何采集/脚本
    都不会缺列。后续调用仅返回连接(_schema_ensured 标志避免重复开销,幂等操作
    多线程/多进程并发也安全)。
    """
    global _schema_ensured, DB_PATH
    # DB_PATH 仍是未解析哨兵 ⇒ 按阶梯解析(找不到直接报错,不建空库)。
    # 调用方/测试已显式改写 DB_PATH(≠ 哨兵)则尊重其值,允许在指定路径上新建库
    # (既有测试 fixture 用法,如 monkeypatch.setattr(app.db, "DB_PATH", tmp))。
    if DB_PATH == _DEFAULT_DB_PATH:
        DB_PATH = resolve_db_path()
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

    # index_daily.source 列（2026-10-14 加，T5 占位行 source 标记）：区分「行情源真实价」
    # (collect) / 「盘中快照反哺」(intraday_snapshot) / 「计算法合成」(calc，如
    # close=prev_close×(1+pct/100)），让下游可识别占位/合成行，从源头减少「先有信号、
    # 后无信号」的假事件。旧行 source 为 NULL = 未标注(历史存量)。
    if "source" not in cols:
        try:
            conn.execute("ALTER TABLE index_daily ADD COLUMN source TEXT")
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

    # intraday_snapshot.global_realtime 列（2026-07-31 加，全球指数实时报价入库）
    # 根因：_save_db INSERT 只写6字段无 global_realtime，export.py reload 读 DB 生成
    # intraday_snapshot.json 丢失 global_realtime，致前端德法角标无实时数据 + reload 覆盖实时版。
    # 加列后 _save_db INSERT + load_latest_snapshot SELECT 均补 global_realtime，reload 不再丢失。
    if "global_realtime" not in snap_cols:
        try:
            conn.execute("ALTER TABLE intraday_snapshot ADD COLUMN global_realtime TEXT")
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
