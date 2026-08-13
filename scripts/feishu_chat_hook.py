#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_chat_hook.py - Claude Code hooks 逐条实时抄送用户对话到飞书开发群。

用户需求（2026-08-11）：
  "我发一句就抄送，你回复一句也直接抄送" —— 逐条实时，不是打包批量。
2026-08-13 升级（用户原话"索性全量抄送,不过滤了,反正也滤不好"）：
  主/子会话全量抄送，不再跳过子 agent 会话；每条标注主会话/子会话+角色。

由 .claude/settings.json hooks 触发：
  UserPromptSubmit -> python3 scripts/feishu_chat_hook.py user
      stdin JSON 含用户消息正文在 prompt 字段 -> 抄送该句
  Stop             -> python3 scripts/feishu_chat_hook.py assistant
      整段回复全文抄送（2026-08-12）：一个 turn 内 assistant 常有多条文本消息
      （工具循环中间分析 + 最终结论），拼接 transcript 当前 turn 内**所有** assistant
      文本消息（以最后一条真实 user 消息为 turn 边界）整段抄送，不只最后一条；
      payload 的 last_assistant_message（新版 Claude Code 2.1.224 已含最终回复全文）
      保留作"最后一条"兜底补丁（transcript 拼不到时降级只发最后一条，不丢不阻塞）

主/子会话区分（2026-08-13 重建，替代已失效的 AI_AGENT 后缀判定）：
  根因：Claude Code 2.1.224 主会话 hook 子进程 AI_AGENT 已从 _harness 变成 _agent，
  原 AI_AGENT.endswith("_agent") 跳过逻辑会误跳主会话（丢用户消息）+误当子会话。
  2.1.224 原生可靠区分信号（payload 字段）：
    - hook_event_name：主会话 Stop="Stop"（无 agent_id/agent_type）；子会话="SubagentStop"
      且带 agent_id/agent_type/agent_transcript_path（agent_type=角色名）
    - UserPromptSubmit：带 agent_id 或 transcript_path 含 "/subagents/agent-" => 子会话
    - transcript_path：子会话=<proj>/<sessionId>/subagents/agent-<id>.jsonl；
      主会话=<proj>/<sessionId>.jsonl
    - 子 agent 完成通知注入主会话：UserPromptSubmit prompt 以
      "<agent-message from=\"X\">" 开头（X=角色名/general-purpose）=> 子会话(角色X)汇报
  判据详见 docs/archive + research-hook-main-sub-20260813-1826.log；
  ⚠️ 不能再用 CHILD_SESSION/CLAUDE_CODE_SESSION_ID（主/子同值，曾致停摆事故 e79c23d69）。
  ⚠️ AI_AGENT 已废弃作判定信号（变值 _harness/_agent 均出现过）。

防重复抄送：/tmp/feishu_hook_sent.txt 记录已抄送消息指纹（transcript+消息id/hash），
同一条只抄一次（Stop 会多次触发，必须去重）。
防并发重复：fcntl.flock 对指纹文件加排它锁，串行化读写（Stop/UserPromptSubmit 可能并发触发）。

任何异常必须 exit 0 —— hook 失败不能中断 Claude Code 主流程。
发送复用 scripts/notify.py 的 send_feishu（agent_done 开发群），密钥从
config/feishu.json + .env 读，不硬编码。

