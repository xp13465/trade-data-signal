#!/usr/bin/env python3
"""audit_shadow_vs_default.py - AI 预测影子模式 vs 默认模式命中率只读审计(2026-08-24)。

目的: 回答两问 ①影子模式(方向锚规则 lean)近期命中率 ②默认模式(ai-multi AI 预测)是否真差。
方法口径:
  - 判定数据 = sentiment.db index_daily 的 sh pct_change,取预测日 T 之后第一个交易日收盘涨跌幅(T 日 20:40 出预测,T+1 收盘判定,无前视)。
  - 方向阈值 HIT_THRESHOLD=0.5(与 gen_daily_brief._actual_direction / aggregate_shadow 同口径): |pct|>=0.5 为 up/down,否则 flat。
  - 默认模式严格口径 = 三层全命中(range+middle+sector),与 gen_daily_brief._history_stats 一致;本脚本另算宽松「方向口径」作对照。
输入依赖:
  - /Users/linhuichen/code/trade/static-site/data/daily_brief_history.json (默认模式逐日预测+hit 明细)
  - /Users/linhuichen/code/trade/data/brief_shadow.json (影子逐日记录)
  - /Users/linhuichen/code/trade/data/sentiment.db (index_daily 实际涨跌)
输出: 终端打印两张对照表 + 命中率汇总(只读,不写任何文件)。
复现: python3 docs/ai-predict/shadow-hitrate-audit-scripts/audit_shadow_vs_default.py
数据截止: 2026-08-24(0824 收盘 -0.59 已入 DB;0824 当日预测尚未生成,不在样本内)。
关键口径一句话: 命中=预测 T 日方向/区间 vs T+1 收盘 sh 涨跌幅按 ±0.5% 阈值判定的方向相等。
"""
import json
import sqlite3
from pathlib import Path

REPO = Path("/Users/linhuichen/code/trade")
HIST = REPO / "static-site/data/daily_brief_history.json"
SHADOW = REPO / "data/brief_shadow.json"
DB = REPO / "data/sentiment.db"
TH = 0.5


def direction(pct):
    if pct is None:
        return None
    return "up" if pct > TH else ("down" if pct < -TH else "flat")


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dates_pcts = conn.execute(
        "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date").fetchall()
    conn.close()
    # date -> (下一交易日, pct)
    nxt = {}
    for i, (d, p) in enumerate(dates_pcts):
        nxt[d] = (dates_pcts[i + 1][0], dates_pcts[i + 1][1]) if i + 1 < len(dates_pcts) else (None, None)

    hist = json.load(open(HIST))["items"]
    print("== 默认模式(ai-multi) 逐日 ==")
    print(f"{'预测日':<9}{'方向':<6}{'大盘range':<16}{'T+1':<9}{'实际pct':>8}  {'实际dir':<6} 方向口径 range口径")
    dir_hit = dir_n = strict_hit = strict_n = 0
    for it in hist:
        m = it["meta"]
        d = m["date"]
        nd, np_ = nxt.get(d, (None, None))
        ad = direction(np_)
        pred_dir = m.get("direction")
        rng = m.get("range")
        dh = pred_dir == ad
        rh = None
        if rng and rng.get("lo") is not None and np_ is not None:
            rh = rng["lo"] <= np_ <= rng["hi"]
        dir_n += 1
        dir_hit += 1 if dh else 0
        has_range = bool(rng and rng.get("lo") is not None)
        if has_range:
            strict_n += 1
            strict_hit += 1 if (dh and rh) else 0
        rs = f"{rng['lo']}~{rng['hi']}" if has_range else "无"
        print(f"{d:<9}{pred_dir:<6}{rs:<16}{nd:<9}{np_:>8.2f}  {ad:<6} {'✓' if dh else '✗':^4} {str(rh):>6}")
    print(f"默认模式: 方向口径 {dir_hit}/{dir_n}={dir_hit/dir_n:.0%} | 大盘range+方向双口径 {strict_hit}/{strict_n}")
    print("(前端 stats 严格三层口径见 daily_brief_history.json stats 字段,本脚本不重复算板块/中间层)")

    print("\n== 影子模式(方向锚规则 lean) 逐日 ==")
    rows = json.load(open(SHADOW))
    s_hit = s_n = s_loose = 0
    for r in rows:
        d = r["date"]
        nd, np_ = nxt.get(d, (None, None))
        ad = direction(np_)
        hit = r["pred_shadow"] == ad
        loose = None if np_ is None else ((r["pred_shadow"] == "up" and np_ > 0) or (r["pred_shadow"] == "down" and np_ < 0))
        s_n += 1
        s_hit += 1 if hit else 0
        s_loose += 1 if loose else 0
        print(f"{d:<9}lean={r['pred_shadow']:<5}strength={r['strength']:<7}basis={len(r['basis'])}条 "
              f"T+1={nd} pct={np_} actual={ad} {'✓' if hit else '✗'} (宽松|pct|>0口径: {'✓' if loose else '✗'})")
    if s_n:
        print(f"影子模式: 官方±0.5%口径 {s_hit}/{s_n} | 宽松(涨即中up)口径 {s_loose}/{s_n}")


if __name__ == "__main__":
    main()
