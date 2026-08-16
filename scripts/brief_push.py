#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brief_push.py - AI 每日速递订阅推送服务（2026-08-17 新增，B/C 级新功能）。

为 UUMit 平台「AI 每日速递订阅推送服务」的推送侧：每日 daily_brief.json 一生成，
自动推送到 active 订阅者（email / webhook_url），并同步推送到飞书报告群做日常播报。

- 输入：static-site/data/daily_brief.json（每天 20:40 由 run_daily_brief.sh -> gen_daily_brief.py 生成）
  + 拉取 GET /api/subscribe/recipients（管理员 api_key 鉴权）得 active 订阅者列表。
- 推送渠道（各渠道独立失败不互相阻塞，best-effort）：
  1. email 订阅者：复用 config/email.json 的 SMTP 配置（smtp.163.com:465）发邮件。
  2. webhook_url 订阅者：POST 订阅者提供的 URL，body = {date, direction, range, text 摘要, url}。
  3. 飞书报告群：notify.send_feishu 发完整速递（日常播报主通道）。
- 输出：推送结果日志（成功/失败逐条），失败重试 1 次。
- 防重复推送：data/brief_push_state.json 记录「date 已推送」，同日不重复推。
- 非交易日（周末/节假日）不推送：复用 trade/app/calendar.py is_trading_day
  （memory daily-brief-range-degrade-contract：触发源脚本必带交易日判断）。
- 计费 hook（本期不做自动扣费）：订阅状态手动管理，上架后由 UUMit 平台计费回调对接；
  本脚本已在推送处留计费 hook 注释（BILLING_HOOK），接平台回调时在此落扣费/用量记录。

用法：
  python3 scripts/brief_push.py [--date YYYYMMDD] [--force] [--dry-run] [--config <path>]
    --date      指定推送日期（默认今天）
    --force     忽略非交易日判断强制推送（手动测试用）
    --dry-run   不真发，只打印将推送内容
    --config    订阅管理配置路径（默认 config/brief_push.json，gitignored，含管理员 api_key + API 域名）
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
# daily_brief 数据源（与 gen_daily_brief.py 双写位置一致；launchd 从 trade-data 跑，脚本 resolve 到 trade/scripts）
DATA_DIR = Path(__file__).absolute().parent.parent / "static-site" / "data"
BRIEF_FILE = DATA_DIR / "daily_brief.json"
STATE_FILE = Path(__file__).absolute().parent.parent / "data" / "brief_push_state.json"
DEFAULT_CONFIG = Path(__file__).absolute().parent.parent / "config" / "brief_push.json"

# 管理员 api_key + 域名配置项名（值从 config/brief_push.json 读，gitignored 不进 git）
CONFIG_KEYS = ("api_base", "admin_key")

# 公开站点域名（推送内容里的 url 链接，订阅者点开看完整版）
SITE_URL = "https://ss.fx8.store"


def _urlopen_retry_ssl(req, timeout=20):
    """urlopen 带 SSL 校验失败降级重试（本地 MITM 代理场景，同 notify.py 模式）。

    本地机器有 MITM 代理时 python 证书校验会 CERTIFICATE_VERIFY_FAILED，
    退化为不校验重试一次（仅本项目自建/订阅者 webhook 调用，生产无此问题）。
    """
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        print("[brief_push] SSL 校验失败，退化为不校验重试一次（本地 MITM 代理）", file=sys.stderr)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def is_trading_day(date: str) -> bool:
    """复用 trade/app/calendar.py is_trading_day。"""
    sys.path.insert(0, str(REPO))
    try:
        from app.calendar import is_trading_day as _itd
        from datetime import date as _date
        d = _date(int(date[:4]), int(date[4:6]), int(date[6:8]))
        return bool(_itd(d))
    except Exception as e:
        print(f"[brief_push] 交易日判断失败（默认按交易日处理）: {e}", file=sys.stderr)
        return True


