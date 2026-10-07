#!/usr/bin/env python3
"""PostToolUse(Agent) hook:读实际调用参数机检「派单三件套·可机检项」。

背景(2026-09-29):主控派 implementer 反复漏传 isolation="worktree"(2026-09-24、
2026-09-29 两次同型),导致 agent 在主工作目录 git checkout feat 分支、污染主仓
HEAD、main-merge 被拒。memory 记两次但无效——机械动作必须机检,不能靠记忆。

⚠️ 为什么是这三项(2026-09-29 线上实测把三件套收敛为两项 + 2026-10-07 增第三项,
改/删前必读):
三件套(后台派单/进度文件/巡检兜底)原本都在本 hook 机检,实测证明其中两项
「结构性不可机检」,已移除:
  - 后台派单(run_in_background):真实 hook 的 tool_input 不转发该字段——线上实测
    tool_input 含 subagent_type/isolation/prompt(所以这两项判得对),但永远没有
    run_in_background 键。⇒ 该项在此环境恒报失败,每次派单都刷「② 后台派单缺失」,
    把「全过静默」的信号价值彻底毁掉。
  - 巡检兜底(cron):主控常规流程=「派 agent + 建巡检 cron」放同一条消息,而 hook
    在 Agent 调用那一刻读 .claude/scheduled_tasks.json——那时 cron 必然还没写入
    ⇒ 恒假报;反过来,文件里存在*任意*历史遗留巡检 job 时又恒绿(已用遗留 job 实测),
    无法判断「*本 agent* 有没有被兜底」。两头都不成立。

因此本 hook 机检三项(① 进度文件 / ② worktree 隔离 / ③ timeout 约束),均为参数直给、
可确定性判定的项。「后台派单」「巡检兜底」仍是派单时必守的人工纪律(CLAUDE.md §0.2
照旧要求),只是不由本 hook 机检。看到只检这几项不要以为漏了、擅自加回——「为什么删」见上。

行为:stdin 收 hook JSON;只对 tool_name==Agent 且 tool_input 为有内容的 dict 机检
3 项(field 存在性经 docs/thinking-off-optimization.md:64 的 AgentInput schema 确认;
run_in_background 名义上在 schema 内但平台不转发,已不依赖):
  ① 进度文件:prompt 是否含 /tmp/agent-progress-
  ② worktree 隔离:subagent_type==implementer 要求 isolation=="worktree";
     只读角色(reviewer/researcher/tester)不作隔离硬要求
  ③ 命令超时约束(2026-10-07 新增):prompt 是否含 timeout 标记(判
     "timeout" not in prompt.lower())。对**所有** subagent_type 生效(与 ① 一致,不只
     implementer)。理由同 ①——prompt 是平台转发的直给字段,确定性可判。根因=子 agent
     的 Bash 超 120s 被 harness 自动转后台成 live child ⇒ agent 交完报告仍被停放、UI
     长期显示「卡住」(僵尸;24 例涉 1874 次 Bash 仅 7.4% 显式传 timeout)。
     ⚠️ **诚实标注本项局限**:只保证「派单方写了 timeout 要求」,**不保证**子 agent 真在
     每条命令上传了 timeout——那是子 agent 侧的执行纪律,本 hook 只读派单 prompt,看不到
     其实际 Bash 调用参数。`禁 find /`、`禁裸跑 pip/npm` 等同属子 agent 执行层约束,
     同样不可机检,仍是人工纪律。

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

PROGRESS_FILE_MARKER = "/tmp/agent-progress-"
# ③ 命令超时约束标记(2026-10-07):prompt 需含该子串(大小写不敏感),防子 agent Bash
# 超 120s 被 harness 自动转后台成僵尸。默认实现=判 "timeout" 是否出现在 prompt 里。
TIMEOUT_MARKER = "timeout"
# 落盘摘要日志:把静默失效变成可诊断(模型侧零噪音,文件可反查)。
DISPATCH_LOG_PATH = "/tmp/agent-hook-dispatch.log"
PROMPT_PREVIEW_MAX = 120  # prompt 回显截断长度,防超大 prompt 全文灌进上下文


def _prompt_preview(prompt):
    """prompt 预览:前 120 字符,超长截断加省略号;非 str 显示 repr 前段。"""
    if not isinstance(prompt, str):
        return repr(prompt)[:PROMPT_PREVIEW_MAX]
    if len(prompt) <= PROMPT_PREVIEW_MAX:
        return prompt
    return prompt[:PROMPT_PREVIEW_MAX] + "…"


def _append_dispatch_log(tool_name, tool_input_ok, fails):
    """append 一行派单摘要到 /tmp/agent-hook-dispatch.log。

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


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        _append_dispatch_log("bad-json", "no", "-")
        return 0
    # 顶层非 dict JSON(数组/字符串/null 等)无 tool_name 可查,静默放行不抛异常
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
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        prompt = None  # 类型容错:非 str 一律视为缺失

    is_implementer = isinstance(subagent_type, str) and subagent_type.lower() == "implementer"
    problems = []
    fails = ""

    # ① 进度文件
    if prompt is None or PROGRESS_FILE_MARKER not in prompt:
        problems.append(
            "① 进度文件缺失:prompt 未含 %s 路径(观测 prompt 前 %d 字符=%s)"
            % (PROGRESS_FILE_MARKER, PROMPT_PREVIEW_MAX, _prompt_preview(prompt))
        )
    # ② worktree 隔离(仅 implementer 硬要求)
    if is_implementer:
        if isolation != "worktree":
            problems.append(
                "② worktree 隔离缺失:subagent_type=implementer 但 isolation=%r(需 'worktree')"
                % (isolation,)
            )
    # ③ 命令超时约束(所有 subagent_type 生效,与 ① 一致;判 prompt 含 timeout 标记)
    if prompt is None or TIMEOUT_MARKER not in prompt.lower():
        problems.append(
            "③ 命令超时约束缺失:prompt 未含 %r 要求(观测 prompt 前 %d 字符=%s)"
            % (TIMEOUT_MARKER, PROMPT_PREVIEW_MAX, _prompt_preview(prompt))
        )

    if problems:
        fails = "".join(p.split(" ", 1)[0] for p in problems)  # 收集失败项编号,如 ①②③
        lines = ["[派单机检·§0.2] 以下项未通过(带实际观测值,缺哪件现在补,别裸派):"]
        for p in problems:
            lines.append("  - " + p)
        if not is_implementer:
            lines.append(
                "  〔只读/其它 agent %r〕未强制 worktree 隔离,运行期间主控禁止 checkout/merge"
                "(会把该 agent 工作树拉走)" % (subagent_type,)
            )
        print("\n".join(lines), file=sys.stderr)
        _append_dispatch_log("Agent", "yes", fails)
        return 2

    # 全部 3 项通过 → 静默 exit 0,不制造噪音。
    # 注:只读角色隔离非硬要求;此处不再输出任何 stderr(exit 0 时 stderr 只进
    # debug log,模型永远看不到,输出=白写,故全部删除)。
    _append_dispatch_log("Agent", "yes", "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())