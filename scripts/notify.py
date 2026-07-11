#!/usr/bin/env python3
"""notify.py - update_all 监控通知工具（邮件 + alerts 文件）。

复用 config/email.json（字段：smtp/port/user/password/to，SMTP SSL，163->QQ邮箱），
发邮件参考 check_signals.py 的 send_email。严重告警额外写 data/alerts/latest.md
（覆盖式记最新一次严重），供下轮 Claude 开工优先排查。

用法（CLI）:
  notify.py <subject> <body> [--severe] [--alert-issue <issue> [--alert-log <path>]] [--dry-run]

  --severe          邮件标题前缀加 [需Claude排查]
  --alert-issue     写 data/alerts/latest.md（issue 一句话 + 详情=body + 日志路径）
  --alert-log       配合 --alert-issue，记录日志文件路径
  --dry-run         不真发邮件，只 print 到 stderr（自验用）

邮件发送失败只 print 警告不抛异常（不阻塞调用方，update_all 末尾 || true 双保险）。
"""
from __future__ import annotations

import argparse
import json
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EMAIL_CONFIG = REPO / "config" / "email.json"
ALERTS_DIR = REPO / "data" / "alerts"
ALERTS_FILE = ALERTS_DIR / "latest.md"

# email.json.example 中的占位密码，识别后跳过实际发送
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码，非登录密码>"

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


def send(subject: str, body: str, severe: bool = False, dry_run: bool = False) -> bool:
    """发邮件。severe=True 时标题前缀 [需Claude排查]。

    dry_run=True 只 print 到 stderr 不真发。发送失败只 print 警告不抛异常。
    返回 True 表示发出（或 dry_run 模拟成功），False 表示未发（配置缺失/失败）。
    """
    if severe:
        subject = SEVERE_PREFIX + subject

    if dry_run:
        print(f"[notify][dry-run] subject={subject}", file=sys.stderr)
        print(f"[notify][dry-run] body=\n{body}", file=sys.stderr)
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
        description="update_all 监控通知（邮件 + alerts 文件）"
    )
    parser.add_argument("subject", help="邮件主题")
    parser.add_argument("body", help="邮件正文（HTML）")
    parser.add_argument("--severe", action="store_true", help="严重：标题加 [需Claude排查] 前缀")
    parser.add_argument("--alert-issue", help="写 data/alerts/latest.md，值为问题一句话")
    parser.add_argument("--alert-log", help="配合 --alert-issue，日志文件路径")
    parser.add_argument("--dry-run", action="store_true", help="不真发邮件，只 print 到 stderr")
    args = parser.parse_args(argv)

    send(args.subject, args.body, severe=args.severe, dry_run=args.dry_run)

    if args.alert_issue:
        write_alert(args.alert_issue, args.body, log_path=args.alert_log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
