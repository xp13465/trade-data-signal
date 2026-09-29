#!/usr/bin/env python3
"""PostToolUse(Agent) hook:读实际调用参数逐项机检「派单三件套」。

背景(2026-09-29):主控派 implementer 反复漏传 isolation="worktree"(2026-09-24、
2026-09-29 两次同型),导致 agent 在主工作目录 git checkout feat 分支、污染主仓
HEAD、main-merge 被拒。memory 记两次但无效——机械动作必须机检,不能靠记忆。

行为:stdin 收 hook JSON;只对 tool_name==Agent 且 tool_input 为有内容的 dict 机检
4 项(字段经 docs/thinking-off-optimization.md:64 确认 AgentInput schema):
  ① 进度文件:prompt 是否含 /tmp/agent-progress-
  ② 后台派单:run_in_background is True
  ③ worktree 隔离:subagent_type==implementer 要求 isolation=="worktree";
     只读角色(reviewer/researcher/tester)不作隔离硬要求
  ④ 巡检兜底:.claude/scheduled_tasks.json 存在 15min 档(cron=="3,18,33,48 * * * *")
     或 prompt 含「巡检/兜底」关键词的 job,命中报出 job id

输出规则:只输出未通过项(每项带实际观测值);全部通过 → 静默 exit 0(让 hook
输出=真问题信号,不再是每轮噪音);有未通过项 → stderr + exit 2(保持现状语义:
stderr 注入模型上下文,不阻塞已完成派单);非 Agent 工具 / JSON 解析失败 /
tool_input 缺失或为空 dict → 静默 exit 0。
⚠️ 真实 hook JSON 形态未完全已知,脚本绝不因字段缺失抛异常:全部 .get() 兜底 +
类型容错(prompt 可能非 str、tool_input 可能非 dict、字段可能缺失)。
"""
import sys
import json
import datetime

# 巡检兜底 cron 清单的权威来源(.claude/scheduled_tasks.json),主仓绝对路径。
SCHEDULED_TASKS_PATH = "/Users/linhuichen/code/trade/.claude/scheduled_tasks.json"
WATCHDOG_CRON_15MIN = "3,18,33,48 * * * *"
WATCHDOG_KEYWORDS = ("巡检", "兜底")
PROGRESS_FILE_MARKER = "/tmp/agent-progress-"
# ④ 落盘摘要日志:把静默失效变成可诊断(模型侧零噪音,文件可反查)。
DISPATCH_LOG_PATH = "/tmp/agent-hook-dispatch.log"
PROMPT_PREVIEW_MAX = 120  # ③ prompt 回显截断长度,防超大 prompt 全文灌进上下文


def _prompt_preview(prompt):
    """prompt 预览:前 120 字符,超长截断加省略号;非 str 显示 repr 前段。"""
    if not isinstance(prompt, str):
        return repr(prompt)[:PROMPT_PREVIEW_MAX]
    if len(prompt) <= PROMPT_PREVIEW_MAX:
        return prompt
    return prompt[:PROMPT_PREVIEW_MAX] + "…"


