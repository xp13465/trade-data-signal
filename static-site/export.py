#!/usr/bin/env python3
"""静态化导出脚本：从 SQLite (data/sentiment.db) 导出所有 API 端点数据为静态 JSON。

查询逻辑统一在 app/queries.py（与 main.py 路由共用）。本文件只保留：
- 进程级缓存层（series 全量缓存 + stats 缓存，包装 queries 调用，P1-2 性能优化）
- JSON 写盘（write_json）
- industry 拆分导出（write_industry_split）
- main() 导出流水线

可重复跑（python static-site/export.py），覆盖 data/ 下 JSON。

导出端点：
  - data/overview.json                 （今日快照 + 指数 sparkline + 宽度 + 分数 + 行业热力图 + 买卖点 + 冰点日）
  - data/a-stock-{3m,6m,1y,3y,5y,all}.json
  - data/hk-{3m,6m,1y,3y,5y,all}.json
  - data/global-{3m,6m,1y,3y,5y,all}.json
  - data/sentiment-{3m,6m,1y,3y,5y,all}.json
  - data/industry-{3m,6m,1y,3y,5y,all}.json
  - data/index/{index_id}-all.json     （44 个指数 ohlc + signals 全历史）

range 处理方案（备注）：
  - tab 端点（a-stock/hk/global/sentiment/industry）预生成多 range JSON（各 5 个文件），
    前端按 state.range 直接读对应文件，逻辑最简（无需客户端切片）。
  - index 端点仅预生成 all 全历史（44 文件），前端读后用 ohlc 日期范围客户端过滤 signals
    （signals 数组小，过滤开销可忽略；避免 44×5=220 文件膨胀）。

数据源：仅读 data/sentiment.db（API 只用此库；stock_daily.db 仅供采集器用，API 不读）。
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# 复用 app 包代码（与 API 完全一致的查询逻辑）
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from app.collector.fetchers import load_config  # noqa: E402
from app.compute import signal_stats as sigstats  # noqa: E402
from app.db import get_conn  # noqa: E402
from app import queries  # noqa: E402

STATIC_DIR = Path(__file__).absolute().parent
DATA_DIR = STATIC_DIR / "data"
INDEX_DIR = DATA_DIR / "index"

# 1m 周期已废弃删除：前端 range 选项仅 3m/6m/1y/3y/5y/all（无 1m 按钮），1m JSON 无人 fetch（冗余）
EXPORT_RANGES = ["3m", "6m", "1y", "3y", "5y", "all"]


# ============ 进程级缓存层（P1-2 性能优化）============
# 5 tab × 6 range = 30 次 range 循环，同一 id 被查 6 次。优化：每个 id 只查全量一次，
# 后续按 start/end 字符串切片。date 是 YYYYMMDD 字符串，字典序=时间序，可直接字符串比较过滤。
# cache dict 传给 queries building block 函数（cache 参数），queries 不创建/存储 cache，
# 只在非空时读缓存。进程级缓存，export 跑完即释放（不跨进程持久化）。
_series_cache: dict = {}

# signal_stats 现算缓存（与 export 其他 export_* 保持一致，避免重复算）
_stats_cache: dict | None = None


def _get_stats() -> dict:
    """进程内缓存 signal_stats.compute() 结果。"""
    global _stats_cache
    if _stats_cache is None:
        _stats_cache = queries.stats_all()
    return _stats_cache


# ============ 端点导出函数（薄包装 queries 调用 + 缓存注入）============

def export_overview(conn, cfg):
    """复刻 /api/overview。"""
    return queries.overview(conn, cfg)


def export_a_stock(conn, cfg, rng):
    """复刻 /api/a-stock（含 ETF 候选列表，P2-新-G）。"""
    start, end = queries.range_for(rng)
    return queries.a_stock(conn, cfg, start, end, cache=_series_cache, include_etf=True)


def export_hk(conn, cfg, rng):
    """复刻 /api/hk。"""
    start, end = queries.range_for(rng)
    return queries.hk(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_global(conn, cfg, rng):
    """复刻 /api/global。"""
    start, end = queries.range_for(rng)
    return queries.global_market(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_sentiment(conn, cfg, rng):
    """复刻 /api/sentiment（不含 futures，前端读 futures.json 独立加载）。"""
    start, end = queries.range_for(rng)
    return queries.sentiment(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_industry(conn, cfg, rng):
    """复刻 /api/industry。"""
    start, end = queries.range_for(rng)
    return queries.industry(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_index_detail(conn, cfg, index_id):
    """复刻 /api/index/{index_id}?range=all。全历史 ohlc + signals + stats + strategy + etfs。"""
    start, end = queries.range_for("all")
    return queries.index_detail(conn, cfg, index_id, start, end,
                                cache=_series_cache, stats_all_dict=_get_stats(), include_etf=True)


def export_futures(conn):
    """复刻 /api/futures。同时记录当日同向准确度快照到 futures_ih_detail_acc（写入 hook）。"""
    data = queries.futures_data(conn)
    # 写入 hook：记录当日3角色的 follow_ratio 快照（INSERT OR REPLACE 幂等）
    # 仅在 export 路径写（不在 API 路径写，避免每次页面加载写 DB 致锁竞争）
    try:
        from app.compute.futures_position import record_ih_detail_acc
        for role_key, detail_key in [("中信期货", "citic_ih_detail"),
                                      ("top20", "inst_ih_detail"),
                                      ("国泰君安", "guotai_ih_detail")]:
            result = data.get(detail_key)
            if result and result.get("total"):
                record_ih_detail_acc(role=role_key, result=result, conn=conn)
        conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ record_ih_detail_acc 失败(不阻塞): {e}")
    return data


def export_futures_acc_trend(conn):
    """期货同向准确度每日趋势（futures_ih_detail_acc 表）。

    返回 {dates:[...], series:{中信期货:[...], 机构前20:[...], 国泰君安:[...]}, latest:{...}}
    每点 {date, accuracy, follow_ratio, dominant_dir}。
    用于前端趋势图：识别"同向越来越不准=风格转逆向"（follow_ratio 跌破50%）。

    role key 映射：top20→机构前20（与 queries.futures_data 的角色标签对齐）。
    """
    rows = conn.execute(
        "SELECT date, role, dominant_dir, total, same_count, contrarian_count, "
        "correct_count, wrong_count, accuracy, follow_ratio, sample_start, sample_end "
        "FROM futures_ih_detail_acc ORDER BY date, role"
    ).fetchall()
    if not rows:
        return {"dates": [], "series": {}, "latest": {}}

    role_map = {"中信期货": "中信期货", "top20": "机构前20", "国泰君安": "国泰君安"}
    dates_set: list[str] = []
    series: dict[str, list] = {v: [] for v in role_map.values()}
    by_date_role: dict[tuple, dict] = {}
    for r in rows:
        d = r["date"]
        if d not in dates_set:
            dates_set.append(d)
        role_label = role_map.get(r["role"], r["role"])
        pt = {
            "date": d,
            "accuracy": r["accuracy"],
            "follow_ratio": r["follow_ratio"],
            "dominant_dir": r["dominant_dir"],
            "total": r["total"],
            "same_count": r["same_count"],
            "contrarian_count": r["contrarian_count"],
            "sample_start": r["sample_start"],
            "sample_end": r["sample_end"],
        }
        series[role_label].append(pt)
        by_date_role[(d, role_label)] = pt

    # latest = 最新日每角色的 follow_ratio + yesterday 对比（供前3张表角标用）
    latest_date = dates_set[-1]
    prev_date = dates_set[-2] if len(dates_set) >= 2 else None
    latest: dict = {"date": latest_date, "prev_date": prev_date, "roles": {}}
    for role_label in series.keys():
        cur = by_date_role.get((latest_date, role_label))
        prev = by_date_role.get((prev_date, role_label)) if prev_date else None
        if cur:
            latest["roles"][role_label] = {
                "follow_ratio": cur["follow_ratio"],
                "yesterday_follow_ratio": prev["follow_ratio"] if prev else None,
                "dominant_dir": cur["dominant_dir"],
                "accuracy": cur["accuracy"],
                "sample_start": cur["sample_start"],
                "sample_end": cur["sample_end"],
            }

    return {"dates": dates_set, "series": series, "latest": latest}


def export_futures_acc_conclusion(conn):
    """期货同向准确度规律结论（每日刷新，幂等覆盖）。

    基于 futures_ih_detail_acc 表最新日 follow_ratio + 历史连续段统计 + 4条规律模板，
    生成结构化结论 JSON 供前端卡片化展示。

    4条规律（调研 agent 验证，附数据支撑）:
    1. 【最强】抄底: 中信同向准确度 <=30% -> 34次中33次(97%)后20日正收益，平均 +3.68%
    2. 【次强】顶部预警: 中信同向准确度 >=80% -> 22次中15次(68%)后20日负收益，平均 -2.37%
    3. 【中等】转跟随看多: 中信转同向 -> 14次切换后60日平均 +3.27%
    4. 【辅助】季节性: 4月/10月逆向（年报/三季报披露），2月/7-8月同向（春季躁动/夏季行情）
    """
    rows = conn.execute(
        "SELECT date, role, dominant_dir, total, same_count, contrarian_count, "
        "correct_count, wrong_count, accuracy, follow_ratio, sample_start, sample_end "
        "FROM futures_ih_detail_acc ORDER BY date, role"
    ).fetchall()
    if not rows:
        return {"as_of_date": "", "current_state": {}, "conclusions": [], "streak_history": {}}

    role_map = {"中信期货": "中信期货", "top20": "机构前20", "国泰君安": "国泰君安"}

    # Group by role label
    by_role: dict[str, list] = {}
    all_dates: list[str] = []
    seen_dates: set = set()
    for r in rows:
        d = r["date"]
        if d not in seen_dates:
            seen_dates.add(d)
            all_dates.append(d)
        role_label = role_map.get(r["role"], r["role"])
        by_role.setdefault(role_label, []).append(dict(r))

    all_dates.sort()
    as_of_date = all_dates[-1] if all_dates else ""

    # Compute current state + streak history for each role
    current_state: dict = {}
    streak_history: dict = {}
    for role_label, role_rows in by_role.items():
        role_rows.sort(key=lambda x: x["date"])
        latest = role_rows[-1]
        cur_dir = latest["dominant_dir"] or "-"
        # Current streak: consecutive days with same dominant_dir ending at latest
        streak = 0
        for r in reversed(role_rows):
            if (r["dominant_dir"] or "-") == cur_dir:
                streak += 1
            else:
                break
        current_state[role_label] = {
            "follow_ratio": latest["follow_ratio"],
            "dominant_dir": latest["dominant_dir"] or "-",
            "accuracy": latest["accuracy"],
            "streak_days": streak,
            "streak_type": cur_dir,
            "sample_start": latest["sample_start"],
            "sample_end": latest["sample_end"],
        }
        # Historical streak averages (all completed + current streak)
        same_streaks: list[int] = []
        contra_streaks: list[int] = []
        prev_dir = None
        cur_s = 0
        for r in role_rows:
            d = r["dominant_dir"] or "-"
            if d == prev_dir:
                cur_s += 1
            else:
                if prev_dir == "同向":
                    same_streaks.append(cur_s)
                elif prev_dir == "逆向":
                    contra_streaks.append(cur_s)
                prev_dir = d
                cur_s = 1
        if prev_dir == "同向":
            same_streaks.append(cur_s)
        elif prev_dir == "逆向":
            contra_streaks.append(cur_s)
        streak_history[role_label] = {
            "avg_same_streak": round(sum(same_streaks) / len(same_streaks), 1) if same_streaks else 0,
            "avg_contra_streak": round(sum(contra_streaks) / len(contra_streaks), 1) if contra_streaks else 0,
            "current_streak": streak,
            "current_type": cur_dir,
        }

    # Build 4 conclusions with current status
    citic = current_state.get("中信期货", {})
    citic_fr = citic.get("follow_ratio")
    citic_streak = citic.get("streak_days", 0)
    citic_dir = citic.get("dominant_dir", "-")

    def _fr_str(fr):
        return f"{fr:.1f}%" if fr is not None else "N/A"

    # Pattern 1: 抄底 (中信 <=30%)
    p1_triggered = citic_fr is not None and citic_fr <= 30
    p1_status = (f"已触发（当前{_fr_str(citic_fr)}）" if p1_triggered
                 else f"未触发（当前{_fr_str(citic_fr)}）" if citic_fr is not None else "数据不足")

    # Pattern 2: 顶部预警 (中信 >=80%)
    p2_triggered = citic_fr is not None and citic_fr >= 80
    p2_status = (f"已触发（当前{_fr_str(citic_fr)}）" if p2_triggered
                 else f"未触发（当前{_fr_str(citic_fr)}）" if citic_fr is not None else "数据不足")

    # Pattern 3: 转跟随看多 (中信刚切换到同向, streak 1-5 日视为"刚切换")
    p3_triggered = citic_dir == "同向" and 1 <= citic_streak <= 5
    if citic_dir == "同向":
        p3_status = (f"刚切换同向{citic_streak}日（关注看多）" if citic_streak <= 5
                     else f"已同向{citic_streak}日（非刚切换）")
    else:
        p3_status = f"当前{citic_dir}（需转同向才触发）"

    # Pattern 4: 季节性 (4月/10月逆向季, 2月/7-8月同向季)
    cur_month = int(as_of_date[4:6]) if len(as_of_date) >= 6 else 0
    if cur_month in (4, 10):
        p4_status = f"当前{cur_month}月（逆向季：年报/三季报披露期）"
        p4_action = "参考逆向倾向"
        p4_triggered = True
    elif cur_month == 2 or cur_month in (7, 8):
        p4_status = f"当前{cur_month}月（同向季：春季躁动/夏季行情）"
        p4_action = "参考同向倾向"
        p4_triggered = True
    else:
        p4_status = f"当前{cur_month}月（非季节性关键月）"
        p4_action = "季节性不显著"
        p4_triggered = False

    # === 按月聚合 dominant_dir 序列（规律 A/B 用） ===
    # 中信期货每日 dominant_dir 取 same/contrarian 较大者，follow_ratio=same/total*100
    # 可跌破 50%。按月聚合判定月风格：同向月 / 逆向月 / 震荡月（占比接近或月均 fr≈50%）。
    month_rows = conn.execute(
        "SELECT substr(date,1,6) as month, dominant_dir, COUNT(*) as cnt, "
        "AVG(follow_ratio) as avg_fr "
        "FROM futures_ih_detail_acc WHERE role='中信期货' "
        "GROUP BY month, dominant_dir ORDER BY month, dominant_dir"
    ).fetchall()
    month_dir_count = {}   # month -> {'同向':n, '逆向':n}
    month_fr_sum = {}      # month -> sum(follow_ratio * cnt)
    month_total = {}       # month -> total days
    for r in month_rows:
        m = r["month"]
        d = r["dominant_dir"]
        c = r["cnt"]
        fr = r["avg_fr"] or 0
        month_dir_count.setdefault(m, {"同向": 0, "逆向": 0})
        if d in ("同向", "逆向"):
            month_dir_count[m][d] = c
        month_fr_sum[m] = month_fr_sum.get(m, 0) + fr * c
        month_total[m] = month_total.get(m, 0) + c

    # 按月判定风格：同向 / 逆向 / 震荡
    month_seq = []  # list of (month, judge)
    for m in sorted(month_dir_count.keys()):
        same = month_dir_count[m]["同向"]
        contra = month_dir_count[m]["逆向"]
        total = month_total[m]
        avg_fr = month_fr_sum[m] / total if total else 0
        diff = abs(same - contra)
        # 震荡月：同向/逆向天数差<=2，或月均 follow_ratio 落在 45-55% 区间
        if diff <= 2 or 45 <= avg_fr <= 55:
            judge = "震荡"
        elif same > contra:
            judge = "同向"
        else:
            judge = "逆向"
        month_seq.append((m, judge))

    # 规律 A：按月切换同向/逆向（连续同向/逆向段长度统计，震荡月打断连续段）
    segments = []  # (direction, length, start_month, end_month)
    cur_dir_seg = None
    cur_len_seg = 0
    cur_start_seg = None
    prev_m_seg = None
    for m, judge in month_seq:
        if judge == "震荡":
            # 震荡月风格不明确，结束当前连续方向段
            if cur_dir_seg is not None:
                segments.append((cur_dir_seg, cur_len_seg, cur_start_seg, prev_m_seg))
                cur_dir_seg = None
                cur_len_seg = 0
                cur_start_seg = None
            continue
        if judge == cur_dir_seg:
            cur_len_seg += 1
        else:
            if cur_dir_seg is not None:
                segments.append((cur_dir_seg, cur_len_seg, cur_start_seg, prev_m_seg))
            cur_dir_seg = judge
            cur_len_seg = 1
            cur_start_seg = m
        prev_m_seg = m
    if cur_dir_seg is not None:
        segments.append((cur_dir_seg, cur_len_seg, cur_start_seg, prev_m_seg))

    seg_lengths = [s[1] for s in segments]
    seg_count = len(seg_lengths)
    max_seg = max(seg_lengths) if seg_lengths else 0
    avg_seg = round(sum(seg_lengths) / seg_count, 1) if seg_count else 0
    seg_le2 = sum(1 for l in seg_lengths if l <= 2)
    seg_le2_pct = round(seg_le2 / seg_count * 100) if seg_count else 0

    cur_seg = segments[-1] if segments else None
    cur_seg_dir = cur_seg[0] if cur_seg else "-"
    cur_seg_len = cur_seg[1] if cur_seg else 0

    # 规律 A triggered：当前连续段已达历史上限，下月预期切换风格
    p5_triggered = cur_seg_len >= 2
    if cur_seg:
        if cur_seg_len >= max_seg and max_seg > 0:
            p5_status = (f"当前连续{cur_seg_len}月{cur_seg_dir}"
                         f"（达历史最长{max_seg}月），下月预期切换风格")
        else:
            p5_status = (f"当前{cur_seg_dir}持续{cur_seg_len}月"
                         f"（历史平均{avg_seg}月切换一次）")
    else:
        p5_status = "数据不足"
    p5_stats = (f"近{seg_count}个连续段，平均{avg_seg}月切换一次，"
                f"最长{max_seg}月，{seg_le2_pct}%段长≤2月")

    # 规律 B：切换不顺畅三段式（同向-震荡-逆向 / 逆向-震荡-同向）
    # 严格三段式：中间恰好 1 个震荡月，两端方向相反
    triples_strict = 0
    for i in range(1, len(month_seq) - 1):
        prev_j = month_seq[i - 1][1]
        cur_j = month_seq[i][1]
        next_j = month_seq[i + 1][1]
        if (cur_j == "震荡" and prev_j in ("同向", "逆向")
                and next_j in ("同向", "逆向") and prev_j != next_j):
            triples_strict += 1

    # 宽泛震荡过渡切换：方向切换事件中，两段之间隔>=1 个震荡月的次数
    switch_events = 0
    osc_transition = 0
    last_non_osc = None  # (month, judge, seq_index)
    for idx, (m, judge) in enumerate(month_seq):
        if judge in ("同向", "逆向"):
            if last_non_osc is not None and judge != last_non_osc[1]:
                switch_events += 1
                between = month_seq[last_non_osc[2] + 1:idx]
                if any(j == "震荡" for _, j in between):
                    osc_transition += 1
            last_non_osc = (m, judge, idx)

    osc_pct = round(osc_transition / switch_events * 100) if switch_events else 0

    # 规律 B triggered：当前正处于震荡过渡月（上月方向月，本月震荡）
    p6_triggered = False
    if len(month_seq) >= 2:
        last_j = month_seq[-1][1]
        prev_j = month_seq[-2][1]
        if last_j == "震荡" and prev_j in ("同向", "逆向"):
            p6_triggered = True
            flip = "逆向" if prev_j == "同向" else "同向"
            p6_status = (f"当前处于震荡过渡月（上月{prev_j}->本月震荡），"
                         f"按规律下月可能切换为{flip}")
        else:
            p6_status = f"当前{last_j}（非震荡过渡期）"
    else:
        p6_status = "数据不足"
    p6_stats = (f"历史{switch_events}次方向切换中{osc_transition}次经震荡过渡"
                f"（{osc_pct}%），其中{triples_strict}次为严格"
                f"'1月同向-1月震荡-1月逆向'三段式")

    conclusions = [
        {
            "level": "最强",
            "signal": "抄底",
            "trigger": "中信同向准确度 <=30%",
            "current_status": p1_status,
            "triggered": p1_triggered,
            "stats": "历史34次中33次(97%)后20日正收益，平均 +3.68%",
            "action": "关注抄底机会",
        },
        {
            "level": "次强",
            "signal": "顶部预警",
            "trigger": "中信同向准确度 >=80%",
            "current_status": p2_status,
            "triggered": p2_triggered,
            "stats": "历史22次中15次(68%)后20日负收益，平均 -2.37%",
            "action": "警惕回调",
        },
        {
            "level": "中等",
            "signal": "转跟随看多",
            "trigger": "中信转同向",
            "current_status": p3_status,
            "triggered": p3_triggered,
            "stats": "14次切换后60日平均 +3.27%",
            "action": "看多",
        },
        {
            "level": "辅助",
            "signal": "季节性",
            "trigger": "4月/10月逆向，2月/7-8月同向",
            "current_status": p4_status,
            "triggered": p4_triggered,
            "stats": "历史月级规律",
            "action": p4_action,
        },
        {
            "level": "中等",
            "signal": "按月切换风格",
            "trigger": "中信同向/逆向按月切换，连续段平均1-2月",
            "current_status": p5_status,
            "triggered": p5_triggered,
            "stats": p5_stats,
            "action": "连续段达上限后关注风格切换",
        },
        {
            "level": "辅助",
            "signal": "切换不顺畅三段式",
            "trigger": "切换不顺畅时出现 同向-震荡-逆向 三段式",
            "current_status": p6_status,
            "triggered": p6_triggered,
            "stats": p6_stats,
            "action": "震荡月后关注方向切换",
        },
    ]

    return {
        "as_of_date": as_of_date,
        "current_state": current_state,
        "conclusions": conclusions,
        "streak_history": streak_history,
    }


def export_ad_line(conn):
    """复刻 /api/ad_line。"""
    return queries.ad_line(conn)


def export_volume_ratio(conn):
    """复刻 /api/volume_ratio。"""
    return queries.volume_ratio(conn)


def export_new_high_low(conn):
    """复刻 /api/new_high_low。"""
    return queries.new_high_low(conn)


def export_ma_alignment(conn):
    """复刻 /api/ma_alignment。"""
    return queries.ma_alignment(conn)


def export_rotation(conn):
    """复刻 /api/rotation（latest 统一用 compute_rotation 含门控）。"""
    return queries.rotation(conn)


def export_position():
    """复刻 /api/position。"""
    return queries.position()


def export_summary():
    """复刻 /api/summary。"""
    return queries.summary()


def export_summary_history():
    """历史一句话总结（增量追加，不丢历史）。

    读已有 summary_history.json 保留历史，重算最近 7 天确保最新（含新天），
    7 天前的历史保留不丢。每天增量 +1 累计增长（366/367...），不回填全量历史。
    首次跑基于已有 365 天 JSON（B 方案起点），后续只增不减。

    - 重算最近 7 天：确保最新数据覆盖（含新天）；~7s 可接受（7 天 × ~12 SQL）
    - 历史 7 天前：保留已有 JSON 不重算（不丢历史，不更新）
    - 漏跑补算：update_all 漏跑几天，下次重算最近 7 天补回（7 天窗口内）
    - total = 实际条数（累计增长，非 DB 全量 2562，避免前端算 85 页而 cache 不足致第 4 页起空）
    """
    conn = get_conn()
    # 1. 读已有 JSON（保留历史，不丢）
    existing_path = DATA_DIR / "summary_history.json"
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    else:
        existing = {"items": []}
    existing_items = existing.get("items", [])

    # 2. DB 所有 a_sentiment 交易日倒序（与 queries.summary_history 同源）
    all_dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM score_daily WHERE score_id='a_sentiment' "
        "ORDER BY date DESC"
    ).fetchall()]

    # 3. 重算最近 7 天（确保最新数据覆盖，含新天；~7s 可接受）
    RECALC_RECENT = 7
    recent_dates = all_dates[:RECALC_RECENT]
    recent_items = [queries.summary_brief(queries.generate_summary(d))
                    for d in recent_dates]
    recent_date_set = set(recent_dates)

    # 4. 历史 = 已有 JSON 中 7 天前的（保留不丢，不重算）
    history_items = [it for it in existing_items if it.get("date") not in recent_date_set]

    # 5. 合并：重算最近 7 天 + 历史（均倒序，recent 在前）
    items = recent_items + history_items

    # 6. total = 实际条数（累计增长）
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items)}


def export_signal_freq():
    """复刻 /api/signal_freq：全局信号频率统计。"""
    return queries.signal_freq(_get_stats())


def export_intraday_snapshot():
    """复刻 /api/intraday_snapshot：从 DB 读最新盘中实时快照。"""
    return queries.intraday_snapshot()


def export_etf_national_team(rng="all"):
    """汪汪队宽基 ETF 资金动向（12 只宽基 ETF 份额+成交额+信号）。"""
    return queries.etf_national_team(rng)


def export_etf_national_team_quarterly():
    """季度持有人结构（机构占比历史轨迹）。"""
    return queries.etf_national_team_quarterly()


def export_etf_national_team_holders():
    """v2 具名持有人（cninfo PDF 解析的前十大持有人，含汇金/证金识别）。"""
    return queries.etf_national_team_holders()


# ── 公募基金 7 类端点（薄包装 queries 调用）─────────────────────────────────
def export_public_fund_summary():
    """公募基金总览: 8 指标 + 仓位轨迹 + 净申赎时序。"""
    return queries.public_fund_summary()


def export_public_fund_holdings():
    """Top50 重仓股。"""
    return queries.public_fund_holdings()


def export_public_fund_industry():
    """行业聚合。"""
    return queries.public_fund_industry()


def export_public_fund_sw_industry_alloc():
    """申万一级行业配置(反查口径): 基金 top10 重仓股按申万一级聚合, 揭示真实风格暴露。
    独立计算(不走 export_data 7 元组), 复用 fund_portfolio_hold + sw_components.json 反查。
    供前端"行业配置"卡第四档 'sw' 切换(vs 证监会口径 industry 19 大类)。"""
    return queries.public_fund_sw_industry_alloc()


def export_public_fund_top20():
    """Top20 调仓。"""
    return queries.public_fund_top20()


def export_public_fund_asset_alloc():
    """头部基金资产配置分布。"""
    return queries.public_fund_asset_alloc()


def export_public_fund_industry_fund_map():
    """逐只基金-行业映射, 按合并后行业名分组(前端"点击展开行业基金列表")。"""
    return queries.public_fund_industry_fund_map()


def export_public_fund_manuf_subind_fund_map():
    """制造业子行业 -> 基金详情列表(前端"子行业下钻到基金"弹窗, 方案C Step5)。"""
    return queries.public_fund_manuf_subind_fund_map()


def export_public_fund_position_backtest():
    """G功能: 88 魔咒历史回测 + 极值标注(独立计算, 不走 export_data 7 元组)。"""
    return queries.public_fund_position_backtest()


def export_public_fund_scale_change_ts():
    """N功能: 全市场规模变动历史时序(113期季报, 净申赎+规模两信号)。
    独立计算(不走 export_data 7 元组), 复用 fund_scale_change 全量时序。
    summary.scale_change_history 只取 LIMIT 20 期不够 N 功能全量分析, 故独立导出。"""
    return queries.public_fund_scale_change_ts()


def export_public_fund_industry_rotation_ts():
    """F功能: 全市场行业配置轮动历史时序(50期季报, 27行业合并后平均权重)。
    独立计算(不走 export_data 7 元组), 复用 fund_industry_alloc 全量时序。
    行业名应用 IND_MERGE_MAP 合并(67原始名->27标准名, 和 industry_fund_map 一致)。"""
    return queries.public_fund_industry_rotation_ts()


def export_public_fund_position_estimate():
    """方案A: 今日预估仓位 + 历史预估时序(净值回归反推 + lg 校准)。
    独立计算(不走 export_data 7 元组), 复用 fund_daily_nav 历史净值 + fund_index_daily 沪深300。
    供前端 88 魔咒图加"今日预估仓位"点, 不用等 lg 周频更新。"""
    return queries.public_fund_position_estimate()


# ============ JSON 序列化 + 写盘 ============

def _json_default(o):
    """处理 sqlite3 可能返回的非标准 JSON 类型。"""
    if isinstance(o, (sqlite3.Row,)):
        return dict(o)
    raise TypeError(f"not serializable: {type(o)}")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 紧凑输出（separators 无空白）--industry-all.json 全历史约 26MB，
    # 默认 ', '/': ' 分隔会让其超 Cloudflare Pages 25MB 单文件限制。
    text = json.dumps(data, ensure_ascii=False, default=_json_default,
                      separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text)


# ============ boot.json：首屏 11 JSON 合并（P1-8 性能优化）============
# 首屏原 22 个 fetch（renderOverview + init 阶段），合并后 1 个 fetch boot.json 分发到各模块。
# 首屏请求数减 95%，首屏体感最大。boot.json ~524KB 未压缩 / ~130-175KB br，走 CF Workers Static Assets
# （§8.1：小文件 <5MB 总量走 CF 非 R2；upload-data-large 兜底 >=1MB 不会上传 boot.json）。
# 合并的 11 个 JSON（均首屏必需，<300KB 单文件）：
#   overview/signal_stats/intraday_snapshot/summary/alert/ma_alignment/position/
#   ad_line/volume_ratio/new_high_low/trade_sim_indices
# alert.json 由 scripts/export_alert.py 生成（非 export.py），trade_sim_indices.json 由
# scripts/simulate_trade.py 生成（非 export.py）；二者容错读取，失败则 null（前端 fallback fetch）。
# 时序：17:50 update_all 跑完 pipeline+export_alert 后，alert.json/intraday_snapshot.json 均是当日最新；
#       23:00+ 跑 export.py 时 boot.json 读到的 11 个 JSON 均是当日最新。
def export_boot():
    """合并首屏 11 个小 JSON 到 boot.json，供前端首屏单 fetch 分发。"""
    # (字段名, 文件名) — 字段名用 JSON 文件名去 .json 后缀
    boot_files = [
        ("overview", "overview.json"),
        ("signal_stats", "signal_stats.json"),
        ("intraday_snapshot", "intraday_snapshot.json"),
        ("summary", "summary.json"),
        ("alert", "alert.json"),
        ("ma_alignment", "ma_alignment.json"),
        ("position", "position.json"),
        ("ad_line", "ad_line.json"),
        ("volume_ratio", "volume_ratio.json"),
        ("new_high_low", "new_high_low.json"),
        ("trade_sim_indices", "trade_sim_indices.json"),
    ]
    boot = {}
    missing = []
    for key, fname in boot_files:
        fpath = DATA_DIR / fname
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                boot[key] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # 容错：alert.json/trade_sim_indices.json 可能尚未生成（其他脚本负责）
            # 前端检测 null 则 fallback fetch 对应 JSON
            boot[key] = None
            missing.append(f"{fname}({type(e).__name__})")
    # boot.json 元信息（生成时间 + 合并的文件清单，供前端调试/版本核对）
    boot["_meta"] = {
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [f for _, f in boot_files],
        "missing": missing,
    }
    boot_size = write_json(DATA_DIR / "boot.json", boot)
    print(f"  boot.json ({boot_size} bytes, 合并 {len(boot_files)} 个首屏 JSON"
          f"{f', 缺失: {missing}' if missing else ''})")
    return boot_size


def write_industry_split(conn, cfg, rng="all") -> tuple[dict, int, int]:
    """导出 industry-{rng} 拆分文件并返回 (counts, n_indices, n_concepts)。

    生成（rng 替换下方 {rng}）：
    - industry-{rng}-indices/{iid}.json × 31 行业
    - industry-{rng}-concepts.json（概念 + 当日实时行）
    - industry-{rng}-meta.json（热力图 + index_ids + concept_ids）
    - 仅 all range 额外产 {iid}-detail.json × 31（tooltip 专属字段，按需加载）

    all range 主文件瘦身（全历史 29MB 超 Cloudflare Pages 25MB 限制，瘦身省 ~68%），
    tooltip 专属字段拆到 {iid}-detail.json 按需加载。非 all range（5y 等）主文件保留
    全字段：单文件 <25MB 无需瘦身，且前端 _preloadIndDetail 检测 width[0] 含 zt_count
    即走内存分支（app.js _indHasDetail），免 detail 二次请求，故不产 detail.json。

    供 main() 收盘全量导出 与 intraday_snapshot._export_affected_json 盘中导出共用。
    盘中调用时 index_daily 已含当日行业/概念实时行（_backfill_industry_daily /
    _backfill_concept_daily），故导出 JSON 含当日 -> 前端读 JSON 即可盘中可见当日。
    """
    ind_all = export_industry(conn, cfg, rng)
    ind_split_dir = DATA_DIR / f"industry-{rng}-indices"
    ind_split_dir.mkdir(parents=True, exist_ok=True)
    counts: dict = {}
    slim = rng == "all"  # 仅 all 瘦身（全历史 29MB 超 25MB 限制）
    if slim:
        # B2 折中瘦身：主文件只保留渲染必需字段，tooltip 专属字段拆到 {iid}-detail.json
        _KEEP_DATA = ("date", "close", "pct_change", "amount")
        _KEEP_WIDTH = ("date", "up_count", "down_count")
        _DET_OHLC = ("open", "high", "low")
        _DET_WIDTH = ("zt_count", "dt_count", "zb_count", "seal_rate", "amount")
    for iid, ind in ind_all["indices"].items():
        if slim:
            slim_obj = {k: v for k, v in ind.items() if k not in ("data", "width")}
            slim_obj["data"] = [{k: x.get(k) for k in _KEEP_DATA} for x in ind["data"]]
            slim_obj["width"] = [{k: x.get(k) for k in _KEEP_WIDTH} for x in ind["width"]]
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", slim_obj)
            detail = {
                "ohlc": [{k: x.get(k) for k in _DET_OHLC} for x in ind["data"]],
                "width": [{k: x.get(k) for k in _DET_WIDTH} for x in ind["width"]],
            }
            counts[f"industry-{rng}-indices/{iid}-detail.json"] = write_json(
                ind_split_dir / f"{iid}-detail.json", detail)
        else:
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", ind)
    counts[f"industry-{rng}-concepts.json"] = write_json(
        DATA_DIR / f"industry-{rng}-concepts.json", {"concepts": ind_all["concepts"]})
    counts[f"industry-{rng}-meta.json"] = write_json(
        DATA_DIR / f"industry-{rng}-meta.json",
        {"heatmap": ind_all["heatmap"], "index_ids": list(ind_all["indices"].keys()),
         "concept_ids": list(ind_all["concepts"].keys())})
    n_indices = len(ind_all["indices"])
    n_concepts = len(ind_all["concepts"])
    print(f"  industry-{rng} 拆分: {n_indices} 行业 + {n_concepts} 概念 + meta")
    return counts, n_indices, n_concepts


def write_industry_all_split(conn, cfg) -> tuple[dict, int, int]:
    """兼容别名 -> write_industry_split(conn, cfg, "all")。"""
    return write_industry_split(conn, cfg, "all")


def main():
    cfg = load_config()
    conn = get_conn()
    counts = {}

    # 1. overview
    counts["overview.json"] = write_json(DATA_DIR / "overview.json", export_overview(conn, cfg))
    print(f"  overview.json ({counts['overview.json']} bytes)")

    # 2-6. tab 端点 × 5 ranges
    tab_exporters = {
        "a-stock": export_a_stock,
        "hk": export_hk,
        "global": export_global,
        "sentiment": export_sentiment,
        "industry": export_industry,
    }
    for name, fn in tab_exporters.items():
        for rng in EXPORT_RANGES:
            if name == "industry" and rng in ("all", "5y", "3y"):
                continue  # industry-all/5y/3y 拆分为多文件（见下方），避免大单文件拖慢首屏
            fname = f"{name}-{rng}.json"
            data = fn(conn, cfg, rng)
            counts[fname] = write_json(DATA_DIR / fname, data)
            print(f"  {fname} ({counts[fname]} bytes)")
            # 信号弹窗只需 extras 四件套（不含 indices），单独导出轻量版省 ~68% 体积
            if name == "global" and rng == "all":
                counts["global-extras-all.json"] = write_json(
                    DATA_DIR / "global-extras-all.json",
                    {k: data[k] for k in ("extras", "extras_signals", "extras_stats", "extras_strategy")})
                print(f"  global-extras-all.json ({counts['global-extras-all.json']} bytes)")

    # industry-all/5y/3y 拆分：31 行业各一个文件 + concepts + meta。
    # all 全历史 29MB 超 Cloudflare Pages 25MB 单文件限制须拆；5y 14MB / 3y 9.2MB 虽未超限，
    # 但拆成 31 个小文件按需 fetch 提速首屏（前端 all/5y/3y 并发组装，见 app.js _loadIndustryData）。
    for rng in ("all", "5y", "3y"):
        ind_counts, _n_ind, _n_concept = write_industry_split(conn, cfg, rng)
        counts.update(ind_counts)

    # 7. metrics（已废弃：前端无 fetch 引用，2026-07-15 删除上线产物，不再生成）
    # counts["metrics.json"] = write_json(DATA_DIR / "metrics.json", export_metrics(cfg))
    # print(f"  metrics.json ({counts['metrics.json']} bytes)")

    # 7.5. futures
    counts["futures.json"] = write_json(DATA_DIR / "futures.json", export_futures(conn))
    print(f"  futures.json ({counts['futures.json']} bytes)")

    # 7.5.1 futures_acc_trend（期货同向准确度每日趋势，follow_ratio 可跌破50%反映同向失效）
    counts["futures_acc_trend.json"] = write_json(
        DATA_DIR / "futures_acc_trend.json", export_futures_acc_trend(conn))
    print(f"  futures_acc_trend.json ({counts['futures_acc_trend.json']} bytes)")

    # 7.5.2 futures_acc_conclusion（期货同向准确度规律结论，4条规律+当前触发状态，每日刷新）
    counts["futures_acc_conclusion.json"] = write_json(
        DATA_DIR / "futures_acc_conclusion.json", export_futures_acc_conclusion(conn))
    print(f"  futures_acc_conclusion.json ({counts['futures_acc_conclusion.json']} bytes)")

    # 7.6. ad_line
    counts["ad_line.json"] = write_json(DATA_DIR / "ad_line.json", export_ad_line(conn))
    print(f"  ad_line.json ({counts['ad_line.json']} bytes)")

    # 7.7. volume_ratio
    counts["volume_ratio.json"] = write_json(DATA_DIR / "volume_ratio.json", export_volume_ratio(conn))
    print(f"  volume_ratio.json ({counts['volume_ratio.json']} bytes)")

    # 7.8. position
    counts["position.json"] = write_json(DATA_DIR / "position.json", export_position())
    print(f"  position.json ({counts['position.json']} bytes)")

    # 7.9. summary
    counts["summary.json"] = write_json(DATA_DIR / "summary.json", export_summary())
    print(f"  summary.json ({counts['summary.json']} bytes)")
    counts["summary_history.json"] = write_json(
        DATA_DIR / "summary_history.json", export_summary_history())
    print(f"  summary_history.json ({counts['summary_history.json']} bytes)")
    counts["signal_freq.json"] = write_json(DATA_DIR / "signal_freq.json", export_signal_freq())
    print(f"  signal_freq.json ({counts['signal_freq.json']} bytes)")
    # 7.9.1 signal_stats（per-index 回测统计，6类信号含 sell_stop_loss；供前端❓弹窗分析概况聚合）
    # 用 _stats_all() 现算内存结果（不读根 data/signal_stats.json 旧文件，避免缺品种/过期）
    counts["signal_stats.json"] = write_json(DATA_DIR / "signal_stats.json", _get_stats())
    print(f"  signal_stats.json ({counts['signal_stats.json']} bytes)")

    # 7.9.2 signal_kelly_backtest（信号凯利回测: 6象限×4模式×5周期, 读 signal_stats+board_etf_map+etf_daily）
    # 独立脚本 scripts/signal_kelly_backtest.py, subprocess 调用(隔离 import 副作用)。
    # 失败不阻塞 export(前端 fallback null); signal_stats.json 刚写入, 脚本优先读 static-site/data/ 版。
    # 生成两个文件: signal_kelly_backtest.json(统计,~40KB,CF Workers) + signal_kelly_trades.json(交易记录,~6MB,R2)
    try:
        _sk = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "signal_kelly_backtest.py"),
             "--output", str(DATA_DIR / "signal_kelly_backtest.json")],
            capture_output=True, text=True, timeout=180, cwd=str(ROOT))
        _sk_path = DATA_DIR / "signal_kelly_backtest.json"
        _sk_trades_path = DATA_DIR / "signal_kelly_trades.json"
        if _sk.returncode == 0 and _sk_path.exists():
            counts["signal_kelly_backtest.json"] = _sk_path.stat().st_size
            print(f"  signal_kelly_backtest.json ({counts['signal_kelly_backtest.json']} bytes)")
            if _sk_trades_path.exists():
                counts["signal_kelly_trades.json"] = _sk_trades_path.stat().st_size
                print(f"  signal_kelly_trades.json ({counts['signal_kelly_trades.json']} bytes, R2)")
        else:
            print(f"  signal_kelly_backtest.json: 失败 rc={_sk.returncode} stderr={_sk.stderr[:200]}")
    except Exception as _e:  # noqa: BLE001
        print(f"  signal_kelly_backtest.json: 异常 {_e}")

    # 7.10. rotation
    counts["rotation.json"] = write_json(DATA_DIR / "rotation.json", export_rotation(conn))
    print(f"  rotation.json ({counts['rotation.json']} bytes)")

    # 7.11. new_high_low
    counts["new_high_low.json"] = write_json(DATA_DIR / "new_high_low.json", export_new_high_low(conn))
    print(f"  new_high_low.json ({counts['new_high_low.json']} bytes)")

    # 7.12. ma_alignment
    counts["ma_alignment.json"] = write_json(DATA_DIR / "ma_alignment.json", export_ma_alignment(conn))
    print(f"  ma_alignment.json ({counts['ma_alignment.json']} bytes)")

    # 7.13. intraday_snapshot（盘中实时快照，从 DB 读最新行）
    counts["intraday_snapshot.json"] = write_json(
        DATA_DIR / "intraday_snapshot.json", export_intraday_snapshot())
    print(f"  intraday_snapshot.json ({counts['intraday_snapshot.json']} bytes)")

    # 7.14. etf_national_team × range（默认1y≈0.67MB，all≈7.6MB；手机默认只下1y，避免7.6MB裸传卡顿）
    # 仿 sentiment 拆分：预生成 3m/6m/1y/3y/5y/all 六个文件，前端按 state.range 按需 fetch。
    from app.collector.etf_national_team import export_data as _nt_export_data
    _nt_daily, _nt_quarterly, _nt_holders = _nt_export_data()
    for rng in EXPORT_RANGES:
        fname = f"etf_national_team-{rng}.json"
        counts[fname] = write_json(DATA_DIR / fname, export_etf_national_team(rng))
        print(f"  {fname} ({counts[fname]} bytes)")
    counts["etf_national_team_quarterly.json"] = write_json(
        DATA_DIR / "etf_national_team_quarterly.json", _nt_quarterly)
    print(f"  etf_national_team_quarterly.json ({counts['etf_national_team_quarterly.json']} bytes)")
    counts["etf_national_team_holders.json"] = write_json(
        DATA_DIR / "etf_national_team_holders.json", _nt_holders)
    print(f"  etf_national_team_holders.json ({counts['etf_national_team_holders.json']} bytes)")

    # 7.15. public_fund 7 类（公募基金 88 魔咒/抱团度/净申赎 + 行业下钻到基金）
    # collector 独立库 data/public_fund.db, 这里通过 queries 薄包装读最新小样本产物
    # 2026-07-20 补 industry_fund_map + manuf_subind_fund_map (原仅 5 JSON, 漏第 6/7 值)
    counts["public_fund_summary.json"] = write_json(
        DATA_DIR / "public_fund_summary.json", export_public_fund_summary())
    print(f"  public_fund_summary.json ({counts['public_fund_summary.json']} bytes)")
    counts["public_fund_holdings.json"] = write_json(
        DATA_DIR / "public_fund_holdings.json", export_public_fund_holdings())
    print(f"  public_fund_holdings.json ({counts['public_fund_holdings.json']} bytes)")
    counts["public_fund_industry.json"] = write_json(
        DATA_DIR / "public_fund_industry.json", export_public_fund_industry())
    print(f"  public_fund_industry.json ({counts['public_fund_industry.json']} bytes)")
    counts["public_fund_top20.json"] = write_json(
        DATA_DIR / "public_fund_top20.json", export_public_fund_top20())
    print(f"  public_fund_top20.json ({counts['public_fund_top20.json']} bytes)")
    counts["public_fund_asset_alloc.json"] = write_json(
        DATA_DIR / "public_fund_asset_alloc.json", export_public_fund_asset_alloc())
    print(f"  public_fund_asset_alloc.json ({counts['public_fund_asset_alloc.json']} bytes)")
    counts["public_fund_industry_fund_map.json"] = write_json(
        DATA_DIR / "public_fund_industry_fund_map.json", export_public_fund_industry_fund_map())
    print(f"  public_fund_industry_fund_map.json ({counts['public_fund_industry_fund_map.json']} bytes)")
    counts["public_fund_manuf_subind_fund_map.json"] = write_json(
        DATA_DIR / "public_fund_manuf_subind_fund_map.json", export_public_fund_manuf_subind_fund_map())
    print(f"  public_fund_manuf_subind_fund_map.json ({counts['public_fund_manuf_subind_fund_map.json']} bytes)")
    # G功能: 88 魔咒历史回测 + 极值标注(独立计算, 非 export_data 7 元组)
    counts["public_fund_position_backtest.json"] = write_json(
        DATA_DIR / "public_fund_position_backtest.json", export_public_fund_position_backtest())
    print(f"  public_fund_position_backtest.json ({counts['public_fund_position_backtest.json']} bytes)")
    # N功能: 全市场规模变动时序(净申赎+规模, 113期季报; summary.scale_change_history 只20期不够)
    counts["public_fund_scale_change_ts.json"] = write_json(
        DATA_DIR / "public_fund_scale_change_ts.json", export_public_fund_scale_change_ts())
    print(f"  public_fund_scale_change_ts.json ({counts['public_fund_scale_change_ts.json']} bytes)")
    # F功能: 行业配置轮动时序(50期季报, 27行业合并后平均权重, 堆叠面积图)
    counts["public_fund_industry_rotation_ts.json"] = write_json(
        DATA_DIR / "public_fund_industry_rotation_ts.json", export_public_fund_industry_rotation_ts())
    print(f"  public_fund_industry_rotation_ts.json ({counts['public_fund_industry_rotation_ts.json']} bytes)")
    # 方案A: 今日预估仓位 + 历史预估时序(净值回归反推 + lg 校准, 88魔咒图"今日预估仓位"点)
    counts["public_fund_position_estimate.json"] = write_json(
        DATA_DIR / "public_fund_position_estimate.json", export_public_fund_position_estimate())
    print(f"  public_fund_position_estimate.json ({counts['public_fund_position_estimate.json']} bytes)")
    # 申万一级行业配置(反查口径): 基金 top10 重仓股按申万一级聚合(独立计算, 非 export_data 7 元组)
    # 前端"行业配置"卡第四档 'sw' 切换, vs 证监会口径 industry 19 大类
    counts["public_fund_sw_industry_alloc.json"] = write_json(
        DATA_DIR / "public_fund_sw_industry_alloc.json", export_public_fund_sw_industry_alloc())
    print(f"  public_fund_sw_industry_alloc.json ({counts['public_fund_sw_industry_alloc.json']} bytes)")

    # 8. index/{id}-all.json（44 个指数）
    all_indices = [i["id"] for i in cfg.get("indices", []) if i.get("enabled", True)]
    for iid in all_indices:
        fname = f"{iid}-all.json"
        data = export_index_detail(conn, cfg, iid)
        counts[f"index/{fname}"] = write_json(INDEX_DIR / fname, data)
    print(f"  index/*.json ({len(all_indices)} files)")

    conn.close()

    total_files = len(counts) + len(all_indices)
    total_bytes = sum(counts.values())
    print(f"\n导出完成：{len(counts)} 个 JSON 文件，{total_bytes / 1024 / 1024:.1f} MB")
    print(f"  - overview: 1")
    print(f"  - tab ranges: 5 tabs × {len(EXPORT_RANGES)} ranges")
    print(f"  - metrics: 1")
    print(f"  - index detail: {len(all_indices)} (all range, full history)")
    print(f"输出目录: {DATA_DIR}")

    # P1-8: 合并首屏 11 个小 JSON 到 boot.json
    # 前端首屏单 fetch boot.json 分发，请求数 22 -> 1。详见 export_boot() 注释。
    export_boot()

    # 生成文件后自动走 R2 优化（用户规则：不等超 300MB 才发起）
    # EXPORT_SKIP_R2=1 时跳过（deploy.sh/intraday_snapshot.sh 自己跑 R2，避免重复）
    if os.environ.get("EXPORT_SKIP_R2") != "1":
        print("\n-> 自动上传 R2 (EXPORT_SKIP_R2=1 可跳过)...", flush=True)
        for _cmd in ["upload-lab", "upload-trade-sim-json", "upload-index", "upload-industry", "upload-public-fund", "upload-etf-score", "upload-data-large"]:
            try:
                _r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/upload_r2.py"), _cmd],
                    env={**os.environ, "REPO": str(ROOT)},
                    capture_output=True, text=True, timeout=300)
                print(f"  {_cmd}: rc={_r.returncode}", flush=True)
                if _r.stderr and _r.returncode != 0:
                    print(f"    stderr: {_r.stderr[:200]}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"  {_cmd}: 超时(300s)跳过", flush=True)
            except Exception as _e:  # noqa: BLE001
                print(f"  {_cmd}: 异常 {_e}", flush=True)
        print("-> R2 上传完成(失败不阻塞)", flush=True)


if __name__ == "__main__":
    main()
