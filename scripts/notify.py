#!/usr/bin/env python3
"""notify.py - update_all 监控通知工具（多渠道：邮件 + Telegram + alerts 文件）。

多渠道分发（send()）：先邮件后 Telegram，各渠道独立失败不互相阻塞，返回聚合结果
{"email": bool, "telegram": bool}。

- 邮件：复用 config/email.json（字段：smtp/port/user/password/to，SMTP SSL，163->QQ）。
- Telegram：读 config/telegram.json（bot_token/chat_id/api_base，POST Bot API sendMessage；
  国内 GFW 不可达时 api_base 设 CF Workers 反代 URL，详见 telegram.json.example）。
- 严重告警额外写 data/alerts/latest.md（覆盖式记最新一次严重），供下轮 Claude 开工优先排查。

用法（CLI）:
  notify.py <subject> <body> [--severe] [--alert-issue <issue> [--alert-log <path>]] [--dry-run]

  --severe          标题前缀加 [需Claude排查]（邮件 + Telegram 共用）
  --alert-issue     写 data/alerts/latest.md（issue 一句话 + 详情=body + 日志路径）
  --alert-log       配合 --alert-issue，记录日志文件路径
  --dry-run         不真发，只 print 到 stderr（自验用）

各渠道发送失败只 print 警告不抛异常（不阻塞调用方，update_all 末尾 || true 双保险）。
"""
from __future__ import annotations

import argparse
import json
import re
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EMAIL_CONFIG = REPO / "config" / "email.json"
TELEGRAM_CONFIG = REPO / "config" / "telegram.json"
ALERTS_DIR = REPO / "data" / "alerts"
ALERTS_FILE = ALERTS_DIR / "latest.md"

# email.json.example 中的占位密码，识别后跳过实际发送
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码，非登录密码>"

# telegram.json.example 中的占位值，识别后跳过实际发送
PLACEHOLDER_TG_TOKEN = "YOUR_BOT_TOKEN"
PLACEHOLDER_TG_CHAT = "YOUR_CHAT_ID"

# Telegram Bot API sendMessage 单条文本上限 4096 字符
TG_TEXT_LIMIT = 4096

SEVERE_PREFIX = "[需Claude排查] "


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


def send_telegram(subject: str, body: str, dry_run: bool = False) -> bool:
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

    返回 True 表示发出（或 dry_run 模拟成功），False 表示未发（配置缺失/占位符/发送失败）。
    """
    cfg = load_telegram_config()
    if cfg is None:
        # 配置文件不存在=未配置，静默跳过（非失败）
        return False

    token = str(cfg.get("bot_token", "")).strip()
    chat_id = str(cfg.get("chat_id", "")).strip()
    api_base = str(cfg.get("api_base", "https://api.telegram.org")).strip().rstrip("/")

    if (not token or token == PLACEHOLDER_TG_TOKEN
            or not chat_id or chat_id == PLACEHOLDER_TG_CHAT):
        print(f"[notify] telegram bot_token/chat_id 占位符或缺失，跳过发送（subject={subject}）",
              file=sys.stderr)
        return False

    # Telegram 不支持 HTML table，转纯文本；subject + body 拼接
    text = f"{subject}\n\n{_html_to_text(body)}"
    if len(text) > TG_TEXT_LIMIT:
        text = text[: TG_TEXT_LIMIT - 30] + "\n…(已截断)"

    if dry_run:
        print(f"[notify][dry-run] telegram chat={chat_id} api_base={api_base}", file=sys.stderr)
        print(f"[notify][dry-run] telegram text(前200)=\n{text[:200]}", file=sys.stderr)
        return True

    url = f"{api_base}/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": ""},
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
            print(f"[notify] Telegram 已发送至 {chat_id}：{subject}", file=sys.stderr)
            return True
        print(f"[notify] Telegram API 返回非 ok：{resp_data}", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        # 不抛异常，不阻塞调用方/不阻塞邮件
        print(f"[notify] Telegram 发送失败（不阻塞）：{e}", file=sys.stderr)
        return False


def _send_email(subject: str, body: str, dry_run: bool = False) -> bool:
    """发邮件（内部，由 send() 调用）。dry_run=True 只 print 不真发。

    发送失败只 print 警告不抛异常。返回 True 表示发出（或 dry_run 模拟成功），
    False 表示未发（配置缺失/占位符/发送失败）。
    """
    if dry_run:
        print(f"[notify][dry-run] email subject={subject}", file=sys.stderr)
        print(f"[notify][dry-run] email body=\n{body}", file=sys.stderr)
        return True

    cfg = load_email_config()
    if cfg is None:
        return False

    smtp = cfg.get("smtp", "smtp.163.com")
    port = int(cfg.get("port", 465))
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    to = cfg.get("to", user)

    if not user or not password or password == PLACEHOLDER_PASSWORD:
        print(f"[notify] SMTP password 占位符或缺失，跳过发送（subject={subject}）", file=sys.stderr)
        return False

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("情绪看板监控", user))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)

    try:
        with smtplib.SMTP_SSL(smtp, port, timeout=30) as srv:
            srv.login(user, password)
            srv.sendmail(user, [to], msg.as_string())
        print(f"[notify] 邮件已发送至 {to}：{subject}", file=sys.stderr)
        return True
    except Exception as e:  # noqa: BLE001
        # 不抛异常，不阻塞调用方
        print(f"[notify] 邮件发送失败（不阻塞）：{e}", file=sys.stderr)
        return False


def send(subject: str, body: str, severe: bool = False, dry_run: bool = False) -> dict:
    """多渠道分发通知（邮件 + Telegram）。各渠道独立失败不互相阻塞。

    先邮件后 Telegram，任一渠道失败不影响另一个。返回聚合结果：
      {"email": bool, "telegram": bool}，True 表示该渠道发出（或 dry_run 模拟成功），
      False 表示未发（配置缺失/占位符/发送失败）。

    severe=True 时标题前缀 [需Claude排查]（两个渠道共用同一标题）。
    dry_run=True 两个渠道都只 print 不真发。
    """
    if severe:
        subject = SEVERE_PREFIX + subject
    email_ok = _send_email(subject, body, dry_run=dry_run)
    tg_ok = send_telegram(subject, body, dry_run=dry_run)
    return {"email": email_ok, "telegram": tg_ok}


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="update_all 监控通知（邮件 + Telegram + alerts 文件）"
    )
    parser.add_argument("subject", help="主题")
    parser.add_argument("body", help="正文（HTML，邮件原样发送；Telegram 转纯文本）")
    parser.add_argument("--severe", action="store_true", help="严重：标题加 [需Claude排查] 前缀")
    parser.add_argument("--alert-issue", help="写 data/alerts/latest.md，值为问题一句话")
    parser.add_argument("--alert-log", help="配合 --alert-issue，日志文件路径")
    parser.add_argument("--dry-run", action="store_true", help="不真发，只 print 到 stderr")
    args = parser.parse_args(argv)

    results = send(args.subject, args.body, severe=args.severe, dry_run=args.dry_run)
    ok = [ch for ch, v in results.items() if v]
    fail = [ch for ch, v in results.items() if not v]
    if ok:
        print(f"[notify] 汇总：已发出 {'/'.join(ok)}"
              + (f"（未发出：{'/'.join(fail)}）" if fail else ""), file=sys.stderr)
    else:
        print(f"[notify] 汇总：全部渠道未发出（{'/'.join(fail) or '无渠道'}）", file=sys.stderr)

    if args.alert_issue:
        write_alert(args.alert_issue, args.body, log_path=args.alert_log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