用法（手动测试）：
  echo '{"prompt": "测试用户消息", "session_id": "s1", "transcript_path": "/tmp/t.jsonl"}' \
    | python3 scripts/feishu_chat_hook.py user
  echo '{"transcript_path": "/tmp/t.jsonl", "last_assistant_message": "测试回复全文"}' \
    | python3 scripts/feishu_chat_hook.py assistant
  echo '{"transcript_path": "/tmp/t.jsonl"}' | python3 scripts/feishu_chat_hook.py assistant
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# 已抄送指纹文件（记录 "<模式>|<指纹>" 每行一个；/tmp 重启清空可接受：会话重启本就去重重置）
SENT_FILE = Path("/tmp/feishu_hook_sent.txt")
FEISHU_CHAT_KEY = "agent_done"  # 开发群
BODY_LIMIT = 1800  # 留余量给 subject/截断尾注（notify 内部还会截到 2000）
MAX_RETRY_READ = 5  # assistant 模式等 transcript 刷新的重试次数
RETRY_SLEEP = 0.3  # 秒
# 不抄送的系统/定时 prompt 前缀(2026-08-12 主控定位): 主控 cron 轮询 prompt 会触发
# UserPromptSubmit 被当"用户消息"抄送(飞书群出现"轮询"噪音); 用户真实消息盘中打断
# (turn 运行中注入)反而不触发 UserPromptSubmit → 漏抄, 治漏抄靠 _sweep_unforwarded 补扫。
SKIP_PROMPT_PREFIXES = ("轮询", "[cron-poll", "[cron", "[system", "[SYSTEM", "§11")
# 系统注入/任务通知内容级强特征(2026-08-13 修复): 子 agent 完成通知(task-notification)
# 注入主控会话时以 agentId/任务描述/<task-notification> 标签开头, SKIP_PROMPT_PREFIXES
# 前缀匹配挡不住, 需内容级判定。以下句子只出现在系统注入(Claude Code 后台任务事件文案),
# 真实用户消息不会含; 不用更宽特征防误杀用户消息。
SYSTEM_INJECT_MARKERS = (
    "task-notification",
    "A task-notification fires each time",
    "SYSTEM NOTIFICATION",
    "NOT USER INPUT",
    "This is an automated background-task event",
    "automated background-task event, NOT a message from the user",
    # 2026-08-13 误抄送修复: ①cron 巡检 prompt 固定文案(主控曾把前缀从"轮询"改"§11 cron"绕过前缀黑名单,
    # 内容级特征更稳); ②compact 上下文恢复摘要固定英文开头(被当"👤 用户"误抄)。两条均为系统注入固定文案,
    # 真实用户消息不会含。前缀黑名单+内容级特征双保险。
    "cron 兜底巡检",
    "This session is being continued",
)
# 补扫窗口: 只看 transcript 尾部最近 N 条(防首次接入时洪水补发历史消息)
SWEEP_LINES = 120

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 工具
def _log(msg: str) -> None:
    print(f"[feishu_hook] {msg}", file=sys.stderr)


def _is_system_inject(text: str) -> bool:
    """判定文本是否为系统注入(task-notification 等后台任务事件), 是则返回 True(不抄送)。

    子 agent 完成通知注入主控会话时被 UserPromptSubmit 触发, prompt 以 agentId/
    任务描述/<task-notification> 标签开头, 前缀过滤(SKIP_PROMPT_PREFIXES)挡不住;
    用内容级强特征(SYSTEM_INJECT_MARKERS, 只出现在系统注入的句子)判定, 防误杀真实用户消息。
    """
    if not text:
        return False
    return any(marker in text for marker in SYSTEM_INJECT_MARKERS)


# ---------------------------------------------------------------- 主/子会话判定
# 角色名 -> 中文(2026-08-13 需求): implementer/reviewer/researcher/tester/general-purpose
ROLE_CN = {
    "implementer": "实施",
    "reviewer": "审查",
    "researcher": "调研",
    "tester": "测试",
    "general-purpose": "通用",
}


def _role_cn(role) -> str | None:
    """角色名转中文；未知角色/None 原样返回（None 由调用方兜底成"子会话"）。"""
    if not role:
        return None
    return ROLE_CN.get(role, role)


def _subagent_subject(role) -> str:
    """子会话 subject：🧩 子会话·{中文角色}；角色未知 => 🧩 子会话。"""
    cn = _role_cn(role)
    return f"🧩 子会话·{cn}" if cn else "🧩 子会话"


