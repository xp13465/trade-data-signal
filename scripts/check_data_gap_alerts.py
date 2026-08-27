#!/usr/bin/env python3
"""check_data_gap_alerts.py - 采集数据缺口/停更告警检测器(2026-08-27 告警兜底批)。

背景(任务台账 #103 方案A + S2 用户拍板并入):
- #103: 两处「停机>30天缺口不自愈」——上游源停发超窗口后, 恢复时若直接跳过回填会留
  永久数据洞。根治修法(#97 本尊修法 state 前沿推进)前置=版本稳定+用户启动; 当前批次
  落地的是「检测到即告警」兜底(用户拍板方向)。
  两处实体: ①etf_national_team.db etf_daily.accum_nav 增量补齐窗口 --lookback 30,
  窗口外 NULL 不再被补; ②width_history.run_recent(days=30) 写入限幅近30天, 更早缺口
  永不闭合。
- S2: 北向深缺口分轮回补(a_fund_north)推到 HKEX_BACKFILL_CAP_DAYS=210 天硬顶后放弃
  (capped_giveup, 随 feat/north-fund-gap-accumulate 上线)目前只 print 进 launchd 日志
  (锚点「已越过硬顶」)并清掉分轮 state——监控零捕获。本检测器以 DB 状态推导为主信号
  (内部断档洞 >15 天), 日志扫描为辅证实锤, 不依赖日志轮转不丢信号。

四个检查器(均只读生产库, 不写任何业务数据):
  north_hole          a_fund_north 内部断档洞>15天。洞+无分轮state=SEVERE(不自愈,
                      需人工 fallback1 全量); 洞+有state=WARN(分轮累积推进中, 观察)。
                      附带扫 backfill_evening 日志尾部「已越过硬顶」实锤行。
  north_stale         a_fund_north 最新日期落后>14自然日=SEVERE(采集静默失败堆积;
                      历史最长节假日断档12天(2016国庆), 14不误报)。覆盖「任务rc=0
                      但数据没进库」的静默面(进程监控抓不到)。
  etf_accum_nav_gap   etf_daily.accum_nav 窗口外 NULL(date<=today-6天, T+2净值缓冲):
                      NULL>=20行=WARN; 最老NULL>90天升级 SEVERE 措辞(成片积累,
                      人工 accum-nav 大窗回填)。少量散点(停牌日无净值, 永补不上)
                      属数据特性不告警, 防噪音。
  width_freshness     宽度族(daily_metric, #103 二)单指标停更/断档:
                      GROUP_FULL(2016起全量8个id) 任一 MAX 落后组内参考>5自然日=WARN,
                      >=3个或落后>30天=SEVERE; 内部断档>15天=WARN(run_recent 窗外洞);
                      GROUP_NEW(20260612起3个新id) 只查 MAX 停更(起点演进中不查洞)。
                      附 mootdx_daily_raw 源对照(源没跟上=采集问题; 源有数宽度没算=
                      计算/upsert 问题)。
                      真实先例: a_width_zb_count/seal_rate 2026-07-21 起停更37天无人知,
                      即本检查器要抓的形态。

告警出口(复用 scripts/notify.py 既有通道, 不另起炉灶):
- SEVERE → notify.py --severe(邮件 + data/alerts/latest.md 覆盖式); WARN → notify.py
  普通 [告警] 邮件(对齐 detect_intraday_anomaly 提示性用法); info 只打日志。
- dedup: data/alerts/data_gap_alert_state.json 同 key 每自然日只发一次; 本轮连 info 级
  同源条目都没有(问题真正消失)才发一封 [恢复] 并清 key——低增长落回 info 观察档不算
  恢复(内审 F1 返修: 防止「还在涨但低于阈值」被误报已恢复)。state 写盘原子化
  (tmp+replace, 对照 alert_ack.py 先例; 内审 F2 返修)。人工确认: 复用
  data/alert_state.json 的 acknowledged 字段(alert_ack.py <key> 确认后 24h 免打扰,
  与 schedule_monitor 维度⑨ 契约一致)。

调度: launchd com.trade.check-data-gap 工作日 22:35(21:40 overfit 后/22:00 信号邮件后
35min 错峰, 23:00 安全窗前); bash 包装 scripts/check_data_gap_alerts.sh 出标准开始/结束
行, 供 gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读(同 overfit_monitor
先例, 防检测器自身静默挂掉成新盲区)。

用法:
  python scripts/check_data_gap_alerts.py                  # 生产检测+按需发告警
  python scripts/check_data_gap_alerts.py --dry-run        # 只打印 findings 不发送
  python scripts/check_data_gap_alerts.py --repo <path>    # 指定仓根(测试注入)
  python scripts/check_data_gap_alerts.py --self-test      # two-way 自测(临时库注入)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_REPO = Path(os.environ.get("REPO", "/Users/linhuichen/code/trade-data"))
REPO = DEFAULT_REPO  # --repo 可覆盖(见 main)

# ── 阈值常量(来源注释: 全部有实测/出处依据) ──
NORTH_HOLE_DAYS = 15        # a_fund_north 内部断档洞阈值; 实测历史最大节假日断档12天(2016国庆), 15 留余量不误报
NORTH_STALE_DAYS = 14       # a_fund_north 最新日期落后阈值; 长假断档11天<14 不误报
ACC_NAV_MAX_AGE = 6            # accum_nav NULL 视为「窗口外」的年龄: T+2 净值发布缓冲再富余, >6 天前仍 NULL=补齐通道盖不到
ACC_NAV_NULL_GROW_ALERT = 10   # 基线增量告警线: 存量(≈376行历史特性)无害, 超基线 +10 行=成片回归/补齐通道坏
ACC_NAV_GROW_SEVERE = 50       # 单轮增长超此行数升级 SEVERE
WIDTH_LAG_DAYS = 5          # 宽度族单指标 MAX 落后组内参考的容忍(3交易日≈5自然日)
WIDTH_LAG_SEVERE_DAYS = 30  # 落后超此天数升级 SEVERE(真停更, 对齐「停机>30天」语义)
WIDTH_SEVERE_MIN_N = 3      # 落后容忍内但同时 >=此数个指标落后也升级 SEVERE(族级退化)
WIDTH_HOLE_DAYS = 15        # 宽度族内部断档阈值(同 NORTH_HOLE_DAYS 口径; 预扫全史无>15洞)
# north 深缺口分轮 state 文件名(与 app/collector/direct.py _NORTH_BACKFILL_STATE 对齐)
NORTH_STATE_FILE = "north_fund_backfill_state.json"
# capped_giveup print 锚点(direct.py deep_cap 分支; 该机制上线前日志中不存在属正常)
CAP_GIVEUP_ANCHOR = "已越过硬顶"
# 北向采集 print 落点(backfill_metrics.sh 由 backfill_evening 任务跑 direct 指标)
NORTH_LOG_CANDIDATES = ["backfill_evening_launchd.log", "backfill_evening_launchd.err"]

# 宽度族指标清单(与 app/collector/width_history.py 写入 id 对齐; 改宽度指标清单须同步此处)
WIDTH_GROUP_FULL = [  # 20160104 起全量(起点一致, 可查洞)
    "a_width_zt_count", "a_width_dt_count", "a_width_zb_count", "a_width_seal_rate",
    "a_width_up_count", "a_width_down_count", "a_amount", "a_up_down_ratio",
]
WIDTH_GROUP_NEW = [  # 20260612 起新增(起点演进中, 只查停更不查洞)
    "a_width_daban_premium", "a_width_max_lianban", "a_width_zhaban_rate",
]
WIDTH_NEW_START = "20260612"  # GROUP_NEW 预期起点(未到起点的行不算落后)


def _jd(d: str) -> int:
    """YYYYMMDD → 序数 int(非法串返回 0)。"""
    try:
        return datetime.strptime(str(d)[:8], "%Y%m%d").toordinal()
    except Exception:
        return 0


def _find_holes(dates: list[str], hole_days: int) -> list[tuple[str, str, int]]:
    """排序日期串列表里找相邻断档 >hole_days 自然日的洞, 返回 [(前日期, 后日期, 断档天数)]。"""
    ds = sorted({str(d) for d in dates if d and len(str(d)) >= 8})
    holes = []
    for a, b in zip(ds, ds[1:]):
        ja, jb = _jd(a), _jd(b)
        if ja and jb and jb - ja > hole_days:
            holes.append((a, b, jb - ja))
    return holes


class Finding:
    """单条告警发现。key 用于 dedup/ack, level∈{info,warn,severe}。"""

    def __init__(self, key: str, level: str, title: str, detail: str):
        self.key, self.level, self.title, self.detail = key, level, title, detail


def _q1(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> tuple:
    row = conn.execute(sql, params).fetchone()
    return row if row else ()


# ── checker 1+2: 北向 a_fund_north(S2 + 静默失败面) ──

def check_north(repo: Path, today: datetime) -> list[Finding]:
    out: list[Finding] = []
    db = repo / "data" / "sentiment.db"
    if not db.exists():
        return [Finding("data_gap:north", "warn", "北向检测跳过(主库缺失)",
                        f"{db} 不存在, north 检查未执行(环境异常)")]

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM daily_metric WHERE metric_id='a_fund_north' ORDER BY date")]
    finally:
        conn.close()
    mx = dates[-1] if dates else ""

    # checker north_stale: 保鲜(最新日期落后; 抓「任务 rc=0 但数据没进库」静默面)
    if mx:
        lag = _jd(today.strftime("%Y%m%d")) - _jd(mx)
        if lag > NORTH_STALE_DAYS:
            out.append(Finding(
                "data_gap:north_stale", "severe",
                f"北向资金 a_fund_north 已 {lag} 天未更新",
                f"最新数据日 {mx}, 距今 {lag} 自然日(阈值 {NORTH_STALE_DAYS})。<br>"
                f"影响: 首页情绪分/北向展示读到旧数据, AI 宏输入滞后。<br>"
                f"日志: {repo}/data/logs/backfill_evening_launchd.log<br>"
                f"建议: 任务 rc=0 也可能静默没写库(东财封禁+fallback 均挂时仅 print); "
                f"查最近一轮 backfill_evening 日志 [a_fund_north] 段, 必要时手动补采。"))

    # checker north_hole: 内部断档洞(不自愈缺口; capped_giveup 的 DB 可观测等价信号)
    holes = _find_holes(dates, NORTH_HOLE_DAYS)
    if holes:
        holes_txt = "; ".join(f"{a}→{b} 缺{d}天" for a, b, d in holes[:5])
        state_p = db.parent / NORTH_STATE_FILE
        state_on = state_p.exists()
        state_txt = ""
        if state_on:
            try:
                st = json.loads(state_p.read_text(encoding="utf-8"))
                state_txt = f"前沿 {st.get('earliest_covered', '?')}(updated_at {st.get('updated_at', '?')})"
            except Exception:
                state_txt = "state 文件存在但不可读"
        # 日志实锤扫描: capped_giveup print 只进 launchd 日志(state 已被清, 无持久化标记)
        log_hit = _scan_cap_giveup_log(repo)

        if state_on and not log_hit:
            out.append(Finding(
                "data_gap:north_hole", "warn",
                f"北向 a_fund_north 存在 {len(holes)} 处深缺口(分轮回补推进中)",
                f"洞: {holes_txt}。<br>分轮 state 在({state_txt}), 回补机制每轮向前推进属正常; "
                f"若数日无推进或逼近 210 天硬顶将升级为放弃告警。"))
        else:
            ev = f"<br>日志实锤: {log_hit}" if log_hit else \
                 "<br>日志尾部未见「已越过硬顶」行(可能为历史洞或日志已轮转)。"
            out.append(Finding(
                "data_gap:north_hole", "severe",
                f"北向 a_fund_north 深缺口不自愈({len(holes)} 处断档>{NORTH_HOLE_DAYS}天, 分轮已放弃/未推进)",
                f"洞: {holes_txt}。<br>影响: 该区间北向数据永久缺失, 情绪分历史/AI宏回测口径留洞。"
                f"{ev}<br>日志: {repo}/data/logs/backfill_evening_launchd.log<br>"
                f"建议: 人工兜底=东财 fallback1 全量回填或手动补采; 长期=#97 state 前沿推进修法"
                f"(pending #103 等用户启动)。"))
    return out


def _scan_cap_giveup_log(repo: Path) -> str:
    """扫北向采集日志尾部找 capped_giveup 实锤行, 返回证据文本(无=空串)。"""
    log_dir = repo / "data" / "logs"
    for name in NORTH_LOG_CANDIDATES:
        p = log_dir / name
        if not p.exists():
            continue
        try:
            size = p.stat().st_size
            with open(p, "rb") as f:
                f.seek(max(0, size - 512 * 1024))  # 只读尾部 512KB 防大文件
                tail = f.read().decode("utf-8", errors="replace")
            hits = [ln.strip() for ln in tail.splitlines() if CAP_GIVEUP_ANCHOR in ln]
            if hits:
                return hits[-1][:300]
        except Exception:
            continue
    return ""


# ── checker 3: etf_daily.accum_nav 窗口外 NULL(#103 一) ──

def check_etf_accum_nav(repo: Path, today: datetime,
                        baseline: dict | None = None) -> tuple[list[Finding], dict | None]:
    """#103 一: accum_nav 窗口外 NULL 监控(**基线增量口径**)。

    生产实况: 全史窗口外 NULL 存量≈376 行(2012 起, 含早年缺净值/停牌日特性),
    属无害存量——若按绝对值告警=每天一封噪音邮件永不恢复。本检查锚定存量基线
    (首日自动建档, 存 alerts state), 只对**超出基线的增长**(成片回归/补齐通道坏掉)
    告警, 对齐 #103「检测缺口不自愈扩大」的本意。
    返回 (findings, new_baseline_or_None)。
    """
    db = repo / "data" / "etf_national_team.db"
    if not db.exists():
        return ([Finding("data_gap:etf_accum_nav_gap", "warn", "ETF累计净值检测跳过(库缺失)",
                        f"{db} 不存在, 未检测(环境异常)")], None)
    cutoff = (today - timedelta(days=ACC_NAV_MAX_AGE)).strftime("%Y%m%d")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    try:
        n, oldest = _q1(conn, "SELECT COUNT(*), MIN(date) FROM etf_daily "
                              "WHERE accum_nav IS NULL AND date <= ?", (cutoff,))
        n = int(n or 0)
    finally:
        conn.close()
    cur_base = {"count": n, "oldest": str(oldest or ""), "set_at": today.strftime("%Y-%m-%d")}
    if n == 0:
        return ([], cur_base if not baseline else baseline)
    oldest = str(oldest or "?")

    # 首轮运行: 建档不发告警(info 说明), 下轮起才有可比基线
    if not baseline or "count" not in baseline:
        return ([Finding(
            "data_gap:etf_accum_nav_gap", "info",
            f"ETF 累计净值窗口外 NULL 存量基线建档: {n} 行(最老 {oldest})",
            f"首日锚定存量基线(历史存量属无害, 见告警批报告); 此后只对超出基线 "
            f"+{ACC_NAV_NULL_GROW_ALERT} 行的增长告警(#103 方案A: 停机超窗留下的洞不再自动补齐,"
            f"扩容才是事故)。")], cur_base)

    growth = n - int(baseline.get("count", n))
    if growth <= 0:
        return ([], baseline)
    if growth < ACC_NAV_NULL_GROW_ALERT:
        return ([Finding(
            "data_gap:etf_accum_nav_gap", "info",
            f"ETF 累计净值窗口外 NULL 增长 +{growth}(基线 {baseline['count']} → {n}, 低于告警线)",
            f"少量增长多为当日停牌等特性, 达 +{ACC_NAV_NULL_GROW_ALERT} 行升级告警。")], baseline)

    base_oldest = str(baseline.get("oldest") or "?")
    tail = (f"最老 NULL {oldest}(较基线最早 {base_oldest} 更老), 缺口向更深历史蔓延, 属成片积累需人工大窗回填。"
            if _jd(oldest) and _jd(base_oldest) and _jd(oldest) < _jd(base_oldest)
            else f"最老 NULL {oldest}。")
    return ([Finding(
        "data_gap:etf_accum_nav_gap",
        "severe" if growth >= ACC_NAV_GROW_SEVERE else "warn",
        f"ETF 累计净值(accum_nav)窗口外缺口扩大 +{growth} 行({baseline['count']}→{n})",
        f"增量补齐通道 accum-nav --lookback 30 只盖近30天, 窗口外 NULL 不会被自动补齐"
        f"(#103 方案A); 本轮超出存量基线 {baseline['count']} 行, 为新增不自愈缺口。{tail}<br>"
        f"影响: 受影响 ETF 收益率/TE 前复权口径缺净值。<br>"
        f"日志: {repo}/data/logs/etf_national_team_launchd.log<br>"
        f"建议: 手动兜底 `python -m app.collector.etf_national_team accum-nav --lookback <更大天数>`; "
        f"根治=#103 本尊修法(state 前沿推进, 等用户启动)。")], cur_base)


# ── checker 4: 宽度族保鲜/断档(#103 二) ──

def check_width(repo: Path, today: datetime) -> list[Finding]:
    db = repo / "data" / "sentiment.db"
    src_db = repo / "data" / "stock_daily.db"
    if not db.exists():
        return [Finding("data_gap:width_gap", "warn", "宽度族检测跳过(主库缺失)",
                        f"{db} 不存在, 未检测(环境异常)")]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    try:
        dates_by_id: dict[str, list[str]] = {}
        for mid in WIDTH_GROUP_FULL + WIDTH_GROUP_NEW:
            dates_by_id[mid] = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM daily_metric WHERE metric_id=? ORDER BY date", (mid,))]
    finally:
        conn.close()

    out: list[Finding] = []
    ref_full = max((dates_by_id[m][-1] if dates_by_id[m] else "" for m in WIDTH_GROUP_FULL), default="")
    ref_new = max((dates_by_id[m][-1] if dates_by_id[m] else "" for m in WIDTH_GROUP_NEW), default="")
    ref = ref_full or ref_new
    ref_jd = max(_jd(ref_full), _jd(ref_new))

    # 4a 单指标停更(落后组内参考): seal_rate/zb_count 型真实先例(20260721 停更37天无人知)
    severe_items: list[str] = []
    mild_items: list[str] = []
    for mid in WIDTH_GROUP_FULL + WIDTH_GROUP_NEW:
        rows = dates_by_id.get(mid, [])
        mx = rows[-1] if rows else ""
        if mid in WIDTH_GROUP_NEW and mx and _jd(mx) < _jd(WIDTH_NEW_START):
            continue  # 新指标尚未到预期起点, 不算落后
        lag = ref_jd - _jd(mx) if (mx and ref_jd) else 10**6
        desc = f"{mid}(止步 {mx or '无数据'}, 落后{lag}天)" if lag < 10**6 else f"{mid}(无数据)"
        if lag > WIDTH_LAG_SEVERE_DAYS:
            severe_items.append(desc)
        elif lag > WIDTH_LAG_DAYS:
            mild_items.append(desc)
    if severe_items:
        out.append(Finding(
            "data_gap:width_gap", "severe",
            f"宽度指标停更 {len(severe_items)} 个: {', '.join(severe_items)}",
            f"宽度族参考日 {ref}; run_recent(days=30) 写入限幅窗外不会自动补齐(#103 二同构)。"
            f"真实先例: a_width_zb_count/seal_rate 20260721 起停更 37 天无人知。<br>"
            f"影响: 宽度/封板率展示与 AI 宏输入缺该指标近值。<br>"
            f"建议: 手动 `python -m app.collector.width_history --recent --days=60` 补算; "
            f"持续停更查 compute_width 该指标 NaN 跳过分支。<br>"
            f"日志: {repo}/data/logs/update_all_launchd.log"))
    elif mild_items:
        out.append(Finding(
            "data_gap:width_gap", "warn",
            f"宽度族 {len(mild_items)} 个指标落后参考日 {ref}",
            f"落后者: {', '.join(mild_items)}。3交易日容忍 {WIDTH_LAG_DAYS} 天, 可能是写入限幅"
            f"或单指标计算异常早期信号(超 {WIDTH_LAG_SEVERE_DAYS} 天升级严重)。"))

    # 4b 内部断档洞(run_recent 窗外历史洞; 仅 GROUP_FULL, 起点一致可判)
    holes_all = []
    for mid in WIDTH_GROUP_FULL:
        for a, b, d in _find_holes(dates_by_id.get(mid, []), WIDTH_HOLE_DAYS):
            holes_all.append(f"{mid}: {a}→{b} 缺{d}天")
    if holes_all:
        out.append(Finding(
            "data_gap:width_gap", "warn",
            f"宽度族 {len(holes_all)} 处历史断档洞(run_recent 窗口外不自愈)",
            f"洞: {'; '.join(holes_all[:5])}{'...' if len(holes_all) > 5 else ''}。"
            f"<br>建议: 手动 `python -m app.collector.width_history`(全量 run)回填。"))

    # 4c 源对照: mootdx 源 vs 宽度参考日(源有数宽度没算=计算/写入问题)
    if src_db.exists() and ref_jd:
        conn2 = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True, timeout=30.0)
        try:
            row2 = _q1(conn2, "SELECT MAX(date) FROM mootdx_daily_raw")
            src_max = row2[0] if row2 else ""
        finally:
            conn2.close()
        if src_max and _jd(src_max) - ref_jd > WIDTH_LAG_DAYS:
            out.append(Finding(
                "data_gap:width_gap", "warn",
                f"涨停源(mootdx)已有数据到 {src_max}, 宽度族止步 {ref}",
                f"源已采集而宽度未重算(run_recent 未跑或写入失败), 查 update_all/scheduler step9。"
                f"<br>日志: {repo}/data/logs/update_all_launchd.log"))
    return out


# ── 出口: dedup + ack + notify(复用 notify.py 既有通道) ──

def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _notify(repo: Path, subject: str, body: str, severe: bool, dry_run: bool) -> bool:
    """经 scripts/notify.py 发送(邮件渠道); severe 额外写 data/alerts/latest.md。"""
    cmd = [sys.executable, str(repo / "scripts" / "notify.py"), subject, body]
    if severe:
        cmd.append("--severe")
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[check_data_gap] notify 退出码 {r.returncode}: {(r.stderr or '')[-300:]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[check_data_gap] notify 异常: {e}", file=sys.stderr)
        return False


def _save_state_atomic(state_p: Path, state: dict) -> None:
    """原子写(tmp + replace), 防半截文件被并发读者读走(对照 alert_ack.py _save_atomic 先例)。

    失败只打日志不抛(不影响检测主流程); 原文件在 dumps/write 任一步失败时保持原样,
    绝不截断(替代旧 write_text 直写——进程中途死会留半截 json, _load_json 兜底虽能容错
    但 dedup/基线状态会静默归零)。"""
    state_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_p.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        tmp.replace(state_p)
    except Exception as e:
        print(f"[check_data_gap] state 原子写失败(保留旧文件): {e}", file=sys.stderr)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _ack_suppressed(repo: Path, key: str, now: datetime) -> bool:
    """人工确认免打扰: data/alert_state.json 该 key acknowledged 24h 内(alert_ack.py 契约一致)。"""
    st = _load_json(repo / "data" / "alert_state.json", {})
    ent = st.get(key)
    if not isinstance(ent, dict):
        return False
    ack = ent.get("acknowledged")
    if not ack:
        return False
    try:
        t = datetime.strptime(str(ack)[:19], "%Y-%m-%d %H:%M:%S")
        return (now - t) < timedelta(hours=24)
    except Exception:
        return False


SEV_ORDER = {"info": 0, "warn": 1, "severe": 2}


def run_alerts(repo: Path, findings: list[Finding], dry_run: bool,
               now: datetime | None = None, extra_state: dict | None = None) -> None:
    """按 dedup/ack 规则发送告警 + 恢复通知, 维护 data_gap_alert_state.json。

    extra_state: 内部键(如下划线前缀的 _accum_nav_baseline 基线)合并进 state; 恢复清理
    循环跳过下划线内部键(它们不是告警 key)。dry-run 不落盘(零副作用)。
    """
    now = now or datetime.now()
    state_p = repo / "data" / "alerts" / "data_gap_alert_state.json"
    state_p.parent.mkdir(parents=True, exist_ok=True)
    state: dict = _load_json(state_p, {})
    today = now.strftime("%Y-%m-%d")

    fired_keys = {f.key for f in findings if SEV_ORDER.get(f.level, 0) >= 1}
    # 活跃 key = 本轮 findings 里该 key 存在任意级别条目(warn/severe 告警或 info 观察),
    # 用于恢复判定(F1 内审返修): 低增长(+1~9 行走 info 分支)仍是「问题活跃中」,
    # 只是不达发送阈值——若按 fired_keys 判恢复, 会发出「已恢复」误导邮件而缺口实际还在涨。
    active_keys = {f.key for f in findings}
    for f in findings:
        sev = SEV_ORDER.get(f.level, 0)
        print(f"[check_data_gap][{f.level}] {f.title}" + ("" if sev >= 1 else "  [info 只记日志]"))
        if sev < 1:
            continue
        if _ack_suppressed(repo, f.key, now):
            print(f"[check_data_gap] {f.key} 已人工确认(24h 免打扰), 跳过发送")
            continue
        if state.get(f.key, {}).get("last_fired") == today:
            print(f"[check_data_gap] {f.key} 今日已发过, 跳过(dedup)")
            continue
        subject = f"[{'严重' if f.level == 'severe' else '告警'}][数据缺口] {f.title} {now.strftime('%m-%d %H:%M')}"
        ok = _notify(repo, subject, f.detail, severe=(f.level == "severe"), dry_run=dry_run)
        if ok or dry_run:
            state[f.key] = {"last_fired": today, "level": f.level, "title": f.title}

    # 恢复通知: state 有记录但本轮连 info 级同源条目都没有 → 问题真正消失才发恢复并清 key
    for key in list(state.keys()):
        if key.startswith("_") or key in active_keys:
            continue  # 下划线内部键不参与; 同 key 本轮仍活跃(info 观察也算)不发恢复
        info = state.pop(key)
        subject = f"[恢复][数据缺口] {info.get('title', key)} 已恢复 {now.strftime('%m-%d %H:%M')}"
        body = f"告警 key: {key}<br>本轮检测已无任何同源信号(缺口闭合且无新增增长)。<br>无需操作, 已自动恢复。"
        print(f"[check_data_gap][recovered] {key} 发恢复通知(dry_run={dry_run})")
        _notify(repo, subject, body, severe=False, dry_run=dry_run)

    if extra_state:
        state.update(extra_state)

    # dry-run 零副作用: 不落盘 state(真实运行才登记/清理 dedup 状态)
    if dry_run:
        print("[check_data_gap][dry-run] state 不落盘(dry-run 零副作用)")
        return
    _save_state_atomic(state_p, state)


def run(repo: Path, dry_run: bool) -> int:
    today = datetime.now()
    state_p = repo / "data" / "alerts" / "data_gap_alert_state.json"
    prev_state: dict = _load_json(state_p, {})
    findings: list[Finding] = []
    new_baseline = None
    findings += check_north(repo, today)
    acc_f, new_baseline = check_etf_accum_nav(
        repo, today, baseline=prev_state.get("_accum_nav_baseline"))
    findings += acc_f
    findings += check_width(repo, today)
    print(f"[check_data_gap] 检测完成: {len(findings)} 条发现 "
          f"(severe={sum(1 for f in findings if f.level == 'severe')}, "
          f"warn={sum(1 for f in findings if f.level == 'warn')}, "
          f"info={sum(1 for f in findings if f.level == 'info')})")
    run_alerts(repo, findings, dry_run=dry_run, now=today,
               extra_state={"_accum_nav_baseline": new_baseline} if new_baseline else None)
    return 0


# ── two-way 自测: 临时库注入, 必命中+必不命中各跑一轮 ──

_TABLE_COLUMNS = {
    "daily_metric": ("date TEXT NOT NULL, metric_id TEXT NOT NULL, value REAL, source TEXT, "
                     "updated_at TEXT, PRIMARY KEY (date, metric_id)", 5),
    "etf_daily": ("date TEXT NOT NULL, etf_code TEXT NOT NULL, accum_nav REAL, "
                  "PRIMARY KEY (date, etf_code)", 3),
    "mootdx_daily_raw": ("code TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY (code, date)", 2),
}


def _make_dbs(base: Path, tables: dict[str, list[tuple]],
              north_state: dict | None, cap_giveup_line: str | None) -> None:
    """在 base/data 下重建 mini 库/日志/state 文件(每 case 干净重来, unlink 防残留)。"""
    data = base / "data"
    (data / "logs").mkdir(parents=True, exist_ok=True)
    for tbl, rows in tables.items():
        ddl_cols, ncol = _TABLE_COLUMNS[tbl]
        dbname = {"daily_metric": "sentiment.db", "etf_daily": "etf_national_team.db",
                  "mootdx_daily_raw": "stock_daily.db"}[tbl]
        p = data / dbname
        if p.exists():
            p.unlink()
        c = sqlite3.connect(p)
        c.execute(f"CREATE TABLE {tbl} ({ddl_cols})")
        ph = ",".join("?" * ncol)
        c.executemany(f"INSERT OR IGNORE INTO {tbl} VALUES ({ph})", rows)
        c.commit()
        c.close()
    sp = data / NORTH_STATE_FILE
    if north_state is None:
        sp.unlink(missing_ok=True)
    else:
        sp.write_text(json.dumps(north_state), encoding="utf-8")
    lp = data / "logs" / "backfill_evening_launchd.log"
    if cap_giveup_line is None:
        lp.unlink(missing_ok=True)
    else:
        lp.write_text(cap_giveup_line + "\n", encoding="utf-8")


def _series(a: str, b: str) -> list[str]:
    """YYYYMMDD a..b 全部自然日(测试夹具用)。"""
    d0, d1 = datetime.strptime(a, "%Y%m%d"), datetime.strptime(b, "%Y%m%d")
    out, d = [], d0
    while d <= d1:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def self_test() -> int:
    """two-way: case B(正常)必不命中 + case A/A2/A3 注入态按预期必命中/降级/静默。"""
    now = datetime(2026, 8, 27, 22, 35)
    fails: list[str] = []

    def all_tables(north_dates, width_spec, null_rows, mootdx_dates):
        return {
            "daily_metric": ([("".join(d), "a_fund_north", 1.0, "t", "t") for d in north_dates] +
                             [("".join(d), mid, 1.0, "t", "t")
                              for mid, ds in width_spec.items() for d in ds]),
            "etf_daily": null_rows + [(("".join(d)), "600000", 1.0) for d in mootdx_dates],
            "mootdx_daily_raw": [("510300", "".join(d)) for d in mootdx_dates],
        }

    with tempfile.TemporaryDirectory(prefix="gap_alert_test_") as td:
        base = Path(td)
        normal = _series("20260101", "20260826")

        # ── case B: 一切正常 → 四 checker 无 warn/severe ──
        width_full = {m: normal for m in WIDTH_GROUP_FULL}
        width_new = {m: normal for m in WIDTH_GROUP_NEW}
        _make_dbs(base, all_tables(normal, {**width_full, **width_new}, [], normal),
                  north_state=None, cap_giveup_line=None)
        fB = (check_north(base, now) + check_etf_accum_nav(base, now)[0] +
              check_width(base, now))
        badB = [f for f in fB if SEV_ORDER.get(f.level, 0) >= 1]
        if badB:
            fails.append(f"case B(正常态)不应命中 warn/severe: {[(f.key, f.level) for f in badB]}")

        # ── case A: 四类异常注入 → 每 checker 必命中且级别正确 ──
        # 北向: 挖内部洞 0502~0531(31天>15) + 顶部砍到 0731(stale 落后27天>14)
        north = [d for d in normal if not ("20260502" <= d <= "20260531") and d <= "20260731"]
        width_a = {**width_full, **width_new}
        width_a["a_width_zb_count"] = [d for d in normal if d <= "20260710"]    # 停更47天>30
        width_a["a_width_seal_rate"] = [d for d in normal if d <= "20260710"]
        width_a["a_width_daban_premium"] = [d for d in normal if d <= "20260815"]  # 落后12天(容忍5~30=mild)
        nulls_a = [("20260301", f"51{i:04d}", None) for i in range(25)]  # 25行>=20 且最老179天>90
        _make_dbs(base, all_tables(north, width_a, nulls_a, normal),
                  north_state=None,
                  cap_giveup_line="2026-08-27 16:35:01 [INFO] [a_fund_north][hkex] 分轮回补前沿 "
                                  "20250130 已越过硬顶 210天(≈源保留窗),放弃分轮回归常规增量")
        fA = check_north(base, now) + check_etf_accum_nav(base, now)[0] + check_width(base, now)
        keysA = {f.key: f.level for f in fA}
        expectA = {
            "data_gap:north_stale": "severe",        # 最新 0731, 落后27天>14
            "data_gap:north_hole": "severe",         # 洞31天+无state+日志实锤
            "data_gap:width_gap": "severe",          # zb/seal 停更47天>30
        }
        # etf_accum_nav 的增量口径由 case A3 套件单独覆盖(建档/低增静默/高增severe)
        for k, lv in expectA.items():
            if k not in keysA:
                fails.append(f"case A 缺告警 {k} (got={list(keysA)})")
            elif keysA[k] != lv:
                fails.append(f"case A {k} 期望 {lv} 实得 {keysA[k]}")
        nh_detail = " ".join(f.detail for f in fA if f.key == "data_gap:north_hole")
        if CAP_GIVEUP_ANCHOR not in nh_detail:
            fails.append("case A north_hole detail 未附「已越过硬顶」日志实锤")
        # mild 单指标(daban_premium 落后12天)被 severe 主条吞并时不另计; 洞文本须含日期区间
        nh_title = " ".join(f.title for f in fA if f.key == "data_gap:north_hole")
        if "20260501" not in nh_title and "20260501" not in nh_detail:
            fails.append("case A north_hole 未描述洞区间(应含 20260501→20260601)")

        # ── case A2: 洞 + 有分轮state(无日志实锤) → 降级 warn(推进中观察) ──
        _make_dbs(base, all_tables(north, width_a, nulls_a, normal),
                  north_state={"metric_id": "a_fund_north", "earliest_covered": "20260601",
                               "updated_at": "2026-08-27 16:35:00"},
                  cap_giveup_line=None)
        fA2 = {f.key: f.level for f in check_north(base, now)}
        if fA2.get("data_gap:north_hole") != "warn":
            fails.append(f"case A2 有 state 应降为 warn, 实得 {fA2.get('data_gap:north_hole')}")

        # ── case A3: 首轮无基线 → accum NULL 存量只建档(info), 不告警; 次轮起按增量判定 ──
        nulls_25 = [("20260301", f"51{i:04d}", None) for i in range(25)]
        _make_dbs(base, all_tables(normal, {**width_full, **width_new}, nulls_25, normal),
                  north_state=None, cap_giveup_line=None)
        fa3, bl = check_etf_accum_nav(base, now)
        a3_bad = [f for f in fa3 if SEV_ORDER.get(f.level, 0) >= 1]
        if a3_bad or not bl or bl.get("count") != 25:
            fails.append(f"case A3 首轮应只建档(info)+返回基线25, 实得 "
                         f"{[(f.key, f.level) for f in fa3]} / baseline={bl}")
        # +8 行(<10): 不告警; +60 行(>50): severe
        nulls_33 = nulls_25 + [("20260401", f"71{i:02d}", None) for i in range(8)]
        _make_dbs(base, all_tables(normal, {**width_full, **width_new}, nulls_33, normal),
                  north_state=None, cap_giveup_line=None)
        fa3b, _ = check_etf_accum_nav(base, now, baseline=bl)
        if any(SEV_ORDER.get(f.level, 0) >= 1 for f in fa3b):
            fails.append(f"case A3b 增长+8(<告警线10)不应告警: {[(f.key, f.level) for f in fa3b]}")
        nulls_85 = nulls_25 + [(("20260401"), f"81{i:03d}", None) for i in range(60)]
        _make_dbs(base, all_tables(normal, {**width_full, **width_new}, nulls_85, normal),
                  north_state=None, cap_giveup_line=None)
        fa3c, _ = check_etf_accum_nav(base, now, baseline=bl)
        lv3c = next((f.level for f in fa3c if f.key == "data_gap:etf_accum_nav_gap"), None)
        if lv3c != "severe":
            fails.append(f"case A3c 增长+60(>severe线50)应 severe, 实得 {lv3c}")

        # ── case A4: run_alerts 出口链路(stub notify 真发模式): state 登记+dedup+恢复通知
        # + extra_state 内部键保留(dry-run 不落盘由生产 --dry-run 行为保证) ──
        # stub notify.py 验证子进程调用通路(命中真实文件即 exit 0)
        stub = base / "scripts" / "notify.py"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        test_findings = [
            Finding("data_gap:t1", "severe", "T1 标题", "T1 明细"),
            Finding("data_gap:t1", "severe", "T1 标题二", "T1 明细二"),  # 同 key 第二条触发 dedup 只登记一次
        ]
        run_alerts(base, test_findings, dry_run=False, now=datetime(2026, 8, 27, 22, 35),
                   extra_state={"_accum_nav_baseline": {"count": 376}})
        st1 = _load_json(base / "data" / "alerts" / "data_gap_alert_state.json", {})
        if set(st1.keys()) != {"data_gap:t1", "_accum_nav_baseline"}:
            fails.append(f"case A4 state 应登记 t1+基线内部键, 实得 {list(st1)}")
        # 第二轮无该 finding → 发恢复清 t1, 基线内部键不受恢复清理影响
        run_alerts(base, [], dry_run=False, now=datetime(2026, 8, 28, 22, 35))
        st2 = _load_json(base / "data" / "alerts" / "data_gap_alert_state.json", {})
        if set(st2.keys()) != {"_accum_nav_baseline"}:
            fails.append(f"case A4 恢复后应只剩基线内部键, 实得 {list(st2)}")

    # ── case A5(内审 F1 返修断言): warn 登记后次轮只出 info 同源条目 → 不发恢复邮件、key 保留 ──
    notify_calls: list[str] = []
    _orig_notify = _notify

    def _spy_notify(repo, subject, body, severe=False, dry_run=False):
        notify_calls.append(subject)
        return True

    globals()["_notify"] = _spy_notify
    try:
        with tempfile.TemporaryDirectory(prefix="gap_alert_f1_") as td:
            b5 = Path(td)
            sp5 = b5 / "data" / "alerts" / "data_gap_alert_state.json"
            sp5.parent.mkdir(parents=True, exist_ok=True)
            t0 = datetime(2026, 8, 26, 22, 35)
            t1 = datetime(2026, 8, 27, 22, 35)
            # 第 1 轮: warn 发送登记(+15 行增长达告警线)
            run_alerts(b5, [Finding("data_gap:t1", "warn", "T1 增长告警", "+15 行")],
                       dry_run=False, now=t0)
            assert any("数据缺口] T1 增长告警" in s for s in notify_calls), "第 1 轮应发 warn 邮件"
            # 第 2 轮(F1 场景): 增长回落到 +5 行 → info 同源条目; 断言不发恢复、state key 保留
            run_alerts(b5, [Finding("data_gap:t1", "info", "T1 低增观察(+5)", "低于告警线")],
                       dry_run=False, now=t1)
            recovered = [s for s in notify_calls if "[恢复]" in s]
            if recovered:
                fails.append(f"F1 断言失败: 低增 info 轮不应发恢复邮件, 实发 {recovered}")
            st5 = _load_json(sp5, {})
            if "data_gap:t1" not in st5:
                fails.append(f"F1 断言失败: info 活跃轮 state 主 key 应保留, 实得 {list(st5)}")
            if st5.get("data_gap:t1", {}).get("last_fired") != "2026-08-26":
                fails.append(f"F1 断言失败: last_fired 应保持首轮日期(不重发), 实得 {st5}")
            # 第 3 轮: findings 全空 → 问题真正消失, 此时应发恢复并清 key(反向对照)
            run_alerts(b5, [], dry_run=False, now=datetime(2026, 8, 28, 22, 35))
            if not any("[恢复]" in s for s in notify_calls):
                fails.append(f"F1 反向断言失败: 无任何同源信号后应发恢复邮件, calls={notify_calls}")
            st6 = _load_json(sp5, {})
            if "data_gap:t1" in st6:
                fails.append(f"F1 反向断言失败: 恢复后 state 应清空 t1, 实得 {list(st6)}")
    finally:
        globals()["_notify"] = _orig_notify

    # ── case A6(内审 F2 返修断言): 原子写——中途失败不留截断 json、tmp 不残留 ──
    with tempfile.TemporaryDirectory(prefix="gap_alert_f2_") as td:
        b6 = Path(td)
        sp6 = b6 / "data" / "alerts" / "data_gap_alert_state.json"
        good = {"k": {"last_fired": "2026-08-26"}}
        sp6.parent.mkdir(parents=True, exist_ok=True)
        sp6.write_text(json.dumps(good), encoding="utf-8")
        # 注入不可 JSON 序列化对象模拟「dumps 中途抛错/进程被杀在写 tmp 阶段」
        _save_state_atomic(sp6, {"bad": object()})
        try:
            after = json.loads(sp6.read_text(encoding="utf-8"))
            if after != good:
                fails.append(f"F2 断言失败: 写失败后原文件应原样保留, 实得 {after}")
        except Exception as e:
            fails.append(f"F2 断言失败: 写失败后原文件不可解析({e})")
        tmp_left = sp6.with_suffix(".json.tmp")
        if tmp_left.exists():
            fails.append("F2 断言失败: 失败后 .json.tmp 应清理不残留")
        # 成功路径: replace 后新内容可读 + 截断字符验证(文件末尾是完整 json 而非半行)
        ok_state = {"done": {"level": "warn"}}
        _save_state_atomic(sp6, ok_state)
        if _load_json(sp6, {}) != ok_state or tmp_left.exists():
            fails.append(f"F2 断言失败: 成功路径写入回读不一致(tmp残留={tmp_left.exists()})")

    if fails:
        for x in fails:
            print(f"[self-test] FAIL: {x}")
        print(f"[self-test] 共 {len(fails)} 项失败")
        return 1
    print("[self-test] PASS: two-way 全过(case B 正常态零命中 / case A 必命中+级别正确"
          "+日志实锤入 detail / A2 有state降级warn / A3 accum 基线建档+低增静默+高增severe"
          " / A4 出口 dedup+恢复链路 / A5-F1 低增info不发恢复+真消失才恢复 / A6-F2 原子写失败保留旧文件)")
    return 0


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser(description="采集数据缺口/停更告警检测器")
    ap.add_argument("--repo", default="", help="仓根(缺省 REPO env 或 trade-data)")
    ap.add_argument("--dry-run", action="store_true", help="只打印 findings 不发送")
    ap.add_argument("--self-test", action="store_true", help="two-way 自测")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.repo:
        REPO = Path(a.repo)
    return run(REPO, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
