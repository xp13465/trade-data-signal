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

# ──────────────────── 常态事件降级判据(2026-10-28 告警降噪 ★4 修订) ────────────────────
# 依据 = `docs/ops/alert-denoise-a4-research-20261028.md` §6(云上 14 天真实数据回放):
#   index_daily 真实变化(剔除 NULL↔NaN 表示差异后)常态 **85 行/天、单批最大 82**;
#   原规格阈值 small<50 / large>=1000 会把每个交易日判进 mid(small 太小),
#   而 large 在真实数据里**永不触发**(单批最大 82)——等于造出一个死闸门。
#   故 small 上限取 200(= 常态单批最大 82 的 2.4 倍),large 仍留 1000 作「整段重写」安全网
#   (14 天 0 次,属**合法的永不触发**,用合成反例证明它会响)。
_IDX_BUCKET_SMALL_BELOW = 200    # len(changes) <  200  ⇒ small
_IDX_BUCKET_LARGE_FROM = 1000    # len(changes) >= 1000 ⇒ large;中间 = mid
# 旧历史行「真覆盖」判据: 行龄 ≥30 天 **且至少一个字段 值→值**。
#   实测 14 天 760 行真实变化里,行龄 >30 天只有 fill(12 行)/ wipe(271 行),correct = 0
#   ⇒ 常态零误报;一旦出现(历史被改成别的值,同 trades-wipe 型)当天就响,且不被数量档稀释。
_IDX_OLD_ROW_AGE_DAYS = 30
# signal_daily: 放弃「pending + 2h 宽限复核」(21 个真实批次回放会判出 726 条假 critical,
#   其中 10-26 一次 562 条雪崩——因当天只跑了一批,"下一次运行必还原"的假设不成立),
#   改用两条**无状态**判据。实测 21 批 net ∈ [-121, +117]、带绝对下限的单日跌幅恒 0
#   ⇒ 14 天 0 次误报;敏感性下限 = 单日 20 行 / 单批净 200 行(1–2 行级真丢失由
#   kelly 孤儿买检测承担,本审计现状下本来就被 440/557 的型别漂移淹没)。
_SIGNAL_NET_CRITICAL = -200
_SIGNAL_DATE_DROP_ROWS = 20
_SIGNAL_DATE_DROP_RATIO = 0.30

# notice 走 23:25 摘要(不单发)时的摘要类别标注(notify.py --digest-category)
_DIGEST_CATEGORY = "history_overwrite"

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

    判据(2026-10-14 定,2026-10-21 修误报口径,2026-10-28 ★4 改严重度判据):
      · **消失**(before-after)= 历史行被重算抹除 → 落表;是否 critical 见下。
      · **出现**(after-before):
          - 若同轮有消失(信号类型变更 buy→buy_aux 会同时产生一对)= 视作**类型变更佐证**,
            落表(进告警正文),助定位;
          - 若同轮**只有出现**(纯历史回填,如迟到信号补采后重算新增历史行)= 合法补账,
            **不落表不告警**(否则批量回填会灌爆审计表 + 制造告警风暴)。
      · **每日全量重算 = 设计行为(2026-10-21)**: signal_daily 每天两次全量重算, 会把同一
        (date,index_id) 的旧 signal 行换成新类型 ⇒ 消失/出现成对出现(实测每日 ~1000 条);
        「配对型别变更 N 条」只作正文信息, **不再单独决定严重度**。
      · **严重度判据(2026-10-28 ★4,见 plan_signal_daily_alert)**: critical ⇔ 单批净变化
        `len(appeared) - len(disappeared) <= -200` **或** 任一 date「消失 ≥20 行 且
        消失/原有行数 ≥30%」;否则 notice(进 23:25 摘要,不单发)。
        依据: 21 个真实批次回放 net ∈ [-121,+117]、带绝对下限的单日跌幅恒 0 ⇒ 14 天零误报;
        原「pending + 2h 宽限复核」会判出 726 条假 critical(含 10-26 一次 562 条雪崩)。
        判据局限: 敏感性下限 = 单日 20 行 / 单批净 200 行, 1–2 行级真丢失不再 critical
        (该能力由 kelly 孤儿买检测承担; 本审计现状下 1 行级本来就被 ~1000 行型别漂移淹没)。
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
        # 2026-10-28 ★4: 严重度由「净变化 + 逐日覆盖率」无状态判据决定(不再看 pure_lost>0),
        # pure_lost 仍传下去只作正文信息(「纯丢失 N 条」)。
        _plan = plan_signal_daily_alert(changes, before, after)
        _alert("signal_daily", changes, run_date, _SIGNAL_DEDUP_WINDOW,
               pure_lost=pure_lost, critical_override=_plan["critical"],
               extra_note=_plan["note"])
    return changes


