#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_chat_hook.py - Claude Code hooks 逐条实时抄送用户对话到飞书开发群。

用户需求（2026-08-11）：
  "我发一句就抄送，你回复一句也直接抄送" —— 逐条实时，不是打包批量。

由 .claude/settings.json hooks 触发：
  UserPromptSubmit -> python3 scripts/feishu_chat_hook.py user
      stdin JSON 含用户消息正文在 prompt 字段 -> 抄送该句
  Stop             -> python3 scripts/feishu_chat_hook.py assistant
      stdin JSON 不含回复正文，但有 transcript_path -> 读最后一条 assistant 文本 -> 抄送

防重复抄送：/tmp/feishu_hook_sent.txt 记录已抄送消息指纹（transcript+消息id/hash），
同一条只抄一次（Stop 会多次触发，必须去重）。
防并发重复：fcntl.flock 对指纹文件加排它锁，串行化读写（Stop/UserPromptSubmit 可能并发触发）。

子 agent 会话不抄送（2026-08-12 修复）：项目级 hooks 在子 agent 会话中同样触发，
若不加判断会把子 agent 输入/输出误抄送。判定用环境变量 AI_AGENT 后缀：
主控 hook 子进程=claude-code_2-1-224_harness，子 agent hook 子进程=claude-code_2-1-224_agent，
AI_AGENT.endswith("_agent") 则 exit 0 跳过（见 main() 开头）。
⚠️ 不能用 CHILD_SESSION 环境变量判定（Claude Code 2.1.224 给主控 hook 子进程也注入=1，
曾致主控抄送停摆，commit e79c23d69 事故，详见 docs/feishu-hook-stall-diagnosis.md）。

任何异常必须 exit 0 —— hook 失败不能中断 Claude Code 主流程。
发送复用 scripts/notify.py 的 send_feishu（agent_done 开发群），密钥从
config/feishu.json + .env 读，不硬编码。

用法（手动测试）：
  echo '{"prompt": "测试用户消息", "session_id": "s1", "transcript_path": "/tmp/t.jsonl"}' \
    | python3 scripts/feishu_chat_hook.py user
  echo '{"transcript_path": "/tmp/t.jsonl"}' | python3 scripts/feishu_chat_hook.py assistant
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# 已抄送指纹文件（记录 "<模式>|<指纹>" 每行一个；/tmp 重启清空可接受：会话重启本就去重重置）
SENT_FILE = Path("/tmp/feishu_hook_sent.txt")
FEISHU_CHAT_KEY = "agent_done"  # 开发群
BODY_LIMIT = 1800  # 留余量给 subject/截断尾注（notify 内部还会截到 2000）
MAX_RETRY_READ = 5  # assistant 模式等 transcript 刷新的重试次数
RETRY_SLEEP = 0.3  # 秒

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 工具
def _log(msg: str) -> None:
    print(f"[feishu_hook] {msg}", file=sys.stderr)


def _load_sent() -> set:
    if not SENT_FILE.exists():
        return set()
    try:
        return set(SENT_FILE.read_text(encoding="utf-8").splitlines())
    except Exception:
        return set()


def _mark_sent(fingerprint: str) -> None:
    try:
        with open(SENT_FILE, "a", encoding="utf-8") as f:
            f.write(fingerprint + "\n")
    except Exception:
        pass


