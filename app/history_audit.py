"""历史行改写审计(2026-10-14 加)——根治「重算抹除历史行」**不可见**问题。

背景(根因报告 `docs/ops/trades-wipe-rootfix-20261014.md`,T1/T3)
  ① **下游** `signal_daily` 每天「全表 `DELETE` + 重算全历史 `INSERT`」
     (`app/compute/signals.py::store`),上游一变(如 `index_daily` 占位价被真实值覆盖)
     重算就吐不出原历史行 → 历史 buy/buy_aux 行**静默消失**,用户侧表现为「trades 断档」。
  ② **上游** `index_daily` 每次采集「整段全历史 `UPSERT` 全字段替换」
     (`app/collector/runner.py::upsert_index_rows`),历史行的价量被改写、零保护。
  唯一有固化保护的是冻结表(`data/signal_kelly_etf_freeze.json`),因此它成了
  「事件曾经存在」的唯一铁证。

设计原则:**只让它可见,不禁止重算/改写**
  · 允许重算(上游源值确实可能有误,必须允许改正),也允许采集覆盖;
    但「历史行(date < 运行日)被消失/改写」这件事必须**留痕 + 告警**,不静默。
  · 每次重算/重写后对历史行做前后 diff:
      signal_daily → `(date,index_id,signal)` 三元组集合的消失 / 出现;
      index_daily  → 已存在的 `(date,index_id)` 行 6 个价量字段发生**实质**变化
                     (浮点容差内忽略,避免源端舍入抖动制造噪声)。
  · 变化逐条落 `history_overwrite_audit` 表(持久可查)+ 汇总告警(复用 notify 链,带 dedup)。
  · 新增行(库里本来没有)不算「改写」,故历史回填(backfill)不会误报。

范围(诚实标注)
  · 只覆盖 `date < 运行日` 的**历史**行。当日(`date == 运行日`)行的盘中正常抖动
    (占位价 → 真实收盘)不在本审计范围——那由 `signal_intraday_log` 过程历史 + 占位行
    source 标记(T5)覆盖。
  · 审计自身失败一律 try/except 吞掉并打印(审计是增强,绝不因它阻断采集/重算主流程)。
"""
from __future__ import annotations

import datetime as dt
import math
from collections import Counter

from .db import get_conn
from .notify_hook import send_alert

# index_daily 价量字段浮点比较容差(相对 1e-4 + 绝对 1e-6);
# 源端舍入抖动(如 2987.8 vs 2987.8000001)不算改写,防噪声。
_IDX_REL_TOL = 1e-4
_IDX_ABS_TOL = 1e-6

# 字段级绝对容差(2026-10-28 加,治「发布精度抖动」误报)。依据 = 云上
# history_overwrite_audit 表 2026-10-14~10-27 全量 index_daily 行(491,532 行)实测:
#   · 剔除 NULL↔NaN 表示变化后剩 1,148 行真实变化,其中 450 行「四价全同、只有 pct/amount 变」;
#     再拆:156 行只有 pct 变(全为「快照 2 位小数 vs 源端全精度」,如 -0.88 vs -0.884983),
#     11 行 pct 与 amount 都变,其余 283 行是 pct 一端缺失(271 条 有值→缺失、12 条 缺失→有值;
#     其中 50 条 amount 两端同为缺失)——值↔缺失,按铁律仍算变化,不许吞。
#   · 这 156 行的 |Δpct| 分布:p50=0.0019 / p99=0.00497 / 最大 0.00501
#     ⇒ 与「pct 发布保留 2 位小数,量化半格 0.005」吻合(0.00501 来自源值本身多于 2 位小数),
#     故 pct_change 取 0.006(0.005 + 余量),不做全局放大。
#   · amount 实测无需额外绝对容差:两端都有值时 |Δamount| 有值行 296 条中 285 条为 0,
#     另 11 条 |Δamount| 为 1e5~3.9e9 元(相对 1.59e-6~12.3%),其中只有 4 条越过相对 1e-4
#     判据(真修正 3.71%~12.3%),其余 7 条属舍入——加绝对容差会吞掉真修正,
#     故沿用相对 1e-4 判据(1e-4 已覆盖纯舍入抖动)。
#   · 红线:close 真纠错(6562.71→3367.89)幅度 48%,远超所有容差,仍判变化。
_FIELD_ABS_TOL = {"pct_change": 0.006}