# ────────────────────────── index_daily 整段重写审计(T3) ──────────────────────────

def audit_index_rows_upsert(rows, conn=None, run_date: str | None = None,
                            caller: str = "runner") -> list:
    """采集整段 UPSERT 前, detach 出「历史行被实质改写」清单 → 落审计表 + 汇总告警。

    rows: [(date, index_id, open, high, low, close, pct_change, amount), ...](采集返回值)。
    只审 date < run_date 的行;只为「库里已存在且值实质变化」的行记改写(新增行不算)。
    不禁止改写(源值确实可能被修正),只暴露。
    caller: 写入来源(**同一事实的唯一判据维度**,2026-10-28 ★4 加)——"runner"(行情源采集,
      默认)/ "index_backfill"(计划内回填,`index_backfill.py` / `hk_industry_backfill.py`
      全部写入点)/ "partial"(单行局部字段写入)。分级由此分流: 计划内回填实测 12 天真实
      变化全 0 条 ⇒ notice;runner 批中/大批量 ⇒ critical(见 plan_index_daily_alerts)。
      漏传 = 回填批被当 runner 判 critical(判据漂移),故该模块所有 index_backfill 写入点
      必须显式传 caller="index_backfill"。
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
    _alert_index_daily(changes, run_date, caller)
    return changes


def audit_index_row_partial(conn, run_date: str, date: str, index_id: str, updates: dict,
                            caller: str = "partial") -> list:
    """单行**局部字段**改写审计(2026-10-14 加,补全 index_daily 同类写入面)。

    用于只 UPDATE 少数列、其余列不动的写入点(如 `intraday_snapshot._backfill_industry_daily_historical`
    的计算法 `UPDATE index_daily SET close=?, source='calc'`)——这类点若整行入参会误报(未动的列被判成变化)。
    只审 `date < run_date` 的历史行,且只比对 updates 里给出的列。返回变化清单。
    caller: 写入来源(2026-10-28 ★4,dedup key 分键用);单行写入恒为 small 档 ⇒ notice,
    但「旧历史行真覆盖」判据照常生效(值→值 且行龄 ≥30 天 ⇒ critical)。
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
              "before_val": _fmt_vals(before_v), "after_val": _fmt_vals(after_v),
              "kinds": _change_kinds(before_v, after_v, fields=cols)}
    try:
        _record(conn, "index_daily", run_date, [change])
    except Exception as e:  # noqa: BLE001
        print(f"[history-audit] index_daily 单行审计落表失败(不阻断): {type(e).__name__} {e}")
    _alert_index_daily([change], run_date, caller)
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
                    # 变化类型集合(值→值 correct / 缺失→有值 fill / 有值→缺失 wipe):
                    # 供「旧行真覆盖」判据区分「历史被改成别的值」与「补空/抹空」。
                    "kinds": _change_kinds(before_v, after_v),
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