def _fp(parts) -> str:
    """指纹：短 hash，避免超长 key 撑大指纹文件。"""
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _truncate(text: str, limit: int = BODY_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…(已截断)"


def _send(subject: str, body: str) -> bool:
    """调 notify.send_feishu 发飞书（agent_done 开发群）。任何异常不抛。"""
    try:
        if _SCRIPT_DIR not in sys.path:
            sys.path.insert(0, _SCRIPT_DIR)
        import notify  # noqa: PLC0415 - 懒导入：import 失败只告警不崩
    except Exception as e:
        _log(f"import notify 失败(忽略): {e}")
        return False
    try:
        ok = notify.send_feishu(subject, body, chat_key=FEISHU_CHAT_KEY)
        _log(f"发送 {'成功' if ok else '未发出/失败'} subject={subject} body_len={len(body)}")
        return bool(ok)
    except Exception as e:
        _log(f"send_feishu 异常(忽略): {e}")
        return False


# ---------------------------------------------------------------- 消息正文提取
def _extract_text(content) -> str:
    """从 assistant message 的 content blocks 提取文本（排除 tool_use 等非 text）。"""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    texts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            t = (b.get("text") or "").strip()
            if t:
                texts.append(t)
    return "\n".join(texts).strip()


def _last_assistant_text(transcript_path: str):
    """读 transcript JSONL 最后一条含文本的 assistant 消息。
    返回 (line_no, text, stable_id)；无则 (None, "", None)。
    stable_id 优先消息自带 uuid/id（transcript 重写行号会变，uuid 更稳）。"""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception as e:
        _log(f"读 transcript 失败: {e}")
        return None, "", None
    for i in range(len(lines) - 1, -1, -1):
        try:
            rec = json.loads(lines[i])
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        text = _extract_text(msg.get("content"))
        if not text:
            continue
        stable = msg.get("id") or msg.get("uuid") or rec.get("uuid") or str(i)
        return i, text, stable
    return None, "", None


# ---------------------------------------------------------------- 两种模式
def handle_user(data: dict) -> int:
    """UserPromptSubmit：stdin JSON 的 prompt 字段 = 用户消息正文。"""
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return 0
    session = data.get("session_id") or ""
    transcript = data.get("transcript_path") or ""
    # 指纹含 prompt 内容 hash：同一句只抄一次（用户重复发同一句文本属罕见，可接受）
    fp = "U|" + _fp([session, transcript, prompt])
    if fp in _load_sent():
        return 0
    _send("👤 用户", _truncate(prompt))
    _mark_sent(fp)
    return 0


def handle_assistant(data: dict) -> int:
    """Stop：stdin 无正文，读 transcript_path 最后一条 assistant 文本。"""
    transcript = data.get("transcript_path") or ""
    if not transcript or not os.path.exists(transcript):
        return 0

    line_no, text, stable = None, "", None
    for _ in range(MAX_RETRY_READ):
        line_no, text, stable = _last_assistant_text(transcript)
        if text:
            break
        time.sleep(RETRY_SLEEP)

    if text:
        fp = "A|" + _fp([transcript, str(stable or line_no)])
        if fp in _load_sent():
            return 0
        _send("🤖 Claude", _truncate(text))
        _mark_sent(fp)
        return 0

    # 取不到正文：仅当 transcript 最后一条确为 assistant（真发生回复但无文本可提）
    # 才发占位；transcript 空/未刷新时静默跳过（避免刷屏）。
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1]) if lines else None
    except Exception:
        last = None
    if isinstance(last, dict) and last.get("type") == "assistant":
        fp = "A|" + _fp([transcript, "placeholder"])
        if fp not in _load_sent():
            _send("🤖 Claude", "[已回复（正文取不到）]")
            _mark_sent(fp)
    return 0


# ---------------------------------------------------------------- 入口
def main(argv) -> int:
    # 子 agent 会话不抄送（2026-08-12 修复 bug，依据诊断实测 docs/feishu-hook-stall-diagnosis.md）：
    # 项目级 hooks 在子 agent（Agent 工具派出的独立会话）中同样被加载并触发，
    # 若不拦截会把子 agent 的输入（任务 prompt）误当用户消息抄送飞书（用户已反馈）。
    # 区分标志（实测 2026-08-12 01:10 /tmp/feishu_hook_capture.log）：
    #   主控会话 hook 子进程 AI_AGENT=claude-code_2-1-224_harness（不跳过）
    #   子 agent hook 子进程  AI_AGENT=claude-code_2-1-224_agent（跳过）
    # ⚠️ 不能用 CHILD_SESSION 判定（主控 hook 子进程也被注入=1，曾致停摆事故）。
    # 主控会话逐条实时抄送完全不受影响。异常也 exit 0 不阻塞 Claude Code。
    if os.environ.get("AI_AGENT", "").endswith("_agent"):
        return 0
    mode = argv[1] if len(argv) > 1 else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        data = {}

    # 并发互斥：对指纹文件加排它锁，串行化"读已发->发送->标记"，防 Stop 并发重复抄送。
    try:
        import fcntl
        with open(SENT_FILE, "a+", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                if mode == "user":
                    handle_user(data)
                elif mode == "assistant":
                    handle_assistant(data)
                else:
                    _log(f"未知模式: {mode!r}（预期 user|assistant）")
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
    except Exception as e:
        # 无 fcntl(非 POSIX)或锁异常：退化为不加锁直接处理（不中断主流程）
        _log(f"flock 异常(忽略，退化执行): {e}")
        try:
            if mode == "user":
                handle_user(data)
            elif mode == "assistant":
                handle_assistant(data)
        except Exception as e2:
            _log(f"处理异常(忽略): {e2}")
    return 0  # hook 永远 exit 0，不阻塞 Claude Code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