# 告警去重窗口(秒): signal_daily 是 P0(丢成交) → 1h; index_daily 量大噪音面广 → 24h 日报
_SIGNAL_DEDUP_WINDOW = 3600
_INDEX_DEDUP_WINDOW = 86400

_SAMPLE_N = 8  # 告警正文样例条数上限

# 可审计的 index_daily 价量列(局部字段审计只接受这些列名,防 SQL 注入/写错列)
_IDX_VALUE_COLS = ("open", "high", "low", "close", "pct_change", "amount")


def today_ymd() -> str:
    """运行日(本地时区 YYYYMMDD)。重算/采集的「历史 = date < 运行日」以本地日切。"""
    return dt.date.today().strftime("%Y%m%d")


# ────────────────────────── signal_daily 重算 diff 审计(T1) ──────────────────────────

def snapshot_signal_daily_history(conn, run_date: str) -> set:
    """取 date < run_date 的历史行三元组集合(重算前/后各调一次做 diff)。"""
    rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily WHERE date < ?", (run_date,)
    ).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def audit_signal_daily_store(conn, before: set, after: set, run_date: str | None = None) -> list:
    """重算前后历史行集合 diff → 落审计表 + 汇总告警。返回变化清单(供测试断言)。

    before/after: snapshot_signal_daily_history 的前后快照。

    判据(2026-10-14 定,2026-10-21 修误报口径):
      · **消失**(before-after)= 历史行被重算抹除 → 落表;是否 critical 见下。
      · **出现**(after-before):
          - 若同轮有消失(信号类型变更 buy→buy_aux 会同时产生一对)= 视作**类型变更佐证**,
            落表(进告警正文),助定位;
          - 若同轮**只有出现**(纯历史回填,如迟到信号补采后重算新增历史行)= 合法补账,
            **不落表不告警**(否则批量回填会灌爆审计表 + 制造告警风暴)。
      · **每日全量重算 = 设计行为, 不再报 critical(2026-10-21)**:
        signal_daily 每天两次全量重算, 会把同一 (date,index_id) 的旧 signal 行换成新类型
        ⇒ 消失/出现成对出现(实测每日 ~1000 条、审计表逐日稳定 5 万行, 复现见
        scripts/alert_weekly_review.py 的周告警盘点口径)。**消失行能在同一 (date,index_id) 找到对应「出现」行
        = 型别变更 ⇒ notice(severe=False)**, 只提示不告警;
        **找不到配对 = 纯丢失(行被抹掉没有替身)⇒ 仍 critical**, 判别力不降。
        判据局限: 若同一天同一指数「删旧行 + 无故新增一条不同类型」, 也会被判成设计行为;
        这种情形概率低(真丢失通常整行消失、无配对), 但已知并注明(见告警正文)。
    返回完整 diff 清单(调用方/测试可见全貌),落表/告警范围见上。
    """
    run_date = run_date or today_ymd()
    changes = []
    for (d, iid, sig) in sorted(before - after):
        changes.append({"kind": "disappeared", "date": d, "index_id": iid,
                        "signal": sig, "before_val": sig, "after_val": None})
    for (d, iid, sig) in sorted(after - before):
        changes.append({"kind": "appeared", "date": d, "index_id": iid,
                        "signal": sig, "before_val": None, "after_val": sig})
    if not changes:
        return changes
    n_dis = sum(1 for c in changes if c["kind"] == "disappeared")
    # 只有出现(纯回填)不落表不告警; 有消失时连"出现"一并落表(类型变更佐证)
    to_record = changes if n_dis else []
    if to_record:
        try:
            _record(conn, "signal_daily", run_date, to_record)
        except Exception as e:  # noqa: BLE001  审计落表失败不阻断重算
            print(f"[history-audit] signal_daily 审计落表失败(不阻断): {type(e).__name__} {e}")
    if n_dis:
        # 2026-10-21: 区分「配对型别变更(每日全量重算的设计行为)」与「纯丢失(真故障)」。
        # 2026-10-22 审查差集 D6: 配对必须**一对一多重集**(Counter), 不能只用集合判
        # 「同键出现过」。本地库实测 3155 个键同 (date,index_id) 有多行(如 cgb_10y_etf
        # 同日 band_hold + buy_special); 若用集合, 同键 2 行消失而只补回 1 行时, 被掩盖的
        # 那一行消失会被误判成「配对型别变更」⇒ 少报纯丢失/漏 critical。Counter 一对一
        # 扣减后, 多出来的消失行仍进 pure_lost(真故障判别力不降)。
        _appeared_left = Counter((c["date"], c["index_id"]) for c in changes
                                 if c["kind"] == "appeared")
        pure_lost = []
        for c in changes:
            if c["kind"] != "disappeared":
                continue
            _k = (c["date"], c["index_id"])
            if _appeared_left.get(_k, 0) > 0:
                _appeared_left[_k] -= 1  # 一对一配对: 每条「出现」只能抵一次「消失」
            else:
                pure_lost.append(c)
        _alert("signal_daily", changes, run_date, _SIGNAL_DEDUP_WINDOW,
               pure_lost=pure_lost)
    return changes


