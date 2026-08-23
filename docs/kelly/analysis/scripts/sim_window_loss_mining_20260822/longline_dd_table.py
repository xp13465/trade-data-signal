#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
longline_dd_table.py — mine25 长线报告 §11.5/§11.6 数据提取器(回撤排序表 + 双维综合评级)

目的
    从 mine25_longline_operable.json 提取九模式(A-I)× 6 方案 × cap20 档的回撤
    (mdd_merged_terminal.mdd)与合计(total_merged),生成两块 markdown:
      §11.5 回撤排序表:每模式一行,行内 6 方案按 |mdd| 从浅到深排序
      §11.6 双维综合排名分:模式内「收益名次(total_merged 降序)+ 回撤名次(|mdd| 升序)
      求和 = 综合分(越小越强)」,输出九模式综合分矩阵 + 各方案综合分中位数/总和结论
    方法学与前端水印思路同源:多维排名综合(收益名次 + 回撤名次)。
    数字全部程序化从 json 提取,禁止手抄;缺 cap 档/字段缺失如实标注「数据缺口」不编数。

输入
    data/mine25_longline_operable.json(mine25_longline_operable.py 生成,
        runs[mode A-I][project][cap] 结构,cap ∈ {'10','20','50','nocap'},
        字段 mdd_merged_terminal{mdd,...} 与 total_merged)

输出
    stdout:两块 markdown 表(可直接粘入报告)
    data/mine25_longline_dd_table.md:同样内容落盘存档(供报告引用/复查)

关键参数
    CAP_MAIN = '20'(cap20 主推档,mine25 主口径;nocap 仅对照)
    PROJECT_LABELS:json 项目键 → 展示名(8键/9键/A/B/C/NEW)
    MODE_LABELS:json 模式键 A-I → 报告行名

复现
    cd /Users/linhuichen/code/trade/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822
    python3 longline_dd_table.py
    数据版本:signal_date 至 20260820,MTM 价格截至 2026-08-23 05:09(见 json meta)
