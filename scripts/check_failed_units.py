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
  ② 巡检者自身存活(= ② 「不能巡检者死了没人知」): 对 WATCHMAN_UNITS(9 个「无数据产物可反证
     其存活」的守护/巡检/监控 timer: patrol / schedule-monitor / check-monitor-heartbeat /
     self-heal / r2-consistency / check-data-gap / overfit-monitor / alert-weekly-review; 收录边界见
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
     脚本被删→注册漏跑(注册过的)或脚本存在性检查(全 9 个守护 unit, 与注册无关);
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
    --dedup-key failed_units_patrol --dedup-window 0
  ⚠️ #240 ②(2026-10-09): 窗口 21600 → **0**。每日 1 次 / 集合变化判定的闸门已移到本脚本自管
  (adr.failed_units_daily_judge), 若仍留 6h 窗会把「新增立即报」吞掉。--dedup-key 一字不改
  (notify.py #196③「连续 3 天升 critical」以该 key 精确接线)。
  ⚠️ #240 ② 精修(2026-10-09, 方向感知): 判定**拆方向** —— **新增** failed unit 立即报;
  **集合缩小(=恢复进展)** 静默; 次日首报照报; 同集合 24h 二次 added 抖动抑制(unit 反复
  fail→clear→fail)。判据见 adr.failed_units_identity / adr.failed_units_daily_judge。
  真故障判别维度保留: 新增立即报 + #196③ 连续 3 天升 critical + 跨日首报。
  ⚠️ F1 复审(2026-10-09): notify.py **恒 return 0**(含「全部渠道未发出」),
  故「是否发出去」判据不能只看 rc(否则渠道全失败照样落签名 → 当日同集合全抑制 = 当天失报)。
  ⚠️ 2026-10-22 审查 BLOCK-2 收口: 判据 = `--result-file` 的 status ∈ {sent, digested}
  (digested=已并入当日摘要 buffer, 由 23:25 摘要统一交付 = 已处置); 其余/suppressed/failed/
  结果文件缺失一律不落签 → 下轮重试, 不吞真故障。旧版 notify 的字符串回退已删除(旧 argparse
  不认 --result-file 会直接报错, 回退分支实为死代码; 两脚本同 commit 部署保证版本一致)。
  「连续 3 天仍异常 → 升 critical」由 notify.py 调用侧拦截(#196③,
  alert_denoise_rules.consecutive_days_escalate, 状态 data/failed_units_patrol_state.json)。

【#280 failed-unit 白名单(2026-10-22)】
  有些 failed unit 是**系统层已知噪音**、不是本项目故障(典型: `fwupd-refresh.service`,
  OS 侧 LVFS 固件刷新服务, 退出码 1 与本站无关, 见 docs/ops/failed-units-rca-20261022.md)。
  白名单文件: `docs/deploy/failed-unit-allowlist.txt`(代码仓内, 随 git 走; 云上经
  `$REPO/scripts` symlink 的 resolve() 找到代码仓, 不依赖数据仓有 docs/)。
  格式: 一行一个 unit 名, 支持 `fnmatch` 通配(如 `fwupd*`), `#` 开头为注释。
  规则:
    - 命中白名单 ⇒ **不告警**, 但每轮都打印 `[INFO] 白名单忽略: <unit>`(可追溯, 不是静默丢弃);
    - **禁止白名单 `trade-*`**(本项目的 unit 全部以 trade- 开头)——启动即机检, 命中 ⇒
      stderr 报错 + exit 2(防止有人用白名单把本项目真故障静音, 告警等级不得为安静而降);
      机检是**效果判据**且**不用列举样例**: 探针集合 = 项目真实 unit 全集(静态 =
      `alert_denoise_rules.WATCHMAN_UNITS` + 仓库 unit 文档经 `gen_systemd_units.py` 枚举;
      动态 = 运行时 `systemctl list-unit-files` 的 trade-*.{service,timer,socket};
      动态取不到 ⇒ 回退静态 + 一行 INFO)。任一 pattern 用 fnmatch 命中任一真实 unit ⇒
      exit 2(消息写明「会静音真实 unit Y」)。另加命名空间结构判据: `*.socket` 这类以项目
      unit 后缀结尾的通配即使当前无该类真实 unit 也拒绝, 防未来新增 unit 被旧白名单静音;
    - 白名单文件缺失/为空 ⇒ 按空白名单处理 + 打印 INFO, **不崩**(安全降级);
      而「真实 unit 全集取不到」是另一种情况: **拒绝加载**(exit 2), 不因判不了而放行。

【#275 D1 同步失败消费(2026-10-22)】
  `scripts/sync_fund_score_to_d1.sh` / `sync_fund_screener_to_d1.sh` 失败时写
  `<REPO>/data/d1_sync_state/<script>.json`(连续失败计数, 见 scripts/d1_sync_state.py)。
  本脚本作为**既有巡检链**的消费方(不新增 systemd unit):
    - 连续失败 >= 2 且该连续段尚未告警 ⇒ 发**一条** `--dedup-key d1_sync_fail --dedup-window 0`
      告警(脚本名/连续次数/首失败时间/最后错误/wrangler 凭据状态), 发出后落 `alerted` 标记;
    - 已告警 ⇒ 打印 INFO 不重发(防 15min 一轮轰炸, #269 教训);
    - 单次失败(=1)⇒ 只打印 INFO, 不告警;
    - 同步成功后状态文件被同步脚本删除 ⇒ 自动清零、无残留。
    告警未送达 ⇒ rc=4(与 failed-unit 通道同约定, 由 schedule_monitor 独立复核)。

【出口码】0=健康 / 1=发现异常且告警**真发出**或按设计静默(降噪抑制)/ dry 打印
  / 4=发现异常但告警**未送达**(结构化结果 status ∉ {sent, digested}; 不落签名, 下轮重试)
  / 3=跳过(非云上: 无 systemctl 且无注入样本) / 2=内部错误(如注入样本解析失败、
    白名单非法)。
  schedule_monitor 侧映射(2026-10-21 起): 1→记日志「异常已告警或按设计静默」(不得自证已发出);
  4→独立 SEVERE 复核项「巡检发现异常但告警未送达」; 其他非 {0,1,3,4} → SEVERE「本巡检自己跑挂了」。

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
import fnmatch
import json
import os
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))  # #245 批2 W1: 台账 source 溯源
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# absolute() 非 resolve(): 保持 <REPO>/scripts symlink 字面路径, 与调用方同树(同 check_s06_freshness)
SCRIPT_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPT_DIR))
import alert_denoise_rules as adr  # noqa: E402
import d1_sync_state as d1ss  # noqa: E402  (#275 状态文件模块: 常量/读写单一事实源)

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

