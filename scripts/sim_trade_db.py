#!/usr/bin/env python3
"""sim_trade_db.py - A 模式信号触发模拟交易账本: 建库/DDL/append-only 触发器/视图。

设计权威: docs/auto-trade/sim-trade-trigger-design-20261120.md(2026-11-20 调研报告
`/tmp/trigger-sim-research-20261120.md` §3/§4 的落地实现)。

核心约定:
  - 独立库 data/sim_trade.db, 不碰 sentiment.db / etf_national_team.db 任何一行。
  - 4 张表只允许 INSERT OR IGNORE; 状态流转/纠错一律追加 sim_trade_event 或
    supersedes_* 新行, 绝不 UPDATE/DELETE。
  - BEFORE UPDATE / BEFORE DELETE × 4 表 = 8 条 RAISE(ABORT) 触发器兜底。
    (禁用 INSERT OR REPLACE: REPLACE 命中冲突会先 DELETE 旧行 → 被 DELETE 触发器 ABORT。)
  - 确定性 ID = sha1(业务键拼接)[:32], 重跑幂等。

用法:
  python3 scripts/sim_trade_db.py --init --db data/sim_trade.db
  python3 scripts/sim_trade_db.py --check --db data/sim_trade.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

TABLE_DDL = [
    # 3.1 触发定格: 一笔信号一行
    """
CREATE TABLE IF NOT EXISTS sim_trade_signal (
  signal_id          TEXT PRIMARY KEY,          -- sha1(strategy|signal_date|exec_date|etf_code|plan_hash)[:32]
  schema_version     INTEGER NOT NULL DEFAULT 1,
  strategy           TEXT NOT NULL DEFAULT 'A', -- A 模式
  signal_date        TEXT NOT NULL,             -- T(YYYYMMDD)
  exec_date          TEXT NOT NULL,             -- T+1 预期买入日
  sell_due_date      TEXT NOT NULL,             -- D+10 预期卖出日
  index_id           TEXT NOT NULL,
  etf_code           TEXT NOT NULL,
  etf_name           TEXT,
  signal             TEXT,                      -- buy/buy_aux/buy_special/buy_backup
  track_score        REAL,
  rating             TEXT,                      -- high/mid/low
  bk_ts              REAL,                      -- 冻结分
  track_tier         TEXT,
  late               INTEGER NOT NULL DEFAULT 0,
  source             TEXT NOT NULL,             -- log/replay/backfill
  s06_effective_mode TEXT,                      -- a9/new14
  s06_decision_date  TEXT,
  s06_state_generated_at TEXT,
  s06_state_sha256   TEXT,
  fade_mode          TEXT NOT NULL DEFAULT 's06',
  fade_keyset_hash   TEXT,
  universe_pass      INTEGER,                   -- 1 通过入样宇宙
  fade_pass          INTEGER,                   -- 1 通过 AI 降亏
  k_cap              INTEGER NOT NULL DEFAULT 1,
  k_rank             INTEGER,                   -- 当日 K 排名
  amount             REAL NOT NULL DEFAULT 10000,
  plan_prev_close    REAL,                      -- 触发时定格的昨收(挂单价上限)
  signal_accum_nav   REAL,                      -- T 日 accum_nav(等价换算基准)
  signal_close_raw   REAL,                      -- T 日原始 close(等价换算基准)
  plan_hash          TEXT,                      -- nextday_plan 条目/文件 hash
  day_snapshot_hash  TEXT,
  frozen_at          TEXT NOT NULL,             -- 触发时刻(ISO)
  trigger_source     TEXT NOT NULL,             -- nextday_plan.json/manual/backfill
  supersedes_signal_id TEXT,                    -- 计划变更时新行指向旧行
  revision           INTEGER NOT NULL DEFAULT 1,
  note               TEXT,
  created_at         TEXT NOT NULL
)
""",
    "CREATE INDEX IF NOT EXISTS idx_sim_signal_exec ON sim_trade_signal(exec_date)",
    "CREATE INDEX IF NOT EXISTS idx_sim_signal_code ON sim_trade_signal(etf_code)",
    "CREATE INDEX IF NOT EXISTS idx_sim_signal_sd ON sim_trade_signal(signal_date)",
    # 3.2 操作指令(预留交易软件对接)
    """