"""

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "mine25_longline_operable.json"
OUT = HERE / "data" / "mine25_longline_dd_table.md"

CAP_MAIN = "20"

# json 项目键 → 展示名(与报告 §11.1/§11.2 表头一致)
PROJECT_ORDER = ["P0_8键", "P1_9键", "A_on9", "B_on9", "C_on9", "NEW_mine24_14键"]
PROJECT_LABELS = {
    "P0_8键": "8键",
    "P1_9键": "9键",
    "A_on9": "A",
    "B_on9": "B",
    "C_on9": "C",
    "NEW_mine24_14键": "NEW",
}

# json 模式键 → 报告行名(与 §11.1 一致)
MODE_LABELS = {
    "A": "A 固定10天",
    "B": "B 3%止盈(10天上限)",
    "C": "C 5%止盈(10天上限)",
    "D": "D 7%止盈(10天上限)",
    "E": "E 持有5天",
    "F": "F 持有15天",
    "G": "G 卖出信号",
    "H": "H 卖出+追止损",
    "I": "I 追关注加追止损",
}
MODE_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]


def load():
    with open(SRC, encoding="utf-8") as f:
        return json.load(f)


def get_cell(runs, mode, proj, cap):
    """取 (total_merged, mdd_abs, mdd_raw, gap_flag);缺档/缺字段返回 gap 标记,不编数。"""
    cell = runs.get(mode, {}).get(proj, {}).get(cap)
    if cell is None:
        return None
    total = cell.get("total_merged")
    mdd_obj = cell.get("mdd_merged_terminal") or {}
    mdd = mdd_obj.get("mdd")
    if total is None or mdd is None:
        return None
    return {"total": total, "mdd": mdd, "mdd_abs": abs(mdd),
            "trough": mdd_obj.get("trough_day"), "recovered": mdd_obj.get("recovered")}


def fmt_mdd(v):
    return f"{v:+,.0f}".replace("-", "-")  # mdd 本身为负,保留负号


def rank_rows(runs, cap):
    """每模式内:收益名次(total 降序)、回撤名次(|mdd| 升序)。返回 {mode: {proj: cell+ranks}}"""
    table = {}
    for m in MODE_ORDER:
        row = {}
        for p in PROJECT_ORDER:
            cell = get_cell(runs, m, p, cap)
            if cell is not None:
                row[p] = cell
        gaps = [p for p in PROJECT_ORDER if p not in row]
        # 收益名次:total 降序;回撤名次:|mdd| 升序
        by_total = sorted(row.items(), key=lambda kv: -kv[1]["total"])
        by_dd = sorted(row.items(), key=lambda kv: kv[1]["mdd_abs"])
        for i, (p, c) in enumerate(by_total, 1):
            c["rank_total"] = i
        for i, (p, c) in enumerate(by_dd, 1):
            c["rank_dd"] = i
        for p, c in row.items():
            c["combo"] = c["rank_total"] + c["rank_dd"]
        table[m] = {"row": row, "gaps": gaps}
    return table


def dd_order_str(row):
    """回撤从浅到深排序串(|mdd| 小在前),用 > 连接(左边=回撤更浅)。"""
    items = sorted(row.items(), key=lambda kv: kv[1]["mdd_abs"])
    parts = []
    for p, c in items:
        parts.append(f"{PROJECT_LABELS[p]} {fmt_mdd(c['mdd'])}")
    # ≈ 标注:相邻差距 <2%(与 §11.1 口径一致,基于 |mdd| 绝对值)
    out = []
    for i, s in enumerate(parts):
        out.append(s)
        if i < len(items) - 1:
            a, b = items[i][1]["mdd_abs"], items[i + 1][1]["mdd_abs"]
            out.append("≈" if abs(a - b) / max(a, b) < 0.02 else ">")
    return " ".join(out)


def build_dd_table(table):
    lines = [
        "| 模式 | cap20 六方案回撤排序(|mdd| 从浅到深,元;≈=差距<2%) |",
        "|---|---|",
    ]
    for m in MODE_ORDER:
        lines.append(f"| {MODE_LABELS[m]} | {dd_order_str(table[m]['row'])} |")
    return "\n".join(lines)


def build_combo_matrix(table):
    """九模式综合分矩阵:格=综合分(收益名次+回撤名次),越小越强。"""
    lines = [
        "| 模式 | " + " | ".join(PROJECT_LABELS[p] for p in PROJECT_ORDER) + " |",
        "|---|" + "---|" * len(PROJECT_ORDER),
    ]
    for m in MODE_ORDER:
        row = table[m]["row"]
        cells = []
        for p in PROJECT_ORDER:
            if p in row:
                c = row[p]
                cells.append(f"{c['combo']}(收{c['rank_total']}+回{c['rank_dd']})")
            else:
                cells.append("数据缺口")
        lines.append(f"| {MODE_LABELS[m]} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def combo_conclusion(table):
    """各方案综合分中位数/总和,给一行结论。"""
    # 每模式综合分最小的方案 = 该模式综合第一
    mode_best = {m: min(c["combo"] for c in table[m]["row"].values()) for m in MODE_ORDER if table[m]["row"]}
    stats = {}
    for p in PROJECT_ORDER:
        vals = [table[m]["row"][p]["combo"] for m in MODE_ORDER if p in table[m]["row"]]
        if vals:
            firsts = sum(1 for m in MODE_ORDER
                         if p in table[m]["row"] and table[m]["row"][p]["combo"] == mode_best[m])
            stats[p] = {"n": len(vals), "median": statistics.median(vals),
                        "sum": sum(vals), "firsts": firsts}
    ranked = sorted(stats.items(), key=lambda kv: (kv[1]["median"], kv[1]["sum"]))
    lines = ["| 方案 | 综合分中位数 | 综合分总和 | 综合分第一的模式数 |", "|---|---|---|---|"]
    for p, s in ranked:
        lines.append(f"| {PROJECT_LABELS[p]} | {s['median']:g} | {s['sum']} | {s['firsts']}/{s['n']} |")
    best = ranked[0]
    concl = (f"综合分中位数最优=**{PROJECT_LABELS[best[0]]}**(中位 {best[1]['median']:g},"
             f"九模式总和 {best[1]['sum']},拿下 {best[1]['firsts']}/{best[1]['n']} 个模式综合第一)。")
    return "\n".join(lines), concl


def main():
    data = load()
    runs = data["runs"]
    table = rank_rows(runs, CAP_MAIN)

    # 数据缺口检查(全 9×6×cap20)
    gap_lines = []
    for m in MODE_ORDER:
        if table[m]["gaps"]:
            gap_lines.append(f"{m}: 缺 {','.join(table[m]['gaps'])}")
    gap_note = (";".join(gap_lines)) if gap_lines else "无(cap20 档 9×6=54 格全在)"

    dd_tbl = build_dd_table(table)
    combo_tbl = build_combo_matrix(table)
    stat_tbl, concl = combo_conclusion(table)

    md = f"""<!-- 由 longline_dd_table.py 自动生成,数字逐位取自 mine25_longline_operable.json(cap20 档),勿手改 -->

## §11.5 回撤排序表(cap20 主推档,mdd_merged_terminal,|mdd| 从浅到深;≈=差距<2%)

{dd_tbl}

数据缺口检查:{gap_note}

## §11.6 双维综合排名分(收益名次 + 回撤名次,模式内求和,越小越强)

方法学:每个模式内,6 方案按收益(total_merged)降序取名次、按回撤(|mdd| 升序)取名次,两名次求和=综合分(2~12,越小越强)。与前端水印思路同源:多维排名综合(稳健/激进/保守水印即由此类多维排名而来)。

{combo_tbl}

各方案综合分汇总(九模式):

{stat_tbl}

一行结论:{concl}
"""
    OUT.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[saved] {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
