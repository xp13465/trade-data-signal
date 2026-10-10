#!/bin/bash
# schedule_monitor.sh - 计划任务执行监控（方案B：独立监控脚本 + launchd 每15分钟触发）
#
# 9 个 launchd 计划任务：update_all / backfill_evening / intraday_snapshot /
# futures_backfill / lhb_backfill / rzhb_backfill / etf_national_team / lab_auto /
# us_stock_morning。
# 每个任务的计划时点表来自 ~/Library/LaunchAgents/com.trade.*.plist 的 StartCalendarInterval。
#
# 检查项（10 维度, R2迁移后72h监控 2026-08-08 扩展, 2026-08-17 加维度⑦飞书配置+维度⑧hook心跳
#   +维度⑨飞书ws假死, 2026-10-05 加维度⑩主机资源）：
#   1) 漏跑：当前时间落在某任务计划时点 + 30min 容忍窗口内，但 last_run < 计划时点 = 漏跑告警
#   2) 退出失败：schedule_stats.json 中 last_exit 非 0（非 null，null=进行中/无数据不算失败）
#   2b) log异常关键词：scan_log_anomaly 抓 Traceback/异常类名/FATAL（exit=0 不可信, 脚本吞异常漏报）
#   3) 执行耗时：last_duration_sec 超阈值告警（intraday>10min/update_all>70min/backfill>75min，
#      2026-08-14 依实测重标，原 update_all>30min 误报正常日 60min）
#   4) launchctl 加载：11 个 com.trade label 未加载 = launchd 层挂了
#   5) 产物时效（Worker路径）：线上 overview.json collected_at vs NOW, 主站单域名(R2直连容错见⑥), 盘中<20min
#   6) R2直连时效：ssd.fx8.store overview/intraday collected_at 时效 + R2可达性
#      （R2直连stale+Worker stale=upload_r2断; R2直连fresh+Worker stale=CF cache purge失效）
#   7) 飞书配置：config/feishu.json 缺失且 .env 有 FEISHU 凭证（配置丢失），或
#      feishu_listener.err 尾部 10 条内含"feishu.json 不存在"（listener 停摆）
#      （2026-08-17 三件套①防 feishu.json 丢失致飞书静默停摆数天）
#   8) 飞书 hook 心跳自检（#25）：Claude Code 会话活跃(pgrep claude 有进程)但
#      /tmp/feishu_hook_heartbeat 缺失或 >90min 陈旧 → 告警（hook 未触发/静默停摆；
#      文件缺失时额外要求 claude 进程存活 >30min 防刚开机误报；与维度⑦互补）
#   9) 飞书 ws listener 接收侧静默假死（2026-08-17 #25 缺口A）：进程在+ws 连接在但收不到
#      事件时，/tmp/feishu_ws_last_event 陈旧（>90min）→ 告警（KeepAlive 探测抓不到）。
#  10) 主机资源（#164, 2026-10-05, 云上健康巡检 D1 P1-1）：磁盘/inode/内存/swap 使用率
#      >=85% 预警（聚合）/ >=90% SEVERE（即时）—— 原 9 维度只看任务执行面，无一条看主机
#      资源；09-30 磁盘涨到 92% 全靠人眼，写满会先让任务/DB/告警链一起瘫。详见检查块注释。
#
# 告警链路：复用 scripts/notify.py（邮件 + data/alerts/latest.md），告警不阻塞、不重试。
# 阶段3 R2上传失败 notify 已接入: intraday_snapshot.sh upload-index/upload-intraday 失败发
#   notify --severe --dedup-key; deploy.sh upload-all-data 等失败收集 R2_FAIL 发 notify --severe。
#
# 修复闭环: 告警邮件 -> 主控 Claude Code cron 定期查 alert_state.json(活跃告警)/
#   schedule_stats.json(任务状态) -> 派 agent 修正 -> 修正后任务跑新版 exit=0/时效恢复 ->
#   schedule_monitor 检测恢复发恢复邮件。launchd 持久(schedule_monitor/self_heal 不依赖会话)。
# launchd 每15分钟(Minute=0,15,30,45)由 com.trade.schedule-monitor.plist 触发。
#
# 2026-08-14 告警邮件优化:
#   A1 新增"进行中超时检测"(任务 dur=null 未完成, 超计划时点+阈值+缓冲仍不结束 = 疑似卡死
#      告警, 如 update_all 17:50 卡死 54min 无告警的 8-14 事故); 修复 null dur 误恢复
#      (进行中任务 key 保持 active, 不判"已消失"发恢复邮件)。
#   A3 恢复邮件最小静默窗口: 同 key 上次恢复(last_recovered) <30min 不重复发恢复邮件
#      (防 8-12 振荡), 状态仍置 recovered。
#   B2 告警正文模板化: 每项 4 行 [严重度]任务 异常类型 / 影响 / 日志 / 建议;
#      恢复邮件尾加"无需操作,已自动恢复"提示。
set -uo pipefail
# ── REPO/GIT_REPO 单点解析(#195 批2):共享 lib(env 优先零改写 > $0 双布局推导 > fail-loud)──
# 去掉写死的 mac 默认值(原靠 unit 的 Environment= 兜住,env 一丢即静默坏);原 export
# 语义逐字节保留(python 子进程可见性与迁移前一致)。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
cd "$REPO"

# 注：launchd plist 设 REPO=/Users/linhuichen/code/trade-data，trade-data/scripts 是
# trade/scripts 的 symlink（代码共用）；trade-data/data/logs 则是独立真实目录（非 symlink、
# 非 hard link，inode 与 trade/data/logs 不同），launchd 写入的 *_launchd.log 存于此。
# 故 $REPO/data/logs/*_launchd.log 在 trade-data 下可读到正确日志。
export REPO

# 用 python heredoc 处理日期解析 + JSON 读取（bash 处理太繁琐易错）
"$REPO/.venv/bin/python" <<'PYEOF' 2>&1
import hashlib
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# #123 告警降噪 R1~R5 判定规则纯函数(2026-10-01): REPO/scripts 是 trade-data -> trade 的
# symlink, 生产云上同树读得到; 测试脚本 scripts/tests/test_alert_denoise_20261001.py
# import 同一模块打「真实判定函数」反例断言(拒绝逻辑模拟代替真实代码)。
sys.path.insert(0, str(Path(os.environ["REPO"]) / "scripts"))
import alert_denoise_rules as adr  # noqa: E402
# #241 同族(2026-10-09): notify 子进程「是否真发出过」的唯一判据(rc 不可信: notify.py
# main() 所有出口恒 return 0)。用于「先落签后 fire-and-forget 通知」病灶的回滚判定。
from notify_sent import notify_sent  # noqa: E402

REPO = Path(os.environ["REPO"])
LOG_DIR = REPO / "data" / "logs"
STATS_FILE = REPO / "static-site" / "data" / "schedule_stats.json"
MONITOR_LOG = LOG_DIR / "schedule_monitor_launchd.log"

NOW = datetime.now()
TOLERANCE = timedelta(minutes=30)  # 漏跑检查容忍窗口（适用所有任务，与采集频率无关）
# 产物时效检查阈值（intraday 15min 频率 + 5min buffer = 20min）：
#   intraday 15min 推一次 overview.json，下一轮 sch+15min 已推新版，留 5min buffer 给
#   采集+push 耗时（任务2优化后 <7min），超过 20min 即为线上滞后（push 失败或卡死）。
LAG_TOLERANCE = timedelta(minutes=20)