def classify(data: dict):
    """按 payload 判定主会话/子会话 + 角色（2026-08-13 重建，替代 AI_AGENT 后缀）。

    返回 (kind, role, sub_transcript)：
      kind: "main" | "subagent" | "unknown"
      role: agent_type(implementer/reviewer/researcher/tester/general-purpose)，未知 None
      sub_transcript: 子会话的 agent_transcript_path（仅 subagent 可能有）

    2.1.224 原生信号（researcher 源码级 + 实测 payload 佐证，详见 docstring）：
      - hook_event_name: 主 Stop="Stop" / 子 Stop="SubagentStop"(带 agent_id/agent_type)
      - UserPromptSubmit: 带 agent_id 或 transcript_path 含 "/subagents/agent-" => 子会话
      - 无 hook_event_name 时(旧版/手动测试)退化用 transcript_path 路径特征判定
    """
    hev = data.get("hook_event_name")
    if hev == "SubagentStop":
        return ("subagent", data.get("agent_type") or None, data.get("agent_transcript_path"))
    if hev == "Stop":
        # 主会话 Stop 正常无 agent_id；极端情况（部分版本子 Stop 也发 Stop）兜底判子
        if data.get("agent_id"):
            return ("subagent", data.get("agent_type") or None, None)
        return ("main", None, None)
    tp = data.get("transcript_path") or ""
    if hev == "UserPromptSubmit":
        if data.get("agent_id") or "/subagents/agent-" in tp:
            return ("subagent", data.get("agent_type") or None, tp)
        return ("main", None, tp)
    # 无 hook_event_name：退化路径特征判定（手动测试/旧版 Claude Code）
    if data.get("agent_id") or "/subagents/agent-" in tp:
        return ("subagent", data.get("agent_type") or None, tp)
    return ("main", None, tp)


_AGENT_MESSAGE_RE = re.compile(r'<agent-message from="([^"]+)"')


def _agent_message_role(prompt: str) -> str | None:
    """从 "<agent-message from=\"X\">" 前缀提取子 agent 角色名 X（无则 None）。"""
    m = _AGENT_MESSAGE_RE.search(prompt or "")
    return m.group(1) if m else None


def _detect_subagent_role(transcript_path: str) -> str | None:
    """从子 agent transcript 首部提取角色名（补扫/无 agent_type 时兜底）。

    子 agent 自己的 transcript 首条 user 消息含
    <command-name>role-<角色></command-name>（本 agent 实测 role-implementer）。"""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for ln in lines[:40]:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        txt = json.dumps(rec, ensure_ascii=False)
        m = re.search(r'role-(implementer|reviewer|researcher|tester|general-purpose)', txt)
        if m:
            return m.group(1)
    return None


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


def _collect_turn_assistant_texts(transcript_path: str):
    """读 transcript，拼接"当前 turn"内**所有** assistant 文本消息。

    当前 turn 界定：最后一条真实 user 消息（JSONL type=user 且 message.content 为
    非空 str 文本，排除 tool_result 等 dict content）之后的全部 assistant 消息。
    一个 turn 内 assistant 常有多条文本消息（工具循环中间的"分析" + 最终结论），
    整段回复全文抄送需全含，不只 last_assistant_message（最后一条）。

    返回 [(line_no, text, stable), ...] 按行序（最近 turn 在尾部）；无则 []。
    stable_id 优先消息自带 uuid/id（transcript 重写行号会变，uuid 更稳）。"""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception as e:
        _log(f"读 transcript 失败: {e}")
        return []
    boundary_found = False  # 是否遇过真实 user 消息（turn 边界）
    records = []
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        t = rec.get("type")
        if t == "user":
            msg = rec.get("message")
            c = (msg or {}).get("content") if isinstance(msg, dict) else None
            if isinstance(c, str) and c.strip():
                boundary_found = True
                records = []  # 新 turn 边界：重置，之前的 assistant 不属于当前 turn
        elif t == "assistant":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            text = _extract_text(msg.get("content"))
            if text:
                stable = msg.get("id") or msg.get("uuid") or rec.get("uuid") or str(i)
                records.append((i, text, stable))
    return records if boundary_found else []