# ────────────────────────── index_daily 整段重写审计(T3) ──────────────────────────

def audit_index_rows_upsert(rows, conn=None, run_date: str | None = None) -> list:
    """采集整段 UPSERT 前, detach 出「历史行被实质改写」清单 → 落审计表 + 汇总告警。

    rows: [(date, index_id, open, high, low, close, pct_change, amount), ...](采集返回值)。
    只审 date < run_date 的行;只为「库里已存在且值实质变化」的行记改写(新增行不算)。
    不禁止改写(源值确实可能被修正),只暴露。
    返回变化清单(供测试断言)。默认自开连接;传入 conn 时复用(调用方随后自己 commit)。
    """
    run_date = run_date or today_ymd()
    hist = [tuple(r) for r in rows if r and r[0] and r[0] < run_date]
    if not hist:
        return []
    own = conn is None
    if own:
        conn = get_conn()
    try:
        changes = _diff_index_history(conn, hist)
    finally:
        if own:
            conn.close()
    if not changes:
        return changes
    if own:
        conn = get_conn()
    try:
        _record(conn, "index_daily", run_date, changes)
        if own:
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[history-audit] index_daily 审计落表失败(不阻断): {type(e).__name__} {e}")
    finally:
        if own:
            conn.close()
    _alert("index_daily", changes, run_date, _INDEX_DEDUP_WINDOW)
    return changes


def audit_index_row_partial(conn, run_date: str, date: str, index_id: str, updates: dict) -> list:
    """单行**局部字段**改写审计(2026-10-14 加,补全 index_daily 同类写入面)。

    用于只 UPDATE 少数列、其余列不动的写入点(如 `intraday_snapshot._backfill_industry_daily_historical`
    的计算法 `UPDATE index_daily SET close=?, source='calc'`)——这类点若整行入参会误报(未动的列被判成变化)。
    只审 `date < run_date` 的历史行,且只比对 updates 里给出的列。返回变化清单。
    """
    run_date = run_date or today_ymd()
    if not date or date >= run_date or not updates:
        return []
    cols = [c for c in updates if c in _IDX_VALUE_COLS]
    if not cols:
        return []
    row = conn.execute(
        f"SELECT {','.join(cols)} FROM index_daily WHERE date=? AND index_id=?", (date, index_id)
    ).fetchone()
    if row is None:
        return []  # 新增行, 不算改写
    before_v = tuple(row)
    after_v = tuple(updates[c] for c in cols)
    # cols 顺序跟随 updates(可能不是 _IDX_VALUE_COLS 原序)⇒ 传实际列顺序, 字段级容差才对齐
    if not _values_changed(before_v, after_v, fields=cols):
        return []
    change = {"kind": "changed", "date": date, "index_id": index_id, "signal": None,
              "before_val": _fmt_vals(before_v), "after_val": _fmt_vals(after_v)}
    try:
        _record(conn, "index_daily", run_date, [change])
    except Exception as e:  # noqa: BLE001
        print(f"[history-audit] index_daily 单行审计落表失败(不阻断): {type(e).__name__} {e}")
    _alert("index_daily", [change], run_date, _INDEX_DEDUP_WINDOW)
    return [change]


