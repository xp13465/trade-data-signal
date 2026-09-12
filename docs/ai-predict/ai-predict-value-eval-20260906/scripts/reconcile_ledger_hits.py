#!/usr/bin/env python3
"""reconcile_ledger_hits.py - 每日速递 AI 预测历史命中率独立对账(2026-09-08)

目的: 用数据回答「AI 预测准不准、砍还是留」——把 brief_ledger.json 14 条预测
      (direction_call + range) 与次日上证指数(及沪深300)真实涨跌逐条对账,
      计算方向命中率/区间命中率/子指数命中率, 并与「随机猜/恒押一方/规则影子」
      三基线对照, 评估 AI 预测是否超越无信息基线。

方法口径:
  - 日期语义: ledger.date = 预测生成日(T 日 20:40), 预测目标是 T+1 次日行情;
    次日 = date 之后第一个在 index_daily 有数据(全局交易日对齐)的 date。
  - 预测对象: 生产口径 range 对「上证指数」(index_daily index_id='sh',
    gen_daily_brief.py L1562 prompt 与 L3876 展示均写明上证指数);任务书称呼
    「沪深300」为主控简化表述, 脚本同时输出 hs300 对照。
  - 方向三分类: 与 gen_daily_brief._actual_direction 同口径 HIT_THRESHOLD=0.5
    (>0.5% → up; <-0.5% → down; 否则 flat)。
  - 方向命中(严格口径=生产): direction_call=up 且 actual=up, 或 down 且 actual=down;
    actual=flat 一律判未中(押方向本就该难, 生产同口径)。
  - 方向命中(宽松口径): call=up → 实际 pct>=0 中(flat 也算中); call=down → pct<=0 中。
  - 区间命中: 实际 pct ∈ [range.lo, range.hi] 闭区间。
  - 子指数区间: index_ranges 中深证成指(index_id=sz)/创业板指(index_id=cyb)
    次日 pct ∈ [lo,hi] 闭区间。
  - 影子规则: brief_shadow.json pred_shadow(规则方向锚合成) vs 次日上证方向,
    同 HIT_THRESHOLD 三分类, flat 押中 flat 才算中(严格)。

输入依赖:
  - data/brief_ledger.json(预测账底, 14 条)
  - data/brief_shadow.json(影子规则, 8 条)
  - data/sentiment.db index_daily 表(index_id in sh/hs300/sz/cyb, 上证/沪深300/
    深证成指/创业板指日线 pct_change), 数据截止 20260907。

输出: stdout 逐条对账表 + 汇总统计(txt 另存 ./out/reconcile_ledger_hits.txt)。

复现: python3 docs/ai-predict/ai-predict-value-eval-20260906/scripts/reconcile_ledger_hits.py
数据截止: 2026-09-07(下次重跑以 index_daily 最新交易日为准)。
"""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path("/Users/linhuichen/code/trade")
LEDGER = ROOT / "data" / "brief_ledger.json"
SHADOW = ROOT / "data" / "brief_shadow.json"
DB = ROOT / "data" / "sentiment.db"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)

HIT_THRESHOLD = 0.5


def actual_direction(pct):
    if pct is None:
        return None
    if pct > HIT_THRESHOLD:
        return "up"
    if pct < -HIT_THRESHOLD:
        return "down"
    return "flat"


