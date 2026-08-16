#!/usr/bin/env python3
"""
目的:统计 Claude Code 会话记录的 token 缓存命中率(cache_read/(cache_read+input)),量化 2026-08-15 优化落档前后的改善效果。

方法口径:
  - 逐条扫描 assistant 消息的 message.usage 字段,提取:
      cache_read_input_tokens / cache_creation_input_tokens / input_tokens
  - 命中率 = cache_read / (cache_read + input)(cache_read 命中 + input 冷启动重读)
  - 按天聚合求和后算当天命中率(不是逐条命中率平均)
  - 对比窗口:前=08-10~08-14,后=08-15~08-16(按任务定)

输入依赖:会话 JSONL 目录(默认 ~/.claude/projects/-Users-linhuichen-code-trade/),逐行读不进内存。

输出:按天命中率表 + 前后对比结论(改善/恶化/无变化 + 百分比)。

复现命令:
      python3 scripts/token_cache_stats.py                     # 扫默认目录
      python3 scripts/token_cache_stats.py <jsonl_dir> <start> <end>   # 自定义目录+窗口(YYYY-MM-DD)
"""
import json
import glob
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta


def parse_usage(line_obj):
    """从一行事件对象提取 usage 三字段,失败返回 None。"""
    m = line_obj.get("message") or {}
    usage = m.get("usage") if isinstance(m, dict) else None
    if not isinstance(usage, dict):
        return None
    cr = usage.get("cache_read_input_tokens")
    cc = usage.get("cache_creation_input_tokens")
    inp = usage.get("input_tokens")
    if cr is None or cc is None or inp is None:
        return None
    return int(cr), int(cc), int(inp)


def scan_stream(path):
    """流式读单文件,产出 (yyyy-mm-dd, cr, cc, inp)。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "assistant":
                continue
            ts = obj.get("timestamp")
            if not ts or not isinstance(ts, str) or len(ts) < 10:
                continue
            try:
                day = datetime.fromisoformat(ts[:19]).strftime("%Y-%m-%d")
            except Exception:
                continue
            parsed = parse_usage(obj)
            if parsed is None:
                continue
            cr, cc, inp = parsed
            # 跳过异常值:一次性全 0 无效请求(cache_creation 全 0 且 cr/inp 都 0 说明空 usage)
            if cr == 0 and cc == 0 and inp == 0:
                continue
            yield day, cr, cc, inp


def main():
    jsonl_dir = (
        sys.argv[1]
        if len(sys.argv) >= 2
        else os.path.expanduser("~/.claude/projects/-Users-linhuichen-code-trade")
    )
    start = sys.argv[2] if len(sys.argv) >= 3 else "2026-08-10"
    end = sys.argv[3] if len(sys.argv) >= 4 else "2026-08-16"
    window = [datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()]

    files = glob.glob(os.path.join(jsonl_dir, "*.jsonl"))
    if not files:
        print(f"no jsonl files in {jsonl_dir}")
        sys.exit(1)

    # 按天聚合
    daily = defaultdict(lambda: {"cr": 0, "cc": 0, "inp": 0, "n": 0})
    total_files = 0
    for path in files:
        total_files += 1
        for day_str, cr, cc, inp in scan_stream(path):
            dd = datetime.strptime(day_str, "%Y-%m-%d").date()
            if not (window[0] <= dd <= window[1]):
                continue
            d = daily[day_str]
            d["cr"] += cr
            d["cc"] += cc
            d["inp"] += inp
            d["n"] += 1

    if not daily:
        print(f"no usage data in window {start}~{end} (scanned {total_files} files)")
        sys.exit(1)

    # 按天输出
    print(f"{'date':<12}{'cache_read':>14}{'cache_creation':>16}{'input':>14}{'hit_rate':>10}")
    ordered = sorted(daily.keys())
    for day_str in ordered:
        d = daily[day_str]
        denom = d["cr"] + d["inp"]
        hit = d["cr"] / denom if denom else None
        hit_txt = f"{hit:.4f}" if hit is not None else "  n/a"
        print(
            f"{day_str:<12}{d['cr']:>14,}{d['cc']:>16,}{d['inp']:>14,}"
            f"{hit_txt:>10}"
        )

    # 窗口均值对比
    cutoff = datetime.fromisoformat("2026-08-15").date()
    buckets = {"before": {"cr": 0, "inp": 0, "n": 0}, "after": {"cr": 0, "inp": 0, "n": 0}}
    for day_str, d in daily.items():
        dd = datetime.strptime(day_str, "%Y-%m-%d").date()
        key = "after" if dd >= cutoff else "before"
        b = buckets[key]
        b["cr"] += d["cr"]
        b["inp"] += d["inp"]
        b["n"] += d["n"]

    print("\n--- 窗口聚合(求和后算命中率,避免天数不等偏差) ---")
    for label in ("before", "after"):
        b = buckets[label]
        denom = b["cr"] + b["inp"]
        hit = b["cr"] / denom if denom else None
        print(
            f"{label:<8} days={b['n']:<3} cache_read={b['cr']:>14,}"
            f" input={b['inp']:>14,} hit_rate={hit if hit is None else round(hit,4)}"
        )

    bh = (buckets["before"]["cr"] / (buckets["before"]["cr"] + buckets["before"]["inp"])
          if buckets["before"]["cr"] + buckets["before"]["inp"] else None)
    ah = (buckets["after"]["cr"] / (buckets["after"]["cr"] + buckets["after"]["inp"])
          if buckets["after"]["cr"] + buckets["after"]["inp"] else None)
    if bh is None or ah is None or buckets["before"]["n"] == 0 or buckets["after"]["n"] == 0:
        print("\n结论:样本不足(前/后至少一侧无数据),无法下改善/恶化结论。")
        return
    delta = (ah - bh) * 100
    trend = "改善" if delta > 0 else ("恶化" if delta < 0 else "无变化")
    print(
        f"\n结论:命中率 前 {bh:.4f} -> 后 {ah:.4f} ({trend}, "
        f"{'+' if delta>=0 else ''}{delta:.2f} 个百分点)。"
        f"参考健康标准 >0.7 → 前{'(达标)' if bh>0.7 else '(未达标)'} / 后{'(达标)' if ah>0.7 else '(未达标)'}"
    )


if __name__ == "__main__":
    main()
