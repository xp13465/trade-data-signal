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
     2026-09-19 起加「配置快照」维度:
       - 走势表从 5 列扩到 7 列(新增「模型/端点」「思考%」),历史行缺列自动补 "—" 并回填
       - 新增「配置快照日志」区块(日期|模型|端点|思考%|effort|来源)
       - 每天落盘去敏配置快照 claude-work-mode/config-snapshots/YYYY-MM-DD.json
         (只存 BASE_URL/MODEL/SUBAGENT 三字段,绝不落 token,防 GitHub Push Protection 拦)
       - 模型 = JSONL message.model 按当天 input token 加权取 top1;
         思考% = 当天 thinking 块字符占比折算 token 后加权(output_tokens 为权重,与命中率口径对齐);
         端点 = 历史查一次性时段表(ENDPOINT_TABLE),当天实时抓 settings.json + 代理进程 env + launchd label。
     追加成功后自动收尾: git add/commit + push origin main(2026-08-19 用户拍板方案①,
     绕开 main-merge.sh 统一入口,只动这一个文档文件、23:30 安全窗口跑)。
     幂等无实际变更时跳过 commit+push;push non-ff 自动 fetch+rebase+重试,不 force,
     rebase 冲突 abort + 告警退出非 0(§8/§23.11)。
     验证/演练用 dry 模式: env TOKEN_CACHE_STATS_DRY=1 时写 README+快照但不 commit+push。

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_atomic import atomic_write_json  # noqa: E402  (原子写公共模块, 2026-09-22 非 kelly 链路统一)


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
# 配置快照日志区块标记(2026-09-19 新增: 日期|模型|端点|思考%|effort|来源)
CFGLOG_MARK_START = "<!-- token-cache-cfglog-begin -->"
CFGLOG_MARK_END = "<!-- token-cache-cfglog-end -->"
# 配置快照落盘目录(相对 trade 仓库根,去敏)
CONFIG_SNAPSHOT_REL = "claude-work-mode/config-snapshots"
# ASCII 迷你柱状图区块标记
ASCII_MARK_START = "<!-- token-cache-ascii-begin -->"
ASCII_MARK_END = "<!-- token-cache-ascii-end -->"
# ASCII 图刻度:每格 = 0.01 命中率,下限 0.70~1.00
ASCII_MIN = 0.70
ASCII_PER = 0.01
# trade 仓库根(用于查当日 claude-work-mode/CLAUDE.md 改动)
# 支持 TRADE_REPO_ROOT 环境变量覆盖(worktree/演练用),默认主仓库(定时任务行为不变)
TRADE_ROOT = os.environ.get("TRADE_REPO_ROOT", "/Users/linhuichen/code/trade")

# 端点时段表(历史一次性硬编码,2026-09-19 researcher 查证;未来端点切换由每日快照自动跟随)
# 过渡日多端点并存(08-19 上午方舟/10:39 后官方;09-01 前半 openrouter/01:55 后商汤)→ 标「混合」不强行单值
# 09-12~09-17 pro-0813 端点存疑(settings mtime 09-17 22:24 ≠ JSONL 09-12 就 pro 主导)→ 标「待确认」不硬填
ENDPOINT_TABLE = [
    ("2026-08-18", "2026-08-18", "方舟plan"),
    ("2026-08-19", "2026-08-19", "官方直连(混合)"),
    ("2026-08-20", "2026-08-20", "官方直连"),
    ("2026-08-21", "2026-08-30", "opencode"),
    ("2026-08-31", "2026-08-31", "openrouter直连"),
    ("2026-09-01", "2026-09-01", "商汤rotate(混合)"),
    ("2026-09-02", "2026-09-12", "商汤rotate"),
    ("2026-09-13", "2026-09-17", "待确认"),
    ("2026-09-18", "9999-12-31", "8899·商汤rotate"),
]


# ---------------------------------------------------------------------------
# 配置快照维度(2026-09-19 新增): model/思考%聚合 + 端点时段表 + 当天实时抓取 + 去敏快照
# ---------------------------------------------------------------------------

