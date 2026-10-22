#!/usr/bin/env python3
"""d1_sync_state.py - CF D1 同步失败可见化 + wrangler 凭据巡检（#275, 2026-10-22）

【为什么需要它（病灶，已核实）】
  #275：`scripts/sync_fund_score_to_d1.sh` 自 2026-10-01 16:02 起连续 **39 次**失败
  （云上 wrangler 未登录），脚本全程「失败不阻塞主流程」且**零告警** ⇒ D1 `fund_score`
  静默停更 20 天，直到人做 #266 时才偶然发现。
  同类面：`scripts/sync_fund_screener_to_d1.sh`（#266 起同一 D1 数据库、同一 wrangler 凭据）。
  根因不是某一次失败，而是「**失败没有任何消费方**」——所以本模块只做一件事：
  把「同步失败」落成**可被巡检读取的状态**，并由既有巡检链
  `check_failed_units.py`（云上 trade-schedule-monitor.timer，15min 一轮）消费。

【状态文件（唯一事实源）】
  `<REPO>/data/d1_sync_state/<script>.json`，原子写（tmp + os.replace，防读到半截 JSON）：
    {
      "script": "sync_fund_score_to_d1",     # 同步脚本短名（不含 .sh）
      "consecutive_failures": 3,             # 连续失败次数（成功清零=删文件）
      "first_failure_at": "...",             # 本轮连续失败的首失败时间（告警正文用）
      "last_failure_at": "...",
      "last_error": "wrangler 凭据无效/过期…", # 最后错误摘要（≤500 字）
      "credential": "invalid|valid|unknown", # wrangler 凭据状态（whoami 预检结论）
      "alerted": false,                      # 本轮连续失败是否已告警（防每轮轰炸）
      "alerted_at": "", "alerted_count": 0,
      "updated_at": "..."
    }
  **成功 = 删除状态文件**（不残留、不写「成功」记录 ⇒ 无状态残留，证据用例⑥）。

【消费端契约（check_failed_units.py）】
  consecutive_failures >= ALERT_THRESHOLD(2) 且 alerted=false ⇒ 发一条告警（含脚本名/
  连续次数/首失败时间/最后错误/凭据状态），成功后把 alerted=true 落盘 ⇒ 第 3 次起不重发；
  同步成功后状态文件被删 ⇒ 不告警（不再重复）。单次偶发失败（=1）不告警。

【告警四元组声明（#264 包3 件F，缺一不上线）】
  - 默认 tier：critical（check_failed_units.py 侧走 notify.py `--severe`）
  - dedup window：0（**关死 notify 通用抑制**；抑制由本模块的 `alerted` 状态自管：
    「一轮连续失败只告警 1 次」，与 failed_units_patrol 同款「窗口 0 + 脚本自管闸门」先例）
  - 聚合域：`collect`（D1 数据发布链；建议域，待 264b 对齐）
  - 首报策略：首报必达（连续第 2 次失败即直发，不等摘要）

【CLI（bash 调用；也供巡检/人工排查）】
  d1_sync_state.py whoami-check [--timeout 90]
      0=凭据有效 / 1=凭据无效或过期 / 2=无法验证（npx 缺失/超时）
      只打印摘要（不打印任何 token；wrangler whoami 本身也不回显 token）
  d1_sync_state.py record-failure --script NAME --error TEXT
      [--credential valid|invalid|unknown] [--state-dir DIR] [--now "YYYY-MM-DD HH:MM:SS"]
  d1_sync_state.py record-success --script NAME [--state-dir DIR]
  d1_sync_state.py status [--state-dir DIR]      # 人读清单（排查用）

【状态目录默认值】
  $REPO/data/d1_sync_state；REPO 未设时回退「本文件所在 git 仓根/data/d1_sync_state」。
  ⚠️ 生产一律显式传 --state-dir "$REPO/data/d1_sync_state"：云上 REPO（数据仓）与
  GIT_REPO（代码仓）是两棵树，必须固定落在数据仓，才与 check_failed_units.py
  的 `--repo`（=REPO）读到同一处。

【复现】
  python3 scripts/d1_sync_state.py record-failure --script demo --error "x" \
      --state-dir /tmp/d1s && python3 scripts/d1_sync_state.py status --state-dir /tmp/d1s
  回归：scripts/tests/test_275_d1_sync_visibility_20261022.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── 巡检消费端契约常量（check_failed_units.py 直接 import，避免两处清单漂移）──
STATE_DIRNAME = "d1_sync_state"          # <REPO>/data/ 下的状态目录名
ALERT_THRESHOLD = 2                      # 连续失败 >= 2 次才告警（#275 任务书口径）
DEDUP_KEY = "d1_sync_fail"               # notify.py 去重键（抑制由状态文件自管）
ALERT_DEDUP_WINDOW = 0                   # 关死 notify 通用抑制，见模块头四元组声明
WHOAMI_TIMEOUT_SECONDS = 90              # whoami 预检超时（防 npx 卡死拖住同步链）

# 凭据状态 → 人读文案（告警正文/日志共用，说人话）
CREDENTIAL_LABELS = {
    "valid": "有效",
    "invalid": "无效/过期",
    "unknown": "未确认",
}


def default_state_dir() -> Path:
    """状态目录默认值：$REPO/data/d1_sync_state，否则本文件所在仓根/data/...。"""
    repo = os.environ.get("REPO")
    if repo:
        return Path(repo) / "data" / STATE_DIRNAME
    return Path(__file__).absolute().parent.parent / "data" / STATE_DIRNAME


def state_path(state_dir: Path, script: str) -> Path:
    """状态文件名 = <script>.json（script 只允许安全字符，防路径穿越）。"""
    safe = "".join(c for c in str(script) if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError("script 名为空或全是非法字符")
    return Path(state_dir) / f"{safe}.json"


def load_state(state_dir: Path, script: str) -> dict | None:
    """读状态；缺失/损坏返回 None（消费端按「无状态」处理，不崩）。"""
    p = state_path(state_dir, script)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 缺失/坏 JSON 都是「无有效状态」
        return None
    return obj if isinstance(obj, dict) else None


def _atomic_write(path: Path, payload: dict) -> None:
    """原子写（tmp + os.replace），防巡检/人工读到半截 JSON（§22 数据一致性铁律）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def record_failure(state_dir: Path, script: str, error: str,
                   credential: str = "unknown", now: datetime | None = None) -> dict:
    """记一次失败：连续计数 +1；首次失败记 first_failure_at；保留已告警标记。

    写失败不抛异常（否则会盖掉调用方原本的失败退出码），只 warn 到 stderr。
    """
    now = now or datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    prev = load_state(state_dir, script) or {}
    try:
        prev_n = int(prev.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        prev_n = 0
    new = {
        "script": script,
        "consecutive_failures": prev_n + 1,
        "first_failure_at": str(prev.get("first_failure_at") or now_str),
        "last_failure_at": now_str,
        "last_error": str(error or "")[:500],
        "credential": credential if credential in CREDENTIAL_LABELS else "unknown",
        "alerted": bool(prev.get("alerted")),
        "alerted_at": str(prev.get("alerted_at") or ""),
        "alerted_count": int(prev.get("alerted_count") or 0),
        "updated_at": now_str,
    }
    try:
        _atomic_write(state_path(state_dir, script), new)
    except Exception as e:  # noqa: BLE001
        print(f"[d1-state] WARN 失败状态写入失败({type(e).__name__}: {e})："
              f"本次失败可能无法被巡检看见", file=sys.stderr)
    return new


def record_success(state_dir: Path, script: str) -> bool:
    """成功 = 删状态文件（连续计数清零、无残留）。返回是否真的删了。"""
    p = state_path(state_dir, script)
    removed = False
    try:
        if p.exists():
            p.unlink()
            removed = True
    except Exception as e:  # noqa: BLE001
        print(f"[d1-state] WARN 状态清零失败({type(e).__name__}: {e})", file=sys.stderr)
    # 顺手清掉可能残留的 .tmp（写中途被 kill 的痕迹）
    try:
        tmp = p.with_name(p.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
    except Exception:  # noqa: BLE001
        pass
    return removed


def mark_alerted(state_dir: Path, script: str, now: datetime | None = None) -> dict | None:
    """告警真发出后落 alerted 标记（消费端调用；防每 15min 重复轰炸）。"""
    now = now or datetime.now()
    st = load_state(state_dir, script)
    if st is None:
        return None
    st["alerted"] = True
    st["alerted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    st["alerted_count"] = int(st.get("consecutive_failures") or 0)
    st["updated_at"] = st["alerted_at"]
    try:
        _atomic_write(state_path(state_dir, script), st)
    except Exception as e:  # noqa: BLE001
        print(f"[d1-state] WARN 告警标记落盘失败(下轮可能重复报一次): "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return None
    return st


def check_wrangler_credentials(timeout: float = WHOAMI_TIMEOUT_SECONDS) -> tuple[int, str]:
    """wrangler 凭据预检：0=有效 / 1=无效或过期 / 2=无法验证。

    ⚠️ 输出只取「最后一行摘要」判读，**绝不把完整输出/任何凭据打进日志**。
    whoami 返回码非 0 一律按「凭据不可用」计失败（#275 病灶：daemon 未登录时
    d1 execute 才失败，且失败没人看；现在把失败前移到同步开始前，错误语义明确）。
    """
    try:
        r = subprocess.run(["npx", "wrangler", "whoami"],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 2, "npx 不存在，无法执行 wrangler whoami（环境缺少 node/npx）"
    except subprocess.TimeoutExpired:
        return 2, f"wrangler whoami 超时（>{timeout:.0f}s），无法确认凭据状态"
    except Exception as e:  # noqa: BLE001
        return 2, f"wrangler whoami 执行异常: {type(e).__name__}: {e}"

    out = ((r.stdout or "") + (r.stderr or "")).strip()
    tail = (out.splitlines()[-1] if out else "")[:300]
    if r.returncode == 0:
        return 0, "wrangler 凭据有效"
    low = out.lower()
    if any(k in low for k in ("not authenticated", "authentication", "login", "unauthorized",
                              "invalid api token", "not logged in")):
        return 1, f"wrangler 凭据无效/过期（whoami 失败）：{tail}"
    return 1, f"wrangler whoami 失败（凭据不可用或网络异常）：{tail}"


def format_problem(st: dict) -> str:
    """把状态文件转成一条人读告警行（消费端日志/正文共用）。"""
    script = st.get("script") or "?"
    n = st.get("consecutive_failures")
    first = st.get("first_failure_at") or "?"
    err = st.get("last_error") or "(无错误摘要)"
    cred = CREDENTIAL_LABELS.get(str(st.get("credential")), "未确认")
    return (f"D1 同步连续失败: {script} 连续 {n} 次, 首失败 {first}, "
            f"最后错误: {err}, wrangler 凭据: {cred}")


def _cmd_status(state_dir: Path) -> int:
    files = sorted(Path(state_dir).glob("*.json")) if Path(state_dir).is_dir() else []
    if not files:
        print(f"[d1-state] 无状态文件（目录: {state_dir}）")
        return 0
    for p in files:
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[d1-state] {p.name}: 读取失败 {type(e).__name__}")
            continue
        if not isinstance(st, dict):
            print(f"[d1-state] {p.name}: 顶层非对象")
            continue
        print("[d1-state] " + format_problem(st)
              + (f" | 已告警@{st.get('alerted_at')}" if st.get("alerted") else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CF D1 同步失败状态 + wrangler 凭据预检（#275）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_who = sub.add_parser("whoami-check", help="wrangler 凭据预检（不打印 token）")
    p_who.add_argument("--timeout", type=float, default=WHOAMI_TIMEOUT_SECONDS)

    p_fail = sub.add_parser("record-failure", help="记一次同步失败（连续计数 +1）")
    p_fail.add_argument("--script", required=True)
    p_fail.add_argument("--error", required=True)
    p_fail.add_argument("--credential", default="unknown",
                        choices=sorted(CREDENTIAL_LABELS))
    p_fail.add_argument("--state-dir", default=None)
    p_fail.add_argument("--now", default=None, help="自测注入运行时刻(YYYY-MM-DD HH:MM:SS)")

    p_ok = sub.add_parser("record-success", help="记一次成功（删除状态文件）")
    p_ok.add_argument("--script", required=True)
    p_ok.add_argument("--state-dir", default=None)

    p_st = sub.add_parser("status", help="人读状态清单")
    p_st.add_argument("--state-dir", default=None)

    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir) if getattr(args, "state_dir", None) else default_state_dir()

    if args.cmd == "whoami-check":
        rc, msg = check_wrangler_credentials(args.timeout)
        stream = sys.stdout if rc == 0 else sys.stderr
        print(f"[d1-state] {msg}", file=stream)
        return rc

    if args.cmd == "record-failure":
        now = None
        if args.now:
            try:
                now = datetime.strptime(args.now, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                print(f"[d1-state] WARN --now 格式非法，改用当前时间: {args.now}",
                      file=sys.stderr)
        st = record_failure(state_dir, args.script, args.error,
                            credential=args.credential, now=now)
        print(f"[d1-state] 已记录失败: {format_problem(st)}", file=sys.stderr)
        return 0

    if args.cmd == "record-success":
        removed = record_success(state_dir, args.script)
        print(f"[d1-state] 成功已清零: {args.script}"
              + ("（删除原失败状态）" if removed else "（无失败状态残留）"), file=sys.stderr)
        return 0

    if args.cmd == "status":
        return _cmd_status(state_dir)

    return 2


if __name__ == "__main__":
    sys.exit(main())