# #280 failed-unit 白名单默认路径。
# resolve() 而非 absolute(): 云上 `$REPO/scripts` 是指向 `$GIT_REPO/scripts` 的 symlink,
# 数据仓里没有 docs/; resolve() 落到代码仓(<GIT_REPO>/scripts/check_failed_units.py),
# 父父目录即代码仓根, 白名单随 git pull 更新。
ALLOWLIST_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "deploy" / "failed-unit-allowlist.txt")
# 白名单禁止项: 本项目 unit 全部以 trade- 开头, 允许进白名单 = 允许把真故障静音 ⇒ 启动机检拦下。
# ⚠️ 只用字面前缀判**不够**, 也不能靠「列举代表性样例」: 匹配走 fnmatch(`apply_allowlist`),
# 每补一次样例就会有新写法绕过(第一轮 `*` / `trade*`; 第二轮补 `.timer`/`.socket` 样例后
# `*schedule-monitor.timer` 仍能静音真实 trade-schedule-monitor.timer —— 2026-10-22 三次实测)。
# 根治 = **效果判据用项目真实 unit 全集**, 不是样例:
#   ① 静态源(始终可得): WATCHMAN_UNITS(单一事实源) + 仓库 unit 文档
#      (`gen_systemd_units.py` 解析 docs/deploy/systemd-units-20260912.md, 复用既有入口,
#      不新造第三份清单);
#   ② 动态源(运行时): `systemctl list-unit-files` 里当前 trade-*.{service,timer,socket};
#   ③ 动态取不到 ⇒ 回退静态集合并打一行 INFO(不崩、不放行)。
# 任一 pattern 用 fnmatch 命中任一真实 unit ⇒ error, rc=2 拒绝启动。
# 另加**命名空间结构判据**(防未来新增 unit 绕过列举): 凡以项目 unit 后缀
# (.service/.timer/.socket)结尾、且字面前缀不排除 trade- 的模式(`*.socket` 等)一律拒绝 ——
# 即使当前还没有该后缀的真实 unit, 也不能留「以后新增同类 unit 就被静音」的口子。
FORBIDDEN_ALLOW_PREFIX = "trade-"
PROJECT_UNIT_SUFFIXES = (".service", ".timer", ".socket")
# 代码仓根(resolve 后): 云上 $REPO/scripts 是 symlink, 静态 unit 文档在代码仓而非数据仓。
_CODE_REPO_ROOT = Path(__file__).resolve().parent.parent


