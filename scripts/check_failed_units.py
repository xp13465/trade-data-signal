#!/usr/bin/env python3
"""check_failed_units.py - 云上 failed-unit 巡检 + 巡检者(守护链路)自身存活检查
(#196①, F1 族「巡检/链路自身死亡」可见性统一, 2026-10-05)

【为什么需要它(病灶)】
  #194/#191 独立审查同族结论: **全站没有任何 `systemctl --failed` 的消费方**
  (`schedule_monitor` 11 个 label 无 patrol; `schedule_stats` 三副本 `grep -c patrol` = 0)。
  ⇒ 任何 unit 静默失败(#194 的 exit 3 / #191 的漂移巡检被删)都**无人看见**: systemd 层
  可见(unit failed + journal), 自动监控层零消费 —— 要人工 `systemctl --failed` 才见。
  本脚本 = 把 systemd 层的事实接进监控层(挂在既有云上 timer `trade-schedule-monitor.timer`,
  15min 一轮, 由 schedule_monitor.sh 子进程调用; 同 check_s06_freshness.py 先例)。
  **只告警、不改生产**(不 restart/reset-failed/enable/disable 任何 unit)。

【两类判定(都是「真故障判别维度」, 非噪音; memory alert-denoise-keep-fault-discriminator)】
  ① failed-unit: `systemctl list-units --state=failed --no-legend --plain` 非空 → 真故障。
  ② 巡检者自身存活(= ② 「不能巡检者死了没人知」): 对 WATCHMAN_UNITS(7 个「无数据产物可反证
     其存活」的守护/巡检/监控 timer: patrol / schedule-monitor / check-monitor-heartbeat /
     self-heal / r2-consistency / check-data-gap / overfit-monitor; 收录边界见
     alert_denoise_rules.WATCHMAN_UNITS 注释)逐个判:
       - LoadState == not-found      → unit 文件离盘(巡检被删的最彻底形态)
       - UnitFileState != enabled    → 被停用/禁用/掩蔽(不再随开机调度)
       - timer ActiveState != active → 不再被调度(停摆)
       - 被触发 .service 的 ExecStart 脚本本体不在盘 → systemd 会静默跳过(见下面「脚本存在性」
         一节)。⚠️ `.timer` 自身**没有 ExecStart 属性**, 须经 `Triggers` 解析到它触发的
         `.service` 再取 ExecStart(见 `_resolve_exec_entries`; 2026-10-06 #203 根因)
     ⚠️ 状态判定一律 `systemctl show -p ActiveState ...`, **禁 `is-active`**(oneshot 运行中
     is-active=activating 且 rc=3, 与 inactive 同 rc —— #160 P0 同款陷阱; 见
     schedule_monitor.sh:launchctl_loaded 注释: 该函数语义是「unit 是否已加载」不是「是否在跑」)。

【为什么 ② 必须由本脚本承担(与 cloud_unit_patrol.sh 的 ConditionPathExists 有关)】
  trade-cloud-unit-patrol.service 带 `ConditionPathExists=<REPO>/scripts/cloud_unit_patrol.sh`。
  脚本被删时 ⇒ systemd **根本不启动该 unit**(条件不满足 = skipped, 不进 failed) ⇒
  ① failed-unit 通道**看不见**它。此时唯一能发现的是 **② 的漏跑通道**(register 进
  schedule_monitor/gen_schedule_stats 的 TASKS, 日志不再出现「开始」行 → 漏跑告警)。
  ⇒ ①②③ 四路(本脚本 failed-unit / 本脚本 timer 存活 / 本脚本脚本存在性 / 注册漏跑)覆盖的
     失败模式互不重叠:
     脚本被删→注册漏跑(注册过的)或脚本存在性检查(全 7 个守护 unit, 与注册无关);
     timer 被停/unit 离盘→本脚本存活检查; 跑起来却失败(漂移/exit3)→本脚本 failed-unit +
     gen_schedule_stats exit!=0 通道。

【与 patrol 自身通道的去重(防同一次漂移两封邮件)】
  patrol 漂移时它自己已 `notify --severe --dedup-key cloud_unit_patrol_drift`(含差异明细),
  且该 unit 会留在 failed 态 → 本脚本 ① 也会看到同一个 failed unit。为避免复述, 本脚本对
  `trade-cloud-unit-patrol.service` 这一个 unit 做**定向抑制**: 若 patrol 包装器通道已为
  **本次运行实例**发过告警(wrapper_channel_alerted, 同 R7/R3 先例), 该 failed 项降为日志。
  反例保证: 包装器 notify 发送失败/去重表缺失 → 判定 False → 本脚本照报(双保险, 不吞真故障)。
  其余任何 unit 失败照报不抑制(它们没有别的通道)。

【告警】--notify 才真发(默认 dry 只打印, 单测/手动排查安全):
  notify.py <subject> <body> --severe --from-prefix "[告警]"
    --dedup-key failed_units_patrol --dedup-window 21600
  「连续 3 天仍异常 → 升 critical」由 notify.py 调用侧拦截(#196③,
  alert_denoise_rules.consecutive_days_escalate, 状态 data/failed_units_patrol_state.json)。

【出口码】0=健康 / 1=发现异常(已告警或 dry 打印) / 3=跳过(非云上: 无 systemctl 且无注入样本)
  / 2=内部错误(如注入样本解析失败)。schedule_monitor 侧映射: 1→记日志(自身通道已发);
  其他非 {0,1,3} → 追加一条 SEVERE 进主告警邮件(让「本巡检自己跑挂了」可见)。

【自测桩(生产不设; 全离线、零真通知)】
  --failed-units-file <path>  systemctl --failed 输出的 text(替代真机命令)
  --unit-show-json <path>     {unit: {ActiveState,LoadState,UnitFileState,Triggers,ExecStart}} JSON
                              (替代 systemctl show; **必须与云上真实形态同形**: `.timer` 条目
                              只带 Triggers(点向其 .service), ExecStart 落在被触发的 `.service`
                              条目上; ExecStart 可 str/list。见 scripts/tests/ 的云上实测 fixture)
  --stats-file <path>         schedule_stats.json(抑制判定读 patrol last_run; 默认 <repo>/static-site/data/)
  --dry-run                   强制不发(默认即 dry, 此开关供调用方显式声明)
复现命令见文件尾 `## 复现段` 与 scripts/tests/test_196_patrol_visibility_20261005.py。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# absolute() 非 resolve(): 保持 <REPO>/scripts symlink 字面路径, 与调用方同树(同 check_s06_freshness)
SCRIPT_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPT_DIR))
import alert_denoise_rules as adr  # noqa: E402

# 数据仓候选: env 注入优先(云上 REPO=/home/ubuntu/code/trade-data), 回退 mac 本机 trade-data
DEFAULT_REPO_CANDIDATES = [
    Path(c) for c in (
        os.environ.get("REPO", ""),
        os.environ.get("GIT_REPO", ""),
        os.environ.get("MAIN_REPO", ""),
        "/Users/linhuichen/code/trade-data",
    ) if c
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "static-site" / "data").exists()),
                    DEFAULT_REPO_CANDIDATES[0])

# 巡检者: 由 alert_denoise_rules.WATCHMAN_UNITS 单一事实源提供(避免「清单两份」漂移)
WATCHMAN_UNITS = adr.WATCHMAN_UNITS
# patrol 包装器通道的 dedup key(= cloud_unit_patrol.sh 字面量)与其 unit 名
PATROL_UNIT = "trade-cloud-unit-patrol.service"


def _run_failed_units_cmd():
    """真机取 failed unit 列表(--no-legend 无表头/图例; --plain 不染色)。"""
    r = subprocess.run(
        ["systemctl", "list-units", "--state=failed", "--no-legend", "--no-pager", "--plain"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")


def _run_unit_show(unit):
    """取单个 unit 的三态 + Triggers + ExecStart(Key=Value 解析, 不依赖 -p 输出顺序)。

    ExecStart 可能多行(oneshot 多命令)⇒ 收集为 list(其余键仍是标量, 调用点不变)。
    Triggers: `.timer` 触发的目标 unit(`Triggers=<name>.service`), 供 _resolve_exec_entries
    把 timer 解析到真正持 ExecStart 的 .service(#203); 对 .service 该字段为空, 无害。
    """
    r = subprocess.run(
        ["systemctl", "show", "-p", "ActiveState", "-p", "LoadState", "-p", "UnitFileState",
         "-p", "Triggers", "-p", "ExecStart", unit],
        capture_output=True, text=True, timeout=30, check=False,
    )
    d, exec_lines = {}, []
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "ExecStart":
                exec_lines.append(v)
            else:
                d[k] = v
    if exec_lines:
        d["ExecStart"] = exec_lines
    return d


def _as_list(v):
    """ExecStart 等字段: str / list[str] / None → list[str](滤掉 None/空串)。"""
    if v is None:
        return []
    items = [v] if isinstance(v, str) else list(v)
    return [str(x) for x in items if x not in (None, "")]


def _resolve_exec_entries(unit, kind, show):
    """取「该巡检 unit 真正会执行的脚本」的 ExecStart 原始行(供 extract_script_paths 解析)。

    ⚠️ 为什么不能直接读 unit 自身的 ExecStart(2026-10-06 #203 根因, §18 L49 同台):
      ②b 层的 WATCHMAN_UNITS **全部是 `.timer`**; timer 单元**没有 ExecStart 属性**(其职责
      是调度, 真正执行在被触发的 `.service` 里)⇒ `systemctl show <timer> -p ExecStart` 恒为空
      ⇒ 解析出的脚本路径恒为空 ⇒ 该层在生产**恒空转(永不报警, 假绿)**。

    正确取法(云上实测 systemd 249 形态): `.timer` 的 `Triggers=<name>.service` 是权威触发对象
    (实测: trade-cloud-unit-patrol.timer → Triggers=trade-cloud-unit-patrol.service), 对每个
    被触发 unit 取 ExecStart 并聚合。Triggers 为空(unit 未加载/查询失败)时回退同名前缀
    `.service`(systemd 的 timer 默认 `Unit=<同名>.service` 规则); 仍取不到则返回 []。

    **fail-open**: 解析不到就不判, 绝不把「解析失败」报成「脚本被删」; 删除形态(LoadState=
    not-found)由 judge_watchman_units 负责报, 不靠本层。

    show: 取单个 unit 字段的 callable(unit -> dict); 真实(systemctl show)/注入两态共用同一路径。
    """
    if kind != "timer":
        return _as_list((show(unit) or {}).get("ExecStart"))
    targets = str((show(unit) or {}).get("Triggers") or "").split()
    if not targets and unit.endswith(".timer"):
        targets = [unit[: -len(".timer")] + ".service"]
    entries = []
    for t in targets:
        entries.extend(_as_list((show(t) or {}).get("ExecStart")))
    return entries


def _read_patrol_last_run(stats_path):
    """从 schedule_stats.json 取 cloud_unit_patrol.last_run(供 patrol 定向抑制判定)。缺失返回 None。"""
    try:
        for s in json.loads(Path(stats_path).read_text(encoding="utf-8")):
            if s.get("task") == "cloud_unit_patrol":
                return s.get("last_run")
    except Exception:  # noqa: BLE001
        return None
    return None


def _send_notify(repo, subject, body):
    """子进程调 notify.py(--severe 真发)。返回 (ok, detail)。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "notify.py"), subject, body.replace("\n", "<br>"),
             "--severe", "--from-prefix", "[告警]",
             "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY, "--dedup-window", "21600"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()[-300:]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="云上 failed-unit 巡检 + 巡检者自身存活检查(#196①)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="数据仓根(默认按 env/存在性探测)")
    ap.add_argument("--notify", action="store_true",
                    help="真发告警(默认 dry 只打印; schedule_monitor 传此开关)")
    ap.add_argument("--dry-run", action="store_true", help="强制不发(默认即 dry, 显式声明用)")
    ap.add_argument("--failed-units-file", default=None,
                    help="自测桩: 提供 systemctl --failed 输出 text(替代真机命令)")
    ap.add_argument("--unit-show-json", default=None,
                    help="自测桩: {unit: {ActiveState,LoadState,UnitFileState}} JSON(替代 systemctl show)")
    ap.add_argument("--stats-file", default=None,
                    help="自测桩: schedule_stats.json 路径(抑制判定读 patrol last_run)")
    args = ap.parse_args()

    repo = Path(args.repo)
    do_notify = args.notify and not args.dry_run

    _inj_failed = args.failed_units_file is not None
    _inj_show = args.unit_show_json is not None
    # ── 环境守卫: 拿不到权威输入(=非云上, mac 无 systemctl)→ 只打印 + exit 3, 绝不 notify ──
    # 判据与 cloud_unit_patrol.sh 同精神: 「权威源可得」才巡检。mac 上 schedule_monitor 不跑,
    # 但手动/误调本脚本时也不该把「本机没有 systemctl」当成「云上 unit 全挂」而误发告警。
    if (not _inj_failed or not _inj_show) and not shutil.which("systemctl"):
        print(f"[skip] 非云上巡检环境: 无 systemctl 且未提供注入样本 —— 本次不巡检、不发通知。")
        return 3

    # ── ① failed-unit ──
    try:
        if _inj_failed:
            out = Path(args.failed_units_file).read_text(encoding="utf-8")
        else:
            out = _run_failed_units_cmd()
    except Exception as e:  # noqa: BLE001
        print(f"CHECK_FAILED_UNITS_ERROR 读取 failed unit 列表失败: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 2
    failed = adr.parse_failed_units(out)
    suppressed = []
    if failed:
        # patrol unit 定向抑制: 包装器通道已为本次运行实例发过 → 本项降日志(详见文件头)
        _stats_path = (Path(args.stats_file) if args.stats_file
                       else repo / "static-site" / "data" / "schedule_stats.json")
        _patrol_lr = _read_patrol_last_run(_stats_path)
        if PATROL_UNIT in failed and adr.wrapper_channel_alerted(
                repo, _patrol_lr, adr.PATROL_DRIFT_DEDUP_KEY):
            failed = [u for u in failed if u != PATROL_UNIT]
            suppressed.append(f"{PATROL_UNIT}(patrol 包装器通道本次已发, 不复述)")

    # ── ② 巡检者自身存活 ──
    # show: 取单 unit 字段的 callable; 真实(systemctl show)/注入(show_map)两态共用同一解析路径,
    # 防两态逻辑漂移(注入样本必须与云上真实形态同形: .timer 只带 Triggers, ExecStart 在其
    # 触发的 .service 上 —— §18 L49 假样本养绿的根治)。
    if _inj_show:
        try:
            show_map = json.loads(Path(args.unit_show_json).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"CHECK_FAILED_UNITS_ERROR 读取 unit 状态失败: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 2

        def _show(u):
            return show_map.get(u) or {}
    else:
        _show = _run_unit_show
    try:
        rows = []
        for u, k in WATCHMAN_UNITS:
            d = _show(u)
            rows.append({"unit": u, "kind": k,
                         "active_state": d.get("ActiveState"),
                         "load_state": d.get("LoadState"),
                         "unit_file_state": d.get("UnitFileState"),
                         "exec_start": _resolve_exec_entries(u, k, _show)})
    except Exception as e:  # noqa: BLE001
        print(f"CHECK_FAILED_UNITS_ERROR 读取 unit 状态失败: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 2
    watchman = adr.judge_watchman_units(rows)

    # ── ②b 巡检者「被执行的脚本本体」是否还在盘上(§196 同模式暴击面: 脚本被删=静默) ──
    # 为什么单独一层: 带 `ConditionPathExists=<script>` 的 unit(patrol / heartbeat / r2-consistency)
    # 在脚本被删时 systemd **跳过不跑**(既不 failed 也不写日志) ⇒ ①failed-unit 与 ③漏跑
    # 都可能抓不到(漏跑只在注册过 TASKS 的任务上生效)。直接查文件本体 = 与注册无关的兜底。
    # r["exec_start"] 由 _resolve_exec_entries 填: 对 .timer 已解析到其触发 .service 的 ExecStart
    # (timer 自身无 ExecStart, 直读会恒空 → 2026-10-06 #203 生产空转根因)。
    # 判据 fail-open: 只认 .sh/.py 绝对路径(extract_script_paths), 解析不到就不判。
    # 只在云上跑(本函数已过「无 systemctl → exit 3」守卫), 故 /home/ubuntu/... 路径可判真伪。
    script_missing = []
    for r in rows:
        for p in adr.extract_script_paths(r.get("exec_start")):
            if not Path(p).exists():
                script_missing.append(f"{r['unit']} 被执行的脚本已不在盘: {p}"
                                      " —— 该 unit 会被 systemd 静默跳过(ConditionPathExists/ExecMissing)")
    if script_missing:
        watchman.extend(script_missing)

    # ── 汇总 ──
    problems = []
    if failed:
        problems.append("云上 failed unit: " + ", ".join(failed))
    problems.extend(watchman)
    if suppressed:
        for s in suppressed:
            print(f"[suppress] {s}")

    if not problems:
        print(f"CHECK_FAILED_UNITS_OK failed=0 watchman={len(WATCHMAN_UNITS)} 个 timer 全部在跑")
        return 0

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[告警] 云上 unit 巡检发现异常({len(problems)} 项) {now_str[5:16]}"
    body_lines = []
    if failed:
        body_lines.append("<b>failed unit(运行过但失败)</b>: " + ", ".join(failed))
    if watchman:
        body_lines.append("<b>巡检者自身存活异常</b>:")
        body_lines.extend("　- " + w for w in watchman)
    body_lines.append(f"脚本: scripts/check_failed_units.py &nbsp;时间: {now_str}")
    body_lines.append("处置: 人类排查 `systemctl status <unit>` / `journalctl -u <unit> -n 100`;"
                      "确认修复后 `systemctl reset-failed <unit>`(本巡检只告警, 不改生产)。")
    body = "<br>".join(body_lines)
    print(f"CHECK_FAILED_UNITS_FAIL({len(problems)} 项): " + " | ".join(problems))

    if do_notify:
        ok, detail = _send_notify(repo, subject, body)
        if ok:
            print("[failed-units] 告警已发出(--severe)", file=sys.stderr)
        else:
            print(f"[failed-units] 告警发送失败(不落抑制, 下轮重试): {detail}", file=sys.stderr)
    else:
        # dry-run 打印「将要发送的内容」便于人工排查/自验留证(绝不真发)
        print("[failed-units] dry-run: 未真发通知(需 --notify 才发); 将发送内容如下:", file=sys.stderr)
        print(f"  SUBJECT: {subject}", file=sys.stderr)
        print(f"  BODY: {body}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())