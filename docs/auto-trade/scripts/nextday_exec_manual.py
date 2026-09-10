#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动更新「实操步骤表格」行为状态工具(阶段一 · 未接自动化时人工跟单用)

目的: 用户手动完成某步操作后, 把 auto_trade_steps.json 里对应行为状态更新为真实状态,
      让页面表格与真实持仓对齐; 同时也是阶段二自动化执行器回写状态的同构脚本参考。

口径: 状态机见 docs/auto-trade/next-day-buy-prd-20260910.md §6.3
      (pending/submitted/filled/partial_filled/cancelled/tailback/skipped/done/failed)

输入: static-site/data/auto_trade_steps.json (不存在则初始化骨架)
输出: 同一文件原地更新 + 追加历史事件记录
复现/用法:
  python3 docs/auto-trade/scripts/nextday_exec_manual.py --list 20260907
  python3 docs/auto-trade/scripts/nextday_exec_manual.py --status 20260907 3 filled --price 1.123 --shares 8900
  python3 docs/auto-trade/scripts/nextday_exec_manual.py --status 20260907 5 done --note "手动卖出完成"
"""
import argparse, json, sys, datetime, os

ROOT = "/Users/linhuichen/code/trade"
STEPS_PATH = os.path.join(ROOT, "static-site/data/auto_trade_steps.json")

STATUS_TEXT = {
    "pending": "待执行", "submitted": "已挂单", "filled": "已成交",
    "partial_filled": "部分成交", "cancelled": "已撤销", "tailback": "已兜底",
    "skipped": "已跳过", "done": "已完成", "failed": "执行失败",
}
# 允许流转白名单(§6.3 状态机); None = 任意
TRANSITIONS = {
    "pending":     {"submitted", "skipped"},
    "submitted":   {"filled", "partial_filled", "cancelled", "skipped", "failed"},
    "partial_filled": {"filled", "cancelled", "tailback", "skipped"},
    "cancelled":   {"tailback", "skipped", "failed"},
    "tailback":    {"done", "failed"},
    "filled":      {"done"},
    "skipped":     set(), "failed": set(), "done": set(),
}

def load_doc():
    if os.path.exists(STEPS_PATH):
        with open(STEPS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
    else:
        doc = {"schema_version": "v1", "steps": []}
    doc_d = doc.get("date")
    for st in doc.get("steps", []):
        if st.get("date") is None and doc_d:
            st["date"] = doc_d
    return doc

def save_doc(doc):
    os.makedirs(os.path.dirname(STEPS_PATH), exist_ok=True)
    with open(STEPS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

def find_step(doc, date, seq):
    for st in doc["steps"]:
        if st.get("date") == date and st.get("seq") == seq:
            return st
    return None

def cmd_list(doc, date):
    for st in doc["steps"]:
        if st.get("date") == date:
            print(f'seq={st["seq"]} {st.get("time_slot")} {st.get("action")} '
                  f'{st.get("etf_code")} {st.get("status")}@{st.get("status_text")} '
                  f'price={st.get("actual_price", "")} note={st.get("trigger_note", "")}')
    return 0

def cmd_status(doc, date, seq, new_status, price, shares, note):
    st = find_step(doc, date, seq)
    if st is None:
        print(f"FAIL: date={date} seq={seq} 不存在于 auto_trade_steps.json", file=sys.stderr)
        return 1
    old = st.get("status")
    allowed = TRANSITIONS.get(old, set())
    if new_status not in allowed:
        print(f"FAIL: 非法流转 {old} -> {new_status}(白名单={sorted(allowed) or '终态'})", file=sys.stderr)
        return 1
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history = st.get("_history", [])
    history.append({"from": old, "to": new_status, "at": now,
                    "note": note or "", "actor": "manual"})
    st["_history"] = history
    st["status"] = new_status
    st["status_text"] = STATUS_TEXT.get(new_status, new_status)
    if price is not None:
        st["actual_price"] = price
    if shares is not None:
        st["actual_shares"] = shares
    st["updated_at"] = now
    if note:
        st["remark"] = note
    save_doc(doc)
    print(f"OK: {date}/{seq} {old} -> {new_status} ({STATUS_TEXT.get(new_status)}) @ {now}")
    return 0

def main():
    ap = argparse.ArgumentParser(description="实操步骤表格手动状态更新")
    ap.add_argument("--list", metavar="DATE", help="列出某交易日全部行为行")
    ap.add_argument("--status", nargs=3, metavar=("DATE", "SEQ", "NEW_STATUS"),
                    help="更新某行为状态")
    ap.add_argument("--price", type=float, help="实际成交价")
    ap.add_argument("--shares", type=float, help="实际成交份额")
    ap.add_argument("--note", help="备注")
    a = ap.parse_args()
    doc = load_doc()
    if a.list:
        return cmd_list(doc, a.list)
    if a.status:
        return cmd_status(doc, a.status[0], int(a.status[1]), a.status[2],
                          a.price, a.shares, a.note)
    ap.print_help()
    return 2

if __name__ == "__main__":
    sys.exit(main())