CREATE TABLE IF NOT EXISTS sim_trade_order (
  order_id           TEXT PRIMARY KEY,          -- sha1(signal_id|side|intended_at|qty|price_type|limit_price)[:32]
  signal_id          TEXT NOT NULL,
  strategy           TEXT NOT NULL DEFAULT 'A',
  side               TEXT NOT NULL CHECK(side IN ('buy','sell')),
  action             TEXT NOT NULL,             -- open/close(未来扩展)
  etf_code           TEXT NOT NULL,
  etf_name           TEXT,
  qty_plan           REAL,                      -- 计划份额(100 份整手)
  qty_unit           TEXT NOT NULL DEFAULT 'share',
  amount             REAL,                      -- 计划金额
  price_type         TEXT NOT NULL DEFAULT 'market', -- market/limit
  limit_price        REAL,
  intended_at        TEXT NOT NULL,             -- 09:30/14:55
  triggered_at       TEXT NOT NULL,             -- 实际插入时刻
  trigger_source     TEXT NOT NULL,
  broker_account     TEXT,                      -- 预留
  broker_order_id    TEXT,                      -- 预留
  request_payload    TEXT,                      -- 未来交易软件原始指令 JSON
  response_payload   TEXT,                      -- 未来回执 JSON
  initial_status     TEXT NOT NULL DEFAULT 'submitted', -- 初始态; 后续状态走 event
  created_at         TEXT NOT NULL,
  FOREIGN KEY(signal_id) REFERENCES sim_trade_signal(signal_id)
)
""",
    "CREATE INDEX IF NOT EXISTS idx_sim_order_signal ON sim_trade_order(signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_sim_order_intended ON sim_trade_order(intended_at)",
    # 3.3 成交/未成交事件
    """
CREATE TABLE IF NOT EXISTS sim_trade_fill (
  fill_id            TEXT PRIMARY KEY,          -- sha1(order_id|fill_date|source|price_raw|shares_real)[:32]
  order_id           TEXT NOT NULL,
  side               TEXT NOT NULL CHECK(side IN ('buy','sell')),
  fill_date          TEXT NOT NULL,
  fill_time          TEXT,                      -- 09:30/14:55/22:45
  price_kind         TEXT NOT NULL,             -- open/close/intraday
  price_raw          REAL NOT NULL,             -- 真实原始价
  price_equiv        REAL,                      -- accum_nav 等价值(回测口径)
  accum_nav_ref      REAL,                      -- 换算用的 accum_nav
  raw_close_ref      REAL,                      -- 换算用的原始 close
  raw_ref_date       TEXT,
  shares_calc        REAL,                      -- 回测分数份额
  shares_real        REAL,                      -- 真实 100 份整手份额
  gross              REAL,
  commission         REAL,
  transfer_fee       REAL,
  stamp_tax          REAL,
  net                REAL,
  fee_preset         TEXT,                      -- etf_main/backtest
  fee_config         TEXT,                      -- 完整费率 JSON
  source             TEXT NOT NULL,             -- realtime/etf_daily/backfill
  source_ts          TEXT,
  quote_date         TEXT,                      -- expect_date 校验
  status             TEXT NOT NULL DEFAULT 'confirmed', -- provisional/confirmed
  supersedes_fill_id TEXT,                      -- 复核/纠错指向旧行
  correction_reason  TEXT,
  created_at         TEXT NOT NULL,
  FOREIGN KEY(order_id) REFERENCES sim_trade_order(order_id)
)
""",
    "CREATE INDEX IF NOT EXISTS idx_sim_fill_order ON sim_trade_fill(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_sim_fill_date ON sim_trade_fill(fill_date)",
    # 3.4 触发/重试/失败/纠错审计
    """
CREATE TABLE IF NOT EXISTS sim_trade_event (
  event_id           TEXT PRIMARY KEY,          -- sha1(order_id|event_type|event_at|payload)[:32]
  order_id           TEXT,
  signal_id          TEXT,
  event_type         TEXT NOT NULL,             -- trigger_run/fill_attempt/fill_failed/order_cancel/correction/void/settle
  event_at           TEXT NOT NULL,
  payload            TEXT,                      -- JSON
  source             TEXT,
  note               TEXT,
  created_at         TEXT NOT NULL
)
""",
    "CREATE INDEX IF NOT EXISTS idx_sim_event_order ON sim_trade_event(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_sim_event_type ON sim_trade_event(event_type)",
]

VIEW_DDL = [
    # 未被 supersede 的成交(confirmed/provisional 都算有效, 复盘时优先 confirmed)
    """
CREATE VIEW IF NOT EXISTS v_sim_fill_effective AS
SELECT f.* FROM sim_trade_fill f
WHERE NOT EXISTS (SELECT 1 FROM sim_trade_fill g WHERE g.supersedes_fill_id = f.fill_id)
  AND f.status IN ('confirmed','provisional')
