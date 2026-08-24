#!/usr/bin/env python3
"""PostToolUse(Agent) hook:子 agent 派出后机械提醒主控补齐「派单三件套」。

背景(2026-08-25 L01 二次复发根治):compact 后主控裸派 3 个 agent 零巡检兜底,
#11 researcher 死亡半天无人发现。规范全文在 docs/main-governance.md §11,
但该文件按需读、compact 后不注入——靠记忆必失效,故用 hook 机械强制。

行为:stdin 收 hook JSON;若 tool_name==Agent 则 stderr 输出一行自查提醒并
以 exit 2 结束(exit 2 = PostToolUse 将 stderr 作为 feedback 注入模型上下文,
不阻塞已完成的派单)。其他工具静默放行。
"""
import sys
import json


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Agent":
        return 0
    msg = (
        "[派单三件套自查·§11] agent 已派出,立即核对:①prompt 是否写了进度文件"
        "/tmp/agent-progress-<名>.md 并要求每步 echo;②巡检兜底 cron 是否已存在且覆盖本 agent"
        "(CronList 查,无则 CronCreate 15min 档+durable+门控零输出;全部完成后再 CronDelete);"
        "③并发 implementer 是否 worktree 隔离。通知送达不可靠是架构事实,"
        "cron 兜底是唯一可靠残余——缺哪件现在补,别裸派。"
    )
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
