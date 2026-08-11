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
  notify.py --agent-done <name> <summary> [--dry-run]
             （agent 完成通知：发邮件直达用户绕过主控队列，5min 去重防轰炸；飞书固定发开发群）

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

# 飞书 tenant_access_token 缓存（2h 有效，过期前 120s 刷新复用）
_FEISHU_TOKEN_CACHE: dict = {"token": None, "expire_at": 0.0}
# 飞书 open.feishu.cn（中国版域名）
FEISHU_API_BASE = "https://open.feishu.cn"

# SEVERE_PREFIX 保留空串（2026-07-20 改造：由调用方在 subject 表达严重程度，统一 [告警] 前缀）。
# --severe 标记仍用于 write_alert 写 data/alerts/latest.md（独立于 subject 前缀）。
SEVERE_PREFIX = ""


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
    """读 config/feishu.json。不存在/解析失败返回 None（=未配置，静默跳过）。"""
    if not FEISHU_CONFIG.exists():
        return None
    try:
        return json.loads(FEISHU_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[notify] config/feishu.json 解析失败：{e}", file=sys.stderr)
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


def _send_feishu_api(chat_id: str, subject: str, text: str) -> bool:
    """飞书应用模式发送：POST im/v1/messages?receive_id_type=chat_id（text 消息）。"""
    token = _get_tenant_access_token()
    if not token:
        return False
    url = f"{FEISHU_API_BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    content = json.dumps({"text": text}, ensure_ascii=False)
    payload = json.dumps({"receive_id": chat_id, "msg_type": "text", "content": content},
                         ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Authorization": f"Bearer {token}"}
    try:
        data = _feishu_http_post_json(url, payload, headers)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] Feishu 发送失败（不阻塞）：{e}", file=sys.stderr)
        return False
    if data.get("code") == 0:
        print(f"[notify] Feishu 已发送至 {chat_id}：{subject}", file=sys.stderr)
        return True
    print(f"[notify] Feishu API 返回非 0：code={data.get('code')} "
          f"msg={data.get('msg')}（subject={subject}）", file=sys.stderr)
    return False


def _send_feishu_webhook(url: str, subject: str, text: str) -> bool:
    """飞书 webhook 模式发送（阶段1自定义机器人备用）：POST 群机器人 webhook。"""
    payload = json.dumps({"msg_type": "text", "content": {"text": text}},
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
    """按通知类别路由飞书群：severe/[告警] -> alert 群；[完成]/[恢复] -> agent_done 群；
    其余（收盘分析/盘中信号/小时级节点/买卖点信号等）-> report 群。"""
    if severe:
        return "alert"
    hay = f"{from_prefix or ''} {subject}"
    if "[告警]" in hay:
        return "alert"
    if "[完成]" in hay or "[恢复]" in hay:
        return "agent_done"
    return "report"


def send_feishu(subject: str, body: str, chat_key: str | None = None,
                dry_run: bool = False, severe: bool = False,
                from_prefix: str | None = None) -> bool:
    """发飞书群消息（自建应用 im/v1/messages 或 webhook 模式）。

    chat_key 显式指定（alert/agent_done/report）；None 时按 _resolve_feishu_chat_key
    自动映射。配置缺失/enabled=false/占位符 -> 静默跳过（同 Telegram 未配置口径）。
    发送失败只 print 警告不抛异常（不阻塞调用方/不阻塞邮件）。
    返回 True 表示发出（或 dry_run 模拟成功），False 表示未发/失败。
    """
    cfg = load_feishu_config()
    if cfg is None:
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
    text = f"{subject}\n\n{_html_to_text(body)}"
    if len(text) > FEISHU_TEXT_LIMIT:
        text = text[: FEISHU_TEXT_LIMIT - 30] + "\n…(已截断)"
    if dry_run:
        print(f"[notify][dry-run] feishu group={chat_key} chat_id={chat_id}", file=sys.stderr)
        print(f"[notify][dry-run] feishu text(前200)=\n{text[:200]}", file=sys.stderr)
        return True
    mode = str(cfg.get("mode", "app") or "app").lower()
    if mode == "webhook":
        url = str((cfg.get("webhook_urls") or {}).get(chat_key, "") or "").strip()
        if not url:
            print(f"[notify] feishu webhook 模式但群 {chat_key} 未配置 webhook_urls，跳过",
                  file=sys.stderr)
            return False
        return _send_feishu_webhook(url, subject, text)
    return _send_feishu_api(chat_id, subject, text)


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
    msg["From"] = formataddr((from_name, user))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)

    try:
        with smtplib.SMTP_SSL(smtp, port, timeout=30) as srv:
            srv.login(user, password)
            srv.sendmail(user, [to_addr], msg.as_string())
        print(f"[notify] 邮件已发送至 {to_addr}：{subject}", file=sys.stderr)
        return True
    except Exception as e:  # noqa: BLE001
        # 不抛异常，不阻塞调用方
        print(f"[notify] 邮件发送失败（不阻塞）：{e}", file=sys.stderr)
        return False


def send(subject: str, body: str, severe: bool = False, dry_run: bool = False,
         from_prefix: str | None = None, feishu_group: str | None = None,
         feishu_only: bool = False) -> dict:
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
    邮件兜底保留：飞书失败不阻塞、邮件照发（SEVERE 告警邮件始终发，防飞书故障无通知）。
    """
    if severe:
        subject = SEVERE_PREFIX + subject
    email_ok = _send_email(subject, body, dry_run=dry_run, from_prefix=from_prefix) if not feishu_only else False
    tg_ok = send_telegram(subject, body, dry_run=dry_run) if not feishu_only else False
    fs_ok = send_feishu(subject, body, chat_key=feishu_group, dry_run=dry_run,
                        severe=severe, from_prefix=from_prefix)
    return {"email": email_ok, "telegram": tg_ok, "feishu": fs_ok}


def send_to(subject: str, body: str, email: str | None = None,
            chat_id: str | None = None, dry_run: bool = False,
            from_prefix: str | None = None, feishu_group: str | None = None,
            feishu_only: bool = False) -> dict:
    """A12 订阅推送：指定收件人（email/chat_id）多渠道分发。

    与 send() 区别：send() 用 config 全局 to/chat_id（单一管理员）；
    send_to() 接收 email/chat_id 参数，给订阅者独立推送（SMTP user/password、
    bot_token/api_base 仍用 config 全局配置，单一发件方给多收件人）。

    email/chat_id 任一为 None/空则跳过该渠道。各渠道独立失败不互相阻塞。
    返回 {"email": bool, "telegram": bool, "feishu": bool}。
    from_prefix：邮件发件人名前缀（None=默认 "信号实验室监控"）。
    feishu_group：飞书群 key（None=按前缀自动映射，订阅信号推送默认进 report 报告群）。
    """
    email_ok = _send_email(subject, body, dry_run=dry_run, to=email, from_prefix=from_prefix) if email and not feishu_only else False
    tg_ok = send_telegram(subject, body, dry_run=dry_run, chat_id=chat_id) if chat_id and not feishu_only else False
    fs_ok = send_feishu(subject, body, chat_key=feishu_group, dry_run=dry_run,
                        severe=False, from_prefix=from_prefix)
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
    """发送后更新 dedup_key 的 last_alerted 为当前时间（无论发送成败，已尝试即更新）。

    防止发送失败（SMTP 错误等）时每周期重试轰炸：发送失败本身是另一层问题，
    schedule_monitor 不感知 notify.py 调用（intraday exit 0 只要 git push 成功），
    故 notify.py 自管去重，尝试发送即更新 last_alerted，window 内不再重试。
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
                      feishu_group: str | None = None) -> dict:
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
                   feishu_group=feishu_group or "agent_done")

    # 发送后更新 dedup（无论成败，已尝试即更新）
    if not dry_run:
        update_dedup(dedup_key)

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="update_all 监控通知（邮件 + Telegram + alerts 文件）"
    )
    parser.add_argument("subject", help="主题（--agent-done 模式下为结论摘要）")
    parser.add_argument("body", nargs="?", default="", help="正文（HTML，邮件原样发送；Telegram 转纯文本）。"
                        "--agent-done 模式下可省略")
    parser.add_argument("--severe", action="store_true",
                        help="严重标记：用于 write_alert 语义（2026-07-20 改造：不再修改 subject 前缀）")
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
    args = parser.parse_args(argv)

    # agent 完成通知模式：subject=结论摘要，直达用户绕过主控队列
    if args.agent_done:
        results = notify_agent_done(args.agent_done, args.subject, dry_run=args.dry_run,
                                    feishu_group=args.feishu_group)
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
                   feishu_only=args.feishu_only)
    ok = [ch for ch, v in results.items() if v]
    fail = [ch for ch, v in results.items() if not v]
    if ok:
        print(f"[notify] 汇总：已发出 {'/'.join(ok)}"
              + (f"（未发出：{'/'.join(fail)}）" if fail else ""), file=sys.stderr)
    else:
        print(f"[notify] 汇总：全部渠道未发出（{'/'.join(fail) or '无渠道'}）", file=sys.stderr)

    # 发送后更新 dedup（无论成败，已尝试即更新，防发送失败时每周期重试轰炸）
    if args.dedup_key and not args.dry_run:
        update_dedup(args.dedup_key)

    if args.alert_issue:
        write_alert(args.alert_issue, args.body, log_path=args.alert_log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
