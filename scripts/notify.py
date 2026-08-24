#!/usr/bin/env python3
"""notify.py - update_all 监控通知工具（多渠道：邮件 + Telegram + 飞书 + alerts 文件）。

多渠道分发（send()）：先邮件后 Telegram 再飞书，各渠道独立失败不互相阻塞，返回聚合结果
{"email": bool, "telegram": bool, "feishu": bool}。

- 邮件：复用 config/email.json（字段：smtp/port/user/password/to，SMTP SSL，163->QQ）。
- Telegram：读 config/telegram.json（bot_token/chat_id/api_base，POST Bot API sendMessage；
  国内 GFW 不可达时 api_base 设 CF Workers 反代 URL，详见 telegram.json.example）。
- 飞书：读 config/feishu.json（app_id/app_secret 从 .env 读 FEISHU_APP_ID/FEISHU_APP_SECRET，
  三群 chat_id 映射 alert=运维群/agent_done=开发群/report=报告群，tenant_access_token +
  im/v1/messages API，详见 feishu.json.example 与 docs/feishu-bot-integration-plan.md）。
- 严重告警额外写 data/alerts/latest.md（覆盖式记最新一次严重），供下轮 Claude 开工优先排查。
- 邮件兜底保留：飞书失败不阻塞邮件（best-effort），SEVERE 告警邮件始终发（防飞书故障无通知）。

用法（CLI）:
  notify.py <subject> <body> [--severe] [--alert-issue <issue> [--alert-log <path>]]
             [--from-prefix <prefix>] [--dry-run] [--feishu-group <key>] [--feishu-only]
             [--reply-to-message-id <id>]
  notify.py --agent-done <name> <summary> [--dry-run]
             （agent 完成通知：发邮件直达用户绕过主控队列，5min 去重防轰炸；飞书固定发开发群）

  --reply-to-message-id  飞书引用回复：body 加 reply_to_message_id，把消息作为对指定
                    消息 ID 的引用回复发送（回复挂靠在原消息下方，任务状态可挂靠追踪）。
                    仅飞书应用模式（im/v1/messages）生效，email/telegram 忽略此参数。

  --severe          2026-07-20 改造：仅用于 write_alert 语义标记（SEVERE_PREFIX 已置空串，
                    subject 前缀由调用方控制，统一 [告警]/[完成]/[恢复] 模板）。
  --alert-issue     写 data/alerts/latest.md（issue 一句话 + 详情=body + 日志路径）
  --alert-log       配合 --alert-issue，记录日志文件路径
  --from-prefix     邮件发件人名前缀（如 [告警] -> "From: [告警] 信号实验室 <user>"）。
                    默认 None 时用 "信号实验室监控"。
  --feishu-group    飞书群 key 显式覆盖（alert/agent_done/report）
  --feishu-only     只发飞书（跳过邮件/Telegram），调试用
  --dry-run         不真发，只 print 到 stderr（自验用）

各渠道发送失败只 print 警告不抛异常（不阻塞调用方，update_all 末尾 || true 双保险）。
"""
from __future__ import annotations

import argparse
import certifi
import json
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
EMAIL_CONFIG = REPO / "config" / "email.json"
TELEGRAM_CONFIG = REPO / "config" / "telegram.json"
FEISHU_CONFIG = REPO / "config" / "feishu.json"
ALERTS_DIR = REPO / "data" / "alerts"
ALERTS_FILE = ALERTS_DIR / "latest.md"
# notify.py 去重文件(独立于 schedule_monitor 的 alert_state.json,互不污染)。
# 结构: {"<dedup_key>": {"last_alerted": "YYYY-MM-DD HH:MM:SS"}}。
# 不进 git(运行时数据,与 alert_state.json 同级 .gitignore 忽略)。
DEDUP_FILE = REPO / "data" / "notify_dedup.json"

# email.json.example 中的占位密码，识别后跳过实际发送
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码，非登录密码>"

# telegram.json.example 中的占位值，识别后跳过实际发送
PLACEHOLDER_TG_TOKEN = "YOUR_BOT_TOKEN"
PLACEHOLDER_TG_CHAT = "YOUR_CHAT_ID"

# feishu.json.example 中的占位值，识别后跳过实际发送（app_id/app_secret 优先从 .env 读）
PLACEHOLDER_FEISHU_ID = "cli_xxx"
PLACEHOLDER_FEISHU_SECRET = "YOUR_APP_SECRET"

# Telegram Bot API sendMessage 单条文本上限 4096 字符
TG_TEXT_LIMIT = 4096

# 飞书 text 消息单条长度上限（约 1-2K 量级，取保守 2000；超长截断）
FEISHU_TEXT_LIMIT = 2000

# 飞书 post 富文本（msg_type=post）每段行数上限（2026-08-16 用户定：放开行数+超长分段连发）。
#   - 旧：20 行即截断省略尾部（信息量优先），超长会丢「细讲/风险项/辩论/四角色」。
#   - 新：单条 post 真实上限约 30KB（样式标签占体积），80 行≈5.6K 字符离上限很远；
#         20→80 放宽让 AI预测/买卖点等日常内容完整落一条，不省略。
#   - 仍可能超 80 行（如买卖点全量触发）时，send_feishu 内部按此值每段切分、多段连发
#     （标题带 N/M 序号），绝不省略行（和页面一致）。由此跳过 20 行截断省略逻辑。
FEISHU_POST_MAX_ROWS = 80

# P1-1（2026-08-11 稳定性修复）：飞书发送有限重试 3 次（指数退避 1s/3s/7s）。
# 网络瞬时错误（URLError/HTTP 5xx）与飞书服务端瞬时错误码重试；确定性错误（4xx/
# token 无效/内容非法等）不重试。防止偶发网络抖动/服务端瞬时错误导致消息永久不发。
_FEISHU_SEND_ATTEMPTS = 3
_FEISHU_RETRYABLE_CODES = {99999, 9999, 10001, 10002}

# ── 告警三级分级（2026-08-24，codex 审计降噪改造）─────────────────────────────
# 背景：alert_state.json 59 条告警 54 条 recovered（91.5% 自愈率），大部分推送是瞬时网络
# 抖动而非真实故障，轰炸稀释真故障敏感度。三级路由（冻结契约：只减假警报，critical 真故
# 障仍即时可达用户，行为对照表见 docs/alert-tier-refactor-20260824.md）：
#   critical = 真故障（服务宕/数据丢失/卡死/最终失败）→ 立即邮件+飞书 alert 群（=原 severe 行为）
#   warning  = 高概率自愈类（瞬时超时抖动/rebase 中间态/smoke curl 抖动/监控交接类）
#              → 写 buffer，30min 聚合一批由 flush_warning_batch 发出（schedule_monitor/
#              monitor_72h 每轮尾部调用；满窗口条目合并一封，绝不丢条目）
#   info     = 单次瞬时抖动自愈/已确认项的重复提醒 → 只记 dashboard（info_log.jsonl），不推送
TIER_CRITICAL = "critical"
TIER_WARNING = "warning"
TIER_INFO = "info"
WARNING_BUFFER_FILE = ALERTS_DIR / "warning_buffer.jsonl"
INFO_LOG_FILE = ALERTS_DIR / "info_log.jsonl"
WARNING_BATCH_WINDOW = 1800  # 30min 聚合窗口（秒）


def _feishu_backoff(attempt: int) -> float:
    """指数退避：attempt=0->1s, 1->3s, 2->7s。返回 sleep 秒数。"""
    secs = float(2 ** attempt + attempt)  # 1, 3, 7
    time.sleep(secs)
    return secs

# ⚠️ 飞书 post 文本色实测结论（2026-08-11）：im/v1/messages 的 post text 标签**不支持**
# style.color（任何色名/hex 都报 230001 invalid message content，实测验证）。
# 彩色语义改用【彩色 emoji 前缀 + md 加粗表头】实现（🔴买/🟢卖/⚪持有，A股红涨绿跌与平台信号灯一致，md 支持 **加粗**）。
# 后续若飞书 API 开放 style 支持，再恢复 post_text 的 color 参数。

# 飞书 tenant_access_token 缓存（2h 有效，过期前 120s 刷新复用）
_FEISHU_TOKEN_CACHE: dict = {"token": None, "expire_at": 0.0}
# 飞书 open.feishu.cn（中国版域名）
FEISHU_API_BASE = "https://open.feishu.cn"

# SEVERE_PREFIX 保留空串（2026-07-20 改造：由调用方在 subject 表达严重程度，统一 [告警] 前缀）。
# --severe 标记仍用于 write_alert 写 data/alerts/latest.md（独立于 subject 前缀）。
SEVERE_PREFIX = ""