def _field_change_kind(a, b, field: str | None = None) -> str | None:
    """单字段变化类型: None=无实质变化 / "fill"(缺失→有值)/ "wipe"(有值→缺失)/ "correct"(值→值)。

    判据(2026-10-28 修订):
      · 两端都缺失(None/NaN 任意组合)⇒ 不变(纯表示差异);
      · 一端缺失、另一端有值 ⇒ **算变化**(值→缺失可能是真丢行, 绝不吞);
      · 数值差异在容差内 ⇒ 不变:先看字段级绝对容差 `_FIELD_ABS_TOL`,
        再看全局相对 1e-4 + 绝对 1e-6;
      · 非数值型不一致 ⇒ 算变化(value→value)。
    field: 该位的列名(局部字段审计时列顺序由 updates 决定, 必须传实际列名才命中字段级容差)。
    """
    a_missing, b_missing = _is_missing(a), _is_missing(b)
    if a_missing and b_missing:
        return None
    if a_missing:
        return "fill"
    if b_missing:
        return "wipe"
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None if a == b else "correct"
    delta = abs(fa - fb)
    if delta == 0:
        return None
    field_tol = _FIELD_ABS_TOL.get(field)
    if field_tol is not None and delta <= field_tol:
        return None
    if delta > _IDX_ABS_TOL and delta / max(abs(fa), abs(fb), 1e-12) > _IDX_REL_TOL:
        return "correct"
    return None


def _change_kinds(before: tuple, after: tuple, fields: tuple = _IDX_VALUE_COLS) -> set:
    """本行涉及的变化类型集合(子集 of {"correct","fill","wipe"})。"""
    kinds = set()
    for i, (a, b) in enumerate(zip(before, after)):
        k = _field_change_kind(a, b, fields[i] if i < len(fields) else None)
        if k:
            kinds.add(k)
    return kinds


def _values_changed(before: tuple, after: tuple, fields: tuple = _IDX_VALUE_COLS) -> bool:
    """逐字段比对, 任一字段「实质变化」即算改写(判据见 _field_change_kind)。

    fields: 与 before/after 逐位对应的列名(局部字段审计时列顺序由 updates 决定,
    必须传入实际列顺序才能命中字段级容差)。
    """
    return any(_field_change_kind(a, b, fields[i] if i < len(fields) else None)
               for i, (a, b) in enumerate(zip(before, after)))


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


def _index_bucket(n: int) -> str:
    """本批真实变化条数 → 量级档(small/mid/large)。"""
    if n < _IDX_BUCKET_SMALL_BELOW:
        return "small"
    if n < _IDX_BUCKET_LARGE_FROM:
        return "mid"
    return "large"


def _row_age_days(date: str, run_date: str) -> int:
    """行龄(天)= run_date - date。两参数都是库内 `YYYYMMDD` 字符串;解析失败按 0(不当旧行)。"""
    try:
        return (dt.datetime.strptime(str(run_date), "%Y%m%d").date()
                - dt.datetime.strptime(str(date), "%Y%m%d").date()).days
    except (TypeError, ValueError):
        return 0


