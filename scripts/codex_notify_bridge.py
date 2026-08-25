#!/usr/bin/env python3
"""codex notify 桥接:codex turn 完成时推送飞书 + 落 .done 信号文件。

目的(2026-08-26 用户拍板):codex 作为外部 reviewer 完成 review 后,不再靠主会话
cron 轮询 /tmp/codex-reports/(平均延迟 7-8 分钟),而是 codex 一收工就主动推:
  ①飞书 agent_done 群(秒级可达用户手机,复用 scripts/notify.py 现成通道)
  ②落 /tmp/codex-reports/<thread>.done 信号文件(主会话巡检 cron 扫到即读报告,
    从"盲轮询"升级为"信号触发",cron 退化纯兜底)

协议(codex config.toml: notify = ["python3", "<此脚本路径>"]):
codex 每次 turn 结束把 JSON 当最后一个 argv 参数调本程序:
  {"type":"agent-turn-complete","thread_id":"...","turn_id":"...",
   "cwd":"...","input_messages":[...],"last_assistant_message":"..."}

零 token 设计:本脚本不调用任何 LLM,纯文件/HTTP 操作,codex 与主会话双方 0 token;
通知内容取自 payload 的 last_assistant_message 截断摘要。

依赖:scripts/notify.py(发飞书)。失败只 print 不抛异常(notify 阻塞 codex=事故)。
复现:手动测试 `python3 scripts/codex_notify_bridge.py '{"type":"agent-turn-complete",
 "thread_id":"test-1","cwd":"/tmp","input_messages":["hi"],"last_assistant_message":"done"}'`
"""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORTS_DIR = Path("/tmp/codex-reports")
MAX_MSG_LEN = 500


def main() -> None:
    if len(sys.argv) < 2:
        return  # 无参数(codex 只在 turn-complete 时带 JSON)静默退出
    try:
        payload = json.loads(sys.argv[-1])
    except (json.JSONDecodeError, IndexError):
        return

    thread_id = str(payload.get("thread_id", "unknown"))
    last_msg = payload.get("last_assistant_message") or ""
    cwd = payload.get("cwd", "")
    ts = datetime.now().strftime("%H:%M")

    # ① .done 信号文件(主会话 cron 扫描点;原子写防半文件)
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        sig = REPORTS_DIR / f"{thread_id}.done"
        tmp = sig.with_suffix(".done.tmp")
        tmp.write_text(json.dumps({
            "thread_id": thread_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "cwd": cwd,
            "summary": last_msg[:MAX_MSG_LEN],
        }, ensure_ascii=False))
        tmp.replace(sig)
    except OSError as e:
        print(f"[codex-notify] 写信号文件失败: {e}", file=sys.stderr)

    # ② 飞书 agent_done 群(开发群;复用 notify.py 现成通道)
    #    只在 cwd 是本项目时推,避免其他目录的 codex 会话误报。
    if "trade" not in cwd:
        return
    summary = (last_msg[:300] + "…") if len(last_msg) > 300 else last_msg
    subject = "[codex] turn 完成"
    body = f"{ts} codex({thread_id[:12]}) 收工\n{summary or '(无文本回复)'}\n报告目录: {REPORTS_DIR}"
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from notify import send_feishu
        send_feishu(subject, body, chat_key="agent_done")
    except Exception as e:  # noqa: BLE001 — notify 失败绝不反噬 codex
        print(f"[codex-notify] 飞书发送失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
