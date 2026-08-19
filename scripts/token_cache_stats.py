#!/usr/bin/env python3
"""
目的:统计 Claude Code 会话记录的 token 缓存命中率(cache_read/(cache_read+input)),量化 2026-08-15 优化落档前后的改善效果。

方法口径:
  - 逐条扫描 assistant 消息的 message.usage 字段,提取:
      cache_read_input_tokens / cache_creation_input_tokens / input_tokens
  - 命中率 = cache_read / (cache_read + input)(cache_read 命中 + input 冷启动重读)
  - 按天聚合求和后算当天命中率(不是逐条命中率平均)
  - 对比窗口:前=08-10~08-14,后=08-15~08-16(按任务定)

两种模式:
  A. 统计报告模式(默认):按天命中率表 + 前后对比结论,不写任何文件。
  B. 每日追加走势模式(--append-daily [date],默认今天):算当天命中率,
     顺带抓当天 claude 版本(claude --version)+ 当天 claude-work-mode/根 CLAUDE.md git commit 改动,
     幂等地追加/更新 claude-work-mode/README.md 的「命中率走势」表与「版本/改动日志」小节
     (按日期去重:当天已存在则更新不重复追加)。
     追加成功后自动收尾: git add/commit + push origin main(2026-08-19 用户拍板方案①,
     绕开 main-merge.sh 统一入口,只动这一个文档文件、23:30 安全窗口跑)。
     幂等无实际变更时跳过 commit+push;push non-ff 自动 fetch+rebase+重试,不 force,
     rebase 冲突 abort + 告警退出非 0(§8/§23.11)。

输入依赖:会话 JSONL 目录(默认 ~/.claude/projects/-Users-linhuichen-code-trade/),逐行读不进内存。
        追加模式另依赖:claude-work-mode/README.md(读写)、git -C trade log(读当日规范改动)。

复现命令:
      python3 scripts/token_cache_stats.py                     # A 扫默认目录,默认窗口
      python3 scripts/token_cache_stats.py <jsonl_dir> <start> <end>   # A 自定义目录+窗口(YYYY-MM-DD)
      python3 scripts/token_cache_stats.py --append-daily       # B 追加今天走势(23:30 定时)
      python3 scripts/token_cache_stats.py --append-daily 2026-08-16   # B 追加指定日期走势
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


# ---------------------------------------------------------------------------
# 每日追加走势模式(--append-daily): 幂等更新 claude-work-mode/README.md 命中率走势表 + 版本/改动日志
# ---------------------------------------------------------------------------

# 命中率走势表所在 README(相对 trade 仓库根)
README_REL = "claude-work-mode/README.md"
# 走势表内嵌区块标记(README 中该表前后两行)
TREND_MARK_START = "<!-- token-cache-trend-begin -->"
TREND_MARK_END = "<!-- token-cache-trend-end -->"
# 版本/改动日志区块标记
CHANGELOG_MARK_START = "<!-- token-cache-changelog-begin -->"
CHANGELOG_MARK_END = "<!-- token-cache-changelog-end -->"
# ASCII 迷你柱状图区块标记
ASCII_MARK_START = "<!-- token-cache-ascii-begin -->"
ASCII_MARK_END = "<!-- token-cache-ascii-end -->"
# ASCII 图刻度:每格 = 0.01 命中率,下限 0.70~1.00
ASCII_MIN = 0.70
ASCII_PER = 0.01
# trade 仓库根(用于查当日 claude-work-mode/CLAUDE.md 改动)
TRADE_ROOT = "/Users/linhuichen/code/trade"


def _run_cmd(args, cwd=None):
    """跑子进程命令,返回 stdout 清洗后字符串;失败返回空串。"""
    import subprocess
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=30
        ).stdout
        return (out or "").strip()
    except Exception:
        return ""


def _get_claude_version():
    """取当天实际运行 claude 版本,如 '2.1.224'(失败='?')。"""
    v = _run_cmd(["claude", "--version"])
    # 输出形如 "2.1.224 (Claude Code)";只取第一个 token
    if v:
        return v.split()[0]
    return "?"


def _get_day_changes(date_str):
    """返回当天 trade 仓库 claude-work-mode/CLAUDE.md 的 git commit 改动摘要列表,如 ['hash 主题']。"""
    # commit 时间戳按当日 00:00~次日 00:00(用 <date> 00:00 到 <date+1> 00:00)
    from datetime import timedelta
    d = datetime.strptime(date_str, "%Y-%m-%d")
    since = d.strftime("%Y-%m-%d 00:00")
    until = (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00")
    out = _run_cmd(
        ["git", "log", "--since=%s" % since, "--until=%s" % until,
         "--oneline", "--", "claude-work-mode/", "CLAUDE.md"],
        cwd=TRADE_ROOT,
    )
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return lines


def _split_trend_table(block):
    """从走势区块原文解析出 {date: [date, hit, cold_inp, claude_ver, changes]} 与行顺序。

    走势表列: 日期 | 命中率 | 冷读input | claude版本 | 当日改动
    返回 (ordered_dates, rows)。rows[date] = [date, hit, cold_inp, claude_ver, changes]。
    """
    rows = {}
    ordered = []
    for ln in block.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # 跳过表头行与分隔行(-- 开头的 markdown 分隔)
        if len(cells) < 5:
            continue
        if cells[0].startswith("日期") or cells[0].startswith("---"):
            continue
        date = cells[0]
        rows[date] = cells[:5]
        ordered.append(date)
    return ordered, rows


def _render_trend_table(ordered, rows):
    """渲染走势表 markdown: 表头+分隔行+按日期升序的数据行。"""
    out = []
    out.append("| 日期 | 命中率 | 冷读input | claude版本 | 当日改动 |")
    out.append("|---|---|---|---|---|")
    for date in sorted(ordered):
        r = rows[date]
        out.append(
            "| %s | %s | %s | %s | %s |" % (r[0], r[1], r[2], r[3], r[4])
        )
    return "\n".join(out)


def _split_changelog(block):
    """从版本/改动日志区块解析:返回 {header_lines_after_context}。保留既有行顺序。"""
    # 日志区内容行(排除内嵌上下文注释),原样保留;追加函数只做"按日期去重增行"
    lines = []
    for ln in block.splitlines():
        if ln.strip():
            lines.append(ln)
    return lines


def _render_ascii(ordered, rows):
    """渲染 ASCII 迷你柱状图:日期 + 柱(每格 0.01 命中率,0.70~1.00) + 冷读 input + 命中率。"""
    out = []
    out.append("```")
    out.append("命中率刻度 0.70 ───────────────────────────── 1.00 (每格 0.01)")
    for date in sorted(ordered):
        r = rows[date]
        hit = float(r[1]) if r[1] not in ("n/a",) else 0.0
        # 柱格数 = (hit - 0.70) / 0.01,最少 0 格
        if hit is not None:
            bar_n = max(0, int(round((hit - ASCII_MIN) / ASCII_PER)))
        else:
            bar_n = 0
        bar = "█" * bar_n
        # 日期用短格式(去掉年份前 4 位 "2026-",保留 MM-DD)
        short = date[5:] if len(date) >= 10 and date[4] == "-" else date
        out.append("%-6s %s(%d)  %-12s  %.4f" % (short, bar, bar_n, r[2], hit))
    out.append("```")
    return "\n".join(out)


def _replace_block(text, start_mark, end_mark, new_content):
    """把 text 中 start_mark..end_mark 之间内容替换为 new_content(含两个标记)。"""
    pre = text.split(start_mark, 1)[0] + start_mark + "\n"
    rest = text.split(start_mark, 1)[1]
    # 找到 end_mark,去掉其前旧内容
    tail = rest.split(end_mark, 1)[1]
    return pre + new_content + "\n" + end_mark + tail


def _git_commit_push_readme(date_str):
    """append_daily 写 README 后自动 commit + push main(2026-08-19 用户拍板方案①)。

    背景: 本脚本由 launchd(com.trade.token-cache-stats)每天 23:30 跑 --append-daily,
          追加 README 命中率走势。原设计"不推 git"导致 README 长期留未提交 M,
          污染工作区并卡死其他流程(如 main-merge.sh 全工作区 diff 误入 commit 分支)。
          用户确认: 追加完自动 commit + push main。绕开 main-merge.sh 统一入口
          (只动这一个文档文件、23:30 安全窗口跑, 走统一入口太重)。

    幂等: README 无实际变更(同日重复跑=更新不重复追加)时跳过 commit+push, 不制造空提交。

    push 失败(non-fast-forward)按 §8 处理: git fetch + rebase origin/main + 重试,
    不 force;rebase 失败/仍失败则打日志告警退出非 0, 绝不静默吞掉(§23.11)。
    全程 print 日志(launchd 写 stdout/err 文件), 不打印 key/token。
    """
    import subprocess
    git = ["git", "-C", TRADE_ROOT]

    # 1. README 是否真的变了(相对 HEAD, 覆盖工作区+暂存区);幂等无变更→跳过
    r = subprocess.run(git + ["diff", "--quiet", "--", README_REL],
                       cwd=TRADE_ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        print("README 无实际变更, 跳过 commit+push(幂等 %s)" % date_str)
        return

    # 2. add + commit
    subprocess.run(git + ["add", README_REL],
                   cwd=TRADE_ROOT, capture_output=True, text=True, check=True)
    msg = (
        "chore(命中率走势): %s 自动追加(token-cache-stats 每日收尾)\n\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>" % date_str
    )
    c = subprocess.run(git + ["commit", "-m", msg],
                       cwd=TRADE_ROOT, capture_output=True, text=True)
    if c.returncode != 0:
        print("✗ commit README 失败: %s" % (c.stderr or "").strip()[-500:], file=sys.stderr)
        sys.exit(1)
    commit_tail = (c.stdout or "").strip().splitlines()
    print("commit 完成: %s" % (commit_tail[-1] if commit_tail else c.returncode))

    # 3. push origin main(§8: non-ff 优先 fetch+rebase+重试, 不 force, 失败告警非 0 绝不静默)
    p = subprocess.run(git + ["push", "origin", "main"],
                       cwd=TRADE_ROOT, capture_output=True, text=True)
    if p.returncode == 0:
        print("push origin main 成功")
        return
    err_tail = (p.stderr or "").strip().splitlines()
    print("push origin main 失败(%s), 尝试 git fetch + rebase + 重试(§8 不 force)"
          % (err_tail[-1] if err_tail else p.returncode))
    subprocess.run(git + ["fetch", "origin"], cwd=TRADE_ROOT, capture_output=True, text=True)
    reb = subprocess.run(git + ["rebase", "origin/main"],
                         cwd=TRADE_ROOT, capture_output=True, text=True)
    if reb.returncode != 0:
        subprocess.run(git + ["rebase", "--abort"], cwd=TRADE_ROOT, capture_output=True, text=True)
        print("✗ rebase origin/main 失败, 已 abort。请人工处理(§23.11 绝不静默)", file=sys.stderr)
        print((reb.stderr or "").strip()[-500:], file=sys.stderr)
        sys.exit(1)
    p2 = subprocess.run(git + ["push", "origin", "main"],
                        cwd=TRADE_ROOT, capture_output=True, text=True)
    if p2.returncode != 0:
        print("✗ 重试 push origin main 仍失败, 绝不静默吞掉(§23.11): %s"
              % (p2.stderr or "").strip()[-500:], file=sys.stderr)
        sys.exit(1)
    print("push origin main 成功(经 rebase 重试)")


def append_daily(date_str, jsonl_dir):
    """追加/更新 date_str 当天命中率走势 + 版本/改动。幂等:同天重复跑=更新不重复追加。"""
    files = glob.glob(os.path.join(jsonl_dir, "*.jsonl"))
    if not files:
        print("no jsonl files in %s" % jsonl_dir)
        sys.exit(1)
    agg = {"cr": 0, "cc": 0, "inp": 0}
    for path in files:
        for day, cr, cc, inp in scan_stream(path):
            if day == date_str:
                agg["cr"] += cr
                agg["inp"] += inp
    denom = agg["cr"] + agg["inp"]
    hit = agg["cr"] / denom if denom else 0.0
    cold = agg["inp"]
    read = agg["cr"]

    claude_ver = _get_claude_version()
    changes = _get_day_changes(date_str)
    # 当日改动列:未空则 "hash 主题" 单行;多个用 "; " 连接;无则 "无"
    if changes:
        change_txt = "; ".join(c.split()[0] + " " + " ".join(c.split()[1:]) for c in changes)
    else:
        change_txt = "无"

    readme_path = os.path.join(TRADE_ROOT, README_REL)
    if not os.path.exists(readme_path):
        print("README not found: %s" % readme_path)
        sys.exit(1)
    with open(readme_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    # ---- 更新走势表 ----
    if TREND_MARK_START in content and TREND_MARK_END in content:
        block = content.split(TREND_MARK_START, 1)[1].split(TREND_MARK_END, 1)[0]
        ordered, rows = _split_trend_table(block)
    else:
        ordered, rows = [], {}
    hit_str = "%.4f" % hit if denom else "n/a"
    cold_str = "{:,}".format(cold)
    rows[date_str] = [date_str, hit_str, cold_str, claude_ver, change_txt]
    if date_str not in ordered:
        ordered.append(date_str)
    new_table = _render_trend_table(ordered, rows)
    content = _replace_block(content, TREND_MARK_START, TREND_MARK_END, new_table)

    # ---- 更新 ASCII 迷你柱状图 ----
    if ASCII_MARK_START in content and ASCII_MARK_END in content:
        new_ascii = _render_ascii(ordered, rows)
        content = _replace_block(content, ASCII_MARK_START, ASCII_MARK_END, new_ascii)

    # ---- 更新版本/改动日志 ----
    log_entry = "| %s | %s | %s |" % (date_str, claude_ver, change_txt if change_txt != "无" else "—")
    if CHANGELOG_MARK_START in content and CHANGELOG_MARK_END in content:
        log_block = content.split(CHANGELOG_MARK_START, 1)[1].split(CHANGELOG_MARK_END, 1)[0]
        lines = _split_changelog(log_block)
        # 幂等:若该日期已有一行则替换,否则追加
        existing = [i for i, ln in enumerate(lines) if ln.startswith("| %s " % date_str)]
        if existing:
            lines[existing[0]] = log_entry
        else:
            lines.append(log_entry)
        new_log = "\n".join(lines)
        content = _replace_block(content, CHANGELOG_MARK_START, CHANGELOG_MARK_END, new_log)

    with open(readme_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(
        "appended %s: hit=%.4f cache_read=%s input=%s claude=%s changes=%s"
        % (date_str, hit, read, cold, claude_ver, change_txt)
    )

    # 2026-08-19 用户拍板方案①: 追加完自动 commit + push main(绕开 main-merge.sh 统一入口,
    # 只动这一个文档文件、每天 23:30 安全窗口跑)。幂等无变更时跳过, 不制造空提交。
    _git_commit_push_readme(date_str)


def main():
    # 每日追加走势模式(--append-daily [date]，默认今天)
    if len(sys.argv) >= 2 and sys.argv[1] == "--append-daily":
        date_str = sys.argv[2] if len(sys.argv) >= 3 else datetime.now().strftime("%Y-%m-%d")
        jdir = sys.argv[3] if len(sys.argv) >= 4 else os.path.expanduser(
            "~/.claude/projects/-Users-linhuichen-code-trade"
        )
        append_daily(date_str, jdir)
        return

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
