#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#327 每日 23:25 拉 /api/err/stats, ≥20 条同一错误采样 → notify --severe + alert_ledger 行。

调用方: schedule_monitor.sh 在 ~23:25 窗口（±5min）调度（不限交易日）。
鉴权: 复用 worker /api/err/stats 的 X-Admin-Pwd（同 FEEDBACK_ADMIN_PASSWORD secret, 留言管理端先例）。
  · secret 从 env ERR_STATS_ADMIN_PWD 读（云上 systemd unit EnvironmentFile 注入;
    缺省回退 env FEEDBACK_ADMIN_PASSWORD 便于复用既有 secret）。
  · 两者均缺则跳过本轮（不告警, 日志说明）。
阈值: alert_denoise_rules.FE_ERR_SEVERE_THRESHOLD（默认 20, 同源常量）。
去重: notify --dedup-key fe-err|<YYYYMMDD>|<md5>（alert_state 6h 窗 severe 默认去重;
      alert_denoise_rules.FE_ERR_DEDUP_KEY_PREFIX 同源）。
台账: data/alerts/alert_ledger.jsonl 追加一行 `fe-err|<md5>|<count>|<date>`（供排障反查）。

红线（§5.9 三验齐）:
  · 问题真实: 前端零错误捕获（researcher §1.1 实测 rc=1）+ KV 计数入口已建（worker err_report.js）
  · 根因定位: 数据流"前端 → KV → 无人读"; 本脚本补"读+告警"环节
  · 修复机制可达: schedule_monitor 已是告警链主调度, 加 23:25 子任务拉 stats 超阈值 severe,
    走既有 notify --severe + alert_denoise 去重（与 R7 同口径）→ 必然生效

禁发通知（红线）: 本脚本仅在云上由 schedule_monitor 调度时才真调 notify;
  本机单测/pytest 必须打桩（--dry-run / monkeypatch subprocess）, 禁真发邮件/飞书（§23.2 / L48）。
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import alert_denoise_rules as adr
except ImportError:  # 单测可打桩
    adr = None

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
REPO = Path(__file__).resolve().parent.parent
STATS_URL_DEFAULT = "https://ss.fx8.store/api/err/stats"
ALERT_LEDGER = REPO / "data" / "alerts" / "alert_ledger.jsonl"
NOTIFY_PY = REPO / "scripts" / "notify.py"
TIMEOUT_FETCH = 15
TIMEOUT_NOTIFY = 60


def _today_sh() -> str:
    return datetime.now(TZ_SHANGHAI).strftime("%Y%m%d")


def _today_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat()


def fetch_stats(url: str, admin_pwd: str, days: int = 1, limit: int = 100) -> dict:
    """curl /api/err/stats 带 X-Admin-Pwd header, 返回 JSON dict。失败抛异常。"""
    full = f"{url}?days={days}&limit={limit}"
    req = urllib.request.Request(full, headers={
        "X-Admin-Pwd": admin_pwd,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_FETCH) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _md5_short(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode("utf-8", errors="replace")).hexdigest()[:12]


def _write_ledger(md5: str, count: int, date_str: str) -> None:
    try:
        ALERT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_LEDGER, "a", encoding="utf-8") as f:
            f.write(f"fe-err|{md5}|{count}|{date_str}\n")
    except Exception as e:
        print(f"[warn] 写 alert_ledger 失败(不阻塞): {e}", file=sys.stderr)


def build_dedup_key(date_str: str, md5: str) -> str:
    prefix = getattr(adr, "FE_ERR_DEDUP_KEY_PREFIX", "fe-err|") if adr else "fe-err|"
    return f"{prefix}{date_str}|{md5}"


def run(args=None) -> int:
    p = argparse.ArgumentParser(description="#327 每日拉 /api/err/stats 超阈值告警")
    p.add_argument("--url", default=os.environ.get("ERR_STATS_URL", STATS_URL_DEFAULT))
    p.add_argument("--admin-pwd", default=os.environ.get("ERR_STATS_ADMIN_PWD")
                   or os.environ.get("FEEDBACK_ADMIN_PASSWORD", ""))
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--threshold", type=int,
                   default=getattr(adr, "FE_ERR_SEVERE_THRESHOLD", 20) if adr else 20)
    p.add_argument("--dry-run", default="0", choices=("0", "1"),
                   help="1=只解析+打印不真调 notify/不写台账（单测用）; 0=生产真发（默认）")
    p.add_argument("--notify-bin", default=str(NOTIFY_PY))
    ns = p.parse_args(args)

    if not ns.admin_pwd:
        print("[fe-err] 未配置 ERR_STATS_ADMIN_PWD/FEEDBACK_ADMIN_PASSWORD, 跳过本轮")
        return 0
    try:
        stats = fetch_stats(ns.url, ns.admin_pwd, days=ns.days, limit=ns.limit)
    except Exception as e:
        print(f"[fe-err] 拉 stats 失败(不阻塞): {e}", file=sys.stderr)
        return 0
    errors = stats.get("errors") or []
    if not errors:
        print(f"[fe-err] 当日零错误样本, 不告警 (generated_at={stats.get('generated_at')})")
        return 0

    date_str = _today_sh()
    triggered = [e for e in errors if int(e.get("count") or 0) >= ns.threshold]
    if not triggered:
        top = errors[0]
        print(f"[fe-err] 当日最高 count={top.get('count')} < 阈值 {ns.threshold}, 不告警 "
              f"(msg={top.get('message','')[:60]!r})")
        return 0

    print(f"[fe-err] {len(triggered)} 条错误超阈值({ns.threshold}), 触发 severe")
    for e in triggered:
        msg = e.get("message") or ""
        filename = e.get("filename") or ""
        count = int(e.get("count") or 0)
        md5 = _md5_short(f"{msg}|{filename}")
        dedup_key = build_dedup_key(date_str, md5)
        body = (
            f"[前端错误汇总 #{date_str}] 同一错误采样计数 ≥ {ns.threshold}\n"
            f"  message: {msg[:200]}\n"
            f"  filename: {filename[:200]}\n"
            f"  build_id: {e.get('build_id','')}\n"
            f"  count(1%采样): {count}\n"
            f"  first_ts: {e.get('first_ts','')}\n"
            f"  last_ts: {e.get('last_ts','')}\n"
            f"  排障: wrangler kv key list --binding=SUBSCRIBE_KV --prefix=fe-err:\n"
            f"  来源: schedule_monitor 23:25 轮 check_fe_err_stats.py"
        )
        if ns.dry_run == "1":
            print(f"[fe-err dry-run] dedup_key={dedup_key} count={count} msg={msg[:60]!r}")
            continue
        # 真调 notify --severe（云上 schedule_monitor 调度时才走此分支）
        try:
            subprocess.run(
                [sys.executable, str(ns.notify_bin),
                 "--severe", "--dedup-key", dedup_key,
                 "--subject", f"[前端错误汇总] {msg[:40]} ×{count}"],
                input=body, text=True, capture_output=True,
                timeout=TIMEOUT_NOTIFY, check=False,
            )
        except Exception as e2:
            print(f"[fe-err] notify 调用失败(不阻塞): {e2}", file=sys.stderr)
        _write_ledger(md5, count, date_str)
    return 0


if __name__ == "__main__":
    sys.exit(run())