def _append_dispatch_log(tool_name, tool_input_ok, fails):
    """④ append 一行派单摘要到 /tmp/agent-hook-dispatch.log。

    硬要求:文件不存在要能创建(append 模式自动建);写日志本身 try/except 吞掉
    异常(目录不可写/磁盘满)绝不因日志让 hook 崩掉。
    """
    try:
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        line = "<%s> tool=%r tool_input=%s fails=%s\n" % (ts, tool_name, tool_input_ok, fails)
        with open(DISPATCH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def find_watchdog_job():
    """返回 (job_id_or_None, err_or_None)。cron 命中 15 分钟档或 prompt 含关键词即判命中。

    已知局限(2026-09-29):本判据是「.claude/scheduled_tasks.json 里存在*任意*巡检 job」,
    而非「*本 agent* 被兜底覆盖」→
      假阳性:任意遗留/他人 job 命中 15min 档或关键词即判通过;
      反向假阴性:cron 格式若写成 `*/15 * * * *`(精确串匹配全失)会漏判。
    作为提醒钩子可接受,仅作「最坏有没有兜底」的下限信号,不作「本 agent 已被覆盖」的证明。
    """
    try:
        with open(SCHEDULED_TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # 文件不存在/坏 JSON → 视为无兜底,不抛异常
        return None, "读取失败: %s" % e
    # 兼容两形态:①{"tasks":[{job}...]} ②{id:{job}} 或 {<任意key>:{job}}(直接遍历 values)
    candidates = []
    if isinstance(data, dict):
        if isinstance(data.get("tasks"), list):
            candidates.extend(data["tasks"])
        for v in data.values():
            if isinstance(v, dict) and "cron" in v:
                candidates.append(v)
    for t in candidates:
        if not isinstance(t, dict):
            continue
        cron = t.get("cron")
        prompt = t.get("prompt")
        if cron == WATCHDOG_CRON_15MIN:
            return t.get("id"), None
        if isinstance(prompt, str) and any(kw in prompt for kw in WATCHDOG_KEYWORDS):
            return t.get("id"), None
    return None, None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        _append_dispatch_log("bad-json", "no", "-")
        return 0
    # ① 顶层非 dict JSON(数组/字符串/null 等)无 tool_name 可查,静默放行不抛异常
    if not isinstance(data, dict):
        _append_dispatch_log("non-dict", "no", "-")
        return 0
    tool_name = data.get("tool_name")
    if tool_name != "Agent":
        _append_dispatch_log(tool_name, "no", "-")
        return 0
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict) or not tool_input:
        # tool_input 缺失 / 非 dict / 空 dict = 无实际参数可查,静默放行
        _append_dispatch_log("Agent", "no", "-")
        return 0

    subagent_type = tool_input.get("subagent_type")
    isolation = tool_input.get("isolation")
    run_in_background = tool_input.get("run_in_background")
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        prompt = None  # 类型容错:非 str 一律视为缺失

    is_implementer = isinstance(subagent_type, str) and subagent_type.lower() == "implementer"
    problems = []
    fails = ""
    watchdog_id, watchdog_err = None, None

    # ① 进度文件
    if prompt is None or PROGRESS_FILE_MARKER not in prompt:
        problems.append(
            "① 进度文件缺失:prompt 未含 %s 路径(观测 prompt 前 %d 字符=%s)"
            % (PROGRESS_FILE_MARKER, PROMPT_PREVIEW_MAX, _prompt_preview(prompt))
        )
    # ② 后台派单
    if run_in_background is not True:
        problems.append(
            "② 后台派单缺失:未显式传 run_in_background=true(观测 run_in_background=%r)"
            % (run_in_background,)
        )
    # ③ worktree 隔离(仅 implementer 硬要求)
    if is_implementer:
        if isolation != "worktree":
            problems.append(
                "③ worktree 隔离缺失:subagent_type=implementer 但 isolation=%r(需 'worktree')"
                % (isolation,)
            )
    # ④ 巡检兜底
    watchdog_id, watchdog_err = find_watchdog_job()
    if watchdog_id is None:
        problems.append(
            "④ 巡检兜底缺失:%s 无 15min 档(%s)或 prompt 含 %r 的 job(%s)"
            % (SCHEDULED_TASKS_PATH, WATCHDOG_CRON_15MIN, WATCHDOG_KEYWORDS, watchdog_err or "未找到")
        )

    if problems:
        fails = "".join(p.split(" ", 1)[0] for p in problems)  # 收集失败项编号,如 ①②③
        lines = ["[派单三件套机检·§11] 以下项未通过(带实际观测值,缺哪件现在补,别裸派):"]
        for p in problems:
            lines.append("  - " + p)
        if watchdog_id:
            lines.append("  ✓ 巡检兜底已在: id=%s(该项通过)" % watchdog_id)
        if not is_implementer:
            lines.append(
                "  〔只读/其它 agent %r〕未强制 worktree 隔离,运行期间主控禁止 checkout/merge"
                "(会把该 agent 工作树拉走)" % (subagent_type,)
            )
        print("\n".join(lines), file=sys.stderr)
        _append_dispatch_log("Agent", "yes", fails)
        return 2

    # 全部 4 项通过 → 静默 exit 0,不制造噪音。
    # 注:只读角色隔离非硬要求;此处不再输出任何 stderr(exit 0 时 stderr 只进
    # debug log,模型永远看不到,输出=白写,故全部删除)。
    _append_dispatch_log("Agent", "yes", "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())