""",
    # 未被 supersede 的信号
    """
CREATE VIEW IF NOT EXISTS v_sim_signal_effective AS
SELECT s.* FROM sim_trade_signal s
WHERE NOT EXISTS (SELECT 1 FROM sim_trade_signal g WHERE g.supersedes_signal_id = s.signal_id)
""",
    # 一笔持仓/平仓(买入+卖出): 每个 order 取「confirmed 优先, 否则 latest created_at」的有效 fill
    """
CREATE VIEW IF NOT EXISTS v_sim_trade_position AS
SELECT s.signal_id, s.strategy, s.signal_date, s.exec_date, s.sell_due_date,
       s.etf_code, s.etf_name, s.signal, s.rating, s.track_score, s.s06_effective_mode,
       s.amount, s.source AS signal_source,
       ob.fill_id AS buy_fill_id, ob.fill_date AS buy_fill_date, ob.price_kind AS buy_fill_kind,
       ob.price_raw AS buy_price_raw, ob.price_equiv AS buy_price_equiv,
       ob.shares_real AS buy_shares_real, ob.shares_calc AS buy_shares_calc, ob.net AS buy_cost,
       os.fill_id AS sell_fill_id, os.fill_date AS sell_fill_date, os.price_kind AS sell_fill_kind,
       os.price_raw AS sell_price_raw, os.price_equiv AS sell_price_equiv,
       os.net AS sell_proceeds,
       -- 估值标记(price_kind='mark')不是真实卖出: 不计已平仓/已实现盈亏, 只作对账参考
       CASE WHEN os.fill_id IS NOT NULL AND os.price_kind <> 'mark'
            THEN os.price_raw - ob.price_raw END AS price_diff,
       -- calc 口径=表内 net 列(写入时即 calc 费率口径的净额: 买入=含费总花费, 卖出=扣费净回款)
       CASE WHEN os.fill_id IS NOT NULL AND os.price_kind <> 'mark'
                 AND ob.net IS NOT NULL AND os.net IS NOT NULL
            THEN os.net - ob.net END AS profit_calc,
       -- real 口径=真实费率净额, 存在 fee_config JSON 的 real 段(表内 net 列是 calc 口径, 不可混用)
       CASE WHEN os.fill_id IS NOT NULL AND os.price_kind <> 'mark'
                 AND json_extract(ob.fee_config,'$.real.net') IS NOT NULL
                 AND json_extract(os.fee_config,'$.real.net') IS NOT NULL
            THEN json_extract(os.fee_config,'$.real.net') - json_extract(ob.fee_config,'$.real.net')
            END AS profit_real,
       -- 未平仓估值标记的页面卡口径利润(仅 --mark-open 回填/复盘对账用, 非已实现;
       -- mark fill 的 fee_config 是 {"mark":true,"profit":X}, 利润在顶层 $.profit 非 $.mark.profit)
       CASE WHEN os.fill_id IS NOT NULL AND os.price_kind = 'mark'
            THEN json_extract(os.fee_config,'$.profit') END AS profit_mark,
       CASE WHEN os.fill_id IS NOT NULL AND os.price_kind <> 'mark' THEN 1 ELSE 0 END AS closed
FROM v_sim_signal_effective s
LEFT JOIN sim_trade_order bo ON bo.signal_id=s.signal_id AND bo.side='buy'
LEFT JOIN sim_trade_order so ON so.signal_id=s.signal_id AND so.side='sell'
LEFT JOIN v_sim_fill_effective ob ON ob.fill_id = (
    SELECT f.fill_id FROM v_sim_fill_effective f
    WHERE f.order_id = bo.order_id AND f.side='buy'
    ORDER BY CASE f.status WHEN 'confirmed' THEN 0 ELSE 1 END, f.created_at DESC LIMIT 1)
LEFT JOIN v_sim_fill_effective os ON os.fill_id = (
    SELECT f.fill_id FROM v_sim_fill_effective f
    WHERE f.order_id = so.order_id AND f.side='sell'
    ORDER BY CASE f.status WHEN 'confirmed' THEN 0 ELSE 1 END, f.created_at DESC LIMIT 1)
""",
]

TRIGGER_TABLES = ("sim_trade_signal", "sim_trade_order", "sim_trade_fill", "sim_trade_event")


def build_trigger_ddl(table: str) -> list[str]:
    short = table.replace("sim_trade_", "")
    return [
        f"""CREATE TRIGGER IF NOT EXISTS trg_sim_{short}_no_update
BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT, 'append-only: {table} UPDATE forbidden'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_sim_{short}_no_delete
BEFORE DELETE ON {table}
BEGIN SELECT RAISE(ABORT, 'append-only: {table} DELETE forbidden'); END""",
    ]


TRIGGER_DDL = [sql for t in TRIGGER_TABLES for sql in build_trigger_ddl(t)]


def now_iso() -> str:
    """本地时区 ISO 秒级时间戳(账本 created_at/frozen_at 统一口径)。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stable_id(*parts) -> str:
    """确定性 ID = sha1(业务键以 | 拼接)[:32];None 视为空串。"""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def file_sha256(path: str | Path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(db_path: str | Path, create: bool = False) -> sqlite3.Connection:
    p = Path(db_path)
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    # ⚠️ 必须开 recursive_triggers: SQLite 默认 OFF 时, INSERT OR REPLACE 冲突删除旧行
    # 不触发 BEFORE DELETE 触发器(实测 REPLACE 会静默替换成功) → append-only 被绕过。
    # 开启后 REPLACE 的内部 DELETE 命中 trg_*_no_delete → RAISE(ABORT)。(闸门动态实测覆盖)
    con.execute("PRAGMA recursive_triggers=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def drop_views_ddl() -> list[str]:
    """视图无数据, 允许重建(表/触发器不受影响, append-only 仍成立)。"""
    out = []
    for sql in VIEW_DDL:
        name = sql.split("VIEW IF NOT EXISTS", 1)[1].split(" AS", 1)[0].strip()
        out.append(f"DROP VIEW IF EXISTS {name}")
    return out


def ensure_schema(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    for sql in TABLE_DDL:
        cur.execute(sql)
    for sql in TRIGGER_DDL:
        cur.execute(sql)
    for sql in drop_views_ddl():
        cur.execute(sql)
    for sql in VIEW_DDL:
        cur.execute(sql)
    con.commit()


def init_db(db_path: str | Path) -> sqlite3.Connection:
    con = connect(db_path, create=True)
    ensure_schema(con)
    try:
        import os
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return con


def insert_or_ignore(con: sqlite3.Connection, table: str, row: dict) -> bool:
    """只允许 INSERT OR IGNORE(禁 REPLACE/UPDATE/DELETE)。返回是否真的插入了一行。"""
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    cur = con.execute(sql, [row[c] for c in cols])
    return cur.rowcount == 1


def record_event(con: sqlite3.Connection, event_type: str, *, order_id=None,
                 signal_id=None, payload=None, source=None, note=None,
                 event_at=None) -> bool:
    """追加审计事件(失败/重试/纠错/结算)。event_at 相同 + payload 相同 → 幂等忽略。"""
    at = event_at or now_iso()
    payload_s = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload is not None else None
    eid = stable_id(order_id, event_type, at, payload_s)
    return insert_or_ignore(con, "sim_trade_event", {
        "event_id": eid,
        "order_id": order_id,
        "signal_id": signal_id,
        "event_type": event_type,
        "event_at": at,
        "payload": payload_s,
        "source": source,
        "note": note,
        "created_at": now_iso(),
    })


def trigger_names(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_sim_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def check_db(con: sqlite3.Connection) -> dict:
    """只读自检: 触发器数=8 / integrity_check / 表与视图齐全。"""
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sim_trade_%'").fetchall()}
    views = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'v_sim_%'").fetchall()}
    trigs = trigger_names(con)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    return {
        "tables": sorted(tables),
        "views": sorted(views),
        "triggers": trigs,
        "trigger_count": len(trigs),
        "integrity_check": integrity,
        "ok": len(tables) == 4 and len(views) == 3 and len(trigs) == 8 and integrity == "ok",
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="模拟交易账本建库/自检(append-only)")
    ap.add_argument("--init", action="store_true", help="建表+触发器+视图(幂等)")
    ap.add_argument("--check", action="store_true", help="自检并打印 JSON")
    ap.add_argument("--db", default="data/sim_trade.db", help="账本 DB 路径")
    args = ap.parse_args()
    if not args.init and not args.check:
        ap.print_help()
        return 2
    if args.init:
        con = init_db(args.db)
        print(json.dumps({"db": str(args.db), **check_db(con)}, ensure_ascii=False, indent=1))
        con.close()
        return 0
    con = connect(args.db)
    print(json.dumps(check_db(con), ensure_ascii=False, indent=1))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