def _diff_index_history(conn, hist: list) -> list:
    """按 index_id 分组, 在各自 [min_date,max_date] 范围内取现库值逐行比对。"""
    groups: dict[str, list] = {}
    for r in hist:
        groups.setdefault(r[1], []).append(r)
    changes = []
    for iid, grp in groups.items():
        dates = [g[0] for g in grp]
        lo, hi = min(dates), max(dates)
        cur = {}
        for row in conn.execute(
            "SELECT date, open, high, low, close, pct_change, amount FROM index_daily "
            "WHERE index_id=? AND date>=? AND date<=?",
            (iid, lo, hi),
        ):
            cur[row[0]] = (row[1], row[2], row[3], row[4], row[5], row[6])
        for g in grp:
            before_v = cur.get(g[0])
            if before_v is None:
                continue  # 新增行(库中原本没有), 不算改写
            after_v = tuple(g[2:8])
            if _values_changed(before_v, after_v):
                changes.append({
                    "kind": "changed", "date": g[0], "index_id": iid, "signal": None,
                    "before_val": _fmt_vals(before_v), "after_val": _fmt_vals(after_v),
                })
    return changes


def _is_missing(x) -> bool:
    """「缺失」的统一定义:None 与 NaN 等价(2026-10-28 修)。

    为什么必须等价:csindex 等源对缺失值返回 float('nan'),而 SQLite 把 NaN 存成 NULL
    ⇒ 库里读出来是 None、采集回来是 nan ⇒ 旧比较器(None↔值 → 变化)会把同一行
    「NULL→NaN」判成每次都在改写(实测 491,532 行审计里 490,384 行 = 99.77% 是这种
    纯表示变化,同一个 (date,index_id) 被记了 20 次)。math.isnan 对 int/float 及
    numpy.float32/64(NaN)均可用,对 str 等抛 TypeError ⇒ 按非缺失处理。
    """
    if x is None:
        return True
    try:
        return math.isnan(x)
    except (TypeError, ValueError):
        return False


def _values_changed(before: tuple, after: tuple, fields: tuple = _IDX_VALUE_COLS) -> bool:
    """逐字段比对, 任一字段「实质变化」即算改写。

    判据(2026-10-28 修订):
      · 两端都缺失(None/NaN 任意组合)⇒ 该字段不算变化(纯表示差异);
      · 一端缺失、另一端有值 ⇒ **算变化**(值→缺失可能是真丢行, 绝不吞);
      · 数值差异在容差内 ⇒ 不算变化:先看字段级绝对容差 `_FIELD_ABS_TOL`,
        再看全局相对 1e-4 + 绝对 1e-6;
      · 非数值型不一致 ⇒ 算变化。
    fields: 与 before/after 逐位对应的列名(局部字段审计时列顺序由 updates 决定,
    必须传入实际列顺序才能命中字段级容差)。
    """
    for i, (a, b) in enumerate(zip(before, after)):
        a_missing, b_missing = _is_missing(a), _is_missing(b)
        if a_missing and b_missing:
            continue
        if a_missing or b_missing:
            return True
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            if a != b:
                return True
            continue
        delta = abs(fa - fb)
        if delta == 0:
            continue
        field_tol = _FIELD_ABS_TOL.get(fields[i]) if i < len(fields) else None
        if field_tol is not None and delta <= field_tol:
            continue
        if delta > _IDX_ABS_TOL and delta / max(abs(fa), abs(fb), 1e-12) > _IDX_REL_TOL:
            return True
    return False


def _fmt_vals(vals: tuple) -> str:
    out = []
    for x in vals:
        if x is None:
            out.append("-")
        elif isinstance(x, float):
            out.append(f"{x:g}")
        else:
            out.append(str(x))
    return "|".join(out)


# ────────────────────────── 落表 + 告警 ──────────────────────────

def _record(conn, src_table: str, run_date: str, changes: list) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO history_overwrite_audit "
        "(detected_at, run_date, src_table, kind, date, index_id, signal, before_val, after_val) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(now, run_date, src_table, c["kind"], c["date"], c["index_id"],
          c["signal"], c["before_val"], c["after_val"]) for c in changes],
    )
    conn.commit()