def load_index_map():
    """index_id -> {date: pct_change}"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        cur = conn.execute(
            "SELECT index_id, date, pct_change FROM index_daily "
            "WHERE index_id IN ('sh','hs300','sz','cyb')"
        )
        m = {}
        for iid, date, pct in cur.fetchall():
            m.setdefault(iid, {})[date] = pct
        return m
    finally:
        conn.close()


def next_trade_date(dates_sorted, d):
    return next((x for x in dates_sorted if x > d), None)


def main():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    shadow = json.loads(SHADOW.read_text(encoding="utf-8"))
    idx = load_index_map()
    sh_dates = sorted(idx["sh"].keys())

    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 110)
    out("每日速递 AI 预测历史命中率对账(独立重算, 2026-09-08)")
    out(f"对账对象: brief_ledger.json {len(ledger)} 条(预测侧) + brief_shadow.json {len(shadow)} 条(规则基线条是对照)")
    out(f"预测对象: range=上证指数(sh); index_ranges 子指数对照 sz/cyb; hs300 为任务书口径对照")
    out(f"方向三分类: >+{HIT_THRESHOLD}% up / <-{HIT_THRESHOLD}% down / 其余 flat; 次日=T+1 首个交易日(全局交易日对齐)")
    out("=" * 110)

    # ---- ledger 逐条对账 ----
    out(f"\n【一】brief_ledger 逐条对账(上证 sh / 沪深300 hs300 / 子指数 sz·cyb)")
    hdr = (f"{'date':10} {'call':6} {'range':16} | {'sh%':>7} {'sh_dir':6} {'dirH':5} "
           f"{'rngH':5} | {'hs300%':>7} {'hs_dir':6} {'hsdirH':6} | "
           f"{'sz_pred':14} {'sz%':>7} {'szH':5} | {'cyb_pred':14} {'cyb%':>7} {'cybH':5}")
    out(hdr)
    out("-" * 110)

    rows_eval = []  # (date, call, rng_lo, rng_hi, sh_pct, sh_dir, dir_hit_strict, dir_hit_loose, rng_hit)
    for r in ledger:
        d = r["date"]
        nxt = next_trade_date(sh_dates, d)
        if nxt is None:
            out(f"{d}      {r['pred_side']['direction_call']:6}  ... 次日无数据(待评估: 生成日之后尚无交易日收盘)")
            continue
        ps = r["pred_side"]
        call = ps.get("direction_call") or ps.get("direction")
        rng = ps.get("range") or {}
        lo, hi = rng.get("lo"), rng.get("hi")
        sh_pct = idx["sh"].get(nxt)
        hs300_pct = idx["hs300"].get(nxt)
        sh_dir = actual_direction(sh_pct)
        hs_dir = actual_direction(hs300_pct)
        # 方向命中
        dir_hit_strict = (call == sh_dir) if (call and sh_dir) else None
        # 宽松口径: 押方向同向即可(flat 也算中)
        if call == "up" and sh_pct is not None and sh_pct >= 0:
            dir_hit_loose = True
        elif call == "down" and sh_pct is not None and sh_pct <= 0:
            dir_hit_loose = True
        elif call == "flat":
            dir_hit_loose = (sh_dir == "flat")
        else:
            dir_hit_loose = None if sh_pct is None else False
        # 区间命中(上证)
        rng_hit = (lo <= sh_pct <= hi) if (sh_pct is not None and lo is not None) else None
        # 子指数
        def _sub(pred_lo, pred_hi, iid):
            p = idx.get(iid, {}).get(nxt)
            return (p, (pred_lo <= p <= pred_hi) if (p is not None and pred_lo is not None) else None)
        sz_pred = next((x for x in ps.get("index_ranges") or [] if x.get("index_id") == "sz"), None)
        cyb_pred = next((x for x in ps.get("index_ranges") or [] if x.get("index_id") == "cyb"), None)
        sz_p, sz_h = _sub((sz_pred or {}).get("lo"), (sz_pred or {}).get("hi"), "sz") if sz_pred else (None, None)
        cyb_p, cyb_h = _sub((cyb_pred or {}).get("lo"), (cyb_pred or {}).get("hi"), "cyb") if cyb_pred else (None, None)

        fsh = f"{sh_pct:+.2f}" if sh_pct is not None else "  --"
        fhs = f"{hs300_pct:+.2f}" if hs300_pct is not None else "  --"
        fsz = f"{sz_p:+.2f}" if sz_p is not None else "  --"
        fcyb = f"{cyb_p:+.2f}" if cyb_p is not None else "  --"
        rng_s = f"[{lo},{hi}]" if lo is not None else "  --"
        sz_s = f"[{(sz_pred or {}).get('lo')},{(sz_pred or {}).get('hi')}]" if sz_pred else "  --"
        cyb_s = f"[{(cyb_pred or {}).get('lo')},{(cyb_pred or {}).get('hi')}]" if cyb_pred else "  --"
        out(f"{d} {call or '-':>6} {rng_s:16} | {fsh:>7} {sh_dir or '--':6} "
            f"{'Y' if dir_hit_strict else ('n' if dir_hit_strict is False else '-'):>5} "
            f"{'Y' if rng_hit else ('n' if rng_hit is False else '-'):>5} | "
            f"{fhs:>7} {hs_dir or '--':6} {'Y' if (call == hs_dir) else ('n' if (call and hs_dir) else '-'):>6} | "
            f"{sz_s:14} {fsz:>7} {'Y' if sz_h else ('n' if sz_h is False else '-'):>5} | "
            f"{cyb_s:14} {fcyb:>7} {'Y' if cyb_h else ('n' if cyb_h is False else '-'):>5}")
        rows_eval.append(dict(
            date=d, call=call, lo=lo, hi=hi, next=nxt,
            sh_pct=sh_pct, sh_dir=sh_dir, dir_strict=dir_hit_strict, dir_loose=dir_hit_loose,
            rng_hit=rng_hit, hs300_pct=hs300_pct, sz_h=sz_h, cyb_h=cyb_h,
        ))

    evaled = [r for r in rows_eval if not (r["call"] and r["sh_dir"])]
    # ---- 汇总 ----
    n = len(rows_eval)
    out("\n" + "=" * 110)
    out("【二】汇总统计")
    out(f"可评估条数: {n}/14(20260907 生成日之后 0908 未收盘 → 待评估, 不计)")
    if n:
        strict_hits = sum(1 for r in rows_eval if r["dir_strict"])
        strict_cnt = sum(1 for r in rows_eval if r["dir_strict"] is not None)
        loose_hits = sum(1 for r in rows_eval if r["dir_loose"] is True)
        loose_cnt = sum(1 for r in rows_eval if r["dir_loose"] is not None)
        rng_hits = sum(1 for r in rows_eval if r["rng_hit"])
        rng_cnt = sum(1 for r in rows_eval if r["rng_hit"] is not None)
        sz_hits = sum(1 for r in rows_eval if r["sz_h"])
        sz_cnt = sum(1 for r in rows_eval if r["sz_h"] is not None)
        cyb_hits = sum(1 for r in rows_eval if r["cyb_h"])
        cyb_cnt = sum(1 for r in rows_eval if r["cyb_h"] is not None)
        up_calls = sum(1 for r in rows_eval if r["call"] == "up")
        down_calls = sum(1 for r in rows_eval if r["call"] == "down")

        out(f"  方向命中(严格, flat=未中): {strict_hits}/{strict_cnt} = "
            f"{strict_hits/strict_cnt:.1%}" if strict_cnt else "  (无症状)")
        out(f"  方向命中(宽松, 同向即可):  {loose_hits}/{loose_cnt} = "
            f"{loose_hits/loose_cnt:.1%}" if loose_cnt else "  (无症状)")
        out(f"  区间命中(上证 pct∈range):  {rng_hits}/{rng_cnt} = "
            f"{rng_hits/rng_cnt:.1%}" if rng_cnt else "  (无区间)")
        out(f"  深证成指区间命中:            {sz_hits}/{sz_cnt} = "
            f"{sz_hits/sz_cnt:.1%}" if sz_cnt else "  (无预测)")
        out(f"  创业板指区间命中:            {cyb_hits}/{cyb_cnt} = "
            f"{cyb_hits/cyb_cnt:.1%}" if cyb_cnt else "  (无预测)")
        out(f"  押注分布: up={up_calls} down={down_calls} flat={n-up_calls-down_calls}")

        # 恒押基线: 恒 up / 恒 down
        up_actual = sum(1 for r in rows_eval if r["sh_dir"] == "up")
        down_actual = sum(1 for r in rows_eval if r["sh_dir"] == "down")
        flat_actual = sum(1 for r in rows_eval if r["sh_dir"] == "flat")
        out("")
        out(f"  实际方向分布(上证, 三分类): up={up_actual} down={down_actual} flat={flat_actual}")
        out(f"  基线对照:")
        out(f"    随机猜方向(两分):     ~{50:.0f}%  (实际 up/down 天数 {up_actual+down_actual} 天, 随机猜两分期望 {((up_actual+down_actual)/n):.1%})")
        out(f"    恒押up(占优方向):      {up_actual}/{n} = {up_actual/n:.1%}  (严格口径下恒押up命中率, flat 日算未中)")
        out(f"    恒押down:              {down_actual}/{n} = {down_actual/n:.1%}")
        # 严格口径基线: 恒押up 也要 flat=未中
        out(f"    恒押up(宽松, up/中flat同向): {(up_actual+flat_actual)}/{n} = {(up_actual+flat_actual)/n:.1%}")

    # ---- shadow 巡航堡垒 ----
    out("\n" + "=" * 110)
    out("【三】影子规则(brief_shadow)方向对账 —— 规则基线条是对照")
    out(f"{'date':10} {'pred_shadow':12}{'sh%':>8} {'sh_dir':6} {'HIT':5}")
    sh_ev = [r for r in ledger if r.get("date") in {s["date"] for s in shadow}]
    sh_rows = []
    for s in sorted(shadow, key=lambda x: x["date"]):
        d = s["date"]
        nxt = next_trade_date(sh_dates, d)
        if nxt is None:
            out(f"{d} {'':12} 次日无数据")
            continue
        p = idx["sh"].get(nxt)
        ad = actual_direction(p)
        pred = s.get("pred_shadow")
        hit = (pred == ad) if (pred and ad) else None
        out(f"{d} {str(pred):12}{p if p is None else '+%.2f' % p:>8} {ad or '--':6} "
            f"{'Y' if hit else ('n' if hit is False else '-')}")
        sh_rows.append(hit)
    ev = [h for h in sh_rows if h is not None]
    if ev:
        out(f"  影子命中: {sum(ev)}/{len(ev)} = {sum(ev)/len(ev):.1%}")

    (OUT / "reconcile_ledger_hits.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[结果已存] {OUT / 'reconcile_ledger_hits.txt'}")


if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────────────────────
# 【四】history 全生命周期对账(0810-0904, 官方归档=用户实际展示位)
# 说明: ledger 只覆盖 0819 起(record_ledger Phase1 2026-08-26 上线, 0819-0828 由
#       shadow 迁移并入);更早 0810-0818 的记录仅在 daily_brief_history.json。
#       本节对 history 全部可评估条目(次日已收盘)做方向+区间独立对账, 补全全貌。
# ─────────────────────────────────────────────────────────────────────────────
def history_reconcile():
    hist_path = ROOT / "static-site" / "data" / "daily_brief_history.json"
    if not hist_path.exists():
        print("[四] daily_brief_history.json 不存在, 跳过")
        return
    hist = json.loads(hist_path.read_text(encoding="utf-8")).get("items", [])
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    shm = {d: p for d, p in conn.execute(
        "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date")}
    conn.close()
    sh_dates = sorted(shm.keys())

    lines = []
    def out(s=""):
        print(s); lines.append(s)

    out("\n" + "=" * 110)
    out("【四】daily_brief_history 全生命周期方向/区间对账(含 ledger 未覆盖的 0810-0818)")
    out(f"{'date':10} {'pred':6} {'range':16} | {'sh%':>7} {'sh_dir':6} {'dirH':5} {'rngH':5}")
    rows = []
    for it in sorted(hist, key=lambda x: x["date"]):
        dt = it["date"]
        nxt = next((x for x in sh_dates if x > dt), None)
        if nxt is None:
            continue
        pct = shm.get(nxt)
        ad_ = actual_direction(pct)
        mm = it.get("meta") or {}
        pred = mm.get("direction_call") or mm.get("direction")
        rng = mm.get("range") or {}
        lo, hi = rng.get("lo"), rng.get("hi")
        dhit = (pred == ad_) if (pred and ad_) else None
        rhit = (lo <= pct <= hi) if (pct is not None and lo is not None) else None
        rng_s = f"[{lo},{hi}]" if lo is not None else "  --"
        out(f"{dt} {str(pred or '-'):6} {rng_s:16} | "
            f"{pct if pct is None else '+%.2f' % pct:>7} {ad_ or '--':6} "
            f"{'Y' if dhit else ('n' if dhit is False else '-'):>5} "
            f"{'Y' if rhit else ('n' if rhit is False else '-'):>5}")
        rows.append(dict(dt=dt, pred=pred, pct=pct, ad=ad_, dhit=dhit, rhit=rhit))

    ev = [r for r in rows if r["pred"]]
    if ev:
        d_hit = sum(1 for r in ev if r["dhit"])
        r_hit = sum(1 for r in ev if r["rhit"] is True)
        r_cnt = sum(1 for r in ev if r["rhit"] is not None)
        out("")
        out(f"  全生命周期方向命中: {d_hit}/{len(ev)} = {d_hit/len(ev):.1%}")
        out(f"  区间命中(0814+共{r_cnt}条): {r_hit}/{r_cnt} = {r_hit/r_cnt:.1%}" if r_cnt else "  无区间")
        # 分阶段
        old = [r for r in ev if r["dt"] < "20260825"]
        new = [r for r in ev if r["dt"] >= "20260825"]
        old_h = sum(1 for r in old if r["dhit"])
        new_h = sum(1 for r in new if r["dhit"])
        out(f"  阶段拆分: 0810-0824(老方向,{len(old)}条)={old_h}/{len(old)}={old_h/len(old):.1%} | "
            f"0825+(R3强制direction_call,{len(new)}条)={new_h}/{len(new)}={new_h/len(new):.1%}")
        # 基线
        up_a = sum(1 for r in rows if r["ad"] == "up")
        dn_a = sum(1 for r in rows if r["ad"] == "down")
        fl_a = sum(1 for r in rows if r["ad"] == "flat")
        n = len(rows)
        out(f"  实际方向分布: up={up_a} down={dn_a} flat={fl_a}(n={n}, flat占比{fl_a/n:.0%})")
        out(f"  基线: 恒押up严格={up_a}/{n}={up_a/n:.1%} | 恒押down={dn_a}/{n}={dn_a/n:.1%} | "
            f"随机三分≈33%")

    (OUT / "reconcile_ledger_hits.txt").parent.mkdir(parents=True, exist_ok=True)
    with (OUT / "reconcile_ledger_hits.txt").open("a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(lines))

history_reconcile()