def _static_project_units():
    """静态真实 unit 集合: WATCHMAN_UNITS + 仓库 unit 文档枚举(既有入口,不新造清单)。"""
    units = {u for u, _ in WATCHMAN_UNITS}
    try:
        import gen_systemd_units as gsu  # 复用既有枚举器(docs/deploy/systemd-units-20260912.md)
        md_path = _CODE_REPO_ROOT / gsu.MD_REL_PATH
        order, _ = gsu.parse_units(str(md_path))
        units.update(order)
    except Exception as e:  # noqa: BLE001 - 文档缺失/解析失败 ⇒ 降级用 WATCHMAN_UNITS, 不崩
        print(f"[INFO] 静态 unit 文档枚举失败({type(e).__name__}), 本次仅用 WATCHMAN_UNITS "
              f"({len(units)} 个)做白名单效果判定")
    return {u for u in units if u.startswith(FORBIDDEN_ALLOW_PREFIX)}


def _dynamic_project_units():
    """运行时系统现状: 当前 trade-*.{service,timer,socket}(取不到返回空, 由调用方回退静态)。"""
    if not shutil.which("systemctl"):
        return []
    try:
        r = subprocess.run(
            ["systemctl", "list-unit-files", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode != 0:
            return []
    except Exception:  # noqa: BLE001 - 无 systemd/超时 ⇒ 回退静态集合
        return []
    names = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if name.startswith(FORBIDDEN_ALLOW_PREFIX) and name.endswith(PROJECT_UNIT_SUFFIXES):
            names.add(name)
    return sorted(names)


def collect_real_units():
    """收集项目真实 unit 全集 = 静态(WATCHMAN_UNITS + 仓库文档) ∪ 动态(systemctl 现状)。

    动态取不到 ⇒ 回退静态集合并打印一行 INFO —— **不崩、不因取不到而放行**
    (放行由 load_allowlist 的「全集为空 ⇒ 拒绝加载」兜底)。
    """
    static = _static_project_units()
    try:
        dynamic = _dynamic_project_units()
    except Exception:  # noqa: BLE001 - 动态源任何异常都回退静态, 绝不因此放行
        dynamic = []
    units = sorted(static | set(dynamic))
    if dynamic:
        print(f"[INFO] failed-unit 白名单探针: 真实 unit 全集 {len(units)} 个"
              f"(静态 {len(static)} + 系统现状 {len(dynamic)})")
    else:
        print(f"[INFO] 动态 unit 现状取不到, 回退静态 unit 集合({len(static)} 个)判定白名单")
    return units


def _literal_prefix(pattern):
    """fnmatch 模式的字面前缀(第一个通配符之前的部分)。"""
    out = []
    for ch in pattern:
        if ch in "*?[":
            break
        out.append(ch)
    return "".join(out)


def _could_match_project_namespace(pattern):
    """结构判据: 模式是否可能命中 trade-*.<service|timer|socket> 中的**任意**名字。

    fnmatch 整串锚定 ⇒ 若字面前缀与 `trade-` 不相容(如 `fwupd`), 永远匹配不到本项目 unit;
    反之(空前缀 / `trade` / `trade-` / `t*`) 就存在命中可能。这里只对**项目 unit 后缀**结尾的
    模式启用(如 `*.socket`): 当前可能还没有该后缀的真实 unit, 但未来新增不能被静音。
    无后缀的通配(`*patrol*`)交给真实 unit 全集判定, 避免过度拦截 `fwupd*` 这类合法条目。
    """
    if not pattern.endswith(PROJECT_UNIT_SUFFIXES):
        return False
    lit = _literal_prefix(pattern)
    return FORBIDDEN_ALLOW_PREFIX.startswith(lit) or lit.startswith(FORBIDDEN_ALLOW_PREFIX)


def _run_failed_units_cmd():
    """真机取 failed unit 列表(--no-legend 无表头/图例; --plain 不染色)。"""
    r = subprocess.run(
        ["systemctl", "list-units", "--state=failed", "--no-legend", "--no-pager", "--plain"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")


def load_allowlist(path, probe_units=None):
    """读 failed-unit 白名单(#280)。返回 (patterns, errors)。

    - 文件缺失 ⇒ ([], []) 且打印 INFO(安全降级: 按空白名单处理, 绝不崩);
    - 空行 / `#` 注释行忽略;
    - 命中 `FORBIDDEN_ALLOW_PREFIX`(trade-*)⇒ 记入 errors(调用方 exit 2 拒绝运行),
      防止用白名单把本项目真故障静音;
    - **效果判据(防通配绕过)**: 探针集合 = 项目真实 unit 全集
      (静态 WATCHMAN_UNITS + 仓库 unit 文档, 动态 systemctl 现状; 取不到动态则回退静态 + INFO)。
      每个 pattern 用 `fnmatch` 对任一真实 unit 实测命中 ⇒ 记错并写明「会静音真实 unit X」;
    - **命名空间结构判据**: 以项目 unit 后缀结尾、且字面前缀不排除 trade- 的模式
      (`*.socket` / `trade-*.timer` 等)一律拒绝 —— 防「当前没有该后缀真实 unit」时漏判,
      也防未来新增 unit 被旧白名单静音;
    - 真实 unit 全集为空(静态/动态都取不到)⇒ 记错拒绝加载, **不放行**任何模式。
    `probe_units` 仅供单测注入(默认 None = 现场收集)。
    """
    p = Path(path)
    if not p.is_file():
        print(f"[INFO] failed-unit 白名单文件缺失, 按空白名单处理(不静默丢故障): {p}")
        return [], []
    patterns, errors = [], []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:  # noqa: BLE001 - 读失败按空白名单 + 提示, 不阻断其余巡检
        print(f"[INFO] failed-unit 白名单读取失败({type(e).__name__}), 按空白名单处理: {p}")
        return [], []
    if probe_units is None:
        real_units = collect_real_units()
    else:
        real_units = sorted(set(probe_units))
    if not real_units:
        errors.append("无法取得项目真实 unit 全集(静态+动态均为空), 拒绝加载白名单: "
                      f"无法证明任一 pattern 不会静音本项目 unit ({p})")
        return [], errors  # 不放行: 判不了就不加载任何 pattern
    for ln in lines:
        item = ln.strip()
        if not item or item.startswith("#"):
            continue
        if item.startswith(FORBIDDEN_ALLOW_PREFIX):
            errors.append(f"白名单禁止包含本项目 unit(以 {FORBIDDEN_ALLOW_PREFIX} 开头, "
                          f"会把真故障静音): {item} ({p})")
            continue
        hit = next((u for u in real_units if fnmatch.fnmatchcase(u, item)), None)
        if hit:
            errors.append(f"白名单禁止包含会静音真实 unit 的模式: {item} → 会静音真实 unit "
                          f"{hit} ({p})")
            continue
        if _could_match_project_namespace(item):
            errors.append(f"白名单禁止包含会命中本项目 unit 命名空间的模式: {item} → 可匹配 "
                          f"{FORBIDDEN_ALLOW_PREFIX}*.<service|timer|socket> ({p})")
            continue
        if item not in patterns:
            patterns.append(item)
    return patterns, errors


def apply_allowlist(failed, patterns):
    """把 failed unit 列表按白名单拆成 (剩余待报, 已白名单忽略)。

    命中项逐个打印 `[INFO] 白名单忽略: <unit>` —— 忽略但**可追溯**, 不是静默丢弃。
    """
    if not patterns:
        return list(failed), []
    kept, ignored = [], []
    for u in failed:
        if any(fnmatch.fnmatchcase(u, pat) for pat in patterns):
            ignored.append(u)
            print(f"[INFO] 白名单忽略: {u}")
        else:
            kept.append(u)
    return kept, ignored


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


def _read_sig_state(path):
    """读 #240 ② 集合签名状态(缺失/损坏 → {}(视为「集合有变」, fail-loud 照报))。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_sig_state(path, prev_state, *, sent, reason, observed_sig, observed_items,
                     today_str, now_str):
    """原子落盘集合状态(与 consecutive_days_escalate 同款 tmp+replace)。失败仅告警不阻断。

    #240 ② 精修(方向感知): 状态字段(见 alert_denoise_rules.failed_units_daily_judge docstring):
      signature          = 最近一次「真发出」告警的集合签名(原语义保留)
      prev_signature     = **上一轮观测**到的集合签名(供下一轮变更比对)
      items              = **上一轮观测**到的成员列表(方向判定: added/shrunk)
      last_alert_date    = 最近一次真发出告警的自然日
      last_added_signature/last_added_at = 抖动抑制(同集合 24h 二次 added)
    sent=False(降噪静默轮): 只刷新观测字段(prev_signature/items), **不动** signature/last_alert_date
      —— 否则「集合缩小」静默轮会把「上次已报集合」抹掉, 破坏当日去重与抖动判定。
    sent=True 且 reason∈{"added","changed"}: 记 last_added_*(抖动抑制基准; changed=迁移期保守报,
      语义上也是「新集合首报」, 同样需作为抖动基准, 否则首次告警后的同集合二次 added 无基准可比)。
    """
    prev_state = prev_state if isinstance(prev_state, dict) else {}
    new = {
        "signature": observed_sig if sent else str(prev_state.get("signature") or ""),
        "prev_signature": observed_sig,
        "items": list(observed_items or []),
        "last_alert_date": today_str if sent else str(prev_state.get("last_alert_date") or ""),
        "last_added_signature": str(prev_state.get("last_added_signature") or ""),
        "last_added_at": str(prev_state.get("last_added_at") or ""),
        "updated_at": now_str,
    }
    if sent and reason in ("added", "changed"):
        new["last_added_signature"] = observed_sig
        new["last_added_at"] = now_str
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:  # noqa: BLE001
        print(f"[failed-units] 集合签名状态落盘失败(下轮或重复报一次, 不吞真故障): {e}",
              file=sys.stderr)


def _send_notify(repo, subject, body, dedup_key=None):
    """子进程调 notify.py(--severe 真发)。返回 (sent, detail)。

    dedup_key: 告警通道去重键, 默认 failed_units_patrol(原通道一字不改);
    #275 D1 同步通道传 d1_sync_fail(各自独立闸门, 互不占键)。

    ⚠️ #240 ② 起 `--dedup-window 0`: 每日 1 次/集合变化的闸门已由本脚本自管
    (failed_units_daily_judge), 若仍用 6h 窗则「集合有变立即报」会被 notify 的通用去重
    吞掉。dedup-key 保持 failed_units_patrol **一字不改** —— notify.py 的 #196③
    「连续 N 天升 critical」正是以该 key 精确匹配接线(见 notify.py _ESCALATE_CHANNELS)。

    ⚠️ #264 件A(2026-10-15): 上面的 `--dedup-window 0` **只作用于首报通道**(window=0 =
    集合有变立即报, 保持原样)。升级档(升 critical)**不再复用本窗**, 改判 notify.py 侧
    自己的独立窗 `adr.ESCALATED_DEDUP_WINDOW_SECONDS`(实测锚定 72h, 见该常量取值依据)。病灶: 升级档原样复用本窗 ⇒
    check_dedup(key, 0) 恒放行 ⇒ 升级 critical 永不被抑制(10-15 单日 6 封)。本脚本无需改动。

    ⚠️ F1 复审(2026-10-09): 返回的 sent **不是 rc==0**。rc 恒 0 不含告知力: 全渠道失败也
    return 0, 若按 rc 落签名, 渠道故障当天会把同集合告警全部抑制 = 当天失报。

    ⚠️ 2026-10-21 告警黑洞根因修(主判据改为结构化结果): 传 `--result-file` 读 notify.py 写出的
    JSON `status` 字段(字符串判据把「升级档 suppress」也判成未发出 = 7 天零告警根因之一)。
    ⚠️ 2026-10-22 审查 BLOCK-2: 新增独立态 `digested`(已并入当日摘要 buffer, 由 23:25 摘要
    统一交付 = 已处置) —— 必须与「未送达」区分, 否则域聚合场景会 rc=4 打出假 SEVERE, 且
    签名不落盘导致每 15min 重试、域状态滑动窗永不过期(假 SEVERE 持续一整天)。
    判据: status ∈ {sent, digested} → True; suppressed/failed/noop/缺失 → False(不落状态, 下轮重试)。
    旧版 notify 字符串回退已删除(旧 argparse 不认 --result-file 直接报错, 回退分支不可达 = 死代码;
    两脚本同 commit 部署保证版本一致, 见审查差集 D7)。
    """
    # 默认键必须仍是 failed_units_patrol(#196③ 升档接线靠它精确匹配);仅 D1 通道
    # (#275)显式传入自己的键, 两者互不干扰。
    key_args = (["--dedup-key", dedup_key] if dedup_key
                else ["--dedup-key", adr.FAILED_UNITS_DEDUP_KEY])
    fd, result_path = tempfile.mkstemp(prefix="notify_result_", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "notify.py"), subject, body.replace("\n", "<br>"),
             "--severe", "--from-prefix", "[告警]",
             *key_args, "--dedup-window", "0",
             "--result-file", result_path],
            capture_output=True, text=True, timeout=120, check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        _status, _channels = None, {}
        try:
            payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
            _status = payload.get("status")
            _channels = payload.get("channels") or {}
        except Exception:  # noqa: BLE001 - 结果文件缺失/损坏: 按「未送达」处理(不猜)
            _status = None
        if _status is None:
            detail = out.strip()[-300:] or f"rc={proc.returncode}(无输出)"
            return False, f"status=missing(结果文件缺失/损坏, 按未送达处理) {detail}"
        sent = _status in ("sent", "digested")
        detail = (f"status={_status} channels={_channels} "
                  f"recent={(out.strip()[-200:] or '')}")
        return sent, detail
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(result_path)
        except OSError:
            pass


def _check_d1_sync(repo, do_notify):
    """消费 D1 同步失败状态(#275, 2026-10-22)。返回通道 rc: 0=无待报 / 1=已报或按设计静默 / 4=告警未送达。

    只读 `<repo>/data/d1_sync_state/*.json`(同步脚本写, 成功即删), **不跑同步脚本、不改生产**。
    告警闸门 = 状态文件里的 alerted 标记(一轮连续失败只报一次, 防 15min 一轮轰炸):
      连续失败 >= ALERT_THRESHOLD(2) 且 alerted=false ⇒ 发一条; 发出后 mark_alerted;
      alerted=true ⇒ 只打印 INFO; 单次失败 ⇒ 只打印 INFO。
    """
    state_dir = Path(repo) / "data" / d1ss.STATE_DIRNAME
    if not state_dir.is_dir():
        print(f"[INFO] D1 同步状态目录不存在(无失败记录): {state_dir}")
        return 0

    pending, single = [], []
    for p in sorted(state_dir.glob("*.json")):
        st = d1ss.load_state(state_dir, p.stem)
        if not st:
            print(f"[INFO] D1 同步状态文件不可读, 按无状态处理: {p.name}")
            continue
        name = str(st.get("script") or p.stem)
        try:
            n = int(st.get("consecutive_failures") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < d1ss.ALERT_THRESHOLD:
            single.append(f"{name} 连续 {n} 次(未达告警阈值 {d1ss.ALERT_THRESHOLD})")
        elif st.get("alerted"):
            print(f"[INFO] D1 同步连续失败已告警过, 不重复: {name} 连续 {n} 次")
        else:
            pending.append((name, st))

    for line in single:
        print(f"[INFO] D1 同步失败: {line}")

    if not pending:
        return 0

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[告警] D1 数据同步连续失败({len(pending)} 个脚本) {now_str[5:16]}"
    body_lines = ["<b>D1 数据同步连续失败</b>(同一脚本连续 ≥2 次失败, 每个连续段只报一次):"]
    body_lines.extend("　- " + d1ss.format_problem(st) for _, st in pending)
    body_lines.append("处置: 云上 `npx wrangler whoami` 确认登录状态; 修复后重跑对应 sync 脚本"
                      "(成功会自动清零、不再告警)。")
    body = "<br>".join(body_lines)
    for name, st in pending:
        print(f"[d1-sync] 待告警: {d1ss.format_problem(st)}")

    if not do_notify:
        print("[d1-sync] dry-run: 未真发通知(需 --notify 才发); 将发送内容如下:", file=sys.stderr)
        print(f"  SUBJECT: {subject}", file=sys.stderr)
        print(f"  BODY: {body}", file=sys.stderr)
        return 1

    sent, detail = _send_notify(repo, subject, body, dedup_key=d1ss.DEDUP_KEY)
    if not sent:
        print(f"[d1-sync] 告警未发出(不落标记, 下轮重试): {detail}", file=sys.stderr)
        return 4
    for name, _st in pending:
        d1ss.mark_alerted(state_dir, name)
    print(f"[d1-sync] 告警已发出并落 alerted 标记({len(pending)} 个脚本; "
          f"reason=threshold, dedup_key={d1ss.DEDUP_KEY})", file=sys.stderr)
    return 1


def _merge_d1_rc(base_rc, d1_rc):
    """合并两条通道的出口码: 4(未送达)最优先; D1 有待报/已报时把健康轮抬成 1。"""
    if d1_rc == 4:
        return 4
    if d1_rc == 1 and base_rc == 0:
        return 1
    return base_rc


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
    ap.add_argument("--allowlist-file", default=str(ALLOWLIST_DEFAULT_PATH),
                    help="failed-unit 白名单文件(#280; 默认 docs/deploy/failed-unit-allowlist.txt)")
    args = ap.parse_args()

    repo = Path(args.repo)
    do_notify = args.notify and not args.dry_run

    # ── #280 白名单: 先加载+机检(含 trade-* 禁令) ──
    # 放在环境守卫**之前**: 白名单被塞真故障 = 配置事故, 任何环境都必须当场拒绝运行(exit 2)。
    allow_patterns, allow_errors = load_allowlist(args.allowlist_file)
    if allow_errors:
        for e in allow_errors:
            print(f"CHECK_FAILED_UNITS_ERROR {e}", file=sys.stderr)
        return 2

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
    failed, allowlisted = apply_allowlist(failed, allow_patterns)
    suppressed = []
    if allowlisted:
        print(f"[INFO] 本轮白名单忽略 {len(allowlisted)} 个 failed unit: "
              f"{', '.join(allowlisted)}")
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

    # ── #275 D1 同步失败消费(独立通道; 不并入 failed-units 签名/降噪, 各自闸门) ──
    # 放在汇总前: 即便 failed-unit 全健康, D1 连续失败也必须让本次运行 rc!=0 被看见。
    _d1_rc = _check_d1_sync(repo, do_notify)

    # ── 汇总 ──
    problems = []
    if failed:
        problems.append("云上 failed unit: " + ", ".join(failed))
    problems.extend(watchman)
    if suppressed:
        for s in suppressed:
            print(f"[suppress] {s}")

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")
    _sig_state_path = repo / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME
    _prev_state = _read_sig_state(_sig_state_path)
    # 方向判定用的**细粒度成员**(见 adr.failed_units_identity): failed unit 名逐个 + 存活异常逐条
    _identity = adr.failed_units_identity(failed, watchman)

    if not problems:
        # 健康轮: 记录「集合已空」观测 —— 否则「清空后同 unit 重现」会被误判为 shrunk 而**漏报**
        # (真故障判别维度: 重现 = 新一次失败, 必须报)。写条件 (items or prev_signature or signature)
        # 因 signature 永不置空而实质恒真 ⇒ 一旦状态文件已有任何签名, 每个健康轮都会重写该小 JSON
        # 并打 1 行 stderr(微写+日志, 无害)。原注释「仅在曾观测到非空集合时写一次」与实态不符, 已订正。
        if do_notify and (_prev_state.get("items") or _prev_state.get("prev_signature")
                          or _prev_state.get("signature")):
            _write_sig_state(_sig_state_path, _prev_state, sent=False, reason="empty",
                             observed_sig="", observed_items=[],
                             today_str=today_str, now_str=now_str)
            print("[failed-units] 记录「集合已空」观测(供方向判定)", file=sys.stderr)
        print(f"CHECK_FAILED_UNITS_OK failed=0 watchman={len(WATCHMAN_UNITS)} 个 timer 全部在跑")
        return _merge_d1_rc(0, _d1_rc)

    # ── ③ 降噪(#240 ② + 方向感知精修, 2026-10-09) ──
    # 同一失败集合当日只报 1 次(消除 09:45/16:00/22:15 三封同文); **新增** failed unit 立即报;
    # **集合缩小(=恢复进展)** 静默; 次日首报照报; 同集合 24h 二次 added 抖动抑制。
    # 判定为纯函数(adr.failed_units_daily_judge), 状态单独落盘。
    _sig = adr.failed_units_signature(problems)
    _send, _reason = adr.failed_units_daily_judge(_prev_state, _sig, _identity, today_str, now)
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
        if not _send:
            # shrunk(集合缩小=恢复进展) / same-set-same-day(当日同集合) / added-jitter(抖动):
            # 静默, 但仍**刷新观测字段**(prev_signature/items)供下轮方向判定(不动已报集合基准)
            _write_sig_state(_sig_state_path, _prev_state, sent=False, reason=_reason,
                             observed_sig=_sig, observed_items=_identity,
                             today_str=today_str, now_str=now_str)
            print(f"[failed-units] 降噪: 本轮不重发(reason={_reason}; "
                  f"仅「新增 failed unit」/「次日首报」才发)", file=sys.stderr)
            return _merge_d1_rc(1, _d1_rc)
        sent, detail = _send_notify(repo, subject, body)
        if sent:
            # 只有真发出才落状态(发送失败→不落→下轮重试, 不吞真故障)
            _write_sig_state(_sig_state_path, _prev_state, sent=True, reason=_reason,
                             observed_sig=_sig, observed_items=_identity,
                             today_str=today_str, now_str=now_str)
            print(f"[failed-units] 告警已发出(--severe, reason={_reason})", file=sys.stderr)
        else:
            # 2026-10-21: 结构化结果判「真发送」; 未发出 ⇒ 不落签名(下轮重试) + **rc=4**
            # 让 schedule_monitor 把「巡检发现异常但告警没送达」当独立故障复核/上报,
            # 不再自证「自身通道已发告警」(告警黑洞 7 天无人知的另一半根因)。
            print(f"[failed-units] 告警未发出(不落抑制, 下轮重试): {detail}", file=sys.stderr)
            return _merge_d1_rc(4, _d1_rc)
    else:
        # dry-run 打印「将要发送的内容」便于人工排查/自验留证(绝不真发)
        print(f"[failed-units] dry-run: 未真发通知(需 --notify 才发); "
              f"降噪判定 send={_send} reason={_reason}; 将发送内容如下:", file=sys.stderr)
        print(f"  SUBJECT: {subject}", file=sys.stderr)
        print(f"  BODY: {body}", file=sys.stderr)
    return _merge_d1_rc(1, _d1_rc)


if __name__ == "__main__":
    sys.exit(main())