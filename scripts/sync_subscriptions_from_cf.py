#!/usr/bin/env python3
"""sync_subscriptions_from_cf.py - 从 CF Workers 拉订阅回流本地 config/subscriptions.json。

C 方案（2026-07-24）：生产环境订阅 CRUD 走 CF Workers + KV，本地 check_signals.py
推送邮件/Telegram 需读 config/subscriptions.json。本脚本在 check_signals.py 跑前
拉 https://ss.fx8.store/api/subscribe/export（带 X-Sub-Pwd header），原子写本地文件。

失败不阻塞（网络错/密码错/KV 空），用旧 config/subscriptions.json 兜底。
check_signals.py 在 load_subscriptions() 开头 subprocess 调本脚本（best-effort sync）。

配置：config/sub_pwd.json（含密码，已 gitignore），格式 {"pwd": "xxx"}。
  密码也可用环境变量 SUBSCRIBE_PASSWORD 覆盖（优先级高于配置文件）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBS_PATH = REPO / "config" / "subscriptions.json"
PWD_PATH = REPO / "config" / "sub_pwd.json"
EXPORT_URL = "https://ss.fx8.store/api/subscribe/export"


def load_pwd() -> str:
    """读密码：环境变量 SUBSCRIBE_PASSWORD > config/sub_pwd.json > 空。"""
    env_pwd = os.environ.get("SUBSCRIBE_PASSWORD", "").strip()
    if env_pwd:
        return env_pwd
    if PWD_PATH.exists():
        try:
            data = json.loads(PWD_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return str(data.get("pwd", "")).strip()
        except Exception:
            pass
    return ""


def main() -> int:
    pwd = load_pwd()
    if not pwd:
        print("[sync_subscriptions] 未配置密码（SUBSCRIBE_PASSWORD 环境变量/config/sub_pwd.json 均空），跳过同步", file=sys.stderr)
        return 1

    try:
        import requests
    except ImportError:
        # requests 不可用时用 urllib 兜底
        import urllib.request
        import urllib.error
        req = urllib.request.Request(EXPORT_URL, headers={"X-Sub-Pwd": pwd})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    print(f"[sync_subscriptions] HTTP {resp.status}，跳过同步", file=sys.stderr)
                    return 1
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            print(f"[sync_subscriptions] 网络错误：{e}，跳过同步（用旧 config/subscriptions.json）", file=sys.stderr)
            return 1
    else:
        try:
            r = requests.get(EXPORT_URL, headers={"X-Sub-Pwd": pwd}, timeout=15)
        except Exception as e:
            print(f"[sync_subscriptions] 网络错误：{e}，跳过同步（用旧 config/subscriptions.json）", file=sys.stderr)
            return 1
        if r.status_code != 200:
            print(f"[sync_subscriptions] HTTP {r.status_code}：{r.text[:200]}，跳过同步", file=sys.stderr)
            return 1
        raw = r.text

    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"[sync_subscriptions] 响应非合法 JSON：{e}，跳过同步", file=sys.stderr)
        return 1

    if not isinstance(data, dict) or not isinstance(data.get("subscriptions"), list):
        print("[sync_subscriptions] 响应格式异常（非 {subscriptions:[...]}），跳过同步", file=sys.stderr)
        return 1

    # 原子写（.tmp + rename）：防 check_signals 并发读半截文件
    SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=str(SUBS_PATH.parent), prefix=".sub_sync_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, SUBS_PATH)
    except Exception as e:
        print(f"[sync_subscriptions] 写文件失败：{e}，跳过同步", file=sys.stderr)
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        return 1

    count = len(data.get("subscriptions", []))
    print(f"[sync_subscriptions] 同步成功：{count} 个订阅 -> {SUBS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