def fetch_recipients(cfg: dict, dry_run: bool = False) -> list:
    """拉取 GET /api/subscribe/recipients（管理员 key 鉴权），返回 active 订阅者列表。"""
    api_base = (cfg.get("api_base") or "").rstrip("/")
    admin_key = cfg.get("admin_key") or ""
    if not api_base or not admin_key:
        print("[brief_push] 配置缺失 api_base/admin_key（config/brief_push.json），跳过订阅者推送", file=sys.stderr)
        return []
    url = f"{api_base}/api/subscribe/recipients"
    # 带浏览器 UA：CF WAF 会 403 拦截 Python urllib 默认 UA（curl 能过因为 UA 正常）
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {admin_key}",
            "User-Agent": "Mozilla/5.0 (brief-push-subscription-service)",
        },
    )
    try:
        with _urlopen_retry_ssl(req) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("recipients") or []
    except Exception as e:
        print(f"[brief_push] 拉取订阅者失败: {e}", file=sys.stderr)
        return []


def build_text(brief: dict) -> str:
    """把 daily_brief 的 text 字段（review/trend/watch 等）拍平成推送正文。"""
    text = brief.get("text") or {}
    lines = []
    if isinstance(text, dict):
        order = ["review", "trend", "watch", "risk", "highlights", "confidence_reason"]
        for k in order:
            v = text.get(k)
            if v:
                lines.append(f"【{k}】{v}")
        # 兜底：未覆盖的键
        for k, v in text.items():
            if k not in order and v:
                lines.append(f"【{k}】{v}")
    elif isinstance(text, str):
        lines.append(text)
    return "\n\n".join(lines)


def push_webhook(recipient: dict, brief: dict, date: str, dry_run: bool = False) -> bool:
    """POST webhook_url 订阅者。body = {date, direction, range, text 摘要, url}。"""
    url = recipient.get("webhook_url") or ""
    if not url:
        return False
    meta = brief.get("meta") or {}
    payload = {
        "date": date,
        "direction": meta.get("direction"),
        "range": meta.get("range"),
        "text": build_text(brief),
        "url": f"{SITE_URL}/?brief={date}",
    }
    if dry_run:
        print(f"[brief_push][dry-run] webhook -> {url}\n{json.dumps(payload, ensure_ascii=False)[:300]}", file=sys.stderr)
        return True
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (brief-push-subscription-service)",
        },
        method="POST",
    )
    try:
        with _urlopen_retry_ssl(req) as r:
            r.read()
        return True
    except Exception as e:
        print(f"[brief_push] webhook {url} 推送失败: {e}", file=sys.stderr)
        return False


def push_email(recipient: dict, brief: dict, date: str, dry_run: bool = False) -> bool:
    """email 订阅者：复用 notify._send_email（config/email.json SMTP 配置）。"""
    email = recipient.get("email") or ""
    if not email:
        return False
    meta = brief.get("meta") or {}
    subject = f"[每日速递] {date} A股市场速递"
    body = (
        f"<h3>AI 每日速递 {date}</h3>"
        f"<p>方向：{meta.get('direction')} ｜ 区间：{meta.get('range')}</p>"
        f"<pre style='white-space:pre-wrap'>{build_text(brief)}</pre>"
        f"<p><a href='{SITE_URL}'>打开完整看板</a></p>"
        f"<hr><p style='color:#888'>{brief.get('disclaimer','')}</p>"
    )
    sys.path.insert(0, str(REPO / "scripts"))
    from notify import _send_email  # 复用 SMTP 配置与发送逻辑
    return _send_email(subject, body, dry_run=dry_run, to=email, from_prefix="[每日速递]")


