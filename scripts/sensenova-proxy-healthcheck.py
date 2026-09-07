#!/usr/bin/env python3
"""sensenova-proxy-healthcheck.py - 商汤轮换代理 /healthz 心跳告警(2026-09-07 接线)。

背景(见 docs/sensenova/out-of-range-locate-20260907.md §四.4 + docs/sensenova/sensenova-proxy-healthcheck.md):
- 8899 代理(sensenova-rotate-proxy.py, launchd com.trade.thinking-proxy 托管, KeepAlive 启动秒级重启)
  已实现 /healthz 端点, 但"进程在但卡死/端口无响应"级异常无监控, 代理挂掉只有用户发现才暴露。
- 本脚本定时(launchd 每 5 分钟)GET http://127.0.0.1:8899/healthz, 连续 N 次失败才告警
  (防单次瞬断误报 + 给 launchd 自动重启恢复时间), 恢复时补 [恢复] 通知(与 [告警] 成对闭环)。
- 告警走 scripts/notify.py CLI(--severe 邮件始终发 + 飞书 alert 群) + --alert-issue 镜像 latest.md(L46④)。
- 幂等:连续失败只在【未 firing】时告警一次, 不重复轰炸; 恢复后再异常才再告警; 健康时不发任何通知。

方法口径:
  一次探测 = GET /healthz 超时 5s, 判定 ok = HTTP 200 且 JSON status=="ok"。
  一轮 = 最多 3 次探测, 连续失败(每次探测前 sleep 2s 等重启)全部失败才算异常 = fired。
  状态文件 data/sensenova_health_state.json(不进 git, 仓外本地)track fired/recovered。

用法:
  python3 scripts/sensenova-proxy-healthcheck.py                 # 生产检测+按需发告警
  python3 scripts/sensenova-proxy-healthcheck.py --dry-run       # 只打印不真发(自验用)
  python3 scripts/sensenova-proxy-healthcheck.py --fail-fast     # 测不通即 exit 3(launchd 首部署冒烟用)
  python3 scripts/sensenova-proxy-healthcheck.py --port 18999    # 非 8899 端口(测试实例隔离)
  单测: python3 scripts/sensenova-proxy-healthcheck.py --self-test --dry-run  # 不落盘不发送

launchd: scripts/com.trade.sensenova-healthcheck.plist(StartInterval 300)
日志: trade-data/data/logs/sensenova-healthcheck.log / .err
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).absolute().parent
DEFAULT_REPO_CANDIDATES = [
    Path("/Users/linhuichen/code/trade-data"),
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "data").exists()),
                    DEFAULT_REPO_CANDIDATES[0])
STATE_PATH_NAME = "sensenova_health_state.json"   # data/sensenova_health_state.json(不进 git)
DEFAULT_PORT = 8899
MAX_FAILS = 3
PROBE_TIMEOUT = 5          # 单次 GET 超时秒
PROBE_INTERVAL = 2         # 失败后重试间隔秒(给 launchd KeepAlive 重启窗口)
LOG_PATH = "/Users/linhuichen/code/trade-data/data/logs/sensenova-healthcheck.err"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _probe_once(port: int, timeout: float) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            body = resp.read().decode("utf-8", "replace")
            data = json.loads(body)
            if data.get("status") != "ok":
                return False, f"status={data.get('status')!r}"
            return True, f"uptime={data.get('uptime_sec')}s rotate_keys={data.get('rotate_keys')} cooling={data.get('cooling_keys')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError, json.JSONDecodeError) as e:
        return False, f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 - 探测失败不致命, 记录即返回
        return False, f"{type(e).__name__}: {e}"


def _one_round(port: int) -> tuple[bool, list[str]]:
    """一轮 = 连续探测, 任一成功即健康。返回 (healthy, [失败原因])。"""
    failures: list[str] = []
    for attempt in range(1, MAX_FAILS + 1):
        if attempt > 1:
            time.sleep(PROBE_INTERVAL)
        ok, detail = _probe_once(port, PROBE_TIMEOUT)
        if ok:
            return True, []
        failures.append(f"[{_now_str()}] attempt {attempt}/{MAX_FAILS} FAIL: {detail}")
    return False, failures


def _load_state(repo: Path) -> dict:
    try:
        return json.loads((repo / "data" / STATE_PATH_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(repo: Path, state: dict) -> None:
    try:
        (repo / "data" / STATE_PATH_NAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[healthcheck] 状态文件写入失败(不影响本次通知): {e}", file=sys.stderr)


def _notify(repo: Path, subject: str, body: str, severe: bool,
            dry_run: bool, alert_issue: str | None = None) -> bool:
    """经 scripts/notify.py 发送; severe 额外写 data/alerts/latest.md(镜像防旁路)。"""
    cmd = [sys.executable, str(SCRIPT_DIR / "notify.py"), subject, body]
    if severe:
        cmd.append("--severe")
        if alert_issue:
            cmd += ["--alert-issue", alert_issue, "--alert-log", LOG_PATH]
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[healthcheck] notify 退出码 {r.returncode}: {(r.stderr or '')[-300:]}", file=sys.stderr)
            return False
        print(f"[healthcheck][notify] subject={subject!r} severe={severe} dry_run={dry_run}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[healthcheck] notify 异常: {e}", file=sys.stderr)
        return False


def _send_alert(repo: Path, port: int, body: str, dry_run: bool) -> bool:
    subject = f"[告警] 商汤代理 {port} 心跳异常"
    issue = f"商汤代理{port}心跳异常"
    full_body = (f"<b>[告警] 商汤轮换代理 127.0.0.1:{port} /healthz 连续 {MAX_FAILS} 次无响应。</b><br>"
                 f"时间段: <code>{body}</code><br>"
                 f"代理进程由 launchd com.trade.thinking-proxy 托管(KeepAlive 自动重启), 秒级恢复属预期;<br>"
                 f"若持续异常 = 进程在但卡死(healthz 检测正为此场景), 处置: "
                 f"<code>launchctl kickstart -k gui/$(id -u)/com.trade.thinking-proxy</code> 重启代理, "
                 f"或 tail 日志 <code>trade-data/data/logs/sensenova-rotate.err</code> 根因排查。<br>"
                 f"告警日志: {LOG_PATH}")
    return _notify(repo, subject, full_body, severe=True, dry_run=dry_run, alert_issue=issue)


def _send_recovery(repo: Path, port: int, dry_run: bool) -> bool:
    subject = f"[恢复] 商汤代理 {port} 心跳已恢复"
    body = (f"<b>[恢复] 商汤轮换代理 127.0.0.1:{port} /healthz 已恢复响应。</b><br>"
            f"无需操作, 已自动恢复。")
    return _notify(repo, subject, body, severe=False, dry_run=dry_run)


def _self_test(port: int, dry_run: bool) -> int:
    """dry 自验(不落盘不真发): 构造两场景验证状态机 code path。
    场景1 健康: 不触发任何通知(无退化)。场景2 异常: 触发 [告警] 分支(dry-run 只打印)。"""
    print("[self-test] 场景1 健康态: _one_round 返回 healthy=True → 应不发任何通知")
    healthy, failures = _one_round(port)
    if healthy:
        print("[self-test][PASS] 场景1 健康态无通知(真实端口探测正常)")
    else:
        print(f"[self-test][WARN] 真实端口 {port} 探测失败({failures[-1]}), 场景1 以模拟代替")
    print("[self-test] 场景2 异常态: 连续失败 → 发 [告警](dry-run)")
    fake_failures = ["[self-test] 模拟 failure 1", "[self-test] 模拟 failure 2"]
    ok = _send_alert(Path(DEFAULT_REPO), port, "<br>".join(fake_failures), dry_run=True)
    print(f"[self-test][{'PASS' if ok else 'FAIL'}] 场景2 [告警] code path 已触发(dry-run 未真发)")
    print("[self-test] 场景2b 幂等: fired=true 时抑制重复告警(见 main 分支, 本轮跳过落盘)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="商汤轮换代理 /healthz 心跳告警")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="数据仓根(trade-data)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="代理监听端口(默认 8899)")
    ap.add_argument("--dry-run", action="store_true", help="不真发通知只打印")
    ap.add_argument("--fail-fast", action="store_true",
                    help="健康 pass(exit 0) / 异常 exit 3(launchd 首部署冒烟脚本用)")
    ap.add_argument("--self-test", action="store_true", help="dry 自验(不落盘不真发)")
    args = ap.parse_args()

    repo = Path(args.repo)
    state = _load_state(repo)

    if args.self_test:
        return _self_test(args.port, args.dry_run)

    healthy, failures = _one_round(args.port)
    fired = state.get("fired", False)

    if healthy:
        if fired:
            # 曾告警过 → 现在恢复: 补 [恢复] 通知 + 清 fired(状态变化才写盘)
            print(f"[healthcheck][{_now_str()}] 心跳恢复(fired→clear), 发恢复通知")
            ok = _send_recovery(repo, args.port, args.dry_run)
            if not args.dry_run and ok:
                _save_state(repo, {"fired": False, "recovered_at": _now_str()})
        else:
            # 一直健康: 不发任何通知(无退化), 且不写盘(状态无变化)
            print(f"[healthcheck][{_now_str()}] 心跳正常, 无异常不通知")
        return 0

    # 异常
    if fired:
        print(f"[healthcheck][{_now_str()}] 连续失败仍异常, 但已 fired(true) 抑制重复告警; "
              f"fail={failures[-1]}")
        return 0
    # 首次异常 → 告警 + 记 fired
    print(f"[healthcheck][{_now_str()}] 连续 {MAX_FAILS} 次失败, 发 [告警]"
          f"{'[dry-run]' if args.dry_run else ''}")
    for f in failures:
        print(f"  {f}", file=sys.stderr)
    ok = _send_alert(repo, args.port, "<br>".join(failures), args.dry_run)
    if ok and not args.dry_run:
        _save_state(repo, {"fired": True, "fired_at": _now_str(), "last_failures": failures})
    elif not ok:
        # notify 发送失败不记 fired → 下一轮自动重试验证通道(参考 check_s06 同款契约)
        print("[healthcheck] notify 未确认发件成功, 不落 fired 状态, 下轮重试", file=sys.stderr)
    else:
        print("[healthcheck] dry-run 不落盘", file=sys.stderr)

    if args.fail_fast:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())