def _scan_rich(path):
    """流式读单文件,产出 (day, cr, cc, inp, out, model, think_chars, text_chars)。

    在现有 grep '"usage"' 快筛基础上,对 assistant 行额外解析 message.model
    与 content 里的 thinking/text 块(块无 token 数,用字符长度累加,
    思考% 由 _aggregate_days/_think_pct 按天求和聚合后算比)。
    """
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
            if cr == 0 and cc == 0 and inp == 0:
                continue
            m = obj.get("message") or {}
            usage = m.get("usage") if isinstance(m, dict) else None
            out = (usage or {}).get("output_tokens") or 0
            model = m.get("model") if isinstance(m, dict) else None
            if not isinstance(model, str):
                model = "?"
            think_chars = 0
            text_chars = 0
            content = m.get("content") if isinstance(m, dict) else None
            if isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    t = blk.get("type")
                    if t == "thinking":
                        think_chars += len(blk.get("thinking") or "")
                    elif t == "text":
                        text_chars += len(blk.get("text") or "")
            yield day, cr, cc, inp, int(out), model, think_chars, text_chars


def _aggregate_days(jsonl_dir):
    """全量扫描所有 JSONL,按天聚合 usage + model top1(input token 加权) + 思考字符。

    返回 {date: {cr, inp, cc, out, think_chars, text_chars, model_tok: {model: inp_tok}, n}}。
    思考% 由 _think_pct(think_chars, text_chars) 按天求和聚合后算比。
    """
    agg = defaultdict(lambda: {"cr": 0, "cc": 0, "inp": 0, "out": 0,
                               "think_chars": 0, "text_chars": 0, "n": 0,
                               "model_tok": defaultdict(int)})
    files = glob.glob(os.path.join(jsonl_dir, "*.jsonl"))
    for path in files:
        for day, cr, cc, inp, out, model, tc, xc in _scan_rich(path):
            g = agg[day]
            g["cr"] += cr
            g["cc"] += cc
            g["inp"] += inp
            g["out"] += out
            g["n"] += 1
            g["think_chars"] += tc
            g["text_chars"] += xc
            g["model_tok"][model] += inp
    return dict(agg)


def _short_model(m):
    """模型短名:去 provider 前缀(deepseek/ stealth/ 等)、去 :free 后缀、去 deepseek-v4- 前缀。"""
    if "/" in m:
        m = m.rsplit("/", 1)[-1]
    m = m.split(":", 1)[0]
    if m.startswith("deepseek-v4-"):
        m = m[len("deepseek-v4-"):]
    return m


def _model_top1(model_tok):
    """按 input token 加权取 top1 模型;空返回 "?"。"""
    if not model_tok:
        return "?"
    return max(model_tok.items(), key=lambda kv: kv[1])[0]


def _think_pct(think_chars, text_chars):
    """思考% = 思考字符 / (思考字符 + 文本字符),按天求和聚合后算比,整数百分数。

    口径与命中率同构(先求和再算比);JSONL 的 usage 无 thinking token 数字
    (output_tokens_details.thinking_tokens 恒 0,不可靠),故用 content 里
    thinking/text 块字符长度近似 token 占比。无内容返回 None。
    """
    total = think_chars + text_chars
    if total <= 0:
        return None
    return 100.0 * think_chars / total


def _lookup_endpoint(date_str):
    """查时段表返回历史端点标签;表外返回 None。"""
    for lo, hi, ep in ENDPOINT_TABLE:
        if lo <= date_str <= hi:
            return ep
    return None