def plan_index_daily_alerts(changes: list, run_date: str, caller: str) -> list[dict]:
    """index_daily 本批告警计划(**纯函数, 不外发**;审计入口据此发,回放/单测直接断言)。

    分级(2026-10-28 ★4, 依据 docs/ops/alert-denoise-a4-research-20261028.md §6(b)):
      · 数量档 = 本批真实变化条数: small < 200 / mid 200–999 / large >= 1000;
      · critical ⇔ `caller == "runner"` 且 档位 ∈ {mid, large};
        其余(index_backfill 计划内回填 / partial 单行 / runner 的 small 常态 T+1 修正)
        ⇒ notice(进 23:25 摘要, 不单发);
      · **旧行真覆盖**独立成一条 critical(独立 dedup key, 行龄 ≥30 天 且 存在字段 值→值):
        哪怕只有 1 行也照报, 不被数量档稀释;若本批同时有 small/mid 数据, 两条告警各自发出
        (critical 不被吞, 小批信息也不丢)。
    返回 [{"changes","critical","dedup_suffix","note"}, ...](空批返回 [])。
    """
    if not changes:
        return []
    bucket = _index_bucket(len(changes))
    critical = caller == "runner" and bucket in ("mid", "large")
    plan = [{
        "changes": changes,
        "critical": critical,
        "dedup_suffix": f"{caller}:{bucket}",
        "note": (f"本批真实变化 {len(changes)} 条 ⇒ **{bucket} 档**(写入方 caller={caller})。"
                 + ("runner 批达到中/大批量改写 ⇒ critical。" if critical
                    else "常态量级/计划内回填 ⇒ 提示级(并入当日摘要, 不单独发信)。")),
    }]
    old_rows = [c for c in changes
                if "correct" in (c.get("kinds") or ())
                and _row_age_days(c.get("date"), run_date) >= _IDX_OLD_ROW_AGE_DAYS]
    if old_rows:
        plan.append({
            "changes": old_rows,
            "critical": True,
            "dedup_suffix": "old_overwrite",
            "note": (f"⚠ **旧历史行真覆盖 {len(old_rows)} 条**: 行龄 ≥{_IDX_OLD_ROW_AGE_DAYS} 天的行"
                     "被改成了别的值(值→值, 不是补空也不是抹空)。14 天实测常态恒为 0 条"
                     "(旧行只有 fill/wipe)⇒ 判 critical, 不受本批数量档稀释。"),
        })
    return plan


def _alert_index_daily(changes: list, run_date: str, caller: str) -> None:
    """按 plan_index_daily_alerts 逐条发出(每条一个独立 dedup key)。"""
    for item in plan_index_daily_alerts(changes, run_date, caller):
        _alert("index_daily", item["changes"], run_date, _INDEX_DEDUP_WINDOW,
               critical_override=item["critical"], dedup_suffix=item["dedup_suffix"],
               extra_note=item["note"])


def plan_signal_daily_alert(changes: list, before: set, after: set) -> dict:
    """signal_daily 本批判级(**纯函数**): 两条无状态判据(2026-10-28 ★4 定)。

      · net = len(appeared) - len(disappeared);net <= -200 ⇒ critical;
      · 逐 date: before = after + 消失 - 出现(this is exactly the set counts),
        drop = before - after;任一 date「drop >= 20 且 drop/before >= 30%」⇒ critical;
      · 否则 notice(进 23:25 摘要)。
    只统计本批有变化的 date(其余 date drop 恒 0), 用调用方已拿到的前后集合计数,
    不额外扫表(before/after 已是 71,836 行三元组集合, 计数是毫秒级)。
    返回 {"critical": bool, "note": str}。
    """
    n_dis = sum(1 for c in changes if c["kind"] == "disappeared")
    n_app = sum(1 for c in changes if c["kind"] == "appeared")
    net = n_app - n_dis
    before_cnt = Counter(d for d, _i, _s in before)
    after_cnt = Counter(d for d, _i, _s in after)
    worst_date, worst_drop, worst_before = None, 0, 0
    hit_dates = []
    for d in sorted({c["date"] for c in changes}):
        b = before_cnt.get(d, 0)
        a = after_cnt.get(d, 0)
        drop = b - a
        if drop > worst_drop:
            worst_date, worst_drop, worst_before = d, drop, b
        if b and drop >= _SIGNAL_DATE_DROP_ROWS and drop / b >= _SIGNAL_DATE_DROP_RATIO:
            hit_dates.append(d)
    if net <= _SIGNAL_NET_CRITICAL:
        critical, reason = True, f"单批净变化 {net:+d} ≤ {_SIGNAL_NET_CRITICAL} 条"
    elif hit_dates:
        critical, reason = True, (f"单日消失 ≥{_SIGNAL_DATE_DROP_ROWS} 行且占原有 ≥"
                                  f"{_SIGNAL_DATE_DROP_RATIO:.0%}: {','.join(hit_dates[:3])}")
    else:
        critical = False
        reason = "未达 critical 阈值(每日全量重算的型别漂移属常态)"
    note = (f"判据(2026-10-28 ★4): 净变化 {net:+d} 条(出现 {n_app} / 消失 {n_dis}),"
            f" 单日最大消失 {worst_drop} 条"
            + (f"({worst_date} 原有 {worst_before} 行)" if worst_date else "")
            + f" ⇒ {reason}。")
    return {"critical": critical, "note": note}