def _alert(src_table: str, changes: list, run_date: str, dedup_window: int,
           pure_lost: list | None = None) -> None:
    """发历史改写告警。

    pure_lost(2026-10-21): signal_daily 专用 —— 无配对「出现」行的消失清单。
      · None(未提供, 如 index_daily)= 维持原 critical 行为(不降判别力);
      · 空 list = 消失行全部是配对型别变更(每日全量重算设计行为)⇒ notice 级(severe=False);
      · 非空 = 存在纯丢失 ⇒ 仍 critical, 正文写明「其中纯丢失 N 条」。
    """
    n = len(changes)
    n_dis = sum(1 for c in changes if c["kind"] == "disappeared")
    n_app = sum(1 for c in changes if c["kind"] == "appeared")
    n_chg = sum(1 for c in changes if c["kind"] == "changed")
    parts = []
    if n_dis:
        parts.append(f"消失{n_dis}")
    if n_app:
        parts.append(f"出现{n_app}")
    if n_chg:
        parts.append(f"值改写{n_chg}")
    iids = sorted({c["index_id"] for c in changes})

    def _one(c: dict) -> str:
        head = f"{c['date']}|{c['index_id']}" + (f"|{c['signal']}" if c["signal"] else "")
        if c["kind"] == "changed":
            return f"{head}(改:{c['before_val']}->{c['after_val']})"
        return f"{head}({c['kind']})"

    # 2026-10-21: 只有「纯丢失」才是 P0; 消失/出现配对的型别变更 = 每日全量重算的设计行为。
    design_note = ""
    if pure_lost is not None:
        n_pure = len(pure_lost)
        n_paired = n_dis - n_pure
        critical = n_pure > 0
        if n_paired:
            design_note = (
                f"其中**型别变更 {n_paired} 条**(同一 date+index_id 的旧 signal 被换成新类型)"
                "= signal_daily 每日全量重算的设计行为, 非数据损坏"
                "(实测每日两次、审计表逐日稳定 ~5 万行; 复现见 scripts/alert_weekly_review.py)。"
            )
        if critical:
            design_note += f"\n⚠ **纯丢失 {n_pure} 条**(消失后同 date+index_id 无任何新行)= 真故障信号。"
        else:
            design_note += (
                "\n判据局限: 若同一天同一指数「删旧行 + 无故新增一条不同类型」, 也会被判为设计行为;"
                "该情形概率低(真丢失通常整行消失、无配对), 但已知并在此注明。"
            )
    else:
        critical = True
    tag = "" if critical else "-提示"
    subject = f"[历史行改写{tag}] {src_table} 历史行被重写 {n} 条({'/'.join(parts)})"
    sample = "; ".join(_one(c) for c in changes[:_SAMPLE_N])
    body = (
        f"{src_table} 的**历史行**(date < {run_date})在本次重算/采集前后发生改写 {n} 条"
        f"({'/'.join(parts)}), 涉及 {len(iids)} 个指数。\n"
        + (design_note + "\n" if design_note else
           "这是「重算/整段重写抹掉历史行」的可见信号(见 docs/ops/trades-wipe-rootfix-20261014.md)。\n")
        + f"明细已落 history_overwrite_audit 表(run_date={run_date})。\n"
        f"样例: {sample}"
    )
    if len(changes) > _SAMPLE_N:
        body += f"\n(仅列前 {_SAMPLE_N} 条, 其余见审计表)"
    try:
        send_alert(subject, body,
                   # 严重度进 dedup key: 防当日先发的 notice 把后来真 critical 压掉(1h 窗)。
                   dedup_key=f"history_overwrite:{src_table}:{run_date}:"
                             f"{'critical' if critical else 'notice'}",
                   # notice 是设计行为, 每天最多一条(实测 signal_daily 每日两次重算);
                   # critical 沿用原窗口(1h)不放松。
                   dedup_window=dedup_window if critical else max(dedup_window, 86400),
                   severe=critical,
                   from_prefix="[告警]" if critical else "[提示]")
    except Exception as e:  # noqa: BLE001  告警失败不阻断
        print(f"[history-audit] {src_table} 改写告警调用异常: {type(e).__name__} {e}")