def push_feishu(brief: dict, date: str, dry_run: bool = False) -> bool:
    """飞书报告群推送完整速递（日常播报主通道）。"""
    meta = brief.get("meta") or {}
    subject = f"[每日速递] {date}"
    body = (
        f"方向：{meta.get('direction')} ｜ 区间：{meta.get('range')}\n\n"
        f"{build_text(brief)}"
    )
    sys.path.insert(0, str(REPO / "scripts"))
    from notify import send_feishu
    return send_feishu(subject, body, chat_key="report", dry_run=dry_run)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--force", action="store_true", help="忽略非交易日判断强制推送")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    date = args.date
    dry_run = args.dry_run

    # 非交易日跳过（触发源脚本必带交易日判断，memory daily-brief-range-degrade-contract）
    if not args.force and not is_trading_day(date):
        print(f"[brief_push] {date} 非交易日，跳过推送")
        return 0

    # 读 daily_brief.json
    if not BRIEF_FILE.exists():
        print(f"[brief_push] 未找到 {BRIEF_FILE}", file=sys.stderr)
        return 1
    try:
        brief = json.loads(BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[brief_push] daily_brief.json 解析失败: {e}", file=sys.stderr)
        return 1
    brief_date = str((brief.get("meta") or {}).get("date") or "")
    if not brief_date:
        print(f"[brief_push] daily_brief.json 无 meta.date", file=sys.stderr)
        return 1
    # 数据一致性（§22）：推送内容 = 生成文件逐位一致（同 date 才推）
    if brief_date != date:
        print(f"[brief_push] daily_brief 日期 {brief_date} != 指定 {date}，不推送（防推送错日内容）", file=sys.stderr)
        return 1

    # 防重复推送
    state = load_state()
    if state.get("pushed") == date and not args.force and not dry_run:
        print(f"[brief_push] {date} 已推送过，跳过（防重复）")
        return 0

    # 拉订阅者（管理员 key）
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if Path(args.config).exists() else {}
    recipients = fetch_recipients(cfg, dry_run)
    print(f"[brief_push] {date} 订阅者 {len(recipients)} 人")

    results = {"email": [], "webhook": [], "feishu": False}

    # 逐订阅者推送 + 失败重试 1 次
    for r in recipients:
        rtype = r.get("type")
        if rtype == "email":
            ok = push_email(r, brief, date, dry_run)
            if not ok and not dry_run:
                print(f"[brief_push] email 重试 1 次: {r.get('email')}")
                time.sleep(2)
                ok = push_email(r, brief, date, dry_run)
            results["email"].append({"to": r.get("email"), "ok": ok})
        elif rtype == "webhook":
            ok = push_webhook(r, brief, date, dry_run)
            if not ok and not dry_run:
                print(f"[brief_push] webhook 重试 1 次: {r.get('webhook_url')}")
                time.sleep(2)
                ok = push_webhook(r, brief, date, dry_run)
            results["webhook"].append({"to": r.get("webhook_url"), "ok": ok})

    # 飞书报告群（日常播报主通道）
    results["feishu"] = push_feishu(brief, date, dry_run)

    # 计费 hook（本期不做自动扣费）：订阅状态手动管理，上架后由 UUMit 平台计费回调对接，
    # 在此落「date + 订阅者 key + 推送渠道」用量记录，供平台对账。本期只留日志注释。
    # BILLING_HOOK: 接平台计费回调时，此处把 results 逐条写入计费用量表。

    # 记录已推送（防重复）
    if not dry_run:
        state["pushed"] = date
        state[f"pushed_{date}"] = {
            "ts": datetime.now().isoformat(),
            "recipients": len(recipients),
            "feishu": results["feishu"],
        }
        save_state(state)
        print(f"[brief_push] ✓ {date} 推送完成（email={sum(1 for x in results['email'] if x['ok'])}/"
              f"{len(results['email'])}, webhook={sum(1 for x in results['webhook'] if x['ok'])}/"
              f"{len(results['webhook'])}, feishu={results['feishu']}）")
    else:
        print(f"[brief_push][dry-run] 完成，不写状态")

    return 0


if __name__ == "__main__":
    sys.exit(main())