# ---------------------------------------------------------------- 补扫
def _sweep_unforwarded(transcript_path: str, session: str = ""):
    """补扫 transcript 尾部最近消息，抄送"尚无独立 hook 事件"的 user/assistant 文本。

    根因(2026-08-12 主控定位): 主控长 turn(盘中用户打断/cron 轮询注入)期间无 Stop 事件，
    UserPromptSubmit 也只在该次 prompt 触发——用户真实消息/我的回复若落在长 turn 内，
    永远等不到属于自己的 hook 事件 → 漏抄(飞书群只有👤轮询噪音、缺用户真实句和🤖回复)。
    每次任意 hook 触发(用户新句/轮询/回复)后顺带补扫，把窗口内未抄送的补上。
    指纹与主 handler 同公式(session+transcript+内容)，互斥去重不重发；轮询前缀不补扫。
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception as e:
        _log(f"补扫读 transcript 失败: {e}")
        return
    # 2026-08-13 全量抄送: 补扫同样区分主/子会话(路径含 /subagents/agent- 判子会话)
    subagent = "/subagents/agent-" in (transcript_path or "")
    sub_role = _detect_subagent_role(transcript_path) if subagent else None
    user_subject = _subagent_subject(sub_role) if subagent else "👤 主会话"
    asst_subject = _subagent_subject(sub_role) if subagent else "🤖 主会话"
    for ln in lines[-SWEEP_LINES:]:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == "user":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            c = msg.get("content")
            txt = c.strip() if isinstance(c, str) else ""
            # 2026-08-13: task-notification 注入同样前缀不匹配, 叠加内容级强特征拦截
            if not txt or txt.startswith(SKIP_PROMPT_PREFIXES) or _is_system_inject(txt):
                continue
            fp = "U|" + _fp([session, transcript_path, txt])
            if fp in _load_sent():
                continue
            if _send(user_subject, _truncate(txt)):
                _mark_sent(fp)
        elif rec.get("type") == "assistant":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            txt = _extract_text(msg.get("content"))
            if not txt:
                continue
            fp = "A|" + _fp([transcript_path, txt[:200]])
            if fp in _load_sent():
                continue
            if _send(asst_subject, _truncate(txt)):
                _mark_sent(fp)


# ---------------------------------------------------------------- 两种模式
def handle_user(data: dict) -> int:
    """UserPromptSubmit：stdin JSON 的 prompt 字段 = 用户消息正文。

    2026-08-13 全量抄送：主/子会话均抄送（不再跳过子 agent 会话），并按 classify 标注：
      - 主会话用户 => 👤 主会话
      - 子会话 UserPromptSubmit（子 agent 收到的任务 prompt）=> 🧩 子会话·{角色}
      - 子 agent 完成通知注入主会话（prompt 以 <agent-message from="X"> 开头）
        => 🧩 子会话·{角色X} 汇报
    """
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return 0
    # cron 轮询/系统注入 prompt 不抄送(2026-08-12): 主控定时轮询会被当"用户消息"误抄
    # (2026-08-13 修复): 子 agent 完成通知(task-notification)注入主控会话, prompt 以
    # agentId/描述开头前缀不匹配 → 叠加内容级强特征 _is_system_inject 一并拦截
    if prompt.startswith(SKIP_PROMPT_PREFIXES) or _is_system_inject(prompt):
        return 0
    kind, role, _ = classify(data)
    if prompt.startswith("<agent-message from="):
        # 子 agent 完成通知注入主会话（或子会话收到更深层 agent-message）：标"角色汇报"
        from_role = _agent_message_role(prompt) or "general-purpose"
        subject = f"🧩 子会话·{_role_cn(from_role)} 汇报"
    elif kind == "subagent":
        subject = _subagent_subject(role)
    else:
        subject = "👤 主会话"
    session = data.get("session_id") or ""
    transcript = data.get("transcript_path") or ""
    # 指纹含 prompt 内容 hash：同一句只抄一次（用户重复发同一句文本属罕见，可接受）
    fp = "U|" + _fp([session, transcript, prompt])
    if fp in _load_sent():
        return 0
    if _send(subject, _truncate(prompt)):
        _mark_sent(fp)
    # 顺带补扫：长 turn 内被注入的用户消息/我的回复可能无独立 hook 事件 → 补抄
    _sweep_unforwarded(transcript, session)
    return 0


def handle_assistant(data: dict) -> int:
    """Stop/SubagentStop：拼接当前 turn 内**所有** assistant 文本消息（中间分析+最终结论）整段抄送。

    需求（2026-08-12）："整段回复全文抄送"——一个 turn 内 assistant 常有多条文本消息
    （工具循环中间分析 + 最终结论），只抄 last_assistant_message（最后一条）会丢中间分析。
    方案：优先读 transcript 拼接当前 turn 全部 assistant 文本（MAX_RETRY_READ 重试等
    transcript 刷新）；payload 的 last_assistant_message 保留作"最后一条"兜底补丁——
    transcript 拼不到时降级只发最后一条（不丢不阻塞）；transcript 无 user 边界/全空则占位。

    2026-08-13 全量抄送：主会话 Stop => 🤖 主会话；子会话 SubagentStop => 🧩 子会话·{角色}，
    子会话 transcript 优先用 payload 的 agent_transcript_path（子 agent 的 transcript）。

    防重发：并入拼接的每条 assistant 消息单条指纹一并标记（与 _sweep_unforwarded 同公式），
    避免补扫把中间分析逐条再发一遍造成重复；拼接全文自身指纹防 Stop 多次触发重发。"""
    transcript = data.get("transcript_path") or ""
    session = data.get("session_id") or ""
    last_msg = (data.get("last_assistant_message") or "").strip()

    kind, role, sub_transcript = classify(data)
    if kind == "subagent":
        subject = _subagent_subject(role)
        # 子会话 transcript 优先用 agent_transcript_path（SubagentStop 带），否则退主 transcript_path
        transcript = sub_transcript or transcript
    else:
        subject = "🤖 主会话"

    # 1) 优先：读 transcript 拼接当前 turn 全部 assistant 文本（重试等刷新）
    if transcript and os.path.exists(transcript):
        turn_texts = []
        for _ in range(MAX_RETRY_READ):
            turn_texts = _collect_turn_assistant_texts(transcript)
            if turn_texts:
                break
            time.sleep(RETRY_SLEEP)
        if turn_texts:
            parts = [t for _, t, _ in turn_texts]
            body = "\n\n".join(parts).strip()
            # last_assistant_message 为最终结论：若 transcript 尾部未含（flush 延迟）则补为最后一段
            if last_msg and not body.endswith(last_msg):
                body = (body + "\n\n" + last_msg).strip()
            # 补入段(last_msg 来自 payload, 不在 turn_texts)无条件补标单条指纹：
            # 防 flush 完成后补扫把该段单独重发(reviewer 审出防重发缺陷；重复标记幂等无害)
            if last_msg:
                _mark_sent("A|" + _fp([transcript, last_msg[:200]]))
            fp = "A|" + _fp([transcript, body[:200]])
            if fp in _load_sent():
                _sweep_unforwarded(transcript, session)
                return 0
            # 并入的每条 assistant 单条指纹标记，防 _sweep_unforwarded 逐条重发(P2-1 同公式)
            for _, t, _ in turn_texts:
                _mark_sent("A|" + _fp([transcript, t[:200]]))
            if _send(subject, _truncate(body)):
                _mark_sent(fp)
            _sweep_unforwarded(transcript, session)
            return 0

    # 2) 降级：transcript 拼不到但有最终回复全文 → 只发最后一条（不丢不阻塞）
    if last_msg:
        fp = "A|" + _fp([transcript, last_msg[:200]])
        if fp in _load_sent():
            _sweep_unforwarded(transcript, session)
            return 0
        if _send(subject, _truncate(last_msg)):
            _mark_sent(fp)
        _sweep_unforwarded(transcript, session)
        return 0

    # 3) 取不到正文：仅当 transcript 最后一条确为 assistant（真发生回复但无文本可提）
    # 才发占位；transcript 空/未刷新时静默跳过（避免刷屏）。
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1]) if lines else None
    except Exception:
        last = None
    if isinstance(last, dict) and last.get("type") == "assistant":
        fp = "A|" + _fp([transcript, "placeholder"])
        if fp not in _load_sent():
            if _send(subject, "[已回复（正文取不到）]"):
                _mark_sent(fp)
    _sweep_unforwarded(transcript, session)
    return 0


# ---------------------------------------------------------------- 入口
def main(argv) -> int:
    # 2026-08-13 全量抄送：主/子会话都不再跳过（用户原话"索性全量抄送,不过滤了"）。
    # 原 AI_AGENT.endswith("_agent") 跳过逻辑已移除——2.1.224 主会话 hook 子进程
    # AI_AGENT 已从 _harness 变 _agent，会误跳主会话丢用户消息 + 误当子会话。
    # 主/子区分改为 payload 级 classify()（hook_event_name/agent_id/transcript_path，
    # 见 docstring + classify 注释）。异常也 exit 0 不阻塞 Claude Code。
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
