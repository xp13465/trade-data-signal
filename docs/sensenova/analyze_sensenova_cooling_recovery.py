#!/usr/bin/env python3
"""sensenova-rotate-proxy 冷却恢复耗时分布统计(正式版)

目的:从请求日志解析「同一 key 进入 COOL → 冷却解除 → 再撞 quota 429」的节奏,
     输出定量分布(p50/p90/p99/max),为冷却档位(COOL_L0_SEC/_cool_duration_sec)
     定档提供数据依据,消灭「冷却 1-2min 解除 → ~1min 又撞」的空转。
方法口径:
  - 日志 RESP 行不带 key 标识,无法精确关联「某 key 冷却后哪次响应成功」;
    因此重建每把 key 的冷却状态机(COOL 标记 + SKIP COOLED 事件),按日志时间线重放:
      指标A COOL→冷却期内最后一次被 SKIP = 代理侧冷却占用时长观测值
      指标B 冷却解除(末次 SKIP)→ 下一次 COOL = 解除后到再撞 quota 的真实可用时长(定档核心)
      指标C 相邻两次 COOL 间隔 = 每把 key 冷却周期复发节奏
      指标D 全局 429 响应间隔(不限 key)= 整体撞车频率
  - 日志时间=本机本地时间(CST+0800,北京时间);小时分布用于定位 quota 429 高峰窗口。
输入依赖: /Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log(仓外,真实日志)
输出:      stdout(分布表 + 小时分布 + 每 key 分解)
复现命令:  python3 docs/sensenova/analyze_sensenova_cooling_recovery.py
"""
import re
from collections import defaultdict
from datetime import datetime

LOG_PATH = "/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log"
TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(.*)$")


def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[int(p / 100.0 * (len(s) - 1))]


def fmt_secs(v):
    if v < 120:
        return f"{v:.0f}s"
    return f"{v / 60:.1f}min"


def read_events():
    evs = []
    for line in open(LOG_PATH, errors="replace"):
        m = TS_RE.match(line.strip())
        if m:
            evs.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp(), m.group(2)))
    return evs


def build_seq():
    """每 key:COOL 时间列表 + SKIP 时间列表(去重,排序)。"""
    cool = defaultdict(list)
    skip = defaultdict(list)
    for epoch, rest in read_events():
        if rest.startswith("COOL KEY") and len(rest.split(" ")) > 1:
            cool[rest.split(" ")[1]].append(epoch)
        elif rest.startswith("SKIP COOLED") and len(rest.split(" ")) > 2:
            skip[rest.split(" ")[2]].append(epoch)
    for k in cool:
        cool[k] = sorted(cool[k])
    for k in skip:
        skip[k] = sorted(skip[k])
    return cool, skip


def main():
    cool_times, skip_times = build_seq()

    all_active, all_usable, all_gaps = [], [], []
    per_key = {}
    for key in sorted(cool_times):
        cs = cool_times[key]
        ss = skip_times[key] if key in skip_times else []
        active, usable = [], []
        for i, c in enumerate(cs):
            nxt = cs[i + 1] if i + 1 < len(cs) else float("inf")
            last_skip = None
            j = len(ss) - 1
            while j >= 0 and ss[j] >= c:
                if ss[j] < nxt and (last_skip is None or ss[j] > last_skip):
                    last_skip = ss[j]
                j -= 1
            if last_skip is not None:
                active.append(last_skip - c)
                if nxt != float("inf"):
                    usable.append(nxt - last_skip)
            else:
                if nxt != float("inf"):
                    usable.append(nxt - c)
            if nxt != float("inf"):
                all_gaps.append(nxt - c)
        all_active += active
        all_usable += usable
        per_key[key] = (active, usable)

    def dump(title, vals, extra="n"):
        print(f"=== {title} ===")
        print(f"  {extra}: {len(vals)}")
        for p in ("p10", "p25", "p50", "p75", "p90", "p99"):
            print(f"    {p}: {fmt_secs(pct(vals, float(p[1:])))}")
        print(f"    max: {fmt_secs(max(vals)) if vals else 0}")

    dump("指标A: COOL → 冷却期内最后一次被 SKIP(代理侧冷却占用时长观测)", all_active)
    bucket = lambda v: (sum(1 for x in v if x < 60), sum(1 for x in v if 60 <= x < 300), sum(1 for x in v if x >= 300))
    a = bucket(all_active)
    print(f"    <60s: {a[0]} / 60-300s: {a[1]} / >=300s: {a[2]}")
    print()

    dump("指标B: 冷却解除后到下一次 quota 撞车的真实可用时长(定档核心)", all_usable)
    b = bucket(all_usable)
    print(f"    <30s: {sum(1 for x in all_usable if x < 30)} / 30-120s: {sum(1 for x in all_usable if 30 <= x < 120)} / 120-300s: {sum(1 for x in all_usable if 120 <= x < 300)} / >=300s: {sum(1 for x in all_usable if x >= 300)}")
    print()

    dump("指标C: 相邻两次 COOL 间隔(冷却周期复发节奏)", all_gaps)
    print()

    print("=== per-key 指标B(可用时长) ===")
    for key, (aa, uu) in sorted(per_key.items()):
        if uu:
            print(f"  {key}: n={len(uu)} p50={fmt_secs(pct(uu, 50))} p90={fmt_secs(pct(uu, 90))} max={fmt_secs(max(uu))}")

    # 小时分布(429 响应 + COOL 标记)
    # 注意:日志时间字符串=本机本地时间(CST+0800,北京时间);直接用字符串小时,不转 epoch(epoch 是 UTC)。
    h_429, h_cool = defaultdict(int), defaultdict(int)
    for line in open(LOG_PATH, errors="replace"):
        m = TS_RE.match(line.strip())
        if not m:
            continue
        h = int(m.group(1)[11:13])
        rest = m.group(2)
        if rest.startswith("RESP") and " -> 429 " in rest:
            h_429[h] += 1
        if rest.startswith("COOL KEY"):
            h_cool[h] += 1
    print()
    print("=== 429 响应按小时分布(北京时间) ===")
    m = max(h_429.values()) or 1
    for h in range(24):
        c = h_429.get(h, 0)
        print(f"  {h:02d}:00 {c:5d} {'#' * (c * 40 // m)}")
    print()
    print("=== COOL 标记按小时分布(北京时间) ===")
    m = max(h_cool.values()) or 1
    for h in range(24):
        c = h_cool.get(h, 0)
        print(f"  {h:02d}:00 {c:5d} {'#' * (c * 40 // m)}")


if __name__ == "__main__":
    main()