# 8 任务计划时点表（与 ~/Library/LaunchAgents/com.trade.*.plist StartCalendarInterval 对齐）
# 字段：task | launchd log 文件名 | 计划时点列表（HH:MM）
TASKS = [
    # trading_day_only: 非交易日跳过漏跑检查(避免周末误报)。
    #   etf 非交易日脚本不启动 last_run 停周五 < 周末时点 = 误报(必需);
    #   intraday/update_all/backfill 非交易日启动写"开始"行 last_run 更新不误报,
    #   但加 trading_day_only=True 额外保险 + 减少无意义检查。
    #   us_stock_morning 无交易日闸门每天跑(美股周末虽休但脚本仍启动采旧数据) = False。
    {"task": "update_all",          "log": "update_all_launchd.log",
     "trading_day_only": True,
     "schedules": ["17:50"],
     # 2026-10-04 云上 trade-update-all.timer 周日错峰(Mon..Sat 17:50 / Sun 22:30):
     # 进行中超时检测拿当天实际时点当起点, 否则周日 22:30 新 run 被算成已运行 280min 误报
     # (2026-10-04 22:30 实证)。漏跑检查周日因 trading_day_only=True 天然跳过, 不受影响。
     "schedules_weekend": ["22:30"]},
    {"task": "backfill_evening",    "log": "backfill_evening_launchd.log",
     "trading_day_only": True,
     "schedules": ["02:00", "16:35", "21:00"]},  # 2026-07-29 加 21:00 槽：csi_div/div_lowvol T日晚发布，21:00 提前采(原仅 02:00 兜底)
    {"task": "intraday_snapshot",   "log": "intraday_snapshot_launchd.log",
     "trading_day_only": True,
     "schedules": [  # 2026-07-29 plist 盘中28次(10m节奏+11:32上午收盘收尾/13:01下午开盘首采/15:02收盘收尾)+15:35/20:35收盘后, 共30时点
         "09:25", "09:35", "09:45", "09:55", "10:05", "10:15", "10:25", "10:35", "10:45", "10:55",
         "11:05", "11:15", "11:25", "11:32",
         "13:01", "13:05", "13:15", "13:25", "13:35", "13:45", "13:55",
         "14:05", "14:15", "14:25", "14:35", "14:45", "14:55", "15:02",
         "15:35", "20:35"]},
    {"task": "futures_backfill",    "log": "futures_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["20:05", "21:00"]},
    {"task": "lhb_backfill",        "log": "lhb_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["18:30", "19:30"]},
    {"task": "rzhb_backfill",       "log": "rzhb_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["08:00"]},  # 2026-07-29 19:15->T+1 08:00：SSE官方T+1早晨发布T日(非误判18-19点)，19:15连续采不到T日
    {"task": "etf_national_team",   "log": "etf_national_team_launchd.log",
     "trading_day_only": True,  # 非交易日脚本不启动(无"开始"行), 必需跳过漏跑检查避免周末误报
     "schedules": ["20:07", "21:30"]},
    {"task": "lab_auto",            "log": "update_lab_launchd.log",
     "trading_day_only": True,
     "schedules": ["19:00"]},
    {"task": "us_stock_morning",    "log": "us_stock_morning_launchd.log",
     "trading_day_only": False,  # 无交易日闸门, 每天跑(美股周末休但脚本仍启动采旧数据 exit=0)
     "schedules": ["05:00"]},  # 2026-07-29 新增：美股04:00收盘后1h采集+deploy，原监控盲区补齐
    # overfit_monitor: 2026-08-25 监控盲区收尾批补入(用户拍板)。此前打点 rc!=0 无自动
    # 消费方(filtered 键事故「校验存在≠校验生效」同款); 配套 overfit_monitor.sh 日志已改
    # 固定 append + 标准开始行(START_RE 可解析)。退出失败/log 异常路径走 schedule_stats.json
    # 全量遍历(gen_schedule_stats TASKS 已加), 此处只管漏跑+进行中超时。
    {"task": "overfit_monitor",     "log": "overfit_monitor_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["21:40"]},
    # s06_snapshot: 2026-08-26 补入(S06 快照每日盘后重生链路, 切全站默认前置)。
    # 同 overfit_monitor 模式: 固定 append + 标准开始/结束行(START_RE 可解析), 此处管漏跑;
    # 「跑了但产物仍过期」的语义盲区由下方 check_s06_freshness.py 检查点兜底。
    {"task": "s06_snapshot",        "log": "s06_snapshot_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["20:35"]},
    # check_data_gap: 2026-08-27 补入(采集数据缺口/停更告警检测器, 告警兜底批 #103 方案A+S2)。
    # launchd com.trade.check-data-gap 交易日 22:35 跑 check_data_gap_alerts.sh
    # (北向深缺口不自愈/停更 + accum_nav 窗外缺口 + 宽度族保鲜, 告警走 notify.py)。
    # 固定 append + 标准开始/结束行, standard 模式可解析; 此处只管漏跑+进行中超时,
    # 数据级告警由检测器自身出口承担(gen_schedule_stats TASKS 已同步注册)。
    {"task": "check_data_gap",      "log": "check_data_gap_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["22:35"]},
    # r2_consistency: 2026-10-05 补入(#160 / D5 P0-1, §22 三站一致性 HTTP 层零校验收口)。
    # 云上 trade-r2-consistency.timer 每日 23:20 跑 check_r2_consistency.sh
    # (local vs R2直链 vs CF r2-proxy vs 主站同源 四源比对 9 个核心产物; rc!=0 → notify --severe)。
    # 每日跑不限交易日: 「各源一致」是不变量, 周末被外部覆盖同样要抓(故 trading_day_only=False)。
    # 固定 append + 标准开始/结束行, standard 模式可解析; 此处只管漏跑。
    # ⚠️ 进行中超时/执行耗时两通道**刻意不覆盖本任务**(未入 DUR_THRESHOLDS; #160 收口
    #    2026-10-05 判定, 与 check_data_gap 同款), 理由:
    #    ①区间内无可行阈值——内层 run_to 900 杀掉挂死的 python 后包装器仍会写完结束行
    #      (dur≈901s), 阈值取 900 就会为同一实例再发一封「执行耗时超标」= 与包装器自身
    #      severe 双响(正是 R7② 要消除的双通道); 取 >960(外层 systemd TimeoutStartSec=960)
    #      则 systemd 先硬杀 → 该通道永不触发 = 死配置。
    #    ②进行中超时触发点 = 23:20 + 900s + 缓冲0min = 23:35, systemd 23:36 已硬杀, 而
    #      monitor 轮次 :00/:15/:30/:45 永不落在该 1 分钟缝里。
    #    → 卡死覆盖由「内层 run_to 900 + 外层 TimeoutStartSec=960」双层硬闸 + 退出失败通道
    #      (last_exit!=0)承担; 本行只管漏跑。
    # 数据级告警由审计器自身出口承担(gen_schedule_stats TASKS 已同步注册)。
    {"task": "r2_consistency",      "log": "r2_consistency_launchd.log",
     "trading_day_only": False,
     "schedules": ["23:20"]},
    # cloud_unit_patrol: 2026-10-05 补入(#196②, F1 族「巡检/链路自身死亡」可见性统一;
    # 与 gen_schedule_stats.py TASKS + LABEL_MAP 同步注册)。
    # systemd trade-cloud-unit-patrol.timer 每日 08:27 跑 cloud_unit_patrol.sh(云上 unit 直连
    # vs 仓库快照漂移比对)。**为何必须注册**: 该 unit 带 ConditionPathExists=<REPO>/scripts/
    # cloud_unit_patrol.sh —— 脚本被删时 systemd 根本不启动(条件不满足=skipped, 不进 failed)
    # ⇒ check_failed_units.py 的 failed-unit 通道看不见; **唯一**能发现的是本行支撑的漏跑通道
    # (日志不再出现「开始」行)。缺则 #191 patrol 被删 = 永久静默(#194/#191 P2-1 同源病灶)。
    # 每日跑不限交易日(「快照==云上」是不变量, 周末手改同样要抓)。
    # exit!=0 通道: patrol rc!=0(漂移/exit3)→ failed unit; 该 unit 已被上条 check_failed_units.py
    # 巡检覆盖且 patrol 自身有 notify 通道 ⇒ exit!=0 汇总通道按下方 r2_consistency 先例做
    # 同实例去重(patrol_wrapper_alerted), 防同一次漂移三封邮件。
    {"task": "cloud_unit_patrol",   "log": "cloud_unit_patrol_launchd.log",
     "trading_day_only": False,
     "schedules": ["08:27"]},
    # turnover_backfill: 2026-09-09 补入(#82 C6: turnover 摘出 update_all 主链独立延后跑)。
    # launchd com.trade.turnover-backfill 交易日 21:10 跑 turnover_backfill.sh
    # (baostock 增量 + cleanup_d3d2 算 a_turnover_* 入 daily_metric + 增量重导 overview/a-stock
    # 传 R2)。固定 append + 标准开始/结束行, standard 模式可解析; 此处只管漏跑+进行中超时。
    # ⚠️ 时点 21:10 为默认建议值(避 21:00 backfill/futures、21:30 etf-nt、22:00 public-fund-full),
    #    最终以主控 merge 时确认的 launchd 部署时点为准。
    {"task": "turnover_backfill",   "log": "turnover_backfill_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["21:10"]},
    # nextday_plan: 2026-09-10 补入(PRD 阶段一次日买入计划生成器, F1 机检链收编)。
    # launchd com.trade.nextday-plan 交易日 22:30 跑 nextday_plan.sh
    # (17:50 export + 20:35 s06 定稿后, 等 21:47 etf_daily 第二批回补当日收盘价再 22:30 生成
    #  次日计划 → data/nextday_plan.json + 两树 static-site/data/ + R2 + 通知; 空计划合法)。
    # 日志固定 append + 标准开始/结束行, standard 模式可解析; 此处只管漏跑+进行中超时,
    # 数据级(过期/缺失/结构)由 check_data_integrity.nextday_plan + check_r2_consistency 出口兜底。
    {"task": "nextday_plan",        "log": "nextday_plan_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["22:30"]},
    # nextday_gap_check: 2026-09-17 补入(#45 伪跳空二次剔除, F3 机检链收编)。
    # systemd trade-nextday-gap-check.timer 交易日 09:26 跑 nextday_gap_check.sh
    # (集合竞价 9:25 结束后拉 akshare 当日开盘价, 对 buy_date==today 买入行做伪跳空二次剔除;
    #  就绪闸 + 300s 重试, 最坏 ~600s; 开盘价取不到则 severe 告警 + 标「待人工」)。
    # 日志固定 append + 标准开始/结束行, standard 模式可解析; 此处只管漏跑+进行中超时。
    {"task": "nextday_gap_check",   "log": "nextday_gap_check_launchd.log",
     "trading_day_only": True,  # 非交易日脚本闸门跳过不写开始行, 必需跳过漏跑检查避免周末误报
     "schedules": ["09:26"]},
]

# 标准任务开始行：=== xxx.sh 开始 YYYY-MM-DD HH:MM:SS ===
START_RE = re.compile(r"开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# etf_nt 任务开始行：[etf_nt] daily 开始 YYYY-MM-DD HH:MM:SS
ETF_START_RE = re.compile(r"\[etf_nt\] daily 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


# #234 甲5(2026-10-10): 容忍日志被 gzip —— 日志归档压缩后 .log 不再存在, 回退读
# 同名 <name>.log.gz, 避免「文件缺失 → last_run=None → 落计划窗口即漏跑误报」。
# 未压缩场景 .log 存在 → 返回原路径, 与改造前逐字等价(零行为变化)。
def resolve_log_path(path: Path):
    """返回可读日志路径: 原 .log 优先, 缺失回退同名 .log.gz, 都无 → None。"""
    if path.exists():
        return path
    alt = path.with_name(path.name + ".gz")
    return alt if alt.exists() else None


def open_log_text(path: Path):
    """按实际形态打开日志文本句柄(.gz → gzip.open, 其余普通 open)。path 须已存在。"""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def parse_last_run(log_path: Path):
    """从 launchd log 解析最近一次开始时间作为 last_run（含 etf_nt 变体）

    #234 甲5(2026-10-10): 容忍日志被 gzip（.log 缺失 → 回退 .log.gz）。
    """
    resolved = resolve_log_path(log_path)
    if resolved is None:
        return None
    last = None
    try:
        with open_log_text(resolved) as f:
            for line in f:
                m = START_RE.search(line) or ETF_START_RE.search(line)
                if m:
                    last = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"[warn] 解析 {log_path.name} 失败: {e}", file=sys.stderr)
    return last


def today_schedule(hm: str) -> datetime:
    """今天 HH:MM 的 datetime（second=0）"""
    h, m = hm.split(":")
    return NOW.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def schedules_for_today(t: dict) -> list:
    """返回今天(按 weekday)适用的计划时点列表。

    update_all: 周一~周六 17:50 / 周日 22:30(2026-10-04 云上
    trade-update-all.timer OnCalendar=Mon..Sat 17:50:00 + Sun 22:30:00,
    周日错峰避开 evening 链)。进行中超时检测必须按当天实际时点算起点,
    否则周日 22:30 新 run 被拿 17:50 当起点误算成「已运行 280min」——
    2026-10-04 22:30 实证误报(schedule_monitor_launchd.log)。
    其余任务无周日差异(无 schedules_weekend), 直接返回 schedules。
    """
    scheds = t["schedules"]
    weekend = t.get("schedules_weekend")
    if weekend:
        # datetime.weekday(): 0=周一 ... 6=周日
        scheds = weekend if NOW.weekday() == 6 else scheds
    return scheds


alerts = []
recoveries = []  # 异常恢复通知(log_anomaly 从 true 变 false)

# 告警去重/抑制机制(2026-07-20): 同一异常持续不重复发邮件,异常消失发恢复邮件
# state 文件不进 git(与 sentiment.db 同级),丢失时 24h stale 降级兜底
ALERT_STATE_FILE = REPO / "data" / "alert_state.json"


def load_alert_state():
    """读 alert_state.json,不存在/异常返回 {}"""
    if not ALERT_STATE_FILE.exists():
        return {}
    try:
        with open(ALERT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] 读 alert_state.json 失败(按空 state 处理): {e}", file=sys.stderr)
        return {}


def save_alert_state(state):
    """写 alert_state.json(目录不存在自动创建)"""
    try:
        ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[warn] 写 alert_state.json 失败: {e}", file=sys.stderr)


def _diff_transition(new_state, pre_state, status):
    """本轮从「非 status」变为 status 的 key 列表(= 本轮新落签/新翻状态的 key)。

    #241 同族(2026-10-09): 用于「先落签后 fire-and-forget 通知」病灶的精确回滚 ——
    只回滚本轮新变 active(告警)/recovered(恢复)的 key, 不动本轮未变化的既有 active
    (持续抑制态)、pending 计数、r5_congestion 状态(无 status 字段) —— 语义最小面。
    """
    out = []
    for k, v in new_state.items():
        if isinstance(v, dict) and v.get("status") == status:
            pv = pre_state.get(k)
            if not (isinstance(pv, dict) and pv.get("status") == status):
                out.append(k)
    return out


def _rollback_transition(new_state, pre_state, status):
    """把本轮新落签(→status)的 key 回滚到本轮开始前的值; 返回回滚条数。

    fail-safe: 通知未确认送达 ⇒ 不落签 ⇒ 下轮重试(条件持续时每轮重发, 通道恢复后首轮
    送达即止)。只回滚本轮 diff, 不动历史状态。
    """
    keys = _diff_transition(new_state, pre_state, status)
    for k in keys:
        if k in pre_state:
            pv = pre_state[k]
            new_state[k] = dict(pv) if isinstance(pv, dict) else pv
        else:
            new_state.pop(k, None)
    return len(keys)


alert_state = load_alert_state()
# #241 同族(2026-10-09): 本轮开始前状态快照 —— 供「通知未确认送达 ⇒ 回滚本轮新落签」使用
# (病灶: 收尾聚合 save_alert_state 先落签, 之后 fire-and-forget notify 丢返回值 ⇒ 通道全挂时
#  当晚计划任务告警丢失且 state 已落签 ⇒ 条件持续期永不重发)。
_STATE_PRE = {k: (dict(v) if isinstance(v, dict) else v) for k, v in alert_state.items()}
seen_keys_this_run = set()  # 本次运行仍存在的异常 key(防误报恢复)
# 2026-08-14 告警优化 A1: 进行中(未完成)任务集合。dur=null + exit=null = 任务仍在跑。
# 用于: ①进行中超时检测(卡死/异常慢) ②恢复检测跳过进行中任务的 key(防 8-14 误恢复)。
in_progress_tasks = set()

# 2026-08-14 告警优化 A3: 恢复邮件最小静默窗口。同 key 上次恢复(last_recovered)距今
# <30min 则不重复发恢复邮件(防 8-12 振荡: active->recovered->active 快速交替轰炸)。
# 状态仍置 recovered(异常确已消失), 仅抑制恢复邮件。
# 2026-09-24 告警降噪 P1(告警噪音证据 2026-09-24): 30min->6h。计划任务异常 57 封的半噪音
# 根因 = recovered->active 振荡(瞬时异常每轮复现被当"新异常"反复 SEVERE)。6h 同时充当
# 恢复邮件静默窗 + _recurrence_suppressed 复现抑制窗: 真卡死(持续 active >6h)仍响, 振荡不轰炸。
RECOVERY_COOLDOWN = timedelta(hours=6)


def _recovery_cooldown_ok(_key, _info):
    """A3: 同 key 上次恢复(last_recovered)距今 <RECOVERY_COOLDOWN(6h) 返回 False(不重复发恢复邮件)。"""
    _lr = _info.get("last_recovered")
    if not _lr:
        return True
    try:
        _lr_dt = datetime.strptime(_lr, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True
    return NOW - _lr_dt >= RECOVERY_COOLDOWN


def _recurrence_suppressed(existing):
    """P1(2026-09-24 告警降噪): recovered 复现抑制。检测循环里 dedup_key 已存在但
    status != active(recovered) = 异常曾恢复又复现; 若距上次恢复 <RECOVERY_COOLDOWN(6h)
    = 同一事件的瞬时振荡(15min 轮询每次 detected 反复当"新异常"直发 = 9-18 一天 13 封
    根因), 抑制 SEVERE 不重发。首次发现(None)/active(持续异常,走既有 suppress)/超过
    窗口后复现(真复发)均放行——真卡死不被吞。"""
    if existing is None:
        return False
    if existing.get("status") == "active":
        return False  # active=持续异常, 由既有 suppress 分支处理
    _lr = existing.get("last_recovered")
    if not _lr:
        return False  # 无恢复记录(如 pending 状态)不抑制
    try:
        _lr_dt = datetime.strptime(_lr, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False
    return NOW - _lr_dt < RECOVERY_COOLDOWN

# 通知分级(2026-08-10): 自愈类(not_loaded/r2_unreachable 等可被 self_heal.sh/网络自愈)
# 连续N次仍异常才通知, 严重类(漏跑/exit失败/数据错)首次即通知。N=2 = 30min(15min频率×2)。
SELF_HEAL_THRESHOLD = 2

# 1) 漏跑检查：对每个任务的每个计划时点，若 now 落在 [sch, sch+30min] 窗口内
#    且 last_run < sch（任务在该计划时点之后没跑过）= 漏跑
#    非交易日跳过 trading_day_only 任务(避免周末误报: etf 等非交易日脚本不启动,
#    last_run 停周五 < 周末时点 = 误报漏跑)。
#    漏跑 suppress(2026-08-01): 同 task 同 sch 同日首次发 SEVERE, 30min 窗口内
#    后续 suppress 不重发(避免 15:15/15:30 两周期重复 2 封邮件, 2026-08-01 intraday
#    15:05 schedules 表写错致误报 2 封事故)。key 含日期每天独立; 不走恢复检测(漏跑
#    补跑不发恢复邮件, 跨日静默清理)。新时点漏跑是不同 key 仍发 SEVERE(不 suppress 新时点)。
try:
    from app.calendar import is_trading_day as _is_trading_day
    _is_today_trading = _is_trading_day()
except Exception as _e:
    print(f"[warn] is_trading_day 判断失败(按交易日处理不跳过): {_e}", file=sys.stderr)
    _is_today_trading = True  # 降级: 按交易日处理(不跳过检查), 避免漏报
for t in TASKS:
    # 非交易日跳过交易日任务的漏跑检查(避免周末误报)
    if t.get("trading_day_only") and not _is_today_trading:
        continue
    log_path = LOG_DIR / t["log"]
    last_run = parse_last_run(log_path)
    last_run_str = last_run.strftime("%Y-%m-%d %H:%M:%S") if last_run else "无"

    for sch_hm in schedules_for_today(t):
        sch = today_schedule(sch_hm)
        # 下界 +60s buffer：launchd StartCalendarInterval 整点触发后，任务脚本有
        # caffeinate + with_lock.py 包装 + mkdir/cd 等启动开销，"开始"行通常延后 3-8s
        # 写入日志。schedule_monitor 同样整点触发(cron Minute=0,15,30,45)，若下界=sch，
        # 读 log 时任务的"开始"行可能还没写入，last_run 解析到上一轮，误报漏跑。
        # 2026-07-23 事故：rzhb/futures/etf 多次整点竞态误报(21:00 futures/21:30 etf/
        # 23:00 rzhb)，下一个 15min 周期自愈 OK。+60s 下界根治：sch+60s <= NOW 才检查，
        # 给任务 1 分钟启动 buffer，覆盖 launchd 启动+写"开始"行的延迟。
        if sch + timedelta(seconds=60) <= NOW <= sch + TOLERANCE:
            # now 在容忍窗口内，检查任务是否在 sch 之后跑过
            if last_run is None or last_run < sch:
                # 漏跑 suppress: key 含日期, 每天每时点独立(不 suppress 新时点)
                missed_key = f"missed|{t['task']}|{sch_hm}|{NOW.strftime('%Y-%m-%d')}"
                seen_keys_this_run.add(missed_key)  # 标记本次仍存在(防误恢复)
                _existing = alert_state.get(missed_key)
                if _existing is None or _existing.get("status") != "active":
                    # 2026-09-29 告警降噪(改动2): 单轮漏跑多为瞬时(09-28 15:02 漏跑 15:35 轮
                    # 自动补跑 exit=0), 首轮记 pending 不通知; 连续 2 轮(30min, 15min频率×2)
                    # 仍无运行 = 真漏跑(非瞬时自愈)才 SEVERE。TOLERANCE=30min 窗口内一个 sch
                    # 最多被检查 2 轮, 故连续 2 轮即覆盖窗口; 窗口内补跑成功(last_run>=sch)
                    # 不进本分支, pending 自然失效(次日 key 含日期独立)。
                    _existing_first = _existing.get("first_seen") if _existing else None
                    _missed_c = (_existing.get("consecutive_count") or 0) + 1 if _existing else 1
                    if _missed_c >= MISSED_CONTINUOUS_THRESHOLD:
                        # 连续 2 轮仍漏跑 = 真漏跑(非瞬时自愈)
                        alerts.append(
                            f"SEVERE: {t['task']} 漏跑 计划<{sch_hm}> toler<30min> "
                            f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> last_run<{last_run_str}>"
                        )
                        alert_state[missed_key] = {
                            "status": "active",
                            "first_seen": _existing_first or NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "consecutive_count": _missed_c,
                            "keyword": f"missed<{sch_hm}>",
                            "line_sample": f"last_run<{last_run_str}>",
                        }
                    else:
                        alert_state[missed_key] = {
                            "status": "pending",
                            "first_seen": _existing_first or NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "consecutive_count": _missed_c,
                            "keyword": f"missed<{sch_hm}>",
                            "line_sample": f"last_run<{last_run_str}>",
                        }
                        print(
                            f"[missed-buffer] {t['task']} 漏跑 计划<{sch_hm}> 连续{_missed_c}/"
                            f"{MISSED_CONTINUOUS_THRESHOLD} 轮, 暂不通知(单轮=瞬时, 补跑即自愈)"
                        )
                else:
                    # 已 active = suppress 不重发, 只 log
                    print(
                        f"[suppress] {t['task']} 漏跑 计划<{sch_hm}> 持续中, "
                        f"last_alerted={_existing.get('last_alerted')}, 不重发"
                    )

# 2) 退出失败检查：从 schedule_stats.json 读 last_exit（非 null 且非 0 = 失败）
#    去重(2026-07-25)：exit!=0 但 last_run 距今 >24h 的旧告警不重复 SEVERE。
#    根因场景：etf_national_team 7/24 20:07 collector crash last_exit=143(假告警)，
#    根因已闭环(bba5ecaa deploy根治 + 6824a43c 真实exit code + c1921857 ProcessPool修crash)，
#    但 stats 旧记录未清(周末不跑，周一 20:07 跑才更新)，schedule_monitor 每15min读到
#    exit=143 非0 -> 持续 SEVERE 告警邮件约192封。
#    去重2(2026-07-30)：exit!=0 走 alert_state.json suppress(与 log异常关键词路径对称)。
#    根因场景：etf_national_team 7/29 21:30 exit=1(deploy rebase失败,a4f48c26修复前),
#    24h 内 schedule_monitor 每15min读到 exit=1 -> 持续 SEVERE 邮件约50封(轰炸用户)。
#    根因:exit!=0 路径只做24h stale去重,没走 alert_state suppress(每15min append SEVERE)。
#    修复:同task同exit_code首次发SEVERE+写state active,持续suppress,exit变0/null发恢复邮件。
#    规则：last_run 距今 >24h 且 exit!=0 = 旧问题(任务超1天没跑)，等下次任务跑更新
#    stats 自动清除，降级 log INFO 不重复 SEVERE；最近 24h 内 exit!=0 首次发SEVERE+suppress(不重发)。
# 2026-07-25: 跑前刷新 schedule_stats.json(保证读最新,不读滞后旧值)。
# 根因:schedule_monitor 每15min跑,但 schedule_stats.json 只在各任务脚本结尾刷新,
# 若任务没跑(如周末),json 滞后旧值(如 etf 143 假告警),schedule_monitor 持续读旧值误告警。
# 跑前调 gen_schedule_stats.py 重生成(读最新 launchd.log),保证读到当前真实状态。
try:
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_schedule_stats.py")],
        capture_output=True, text=True, timeout=60,
    )
except Exception as e:
    print(f"[warn] gen_schedule_stats 刷新失败(读旧 schedule_stats.json): {e}", file=sys.stderr)

STALE_EXIT_THRESHOLD = timedelta(hours=24)

# #162(2026-10-05, 云上健康巡检 D2 P1-b): "进行中"判定的陈旧起点上限。
# 背景: last_duration_sec 为 null 有二义性 —— ① 任务真在跑(有 start 无 end, gen 写 null);
#   ② 最新一次运行的"结束"行没写出(被 systemd TimeoutStartSec 杀 / 漏写),使该 start 永远
#   无配对 → gen_schedule_stats 取 pending_start=它 → last_duration_sec=null,但任务其实早已结束。
# 实例(s06 09-28~09-30): s06_snapshot.sh 三次跑到 R2 段被 systemd 600s 杀在内层 run_to 900s
#   无梯度,日志只留"开始"无"结束",pending=09-30 距今数天;而 last_exit=0(取最近一次 systemd
#   退出码,含 10-02 节假日跳过那次)。monitor 旧判据 `dur is None and last_exit in (None,0)` 把
#   它当"在跑" → in_progress_tasks → 恢复循环永久 hold 住 09-28 的 `s06_snapshot|exit!=0|143`
#   老告警,与"任务已恢复成功(机检六项全 PASS)"的真实状态自相矛盾(D2 P1-b 报告的"残留 hold")。
# 判据: 仅当最新 start 距今 <= IN_PROGRESS_MAX_AGE 才视为"在跑"。
# 取值 6h 依据(两条都要满足):
#   ① 必须显著大于"合法运行"的最长耗时,否则真在跑的任务被踢出 in_progress -> A1 停止检查
#      且其 in_progress_timeout 告警会被误判"已恢复"。实测最长合法运行 = update_all
#      DUR_THRESHOLDS 8100s(2.25h) + IN_PROGRESS_BUFFER 30min = 2.75h;取 2x 余量
#      (memory selftest-window-two-x-period: 窗口须 >= 机制周期 2 倍) -> 5.5h -> 取 6h。
#      ⚠️ 3h 曾考虑(对齐 gen MAX_GAP_SEC)但会踩坑: A1 在 sch+2.75h 才首报,3h 时任务
#         恰好刚出窗口 -> 报完 15min 就"已恢复"(假恢复),故不可取。
#   ② 必须有限(旧代码无上限)才能让"被杀的陈旧起点"自愈: s06 那次 5 天,6h 上限使它在
#      上线后的第一次巡检即退出 in_progress,09-28 老告警如实恢复(D2 P1-b 的正解)。
# 残余(如实登记, 见汇报): 真"卡死">6h 的任务会掉出集合 -> 其 in_progress_timeout 会被
#   报"已恢复"。可接受: A1 早在 2.75h 已 SEVERE 报过(人工已介入),且次日该任务未完成
#   会被"漏跑"检查再报;>6h 未完成属需人工介入的事故态,不再符合"在跑"语义。
IN_PROGRESS_MAX_AGE = timedelta(hours=6)


def _in_progress_state(_s, _now):
    """#162: 单条 stats 的"进行中"判定 -> "running" / "stale" / "no"。

    dur=null(有 start 无 end, gen 写 null)有二义性: "running"=真在跑; "stale"=最新 run
    无结束行的陈旧起点(被 systemd 杀/漏写结束行 -> gen 取它当 pending_start -> 永远 dur=null,
    任务实际早已结束)。"no"=不适用(已完成/非受监控任务/已失败/last_run 不可解析)。
    判据与取值依据(6h)见上方 IN_PROGRESS_MAX_AGE 注释。
    纯函数(只读入参 + 模块常量), 与 scripts/tests/test_monitor_resource_inprogress_20261005.py
    共用同一份实现(防"测试里另写一份判定"的静默漂移)。
    """
    if _s.get("last_duration_sec") is not None:
        return "no"
    if _s.get("task") not in DUR_THRESHOLDS:
        return "no"
    if _s.get("last_exit") not in (None, 0):
        return "no"
    _lr = _s.get("last_run") or ""
    if not _lr:
        return "no"
    try:
        _age = _now - datetime.strptime(_lr, "%Y-%m-%d %H:%M")
    except ValueError:
        return "no"
    return "running" if _age <= IN_PROGRESS_MAX_AGE else "stale"

# 2026-08-24 瞬时超时降噪: 瞬时/降级类 log 异常按"连续>=3轮未自愈才 SEVERE"处理
# (单次/两次视为瞬时抖动,只记 dashboard 不通知)。教训=intraday_snapshot R2 PUT
# 超时连续 11 次全部自愈,每轮都发 SEVERE 邮件=假警报轰炸。
# 2026-09-24 硬化(用户拍板"自愈识别"方案): 缓冲**不再依赖任务名单**——TRANSIENT_TIMEOUT_TASKS/
# EXTRA_DEGRADE_TASKS 已删(名单硬编码=新任务/新形态漏名单即首报, 且普通路径的 ⚠ 瞬态行
# 需要同样降噪)。现在统一按 gen_schedule_stats 输出的 log_anomaly_severity 语义判断:
#   severity=degrade(⚠ 瞬态/设计内降级/未定论)→ 入桶连续 N 轮才 SEVERE
#   severity=critical 或 None(真失败/非瞬态)→ 首报 SEVERE(真异常不该拖)
# severity 来源: EXTRA 路径(scan_marker_log, fetch_news/gen_daily_brief ⚠ 降级 vs ✗ 关键)
#   + 普通路径(Fix C, ⚠ 瞬态行任务在跑无对应成功行=degrade / 任务结束 exit!=0=critical)。
TRANSIENT_TIMEOUT_THRESHOLD = 3
# P2(2026-09-24 r2 终审): EXTRA 任务停摆(部署外生成器整个不跑)漏跑检查阈值。
# fetch_news/gen_daily_brief 不在 MISSED_TASKS 漏跑检查(TASKS 表无对应条目), 若其
#   生成器/systemd timer 被删/崩, 将无声无息。本 dict 定义"多久未运行=停摆发 SEVERE":
#   fetch_news: 计划 30min 一轮(7:30-21:00), 停摆 4h≈错过 ~8 轮, 余量充足防误报
#   gen_daily_brief: 每日 20:40 一轮, 停摆 26h(昨日没跑也一样覆盖次日 22 点前)不误报
EXTRA_MARKER_STALE_LOOPS = {
    "fetch_news": timedelta(hours=4),
    "gen_daily_brief": timedelta(hours=26),
}
# #228 M1(2026-10-07): EXTRA 任务「轮次完整性」通道 —— 判「本轮开始了没跑完」。
# 背景: gen_daily_brief / fetch_news 被 systemd TimeoutStartSec 硬杀时, 既有五通道全被
#   结构性豁免(漏跑不在 TASKS / last_exit=None 不算失败 / 耗时不在阈 / 停摆被 mtime 刷新),
#   被砍轮恒报「OK 无漏跑」(报告 docs/ops/228-monitor-blindspot-20261007.md §1.2/1.3 实证)。
#   本通道补「unit 被杀/FAIL」判别轴(只新增, 不改/不豁免任何既有通道, §23.7)。
# 判别三元素(全部满足才报):
#   ① round_state == 'started_unfinished'(纯日志: 最后一轮有开始标记、无完成/失败标记)
#   ② unit 非运行态(ActiveState ∉ {active,activating,reloading}; 读不到 → 退化为纯 age)
#   ③ 开始标记距今: unit 状态可读 → > ROUND_INCOMPLETE_GRACE; 不可读 → > EXTRA_ROUND_INCOMPLETE
# 阈值口径: EXTRA_ROUND_INCOMPLETE 须 **大于对应 unit 现 TimeoutStartSec**(否则正常慢跑
#   被杀前就误报)且 **远小于停摆阈值**(留语义边界)。云上 2026-10-07 实测: daily-brief
#   TimeoutStartUSec=29min、fetch-news=18min ⇒ 取 45min / 30min(均为 1.5~1.7x 墙钟)。
#   ROUND_INCOMPLETE_GRACE=10min 覆盖正常短跑(fetch_news 常态 24s)+ 探测迟到。
EXTRA_ROUND_INCOMPLETE = {
    "gen_daily_brief": timedelta(minutes=45),
    "fetch_news": timedelta(minutes=30),
}
ROUND_INCOMPLETE_GRACE = timedelta(minutes=10)

# 执行耗时阈值(R2迁移72h监控 2026-08-08): 移到循环外避免每次迭代重建(L2)
# 2026-08-14 修复(reviewer FAIL, A1 误报正常日): 依据 update_all_launchd.log 近9交易日实际耗时
#   (38/38/49/53/54/59/21/53/60 min, max=3609s=8-14, P90=3556s)重标。阈值必须 > 实测 max,
#   否则完成态检查(3609>3600)会复发假SEVERE(8-14 正常完成 exit=0 却曾报 dur>1800s)。
#   update_all 4200s(70min, max 3609s + ~10min 裕量); backfill_evening 4500s(75min,
#   覆盖 16:35 槽 max 2776s + 21:00 槽 08-10 达 3707s)。
#   [2026-09-09 #84 C2 联动标注] update_all 实测已涨到 135~175min(2026-09-08 dur=10271s≈171min,
#   近 10 次 P90≈11000s), 4200s 阈值失真导致每天 2-3 封「执行耗时超标」SEVERE。此处**不抬阈值**
#   (抬了会掩埋 update_all 主链变慢的退化信号)。治本 = #82 C6(turnover 摘出 update_all 主链,
#   175→~85min, 待用户拍板): C6 落地后 update_all 主链耗时回落, 届时按新实测 max 重标本阈值
#   (原则同 L316: 阈值必须 > 新实测 max, 防完成态检查复发假 SEVERE); C6 未落地前保持现状,
#   让「执行耗时超标」继续暴露主链退化(硬信号)而不是被阈值吞掉。
# P1-1(2026-09-24, r2-false-success-rootfix): r2_skip_count 连续 skip 告警阈值。
# SKIPPED_LOCKED 单次 = 设计让路(锁忙下轮重试), 不告警; 但连续 R2_SKIP_CONTINUOUS_THRESHOLD
# 轮 monitor(15min/轮)仍 skip = 上传缺口持续(收盘版/每日版可能一直未上 R2), 才升级 SEVERE。
# monitor 每 15min 轮询, 阈值 3 ≈ intraday(10min/轮)连续 ~4-5 轮 skip(≥45min 上传锁被占)。
R2_SKIP_CONTINUOUS_THRESHOLD = 3
# P1-3(2026-09-24 r2skip-alert-fix): r2_skip_count 的「本轮观察窗口」。r2_skip_count 是
# 任务最近一次运行窗口内 SKIPPED_LOCKED 行数——对每日一轮任务(overfit_monitor 21:40 单轮),
# 一次良性撞锁后该值滞留恒=1 直到次日新一轮。monitor 消费时仅当 last_run 落在本窗口内
# (= 本轮有新运行, 该 skip 是「本轮新发生」)才参与「连续 N 轮」计数; 窗口外(本轮无新运行)
# = 滞留值, 不参与连续计数【#181(2026-10-07)起保留连续链不清零: 旧「滞留即清零」会造成
# 「stale 清零 → 下一 tick 假恢复 → 1h 后重报」结构性循环; 现唯一清零点 = 本轮无 skip 分支】。
# 窗口 30min: monitor 15min/轮, 高频任务(intraday 10min 轮 /
# fetch_news 30min 轮)每轮/隔轮必有新运行, last_run 恒在窗口内 -> 连续 N 轮 SEVERE 行为一条
# 不改; 每日一轮任务 ~2 轮后即出窗口 -> 单次 skip 最大计数 2 < 阈值 3, 跨轮累积误报根治。
R2_SKIP_OBS_WINDOW = timedelta(minutes=30)
# P3(2026-09-29 告警降噪 改动1/2): 连续轮阈值。
#   R2_LAG_CONTINUOUS_THRESHOLD=3: R2 intraday_snapshot 时效滞后单次多为上传间隙瞬时
#     (09-28 13:45/14:15 各 1 封=检查落在上传间隙), 连续 3 轮(≈45min, 15min/轮)仍滞后
#     才 SEVERE; 真断供(前端分时读旧)不会被吞。参照 marker_buffer 计数语义。
#   MISSED_CONTINUOUS_THRESHOLD=2: 单轮漏跑多为瞬时(15:35 轮自动补跑 exit=0), 连续 2 轮
#     (30min, 15min频率×2)仍无运行才 SEVERE; TOLERANCE=30min 窗口内一个 sch 最多被检查 2 轮。
R2_LAG_CONTINUOUS_THRESHOLD = 3
MISSED_CONTINUOUS_THRESHOLD = 2
# #240 ③(2026-10-09) 执行耗时「单轮碰线」降噪(只降噪不降灵敏度, memory
#   alert-denoise-keep-fault-discriminator): 病灶(docs/ops/alert-triage-1008-20261008.md R7)——
#   intraday 10-08 15:02 轮 928s vs 阈值 900s(**仅超 3%**)被判 SEVERE + 15min 后 [恢复],
#   一轮碰线 = 2 封噪音。实测分布(云上 intraday_snapshot_launchd.log 全配对 400 run):
#   盘中 387 run p95=796s / p99=935s / max=1398s(全部 exit=0 正常完成)⇒ 900s 附近是正常
#   波动尾, 单轮碰线不是故障。口径:
#     ① dur >= DUR_IMMEDIATE_MULTIPLE × 阈值(盘中 1800s / 盘后 3600s) = 单次极端超阈
#        (卡死/严重退化量级) → 立即 SEVERE, 不等连续轮。
#     ② 否则需连续 DUR_CONTINUOUS_THRESHOLD 轮(15min/轮)观测到超阈才 SEVERE(pending→active)。
#     ⇒ 真退化照报: 极端单次立即报; 持续多轮报(如 09-30 盘后 2081s, 单 run/日但被其后
#       多个 tick 连续看到 → 连续计数天然可达)。盘中卡死未完成另有 A1 通道(阈值900s+缓冲10min)。
#   ⚠️ 复审 F2(2026-10-09, reviewer 结构性盲区根治): 「连续轮」口径有结构漏洞——
#     dur=None 轮(最新 run 仍在进行中)进不了 dur 块、不登记 seen, 主恢复循环遂把 pending 桶
#     静默翻 recovered、计数从头再来; 配合节拍数学(tick 15min, intraday 槽 10min), 两连观测
#     的真实窗口条件退化为「run 时长 D < 15min, 且下一 tick 恰好没有新 run 在进行中」。
#     阈值恰=900s=15min ⇒ 盘中 D∈[900,1800) 的 run 结构性凑不出「连续 2 轮」而**完全静默**
#     (旧行为会报)。两处根治: ①恢复循环豁免 `|dur_buffer|` 键(桶复位只由 dur 块内联负责)
#     ②桶记 last_run(区分「同一 run 被后续 tick 重复观测」与「另一 run 也超阈」, 供日志/排查;
#     计数仍是「观测轮次」—— 对 1 run/日 的盘后槽, 同一 run 被后续 tick 重复观测正是其累积
#     途径, 故不能按 run 去重)。桶含陈旧保护: 上次观测 >DUR_BUFFER_MAX_AGE 视为新建, 防停跑
#     任务的陈年计数让单轮碰线假达阈。
#     ⚠️ 残余(诚实标注): 同一超阈 run 若被连续两轮观测且中间没有新 run 介入(如午休/收盘后槽),
#     会被计为 2 → SEVERE。这是「1 run/日 槽仍要能报」的必要代价, 且旧行为本就报该情形。
DUR_CONTINUOUS_THRESHOLD = 2
DUR_IMMEDIATE_MULTIPLE = 2
DUR_BUFFER_MAX_AGE = timedelta(hours=24)
DUR_THRESHOLDS = {
    "intraday_snapshot": 900,   # 15min(2026-09-29 告警降噪 改动3: 600->900, 正常286s 3倍裕量;
                                #   盘后>=20:00槽已在 L645-651 分档放宽到 1800s 覆盖, 勿动)
    # 2026-09-09 #82 C6 重标: turnover 已摘出主链(独立任务 com.trade.turnover-backfill 21:10),
    # update_all 主链 = width(实测 36min) + 后续串行(export_fund_nav→deploy→…→daily_summary,
    # 实测 76-85min) ≈ 112-121min。阈值 8100s(135min) = 实测 max + ~14min 裕量,
    # 防 121min 正常完成 > 4200s 旧阈值复发假 SEVERE(2026-08-14 同病)。turnover 自身耗时
    # 由新任务 turnover_backfill 独立监控(schedule_monitor TASKS 已收录)。原 4200s 废弃。
    "update_all": 8100,         # 135min(摘出 turnover 后主链实测 112-121min + 裕量, 2026-09-09)
    "backfill_evening": 4500,   # 75min(实测 max ~3707s 21:00槽 08-10)
    "us_stock_morning": 1800,   # 30min(任务本身秒级,慢在全量 deploy 17-26min 恒超 900s;2026-08-18 900->1800)
    "overfit_monitor": 900,     # 15min(实测打点+双 parity 自检 76s, 2026-08-25; 大裕量防 trades 重算抖动)
    "s06_snapshot": 900,        # 15min(串行 run_to: gen300+check300+R2上传900+posrating300×2+快照上传900; 正常秒级, 裕量防 R2 上传重试; codex008 F5)
    "nextday_plan": 900,        # 15min(生成器读4产物+K=1重算+写两树+R2上传(300s超时)+通知(120s超时), 实测秒级; 裕量防 R2 重试)
    "nextday_gap_check": 900,   # 15min(就绪闸+300s重试+R2上传+通知, 最坏 ~600s; 裕量防 akshare 网络抖动重试)
}
# stats 初始化(2026-08-14 A1 补): A1 进行中检测块引用 stats, 须保证 STATS_FILE 不存在/
#   解析失败时 stats 仍为 [] 而非 NameError(否则进行中检测整块崩溃)。
stats = []
if STATS_FILE.exists():
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            stats = json.load(f)
        for s in stats:
            exit_code = s.get("last_exit")
            # null=进行中/无数据不算失败；非0=退出失败
            if exit_code is not None and exit_code != 0:
                last_run_str = s.get("last_run") or ""
                is_stale = False
                if last_run_str:
                    try:
                        # last_run 格式 "2026-07-24 20:05"（无秒，gen_schedule_stats 写入）
                        last_run_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M")
                        age = NOW - last_run_dt
                        if age > STALE_EXIT_THRESHOLD:
                            is_stale = True
                    except ValueError:
                        print(f"[warn] {s.get('task')} last_run 格式异常: {last_run_str}", file=sys.stderr)
                # 去重 key: task|exit!=0|exit_code (与 log异常关键词路径结构对称)
                # 标记本次仍存在(防误报恢复),无论 stale 与否(与 log关键词路径 L250-251 同逻辑)
                dedup_key = f"{s['task']}|exit!=0|{exit_code}"
                seen_keys_this_run.add(dedup_key)
                if is_stale:
                    # 旧告警已过期(任务>24h没跑)，等下次任务跑更新 stats 自动清除，不重复 SEVERE
                    # state 保持 active(stale 不触发误恢复),等任务真正跑 exit=0/null 才恢复
                    print(
                        f"[info] {s['task']} 退出失败 last_exit={exit_code} "
                        f"last_run={last_run_str} 距今>{int(STALE_EXIT_THRESHOLD.total_seconds()//3600)}h, "
                        f"旧告警已过期,等下次任务跑更新(不重复 SEVERE)"
                    )
                # #123 R3(2026-10-01): nextday_plan 自身通道(nextday_plan.sh L68-76, dedup-key
                # nextday_plan_fail)已发详细告警; 若产物 data/nextday_plan.json 今日已落盘
                # (=计划实际已生成, 失败面多为 R2 上传/通知段), monitor exit!=0 汇总通道不再
                # 双发。产物未生成=真失败 → 双保险双响(反例 B 保证)。判定函数
                # scripts/alert_denoise_rules.py:r3_nextday_product_generated_today。
                elif s.get("task") == "nextday_plan" and adr.r3_nextday_product_generated_today(
                    REPO, NOW.strftime("%Y-%m-%d")
                ):
                    _ex_nd = alert_state.get(dedup_key)
                    if _ex_nd is not None and _ex_nd.get("status") == "active":
                        _ex_nd["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[r3-nextday-suppress] nextday_plan exit={exit_code} 但产物今日已生成, "
                        f"自身通道已发详细告警, monitor 汇总去重"
                    )
                # #160 收口 R7②(2026-10-05): r2_consistency 包装器自身通道
                # (check_r2_consistency.sh → notify --dedup-key r2_consistency_fail, 含问题
                # 明细)已为**本次运行实例**发过告警时, 本 exit!=0 汇总通道不再复述(同一 FAIL
                # 走两通道 = 两封邮件)。判据 = notify_dedup.json 的 last_alerted >= 本次
                # last_run。反例保证(不吞真故障): 包装器告警发送失败/脚本在 notify 前被杀/
                # 去重状态缺失 → 判定 False → 本通道照发(双保险)。判定函数
                # scripts/alert_denoise_rules.py:r7_r2_consistency_wrapper_alerted。
                elif s.get("task") == "r2_consistency" and adr.r7_r2_consistency_wrapper_alerted(
                    REPO, last_run_str
                ):
                    _ex_r2c = alert_state.get(dedup_key)
                    if _ex_r2c is not None and _ex_r2c.get("status") == "active":
                        _ex_r2c["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[r7-r2consistency-suppress] r2_consistency exit={exit_code} 但包装器"
                        f"通道已为本次运行(last_run={last_run_str})发过告警, monitor 汇总去重"
                    )
                # #196②(2026-10-05): cloud_unit_patrol 漂移时包装器自身通道
                # (cloud_unit_patrol.sh → notify --dedup-key cloud_unit_patrol_drift, 含差异明细)
                # 已为**本次运行实例**发过告警时, 本 exit!=0 汇总通道不再复述(同 r2_consistency
                # 先例; 否则同一次漂移 = 包装器邮件 + 本通道邮件 + check_failed_units failed-unit
                # 邮件 三封)。反例保证(不吞真故障): 包装器 notify 发送失败/去重表缺失 → 判定
                # False → 本通道照发。注意 patrol 的 exit 3(环境守卫 SKIP)**不 notify** ⇒
                # 判定 False ⇒ 本通道照报(正是 #191 P2-1 要的「exit 3 生产可见」)。
                elif s.get("task") == "cloud_unit_patrol" and adr.wrapper_channel_alerted(
                    REPO, last_run_str, adr.PATROL_DRIFT_DEDUP_KEY
                ):
                    _ex_cup = alert_state.get(dedup_key)
                    if _ex_cup is not None and _ex_cup.get("status") == "active":
                        _ex_cup["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[196-patrol-suppress] cloud_unit_patrol exit={exit_code} 但包装器"
                        f"通道已为本次运行(last_run={last_run_str})发过告警, monitor 汇总去重"
                    )
                else:
                    existing = alert_state.get(dedup_key)
                    if _recurrence_suppressed(existing):
                        # P1(2026-09-24 告警降噪): recovered 后 6h 内复现=同一事件振荡,
                        # 抑制 SEVERE(9-18 一天 13 封根因: 15min 轮询每轮复现当新异常直发)。
                        # 状态翻 active 保持, 防持续复现时每轮重复进本分支仍被抑制。
                        existing["status"] = "active"
                        existing["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[recurrence-suppress] {s['task']} 退出失败(exit={exit_code}) "
                            f"恢复后<6h复现, 抑制不重发"
                        )
                    elif existing is None or existing.get("status") != "active":
                        # 首次发现 或 超过抑制窗口后复现 = 发 SEVERE + 写 state
                        alerts.append(
                            f"SEVERE: {s['task']} 退出失败 last_exit={exit_code} "
                            f"last_run={last_run_str}"
                        )
                        alert_state[dedup_key] = {
                            "status": "active",
                            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": f"exit={exit_code}",
                            "line_sample": f"last_run={last_run_str}",
                        }
                    else:
                        # 已 active = 抑制不重发,只 log
                        print(
                            f"[suppress] {s['task']} 退出失败(exit={exit_code}) 持续中, "
                            f"last_alerted={existing.get('last_alerted')}, 不重发"
                        )
            # 第4盲区修复: log 异常关键词检查(脚本吞异常 exit=0 漏报)
            # 即使 last_exit=0(异常被 try/except 吞),log 里有 Traceback/异常类名也算失败
            # 复用 24h stale 去重(与 exit!=0 同逻辑, 旧告警不重复 SEVERE)
            if s.get("log_anomaly"):
                keyword = s.get("log_anomaly_keyword") or "?"
                line = (s.get("log_anomaly_line") or "")[:120]
                line_sample = line[:80]
                # 去重 key: task|keyword|line前80字符md5前8位
                dedup_key = (
                    f"{s['task']}|{keyword}|"
                    f"{hashlib.md5(line_sample.encode('utf-8', errors='replace')).hexdigest()[:8]}"
                )
                # 标记本次仍存在(防误报恢复),无论 stale 与否
                seen_keys_this_run.add(dedup_key)
                last_run_str_a = s.get("last_run") or ""
                is_stale_a = False
                if last_run_str_a:
                    try:
                        last_run_dt_a = datetime.strptime(last_run_str_a, "%Y-%m-%d %H:%M")
                        if NOW - last_run_dt_a > STALE_EXIT_THRESHOLD:
                            is_stale_a = True
                    except ValueError:
                        pass
                if is_stale_a:
                    # 24h stale 兜底(state 丢失时仍不轰炸)
                    print(
                        f"[info] {s['task']} log异常 keyword={keyword} "
                        f"last_run={last_run_str_a} 距今>"
                        f"{int(STALE_EXIT_THRESHOLD.total_seconds()//3600)}h, "
                        f"旧告警已过期,等下次任务跑更新(不重复 SEVERE)"
                    )
                else:
                    existing = alert_state.get(dedup_key)
                    if _recurrence_suppressed(existing):
                        # P1(2026-09-24 告警降噪): recovered 后 6h 内复现=同一事件振荡
                        # (瞬时 log 异常每轮复现被当"新异常"), 抑制 SEVERE。
                        # 状态翻 active 保持, 防持续复现每轮重复进本分支仍被抑制。
                        existing["status"] = "active"
                        existing["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[recurrence-suppress] {s['task']} {keyword} 恢复后<6h复现, 抑制不重发"
                        )
                    elif existing is None or existing.get("status") != "active":
                        # 2026-08-24 瞬时超时降噪(教训: intraday_snapshot R2 PUT 超时
                        # 连续 11 次全部自愈,每次都 SEVERE 邮件=假警报轰炸)。
                        # 瞬时/降级类标记先入稳定桶计数(line md5 每次不同,不能按
                        # dedup_key 计数),连续>=3 次跨轮仍异常才升级 SEVERE;未达阈值
                        # 只记 dashboard 不通知(warning 语义)。
                        # 2026-09-24 硬化(用户拍板"自愈识别"方案): 缓冲条件去掉任务名单
                        # (TRANSIENT_TIMEOUT_TASKS/EXTRA_DEGRADE_TASKS 已删), 改纯 severity
                        # 语义判断——gen_schedule_stats 已把「⚠ 瞬态/设计内降级/未定论」
                        # 标 severity=degrade(普通路径 Fix C 的 ⚠ 瞬态行任务在跑、EXTRA 的
                        # fetch_news/gen_daily_brief ⚠ 降级标记), 真失败/非瞬态标 critical
                        # 或 None → 走下方 else 首报(真异常不该拖, 零延迟)。
                        if s.get("log_anomaly_severity") == "degrade":
                            _bk = f"{s.get('task')}|marker_buffer"
                            _b = alert_state.get(_bk) or {}
                            _bs = _b.get("status")
                            if _bs == "pending":
                                _c = (_b.get("consecutive_count") or 0) + 1
                            elif _bs == "alerted":
                                # 已就同类告警过但行内容变了=持续异常换脸,直接升级可见
                                _c = TRANSIENT_TIMEOUT_THRESHOLD
                            else:
                                _c = 1
                            alert_state[_bk] = {
                                "status": "alerted" if _c >= TRANSIENT_TIMEOUT_THRESHOLD else "pending",
                                "first_seen": _b.get("first_seen") or NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "consecutive_count": _c,
                                "keyword": "marker_buffer",
                                "line_sample": line_sample,
                            }
                            # #232(2026-10-07): 计数桶补 mark seen —— 防主恢复循环(L1676-1684)对
                            # 「pending 且未 seen 且非 r2_/72h_ 前缀」的桶键每 tick 误翻 recovered
                            # (否则下 tick L768 else 分支把 count 重置恒 1, SEVERE 结构性不可达=零报)。
                            # 与 r2_intraday_lag 计数桶/missed L381/dedup_key L718 同款既有写法。
                            # 只在 degrade tick 标记 ⇒ 链断(无 degrade)时不再 seen, 恢复循环/inline
                            # 照常清链、下轮从 1 起(防抖语义保持)。语义=按 tick 的「连续>=3轮(≈45min)
                            # 未定论」哨, 阈值与 r2_lag 同族, 不动常量。
                            seen_keys_this_run.add(_bk)
                            if _c < TRANSIENT_TIMEOUT_THRESHOLD:
                                print(
                                    f"[marker_buffer] {s.get('task')} {keyword} 连续{_c}/"
                                    f"{TRANSIENT_TIMEOUT_THRESHOLD} 轮未自愈,暂不通知"
                                    f"(降级/瞬时标记连续>=3轮才SEVERE)"
                                )
                            else:
                                alerts.append(
                                    f"SEVERE: {s['task']} log异常关键词<{keyword}> "
                                    f"exit={exit_code} 已连续{_c}轮未自愈(阈值"
                                    f"{TRANSIENT_TIMEOUT_THRESHOLD}) "
                                    f"last_run={last_run_str_a} 行: {line}"
                                )
                                alert_state[dedup_key] = {
                                    "status": "active",
                                    "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                    "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                    "keyword": keyword,
                                    "line_sample": line_sample,
                                }
                        else:
                            # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                            alerts.append(
                                f"SEVERE: {s['task']} log异常关键词<{keyword}> "
                                f"exit={exit_code}(可能被try/except吞) "
                                f"last_run={last_run_str_a} 行: {line}"
                            )
                            alert_state[dedup_key] = {
                                "status": "active",
                                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "keyword": keyword,
                                "line_sample": line_sample,
                            }
                    else:
                        # 已 active = 抑制不重发,只 log
                        print(
                            f"[suppress] {s['task']} {keyword} 异常持续中, "
                            f"last_alerted={existing.get('last_alerted')}, 不重发"
                        )
            # 2026-08-24 瞬时超时桶自愈重置: 本轮该任务无 log 异常=抖动已过去,
            # 桶翻 recovered 静默(不发恢复邮件); 若已达阈值发过 SEVERE, 原告警 key
            # 的恢复通知仍由主恢复循环负责(桶只管计数,不管通知生命周期)。
            # 2026-09-24 硬化: 恢复检测同样去掉名单限制(桶 key 统一 |marker_buffer,
            # 任何任务本轮无 log 异常即视为抖动自愈, 连续计数重置)。
            if not s.get("log_anomaly"):
                _bk_r = f"{s.get('task')}|marker_buffer"
                _b_r = alert_state.get(_bk_r)
                if _b_r and _b_r.get("status") in ("pending", "alerted"):
                    alert_state[_bk_r] = {
                        **_b_r,
                        "status": "recovered",
                        # #232(2026-10-07): 复位时显式清 count(状态洁净; 与 r2_intraday_lag
                        # L2205-2211 / overview judge L250-253 同款)。即使不清, 下轮 degrade 读
                        # status=recovered 走 L768 else 分支也会重置为 1 —— 此处清=复位语义显式化。
                        "consecutive_count": 0,
                        "recovered_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "recovery_reason": "marker_buffer_self_healed",
                    }
                    print(f"[marker_buffer] {s.get('task')} 标记/超时抖动已自愈(连续计数重置)")
            # 维度③: 执行耗时阈值检查（R2迁移72h监控 2026-08-08）
            # schedule_stats.json 的 last_duration_sec 字段,超阈值告警(进程退化/卡死信号)。
            # intraday ~7min正常 >600s(10min)告警(重叠下一10min槽=下轮读旧数据);
            # update_all 正常 max~60min(实测3609s) >4200s(70min)告警; backfill 正常 max~62min
            #   (21:00槽08-10 3707s) >4500s(75min)告警; (2026-08-14 依实测重标)
            # us_stock_morning 任务本身秒级,但全量 deploy(17-26min)恒超 900s;2026-08-18 阈值 900->1800(30min)。
            # 只检查最近 24h 内完成的任务(stale 不重复告警,同 exit/log_anomaly 逻辑)。
            # 恢复检测: dur 降回阈值内 -> key 未 seen -> L476 恢复循环自动发恢复邮件。
            _dur = s.get("last_duration_sec")
            _dur_task = s.get("task")
            # 2026-08-14 告警优化 A1: 进行中任务收集到 in_progress_tasks。
            # 判定抽为纯函数 _in_progress_state(见常量区注释): "running" 才收集;
            #   "stale"(最新 run 无结束行的陈旧起点, #162) 不算 —— 否则其历史告警被永久
            #   hold(第 ② 用途)且 A1 也无意义(last_run 早已过时)。
            #   ⚠️ 保留"排除 exit!=0"(失败/被杀, 已由退出检查告警, 防重复)。
            # 用途: ①进行中超时检测(A1新增块) ②恢复检测循环跳过该任务的 key
            #   (防 8-14 误恢复: update_all 卡死 dur=null, 未 seen -> 误判"已消失")。
            _ip_state = _in_progress_state(s, NOW)
            if _ip_state == "running":
                in_progress_tasks.add(_dur_task)
            elif _ip_state == "stale":
                print(
                    f"[in-progress-stale] {_dur_task} dur=null 但 last_run={s.get('last_run')} 距今 > "
                    f"{int(IN_PROGRESS_MAX_AGE.total_seconds() // 3600)}h"
                    f"(无结束行的陈旧起点, 任务实际已结束), 不判进行中(不 hold 其历史告警)"
                )
            if _dur is not None and _dur_task in DUR_THRESHOLDS:
                _dur_thresh = DUR_THRESHOLDS[_dur_task]
                # P1-3(2026-09-24, r2-false-success-rootfix): intraday 盘后槽阈值分档。
                # 600s 按盘中(09:35-15:35)时效设计; 盘后 20:35 槽混入 dump+R2 上传
                # (实测 8/12 661s、8/13 2493s, alert-system-evaluation.md L120/L172 P0-2
                # 建议)且 P2-1 收盘轮排队最坏 ~7300s, 600s 必爆「执行耗时超标」SEVERE 噪音。
                # 按 last_run 的 HH:MM 分档: >=20:00 盘后槽放宽到 1800s; 盘中槽保持 600s 严格
                # (时效敏感, 超时即重叠下一 10min 槽读旧数据)。只动 intraday, 其余任务不受影响。
                # 【P2② 实测复核(2026-09-24, 云上 intraday_snapshot_launchd.log 9/14-9/23 全配对)】:
                #   intraday_snapshot 无 16:00/17:50 槽(plist 仅盘中10min档+15:35+20:35, TASKS 表
                #   同源; 17:50 是 update_all 独立任务)。15:35 槽近8交易日 max=418s 恒<600s 无需
                #   放宽; 20:35 槽近8交易日 max=965s(9/15), >=20:00 放宽到 1800s 已覆盖、无超档。
                #   结论: 无需给 16:00/17:50 加 dur 分档(槽点不存在), 现状分档正确。
                if _dur_task == "intraday_snapshot":
                    _dur_lr_slot = s.get("last_run") or ""
                    try:
                        if datetime.strptime(_dur_lr_slot, "%Y-%m-%d %H:%M").strftime("%H:%M") >= "20:00":
                            _dur_thresh = 1800
                    except (ValueError, TypeError):
                        pass
                if _dur > _dur_thresh:
                    _dur_lr = s.get("last_run") or ""
                    _dur_stale = False
                    if _dur_lr:
                        try:
                            _dur_lr_dt = datetime.strptime(_dur_lr, "%Y-%m-%d %H:%M")
                            if NOW - _dur_lr_dt > STALE_EXIT_THRESHOLD:
                                _dur_stale = True
                        except ValueError:
                            pass
                    if not _dur_stale:
                        _dur_key = f"{_dur_task}|dur>{_dur_thresh}s"
                        seen_keys_this_run.add(_dur_key)
                        _ex_dur = alert_state.get(_dur_key)
                        # #240 ③(2026-10-09) 单轮碰线降噪: 计数桶 pending→active(镜像 marker_buffer
                        # 模式)。桶键带阈值维度(dur_buffer|{阈值})防盘中槽(900)与盘后槽(1800)计数串用
                        # ——否则「盘后已 alerted」的桶会让次日盘中首轮碰线直接达阈(假 SEVERE)。
                        _dur_cnt_key = f"{_dur_task}{adr.DUR_BUFFER_KEY_MARK}{_dur_thresh}"
                        seen_keys_this_run.add(_dur_cnt_key)  # 防主恢复循环对 pending 桶静默翻 recovered
                        _dur_b = alert_state.get(_dur_cnt_key) or {}
                        _dur_bs = _dur_b.get("status")
                        # 复审 F2: 陈旧桶保护 —— 上次观测 >24h(任务已停跑, 桶不再被复位)按新建处理,
                        # 防陈年 consecutive_count 让一个单轮碰线假达阈(见文件头 F2 注)
                        _dur_last_seen = _dur_b.get("last_seen")
                        if _dur_last_seen:
                            try:
                                _dur_stale_b = (NOW - datetime.strptime(
                                    _dur_last_seen, "%Y-%m-%d %H:%M:%S") > DUR_BUFFER_MAX_AGE)
                            except (ValueError, TypeError):
                                _dur_stale_b = True
                            if _dur_stale_b:
                                _dur_b, _dur_bs = {}, None
                        _dur_prev_c = _dur_b.get("consecutive_count") or 0
                        if _dur >= _dur_thresh * DUR_IMMEDIATE_MULTIPLE:
                            _dur_c = DUR_CONTINUOUS_THRESHOLD  # 单次极端超阈: 视同已达连续阈值, 立即报
                        elif _dur_bs in ("pending", "alerted") and _dur_prev_c >= 1:
                            # 上一轮(15min 前)已观测到超阈且未被复位(dur=None 轮不复位, 见恢复环豁免)
                            # → 计数 +1。对「1 run/日」的槽(如盘后 20:35)这是唯一能累积的途径。
                            _dur_c = _dur_prev_c + 1
                        else:
                            _dur_c = 1
                        alert_state[_dur_cnt_key] = {
                            "status": "alerted" if _dur_c >= DUR_CONTINUOUS_THRESHOLD else "pending",
                            "first_seen": _dur_b.get("first_seen") or NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "consecutive_count": _dur_c,
                            "last_run": _dur_lr,
                            "last_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": "dur_buffer",
                            "line_sample": f"dur={_dur}s thresh={_dur_thresh}s last_run={_dur_lr}",
                        }
                        # #123 R2(2026-10-01): 「执行耗时」与「进行中超时」双通道同 (task,last_run)
                        # 合并——同一次卡死两套独立 key(L699 本 dur 通道 + L894 超时通道)本就各发
                        # 一封(09-30 实测同轮双发); 现在共享 merge|{task}|{last_run} key, 先发通道
                        # 独占(r2_merge_mark), 后发通道查 r2_merge_already_sent 归入已发(不再双发)。
                        # 反例保证: 同实例合并后仍必响(首条由先发通道发出); 隔日再卡=新 last_run=新
                        # merge key=独立再响, 不吞跨天(判定函数 scripts/alert_denoise_rules.py:r2_*)。
                        if _dur_c < DUR_CONTINUOUS_THRESHOLD:
                            print(f"[dur_buffer] {_dur_task} 耗时 {_dur}s 超阈值 {_dur_thresh}s "
                                  f"连续{_dur_c}/{DUR_CONTINUOUS_THRESHOLD}轮, 暂不通知(单轮碰线; "
                                  f">={_dur_thresh * DUR_IMMEDIATE_MULTIPLE}s 或连续"
                                  f"{DUR_CONTINUOUS_THRESHOLD}轮才 SEVERE; dur=null 轮不复位)")
                        elif adr.r2_merge_already_sent(alert_state, _dur_task, _dur_lr):
                            print(f"[r2-merge-suppress] {_dur_task} 耗时超阈值 {_dur_thresh}s: "
                                  f"同 last_run<{_dur_lr}> 已由超时/耗时另一通道发出, 合并去重")
                        elif _ex_dur is None or _ex_dur.get("status") != "active":
                            alerts.append(
                                f"SEVERE: {_dur_task} 执行耗时 {_dur}s 超阈值 {_dur_thresh}s "
                                f"last_run<{_dur_lr}> (进程退化/卡死信号)"
                            )
                            alert_state[_dur_key] = {
                                "status": "active",
                                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "keyword": f"dur>{_dur_thresh}s",
                                "line_sample": f"dur={_dur}s last_run={_dur_lr}",
                            }
                            adr.r2_merge_mark(alert_state, _dur_task, _dur_lr, NOW)
                        else:
                            print(f"[suppress] {_dur_task} 耗时超阈值持续中, "
                                  f"last_alerted={_ex_dur.get('last_alerted')}, 不重发")
                else:
                    # #240 ③: 耗时回到阈值内 = 碰线/退化已过去 → 计数桶复位(静默; 已发 SEVERE 的
                    # 恢复通知仍由主恢复循环负责, 不在此发)。archive 语义与 marker_buffer 复位同款。
                    _dur_cnt_key_r = f"{_dur_task}{adr.DUR_BUFFER_KEY_MARK}{_dur_thresh}"
                    _dur_br = alert_state.get(_dur_cnt_key_r)
                    if _dur_br and _dur_br.get("status") in ("pending", "alerted"):
                        alert_state[_dur_cnt_key_r] = {
                            **_dur_br,
                            "status": "recovered",
                            "consecutive_count": 0,
                            "recovered_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        }
            # P1-1(2026-09-24, r2-false-success-rootfix): r2_skip_count 真正消费——
            # SKIPPED_LOCKED(R2 上传锁忙跳过本轮)单次是设计让路(下轮 10min 后重试),
            # 不上 SEVERE(噪噪音); 但**连续多轮** skip = 上传缺口持续(收盘版/每日版可能
            # 一直没上 R2), 必须自动发现告警。gen_schedule_stats 已把 TASKS 表任务 +
            # gen_daily_brief/fetch_news(EXTRA_MARKER_SCANS)的 r2_skip_count 输出进
            # schedule_stats.json, 此处消费: 连续多轮 r2_skip_count>0 → SEVERE。
            # 判定: 用 alert_state 的 {task}|r2_skip_rounds 计数跨轮次(15min 一轮 monitor,
            # intraday 10min 一轮, 连续 3 轮 monitor 看到 skip ≈ intraday 连续 3-5 轮 skip)。
            # 恢复: 本轮 r2_skip_count==0/缺失 → 计数清零, key 未 seen → 主恢复循环自动发
            # 恢复邮件。notify 出口与既有告警一致。
            # [#181 2026-10-07 fetchnews-denoise, ①d 三改(计数语义治本, 用户已拍板动此冻结面)]:
            #   ① 轮去重: count_key 增 last_round(= stats last_run 分钟串)做轮标识, 同一轮被多
            #      个 tick 消费时不再重复 +1。根因: fetch_news 每小时 :01/:45 两轮 + 30min 新鲜
            #      窗 + :45 stale, 使「一个真 skip 轮」被 :00/:15/:30 三个 tick 各计 1 次 →
            #      消息自称「连续 3 轮」实则 distinctRounds=2(实测 13/13 SEVERE 皆 counted=3/
            #      distinctRounds=2)。
            #   ② 去假清零: 滞留 skip(本轮无新运行)不再清连续链(保链), 替换旧「age>30min ⇒
            #      清零 + 下一 tick 假恢复」的结构性循环(旧循环致 7h 锁事件每小时重报 1 封)。
            #   ③ seen 补全: 连续计数 >= 阈值 的**任一** skip tick(含新轮/重复轮/滞留轮)都 mark
            #      告警 key seen —— 否则通用恢复循环(L1644-1716, 本轮不改)会在 15min 后把未
            #      seen 的 active key 误判「已消失」→ 假恢复 → 1h 后重报。
            #   保留 else(本轮无 skip)清链分支 = 唯一合法清零点 = 真恢复入口(不得一并去掉)。
            #   阈值 R2_SKIP_CONTINUOUS_THRESHOLD / R2_SKIP_OBS_WINDOW 保持原值(未实现任何 dial)。
            _r2_skip_cnt = s.get("r2_skip_count")
            if isinstance(_r2_skip_cnt, int) and _r2_skip_cnt > 0:
                # P1-3(2026-09-24 r2skip-alert-fix): 计数语义修正——r2_skip_count 是「任务最近
                # 一次运行窗口内 SKIPPED_LOCKED 行数」。last_run 不在本轮观察窗口内(= 本轮没有
                # 新运行)= 滞留值, 不参与「连续 N 轮」计数(#181 后: 保链不清零, 见上②)。
                _r2_fresh = True  # 解析失败/缺失保守当新鲜处理(不因解析问题吞真告警)
                _r2_lr = s.get("last_run") or ""
                if _r2_lr:
                    try:
                        _r2_lr_dt = datetime.strptime(_r2_lr, "%Y-%m-%d %H:%M")
                        _r2_fresh = (NOW - _r2_lr_dt) < R2_SKIP_OBS_WINDOW
                    except ValueError:
                        pass  # 格式异常保守当新鲜
                _r2_cnt_key = f"{s['task']}|r2_skip_rounds"
                _r2_prev = alert_state.get(_r2_cnt_key) or {}
                _r2_n = int(_r2_prev.get("skip_rounds") or 0)
                # #181race(2026-10-09, 用户已拍板动此冻结面): 轮标识**与 skip 窗口同源**——
                #   用 gen_schedule_stats 输出的 r2_round_id(= 拥有当前 skip 窗口那一轮的「轮次
                #   开始」时间戳), **不用文件 mtime(last_run)**。根因:旧用 last_run=mtime 当轮标识,
                #   而计数窗口=[最后「已写」行, EOF) 与之异源; fetch_news :45 tick 与 :45 轮
                #   同秒起跑时「轮次开始」已 flush(mtime 先刷新)而「已写」未写(窗口仍指上一轮) ⇒
                #   same_round 误判 False ⇒ 同一真 skip 轮被 +1 两次(幻影), 阈值 3 退化为 2
                #   (假阳性; 生产样本 docs/ops/181-denoise-prod-sample-20261008.md §5)。
                #   r2_round_id 缺失(旧 stats / 非 EXTRA 任务 / 找不到窗口起点)⇒ 回退 last_run,
                #   行为与改动前逐字一致(向后兼容, 全量既有测试不变)。新鲜度判据仍用 last_run(不变)。
                _r2_round = s.get("r2_round_id") or _r2_lr
                # ① 轮去重: 仅当「本轮有新运行(last_run 新鲜)」且「轮标识 != 上次计数轮」才 +1。
                _r2_same_round = bool(_r2_round) and _r2_round == _r2_prev.get("last_round")
                if _r2_fresh and not _r2_same_round:
                    _r2_n += 1
                    _r2_prev["last_round"] = _r2_round
                    _r2_prev.setdefault("first_seen", NOW.strftime("%Y-%m-%d %H:%M:%S"))
                _r2_prev["skip_rounds"] = _r2_n
                if _r2_n > 0:
                    # 计数 key 只记录连续轮次(不写告警去重 key, 恢复循环按 count_key 判断)
                    alert_state[_r2_cnt_key] = _r2_prev
                if _r2_n >= R2_SKIP_CONTINUOUS_THRESHOLD:
                    # 达到连续阈值: 用独立告警去重 key(计数 key 状态不干扰告警去重)。
                    # ③ seen 补全: 达阈值后**每一** skip tick(新轮/重复/滞留)都 mark 告警 key
                    # seen(告警仍存在) -> 只有 skip 停止(else 清零点不 mark)恢复循环才判消失
                    # 发恢复邮件, 同时杜绝「滞留轮不 mark → 假恢复」循环。
                    _r2_alert_key = f"{s['task']}|r2_skip_alert"
                    seen_keys_this_run.add(_r2_alert_key)
                    _r2_exist = alert_state.get(_r2_alert_key)
                    if _r2_exist is None or _r2_exist.get("status") != "active":
                        _r2_line = f"r2_skip_count={_r2_skip_cnt} 连续{_r2_n}轮"
                        alerts.append(
                            f"SEVERE: {s['task']} R2 上传锁连续 {_r2_n} 轮跳过(SKIPPED_LOCKED), "
                            f"上传缺口持续(收盘版/每日版可能未上 R2), 需人工关注"
                        )
                        alert_state[_r2_alert_key] = {
                            "status": "active",
                            "first_seen": _r2_prev.get(
                                "first_seen", NOW.strftime("%Y-%m-%d %H:%M:%S")),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": "r2_skip_continuous",
                            "line_sample": _r2_line,
                        }
                    else:
                        # 已告警过: 刷新计数 key 触发恢复检测(本轮 skip 仍存在), 不重发
                        # (与现有 durable 告警语义一致)
                        _r2_exist["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                        _r2_exist["line_sample"] = f"r2_skip_count={_r2_skip_cnt} 连续{_r2_n}轮"
                        print(f"[suppress] {s['task']} R2 锁连续skip持续中, "
                              f"last_alerted={_r2_exist.get('last_alerted')}, 不重发")
                elif _r2_n > 0:
                    if _r2_same_round:
                        print(f"[r2-skip-dup] {s['task']} R2 锁skip 同轮重复tick"
                              f"(last_round={_r2_round}), 不重复计数"
                              f"(连续{_r2_n}/{R2_SKIP_CONTINUOUS_THRESHOLD})")
                    elif not _r2_fresh:
                        print(f"[r2-skip-stale] {s['task']} R2 锁skip为滞留值(最近运行距今>"
                              f"{int(R2_SKIP_OBS_WINDOW.total_seconds()//60)}min, 本轮无新运行), "
                              f"保链不计数(连续{_r2_n}/{R2_SKIP_CONTINUOUS_THRESHOLD})")
                    else:
                        print(f"[r2-skip] {s['task']} R2 锁skip 连续{_r2_n}/"
                              f"{R2_SKIP_CONTINUOUS_THRESHOLD} 轮(未达阈值, 不告警)")
                else:
                    # 本轮无新运行且史上无链: 纯滞留 skip, 不建空 key(不留噪音状态)
                    print(f"[r2-skip-stale] {s['task']} R2 锁skip为滞留值(最近运行距今>"
                          f"{int(R2_SKIP_OBS_WINDOW.total_seconds()//60)}min, 本轮无新运行且无"
                          f"历史链), 不计数")
            else:
                # 本轮无 skip: 连续计数清零。计数 key 本轮未 seen +
                # skip_rounds=0 -> 主恢复循环把既有告警 key 判为消失发恢复邮件。
                # (真恢复入口; #181 未改此分支。)
                _r2_cnt_key = f"{s['task']}|r2_skip_rounds"
                _r2_prev = alert_state.get(_r2_cnt_key)
                if _r2_prev and int(_r2_prev.get("skip_rounds") or 0) > 0:
                    _r2_prev["skip_rounds"] = 0
                    _r2_prev["last_round"] = None
                    print(f"[r2-skip] {s['task']} R2 锁连续skip清零(本轮无skip)")
        # P2(2026-09-24 r2 终审): EXTRA 任务停摆漏跑告警。
        # fetch_news/gen_daily_brief 不在 MISSED_TASKS 漏跑检查(TASKS 表无对应条目,
        #   gen_schedule_stats.EXTRA_MARKER_SCANS 单独扫), 若部署外生成器整个停摆
        #   (systemd timer/脚本被删/崩) 将无声无息, 无任何告警。
        # 补: 对 EXTRA 两任务, 若 last_run(文件 mtime≈最近运行) 距今超过该任务
        #   计划频率的 N 倍(停摆阈值), 发 SEVERE。计划频率: fetch_news 30min 一轮
        #   (7:30-21:00), gen_daily_brief 每日 20:40 一轮。
        #   阈值(余量充足防误报): fetch_news 4h(错过 ~8 轮才告警), gen_daily_brief 26h。
        #   只发一次挂 active(主恢复循环在任务恢复后自动发恢复邮件)。
        for _es in stats:
            _et = _es.get("task")
            if _et not in EXTRA_MARKER_STALE_LOOPS:
                continue
            _elr = _es.get("last_run") or ""
            if not _elr:
                continue
            try:
                _elr_dt = datetime.strptime(_elr, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            _eloop = EXTRA_MARKER_STALE_LOOPS[_et]
            if NOW - _elr_dt <= _eloop:
                continue
            _stale_key = f"{_et}|extra_stale"
            seen_keys_this_run.add(_stale_key)
            _ex_stale = alert_state.get(_stale_key)
            if _ex_stale is None or _ex_stale.get("status") != "active":
                alerts.append(
                    f"SEVERE: {_et} 停摆(超{int(_eloop.total_seconds()//3600)}h 未运行) "
                    f"last_run={_elr} (定时器可能被删/脚本崩, 无标准漏跑检查覆盖)"
                )
                alert_state[_stale_key] = {
                    "status": "active",
                    "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                    "keyword": "extra_stale",
                    "line_sample": f"last_run={_elr}",
                }
            else:
                print(f"[suppress] {_et} 停摆告警持续中, last_alerted={_ex_stale.get('last_alerted')}, 不重发")
        # #228 M1(2026-10-07): EXTRA 任务「轮次完整性」通道 —— 判「本轮开始了没跑完」。
        # 与上面停摆通道天然互斥: 停摆 = 无开始标记(round_state='no_start'); 完整性 = 有开始
        #   无收尾(round_state='started_unfinished')。判别三元素见常量区 EXTRA_ROUND_INCOMPLETE。
        # 降噪: 同轮 log_anomaly 已命中(✗/⚠ 更具体的真故障信号) → M1 不重复报(双响抑制)。
        # 恢复: 下一轮成功收尾 ⇒ round_state='completed' ⇒ 本 key 未 seen ⇒ 主恢复循环自动发恢复邮件。
        for _es in stats:
            _et = _es.get("task")
            if _et not in EXTRA_ROUND_INCOMPLETE:
                continue
            if _es.get("round_state") != "started_unfinished":
                continue
            # 同轮已有 log_anomaly(✗/⚠ 关键词命中): 更具体信号优先, M1 不报(降噪, 防双响)
            if _es.get("log_anomaly"):
                continue
            _erst = _es.get("round_start_ts") or ""
            if not _erst:
                continue
            try:
                _erst_dt = datetime.strptime(_erst, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            _eage = NOW - _erst_dt
            _ustate = _es.get("unit_active_state")
            if _ustate:
                # unit 状态可读: 仍在跑(慢跑, 宽容) 或 未超宽限 → 不报
                if _ustate in ("active", "activating", "reloading") or _eage <= ROUND_INCOMPLETE_GRACE:
                    continue
            else:
                # 读不到 unit 状态(非 Linux / unit 不存在): 退化为纯 age 判据(更大阈值防误报)
                if _eage <= EXTRA_ROUND_INCOMPLETE[_et]:
                    continue
            _ri_key = f"{_et}|round_incomplete"
            seen_keys_this_run.add(_ri_key)
            _ex_ri = alert_state.get(_ri_key)
            _le = _es.get("unit_last_exit")
            _le_txt = f"unit last_exit={_le}" if _le is not None else "unit last_exit=未知"
            if _ex_ri is None or _ex_ri.get("status") != "active":
                alerts.append(
                    f"SEVERE: {_et} 轮次未正常收尾(开始 {_erst}, 无完成/失败标记, "
                    f"疑被 systemd 超时杀/FAIL; {_le_txt})"
                )
                alert_state[_ri_key] = {
                    "status": "active",
                    "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                    "keyword": "round_incomplete",
                    "line_sample": f"round_start_ts={_erst} unit_active_state={_ustate} {_le_txt}",
                }
            else:
                _ex_ri["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[suppress] {_et} 轮次未收尾告警持续中, last_alerted={_ex_ri.get('last_alerted')}, 不重发")
    except Exception as e:
        print(f"[warn] 解析 schedule_stats.json 失败: {e}", file=sys.stderr)

# A1 进行中超时检测（2026-08-14 告警优化）: 任务卡死/异常慢(未完成)检测。
# 背景: 原 dur 检查只查"已完成"任务(last_duration_sec 非 null), 任务进行中超时
#   (未完成, dur=null)完全不检查 -> 8-14 update_all 17:50 卡死 54min+ 无超时告警;
#   同时 dur=null 时 key 未 seen, 恢复检测循环误判"异常已消失"发恢复邮件。
# 规则: 对每个进行中任务(dur=null + exit=null, 已收集 in_progress_tasks), 取今日
#   最近一次已到计划时点 sch, 若 last_run >= sch(任务确在该时点启动) 且
#   NOW > sch + 耗时阈值 + 缓冲 -> 超时告警。缓冲(IN_PROGRESS_BUFFER)防正常偏慢误报
#   (update_all +30min / backfill +15min; 阈值已重标 update_all=4200s/backfill=4500s,
#   对齐近9交易日实测 max, 2026-08-14 修复 A1 误报正常日)。
# 超时 key 进 seen_keys_this_run(防误恢复), 已 active 则 suppress 不重发。
IN_PROGRESS_BUFFER = {
    "update_all": 30,          # 计划17:50 +135min阈值(8100s,#82 C6 摘出 turnover 后) +30min缓冲 = 21:35 未完成才告警
                               # (原 18:40 早于正常完成 18:50 误报, reviewer FAIL 2026-08-14)
    "backfill_evening": 15,    # +75min阈值(4500s) +15min = 90min 窗口
    "intraday_snapshot": 10,
    "us_stock_morning": 10,
}
_task_sched_map = {t["task"]: schedules_for_today(t) for t in TASKS}
_stats_by_task = {s.get("task"): s for s in stats if isinstance(s, dict)}
for _ip_task in sorted(in_progress_tasks):
    _ip_scheds = _task_sched_map.get(_ip_task, [])
    _ip_dur_thresh = DUR_THRESHOLDS[_ip_task]
    _ip_buffer = IN_PROGRESS_BUFFER.get(_ip_task, 0)
    # 今日最近一次已到计划时点(<= NOW)
    _sch_dts = []
    for _h in _ip_scheds:
        _st = today_schedule(_h)
        if _st <= NOW:
            _sch_dts.append(_st)
    if not _sch_dts:
        continue
    _latest_sch = max(_sch_dts)
    _ip_stats = _stats_by_task.get(_ip_task, {})
    _ip_lr = _ip_stats.get("last_run") or ""
    _ip_started_at_sch = False
    if _ip_lr:
        try:
            _ip_lr_dt = datetime.strptime(_ip_lr, "%Y-%m-%d %H:%M")
            if _ip_lr_dt >= _latest_sch:
                _ip_started_at_sch = True
        except ValueError:
            pass
    if not _ip_started_at_sch:
        continue
    _timeout_at = _latest_sch + timedelta(seconds=_ip_dur_thresh) + timedelta(minutes=_ip_buffer)
    if NOW <= _timeout_at:
        continue
    _run_min = int((NOW - _latest_sch).total_seconds() // 60)
    _ip_key = f"{_ip_task}|in_progress_timeout"
    seen_keys_this_run.add(_ip_key)
    _ex_ip = alert_state.get(_ip_key)
    # #123 R2(2026-10-01): 与耗时通道(L699)合并去重——同一 (task,last_run) 已由另一通道发过
    # 告警(merge key active)则本通道归入已发, 不双发; 先发通道独占后写 merge mark。
    # 反例: 同实例合并后首条仍必响(先发通道发出), 新 last_run 独立再响。判定函数
    # scripts/alert_denoise_rules.py:r2_merge_already_sent / r2_merge_mark。
    if adr.r2_merge_already_sent(alert_state, _ip_task, _ip_lr):
        print(f"[r2-merge-suppress] {_ip_task} 进行中超时: "
              f"同 last_run<{_ip_lr}> 已由超时/耗时另一通道发出, 合并去重")
    elif _ex_ip is None or _ex_ip.get("status") != "active":
        alerts.append(
            f"SEVERE: {_ip_task} 超时未完成 已运行{_run_min}min "
            f"(计划<{_latest_sch.strftime('%H:%M')}> + 阈值{_ip_dur_thresh}s + 缓冲{_ip_buffer}min"
            f"=<{_timeout_at.strftime('%H:%M')}> 仍未完成, 疑似卡死/异常慢) last_run<{_ip_lr}>"
        )
        alert_state[_ip_key] = {
            "status": "active",
            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": "in_progress_timeout",
            "line_sample": f"run={_run_min}min last_run={_ip_lr}",
        }
        adr.r2_merge_mark(alert_state, _ip_task, _ip_lr, NOW)
    else:
        print(f"[suppress] {_ip_task} 进行中超时持续中, "
              f"last_alerted={_ex_ip.get('last_alerted')}, 不重发")

# 5) launchctl 加载检查（2026-07-20 补缺口，方案D）
#    11个 com.trade label（9监控任务 + self-heal，不含 schedule-monitor 自己防递归）。
#    未加载（plist 手动 unload / bootstrap 失败 / 系统重启后未恢复）= launchd 层挂了，
#    下游 schedule_stats/漏跑检查/退出检查全失效（任务根本不会跑），靠 launchctl print 探测。
#    复用 self_heal.sh L73 launchctl_state 逻辑：returncode!=0 或无 `state = ` 行 = 未加载。
#    调用失败（timeout/异常）保守视为未加载（告警），避免 launchctl 故障漏报。
#    alert_state 去重（与 exit!=0 / log_anomaly 路径对称）：
#      key=`{label}|not_loaded`，首次发 SEVERE + 写 state active + seen_keys_this_run 标记，
#      已 active = suppress 不重发，恢复（seen 但 not_loaded 消失）发恢复邮件。
#    插入位置选在恢复检测(L476)之前：alert_state 修改需在 L509 save 之前完成，
#    seen_keys_this_run 标记需在 L476 恢复检测之前完成（否则 launchctl key 未 seen 被误报恢复）。
LAUNCHCTL_LABELS = [
    "com.trade.update-all",
    "com.trade.backfill-evening",
    "com.trade.intraday-snapshot",
    "com.trade.futures-backfill",
    "com.trade.lhb-backfill",
    "com.trade.rzhb-backfill",
    "com.trade.us-stock-morning",
    "com.trade.etf-national-team",
    "com.trade.lab-auto",
    "com.trade.turnover-backfill",
    "com.trade.self-heal",
    # 不含 com.trade.schedule-monitor 自己（防递归，靠 heartbeat 兜底）
]

# 被 exit!=0 通道覆盖的 label 集合（单一事实源：由已加载的 schedule_stats stats 推导，
# task -> label 映射规则 `com.trade.{task 下划线转连字符}` 与 gen_schedule_stats LABEL_MAP 一致）。
# 这些 label 的 failed 状态由 exit!=0 通道（schedule_stats.json last_exit）登记，
# launchctl failed 分支 skip 防双登记。不在该集合的 label（如 com.trade.self-heal：
# 自身不在 gen_schedule_stats TASKS，exit!=0 通道读不到它）failed 时必须降级告警
# 保留发现能力，否则自愈机制失效完全静默（2026-09-19 review 阻断项）。
# ⚠️ 该集合为空（stats 刷新失败/无数据）= 保守降级：所有 failed 都走降级告警（宁可多告警不漏报）。
_schedule_stats_labels = {
    "com.trade." + s.get("task", "").replace("_", "-")
    for s in stats if s.get("task")
}


def launchctl_loaded(label):
    """检查任务是否已加载（macOS launchctl print / Linux systemctl is-active）。
    返回三态字符串：
      'loaded'      = 已加载且正常（active/inactive 均算，unit 已注册）
      'failed'      = 已加载但运行失败（systemd is-active 返回 failed）——不是未加载！
      'not_loaded'  = 未加载（unit 不存在 / launchctl 探测不到 / 调用失败保守处理）
    语义修正(2026-09-19): 原实现把 failed 与不存在一律归「未加载」，
    与 exit!=0 通道（schedule_stats.json last_exit）对同一现象双登记制造噪音。
    现改为 failed 单独成态：failed=unit 存在但运行失败，运行失败信息由
    exit!=0 通道登记，launchctl 通道只负责真未加载（unit 不存在/未注册）。

    ⚠️ 陷阱提示(2026-10-05 #190，与 #160 P0 同族): 本函数判的是「unit 是否已加载」，
    不是「是否在跑」。云上 trade-*.service 多为 Type=oneshot(RemainAfterExit=no)，
    运行中 ActiveState=activating，`is-active` 输出 'activating' 且 **rc=3(与 inactive 同码)**。
    切勿照本函数/注释推导「is-active rc=0 即在跑」——那是死判据；判「在跑」请照
    self_heal.sh:111(解析 stdout，activating 视为 running)或 check_r2_consistency.sh:91
    (`systemctl show -p ActiveState --value` ∈ {active, activating})。
    """
    if shutil.which("systemctl"):
        # Linux: systemd unit 名 = launchd label 把 com.trade. 前缀映射成 trade-（云上实际 unit 名）
        unit = label.replace("com.trade.", "trade-", 1) + ".service"
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return "not_loaded"  # 调用失败保守视为未加载（告警）
        st = (r.stdout or "").strip()
        # ⚠️ oneshot 陷阱(2026-10-05 #190，与 #160 P0 同源) —— 旧的「0=active(在跑)」注释是错的，勿照抄：
        #   `is-active` 的「在跑」只对 Type=simple 等长驻服务成立(rc=0 ⇔ ActiveState=active)；
        #   云上 trade-*.service 多为 Type=oneshot(RemainAfterExit=no)，**运行中 ActiveState=activating，
        #   is-active 输出 'activating' 且 rc=3(与 inactive 同码)** —— 拿「rc==0 判在跑」在生产恒不成立(死判据)。
        #   故本函数语义刻意定为「unit 是否已加载」(非「是否在跑」)：rc=0(active) / rc=3(inactive 或
        #   activating 或 stdout='failed')均 = 已加载，仅 unit 不存在(rc=4) = not_loaded。
        #   切勿改成 `is-active --quiet`(丢 stdout 会把 failed 吞成 loaded)。判「在跑」照 self_heal.sh:111
        #   或 check_r2_consistency.sh:91(ActiveState ∈ {active, activating})，勿从本函数推导。
        if st == "failed":
            return "failed"
        return "loaded" if r.returncode in (0, 3) else "not_loaded"
    # macOS: launchctl print
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return "not_loaded"  # 调用失败保守视为未加载（告警）
    if r.returncode != 0:
        return "not_loaded"
    return "loaded" if re.search(r"^\s*state = .+$", r.stdout, re.MULTILINE) else "not_loaded"


def not_loaded_help(label):
    """未加载告警的「探测描述 + 恢复命令」文案(按平台, 与 launchctl_loaded 同映射)。
    云上 Linux systemd 不存在 launchctl, 恢复建议须给 systemctl restart <unit>.service;
    macOS 保持 launchctl bootstrap ~/Library/LaunchAgents/<label>.plist。
    """
    if shutil.which("systemctl"):
        unit = label.replace("com.trade.", "trade-", 1) + ".service"
        return (f"systemctl is-active {unit} 未加载", f"systemctl restart {unit}")
    return (f"launchctl print gui/{os.getuid()}/{label} 未加载",
            f"launchctl bootstrap ~/Library/LaunchAgents/{label}.plist")


for _label in LAUNCHCTL_LABELS:
    _lstate = launchctl_loaded(_label)
    if _lstate == "loaded":
        continue  # 已加载，不 add seen（让恢复检测处理 active/pending->recovered）
    if _lstate == "failed":
        # 2026-09-19 语义修正 第一层: failed=已加载但运行失败, 不是"未加载"。
        if _label in _schedule_stats_labels:
            # 被 exit!=0 通道覆盖的 label: 运行失败信息由 exit!=0 通道
            # (schedule_stats.json last_exit)登记并去重, launchctl 通道不在此登记
            # (消除同一现象 not_loaded+exit!=0 两条告警噪音)。
            # 不 add seen: 本通道不认 failed 为 not_loaded, 若此前 not_loaded 已 active,
            # 由恢复检测按未 seen 判"未加载已消失"(语义正确: 不再未加载, 转为运行失败由 exit!=0 通道接管)。
            print(f"[skip] {_label} systemd is-active=failed(已加载但运行失败), 交给 exit!=0 通道登记, 不重复 not_loaded")
            continue
        # ⚠️ 语义修正 第二层(2026-09-19 review 阻断项): self-heal 等不在 gen_schedule_stats
        # TASKS 的 label, exit!=0 通道读不到, 上面 continue 会让 failed 状态彻底静默
        # (自愈机制失效无人知晓)。此处降级为本通道登记: 首次发 SEVERE + 写 state active,
        # 已 active = suppress 不重发(去重), 恢复(本 label 才出现/不再 failed)时由恢复检测
        # 按下条规则发恢复邮件即可(需 add seen 防误报恢复)。
        # severity=SEVERE 直接发: self-heal 是自愈机制本体, 它 failed 无下游可救, 必须直达人。
        _failed_key = f"{_label}|failed"
        seen_keys_this_run.add(_failed_key)
        _existing_failed = alert_state.get(_failed_key)
        if _existing_failed is None or _existing_failed.get("status") == "recovered":
            alerts.append(
                f"SEVERE: {_label} systemd is-active=failed(运行失败) 且不在 schedule_stats "
                f"TASKS(exit!=0 通道读不到), 自愈机制失效已无下游接管, 需人工处理"
            )
            alert_state[_failed_key] = {
                "status": "active",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": "failed",
                "line_sample": _label,
            }
            print(f"[self-heal failed] {_label} 运行失败且无 exit!=0 通道覆盖, 首次发 SEVERE")
        else:
            # 已 active = 抑制不重发,只 log
            print(
                f"[suppress] {_label} systemd is-active=failed(无 exit!=0 覆盖) 持续中, "
                f"last_alerted={_existing_failed.get('last_alerted')}, 不重发"
            )
        continue
    dedup_key = f"{_label}|not_loaded"
    seen_keys_this_run.add(dedup_key)
    _existing = alert_state.get(dedup_key)
    # 通知分级(2026-08-10): not_loaded 可被 self_heal.sh 自动恢复, 连续N次才通知
    if _existing is None or _existing.get("status") == "recovered":
        alert_state[dedup_key] = {
            "status": "pending",
            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alerted": None,
            "consecutive_count": 1,
            "keyword": "not_loaded",
            "line_sample": not_loaded_help(_label)[0],
            "tier": "self_heal",
        }
        print(f"[self_heal pending] {_label} 未加载(自愈类), 连续1/{SELF_HEAL_THRESHOLD}, 暂不通知")
    elif _existing.get("status") == "pending":
        _nl_count = _existing.get("consecutive_count", 0) + 1
        if _nl_count >= SELF_HEAL_THRESHOLD:
            _detect_desc, _recover_cmd = not_loaded_help(_label)
            alerts.append(
                f"SEVERE: {_label} 未加载，需 {_recover_cmd} 恢复"
            )
            _existing["status"] = "active"
            _existing["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            _existing["consecutive_count"] = _nl_count
            print(f"[self_heal escalated] {_label} 连续{_nl_count}次未加载, 发送告警")
        else:
            _existing["consecutive_count"] = _nl_count
            print(f"[self_heal pending] {_label} 连续{_nl_count}/{SELF_HEAL_THRESHOLD}次未加载, 暂不通知")
    elif _existing.get("status") == "active":
        # 已 active = 抑制不重发,只 log
        print(
            f"[suppress] {_label} 未加载持续中, "
            f"last_alerted={_existing.get('last_alerted')}, 不重发"
        )

# ── C3 staticdata 备份心跳新鲜度检查(2026-09-25 审查整改) ──
# 背景: staticdata 灾备第2层备份已拆异步(scripts/staticdata_backup_async.sh), 若异步任务
# 停摆(触发失败/脚本崩/锁死)将无声无息 → 用其心跳状态文件做新鲜度兜底告警。
# 阈值依据(C-3 实测): staticdata 仓库最近 30 天最大 commit 间隔 = 1 天
#   → 阈值 = max(24h × 1.5, 36h) = 36h。超过 36h 无 ok/skip_oversize 完成 = 备份停摆。
# 状态文件不存在 → 不告警(优雅跳过, 防上线即假 SEVERE): 仓库缺失另有独立降级 notify
#   (async 脚本 C-5, --alert-issue 镜像 latest.md), 此处对缺失状态不发 SEVERE。
# result=="fail" / "skip_oversize" 本身已有各自 notify(脚本内 --severe), 不重复告警:
#   本检查只看「最近一次 ok/skip_oversize 完成」的新鲜度, 不看 fail/running。
STATICDATA_HB_FILE = REPO / "data" / "staticdata_backup_heartbeat.json"
STATICDATA_HB_STALE = timedelta(hours=36)  # C-3 阈值 36h(见上注释)
if STATICDATA_HB_FILE.exists():
    try:
        with open(STATICDATA_HB_FILE, encoding="utf-8") as _f:
            _hb = json.load(_f)
        _hb_result = _hb.get("result")
        _hb_ts = _hb.get("ts")
        if _hb_result in ("ok", "skip_oversize") and _hb_ts:
            _hb_dt = datetime.strptime(_hb_ts, "%Y-%m-%d %H:%M:%S")
            _hb_age_h = int((NOW - _hb_dt).total_seconds() // 3600)
            if NOW - _hb_dt > STATICDATA_HB_STALE:
                _hb_key = "staticdata_backup_stale"
                seen_keys_this_run.add(_hb_key)  # 标记本次仍存在, 防误报恢复
                _hb_existing = alert_state.get(_hb_key)
                if _hb_existing is None or _hb_existing.get("status") != "active":
                    # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                    alerts.append(
                        f"SEVERE: staticdata_backup staticdata 异步备份停摆 "
                        f"最近完成<{_hb_result}> 距今{_hb_age_h}h "
                        f"(>{int(STATICDATA_HB_STALE.total_seconds()//3600)}h 阈值) 备份时间<{_hb_ts}>"
                    )
                    alert_state[_hb_key] = {
                        "status": "active",
                        "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "keyword": f"hb_stale_{_hb_result}",
                        "line_sample": f"last_ok={_hb_ts}",
                    }
                else:
                    # 已 active = 抑制不重发, 只 log(恢复由下方恢复检测循环处理:
                    # 心跳恢复 fresh 后未 seen → 自动发恢复邮件)
                    print(
                        f"[suppress] staticdata_backup 异步备份停摆持续中, "
                        f"last_alerted={_hb_existing.get('last_alerted')}, 不重发"
                    )
    except (ValueError, TypeError, KeyError) as _e:
        # 心跳格式异常/解析失败: 按无有效状态处理, 不告警(防上线即假 SEVERE, 盲区写入注释)。
        print(f"[warn] staticdata 备份心跳解析失败(按无有效状态跳过): {_e}", file=sys.stderr)
else:
    # 状态文件不存在 → 不告警(盲区: 仓库缺失/首跑前无法判断停摆; 由 async 脚本 C-5 降级 notify 覆盖)
    print("[info] staticdata 备份心跳文件不存在, 跳过停摆检查(仓库缺失/首跑前, C-5 降级 notify 覆盖)")

# ===== 维度⑩ 主机资源（磁盘/inode/内存/swap）阈值检查（#164, 2026-10-05）=====
# 背景（云上健康巡检 D1 P1-1）：原 9 维度全部面向任务执行面（漏跑/退出/耗时/加载/产物时效
#   /R2/飞书），无一条覆盖"主机资源"。2026-09-30 云上磁盘涨到 92% 全靠人眼发现——磁盘写满会
#   先让任务失败、DB 报错、告警邮件自身都发不出去（日志/产物写不了），是最该"最先知道"的一类。
# 阈值（warn/severe = 85%/90%，四指标同款）：
#   为何不采用 D1 报告建议的「warn 85 / severe 95 + inode≥90 + 内存<500M 或 swap>80%」——
#   ① severe 定 95 太晚: 09-30 那次涨到 92% 全程静默(报告本身就是在说"靠人眼才发现")，95 线
#      整场事故都不会响; 90% 留 ~5-10%(云上 61.8G 盘 = 3-6G)处置余量, 且内存/swap 的 90%
#      已逼近 OOM/换页枯竭。② 四指标同款一对数(而非四套口径)更可预期, 免"哪个指标哪条线"记错。
#   ③ 内存改用"可用量口径"(MemAvailable)而非绝对 <500M: 与磁盘同为单位无关的百分比,
#      阈值语义统一; 且 500M 对 3.7G 与 16G 的机器危险程度完全不同(百分比才能跨机型)。
#   ④ swap 阈值由 80% 提到 85/90 同款: 统一口径; swap 到 80% 时内核 I/O 早已抖动, 提前无益。
#   ① 磁盘 used%（df 口径 used/(used+bavail)，向上取整与 GNU df 显示一致）：85/90 —— 写满即全线瘫。
#   ② inode used%（(f_files-f_ffree)/f_files，df -i 口径，同样向上取整）：85/90 —— inode 耗尽
#      与磁盘写满同效，但"用量"看不见（大量小文件：日志/JSON/WAL/manifest）。同一根因
#      （fs 满）的独立判别维度，不可省。① ② 用 df 显示值（含 ceil）判定，操作者 df 复核能对上；
#      ③ ④ 无 df 对应物（free 只给近似值），用原始值判定不取整。
#   ③ 内存 used%（available 口径 = 100*(1-MemAvailable/MemTotal)）：85/90 —— 用内核"可用量"
#      估计而非含 page cache 的 used%（后者虚高必误报）；>=90% = OOM 风险，任务被 kill。
#   ④ swap used%（仅 SwapTotal>0 时）：85/90 —— swap 耗尽 = 内存压力已到极限的强信号。
# 分级（复用本脚本既有分级，不新造告警通道）：
#   >=severe -> 追加到 alerts（本轮 SEVERE 邮件，即时）+ 写 alert_state 去重；
#   >=warn   -> notify.py --tier warning（入 notify 的 30min 聚合缓冲，尾部 --flush-warnings 批发）
#               + --dedup-key/6h 窗口，防每 15min 一轮轰炸。
# 恢复：本块在主恢复循环（下方 L1227 起）之前运行，key 前缀 host_resource 不在任何 skip 清单中
#   -> 指标回落（未 seen）时由主循环统一发恢复邮件（同 staticdata 心跳块的模式，不另写 inline）。
RESOURCE_WARN_PCT = 85.0
RESOURCE_SEVERE_PCT = 90.0


def _df_pct_ceil(_pct):
    """向上取整到整数百分比（GNU df 显示口径）；_pct 为 None 时透传 None。"""
    if _pct is None:
        return None
    _i = int(_pct)
    return float(_i + 1 if _pct > _i else _i)


def _df_used_pct(_path):
    """POSIX statvfs 算磁盘 used%，与 GNU df 显示一致（含向上取整）。失败 -> None（不告警）。

    用 used/(used+bavail) 是 df 的口径（avail = 非 root 可用块，排除保留块）。
    ⚠️ GNU df 显示百分比时向上取整（ceil），故此处同样 ceil——否则会出现
    "df 显示 85% 而监控算 84%（不告警）"的观感不一致（云上 2026-10-05 实测正是此边界:
    raw 84.01% / df 85%；改 ceil 后云上机检 df 85% == 本实现 85.0%，Linux 已逐位对齐）。
    ⚠️ macOS(开发机)例外: APFS 下 df 报"容器级"容量(含同容器其他卷空闲)与 statvfs 的
    "卷级"口径不同(实测 df -P / =14% vs 本实现 83%)，该对齐只对生产 Linux 成立。
    """
    try:
        _st = os.statvfs(_path)
    except Exception:
        return None
    _used = _st.f_blocks - _st.f_bfree
    _denom = _used + _st.f_bavail
    # 向上取整对齐 df 显示（_df_pct_ceil）；denom<=0 异常 -> None
    return _df_pct_ceil(100.0 * _used / _denom) if _denom > 0 else None


def _inode_used_pct(_path):
    """statvfs inode used%（df -i 口径，含向上取整）。无 inode（f_files<=0）/失败 -> None。"""
    try:
        _st = os.statvfs(_path)
    except Exception:
        return None
    if _st.f_files <= 0:
        return None
    return _df_pct_ceil(100.0 * (_st.f_files - _st.f_ffree) / _st.f_files)


def _mem_used_pct():
    """内存 available 口径 used%。Linux /proc/meminfo；macOS vm_stat+sysctl。失败 -> None。"""
    try:
        if sys.platform.startswith("linux"):
            _v = {}
            with open("/proc/meminfo", encoding="utf-8") as _f:
                for _l in _f:
                    _k, _, _val = _l.partition(":")
                    _v[_k.strip()] = _val.strip()
            _tot = float(_v.get("MemTotal", "0").split()[0])
            _avail = float(_v.get("MemAvailable", "0").split()[0])
            return 100.0 * (1.0 - _avail / _tot) if _tot > 0 and _avail > 0 else None
        if sys.platform == "darwin":
            _page = int(subprocess.run(["sysctl", "-n", "hw.pagesize"], capture_output=True,
                                       text=True, timeout=5).stdout.strip() or 4096)
            _tot = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                      text=True, timeout=5).stdout.strip() or 0)
            _inact = _free = _spec = 0
            for _l in subprocess.run(["vm_stat"], capture_output=True, text=True,
                                     timeout=5).stdout.splitlines():
                _n = _l.split(":")[1].strip().rstrip(".") if ":" in _l else ""
                if _l.startswith("Pages free:"):
                    _free = int(_n)
                elif _l.startswith("Pages inactive:"):
                    _inact = int(_n)
                elif _l.startswith("Pages speculative:"):
                    _spec = int(_n)
            if _tot <= 0:
                return None
            _avail = (_free + _inact + _spec) * _page
            return 100.0 * (1.0 - _avail / _tot)
    except Exception:
        return None
    return None


def _swap_used_pct():
    """swap used%（仅 SwapTotal>0 时；非 Linux/失败 -> None）。"""
    try:
        if sys.platform.startswith("linux"):
            _v = {}
            with open("/proc/meminfo", encoding="utf-8") as _f:
                for _l in _f:
                    _k, _, _val = _l.partition(":")
                    _v[_k.strip()] = _val.strip()
            _tot = float(_v.get("SwapTotal", "0").split()[0])
            _free = float(_v.get("SwapFree", "0").split()[0])
            return 100.0 * (_tot - _free) / _tot if _tot > 0 else None
    except Exception:
        return None
    return None


def _check_resource(_label, _scope, _pct):
    """单指标阈值判定：>=severe 入 alerts（通过主恢复循环统一管恢复）；>=warn 入 notify 聚合。"""
    if _pct is None:
        return
    _key = f"host_resource|{_label}|{_scope}"
    if _pct >= RESOURCE_SEVERE_PCT:
        seen_keys_this_run.add(_key)
        _ex = alert_state.get(_key)
        if _ex is not None and _ex.get("status") == "active":
            print(f"[suppress] {_key} {_pct:.1f}% 持续中, 不重发")
        elif _recurrence_suppressed(_ex):
            _ex["status"] = "active"
            _ex["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[recurrence-suppress] {_key} {_pct:.1f}% 恢复后 <6h 复现, 抑制不重发")
        else:
            alerts.append(
                f"SEVERE: {_label} 使用率 {_pct:.1f}% ({_scope}) "
                f"超严重线 {RESOURCE_SEVERE_PCT:.0f}% —— 主机资源告急"
            )
            alert_state[_key] = {
                "status": "active",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": f"{_label}_high",
                "line_sample": f"{_scope} {_pct:.1f}%",
            }
    elif _pct >= RESOURCE_WARN_PCT:
        _wkey = f"host_resource_warn_{_label}_{_scope}".replace("/", "_")
        try:
            subprocess.run(
                [
                    sys.executable, str(REPO / "scripts" / "notify.py"),
                    f"[资源预警] {_label} 使用率 {_pct:.1f}% ({_scope})",
                    f"{_label} 使用率 {_pct:.1f}% ({_scope}) 已达预警线 {RESOURCE_WARN_PCT:.0f}%"
                    f"(严重线 {RESOURCE_SEVERE_PCT:.0f}%); 未到严重级, 仅提示关注增长趋势。",
                    "--tier", "warning", "--dedup-key", _wkey, "--dedup-window", "21600",
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except Exception as _e:
            print(f"[warn] {_key} warning 入队失败: {_e}", file=sys.stderr)
        print(f"[resource-warn] {_key} {_pct:.1f}% 达预警线(>= {RESOURCE_WARN_PCT:.0f}%)")


# 检查对象：仓库所在 fs + /（同 fs 去重，防同盘重复报）。REPO 在云上=L 盘根，
# 单独列 / 兜底"仓库迁走后根盘另满"的场景。
_res_targets = []
for _p in (str(REPO), "/"):
    try:
        _dev = os.stat(_p).st_dev
    except Exception:
        continue
    if _dev not in [_d for _d, _ in _res_targets]:
        _res_targets.append((_dev, _p))
for _dev, _p in _res_targets:
    _check_resource("主机磁盘", _p, _df_used_pct(_p))
    _check_resource("主机inode", _p, _inode_used_pct(_p))
_check_resource("主机内存", "host", _mem_used_pct())
_check_resource("主机swap", "host", _swap_used_pct())

# ── #196①(2026-10-05, F1 族「巡检/链路自身死亡」可见性统一): 云上 failed-unit 巡检 +
#   巡检者自身存活检查(check_failed_units.py)。位置刻意放"恢复检测循环之前"(同
#   launchctl_loaded 通道 L1106 注释要求): 让 _cfu_key 的 seen 标记先于恢复检测完成,
#   否则下一轮 key 未 seen 会被误判"异常已消失"误发恢复邮件。
#   除让「巡检发现异常」经脚本自身通道(notify --severe, dedup failed_units_patrol)发出外,
#   更关键的是——**巡检脚本自己跑不起来**(被删/异常/意外退出码)时, 本处直接把它变成
#   本轮主告警邮件里的一条 SEVERE, 让「巡检者死了」当场可见(#196② 核心:
#   不能「巡检者死了没人知」)。rc 映射: 0=健康 / 1=自身通道已发(仅记日志) /
#   3=非云上跳过 / 其他(含 FileNotFoundError/非0异常)→ 追加 SEVERE。
#   异常消失(脚本恢复可跑)→ 恢复检测循环自动发一条 [恢复](monitor 自身自愈值得一条通知,
#   与 r2_* 自愈类"静默恢复"口径不同, 故不复用其前缀)。
# #202 P3-b(2026-10-06): key 首段(task 名, 恢复循环 L1619 取 _key.split("|")[0] 展示)此前误用
# "cloud_unit_patrol"(那是另一个 monitor/云上 unit 漂移巡检的名字, 见 TASKS L183), 而本块实际监控对象
# = check_failed_units.py 自身存活 ⇒ 恢复邮件会显示错误的 task 名。改为实际被监控脚本名, 订正恢复文案。
# 行为逐位不变: key 仅是内部标识, 触发/去重/恢复判定逻辑一字未动(详见 #202 报告"同输入输出"段)。
_cfu_key = "check_failed_units|self|dead"
_cfu_dead = None
try:
    _r_cfu = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_failed_units.py"),
         "--repo", str(REPO), "--notify"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    _cfu_out = (_r_cfu.stdout or "").strip()
    if _r_cfu.returncode == 0:
        print(f"[196] {_cfu_out.splitlines()[0] if _cfu_out else 'failed-unit 巡检 OK'}")
    elif _r_cfu.returncode == 1:
        print(f"[196] 云上 unit 异常(自身通道已发告警): {_cfu_out[:300]}")
    elif _r_cfu.returncode == 3:
        print(f"[196] failed-unit 巡检跳过(非云上环境): {_cfu_out[:200]}")
    else:
        _cfu_dead = (f"云上 failed-unit 巡检脚本自身异常 rc={_r_cfu.returncode}: "
                     f"{(_cfu_out + ' ' + (_r_cfu.stderr or '')).strip()[:200]}")
except Exception as _e:
    _cfu_dead = (f"云上 failed-unit 巡检脚本未能运行({type(_e).__name__}: {_e}) —— "
                 f"巡检者自身死亡, 需人工排查 scripts/check_failed_units.py")
if _cfu_dead:
    seen_keys_this_run.add(_cfu_key)
    _cfu_ex = alert_state.get(_cfu_key)
    if _cfu_ex is None or _cfu_ex.get("status") != "active":
        alerts.append(f"SEVERE: {_cfu_dead}")
        alert_state[_cfu_key] = {
            "status": "active",
            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": "巡检脚本自身异常",
            "line_sample": _cfu_dead[:200],
        }
    else:
        _cfu_ex["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[suppress] {_cfu_key} 持续中, 不重发")

# #123 R2(2026-10-01): merge key 24h 清理(防 alert_state 无界膨胀; merge key 不参与恢复)
adr.r2_merge_cleanup(alert_state, NOW)

# 恢复检测: state 里 active 但本次未 seen = 异常已消失,发恢复邮件
# (gen_schedule_stats 每任务只记首个命中,故每 task 至多1个 active key)
# 漏跑 key(missed|...) 特殊处理: 不发恢复邮件(漏跑补跑不需通知, 任务补跑 stats
# 自更新), 跨日(日期<今天)静默清理(昨天漏跑 key 今天不检查了)。
# 同日窗口外未 seen 保持 active(任务可能真漏跑未补, 等 next day 跨日清理)。
for _key, _info in list(alert_state.items()):
    # #123 R2/R5(2026-10-01): merge| 共享去重 key 与 r2_pipeline_congestion| 日汇总状态
    # 不是"异常告警", 不参与恢复检测(否则 merge key 未 seen 被误发恢复邮件)。
    if _key.startswith(adr.MERGE_PREFIX) or _key.startswith(adr.R2_CONGESTION_SUMMARY_KEY_PREFIX):
        continue
    # #240 ③ 复审 F2(2026-10-09): dur 计数桶(|dur_buffer|)由 dur 块**内联自管复位**
    # (耗时回到阈值内 → recovered; 起止都在同一块), 不参与本恢复循环 —— 否则 dur=None 轮
    # (最新 run 进行中)进不了 dur 块、不登记 seen, pending 桶被此处静默翻 recovered、计数从头
    # 再来, 致 D∈[900,1800) 的 run 结构性凑不出「相邻 2 run 各超阈」而完全静默(旧行为会报)。
    # 注: 真告警 key `{task}|dur>{thresh}s` 不受影响, 仍由本循环负责发 [恢复]。
    if adr.DUR_BUFFER_KEY_MARK in _key:
        continue
    # 通知分级(2026-08-10): pending(自愈类未通知) 未 seen = 静默恢复(不发恢复邮件)
    if _info.get("status") == "pending":
        # r2_/72h_ 有自己的 inline 恢复检测, 不在此处理
        if _key.startswith("r2_") or _key.startswith("72h_"):
            continue
        if _key not in seen_keys_this_run:
            _info["status"] = "recovered"
            _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[silent recovery] {_key} 自愈类异常已消失(未通知过)")
        continue
    if _info.get("status") != "active":
        continue
    if _key == "overview_lag_3domain" or _key.startswith("r2_") or _key.startswith("72h_") or _key.startswith("feishu_"):
        # overview 时效滞后的去重+恢复由 overview 检查块内联处理
        # （该块在恢复检测循环之后运行，不能复用此循环，否则未 seen 被误报恢复）
        # R2 keys(r2_unreachable/r2_overview_lag/r2_intraday_lag)同理: R2检查块在
        # 恢复循环之后运行, 由 R2块内联处理恢复(C1修复: 否则每15min 2封邮件)
        # 72h_ keys 由 monitor_72h.sh 独立管理(自己的恢复检测循环 L689-705),
        # schedule_monitor 不检查 72h 条件(sw_version/S5/stale_alert), 不应对其做
        # 恢复检测 -- 否则 72h_ active key 不在 seen_keys_this_run 被误判"已恢复"
        # -> :15/:45 误恢复 + :10/:40 72h重报 = 振荡(2026-08-10 修复)
        # feishu_ keys(飞书配置缺失, 2026-08-17 三件套①)同理: 检查块在恢复循环之后运行,
        # 由块内 inline 处理恢复(防未 seen 被误判已恢复, 与 r2_ 同模式)
        continue
    # 2026-08-14 告警优化 A1: 任务仍在进行中(dur=null + exit=null)时, 其历史异常 key
    # 不能判"已恢复" -> 防 8-14 误恢复(update_all 卡死 dur=null 未 seen 被误判异常已消失,
    # 18:00 误发 [恢复] update_all)。保持 active, 等任务真正完成(exit 非0/耗时超/或进行中
    # 超时告警)后再走恢复逻辑。
    if "|" in _key and _key.split("|", 1)[0] in in_progress_tasks:
        print(f"[hold] {_key} 任务仍在进行中(dur=null), 不判恢复(保持 active)")
        continue
    if _key not in seen_keys_this_run:
        if _key.startswith("missed|"):
            # 漏跑 key: 不发恢复邮件, 检查是否跨日静默清理
            # key 格式: missed|{task}|{sch_hm}|{YYYY-MM-DD}
            parts = _key.split("|")
            if len(parts) == 4 and parts[3] < NOW.strftime("%Y-%m-%d"):
                _info["status"] = "recovered"
                _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[cleanup] 漏跑 key {_key} 跨日清理(不发恢复邮件)")
            # 同日: 保持 active(窗口外未 seen, 任务可能真漏跑未补)
            continue
        _task = _key.split("|", 1)[0] if "|" in _key else _key
        _kw = _info.get("keyword", "?")
        # A3: 静默窗口检查须在覆盖 last_recovered 之前(用旧值判断)
        _emit = _recovery_cooldown_ok(_key, _info)
        _info["status"] = "recovered"
        _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        if _emit:
            recoveries.append({
                "task": _task,
                "keyword": _kw,
                "first_seen": _info.get("first_seen", "?"),
            })
        else:
            print(
                f"[cooldown] {_task} 恢复邮件静默(上次恢复 <{int(RECOVERY_COOLDOWN.total_seconds() // 3600)}h 前), "
                f"状态已置 recovered 但不发邮件 (首次发现: {_info.get('first_seen')})"
            )
        print(
            f"[recovery] {_task} 异常关键词 {_kw} 已消失 "
            f"(首次发现: {_info.get('first_seen')})"
        )
# 2026-08-24 孤儿告警回收(修 recovered 卡死根因): 72h 监控(monitor_72h.sh)的告警 key
# 由其自身负责恢复检测, 但 72h 到期自停(bootout + rm START_FILE)后无人接管 -> 72h_
# 前缀 active/pending key 永久卡死(生产实证: 72h_r2_prefix_industry_fail /
# 72h_sw_version_mismatch 两条 08-12 起卡 active 至今, 主恢复循环 L628 起
# 显式跳过 72h_ 前缀防振荡, 更不会回收它们)。
# 判定=START_FILE 不存在 且 告警最后动作距今>1h(宽限, 防与刚启动的 72h 会话竞态)
# -> 翻 recovered 静默(不发恢复邮件: 监控停摆不是"异常消失", 发恢复邮件反而误导)。
# START_FILE 生命周期如实描述(2026-08-24 reviewer P3 修注释失实): monitor_72h.sh 只在
# 启动发现缺失时写一次时间戳, 运行期从不重建; 每轮心跳处会 touch 刷新 mtime(防 macOS
# /tmp 对 >=3 天未访问文件的清理把它删掉造成监控还活却被判停摆)。故本判定成立=
# 到期自停时被 rm(正常交接) 或从未启动/被手动清掉且 72h 监控已不再运行。
_72H_START_FILE = Path("/tmp/monitor_72h_start")
if not _72H_START_FILE.exists():
    for _ok, _oinfo in list(alert_state.items()):
        if not isinstance(_oinfo, dict):
            continue
        if not _ok.startswith("72h_") or _oinfo.get("status") not in ("active", "pending"):
            continue
        _o_last = _oinfo.get("last_alerted") or _oinfo.get("first_seen") or ""
        try:
            _o_age_h = (
                NOW - datetime.strptime(_o_last[:16], "%Y-%m-%d %H:%M")
            ).total_seconds() / 3600
        except ValueError:
            _o_age_h = 999.0
        if _o_age_h < 1:
            print(f"[orphan] {_ok} 最后动作距今<1h, 暂不回收(宽限期)")
            continue
        _oinfo["status"] = "recovered"
        _oinfo["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        _oinfo["recovery_reason"] = "orphan_reaped"
        print(
            f"[orphan] {_ok} 72h监控已停摆(START_FILE 不存在), "
            f"孤儿告警回收翻 recovered(静默)"
        )
save_alert_state(alert_state)

# 3) ETF 汪汪队耗时阈值检查（B4 稳定性 2026-07-24）
#    daily 正常 ~140s(2.3min), >300s(5min)告警(进程池退化信号, 如 2026-07-23 2032s 事故)
#    backfill 全量正常 ~15min, >1800s(30min)告警
#    只检查最近 2 小时内的完成行(避免旧超时重复告警, schedule_monitor 每15min跑)
ETF_DAILY_THRESHOLD = 300  # 5min
ETF_BACKFILL_THRESHOLD = 1800  # 30min
ETF_DUR_RE = re.compile(r"\[etf_nt\] (daily|backfill) 完成 (\d+\.?\d*)s")
ETF_DAILY_START_RE = re.compile(r"\[etf_nt\] daily 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
ETF_BACKFILL_START_RE = re.compile(r"\[etf_nt\] backfill 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
etf_log = LOG_DIR / "etf_national_team_launchd.log"
_etf_resolved = resolve_log_path(etf_log)  # #234 甲5: 容忍 .log.gz
if _etf_resolved is not None:
    try:
        with open_log_text(_etf_resolved) as _ef:
            etf_lines = _ef.read().splitlines()
        # 反向找最后一行完成行(只查最近一次跑的耗时)
        for i in range(len(etf_lines) - 1, -1, -1):
            m = ETF_DUR_RE.search(etf_lines[i])
            if m:
                mode, dur = m.group(1), float(m.group(2))
                # 反向找该完成行之前最近的同 mode 开始行
                start_re = ETF_DAILY_START_RE if mode == "daily" else ETF_BACKFILL_START_RE
                start_dt = None
                for j in range(i - 1, -1, -1):
                    m2 = start_re.search(etf_lines[j])
                    if m2:
                        start_dt = datetime.strptime(m2.group(1), "%Y-%m-%d %H:%M:%S")
                        break
                # 只检查最近 2 小时内的(避免旧超时重复告警)
                if start_dt and NOW - start_dt <= timedelta(hours=2):
                    threshold = ETF_DAILY_THRESHOLD if mode == "daily" else ETF_BACKFILL_THRESHOLD
                    if dur > threshold:
                        alerts.append(
                            f"SEVERE: etf_national_team {mode} 耗时 {dur:.0f}s 超阈值 {threshold}s "
                            f"(进程池退化信号) start<{start_dt.strftime('%Y-%m-%d %H:%M:%S')}>"
                        )
                break  # 只查最后一行完成行
    except Exception as e:
        print(f"[warn] ETF 耗时检查失败: {e}", file=sys.stderr)

# 4) 产物时效检查：线上 overview.json collected_at vs NOW
#    intraday push 失败就是线上滞后（schedule_stats 只看任务跑了没，不查产物上线=盲区）。
#    仅交易日盘中 09:50-15:05 检查（intraday 每10min推一次，盘中最后 15:02，盘后 15:35/20:35），
#    09:50 起检避开开盘空窗期 overview.json 仍是凌晨旧版导致的误报；避免非交易时段误报。
#    15:05 上限：15:05 时 intraday 15:02 刚推完（完成~15:05）lag≈0-3min 安全；15:15/15:30 是
#    intraday 空窗期（15:02 已推、15:35 未推）检查必误报，故窗口不含 15:15/15:30。
#    2026-07-20 15:30 误报事故根因：窗口含 15:30，overview 停在 15:02 lag=27min>20min 阈值必报。
#    容错说明（2026-09-14 修假阳性）：原依次试 3 域名容错，但 R2 迁移后备站
#    sss.sugas.site/s.sugas.site 无 data 目录（GH Pages/MaoziYun 部署不含 data/），
#    /data/overview.json 永久 404，主站一超时 404 兜不住 → 3 域名全 lag 误报 SEVERE。
#    故 domains 只留主站 ss.fx8.store（Worker 路径），R2 直连容错由第 6) 节 R2 直连时效检查覆盖
#    （两层独立：R2 stale + Worker stale = upload_r2 断；R2 fresh + Worker stale = CF cache purge 失效）。
#    滞后 > 20min 告警 SEVERE（intraday 10min 频率 + 10min buffer）。
#    curl 超时 25s（subprocess timeout 30s 兜底）：overview.json 1.1MB 正常 5~9s，
#    原 8s 踩线致网络稍慢 curl rc=28 超时假阳性；25s 给足余量不阻塞 launchd 15min 周期。
#    用 /usr/bin/curl 而非 urllib：venv python 缺系统 CA 证书会 SSL 校验失败，curl 走系统证书更稳。
try:
    from app.calendar import is_trading_day
    now_hm = NOW.strftime("%H%M")
    # 0950 起检：intraday 第一次 09:35，dur 约 7min（任务2优化后），09:42 才完成 push。
    # 0930-0942 开盘空窗期 overview.json 必然是凌晨 02:38 旧版，必触发误报。
    # 0950 检查避开空窗，覆盖盘中其余时点（intraday 每 10min 推一次）。
    # 1130-1315 排除午休窗口：A股午休 11:30-13:00 无交易，overview.json collected_at
    # 停在上午 11:30 快照(完成于 ~11:37)，直到 13:05 快照完成(~13:12)才更新。
    # 此窗口内 lag 必然 >20min 但属正常(午休没交易)，排除避免误报。
    # 2026-07-24 12:30 误报事故根因：午休未排除，12:15 起 lag>30min 触发 SEVERE。
    # 非交易日已由 is_trading_day() 排除（周末/节假日 overview 滞后正常）。
    if is_trading_day() and "0950" <= now_hm <= "1505" and not ("1130" <= now_hm < "1315"):
        # 单域名主站检查：CF Workers Static Assets 靠部署自动 purge，但 intraday push
        # main 不触发 CF wrangler redeploy，ss.fx8.store cache 可能滞后；滞后即告警。
        # 只留主站 ss.fx8.store（Worker 路径）：备站 sss.sugas.site/s.sugas.site 自 R2 迁移后
        # 无 data 目录 /data/overview.json 永久 404，删掉防假阳性；R2 直连容错见第 6) 节。
        domains = [
            "https://ss.fx8.store",
        ]
        lag_results = []  # [(domain, collected_at, lag_min, status)]
        all_lag = True
        for base in domains:
            url = f"{base}/data/overview.json"
            try:
                result = subprocess.run(
                    ["/usr/bin/curl", "-sS", "--max-time", "25", url],
                    capture_output=True, text=True, timeout=30,
                )
            except subprocess.TimeoutExpired:
                lag_results.append((base, None, None, "timeout"))
                continue
            if result.returncode != 0:
                lag_results.append((base, None, None, f"curl rc={result.returncode}"))
                continue
            try:
                ov = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                lag_results.append((base, None, None, f"json parse fail: {e}"))
                continue
            collected_at = ov.get("collected_at") or ""
            try:
                collected_dt = datetime.strptime(collected_at, "%Y%m%d %H:%M:%S")
            except ValueError:
                lag_results.append((base, collected_at, None, "collected_at 格式异常"))
                continue
            lag = NOW - collected_dt
            lag_min = int(lag.total_seconds() // 60)
            status = "ok" if lag <= LAG_TOLERANCE else "lag"
            lag_results.append((base, collected_at, lag_min, status))
            if lag <= LAG_TOLERANCE:
                all_lag = False
                print(f"[ok] 线上 overview collected_at={collected_at} lag={lag_min}min (via {base})")
                break
        dedup_key = "overview_lag_3domain"
        now_full = NOW.strftime("%Y-%m-%d %H:%M:%S")
        detail = "; ".join(
            f"{b}={ca or 'N/A'} lag={lm if lm is not None else '?'}min [{st}]"
            for b, ca, lm, st in lag_results
        )
        # #123 R1(2026-10-01): 单次 lag>20min 多为上传间隙瞬时(09-30 14:30 24min 直发 1 封误报),
        # 连续 >=2 轮(30min, 15min/轮)仍滞后才 SEVERE(真断供 30min 内必响)。
        # 复用 r2_intraday_lag 的 buffer 计数模式(schedule_monitor.sh L1572-1605 同构),
        # 判定函数在 scripts/alert_denoise_rules.py:r1_buffer_judge(测试脚本打真实函数)。
        # buffer key 带 YYYYMMDD 防跨天残留(隔日从 0 起)。阈值不动(20min)。
        _ov_buf_key = "overview_lag_3domain|buffer|" + NOW.strftime("%Y%m%d")
        _r1_action = adr.r1_buffer_judge(
            alert_state, _ov_buf_key, dedup_key, all_lag, NOW,
        )
        if _r1_action in ("alert", "buffer", "suppress"):
            seen_keys_this_run.add(dedup_key)
        if _r1_action == "alert":
            # 连续 >=2 轮仍滞后 = 真断供, 发 SEVERE + 写 state
            alerts.append(
                f"SEVERE: 线上 overview.json 时效滞后(主站 ss.fx8.store lag) "
                f"threshold<20min> 连续{adr.OVERVIEW_LAG_CONTINUOUS_THRESHOLD}轮 "
                f"now<{now_full}> 详情: {detail}"
            )
            alert_state[dedup_key] = {
                "status": "active",
                "first_seen": now_full,
                "last_alerted": now_full,
                "keyword": "overview_lag",
                "line_sample": detail,
            }
        elif _r1_action == "buffer":
            _bf = alert_state.get(_ov_buf_key) or {}
            print(f"[overview-lag-buffer] 线上 overview 滞后连续"
                  f"{_bf.get('consecutive_count')}/{adr.OVERVIEW_LAG_CONTINUOUS_THRESHOLD} 轮, "
                  f"暂不通知(单次=上传间隙瞬时)")
        elif _r1_action == "suppress":
            _existing = alert_state.get(dedup_key)
            print(f"[suppress] overview 时效滞后持续中, "
                  f"last_alerted={_existing.get('last_alerted')}, 不重发")
        elif _r1_action == "recover":
            # 时效恢复: was active -> resolved, 发恢复邮件(内联, 不复用 L476 恢复循环
            # 因 overview 检查在恢复循环之后运行, 复用会被误报恢复)
            _existing = alert_state.get(dedup_key)
            _emit = _recovery_cooldown_ok(dedup_key, _existing)
            _existing["status"] = "recovered"
            _existing["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            if _emit:
                recoveries.append({
                    "task": "overview_lag",
                    "keyword": "overview_lag",
                    "first_seen": _existing.get("first_seen", "?"),
                })
            else:
                print(f"[cooldown] overview 时效恢复邮件静默(上次恢复<6h前), 状态已置 recovered")
            print(
                f"[recovery] overview 时效滞后已恢复 "
                f"(首次发现: {_existing.get('first_seen')})"
            )
        # overview 检查在 save_alert_state(L509) 之后运行, 需补存防状态丢失
        save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] 线上 overview.json 时效检查失败: {e}", file=sys.stderr)

# 6) R2 直连时效检查（维度⑥，R2迁移后72h监控 2026-08-08）
#    R2 公开桶(ssd.fx8.store)是前端大文件 + Worker /data/rewrite 的唯一数据源。
#    upload_r2 失败/遗漏 -> R2 数据滞后 -> Worker 60s TTL 过期后仍读 R2 旧版 = 线上滞后。
#    此检查直连 R2 验证 upload_r2 链路:
#    - overview.json collected_at 时效(交易日盘中<20min, 非交易时段<24h防周末断链)
#    - intraday_snapshot.json collected_at 时效(交易日盘中<15min)
#    - R2 可达性(ssd.fx8.store 200响应, R2桶/网络故障告警)
#    告警走 alert_state.json 去重(key=r2_overview_lag/r2_intraday_lag/r2_unreachable),
#    与现有 overview_lag_3domain(Worker路径 ss.fx8.store) 对称, 两层独立检查:
#      R2直连stale + Worker路径stale = upload_r2 断(根因在R2上传)
#      R2直连fresh + Worker路径stale = CF cache purge 失效(根因在Worker缓存)
#    恢复检测: 内联处理(此块在 L476 恢复循环之后运行, 不能复用该循环)。
try:
    R2_BASE = "https://ssd.fx8.store"

    def _parse_flexible_ts(ts_str):
        """解析 overview(YYYYMMDD HH:MM:SS) 或 intraday(ISO T+microsec) 格式时间戳"""
        if not ts_str:
            return None
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return None

    def _curl_r2_json(filename, timeout=20):
        """curl R2 直连获取 JSON body, 返回 (data_dict, error_str)"""
        url = f"{R2_BASE}/data/{filename}"
        try:
            result = subprocess.run(
                ["/usr/bin/curl", "-sS", "--max-time", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 4,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        if result.returncode != 0:
            return None, f"curl rc={result.returncode}"
        try:
            return json.loads(result.stdout), None
        except json.JSONDecodeError as e:
            return None, f"json parse fail: {e}"

    now_hm_r2 = NOW.strftime("%H%M")
    is_r2_trading_window = (
        _is_today_trading and "0950" <= now_hm_r2 <= "1505"
        and not ("1130" <= now_hm_r2 < "1315")
    )

    # --- R2 可达性 + overview 时效 ---
    ov_data_r2, ov_err_r2 = _curl_r2_json("overview.json")
    if ov_err_r2:
        # R2 不可达（网络/R2桶故障/upload_r2 完全断）
        _r2_key = "r2_unreachable"
        seen_keys_this_run.add(_r2_key)
        _ex_r2 = alert_state.get(_r2_key)
        if _ex_r2 is None or _ex_r2.get("status") == "recovered":
            alert_state[_r2_key] = {
                "status": "pending",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": None,
                "consecutive_count": 1,
                "keyword": "r2_unreachable",
                "line_sample": ov_err_r2,
                "tier": "self_heal",
            }
            print(f"[self_heal pending] R2 直连不可达(自愈类), 连续1/{SELF_HEAL_THRESHOLD}, 暂不通知")
        elif _ex_r2.get("status") == "pending":
            _r2_count = _ex_r2.get("consecutive_count", 0) + 1
            if _r2_count >= SELF_HEAL_THRESHOLD:
                alerts.append(
                    f"SEVERE: R2 直连不可达 ssd.fx8.store/data/overview.json "
                    f"error<{ov_err_r2}> now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> "
                    f"(R2桶/网络故障, upload_r2 链路断)"
                )
                _ex_r2["status"] = "active"
                _ex_r2["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                _ex_r2["consecutive_count"] = _r2_count
                print(f"[self_heal escalated] R2 直连不可达连续{_r2_count}次, 发送告警")
            else:
                _ex_r2["consecutive_count"] = _r2_count
                print(f"[self_heal pending] R2 直连不可达, 连续{_r2_count}/{SELF_HEAL_THRESHOLD}, 暂不通知")
        elif _ex_r2.get("status") == "active":
            print(f"[suppress] R2 直连不可达持续中, "
                  f"last_alerted={_ex_r2.get('last_alerted')}, 不重发")
    else:
        # R2 可达 -> 恢复检测(r2_unreachable)
        _ex_r2u = alert_state.get("r2_unreachable")
        if _ex_r2u is not None:
            if _ex_r2u.get("status") == "active":
                # A3: 静默窗口
                _emit = _recovery_cooldown_ok("r2_unreachable", _ex_r2u)
                _ex_r2u["status"] = "recovered"
                _ex_r2u["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                if _emit:
                    recoveries.append({
                        "task": "r2_unreachable", "keyword": "r2_unreachable",
                        "first_seen": _ex_r2u.get("first_seen", "?"),
                    })
                else:
                    print(f"[cooldown] r2_unreachable 恢复邮件静默(上次恢复<30min前)")
                print(f"[recovery] R2 直连不可达已恢复 "
                      f"(首次发现: {_ex_r2u.get('first_seen')})")
            elif _ex_r2u.get("status") == "pending":
                _ex_r2u["status"] = "recovered"
                _ex_r2u["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[silent recovery] R2 直连不可达已恢复(未通知过)")

        # overview collected_at 时效 (M1: 非交易日跳过, 对齐 overview_lag_3domain 只交易日;
        # 原非交易时段24h阈值致周五20:35->周六24h+1min误报持续到周一)
        ov_collected_r2 = ov_data_r2.get("collected_at") or ""
        ov_dt_r2 = _parse_flexible_ts(ov_collected_r2)
        if ov_dt_r2 and _is_today_trading:
            ov_lag_r2 = NOW - ov_dt_r2
            ov_lag_min_r2 = int(ov_lag_r2.total_seconds() // 60)
            # 交易日盘中 20min(同 overview_lag_3domain), 交易日非盘中 24h(防盘后断链)
            ov_thresh_r2 = timedelta(minutes=20) if is_r2_trading_window else timedelta(hours=24)
            # #123 R1(2026-10-01): r2_overview_lag 同 overview_lag_3domain 加连续轮——
            # 单次 lag 多为上传间隙瞬时(09-30 14:30 与主站同源 1 封误报), 连续 >=2 轮仍滞后才
            # SEVERE(真断供 30min 内必响)。buffer 带 YYYYMMDD 防跨天残留。判定函数
            # scripts/alert_denoise_rules.py:r1_buffer_judge(与主站块同构, 测试脚本打真实函数)。
            _r2_ov_key = "r2_overview_lag"
            _r2_ov_buf = "r2_overview_lag|buffer|" + NOW.strftime("%Y%m%d")
            if ov_lag_r2 > ov_thresh_r2:
                _r2_ov_act = adr.r1_buffer_judge(
                    alert_state, _r2_ov_buf, _r2_ov_key, True, NOW,
                )
                if _r2_ov_act in ("alert", "buffer", "suppress"):
                    seen_keys_this_run.add(_r2_ov_key)
                _thresh_min = int(ov_thresh_r2.total_seconds() // 60)
                if _r2_ov_act == "alert":
                    # 连续 >=2 轮仍滞后 = 真断供, 发 SEVERE + 写 state
                    alerts.append(
                        f"SEVERE: R2 overview.json 时效滞后 "
                        f"collected_at<{ov_collected_r2}> lag={ov_lag_min_r2}min "
                        f"threshold<{_thresh_min}min> "
                        f"连续{adr.OVERVIEW_LAG_CONTINUOUS_THRESHOLD}轮 "
                        f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> (upload_r2 未推新版)"
                    )
                    alert_state[_r2_ov_key] = {
                        "status": "active",
                        "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "keyword": "r2_overview_lag",
                        "line_sample": f"lag={ov_lag_min_r2}min collected_at={ov_collected_r2}",
                    }
                elif _r2_ov_act == "buffer":
                    _bf_r2o = alert_state.get(_r2_ov_buf) or {}
                    print(f"[r2-ov-lag-buffer] R2 overview 滞后连续"
                          f"{_bf_r2o.get('consecutive_count')}/{adr.OVERVIEW_LAG_CONTINUOUS_THRESHOLD} 轮, "
                          f"暂不通知(单次=上传间隙瞬时)")
                elif _r2_ov_act == "suppress":
                    _ex_r2ov = alert_state.get(_r2_ov_key)
                    print(f"[suppress] R2 overview 滞后持续中, "
                          f"last_alerted={_ex_r2ov.get('last_alerted')}, 不重发")
            else:
                # 恢复检测(r1_buffer_judge 内部已清 buffer)
                _r2_ov_act = adr.r1_buffer_judge(
                    alert_state, _r2_ov_buf, _r2_ov_key, False, NOW,
                )
                if _r2_ov_act == "recover":
                    _ex_r2ov = alert_state.get("r2_overview_lag")
                    # A3: 静默窗口
                    _emit = _recovery_cooldown_ok("r2_overview_lag", _ex_r2ov)
                    _ex_r2ov["status"] = "recovered"
                    _ex_r2ov["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                    if _emit:
                        recoveries.append({
                            "task": "r2_overview_lag", "keyword": "r2_overview_lag",
                            "first_seen": _ex_r2ov.get("first_seen", "?"),
                        })
                    else:
                        print(f"[cooldown] r2_overview_lag 恢复邮件静默(上次恢复<6h前)")
                    print(f"[recovery] R2 overview 时效滞后已恢复 "
                          f"(首次发现: {_ex_r2ov.get('first_seen')})")

    # --- intraday_snapshot 时效（仅交易日盘中, 同 overview 窗口）---
    if is_r2_trading_window:
        id_data_r2, id_err_r2 = _curl_r2_json("intraday_snapshot.json")
        if id_err_r2:
            print(f"[warn] R2 intraday_snapshot 不可达: {id_err_r2} "
                  f"(盘中才检查, 非致命)", file=sys.stderr)
        elif id_data_r2:
            id_collected_r2 = id_data_r2.get("collected_at") or ""
            id_dt_r2 = _parse_flexible_ts(id_collected_r2)
            if id_dt_r2:
                id_lag_r2 = NOW - id_dt_r2
                id_lag_min_r2 = int(id_lag_r2.total_seconds() // 60)
                id_thresh_r2 = timedelta(minutes=20)
                # 2026-09-29 复审(次要项4): buffer 计数 key 加日期维度, 防跨天残留
                # (昨日累计 pending count=2 残留, 今日首轮滞后 +1=3 直接误 SEVERE;
                # 「连续3轮≈45min」判定不会跨天, 隔日应重新从 0 计数)。定义在 if/else 外,
                # 恢复分支(本轮无 lag)也引用同 key。
                _r2_buf_key = "r2_intraday_lag|buffer|" + NOW.strftime("%Y%m%d")
                if id_lag_r2 > id_thresh_r2:
                    _r2_id_key = "r2_intraday_lag"
                    seen_keys_this_run.add(_r2_id_key)
                    _ex_r2id = alert_state.get(_r2_id_key)
                    # 2026-09-29 告警降噪(改动1): 单次 lag>20min 多为上传间隙瞬时滞后
                    # (09-28 13:45/14:15 各 1 封=检查落在上传间隙), 连续 >=3 轮(≈45min,
                    # 15min/轮)仍滞后才 SEVERE=R2 真断供。参照 marker_buffer 计数:
                    # 独立 buffer key 记连续轮次, 达标才写告警 key active(发 SEVERE);
                    # 未达标只打 [r2-lag-buffer] 不通知(历史告警 key 不 active 不恢复)。
                    _r2id_bf = alert_state.get(_r2_buf_key) or {}
                    _bf_st = _r2id_bf.get("status")
                    if _bf_st == "alerted":
                        _r2id_c = R2_LAG_CONTINUOUS_THRESHOLD
                    else:
                        _r2id_c = (_r2id_bf.get("consecutive_count") or 0) + 1
                    alert_state[_r2_buf_key] = {
                        "status": "alerted" if _r2id_c >= R2_LAG_CONTINUOUS_THRESHOLD else "pending",
                        "first_seen": _r2id_bf.get("first_seen") or NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "consecutive_count": _r2id_c,
                        "keyword": "r2_intraday_lag",
                        "line_sample": f"lag={id_lag_min_r2}min collected_at={id_collected_r2}",
                    }
                    if _r2id_c < R2_LAG_CONTINUOUS_THRESHOLD:
                        print(
                            f"[r2-lag-buffer] R2 intraday 滞后连续{_r2id_c}/"
                            f"{R2_LAG_CONTINUOUS_THRESHOLD} 轮, 暂不通知(单次=上传间隙瞬时)"
                        )
                    elif _ex_r2id is None or _ex_r2id.get("status") != "active":
                        alerts.append(
                            f"SEVERE: R2 intraday_snapshot.json 时效滞后 "
                            f"collected_at<{id_collected_r2}> lag={id_lag_min_r2}min "
                            f"threshold<20min> 连续{R2_LAG_CONTINUOUS_THRESHOLD}轮"
                            f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> "
                            f"(upload-intraday 未推新版)"
                        )
                        alert_state[_r2_id_key] = {
                            "status": "active",
                            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": "r2_intraday_lag",
                            "line_sample": f"lag={id_lag_min_r2}min collected_at={id_collected_r2}",
                        }
                    else:
                        print(f"[suppress] R2 intraday 滞后持续中, "
                              f"last_alerted={_ex_r2id.get('last_alerted')}, 不重发")
                else:
                    # 恢复检测
                    _ex_r2id = alert_state.get("r2_intraday_lag")
                    if _ex_r2id is not None and _ex_r2id.get("status") == "active":
                        # A3: 静默窗口
                        _emit = _recovery_cooldown_ok("r2_intraday_lag", _ex_r2id)
                        _ex_r2id["status"] = "recovered"
                        _ex_r2id["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                        if _emit:
                            recoveries.append({
                                "task": "r2_intraday_lag", "keyword": "r2_intraday_lag",
                                "first_seen": _ex_r2id.get("first_seen", "?"),
                            })
                        else:
                            print(f"[cooldown] r2_intraday_lag 恢复邮件静默(上次恢复<30min前)")
                        print(f"[recovery] R2 intraday 时效滞后已恢复 "
                              f"(首次发现: {_ex_r2id.get('first_seen')})")
                    # 本轮已恢复 = 连续链中断, 清 buffer 计数(防跨窗口残留计数误升级:
                    # 若不重置, 恢复前累计到 2 的 consecutive_count 会在下次单次滞后时 +1=3 直接误 SEVERE;
                    # 用当日 key(_r2_buf_key 已在 if 分支定义, 恢复分支同 key → 隔日自动从 0 起)
                    _r2id_bf_r = alert_state.get(_r2_buf_key)
                    if _r2id_bf_r and _r2id_bf_r.get("status") in ("pending", "alerted"):
                        alert_state[_r2_buf_key] = {
                            **_r2id_bf_r, "status": "recovered",
                            "consecutive_count": 0,
                            "recovered_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        }

    # R2 检查在 save_alert_state(L509/L660) 之后运行, 需补存防状态丢失
    save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] R2 直连时效检查失败: {e}", file=sys.stderr)

# 7) 飞书配置检查（维度⑦，2026-08-17 三件套①核心）
#    防 config/feishu.json 丢失致飞书静默停摆数天（send_feishu 缺失直接 return False 静默跳过；
#    listener 每 10s 报"feishu.json 不存在"但无告警，用户数天后才发现）。
#    两个触发面：
#      a) config/feishu.json 不存在 且 .env 有 FEISHU_APP_ID/FEISHU_APP_SECRET
#         （=配置本该存在却异常丢失；全新环境未配置 .env 无凭证不告警防误报）
#      b) feishu_listener.err 尾部 10 条内含"feishu.json 不存在"（listener 场景不调 send_feishu，
#         靠本 15min 周期监控兜底发现）
#    复用 alert_state.json 去重（key=feishu_config_missing，key 前缀 feishu_ 已加入主恢复循环
#    特殊跳过，inline 处理恢复，与 r2_ 同模式防振荡）。
try:
    _feishu_cfg_path = REPO / "config" / "feishu.json"
    _feishu_cfg_missing = not _feishu_cfg_path.exists()
    # .env 是否有 FEISHU 凭证（区分配置丢失 vs 全新环境未配置）
    _feishu_env_has_cred = False
    for _env_path in (Path("/Users/linhuichen/code/trade-data/.env"), REPO / ".env"):
        if not _env_path.exists():
            continue
        try:
            _env_lines = _env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for _ln in _env_lines:
            _ln = _ln.strip()
            if _ln.startswith("FEISHU_APP_ID=") or _ln.startswith("FEISHU_APP_SECRET="):
                _feishu_env_has_cred = True
                break
        if _feishu_env_has_cred:
            break
    # feishu_listener.err 尾部 10 条是否含"feishu.json 不存在"（listener 停摆信号）
    _feishu_err_missing = False
    _feishu_err_path = LOG_DIR / "feishu_listener.err"
    _feishu_err_resolved = resolve_log_path(_feishu_err_path)  # #234 甲5: 容忍 .log.gz
    if _feishu_err_resolved is not None:
        try:
            with open_log_text(_feishu_err_resolved) as _few:
                _tail_lines = _few.read().splitlines()[-10:]
            if any("feishu.json 不存在" in _l for _l in _tail_lines):
                _feishu_err_missing = True
        except Exception:
            _feishu_err_missing = False
    _feishu_key = "feishu_config_missing"
    _feishu_issue = None
    if _feishu_cfg_missing and _feishu_env_has_cred:
        _feishu_issue = ("config/feishu.json 缺失 且 .env 有 FEISHU 凭证"
                         "（配置丢失，飞书通知已静默停摆）")
    elif _feishu_err_missing:
        _feishu_issue = ("feishu_listener.err 尾部报 config/feishu.json 不存在"
                         "（listener 已停摆）")
    if _feishu_issue:
        seen_keys_this_run.add(_feishu_key)
        _ex_fs = alert_state.get(_feishu_key)
        if _ex_fs is None or _ex_fs.get("status") != "active":
            alerts.append(
                f"SEVERE: {_feishu_issue}。恢复：cp config/feishu.json.example "
                "config/feishu.json 后 launchctl kickstart -k gui/$(id -u)/com.trade.feishu-listener"
            )
            alert_state[_feishu_key] = {
                "status": "active",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": "feishu_config_missing",
                "line_sample": ("feishu_listener.err" if _feishu_err_missing
                                else str(_feishu_cfg_path)),
            }
        else:
            print(f"[suppress] 飞书配置缺失持续中, "
                  f"last_alerted={_ex_fs.get('last_alerted')}, 不重发")
    else:
        # 恢复检测（inline，与 r2_ 同模式）：异常已消失 -> 发恢复邮件
        _ex_fs = alert_state.get(_feishu_key)
        if _ex_fs is not None and _ex_fs.get("status") == "active":
            _emit = _recovery_cooldown_ok(_feishu_key, _ex_fs)
            _ex_fs["status"] = "recovered"
            _ex_fs["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            if _emit:
                recoveries.append({
                    "task": "feishu_config", "keyword": "feishu_config_missing",
                    "first_seen": _ex_fs.get("first_seen", "?"),
                })
            else:
                print(f"[cooldown] feishu_config_missing 恢复邮件静默(上次恢复<30min前)")
            print(f"[recovery] 飞书配置缺失已恢复 (首次发现: {_ex_fs.get('first_seen')})")
    # 飞书检查在 save_alert_state(L509/L660) 之后运行, 需补存防状态丢失
    save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] 飞书配置检查失败: {e}", file=sys.stderr)

# 8) 飞书 hook 心跳自检（维度⑧，2026-08-17 #25）
#    防 feishu_chat_hook 静默停摆（hook 判定 bug/配置丢失 → hook 静默跳过/发送失败 →
#    用户发消息无回显且无任何告警，坏几天才发现；与维度⑦ feishu.json 缺失检测互补——
#    ⑦ 覆盖"配置丢失"，本维度覆盖"hook 未接线/未触发"）。
#    hook 每次被调用在 /tmp/feishu_hook_heartbeat 更新 mtime（见 feishu_chat_hook.py main）。
#    判定：Claude Code 会话活跃但心跳缺失或 >90min 陈旧 → 告警。
#    [2026-09-09 #84 C3 降噪] 会话活跃判定由「pgrep claude 有进程」改为「~/.claude/projects/
#    **/*.jsonl 最近 mtime」，根因：claude bg-spare/bg-pty-host 常驻 daemon 进程 24h 挂着，
#    pgrep 恒有 pid → 无用户会话活动时段(深夜/周末)心跳陈旧 = 假阳性 SEVERE(schedule_monitor_
#    launchd.log 09-09 03:00 first_seen，7 天 12 封「suppress/恢复 feishu_hb」对)；jsonl = Claude
#    Code 会话实时追加的最后活动时间戳，更贴近「用户真在用」。
#    三层判定：
#      a) 会话活跃期(session 90min 内有用过) 且 心跳陈旧/缺失 → SEVERE(真断，hook 该触发没触发)
#      b) 会话不活跃(用户暂时没用) 且 心跳陈旧 → 降级 warn 只记日志不发邮件(预期，假阳性消除)
#      c) 极长时间无会话活动(>7 天 jsonl 无新增) 且 claude 进程存活 且 心跳缺失/陈旧 →
#         环境疑似彻底停摆，仍 SEVERE(「心跳真断(长时间无任何活动)仍要报」)
#    防误报：心跳文件缺失时(刚开机/刚清 /tmp)，额外要求 claude 进程存活 >30min 才计较。
#    复用 alert_state.json 去重（key=feishu_hb_stale，key 前缀 feishu_ 已加入主恢复循环
#    特殊跳过，inline 处理恢复，与维度⑦同模式）。
try:
    _hb_path = Path("/tmp/feishu_hook_heartbeat")
    # claude 进程采集(仅用于 c 层兜底 + 缺失时防误报的进程判定, 不再直接当"会话活跃")
    _hb_claude_pids = []
    try:
        _hb_pgrep = subprocess.run(["pgrep", "-f", "claude"],
                                   capture_output=True, text=True, timeout=10)
        _hb_claude_pids = [p for p in _hb_pgrep.stdout.split() if p]
    except Exception as _e:
        _hb_claude_pids = []
    # 会话活跃判定(#84 C3)：~/.claude/projects/**/*.jsonl 最近 mtime
    #   jsonl 会话实时追加<mtime 即最后活动>；扫描异常退化用旧 pgrep 判定(保守不清误报也降级过判)
    _hb_session_active = False
    _hb_long_inactive = False
    _hb_session_last = None
    try:
        _hb_proj = Path.home() / ".claude" / "projects"
        _hb_newest = 0.0
        if _hb_proj.exists():
            for _p in _hb_proj.glob("*/*.jsonl"):
                try:
                    _mt = _p.stat().st_mtime
                    if _mt > _hb_newest:
                        _hb_newest = _mt
                except Exception:
                    pass
        if _hb_newest > 0:
            _hb_session_last = datetime.fromtimestamp(_hb_newest)
            _hb_session_active = (NOW.timestamp() - _hb_newest) < 5400   # 90min 与心跳同窗口
            _hb_long_inactive = (NOW.timestamp() - _hb_newest) > 7 * 86400  # >7 天完全无活动
        else:
            _hb_long_inactive = True  # 无任何 jsonl(projects 目录空/不存在)= 无法确认活跃
    except Exception:
        _hb_session_active = bool(_hb_claude_pids)  # 退化: 扫描异常回旧 pgrep 判定
        _hb_long_inactive = False
    # 心跳新鲜度：文件存在则 mtime(BSD %m)距当前 <90min = 新鲜
    _hb_fresh = False
    _hb_missing = False
    if _hb_path.exists():
        try:
            _hb_mtime = _hb_path.stat().st_mtime
            _hb_fresh = (NOW.timestamp() - _hb_mtime) < 5400  # 90min
        except Exception:
            _hb_missing = True
    else:
        _hb_missing = True
    # 防误报：文件缺失时额外要求 claude 进程存活 >30min（刚开机/刚清 /tmp 不误报）
    _hb_old_proc = False
    if _hb_missing and _hb_claude_pids:
        try:
            _hb_proc = subprocess.run(
                ["ps", "-o", "lstart=", "-p", _hb_claude_pids[0]],
                capture_output=True, text=True, timeout=10)
            _hb_lstart_str = _hb_proc.stdout.strip()
            if _hb_lstart_str:
                # BSD ps lstart 格式：Mon Aug 17 10:30:00 2026
                _hb_lstart = datetime.strptime(_hb_lstart_str, "%a %b %d %H:%M:%S %Y")
                _hb_old_proc = (NOW - _hb_lstart) > timedelta(minutes=30)
        except Exception:
            _hb_old_proc = False
    # 告警条件(#84 C3 三层判定)：
    #   心跳异常(陈旧 或 缺失且进程存活>30min) 为前提；
    #   a) session 活跃(90min 内有用过) → SEVERE(真断)
    #   c) 极长时间无活动(>7 天) 且 claude 进程存活 → SEVERE(长时间无任何活动仍要报)
    #   b) 其余(会话不活跃，用户暂时没用) → 降级 warn 只记日志不发邮件(假阳性消除)
    _hb_hb_bad = (not _hb_fresh) and (_hb_old_proc or not _hb_missing)
    _hb_active_use = _hb_session_active or (_hb_long_inactive and bool(_hb_claude_pids))
    _hb_alert = _hb_hb_bad and _hb_active_use
    _hb_key = "feishu_hb_stale"
    _hb_reason = ""
    if _hb_missing:
        _hb_reason = "心跳文件缺失"
    else:
        _hb_reason = "心跳陈旧"
    if _hb_alert:
        seen_keys_this_run.add(_hb_key)
        _ex_hb = alert_state.get(_hb_key)
        if _ex_hb is None or _ex_hb.get("status") != "active":
            # a) 会话活跃期真断 / c) 极长时间无活动兜底; b) 会话不活跃已下方降级 warn, 不进这里
            _hb_ctx = "Claude Code 会话活跃" if _hb_session_active else "极长时间无会话活动(>7天)"
            alerts.append(
                f"SEVERE: 飞书 hook 心跳自检（{_hb_reason}，{_hb_ctx}但 hook "
                f"超90min未触发）。影响：飞书抄送可能静默停摆，用户消息无回显且无告警。"
                f"恢复：确认 .claude/settings.json 的 UserPromptSubmit/Stop hooks 指向 "
                f"scripts/feishu_chat_hook.py 且脚本无报错；或重启 Claude Code 会话"
            )
            alert_state[_hb_key] = {
                "status": "active",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": "feishu_hb_stale",
                "line_sample": "feishu_hook_heartbeat 心跳陈旧/缺失",
            }
        else:
            print(f"[suppress] 飞书 hook 心跳陈旧持续中, "
                  f"last_alerted={_ex_hb.get('last_alerted')}, 不重发")
    else:
        if _hb_hb_bad:
            # b) 心跳仍异常但会话不活跃(用户暂时没用)= 预期, 降级 warn 只记日志不发邮件(#84 C3)
            #    且不判"已恢复"(hook 可能仍坏着, 防降级期误发恢复邮件); active 状态保持等真恢复
            print(f"[warn] 飞书 hook 心跳{_hb_reason}但无会话活跃"
                  f"(最后活动={_hb_session_last or '无 jsonl'}), 属预期(用户未使用), 不告警(#84 C3 降噪)")
        else:
            # 恢复检测（inline，与维度⑦同模式）：心跳真恢复(fresh) -> 发恢复邮件
            _ex_hb = alert_state.get(_hb_key)
            if _ex_hb is not None and _ex_hb.get("status") == "active":
                _emit = _recovery_cooldown_ok(_hb_key, _ex_hb)
                _ex_hb["status"] = "recovered"
                _ex_hb["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                if _emit:
                    recoveries.append({
                        "task": "feishu_hb", "keyword": "feishu_hb_stale",
                        "first_seen": _ex_hb.get("first_seen", "?"),
                    })
                else:
                    print(f"[cooldown] feishu_hb_stale 恢复邮件静默(上次恢复<30min前)")
                print(f"[recovery] 飞书 hook 心跳已恢复 (首次发现: {_ex_hb.get('first_seen')})")
    # 飞书心跳检查在 save_alert_state(L660) 之后运行, 需补存防状态丢失（同维度⑦）
    save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] 飞书 hook 心跳自检失败: {e}", file=sys.stderr)

# 9) 飞书 ws listener 接收侧静默假死心跳探测（维度⑨，2026-08-17 researcher #25 缺口 A）
#    防 feishu_ws_listener 半死：进程在+ws 连接在但收不到事件时，KeepAlive 和 auto_reconnect
#    都发现不了（用户群消息没回执没落盘且无告警，坏几天才发现）。
#    listener 每次成功处理事件在 /tmp/feishu_ws_last_event 更新 mtime（见 feishu_ws_listener.py
#    _touch_ws_last_event）。判定：listener 进程在跑 但 心跳缺失或 >24h 陈旧 → 告警。
#    阈值 24h：需求群低频，夜间/周末无消息正常，不能用 hook 的 90min 短阈值（必误报）。
#    防误报：心跳文件缺失时(刚重启/刚清 /tmp)，额外要求 listener 进程存活 >30min 才告警（同维度⑧）。
#    走 notify.py 邮件告警（monitor 统一出口），不依赖飞书自身发送（防"飞书挂了告警发不出去"）。
#    进程崩了由 launchd KeepAlive 自动拉起（不算 stale 告警范畴）；若进程彻底不在且不在被
#    KeepAlive 拉（重启窗口外），此亦为异常——但以半死为主告警，进程缺失由其他维度/KeepAlive 覆盖。
#    复用 alert_state.json 去重（key=feishu_ws_stale，key 前缀 feishu_ 已加入主恢复循环
#    特殊跳过，inline 处理恢复，与维度⑦/⑧同模式）。
try:
    _ws_path = Path("/tmp/feishu_ws_last_event")
    # listener 进程在跑判定：pgrep -f feishu_ws_listener.py（monitor 自身是 bash，无自匹配）
    _ws_listener_pids = []
    try:
        _ws_pgrep = subprocess.run(["pgrep", "-f", "feishu_ws_listener.py"],
                                   capture_output=True, text=True, timeout=10)
        _ws_listener_pids = [p for p in _ws_pgrep.stdout.split() if p]
    except Exception:
        _ws_listener_pids = []
    _ws_running = bool(_ws_listener_pids)
    # 心跳新鲜度：文件存在则 mtime 距当前 <24h = 新鲜（86400s）
    _ws_fresh = False
    _ws_missing = False
    if _ws_path.exists():
        try:
            _ws_mtime = _ws_path.stat().st_mtime
            _ws_fresh = (NOW.timestamp() - _ws_mtime) < 86400  # 24h
        except Exception:
            _ws_missing = True
    else:
        _ws_missing = True
    # 防误报：文件缺失时额外要求 listener 进程存活 >30min（刚重启/刚清 /tmp 不误报）
    _ws_old_proc = False
    if _ws_missing and _ws_listener_pids:
        try:
            _ws_proc = subprocess.run(
                ["ps", "-o", "lstart=", "-p", _ws_listener_pids[0]],
                capture_output=True, text=True, timeout=10)
            _ws_lstart_str = _ws_proc.stdout.strip()
            if _ws_lstart_str:
                _ws_lstart = datetime.strptime(_ws_lstart_str, "%a %b %d %H:%M:%S %Y")
                _ws_old_proc = (NOW - _ws_lstart) > timedelta(minutes=30)
        except Exception:
            _ws_old_proc = False
    # 告警条件：listener 进程在跑 + (陈旧 或 (缺失且进程存活>30min))
    _ws_alert = _ws_running and (not _ws_fresh) and (_ws_old_proc or not _ws_missing)
    _ws_key = "feishu_ws_stale"
    _ws_reason = ""
    if _ws_missing:
        _ws_reason = "心跳文件缺失"
    else:
        _ws_reason = "心跳陈旧(>24h 无事件)"
    if _ws_alert:
        seen_keys_this_run.add(_ws_key)
        _ex_ws = alert_state.get(_ws_key)
        # 2026-08-24 人工确认抑制(acknowledged 字段): 用户已知悉并人工核实后
        # (scripts/alert_ack.py feishu_ws_stale 写入时间戳), 24h 内不重复 SEVERE,
        # 只记 dashboard + 每小时一条 info 级日志; 超 24h 未恢复则恢复提醒。
        # 场景=周末/假期无群消息属正常, 人工核实连接健康后免 24h 阈值的持续轰炸。
        _ack_ok = False
        if isinstance(_ex_ws, dict) and _ex_ws.get("acknowledged"):
            try:
                _ack_dt = datetime.strptime(
                    str(_ex_ws["acknowledged"])[:16], "%Y-%m-%d %H:%M"
                )
                _ack_ok = (NOW - _ack_dt) < timedelta(hours=24)
            except ValueError:
                _ack_ok = False
        if _ack_ok:
            print(
                f"[ack] feishu_ws_stale 已于 {_ex_ws['acknowledged']} 人工确认, "
                f"24h 内不重复告警(当前: {_ws_reason})"
            )
            _last_ack_log = _ex_ws.get("last_ack_log") or ""
            try:
                _need_info_log = (
                    not _last_ack_log
                    or (NOW - datetime.strptime(_last_ack_log[:16], "%Y-%m-%d %H:%M"))
                    >= timedelta(hours=1)
                )
            except ValueError:
                _need_info_log = True
            if _need_info_log:
                _ex_ws["last_ack_log"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                try:
                    subprocess.run(
                        [
                            sys.executable, str(REPO / "scripts" / "notify.py"),
                            "飞书ws心跳陈旧(已人工确认,静默中)",
                            f"feishu_ws_stale 持续({_ws_reason}); "
                            f"已于 {_ex_ws.get('acknowledged')} 人工确认, "
                            f"确认后 24h 内静默",
                            "--tier", "info",
                        ],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                except Exception:
                    pass
        elif _ex_ws is None or _ex_ws.get("status") != "active":
            alerts.append(
                f"SEVERE: 飞书 ws listener 接收侧静默假死（{_ws_reason}，进程在跑但超24h "
                f"未成功处理任何事件）。影响：用户群消息可能收不到——无回执无落盘且无告警。"
                f"恢复：查 {LOG_DIR}/feishu_listener.log 确认 ws 连接/事件；必要时 "
                f"launchctl kickstart -k gui/$(id -u)/com.trade.feishu-listener 重启监听"
            )
            alert_state[_ws_key] = {
                "status": "active",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "keyword": "feishu_ws_stale",
                "line_sample": "feishu_ws_last_event 心跳陈旧/缺失",
            }
        else:
            print(f"[suppress] 飞书 ws listener 心跳陈旧持续中, "
                  f"last_alerted={_ex_ws.get('last_alerted')}, 不重发")
    else:
        # 恢复检测（inline，与维度⑦/⑧同模式）：异常已消失 -> 发恢复邮件
        _ex_ws = alert_state.get(_ws_key)
        if _ex_ws is not None and _ex_ws.get("status") == "active":
            _emit = _recovery_cooldown_ok(_ws_key, _ex_ws)
            _ex_ws["status"] = "recovered"
            _ex_ws["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            if _emit:
                recoveries.append({
                    "task": "feishu_ws", "keyword": "feishu_ws_stale",
                    "first_seen": _ex_ws.get("first_seen", "?"),
                })
            else:
                print(f"[cooldown] feishu_ws_stale 恢复邮件静默(上次恢复<30min前)")
            print(f"[recovery] 飞书 ws listener 心跳已恢复 (首次发现: {_ex_ws.get('first_seen')})")
    # 维度⑨在 save_alert_state(L660) 之后运行, 需补存防状态丢失（同维度⑦/⑧）
    save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] 飞书 ws listener 心跳自检失败: {e}", file=sys.stderr)

# B2 告警正文模板化（2026-08-14 告警优化）: 原正文=纯 SEVERE 行列表, 改为每项 4 行模板
#   [严重度] 任务 异常类型 / 影响:XX / 日志:路径 / 建议:XX。按任务写对应影响与建议。
_IMPACT_MAP = {
    "update_all": "全站 overview/评分/预警/ETF清单等数据可能过期或未更新, 前端读到旧版",
    "turnover_backfill": "换手率分布(a_turnover_*)当日数据可能缺失, 首页折叠区/A股走势图换手率读 T-1",
    "backfill_evening": "回填数据(指数/分红等)可能缺失或未更新, 前端对应指标读旧",
    "intraday_snapshot": "盘中 overview/intraday 快照可能过期, 前端分时/实时数据读旧",
    "futures_backfill": "期货数据可能缺失或未更新, 前端期货指标读旧",
    "lhb_backfill": "龙虎榜数据可能缺失或未更新, 前端对应展示读旧",
    "rzhb_backfill": "两融数据可能缺失或未更新, 前端对应展示读旧",
    "etf_national_team": "汪汪队 ETF 数据可能过期或未更新, 前端 ETF 板块读旧",
    "lab_auto": "策略实验室回测数据可能未更新, 前端实验室读旧",
    "us_stock_morning": "美股数据可能缺失或未更新, 前端美股指标读旧",
    "overview": "线上 overview.json 时效滞后, 前端首页可能读到旧数据",
    "R2": "R2 存储(ssd.fx8.store)不可达或数据未推新版, 前端大文件/rewrite 数据源断或读旧",
    "主机磁盘": "主机磁盘超 90%, 继续增长将写满 -> 日志/产物/DB 写入失败, 告警邮件自身也可能发不出(静默失联)",
    "主机inode": "inode 耗尽(小文件数超限), 与磁盘写满同效: 新文件(日志/JSON/WAL)创建失败, 报 'No space left on device'",
    "主机内存": "可用内存 <10%, 逼近 OOM -> 采集/导出/回测进程可能被内核 kill, 表现为任务随机中断(exit=137/143)",
    "主机swap": "swap 接近耗尽, 内存压力已到极限(紧随其后常是 OOM kill); I/O 抖动亦拖慢所有任务",
}
_SUGGEST_MAP = {
    "update_all": "自动恢复中; 若持续(超时告警)请人工查 update_all 进程/卡死点",
    "turnover_backfill": "自动恢复中; 若持续请人工查 turnover_backfill/baostock 采集是否被封禁(10001011)",
    "backfill_evening": "自动恢复中; 若持续请人工检查回填进程",
    "intraday_snapshot": "自动恢复中; 若持续请人工检查盘中采集/push 链路",
    "etf_national_team": "自动恢复中; 若持续(进程池退化)请人工检查",
    "overview": "自动恢复中; 若持续请人工查 intraday/push 链路",
    "R2": "自动恢复中; 若持续请人工查 upload_r2/网络/R2 桶",
    "feishu_config": "恢复：cp config/feishu.json.example config/feishu.json 后 launchctl kickstart com.trade.feishu-listener; 持续缺失=配置被删需重建",
    "主机磁盘": "立即清日志/临时/旧产物或扩容: du -x -h --max-depth=1 / | sort -h; 写不下会让自动任务静默失败",
    "主机inode": "按文件数定位: df -i /; find / -xdev -printf '%h\\n' 2>/dev/null | sort | uniq -c | sort -rn | head",
    "主机内存": "查内存大户 top/ps 找泄漏进程, 评估重启服务/加内存; 持续请上报",
    "主机swap": "同内存处置: 查异常大内存进程/泄漏, 确认 swappiness 与 swap 容量",
}
_LOG_MAP = {t["task"]: str(LOG_DIR / t["log"]) for t in TASKS}


def _format_alert_item(line):
    """B2: 单条 SEVERE 告警行 -> 4 行模板 HTML。"""
    _text = line[8:] if line.startswith("SEVERE: ") else line  # "SEVERE: "=8字符
    _first = _text.split(" ", 1)[0] if " " in _text else _text
    _task = _first
    if _first.startswith("com.trade."):
        _task = _first.replace("com.trade.", "").replace("-", "_")
    elif _first == "线上":
        _task = "overview"
    _impact = _IMPACT_MAP.get(_task, "对应任务数据可能过期或未更新, 前端可能读到旧数据")
    _sugg = _SUGGEST_MAP.get(_task, "自动恢复中; 若持续异常请人工介入检查")
    _log = _LOG_MAP.get(_task, str(MONITOR_LOG))
    _esc = lambda s: str(s).replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return (
        f"<b>[SEVERE] {_esc(_text)}</b><br>"
        f"影响: {_esc(_impact)}<br>"
        f"日志: {_esc(_log)}<br>"
        f"建议: {_esc(_sugg)}"
    )


# 输出 + 告警
now_str = NOW.strftime("%Y-%m-%d %H:%M:%S")
# #123 R5(2026-10-01): R2/部署链路拥堵同根因日汇总。当日 >=2 种 R2 相关告警(如 09-30
# r2_unreachable + r2_overview_lag + intraday 滞后同轮 3 封, 同一 upload_r2 卡死根因) →
# 首条照发保即时性, 第 2 条起并入 r2_pipeline_congestion|{YYYYMMDD} 状态, 23:25 收尾轮发
# 1 条汇总(现象清单 + #149 根因指针)。非 R2 告警(漏跑/exit失败/数据错)不入聚合, 照发。
# 判定/聚合函数 scripts/alert_denoise_rules.py:r5_congestion_process。状态 key 不进恢复循环
# (已在恢复循环开头跳过 R2_CONGESTION_SUMMARY_KEY_PREFIX)。
# 2026-10-01 复审修复(R5 双重致命缺陷, 见 docs/ops/123-alert-denoise-implementation-review-20261001.md):
# ① R5 无条件调用(移出 if alerts)——23:25 收尾轮 alerts 为空时也必须运行, 否则当日已聚合
#    现象永远进不了汇总;
# ② 调用后立即 save_alert_state 落盘——否则 r2_pipeline_congestion|{YYYYMMDD} 状态只存在
#    进程内存, 每轮独立进程退出即丢, 同轮第 2+ 种 R2 告警被吞且永久静默。
_orig_has_alerts = bool(alerts)
alerts, _r5_summary = adr.r5_congestion_process(alert_state, alerts, NOW)
if _r5_summary:
    alerts.append(_r5_summary)
save_alert_state(alert_state)
if alerts:
    print(f"[{now_str}] 检测到 {len(alerts)} 个告警:")
    for a in alerts:
        print(a)
    # 复用 notify.py 发邮件 + 写 alerts/latest.md（subject 统一模板 [告警] ... MM-DD HH:MM）
    # --from-prefix "[告警]" -> 发件人名 "[告警] 信号实验室"
    # B2(2026-08-14): 正文由纯 SEVERE 行列表改为每项 4 行模板(严重度/影响/日志/建议)
    body = "<br><br>".join(_format_alert_item(a) for a in alerts)
    _sm_time = NOW.strftime("%m-%d %H:%M")
    _r_main = subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            f"[告警] {len(alerts)}项计划任务异常 {_sm_time}",
            body,
            "--severe",
            "--from-prefix", "[告警]",
            "--alert-issue", "计划任务监控告警",
            "--alert-log", str(MONITOR_LOG),
        ],
        capture_output=True, text=True, check=False,
    )
    _main_out = (_r_main.stdout or "") + (_r_main.stderr or "")
    if _main_out.strip():
        print(_main_out.strip())
    # #241 同族(2026-10-09): 「先落签后 fire-and-forget 通知」病灶修复 —— 上方 save_alert_state
    # (及轮内检查点)已先把本轮新告警落签 active, 此处 notify 若丢返回值则通道全挂时告警丢失且
    # state 已落签 ⇒ 条件持续期永不重发(15min 全局巡检中枢受影响面最大)。改为: 只有 notify
    # **真发出**才保留本轮新 active 落签; 判不出/全失败 ⇒ 回滚本轮新 active key ⇒ 下轮重试。
    # 判据 = notify_sent(输出文本, rc 不可信: notify.py main() 所有出口恒 return 0)。
    # --alert-issue 的 latest.md 镜像不依赖渠道成功(仍写), 故最新告警页不丢。
    if not notify_sent(_main_out):
        _rb = _rollback_transition(alert_state, _STATE_PRE, "active")
        save_alert_state(alert_state)
        print(f"[warn] 聚合告警未确认送达(rc={_r_main.returncode}) ⇒ 回滚本轮 {_rb} 个新告警落签"
              f"(下轮重试)", file=sys.stderr)
elif _orig_has_alerts:
    print(f"[{now_str}] 本轮告警已由 R2 拥堵日汇总接管, 见 r2_pipeline_congestion 状态")
else:
    print(f"[{now_str}] OK 所有任务按计划执行，无漏跑，无退出失败")

# 恢复邮件(独立于 SEVERE,异常消失即发,不加 --severe 前缀)
# 2026-09-22 告警去噪: r2_* 前缀为自愈类(网络抖动/R2 故障可被 self_heal/网络自愈,
# 见 L247 通知分级注释), 每次抖动发"告警+恢复"2 封(179 封里 82 封是恢复邮件)。
# 统一 suppress r2_* 恢复邮件——状态已在各 inline 恢复点置 recovered(仅抑制邮件),
# 与 72h_ 等自愈类口径一致; 非 r2_ 恢复(漏跑/exit失败/数据错等严重类)仍正常发。
# 2026-09-24 告警降噪 P1("recovered 改恢复汇总"): 恢复邮件加 --dedup-key + 6h 窗口,
# 与 RECOVERY_COOLDOWN(6h)+_recurrence_suppressed 三合一压 recovered->active 振荡轰炸;
# 6h 内无论多少条恢复只发首封(汇总), 6h 后新恢复重新可发——恢复通知是低价值信息,
# 延迟合并可接受, SEVERE(首次异常直发)不受影响。
recoveries = [r for r in recoveries if not str(r.get("task", "")).startswith("r2_")]
if recoveries:
    print(f"[{now_str}] 检测到 {len(recoveries)} 个异常恢复:")
    for r in recoveries:
        print(f"  [恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失")
    if len(recoveries) == 1:
        r0 = recoveries[0]
        subject = f"[恢复] {r0['task']} {r0['keyword']} {NOW.strftime('%m-%d %H:%M')}"
    else:
        subject = f"[恢复] {len(recoveries)}项异常恢复 {NOW.strftime('%m-%d %H:%M')}"
    rec_lines = [
        f"[恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失 "
        f"(首次发现: {r['first_seen']}, 恢复时间: {now_str})"
        for r in recoveries
    ]
    # B2(2026-08-14): 恢复邮件尾加"无需操作,已自动恢复"提示
    rec_lines.append("— 无需操作, 异常已自动恢复 —")
    body = "<br>".join(
        l.replace("<", "&lt;").replace(">", "&gt;") for l in rec_lines
    )
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            subject,
            body,
            "--from-prefix", "[恢复]",
            "--alert-issue", "计划任务监控恢复",
            "--alert-log", str(MONITOR_LOG),
            # 2026-09-24 P1: 恢复汇总 6h 去重(合并成"恢复汇总"一次性发, 防振荡期每轮一封)
            "--dedup-key", "schedule_monitor_recovery", "--dedup-window", "21600",
        ],
        check=False,
    )

# S06 快照新鲜度兜底检查（2026-08-26，S06 每日重生链路第三件）：
# kelly_mode_s06_state.json 的 coverage_end 落后最近已入库交易日 >1 个交易日 →
# check_s06_freshness.py --notify 内部 defer_warning 入聚合队列（自带同状态去重防
# 15min 周期轰炸），由本脚本尾部既有 --flush-warnings 统一批发。放独立脚本+子进程调用：
# 判定逻辑可 dry 单测（--snap/--index 传构造样本），监控层只看退出码。
# 注: s06_snapshot_launchd.log 的漏跑/exit失败已被上方维度1/2 覆盖(标准开始/结束行),
# 本检查补「任务跑了但产物仍过期」的语义盲区(如 gen 成功但 index 输入断更)。
try:
    _r_s06 = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_s06_freshness.py"), "--repo", str(REPO), "--notify"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if _r_s06.returncode == 0:
        print(f"[s06] {_r_s06.stdout.strip().splitlines()[0] if _r_s06.stdout.strip() else '新鲜度 OK'}")
    elif _r_s06.returncode == 1:
        print(f"[s06] 快照过期(已 defer_warning 入聚合队列): {_r_s06.stdout.strip()[:200]}")
    else:
        print(f"[warn] s06 freshness 无法判定 rc={_r_s06.returncode}: "
              f"{(_r_s06.stdout + _r_s06.stderr).strip()[:200]}", file=sys.stderr)
except Exception as e:
    print(f"[warn] s06 freshness 检查失败(不阻塞主流程): {e}", file=sys.stderr)

# pre-upload 覆盖前备份护栏存活观测（#237 D③，2026-10-10）：
# 根因=护栏自 10-05 切桶起 100% 失败却无人察觉（失败只 print、不阻断、无观测点 ⇒ §25
# 「备份先于覆盖」实际能力 0）。判定 = R2 只读 LIST 数 pre-upload/<今日>/ 对象数，与当日
# 通道日志的结构化行对账；fail 时 check_preupload_backup.py 内部 defer_warning 入聚合队列
# （--dedup-key preupload_backup_fail 6h 去重防 15min 周期轰炸），由本脚本尾部既有
# --flush-warnings 统一批发。判据/边界见该脚本 docstring；监控层只看退出码。
# 注: 备份段挂在上传通道内部（无独立 launchd 日志），漏跑由上方维度1/2 覆盖；本检查补
# 「通道跑了但备份零落地」的语义盲区（10-05~10-09 病态形态）。
try:
    _r_pu = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_preupload_backup.py"),
         "--repo", str(REPO), "--notify"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if _r_pu.returncode == 0:
        print(f"[preupload] {_r_pu.stdout.strip().splitlines()[0] if _r_pu.stdout.strip() else 'OK'}")
    elif _r_pu.returncode == 1:
        print(f"[preupload] 覆盖前备份护栏异常(已 defer_warning 入聚合队列): {_r_pu.stdout.strip()[:200]}")
    else:
        print(f"[warn] preupload backup 无法判定 rc={_r_pu.returncode}: "
              f"{(_r_pu.stdout + _r_pu.stderr).strip()[:200]}", file=sys.stderr)
except Exception as e:
    print(f"[warn] preupload backup 检查失败(不阻塞主流程): {e}", file=sys.stderr)

# Heartbeat：每次完整跑完都更新时间戳（主控 Claude Code cron 读此文件，
# 超过 30 分钟未更新 = launchd 层可能挂了，立即提示用户）。
# 文件含时间戳 + 告警数，便于主控层判断"在跑但有告警" vs "完全没跑"。
try:
    heartbeat_path = Path("/tmp/schedule-monitor-heartbeat.txt")
    heartbeat_path.write_text(
        f"{NOW.strftime('%Y-%m-%d %H:%M:%S')}\nalerts={len(alerts)}\n",
        encoding="utf-8",
    )
except Exception as e:
    print(f"[warn] heartbeat 写入失败: {e}", file=sys.stderr)

# 2026-08-24 三级分级接线: 冲出 warning 缓冲区里到期的条目(30min 聚合窗口),
# 满窗聚合一封发出(不逐条轰炸); info 级在 notify.py 内只落盘不推送。
# 放 heartbeat 后=每轮收尾兜底 flush, 与各检查点 defer_warning 配对。
try:
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            "--flush-warnings",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
except Exception as e:
    print(f"[warn] warning 聚合 flush 失败: {e}", file=sys.stderr)

# 2026-10-10 W1-L1 度量层：幂等重算 data/alerts/alert_daily.json（读单点台账派生，
# 跨两树写同一结果）。best-effort，失败不阻塞主流程，且**本机制自身绝不告警**。
# 时点：每轮收尾跑一次（幂等 ⇒ 重复跑无副作用）；避开盘后重任务时点
# （15:35/16:00/17:50/20:35/22:00，§14）±2min，防与 deploy/采集撞车。
_GUARDED_HHMM = ("15:35", "16:00", "17:50", "20:35", "22:00")


def _in_guarded_window(now, tol_min=2):
    for hhmm in _GUARDED_HHMM:
        h, m = (int(x) for x in hhmm.split(":"))
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((now - t).total_seconds()) <= tol_min * 60:
            return True
    return False


try:
    if _in_guarded_window(NOW):
        print("[alert_meter] 盘后重任务窗口内，本轮跳过 recount")
    else:
        _r_meter = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "alert_meter.py"), "--recount"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if _r_meter.returncode != 0:
            print(f"[warn] alert_meter recount rc={_r_meter.returncode}: "
                  f"{(_r_meter.stdout + _r_meter.stderr).strip()[:200]}", file=sys.stderr)
except Exception as e:
    print(f"[warn] alert_meter recount 失败(不阻塞): {e}", file=sys.stderr)
PYEOF

# 总是 exit 0：告警已发邮件，避免 launchd 因非0退出重试
exit 0