def _alert(src_table: str, changes: list, run_date: str, dedup_window: int,
           pure_lost: list | None = None, critical_override: bool | None = None,
           dedup_suffix: str | None = None, extra_note: str = "") -> None:
    """发历史改写告警。

    critical_override(2026-10-28 ★4): 严重度由调用方的纯函数判据决定
      (index_daily → plan_index_daily_alerts; signal_daily → plan_signal_daily_alert)。
    pure_lost(2026-10-21): signal_daily 专用 —— 无配对「出现」行的消失清单,**只作正文信息**
      (2026-10-28 起不再决定严重度; 严重度看 critical_override)。
    dedup_suffix: 进 dedup key 的尾段(index_daily 用 `{caller}:{bucket}` 或 `old_overwrite`);
      缺省沿用 `critical|notice`(signal_daily 与其他调用方)。
    extra_note: 判据/量级说明, 拼进正文(说明「为什么判 critical/notice」)。
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

    # 严重度: 显式判据优先; 兜底保持老行为(未传判据 ⇔ 维持 critical, 不静默降级)。
    critical = critical_override if critical_override is not None else True
    design_note = ""
    if pure_lost is not None:
        n_pure = len(pure_lost)
        n_paired = n_dis - n_pure
        if n_paired:
            design_note = (
                f"其中**型别变更 {n_paired} 条**(同一 date+index_id 的旧 signal 被换成新类型)"
                "= signal_daily 每日全量重算的设计行为, 非数据损坏"
                "(实测每日两次、审计表逐日稳定 ~5 万行; 复现见 scripts/alert_weekly_review.py)。"
            )
        if n_pure:
            design_note += (f"\n其中**纯丢失 {n_pure} 条**(消失后同 date+index_id 无任何新行)"
                            + ("= 真故障信号。" if critical else "= 待观察(未达 critical 阈值)。"))
    if extra_note:
        design_note = (design_note + "\n" if design_note else "") + extra_note
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
    # 分键(2026-10-28 ★4): index_daily 按 caller+bucket / old_overwrite 独立成键,
    # 治「02:02 小批的 24h 窗把 17:59 的 35–82 条真实变化压掉」(占窗与数量无关, 是 key 相同)。
    key_tail = dedup_suffix if dedup_suffix else ("critical" if critical else "notice")
    try:
        send_alert(subject, body,
                   # 严重度进 dedup key: 防当日先发的 notice 把后来真 critical 压掉(1h 窗)。
                   dedup_key=f"history_overwrite:{src_table}:{run_date}:{key_tail}",
                   # notice 是设计行为, 每天最多一条(实测 signal_daily 每日两次重算);
                   # critical 沿用原窗口(1h)不放松。
                   dedup_window=dedup_window if critical else max(dedup_window, 86400),
                   severe=critical,
                   from_prefix="[告警]" if critical else "[提示]",
                   # notice 只进 23:25 摘要(不单发邮件): 常态 ~85 行/天 的 T+1 修正是设计行为,
                   # 单发无信息量(2026-10-28 ★4)。critical 走即时通道不变。
                   defer_digest=not critical,
                   digest_category=None if critical else _DIGEST_CATEGORY)
    except Exception as e:  # noqa: BLE001  告警失败不阻断
        print(f"[history-audit] {src_table} 改写告警调用异常: {type(e).__name__} {e}")