def _live_config():
    """实时抓当前端点配置(去敏)。

    读 ~/.claude/settings.json 的 ANTHROPIC_BASE_URL/ANTHROPIC_MODEL/CLAUDE_CODE_SUBAGENT_MODEL,
    按 BASE_URL 端口查监听进程(ps/lsof)识别代理类型(商汤rotate/ttp-测试等)。
    返回 dict 只含非敏感字段,绝不含 token。
    """
    import subprocess
    import re
    base_url = ""
    model = ""
    subagent = ""
    settings_path = os.path.expanduser("~/.claude/settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as fh:
                s = json.load(fh)
            env = s.get("env") or {}
            base_url = env.get("ANTHROPIC_BASE_URL", "") or ""
            model = env.get("ANTHROPIC_MODEL", "") or ""
            subagent = env.get("CLAUDE_CODE_SUBAGENT_MODEL", "") or ""
        except Exception:
            pass
    proxy_label = ""
    m = re.search(r":(\d+)\s*$", base_url)
    port = m.group(1) if m else ""
    if port:
        try:
            out = subprocess.run(
                ["lsof", "-nP", "-iTCP:%s" % port, "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=10).stdout
            for ln in out.splitlines():
                parts = ln.split()
                if len(parts) < 2 or not parts[1].isdigit():
                    continue  # 跳过 lsof 头部行(COMMAND PID...)等非数字 pid 行
                pid = parts[1]
                pout = subprocess.run(
                    ["ps", "-o", "command=", "-p", pid],
                    capture_output=True, text=True, timeout=5).stdout
                cmd = (pout or "").strip()
                if "sensenova-rotate-proxy.py" in cmd:
                    proxy_label = "商汤rotate"
                elif "ttp-" in cmd:
                    proxy_label = "ttp-测试"
                elif cmd:
                    proxy_label = "本地代理"
                break
        except Exception:
            pass
    endpoint = "?"
    if proxy_label:
        endpoint = "%s·%s" % (port, proxy_label)
    elif base_url:
        if "api.deepseek.com" in base_url:
            endpoint = "官方直连"
        elif "openrouter" in base_url:
            endpoint = "openrouter直连"
        elif "api.volces.com" in base_url or "ark" in base_url.lower():
            endpoint = "方舟"
        else:
            endpoint = "host未知"
    effort_bits = []
    if model:
        effort_bits.append("主%s" % _short_model(model))
    if subagent:
        effort_bits.append("子%s" % _short_model(subagent))
    effort_bits.append("按角色(impl low/rev·tst·res max)")
    return {
        "base_url": base_url,
        "model": model,
        "subagent": subagent,
        "endpoint": endpoint,
        "effort": " ".join(effort_bits),
    }


def _write_config_snapshot(date_str):
    """落盘去敏配置快照 claude-work-mode/config-snapshots/YYYY-MM-DD.json。

    只写 BASE_URL/MODEL/SUBAGENT 三字段,绝不落 token(settings 有明文 sk- 会被
    GitHub Push Protection 拦,故只取白名单字段)。
    """
    live = _live_config()
    snap = {
        "date": date_str,
        "model": live["model"] or "—",
        "subagent_model": live["subagent"] or "—",
        "base_url": live["base_url"] or "—",
        "_note": "去敏快照,只含端点三字段;不落 token(防 GitHub Push Protection)",
    }
    snap_dir = os.path.join(TRADE_ROOT, CONFIG_SNAPSHOT_REL)
    try:
        os.makedirs(snap_dir, exist_ok=True)
    except OSError as e:
        print("warn: 创建快照目录失败 %s: %s" % (snap_dir, e), file=sys.stderr)
        return
    path = os.path.join(snap_dir, "%s.json" % date_str)
    atomic_write_json(path, snap, indent=2)
    print("配置快照已落盘: %s (仅端点三字段,无 token)" % path)


def _get_day_config(date_str, agg_day, is_today):
    """返回某天配置信息 dict:
       model / endpoint / think_pct / effort / source / model_endpoint
       历史: model+思考 来自 JSONL 聚合,端点查时段表, effort="—", source="时段表";
       当天: 端点/effort 实时抓(settings+代理+launchd), source="实时抓取"。
       agg_day 为 None 或空 → model/思考 "—"。
    """
    model = "—"
    think_pct = "—"
    endpoint = "—"
    effort = "—"
    source = "—"
    if agg_day:
        mt = agg_day.get("model_tok") or {}
        if mt:
            model = _short_model(_model_top1(mt))
        pct = _think_pct(agg_day.get("think_chars", 0), agg_day.get("text_chars", 0))
        if pct is not None:
            think_pct = "%d%%" % round(pct)
    if is_today:
        live = _live_config()
        endpoint = live["endpoint"]
        effort = live["effort"]
        source = "实时抓取"
    else:
        ep = _lookup_endpoint(date_str)
        if ep:
            endpoint = ep
            source = "时段表"
    if model != "—" and endpoint != "—":
        model_endpoint = "%s·%s" % (model, endpoint)
    elif model != "—":
        model_endpoint = model
    elif endpoint != "—":
        model_endpoint = endpoint
    else:
        model_endpoint = "—"
    return {
        "model": model, "endpoint": endpoint, "think_pct": think_pct,
        "effort": effort, "source": source, "model_endpoint": model_endpoint,
    }


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
    """从走势区块原文解析 {date: [date, hit, cold_inp, model_ep, think_pct, claude_ver, changes]}。

    走势表列(7 列): 日期 | 命中率 | 冷读input | 模型/端点 | 思考% | claude版本 | 当日改动
    兼容旧 5 列行(2026-09-19 前的旧表): model_ep/think_pct 补 "—"。
    返回 (ordered_dates, rows)。
    """
    rows = {}
    ordered = []
    for ln in block.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        # 跳过表头行与分隔行(-- 开头的 markdown 分隔)
        if len(cells) < 5:
            continue
        if cells[0].startswith("日期") or cells[0].startswith("---"):
            continue
        date = cells[0]
        if len(cells) >= 7:
            rows[date] = cells[:7]
        else:
            # 旧 5 列: [date, hit, cold_inp, claude_ver, changes]
            rows[date] = [cells[0], cells[1], cells[2], "—", "—", cells[3], cells[4]]
        ordered.append(date)
    return ordered, rows


def _render_trend_table(ordered, rows):
    """渲染走势表 markdown: 表头+分隔行+按日期升序的数据行(7 列)。"""
    out = []
    out.append("| 日期 | 命中率 | 冷读input | 模型/端点 | 思考% | claude版本 | 当日改动 |")
    out.append("|---|---|---|---|---|---|---|")
    for date in sorted(ordered):
        r = rows[date]
        out.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (r[0], r[1], r[2], r[3], r[4], r[5], r[6])
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


def _render_cfglog(ordered, agg, today_str):
    """渲染配置快照日志区块: 日期|模型|端点|思考%|effort|来源。

    只列出有配置来源的日期(历史=时段表+JSONL,当天=实时抓取);无配置(如 08-10~08-17 源已丢)跳过。
    """
    out = ["| 日期 | 模型 | 端点 | 思考% | effort | 来源 |", "|---|---|---|---|---|---|"]
    for date in sorted(ordered):
        is_today = (date == today_str)
        cfg = _get_day_config(date, agg.get(date), is_today)
        if cfg["source"] == "—":
            continue
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            date, cfg["model"], cfg["endpoint"], cfg["think_pct"],
            cfg["effort"], cfg["source"]))
    return "\n".join(out)


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

    幂等: README + 当天快照 整体无实际变更(同日重复跑=更新不重复追加)时跳过 commit+push,
    不制造空提交。快照文件与 README 同 commit 进 git(防快照 untracked 污染工作区,
    与 2026-08-19「README 未提交 M 污染工作区」同病复发)。

    push 失败(non-fast-forward)按 §8 处理: git fetch + rebase origin/main + 重试,
    不 force;rebase 失败/仍失败则打日志告警退出非 0, 绝不静默吞掉(§23.11)。
    全程 print 日志(launchd 写 stdout/err 文件), 不打印 key/token。
    """
    import subprocess
    git = ["git", "-C", TRADE_ROOT]

    # 1. add README + 当天快照(精确路径, 不 add 整个 config-snapshots/ 目录, 防未来误含敏感文件)
    subprocess.run(git + ["add", README_REL],
                   cwd=TRADE_ROOT, capture_output=True, text=True, check=True)
    snapshot_rel = os.path.join(CONFIG_SNAPSHOT_REL, "%s.json" % date_str)
    snap_path = os.path.join(TRADE_ROOT, snapshot_rel)
    if os.path.exists(snap_path):
        subprocess.run(git + ["add", snapshot_rel],
                       cwd=TRADE_ROOT, capture_output=True, text=True, check=True)
    else:
        print("warn: 当天快照不存在 %s, 仅提交 README" % snap_path, file=sys.stderr)

    # 2. 幂等无变更(README + 当天快照 整体无 staged 变更)→跳过 commit
    r = subprocess.run(git + ["diff", "--cached", "--quiet", "--", README_REL, snapshot_rel],
                       cwd=TRADE_ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        print("README+快照 无实际变更, 跳过 commit+push(幂等 %s)" % date_str)
        return

    # 3. commit
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

    # 4. push origin main(§8: non-ff 优先 fetch+rebase+重试, 不 force, 失败告警非 0 绝不静默)
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
    """追加/更新 date_str 当天命中率走势 + 版本/改动 + 配置快照维度。幂等:同天重复跑=更新不重复追加。

    2026-09-19 起: 一次全量聚合(_aggregate_days),当天行填实时配置,
    历史已有行回填 model/思考%(JSONL 聚合)+ 端点(时段表);新增「配置快照日志」区块。
    dry 验证: env TOKEN_CACHE_STATS_DRY=1 时写 README+快照但不 commit+push(供演练/验收)。
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    is_today = (date_str == today_str)
    dry = (os.environ.get("TOKEN_CACHE_STATS_DRY") == "1")

    files = glob.glob(os.path.join(jsonl_dir, "*.jsonl"))
    if not files:
        print("no jsonl files in %s" % jsonl_dir)
        sys.exit(1)
    agg = _aggregate_days(jsonl_dir)
    t = agg.get(date_str)
    cr = t["cr"] if t else 0
    inp = t["inp"] if t else 0
    denom = cr + inp
    hit = cr / denom if denom else 0.0
    cold = inp
    read = cr

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

    # ---- 更新走势表(7 列) ----
    if TREND_MARK_START in content and TREND_MARK_END in content:
        block = content.split(TREND_MARK_START, 1)[1].split(TREND_MARK_END, 1)[0]
        ordered, rows = _split_trend_table(block)
    else:
        ordered, rows = [], {}
    hit_str = "%.4f" % hit if denom else "n/a"
    cold_str = "{:,}".format(cold)
    # 当天行: 配置实时抓; claude_ver/改动 实抓
    today_cfg = _get_day_config(date_str, t, is_today)
    rows[date_str] = [date_str, hit_str, cold_str,
                      today_cfg["model_endpoint"], today_cfg["think_pct"],
                      claude_ver, change_txt]
    if date_str not in ordered:
        ordered.append(date_str)
    # 历史行回填 model/端点/思考%(幂等: 已有值也覆盖, 数据源一致)
    for d in list(ordered):
        r = rows[d]
        dcfg = _get_day_config(d, agg.get(d), (d == today_str))
        r[3] = dcfg["model_endpoint"]
        r[4] = dcfg["think_pct"]
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

    # ---- 更新配置快照日志区块(2026-09-19 新增) ----
    if CFGLOG_MARK_START in content and CFGLOG_MARK_END in content:
        new_cfglog = _render_cfglog(ordered, agg, today_str)
        content = _replace_block(content, CFGLOG_MARK_START, CFGLOG_MARK_END, new_cfglog)

    # ---- 当天落盘去敏配置快照(非 dry 或 dry 都写, 供验收检查无 token) ----
    if is_today:
        _write_config_snapshot(date_str)

    with open(readme_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(
        "appended %s: hit=%.4f cache_read=%s input=%s claude=%s changes=%s model_ep=%s think=%s"
        % (date_str, hit, read, cold, claude_ver, change_txt,
           today_cfg["model_endpoint"], today_cfg["think_pct"])
    )

    if dry:
        print("DRY 模式(TOKEN_CACHE_STATS_DRY=1): README+快照已写,跳过 commit+push。")
        return

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
