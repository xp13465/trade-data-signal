#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_monitor_alerts.py - 从 schedule_monitor_launchd.log 提取全量告警检测块并分类统计
目的: 运维告警体系评估的事实源提取(近1-2周全量告警清单 + 分类统计)
输入依赖: /Users/linhuichen/code/trade-data/data/logs/schedule_monitor_launchd.log
输出: stdout(告警清单 + 分类统计);可选 --since 2026-08-02 过滤日期
复现命令: python3 docs/ops/scripts/parse_monitor_alerts.py --since 2026-08-02
数据截止: 2026-08-15 22:00
关键口径: "检测到 N 个告警:" 块 = 本次轮询发现的首次告警(已 active 的会被 suppress,
  故 SEVERE 行数 = 实际触发邮件数), "[notify] 邮件已发送" = 告警邮件事件,
  "[suppress]" 行 = 去重抑制(不重发), "[recovery]" 行 = 恢复事件
"""
import re
import sys
from collections import Counter
from datetime import datetime

LOG = "/Users/linhuichen/code/trade-data/data/logs/schedule_monitor_launchd.log"

def main():
    since = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--since" and i + 1 < len(args):
            since = datetime.strptime(args[i + 1], "%Y-%m-%d")

    with open(LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    events = []
    cur_ts = None
    for ln in lines:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$", ln.strip())
        if m:
            cur_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            rest = m.group(2).strip()
            if rest.startswith("检测到") or rest.startswith("OK ") or rest.startswith("告警已写入"):
                events.append((cur_ts, "cycle", rest))
            elif rest.startswith("SEVERE"):
                events.append((cur_ts, "alert", rest))
            elif rest.startswith("  [恢复]") or rest.startswith("  ["):
                events.append((cur_ts, "recovery", rest))
            else:
                events.append((cur_ts, "other", rest))
        else:
            s = ln.strip()
            if s.startswith("SEVERE:") and cur_ts:
                events.append((cur_ts, "alert", s))
            elif s.startswith("[suppress]") and cur_ts:
                events.append((cur_ts, "suppress", s))
            elif s.startswith("[notify]") and cur_ts:
                events.append((cur_ts, "notify", s))
            elif s.startswith("[recovery]") and cur_ts:
                events.append((cur_ts, "recovery", s))
            elif s.startswith("[cooldown]") and cur_ts:
                events.append((cur_ts, "cooldown", s))
            elif s.startswith("[hold]") and cur_ts:
                events.append((cur_ts, "hold", s))
            elif s.startswith("[self_heal") and cur_ts:
                events.append((cur_ts, "selfheal", s))
            elif s.startswith("[silent recovery]") and cur_ts:
                events.append((cur_ts, "silent_recovery", s))
            elif s.startswith("[cleanup]") and cur_ts:
                events.append((cur_ts, "cleanup", s))
            elif s.startswith("[info]") and cur_ts:
                events.append((cur_ts, "info", s))
            elif s.startswith("[warn]") and cur_ts:
                events.append((cur_ts, "warn", s))
            elif s and cur_ts:
                events.append((cur_ts, "other", s))

    if since:
        events = [e for e in events if e[0] >= since]

    alert_types = Counter()
    alert_by_task = Counter()
    alert_details = []
    notify_feishu = 0
    notify_telegram_skip = 0
    suppress_counts = Counter()
    recovery_counts = Counter()

    for ts, kind, detail in events:
        if kind == "alert":
            body = detail[len("SEVERE:"):].strip()
            task = body.split(" ", 1)[0]
            if task.startswith("com.trade."):
                task = task.replace("com.trade.", "").replace("-", "_")
            elif task in ("线上", "R2"):
                task = "overview" if task == "线上" else "R2"
            if "漏跑" in body:
                atype = "漏跑"
            elif "log异常关键词" in body:
                atype = "log异常关键词"
            elif "执行耗时" in body:
                atype = "执行耗时超阈值"
            elif "退出失败" in body:
                atype = "退出失败"
            elif "未加载" in body:
                atype = "launchctl未加载"
            elif "时效滞后" in body:
                atype = "产物时效滞后"
            elif "不可达" in body:
                atype = "R2不可达"
            elif "超时未完成" in body:
                atype = "进行中超时"
            elif "耗时" in body:
                atype = "耗时"
            else:
                atype = "其他"
            alert_types[atype] += 1
            alert_by_task[task] += 1
            alert_details.append((ts, task, atype, detail))
        elif kind == "suppress":
            s = detail[len("[suppress]"):].strip()
            task = s.split(" ", 1)[0]
            suppress_counts[task] += 1
        elif kind == "recovery":
            recovery_counts["recovery"] += 1
        elif kind == "cooldown":
            recovery_counts["cooldown"] += 1
        elif kind == "notify":
            if "Feishu 已发送" in detail:
                notify_feishu += 1
            if "telegram" in detail and "跳过" in detail:
                notify_telegram_skip += 1

    print(f"=== 告警检测块解析结果 ===")
    print(f"日志文件: {LOG}")
    print(f"过滤起始: {since or '全量(2026-07-23 起)'}")
    print(f"事件总数: {len(events)} (cycle={sum(1 for e in events if e[1]=='cycle')}, "
          f"alert={sum(1 for e in events if e[1]=='alert')})")
    print()
    print("=== SEVERE 告警类型统计 ===")
    for k, v in alert_types.most_common():
        print(f"  {k:20s} {v}")
    print()
    print("=== SEVERE 告警按任务统计 ===")
    for k, v in alert_by_task.most_common():
        print(f"  {k:25s} {v}")
    print()
    print("=== suppress(去重抑制)按任务统计 ===")
    for k, v in suppress_counts.most_common():
        print(f"  {k:25s} {v}")
    print()
    print("=== 恢复事件统计 ===")
    for k, v in recovery_counts.most_common():
        print(f"  {k:20s} {v}")
    print()
    print("=== 全量 SEVERE 告警清单(时间/任务/类型/详情) ===")
    for ts, task, atype, detail in alert_details:
        print(f"  {ts.strftime('%m-%d %H:%M')} | {task:20s} | {atype:14s} | {detail[:160]}")

if __name__ == "__main__":
    main()