# 邮件移动端适配 CSS（@media max-width:600px）：表格转块级（thead 隐藏、tr 卡片、td 全宽）
# + 字号缩 + 列宽弹性 + 长文本换行。修手机预览错位（build_email 原 body max-width:720px +
# 固定列宽 48/56/130px 在窄屏溢出）。check_signals.py / check_nt_signals.py 的 build_email
# <head> 里引用本常量（同一段 CSS 两脚本共用，改一处生效）。
MOBILE_EMAIL_CSS = """<style>
@media (max-width:600px){
  body{max-width:100% !important;padding:10px !important;font-size:13px !important;}
  table{width:100% !important;font-size:12px !important;}
  thead{display:none !important;}
  tr{display:block !important;margin:0 0 10px 0 !important;border:1px solid #e5e6eb !important;border-radius:8px !important;}
  td{display:block !important;width:100% !important;box-sizing:border-box !important;padding:5px 10px !important;text-align:left !important;border:none !important;word-wrap:break-word !important;overflow-wrap:break-word !important;white-space:normal !important;}
}
</style>"""


def load_email_config() -> dict | None:
    """读 config/email.json。不存在/解析失败返回 None。"""
    if not EMAIL_CONFIG.exists():
        print(f"[notify] config/email.json 不存在，跳过邮件", file=sys.stderr)
        return None
    try:
        return json.loads(EMAIL_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[notify] config/email.json 解析失败：{e}", file=sys.stderr)
        return None


def load_telegram_config() -> dict | None:
    """读 config/telegram.json。不存在/解析失败返回 None。

    文件不存在视为"未配置"（静默跳过，与 email.json 不存在同口径）。
    """
    if not TELEGRAM_CONFIG.exists():
        return None
    try:
        return json.loads(TELEGRAM_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[notify] config/telegram.json 解析失败：{e}", file=sys.stderr)
        return None


def _html_to_text(html: str) -> str:
    """简易 HTML -> 纯文本（Telegram 不支持 table 等富 HTML，转纯文本发送）。

    <br>/<p>/<div>/<tr>/<li>/<h*> -> 换行，<td>/<th> -> ' | ' 分隔，其余标签剥离，
    HTML 实体反转义，多余空行折叠。
    """
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</?(p|div|tr|li|h[1-6])\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"</?(td|th)\b[^>]*>", " | ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)  # 剥离剩余标签
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&nbsp;", " "))
    text = re.sub(r"\n{3,}", "\n\n", text)  # 折叠多余空行
    return text.strip()


# ── 飞书 post 富文本（msg_type=post，报告群信号消息用）──────────────────────────
# 飞书官方规范：post 消息 content（app 模式 im/v1/messages）= {"zh_cn": {"title": ...,
# "content": [...]}}（实测无 post 外层包；webhook 模式才需 {"post": ...} 外层）。
# content 为二维数组：外层=行，内层=该行的 tag 列表（text/md/a/at/img 等）。
# - text 标签：纯文本，可选 un_escape（\n 换行生效）；**不支持 style.color**（见上方实测注释）。
# - md 标签：markdown（**加粗**/`行内码`/[链接](url)，表头/高亮用）。
# - a 标签：链接。
# 对比 text 消息：post 支持分组/加粗表头/链接/彩色 emoji，表格不再被 _html_to_text
# 拍平成 ' | ' 纯文本（用户反馈"毫无格式、冗长、可读性差"的根因）。


def post_text(text: str, href: str | None = None, un_escape: bool = False) -> dict:
    """构建飞书 post 富文本的一个 text 标签（见 build_feishu_post）。

    注意：本 API 的 post text 标签不支持 style.color（实测 230001），彩色语义用
    彩色 emoji 前缀（如 🔴 买入/🟢 卖出/⚪ 持有，A股红涨绿跌与平台信号灯一致）实现，见 build_feishu_post 调用方。
    href: 非空时输出 a 链接标签（{tag:a, text, href}）。
    un_escape: True 时 text 内 \\n 换行生效（post 默认按字面渲染，\\n 不换行）。
    """
    if href:
        return {"tag": "a", "text": str(text), "href": href}
    tag = {"tag": "text", "text": str(text)}
    if un_escape:
        tag["un_escape"] = True
    return tag


def post_md(text: str) -> dict:
    """构建飞书 post 富文本的一个 md（markdown）标签：支持 **加粗**/`行内码`/[链接](url)。

    分组表头用（如 "🟢 **买入信号**（主买1 辅买1）"），渲染比 text 醒目。
    """
    return {"tag": "md", "text": str(text)}


def build_feishu_post(title: str, lines: list[list[dict]]) -> dict:
    """构建飞书 post 富文本 content（zh_cn 版，app 模式直接作 content 传 im/v1/messages）。

    结构（飞书官方规范）：
      {"zh_cn": {"title": <标题>, "content": [[{tag:...}, ...], ...]}}
    - title: 消息标题（顶部大字，建议 ≤200 字符）
    - lines: 行列表，每行 = tag 列表（post_text()/post_md() 产出），行内可多 tag 混排

    send_feishu(feishu_post=本返回值) 即以 post 富文本发送（仅 report 群生效）。
    """
    return {"zh_cn": {"title": str(title), "content": [list(line) for line in lines]}}


def _split_post_segments(post_dict: dict, max_rows: int | None = None) -> list[dict]:
    """把 build_feishu_post 产物按 max_rows 每段切分成多个 post dict（标题带 N/M 序号）。

    - 不超过 max_rows 时返回 [post_dict]（一条原样发送，内容不变）。
    - 超过时每段最多 max_rows 行，段标题追加「N/M」序号标识分段连发（第 1 段也带，
      让多段消息清楚可辨），行内容原样保留不进省略行。
    - max_rows 默认 FEISHU_POST_MAX_ROWS（80）。每一行不会被截断、不丢失任何内容。
    """
    if max_rows is None:
        max_rows = FEISHU_POST_MAX_ROWS
    zh = post_dict.get("zh_cn", {}) or {}
    title = str(zh.get("title", ""))
    content = zh.get("content", []) or []
    rows_total = len(content)
    if rows_total <= max_rows:
        return [post_dict]
    n_seg = (rows_total + max_rows - 1) // max_rows
    out: list[dict] = []
    for i in range(n_seg):
        chunk = content[i * max_rows:(i + 1) * max_rows]
        out.append({
            "zh_cn": {
                "title": f"{title} {i + 1}/{n_seg}",
                "content": [list(line) for line in chunk],
            }
        })
    return out


def send_feishu_post_segmented(subject: str, lines: list[list[dict]],
                               max_rows: int | None = None,
                               reply_to_message_id: str | None = None,
                               dry_run: bool = False, from_prefix: str | None = None
                               ) -> bool:
    """逐条连发飞书 post 富文本，超行数自动分段不省略（2026-08-16 用户定放开行数+分段）。

    - lines: build_feishu_post 的行列表（每行 = tag 列表，post_text()/post_md() 产出）。
    - 单次通知内分段连发：≤max_rows(默认 80) 一条发；超过按每段 max_rows 切分，标题带
      「N/M」序号连续发送（每段一个 post 消息），绝不省略行（和页面一致）。
    - 只发飞书 report 群这一个渠道，不走 notify.send 的邮件/Telegram 分发（适合调用方
      已另行处理邮件、仅需飞书分段连发的场景）。用 send()/send_to() 传 feishu_post= 时，
      send_feishu 内部也会自动分段（见 send_feishu），无需显式调本函数。
    - dry_run=True 只 print 不真发。返回 True 表示发出（或 dry_run 模拟成功）。
    - 分段只在单次通知内连发；「同日只发一次」的 dedup 由调用方在 send 前统一做一次
      （本函数不重复检查 dedup，首条后各段不再检查）。
    """
    post = build_feishu_post(subject, lines)
    segments = _split_post_segments(post, max_rows)
    if len(segments) == 1:
        return send_feishu(subject, "", dry_run=dry_run, from_prefix=from_prefix,
                           chat_key="report",
                           reply_to_message_id=reply_to_message_id,
                           feishu_post=post)
    n = len(segments)
    ok = True
    for i, pd in enumerate(segments, 1):
        seg_title = pd.get("zh_cn", {}).get("title", subject)
        print(f"[notify] 分段 {i}/{n} 发出：{seg_title}（{len(pd['zh_cn']['content'])} 行），"
              f"同一通知连发，dedup 只由调用方查一次", file=sys.stderr)
        if not send_feishu(subject, "", dry_run=dry_run, from_prefix=from_prefix,
                           chat_key="report",
                           reply_to_message_id=reply_to_message_id,
                           feishu_post=pd):
            ok = False
    return ok


def send_telegram(subject: str, body: str, dry_run: bool = False,
                  chat_id: str | None = None) -> bool:
    """发 Telegram 消息（POST Bot API sendMessage）。

    读 config/telegram.json（bot_token/chat_id/api_base）。失败只 print 警告不抛异常
    （不阻塞调用方/不阻塞邮件）。

    config/telegram.json 字段：
      - bot_token: BotFather 创建 bot 后给的 token（Telegram 找 @BotFather -> /newbot）
      - chat_id:   目标 chat id。私聊数字 id 或 @channelusername；获取方式：给 bot 发
                   任意消息后访问 https://api.telegram.org/bot<TOKEN>/getUpdates
                   （result.message.chat.id）
      - api_base:  可选，默认 https://api.telegram.org。国内 GFW 不可达时设为
                   CF Workers 反代 URL（复用 ss.fx8.store 域名做 Telegram API 反代，
                   详见 config/telegram.json.example 帮助文本）

    chat_id 参数（A12 订阅推送用）：指定接收方 chat_id，覆盖 config 的 chat_id。
      bot_token/api_base 仍用 config 全局配置（单一 bot 给多用户推送）。None 时用 config 默认。

    返回 True 表示发出（或 dry_run 模拟成功），False 表示未发（配置缺失/占位符/发送失败）。
    """
    cfg = load_telegram_config()
    if cfg is None:
        # 配置文件不存在=未配置，静默跳过（非失败）
        return False

    token = str(cfg.get("bot_token", "")).strip()
    default_chat = str(cfg.get("chat_id", "")).strip()
    # A12 订阅推送：chat_id 参数优先于 config 默认
    target_chat = str(chat_id).strip() if chat_id else default_chat
    api_base = str(cfg.get("api_base", "https://api.telegram.org")).strip().rstrip("/")

    if (not token or token == PLACEHOLDER_TG_TOKEN
            or not target_chat or target_chat == PLACEHOLDER_TG_CHAT):
        print(f"[notify] telegram bot_token/chat_id 占位符或缺失，跳过发送（subject={subject}）",
              file=sys.stderr)
        return False

    # Telegram 不支持 HTML table，转纯文本；subject + body 拼接
    text = f"{subject}\n\n{_html_to_text(body)}"
    if len(text) > TG_TEXT_LIMIT:
        text = text[: TG_TEXT_LIMIT - 30] + "\n…(已截断)"

    if dry_run:
        print(f"[notify][dry-run] telegram chat={target_chat} api_base={api_base}", file=sys.stderr)
        print(f"[notify][dry-run] telegram text(前200)=\n{text[:200]}", file=sys.stderr)
        return True

    url = f"{api_base}/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": target_chat, "text": text, "parse_mode": ""},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8", "replace"))
        if resp_data.get("ok"):
            print(f"[notify] Telegram 已发送至 {target_chat}：{subject}", file=sys.stderr)
            return True
        print(f"[notify] Telegram API 返回非 ok：{resp_data}", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        # 不抛异常，不阻塞调用方/不阻塞邮件
        print(f"[notify] Telegram 发送失败（不阻塞）：{e}", file=sys.stderr)
        return False


# ── 飞书渠道（自建应用 tenant_access_token + im/v1/messages API）────────────────
# 配置 config/feishu.json（gitignore，feishu.json.example 模板）。app_id/app_secret 默认从
# .env 读（FEISHU_APP_ID/FEISHU_APP_SECRET，存 /Users/linhuichen/code/trade-data/.env），
# 也可在 config/feishu.json 显式覆盖。三群映射：alert=运维群(SEVERE告警+计划任务异常) /
# agent_done=开发群(agent完成+用户提需求) / report=报告群(收盘分析+盘中信号+小时级节点)。
# 邮件兜底保留：飞书失败不阻塞邮件（best-effort），SEVERE 告警邮件始终发（防飞书故障无通知）。


def load_feishu_config() -> dict | None:
    """读 config/feishu.json。不存在/解析失败返回 None（=未配置，静默跳过）。

    2026-08-17 三件套②：缺失/解析失败在 stderr 补恢复指引（cp example -> 重启 listener），
    便于运维/告警排查时一键恢复。send_feishu 会在「缺失但 .env 有凭证」时发邮件告警（见
    _alert_feishu_config_missing）。"""
    if not FEISHU_CONFIG.exists():
        print("[notify] config/feishu.json 不存在（飞书未配置或配置丢失）。恢复："
              "cp config/feishu.json.example config/feishu.json 后重启 com.trade.feishu-listener",
              file=sys.stderr)
        return None
    try:
        return json.loads(FEISHU_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[notify] config/feishu.json 解析失败：{e}。恢复：检查 JSON 格式后重启 "
              f"com.trade.feishu-listener（cp config/feishu.json.example config/feishu.json 重置）",
              file=sys.stderr)
        return None


def _load_feishu_credentials() -> tuple[str, str]:
    """返回 (app_id, app_secret)。优先 config/feishu.json 显式字段（非占位符），
    否则读 .env 的 FEISHU_APP_ID/FEISHU_APP_SECRET（trade-data/.env 优先，trade/.env 兜底）。
    不 echo 凭证值。"""
    app_id, app_secret = "", ""
    cfg = load_feishu_config()
    if cfg:
        app_id = str(cfg.get("app_id", "") or "").strip()
        app_secret = str(cfg.get("app_secret", "") or "").strip()
        if (app_id and app_secret
                and PLACEHOLDER_FEISHU_ID not in app_id
                and PLACEHOLDER_FEISHU_SECRET not in app_secret):
            return app_id, app_secret
    # .env 候选路径（FEISHU 凭证在 trade-data/.env；trade/.env 兜底）
    candidates = [
        Path("/Users/linhuichen/code/trade-data/.env"),
        REPO.parent / "trade-data" / ".env",
        REPO / ".env",
    ]
    found_id, found_secret = "", ""
    for env_path in candidates:
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k == "FEISHU_APP_ID":
                found_id = v.strip()
            elif k == "FEISHU_APP_SECRET":
                found_secret = v.strip()
        if found_id and found_secret:
            break
    return found_id, found_secret


def _feishu_http_post_json(url: str, payload: bytes, headers: dict,
                           timeout: int = 20) -> dict:
    """POST JSON 到飞书 API。本地环境 MITM 代理自签证书致默认校验失败，
    遇到 CERTIFICATE_VERIFY_FAILED 退化为不校验重试一次（仅飞书 API 调用）。"""
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        print("[notify] feishu SSL 校验失败，退化为不校验重试一次（本地 MITM 代理）",
              file=sys.stderr)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _get_tenant_access_token() -> str | None:
    """获取飞书 tenant_access_token（带缓存，2h 有效，过期前 120s 刷新复用）。

    失败返回 None（调用方跳过飞书，不阻塞）。"""
    now = time.time()
    if _FEISHU_TOKEN_CACHE["token"] and _FEISHU_TOKEN_CACHE["expire_at"] > now:
        return _FEISHU_TOKEN_CACHE["token"]
    app_id, app_secret = _load_feishu_credentials()
    if (not app_id or not app_secret
            or PLACEHOLDER_FEISHU_ID in app_id
            or PLACEHOLDER_FEISHU_SECRET in app_secret):
        print("[notify] feishu app_id/app_secret 缺失或占位符，跳过发送"
              "（.env 无 FEISHU_APP_ID/FEISHU_APP_SECRET）", file=sys.stderr)
        return None
    url = f"{FEISHU_API_BASE}/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret},
                         ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        data = _feishu_http_post_json(url, payload, headers)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] Feishu 获取 token 失败（跳过发送，不阻塞）：{e}", file=sys.stderr)
        return None
    if data.get("code") != 0:
        print(f"[notify] Feishu token API 返回非 0：code={data.get('code')} "
              f"msg={data.get('msg')}（跳过发送）", file=sys.stderr)
        return None
    token = str(data.get("tenant_access_token", "") or "")
    if not token:
        print("[notify] Feishu token 响应为空，跳过发送", file=sys.stderr)
        return None
    expire = int(data.get("expire", 7200) or 7200)
    _FEISHU_TOKEN_CACHE["token"] = token
    _FEISHU_TOKEN_CACHE["expire_at"] = now + max(60, expire - 120)
    return token


def _send_feishu_api(chat_id: str, subject: str, text: str,
                     reply_to_message_id: str | None = None,
                     msg_type: str = "text",
                     content: dict | None = None) -> bool:
    """飞书应用模式发送：POST im/v1/messages?receive_id_type=chat_id。

    默认 msg_type=text（content=None 时用 text 构建 {"text": text}，向后兼容）；
    msg_type="post" 时 content 传 build_feishu_post 的 {"zh_cn": ...}（富文本，直接作
    content，实测加 {"post": ...} 外层会报 230001 invalid message content）。
    content 是消息内容 dict，序列化成 JSON 字符串放 body["content"]（im/v1/messages 规范）。

    reply_to_message_id 非空时 body 加 "reply_to_message_id"（飞书引用回复，回复挂靠在
    指定原消息下方，任务状态可挂靠追踪；参数名与 feishu_ws_listener.send_receipt 同款）。

    P1-1（2026-08-11 稳定性修复）：有限重试（3 次指数退避 1s/3s/7s）——网络瞬时错误
    （URLError/HTTP 5xx）与飞书服务端瞬时错误码（99999/9999/10001/10002）重试；
    确定性错误（4xx / token 无效 / 内容非法等）不重试直接返回失败。
    对外签名保持不变（hooks 抄送 agent 可能复用）。
    """
    token = _get_tenant_access_token()
    if not token:
        return False
    url = f"{FEISHU_API_BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    if content is None:
        content = {"text": text}
    content_json = json.dumps(content, ensure_ascii=False)
    body = {"receive_id": chat_id, "msg_type": msg_type, "content": content_json}
    if reply_to_message_id:
        body["reply_to_message_id"] = reply_to_message_id
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Authorization": f"Bearer {token}"}
    last_err = ""
    for attempt in range(_FEISHU_SEND_ATTEMPTS):
        try:
            data = _feishu_http_post_json(url, payload, headers)
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < _FEISHU_SEND_ATTEMPTS - 1:
                last_err = f"HTTP {e.code}"
                wait = float(2 ** attempt + attempt)
                print(f"[notify] Feishu 发送 HTTP {e.code}（第{attempt + 1}/{_FEISHU_SEND_ATTEMPTS}次，"
                      f"{wait}s 后重试）：{subject}", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[notify] Feishu 发送失败（HTTP {e.code}，不重试）：{subject}", file=sys.stderr)
            return False
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            if attempt < _FEISHU_SEND_ATTEMPTS - 1:
                wait = float(2 ** attempt + attempt)
                print(f"[notify] Feishu 发送失败（第{attempt + 1}/{_FEISHU_SEND_ATTEMPTS}次，"
                      f"{wait}s 后重试）：{e}", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[notify] Feishu 发送失败重试耗尽（不阻塞）：{e}", file=sys.stderr)
            return False
        code = data.get("code")
        if code == 0:
            print(f"[notify] Feishu 已发送至 {chat_id}：{subject}", file=sys.stderr)
            return True
        if code in _FEISHU_RETRYABLE_CODES and attempt < _FEISHU_SEND_ATTEMPTS - 1:
            last_err = f"code={code} msg={data.get('msg')}"
            wait = float(2 ** attempt + attempt)
            print(f"[notify] Feishu 瞬时错误码 {code}（第{attempt + 1}/{_FEISHU_SEND_ATTEMPTS}次，"
                  f"{wait}s 后重试）：{subject}", file=sys.stderr)
            time.sleep(wait)
            continue
        print(f"[notify] Feishu API 返回非 0：code={code} msg={data.get('msg')}"
              f"（subject={subject}，不重试）", file=sys.stderr)
        return False
    print(f"[notify] Feishu 发送失败（重试耗尽）：{last_err}（subject={subject}）", file=sys.stderr)
    return False


def _send_feishu_webhook(url: str, subject: str, text: str,
                         msg_type: str = "text",
                         content: dict | None = None) -> bool:
    """飞书 webhook 模式发送（阶段1自定义机器人备用）：POST 群机器人 webhook。

    默认 msg_type=text（content=None 时用 text 构建 {"text": text}）。
    msg_type="post" 时 content 传 build_feishu_post 的 {"zh_cn": ...}，webhook 规范要求
    外层包 {"post": ...}（与 app 模式 im/v1/messages 的 content=直接 zh_cn 不同，
    见 send_feishu 注释）；webhook 的 content 是对象非 JSON 字符串。
    """
    if content is None:
        content = {"text": text}
    if msg_type == "post":
        content = {"post": content}
    payload = json.dumps({"msg_type": msg_type, "content": content},
                         ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        data = _feishu_http_post_json(url, payload, headers)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] Feishu webhook 发送失败（不阻塞）：{e}", file=sys.stderr)
        return False
    if data.get("code") == 0 or data.get("StatusCode") == 0:
        print(f"[notify] Feishu webhook 已发送至 {url[:60]}…：{subject}", file=sys.stderr)
        return True
    print(f"[notify] Feishu webhook API 返回非 0：{data}（subject={subject}）",
          file=sys.stderr)
    return False


def _resolve_feishu_chat_key(subject: str, from_prefix: str | None,
                             severe: bool) -> str:
    """按通知类别路由飞书群：severe/[告警]/[恢复]/[监控] -> alert 群；[完成] -> agent_done 群；
    其余（收盘分析/盘中信号/小时级节点/买卖点信号等）-> report 群。

    [恢复] 与 [告警] 成对（异常发生/恢复闭环），同走 alert 告警群，让运维看到完整闭环。
    2026-08-11 修复：改为方括号内词根匹配（正则 [Xxx告警]/[Xxx恢复]/[Xxx监控] 均命中），
    覆盖 monitor_72h.sh 的 [72h恢复]/[72h监控]——原精确串 [告警]/[恢复] 匹配失败，
    致 [72h恢复] 恢复通知误落 report 报告群（用户反馈"监控消息应发运维群"）。"""
    if severe:
        return "alert"
    hay = f"{from_prefix or ''} {subject}"
    # 方括号内词根匹配：覆盖 [告警]/[恢复]/[监控] 及复合词 [72h恢复]/[72h监控] 等
    # （只匹配方括号内，subject 正文含"监控"等词不误伤）
    if re.search(r"\[[^\]]*(告警|恢复|监控)[^\]]*\]", hay):
        return "alert"
    if "[完成]" in hay:
        return "agent_done"
    return "report"


def _alert_feishu_config_missing(dry_run: bool = False) -> None:
    """飞书配置缺失邮件告警（2026-08-17 三件套①核心）。

    feishu.json 丢失但 .env 已有 FEISHU_APP_ID/FEISHU_APP_SECRET = 配置本该存在却异常
    丢失（曾静默停摆数天），走邮件告警链提醒恢复。全新环境未配置（.env 无凭证）不告警
    （由调用方判定，静默跳过）。走 data/notify_dedup.json 去重（key=feishu_config_missing，
    30min 内不重复发防刷屏）。只发邮件（Telegram 是占位符不用），不调 send_feishu 防递归。
    dry_run=True 时只 print 不真发（供测试验证告警路径）。"""
    dedup_key = "feishu_config_missing"
    dedup_window = 1800  # 30min 内不重复告警
    if not dry_run and check_dedup(dedup_key, dedup_window):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = "[告警] 飞书配置缺失 feishu.json 已丢失"
    body = f"""<div style="font-family: monospace; white-space: pre-wrap;">
<b>[告警] 飞书配置缺失</b>
时间：{now}

现象：config/feishu.json 不存在，但 .env 已有 FEISHU_APP_ID/FEISHU_APP_SECRET
      （说明配置本该存在，异常丢失）。飞书通知已静默停摆。

根因：config/feishu.json 被删除/丢失（gitignore 不随 git 恢复）。

恢复指引：
1. 复制模板恢复：cp config/feishu.json.example config/feishu.json
   （example 已含真实三群 chat_id，凭证走 .env 不填）
2. 确认 chat_ids 三项非空（alert/agent_done/report）
3. 重启 listener：launchctl kickstart -k gui/$(id -u)/com.trade.feishu-listener
4. 校验：python scripts/notify.py --dry-run 测试发送

---
本告警由 notify.py send_feishu 配置缺失触发，30min 内不重复发。
</div>"""
    ok = _send_email(subject, body, dry_run=dry_run, from_prefix="[告警]")
    if ok and not dry_run:
        update_dedup(dedup_key)


def send_feishu(subject: str, body: str, chat_key: str | None = None,
                dry_run: bool = False, severe: bool = False,
                from_prefix: str | None = None,
                reply_to_message_id: str | None = None,
                feishu_post: dict | None = None) -> bool:
    """发飞书群消息（自建应用 im/v1/messages 或 webhook 模式）。

    chat_key 显式指定（alert/agent_done/report）；None 时按 _resolve_feishu_chat_key
    自动映射。配置缺失/enabled=false/占位符 -> 静默跳过（同 Telegram 未配置口径）。
    发送失败只 print 警告不抛异常（不阻塞调用方/不阻塞邮件）。
    返回 True 表示发出（或 dry_run 模拟成功），False 表示未发/失败。

    feishu_post（3 群差异化）：仅 report 群生效——非空时用 post 富文本发送
      （build_feishu_post 产出，买卖点/汪汪队信号消息用，买红/卖绿/持有灰分组+彩色标题，A股红涨绿跌约定）。
      alert/agent_done 群忽略 feishu_post 保持简短 text（可读性已够，不破坏现有格式）。

    reply_to_message_id（引用回复）：非空时应用模式 body 加 reply_to_message_id，
    把消息作为对指定消息 ID 的引用回复发送（挂靠原消息下追踪）。webhook 模式不支持
    引用回复（im/v1/messages 专属能力），忽略此参数。email/telegram 忽略此参数。
    """
    cfg = load_feishu_config()
    if cfg is None:
        # 三件套①：配置缺失但 .env 有 FEISHU 凭证 = 配置本该存在却异常丢失 -> 发邮件告警。
        # 全新环境未配置（.env 无凭证）则静默跳过，避免误报。
        _app_id, _app_secret = _load_feishu_credentials()
        if _app_id and _app_secret:
            _alert_feishu_config_missing(dry_run=dry_run)
        else:
            print("[notify] config/feishu.json 缺失且 .env 无 FEISHU 凭证（全新环境未配置），静默跳过",
                  file=sys.stderr)
        return False
    if not cfg.get("enabled", True):
        return False
    if chat_key is None:
        chat_key = _resolve_feishu_chat_key(subject, from_prefix, severe)
    chat_ids = cfg.get("chat_ids") or {}
    chat_id = str(chat_ids.get(chat_key, "") or "").strip()
    if not chat_id:
        print(f"[notify] feishu 群 {chat_key} 未配置 chat_id，跳过发送", file=sys.stderr)
        return False
    # 消息内容：report 群 + feishu_post 非空 -> post 富文本；否则 text（_html_to_text 拍平）。
    # 注意：im/v1/messages（app 模式）的 post content = {"zh_cn": {...}} 直接传（无 post 外层包，
    # 实测加 {"post": ...} 外层会报 230001 invalid message content）；webhook 模式才需 post 外层包
    # （_send_feishu_webhook 内部处理）。build_feishu_post 已返回 {"zh_cn": ...}。
    msg_type, content = "text", None
    post_segments: list[dict] | None = None  # 分段 post（仅 report 群 + 超行数时非 None）
    if feishu_post and chat_key == "report":
        # 超 FEISHU_POST_MAX_ROWS 行时按每段切分、多段连发（标题带 N/M 序号），绝不省略行
        # （2026-08-16 用户定：放开行数+超长分段连发，和页面一致，不丢细讲/风险/辩论/角色）。
        decoded = feishu_post.get("zh_cn", {})
        rows = decoded.get("content", [])
        if len(rows) > FEISHU_POST_MAX_ROWS:
            post_segments = _split_post_segments(feishu_post, FEISHU_POST_MAX_ROWS)
            log_text = (f"{subject}\n\n[post 富文本 {len(rows)} 行超上限，"
                        f"分段 {len(post_segments)} 条连发]")
        else:
            msg_type, content = "post", feishu_post
            log_text = f"{subject}\n\n[post 富文本 {len(rows)} 行]"
    else:
        log_text = f"{subject}\n\n{_html_to_text(body)}"
        if len(log_text) > FEISHU_TEXT_LIMIT:
            # 保留头部（信息量优先：subject+正文开头），截尾部
            log_text = log_text[: FEISHU_TEXT_LIMIT - 30] + "\n…(已截断)"
    if dry_run:
        print(f"[notify][dry-run] feishu group={chat_key} chat_id={chat_id}", file=sys.stderr)
        if reply_to_message_id:
            print(f"[notify][dry-run] feishu reply_to_message_id={reply_to_message_id}",
                  file=sys.stderr)
        print(f"[notify][dry-run] feishu msg_type={msg_type} text(前200)=\n{log_text[:200]}",
              file=sys.stderr)
        return True
    mode = str(cfg.get("mode", "app") or "app").lower()
    if mode == "webhook":
        url = str((cfg.get("webhook_urls") or {}).get(chat_key, "") or "").strip()
        if not url:
            print(f"[notify] feishu webhook 模式但群 {chat_key} 未配置 webhook_urls，跳过",
                  file=sys.stderr)
            return False
        # webhook 模式不支持引用回复（im/v1/messages 专属能力），忽略 reply_to_message_id
        # 分段：每段一个 webhook 消息连发
        if post_segments is not None:
            ok = True
            for i, pd in enumerate(post_segments, 1):
                if not _send_feishu_webhook(url, subject,
                                            f"[post 第{i}/{len(post_segments)}段]",
                                            msg_type="post", content=pd):
                    ok = False
            return ok
        return _send_feishu_webhook(url, subject, log_text,
                                    msg_type=msg_type, content=content)
    # 分段：每段一次 im/v1/messages 调用连发（首条带原 subject，后续 post 标题已含 N/M）
    if post_segments is not None:
        ok = True
        for i, pd in enumerate(post_segments, 1):
            if not _send_feishu_api(chat_id, subject, f"[post 第{i}/{len(post_segments)}段]",
                                    reply_to_message_id=reply_to_message_id,
                                    msg_type="post", content=pd):
                ok = False
        return ok
    return _send_feishu_api(chat_id, subject, log_text,
                            reply_to_message_id=reply_to_message_id,
                            msg_type=msg_type, content=content)


def _send_email(subject: str, body: str, dry_run: bool = False,
                to: str | None = None, from_prefix: str | None = None) -> bool:
    """发邮件（内部，由 send()/send_to() 调用）。dry_run=True 只 print 不真发。

    发送失败只 print 警告不抛异常。返回 True 表示发出（或 dry_run 模拟成功），
    False 表示未发（配置缺失/占位符/发送失败）。

    to 参数（A12 订阅推送用）：指定收件人邮箱，覆盖 config 的 to。
      SMTP user/password 仍用 config 全局配置（单一发件邮箱给多收件人推送）。None 时用 config 默认。

    from_prefix 参数（2026-07-20 改造）：发件人名前缀。
      - None/空：用默认 "信号实验室监控"
      - 非空（如 "[告警]"）：用 "<prefix> 信号实验室"（前缀后加空格）
    """
    if dry_run:
        print(f"[notify][dry-run] email subject={subject} to={to or '(config默认)'}", file=sys.stderr)
        print(f"[notify][dry-run] email body=\n{body}", file=sys.stderr)
        return True

    cfg = load_email_config()
    if cfg is None:
        return False

    smtp = cfg.get("smtp", "smtp.163.com")
    port = int(cfg.get("port", 465))
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    # 发件人地址：优先用 from 字段（如 Resend 已验证域 hi@fx8.store），
    # 缺省回退到 user（163 场景 user=发件邮箱）。认证仍用 user/password（Resend=resend/API key）。
    from_addr = cfg.get("from") or user
    default_to = cfg.get("to", user)
    # A12 订阅推送：to 参数优先于 config 默认
    to_addr = to if to else default_to

    if not user or not password or password == PLACEHOLDER_PASSWORD:
        print(f"[notify] SMTP password 占位符或缺失，跳过发送（subject={subject}）", file=sys.stderr)
        return False

    # 发件人名：from_prefix 非空 -> "<prefix> 信号实验室"；None/空 -> "信号实验室监控"（默认）
    if from_prefix:
        from_name = f"{from_prefix} 信号实验室"
    else:
        from_name = "信号实验室监控"

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)

    try:
        # 本地 python 默认 SSL 证书链缺失会 CERTIFICATE_VERIFY_FAILED，用 certifi 证书
        ctx = ssl.create_default_context(cafile=certifi.where())
        with smtplib.SMTP_SSL(smtp, port, timeout=30, context=ctx) as srv:
            srv.login(user, password)
            srv.sendmail(from_addr, [to_addr], msg.as_string())
        print(f"[notify] 邮件已发送至 {to_addr}：{subject}", file=sys.stderr)
        return True
    except Exception as e:  # noqa: BLE001
        # 不抛异常，不阻塞调用方
        print(f"[notify] 邮件发送失败（不阻塞）：{e}", file=sys.stderr)
        return False


def send(subject: str, body: str, severe: bool = False, dry_run: bool = False,
         from_prefix: str | None = None, feishu_group: str | None = None,
         feishu_only: bool = False,
         reply_to_message_id: str | None = None,
         feishu_post: dict | None = None) -> dict:
    """多渠道分发通知（邮件 + Telegram + 飞书）。各渠道独立失败不互相阻塞。

    先邮件后 Telegram 再飞书，任一渠道失败不影响其他。返回聚合结果：
      {"email": bool, "telegram": bool, "feishu": bool}，True 表示该渠道发出
      （或 dry_run 模拟成功），False 表示未发（配置缺失/占位符/发送失败）。

    severe=True 时写 data/alerts/latest.md（--alert-issue 配合）。
      2026-07-20 改造：subject 前缀由调用方控制（统一 [告警]/[完成]/[恢复] 模板），
      SEVERE_PREFIX 已置空串，--severe 不再修改 subject。
    dry_run=True 所有渠道都只 print 不真发。
    from_prefix：邮件发件人名前缀（None=默认 "信号实验室监控"，非空如 "[告警]" -> "[告警] 信号实验室"）。
    feishu_group：飞书群 key 显式覆盖自动路由（alert/agent_done/report）；None=按
      severe/[告警]/[完成]/[恢复] 自动映射（见 _resolve_feishu_chat_key）。
    feishu_only：True 时只发飞书（跳过邮件/Telegram），调试用。
    reply_to_message_id（引用回复）：仅飞书应用模式生效，透传给 send_feishu -> _send_feishu_api，
      body 加 reply_to_message_id 回复挂靠原消息；email/telegram 忽略此参数。
    feishu_post（2026-08-11 飞书格式模板）：post 富文本数据（build_feishu_post 产出）。
      仅 report 群生效（买卖点/汪汪队信号消息用），alert/agent_done 群忽略保持 text。
    邮件兜底保留：飞书失败不阻塞、邮件照发（SEVERE 告警邮件始终发，防飞书故障无通知）。
    """
    if severe:
        subject = SEVERE_PREFIX + subject
    email_ok = _send_email(subject, body, dry_run=dry_run, from_prefix=from_prefix) if not feishu_only else False
    tg_ok = send_telegram(subject, body, dry_run=dry_run) if not feishu_only else False
    fs_ok = send_feishu(subject, body, chat_key=feishu_group, dry_run=dry_run,
                        severe=severe, from_prefix=from_prefix,
                        reply_to_message_id=reply_to_message_id,
                        feishu_post=feishu_post)
    return {"email": email_ok, "telegram": tg_ok, "feishu": fs_ok}


def send_to(subject: str, body: str, email: str | None = None,
            chat_id: str | None = None, dry_run: bool = False,
            from_prefix: str | None = None, feishu_group: str | None = None,
            feishu_only: bool = False,
            feishu_post: dict | None = None) -> dict:
    """A12 订阅推送：指定收件人（email/chat_id）多渠道分发。

    与 send() 区别：send() 用 config 全局 to/chat_id（单一管理员）；
    send_to() 接收 email/chat_id 参数，给订阅者独立推送（SMTP user/password、
    bot_token/api_base 仍用 config 全局配置，单一发件方给多收件人）。

    email/chat_id 任一为 None/空则跳过该渠道。各渠道独立失败不互相阻塞。
    返回 {"email": bool, "telegram": bool, "feishu": bool}。
    from_prefix：邮件发件人名前缀（None=默认 "信号实验室监控"）。
    feishu_group：飞书群 key（None=按前缀自动映射，订阅信号推送默认进 report 报告群）。
    feishu_post（2026-08-11 飞书格式模板）：post 富文本数据（build_feishu_post 产出），
      仅 report 群生效，alert/agent_done 群忽略保持 text。
    """
    email_ok = _send_email(subject, body, dry_run=dry_run, to=email, from_prefix=from_prefix) if email and not feishu_only else False
    tg_ok = send_telegram(subject, body, dry_run=dry_run, chat_id=chat_id) if chat_id and not feishu_only else False
    fs_ok = send_feishu(subject, body, chat_key=feishu_group, dry_run=dry_run,
                        severe=False, from_prefix=from_prefix,
                        feishu_post=feishu_post)
    return {"email": email_ok, "telegram": tg_ok, "feishu": fs_ok}


def write_alert(issue: str, detail: str, log_path: str | None = None) -> None:
    """覆盖式写 data/alerts/latest.md（最新一次严重告警）。

    内容含时间、问题、详情、日志路径、提示 Claude 开工排查。
    """
    try:
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] alerts 目录创建失败：{e}", file=sys.stderr)
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"- **日志路径**：`{log_path}`\n" if log_path else ""
    content = f"""# 严重告警（最新一次）

> ⚠ 本文件覆盖式记录最新一次严重告警，Claude 开工时优先排查。
> 处理完后可删除本文件或清空（无新告警则保持旧内容）。

- **告警时间**：{now}
- **问题**：{issue}

## 详情

{detail}

{log_line}
## 处理提示

Claude 开工时排查此告警：对照日志路径定位根因，修复后删除本文件。
"""
    try:
        ALERTS_FILE.write_text(content, encoding="utf-8")
        print(f"[notify] 告警已写入 {ALERTS_FILE}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] 告警写入失败：{e}", file=sys.stderr)


def check_dedup(key: str, window: int) -> bool:
    """检查去重：dedup_key 在 window 秒内已告警过则返回 True（suppress 不重发）。

    读 data/notify_dedup.json（独立于 schedule_monitor 的 alert_state.json，互不污染）。
    文件不存在/解析失败/key 不存在/last_alerted 缺失 -> 返回 False（不 suppress，正常发送）。
    用于 intraday_snapshot.sh upload-index R2 失败告警去重：
    R2 偶发 HTTP 500 自愈但单文件失败已致 ok!=total -> 每轮 intraday(15min)发一次告警邮件轰炸，
    加 --dedup-key intraday_upload_index_r2_fail --dedup-window 1800 实现 30min 内不重发。
    """
    if not key or window <= 0:
        return False
    try:
        if not DEDUP_FILE.exists():
            return False
        with open(DEDUP_FILE, encoding="utf-8") as f:
            state = json.load(f)
        info = state.get(key)
        if not info:
            return False
        last = info.get("last_alerted")
        if not last:
            return False
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        age = (datetime.now() - last_dt).total_seconds()
        if age < window:
            print(f"[notify][dedup] suppress key={key} last_alerted={last} "
                  f"age={int(age)}s < window={window}s, 不重发", file=sys.stderr)
            return True
    except Exception as e:  # noqa: BLE001
        # 去重检查失败不影响发送（fail-open，宁可多发不漏发）
        print(f"[notify][dedup] 检查失败(不 suppress，正常发送)：{e}", file=sys.stderr)
    return False


def update_dedup(key: str) -> None:
    """发送**成功**后更新 dedup_key 的 last_alerted 为当前时间。

    P1-1（2026-08-11 稳定性修复）：语义改为"发送成功才更新"——调用方须在确认至少一个
    渠道发送成功后才调用本函数；发送失败不更新 dedup，下次调用可重发（原"无论成败已尝试
    即更新"在偶发发送失败时会导致该消息永久不发，已改）。本函数只管写状态，成功与否由
    调用方判定。
    """
    if not key:
        return
    try:
        DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        state: dict = {}
        if DEDUP_FILE.exists():
            try:
                with open(DEDUP_FILE, encoding="utf-8") as f:
                    state = json.load(f)
                if not isinstance(state, dict):
                    state = {}
            except Exception:  # noqa: BLE001
                state = {}
        state[key] = {"last_alerted": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        DEDUP_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[notify][dedup] 更新 key={key} last_alerted=now", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[notify][dedup] 更新失败(不影响本次发送)：{e}", file=sys.stderr)


def notify_agent_done(agent_name: str, summary: str, dry_run: bool = False,
                      feishu_group: str | None = None,
                      reply_to_message_id: str | None = None) -> dict:
    """agent 完成通知：发邮件(+Telegram+飞书 若配置)直达用户，绕过主控消息队列。

    主控消息队列瓶颈（680 enqueue 仅 313 dequeue=54% 丢失）致 SendMessage/
    task-notification 丢失率高。本函数直接调 send() 发邮件/TG/飞书到用户，不经过主控队列。
    飞书固定发到 agent_done 群（开发群，feishu_group 可显式覆盖）。

    去重：同一 agent 5 分钟(300s)内不重复发（dedup_key=agent_done_<name>），
    防 agent 反复 came to rest 多次完成通知轰炸。

    参数：
      agent_name: agent 名称（如 "notify-research"）
      summary: 完成结论摘要（纯文本，会转 HTML 发送）
      dry_run: True 只 print 不真发
      feishu_group: 飞书群 key 覆盖（默认 agent_done 开发群）

    返回 {"email": bool, "telegram": bool, "feishu": bool}
          （suppress 时额外含 "suppressed": True）。
    """
    dedup_key = f"agent_done_{agent_name}"
    dedup_window = 300  # 5 分钟内同一 agent 不重复发

    # 去重检查
    if not dry_run and check_dedup(dedup_key, dedup_window):
        print(f"[notify][agent-done] suppress {agent_name} 5min 内已发过", file=sys.stderr)
        return {"email": False, "telegram": False, "feishu": False, "suppressed": True}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"\U0001f916 agent {agent_name} 完成"
    body = f"""<div style="font-family: monospace; white-space: pre-wrap;">
<b>\U0001f916 Agent 完成通知</b>
时间：{now}
Agent：{agent_name}

结论摘要：
{summary}

---
本通知由 notify.py notify_agent_done() 直发，绕过主控消息队列。
</div>"""

    results = send(subject, body, dry_run=dry_run, from_prefix="[完成]",
                   feishu_group=feishu_group or "agent_done",
                   reply_to_message_id=reply_to_message_id)

    # P1-1：发送成功才更新 dedup（失败不标记，下次可重发——避免偶发失败致该消息永久不发）
    if not dry_run and any(results.values()):
        update_dedup(dedup_key)

    return results


def _append_jsonl(path: Path, rec: dict) -> None:
    """jsonl 追加（flock 防并发交错；schedule_monitor 15min / monitor_72h 30min 错峰，
    同刻概率低但 flock 保险）。失败只 print 不抛（分级降噪绝不反噬主告警链路）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] jsonl 写入失败 {path.name}：{e}", file=sys.stderr)


def _read_jsonl(path: Path) -> list[dict]:
    """读 jsonl 全部行；文件不存在/解析失败返回 []（fail-open 不丢推送）。"""
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as e:  # noqa: BLE001
        print(f"[notify] jsonl 读取失败 {path.name}：{e}", file=sys.stderr)
    return out


def log_info(subject: str, detail: str = "") -> bool:
    """info 级：只记 dashboard（data/alerts/info_log.jsonl），不推送任何渠道。

    用途：单次瞬时抖动自愈 / acknowledged 窗口内的重复提醒。供排查与页面展示；
    文件增长控制：>2000 行时截断保留最近 1000 行（dashboard 是滚动日志非审计账本）。
    """
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "subject": subject}
    if detail:
        rec["detail"] = str(detail)[:500]
    _append_jsonl(INFO_LOG_FILE, rec)
    # 截断防无限增长（best-effort）
    try:
        lines = INFO_LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > 2000:
            INFO_LOG_FILE.write_text(
                "\n".join(lines[-1000:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(f"[notify][info] 记 dashboard 不推送：{subject}", file=sys.stderr)
    return True


def defer_warning(subject: str, body: str, from_prefix: str | None = None) -> bool:
    """warning 级：写入聚合 buffer（warning_buffer.jsonl），等 flush_warning_batch 批发。

    不直接推送——由 schedule_monitor/monitor_72h 每轮尾部调 flush_warning_batch()，
    满 WARNING_BATCH_WINDOW(30min) 的条目聚合成一封发出（高概率自愈类延迟可达用户可接受，
    换取瞬时抖动不轰炸）。
    """
    _append_jsonl(WARNING_BUFFER_FILE, {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subject": subject,
        "body": str(body)[:3000],
        "from_prefix": from_prefix or "[告警·聚合]",
    })
    print(f"[notify][warning] 入聚合 buffer（30min 批发）：{subject}", file=sys.stderr)
    return True


def flush_warning_batch(dry_run: bool = False) -> dict:
    """把 buffer 中满 30min 窗口的 warning 条目聚合成一封发出（未满窗口的留下轮）。

    返回 {"sent_batch": bool, "n_due": int, "n_remaining": int}。
    - due 条目全部合并为一条消息（标题 N 条聚合 + 正文逐条列出，内容一条不少——
      与 §23.10「拆条拼接不精简」同精神），走 critical 同款渠道（邮件+飞书 alert 群），
      from_prefix 默认 [告警·聚合]。
    - 发送成功才清掉已发条目（失败留下轮重试，宁可重发不丢告警）。
    - dry_run=True 只打印不发不清（自验用）。
    - 竞态安全（2026-08-24 reviewer P2）：读取阶段在 flock 内做快照并记下文件字节数
      pre_offset；发送期间（邮件+飞书重试可达秒级）其他进程 defer_warning 追加的条目
      全部落在 pre_offset 之后，重写阶段只回写 keep + pre_offset 之后的新增行，
      不再整文件覆盖——旧实现 open("w") 先 truncate 后才 flock，窗口内新追加条目被静默清掉。
    """
    import fcntl
    try:
        with open(WARNING_BUFFER_FILE, "rb") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            raw = f.read()
            fcntl.flock(f, fcntl.LOCK_UN)
    except FileNotFoundError:
        return {"sent_batch": False, "n_due": 0, "n_remaining": 0}
    except OSError as e:
        print(f"[notify] warning buffer 读取失败：{e}", file=sys.stderr)
        return {"sent_batch": False, "n_due": 0, "n_remaining": 0}
    pre_offset = len(raw)  # 锁内快照字节数（行边界；append 单行持锁写入）
    entries = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 坏行跳过（fail-open 不丢推送，同 _read_jsonl 口径）
    if not entries:
        return {"sent_batch": False, "n_due": 0, "n_remaining": 0}
    now = datetime.now()
    due, keep = [], []
    for e in entries:
        try:
            ts = datetime.strptime(str(e.get("ts", "")), "%Y-%m-%d %H:%M:%S")
            (due if (now - ts).total_seconds() >= WARNING_BATCH_WINDOW else keep).append(e)
        except ValueError:
            due.append(e)  # 时间戳坏行按到期处理（不静默积压）
    if not due:
        return {"sent_batch": False, "n_due": 0, "n_remaining": len(keep)}
    n = len(due)
    subject = f"[告警·聚合] {n}条 warning 汇总 {now.strftime('%m-%d %H:%M')}"
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    body = "<hr>".join(
        f"<b>{esc(e.get('ts', ''))} {esc(e.get('subject', ''))}</b><br>{esc(e.get('body', ''))}"
        for e in due
    )
    prefix = str(due[0].get("from_prefix") or "[告警·聚合]")
    results = send(subject, body, severe=False, dry_run=dry_run,
                   from_prefix=prefix, feishu_group="alert")
    sent = any(results.values())
    if sent and not dry_run:
        # 发送成功才清已发条目。不整文件覆盖：flock 内重读当前内容，pre_offset 之后的
        # 字节 = 发送期间其他进程 defer_warning 追加的新条目，原样保留（下轮照发）；
        # truncate 在锁内做，杜绝旧实现「先 truncate 后 flock」窗口丢条目。
        # 不用 tmp+rename：rename 换 inode 后，阻塞在本文件 flock 上的 append 方
        # 醒来会写到旧 inode（孤儿 fd），条目静默丢失——原地重写保住同一 inode，
        # 与 _append_jsonl 的 flock-append 互斥语义一致，且持锁仅毫秒级。
        try:
            with open(WARNING_BUFFER_FILE, "rb+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                cur = f.read()
                tail = [ln for ln in cur[pre_offset:].splitlines() if ln.strip()]
                out = b"".join(
                    json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n"
                    for e in keep
                )
                out += b"".join(ln.rstrip(b"\r") + b"\n" for ln in tail)
                f.seek(0)
                f.truncate()
                f.write(out)
                f.flush()
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:  # noqa: BLE001
            print(f"[notify] warning buffer 清理失败（下轮可能重发）：{e}", file=sys.stderr)
    print(f"[notify][warning] 批发 {n} 条（剩余 {len(keep)} 条未满窗口）："
          f"{'已发' if sent else '发送失败留待下轮'}", file=sys.stderr)
    return {"sent_batch": sent, "n_due": n, "n_remaining": len(keep)}


def send_tiered(subject: str, body: str, tier: str = TIER_CRITICAL,
                dry_run: bool = False, from_prefix: str | None = None,
                feishu_group: str | None = None,
                reply_to_message_id: str | None = None) -> dict:
    """三级分级统一入口（2026-08-24）。按 tier 路由：

    - critical：立即全渠道（=send(severe=True)，真故障即时可达用户，冻结契约不变）
    - warning：defer_warning 入 buffer，30min 聚合批发（调用方须在其监控循环尾部
      定期调 flush_warning_batch() 完成实际发送）
    - info：log_info 只记 dashboard 不推送

    返回 dict 含 tier 字段便于调用方日志。未知 tier 按 critical 处理（fail-critical：
    分级配置错误时宁多勿漏，绝不因降级逻辑吞掉真故障）。
    """
    if tier not in (TIER_CRITICAL, TIER_WARNING, TIER_INFO):
        # fail-critical（2026-08-24 reviewer P2 兑现本 docstring 承诺）：tier 不在
        # 白名单一律按 critical 立即全渠道发送，并 log 一行便于暴露拼写错误调用方；
        # 空/None 视为缺省 critical 不打告警（与旧「缺省走 send()」向后兼容语义一致）。
        if tier:
            print(f"[notify][tier] 未知 tier={tier!r} 按 critical 处理"
                  f"(fail-critical 宁多勿漏)", file=sys.stderr)
        tier = TIER_CRITICAL
    if tier == TIER_INFO:
        log_info(subject, body)
        return {"tier": tier, "email": False, "telegram": False, "feishu": False, "info_logged": True}
    if tier == TIER_WARNING:
        defer_warning(subject, body, from_prefix=from_prefix)
        return {"tier": tier, "email": False, "telegram": False, "feishu": False, "deferred": True}
    res = send(subject, body, severe=(tier == TIER_CRITICAL), dry_run=dry_run,
               from_prefix=from_prefix, feishu_group=feishu_group,
               reply_to_message_id=reply_to_message_id)
    return {"tier": tier, **res}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="update_all 监控通知（邮件 + Telegram + alerts 文件）"
    )
    parser.add_argument("subject", nargs="?", default="",
                        help="主题（--agent-done 模式下为结论摘要；--flush-warnings 模式可省略）")
    parser.add_argument("body", nargs="?", default="", help="正文（HTML，邮件原样发送；Telegram 转纯文本）。"
                        "--agent-done 模式下可省略")
    parser.add_argument("--severe", action="store_true",
                        help="严重标记：用于 write_alert 语义（2026-07-20 改造：不再修改 subject 前缀）")
    parser.add_argument("--tier", choices=[TIER_CRITICAL, TIER_WARNING, TIER_INFO], default=None,
                        help="告警三级分级（2026-08-24）：critical=立即邮件+飞书 alert 群；"
                             "warning=入 buffer 由 --flush-warnings 30min 聚合批发；"
                             "info=只记 dashboard(data/alerts/info_log.jsonl) 不推送。"
                             "缺省=走原 send() 行为（向后兼容，既有调用方零改动）")
    parser.add_argument("--flush-warnings", action="store_true",
                        help="批发 warning 聚合 buffer 中满 30min 窗口的条目（schedule_monitor/"
                             "monitor_72h 每轮尾部调用），发送成功才清已发条目")
    parser.add_argument("--alert-issue", help="写 data/alerts/latest.md，值为问题一句话")
    parser.add_argument("--alert-log", help="配合 --alert-issue，日志文件路径")
    parser.add_argument("--agent-done", metavar="NAME", default=None,
                        help="agent 完成通知模式：NAME=agent 名，subject=结论摘要。"
                             "发邮件(+TG)直达用户绕过主控队列，5min 去重防轰炸。"
                             "用于解决 SendMessage/task-notification 丢失率高的问题")
    parser.add_argument("--dedup-key", help="去重 key：同 key 在 --dedup-window 秒内不重发（suppress 静默退出 0）。"
                        "用于 intraday 等 15min 周期任务防 R2 偶发失败轰炸（写入 data/notify_dedup.json）")
    parser.add_argument("--dedup-window", type=int, default=1800, help="去重窗口秒数（默认 1800=30min）")
    parser.add_argument("--dry-run", action="store_true", help="不真发，只 print 到 stderr")
    parser.add_argument("--from-prefix", default=None,
                        help="邮件发件人名前缀（如 [告警]/[完成]/[恢复]）；"
                             "None/空=默认 '信号实验室监控'，非空 -> '<prefix> 信号实验室'")
    parser.add_argument("--feishu-group", default=None, metavar="KEY",
                        help="飞书群 key 显式覆盖自动路由：alert=运维群 / agent_done=开发群"
                             " / report=报告群。默认按 severe/[告警]/[完成]/[恢复] 自动映射")
    parser.add_argument("--feishu-only", action="store_true",
                        help="调试用：只发飞书（跳过邮件/Telegram）")
    parser.add_argument("--reply-to-message-id", default=None, metavar="ID",
                        help="飞书引用回复：把消息作为对指定消息 ID 的引用回复发送"
                             "（body 加 reply_to_message_id，回复挂靠在原消息下方，"
                             "任务状态可挂靠追踪）。仅飞书应用模式生效，email/telegram 忽略")
    args = parser.parse_args(argv)

    # warning 聚合批发模式（schedule_monitor/monitor_72h 每轮尾部调用）
    if args.flush_warnings:
        r = flush_warning_batch(dry_run=args.dry_run)
        print(f"[notify] flush-warnings: {r}", file=sys.stderr)
        return 0

    # 三级分级路由（--tier 显式指定时走分级入口；缺省保持原 send() 行为向后兼容）
    if args.tier:
        res = send_tiered(args.subject, args.body, tier=args.tier, dry_run=args.dry_run,
                          from_prefix=args.from_prefix, feishu_group=args.feishu_group,
                          reply_to_message_id=args.reply_to_message_id)
        print(f"[notify][tier={args.tier}] 路由完成：{res}", file=sys.stderr)
        # critical 且带 --alert-issue 仍写 latest.md（与原 severe 语义对齐）
        if args.tier == TIER_CRITICAL and args.alert_issue:
            write_alert(args.alert_issue, args.body or args.subject, log_path=args.alert_log)
        return 0

    # agent 完成通知模式：subject=结论摘要，直达用户绕过主控队列
    if args.agent_done:
        results = notify_agent_done(args.agent_done, args.subject, dry_run=args.dry_run,
                                    feishu_group=args.feishu_group,
                                    reply_to_message_id=args.reply_to_message_id)
        if results.get("suppressed"):
            return 0
        ok = [ch for ch, v in results.items() if v]
        fail = [ch for ch, v in results.items() if not v and ch != "suppressed"]
        if ok:
            print(f"[notify][agent-done] 汇总：已发出 {'/'.join(ok)}"
                  + (f"（未发出：{'/'.join(fail)}）" if fail else ""), file=sys.stderr)
        else:
            print(f"[notify][agent-done] 汇总：全部渠道未发出（{'/'.join(fail) or '无渠道'}）", file=sys.stderr)
        return 0

    # 去重检查：window 内已告警过则 suppress 静默退出（返回 0，不阻塞调用方）
    # dry-run 不走去重（测试用，需看到发送日志）
    if args.dedup_key and not args.dry_run and check_dedup(args.dedup_key, args.dedup_window):
        return 0

    results = send(args.subject, args.body, severe=args.severe, dry_run=args.dry_run,
                   from_prefix=args.from_prefix, feishu_group=args.feishu_group,
                   feishu_only=args.feishu_only,
                   reply_to_message_id=args.reply_to_message_id)
    ok = [ch for ch, v in results.items() if v]
    fail = [ch for ch, v in results.items() if not v]
    if ok:
        print(f"[notify] 汇总：已发出 {'/'.join(ok)}"
              + (f"（未发出：{'/'.join(fail)}）" if fail else ""), file=sys.stderr)
    else:
        print(f"[notify] 汇总：全部渠道未发出（{'/'.join(fail) or '无渠道'}）", file=sys.stderr)

    # P1-1：发送成功才更新 dedup（失败不标记，下次可重发——避免偶发失败致该消息永久不发）
    if args.dedup_key and not args.dry_run and ok:
        update_dedup(args.dedup_key)

    if args.alert_issue:
        write_alert(args.alert_issue, args.body, log_path=args.alert_log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
