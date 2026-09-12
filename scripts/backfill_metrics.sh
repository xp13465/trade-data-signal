#!/bin/bash
# backfill_metrics.sh - backfill-evening 兜底：补采缺失指数 + direct:类指标(主力净流入等)
# 替代 backfill_indices.sh：原补指数(index_backfill.main 多源校验补采) + 新增 direct
# metrics 补采(a_fund_main 等;东财封禁时 direct.py 内置 akshare fallback 兜底,7-13/7-17
# 间歇封禁后 backfill-evening 槽位补回当日值)。
# launchd 02:00/16:35/21:00 触发(由 com.trade.backfill-evening.plist 调用)。
# 2026-07-29 加 21:00 槽：中证红利(csi_div/div_lowvol)T 日晚发布，21:00 提前采(原仅 02:00 兜底)。
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
if [ "$(uname -s)" = "Darwin" ]; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
fi
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
cd "$REPO"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$REPO/data/logs/backfill_${STAMP}.log"
mkdir -p "$REPO/data/logs"

echo "=== backfill_metrics.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 3 槽位(16:35/21:00/02:00)同一脚本：按当前时刻注入槽位标识给 direct 采集。
# CCASS 季度指标(hkex_ccass_quarterly)据此区分：02:00 强制重算+3600s alarm(每日自纠正+兜底)，
# 16:35/21:00 季度闸门+600s alarm(有最新季度行跳过，省 7-35min 尾部)。update_all(17:50)无此 env
# 默认闸门+600s。
export BACKFILL_SLOT="$(date +%H%M)"

# 1) 补采缺失指数（原 backfill_indices.sh 逻辑：index_backfill.main 校验 + 多源补采 + 重算情绪分）
"$REPO/.venv/bin/python" -c "from app.collector.index_backfill import main; main()" 2>&1 | tee -a "$LOG"
idx_rc=${PIPESTATUS[0]}
if [ "$idx_rc" -ne 0 ]; then
    echo "⚠ index_backfill 主采集失败(退出码 $idx_rc), 计入 backfill 退出码" | tee -a "$LOG"
fi

# 2) 补采 direct:类指标（主力净流入 a_fund_main 等；东财封禁时 direct.py 内置 akshare fallback）
#    独立脚本 scripts/backfill_direct_metrics.py（2026-09-09 从内嵌 python 提取，逻辑逐行一致，
#    唯一变更=缺口判定）。退出码语义：仅「真失败」（no direct.fetch_* 配置缺失 / direct:* error:
#    采集异常 / 抛异常）计 fail → exit 1；「两源皆败无数据」= 数据源正常缺口(gap)，不计 fail、
#    不进退出码，缺口由 collect_health 通道反映（#84 reviewer P1-1：02:00 槽 a_fund_main 每日
#    必现该缺口，旧逻辑计 fail → 每日 exit 1 → schedule_monitor 假 SEVERE+恢复邮件循环）。
"$REPO/.venv/bin/python" "$REPO/scripts/backfill_direct_metrics.py" 2>&1 | tee -a "$LOG"
drc=${PIPESTATUS[0]}
if [ "$drc" -ne 0 ]; then
    echo "⚠ direct metrics 补采有失败(退出码 $drc), 计入 backfill 退出码" | tee -a "$LOG"
fi

# 3) 信号凯利回测快照告警(2026-09-04 断链根治配套): 读 static-site/data/signal_kelly_snapshots/
#    index.json, 检测 max_signal_date 停滞(≥2 交易日) + total_return 突变(相对口径: 单日|Δ|>
#    窗口均值×5% + dir_confirmed 同向确认, 多 mode 合并单条, 详见 signal_kelly_snapshot.py docstring),
#    走 notify.py 邮件+飞书同 body(dedup 24h)。
#    数据目录必须显式 --data-dir "$REPO/static-site/data"(与 export.py 写侧一致; snapshot.py
#    resolve 回 trade/scripts 时默认 data-dir 落 trade 侧旧目录, 与 export 写侧不一致, 故显式传参)。
#    [2026-09-09 #84 C4] sigkelly 停滞检查已从 backfill 退出码剥离: snapshot.py 检测到停滞/突变
#    时自己已走 notify.py 独立告警通道发邮件+飞书(dedup 24h), 不再通过 backfill_evening 的退出码
#    二次上抛。根因(2026-09-08 实测): 主采集 ok=3 全成功但 snap_rc=1 → 脚本 exit 1 →
#    schedule_monitor 判 backfill_evening 退出失败 → 连锁误报"信号凯利回测停滞"+backfill 双封邮件。
#    此处只保留检查本身 + 日志(独立告警通道仍会发), 退出码改为只聚合主采集见下方。
"$REPO/.venv/bin/python" "$REPO/scripts/signal_kelly_snapshot.py" --check --data-dir "$REPO/static-site/data" 2>&1 | tee -a "$LOG"
snap_rc=${PIPESTATUS[0]}
if [ "$snap_rc" -eq 0 ]; then
    echo "  signal_kelly_snapshot --check 通过(无告警)" | tee -a "$LOG"
elif [ "$snap_rc" -eq 1 ]; then
    echo "⚠ signal_kelly_snapshot --check 检测到告警(停滞/突变, 正常路径), 已由 snapshot 独立告警通道发出(邮件+飞书 dedup24h), 不阻塞 backfill(#84 C4)" | tee -a "$LOG"
else
    echo "⚠ signal_kelly_snapshot --check 脚本异常(退出码 $snap_rc, 非预期), 不阻塞 backfill(独立告警通道 #84 C4)" | tee -a "$LOG"
fi

# [2026-09-09 #84 C4] backfill 总退出码只聚合「主采集」(指数补采 index_backfill + direct metrics):
#   主采集全成功 → exit 0(即使 sigkelly 停滞告警 snap_rc=1, 那是独立告警通道的事, 不再拖累本任务)。
#   主采集任一真失败 → exit ≠ 0(schedule_monitor 仍会报, 不放松真告警)。
if [ "$idx_rc" -ne 0 ] || [ "$drc" -ne 0 ]; then
    MAIN_RC=1
else
    MAIN_RC=0
fi
RC=$MAIN_RC
echo "=== backfill_metrics.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC(idx=$idx_rc/direct=$drc/snap=$snap_rc) ===" | tee -a "$LOG"

# 刷新 schedule_stats.json：deploy.sh 在 backfill 内部(index_backfill.main L884)被触发时，
# backfill "结束"行尚未写入日志，gen_schedule_stats 解析 backfill_evening 为 pending(null exit/dur)，
# 致前端"执行统计"backfill_evening 行永显 null。此处 backfill 已结束、日志含完整"开始+结束"对，
# 重跑拿到正确 exit/dur（根治 git log 近10个 commit backfill_evening last_exit=null 的时序竞态）。
# 只写 REPO(trade-data) 版本 schedule_stats.json，trade 版本(static-site/data/)等下次 deploy.sh
# 的 rsync(95-100) 同步；若 backfill 内部 index_backfill 已触发 deploy（有新数据时），本次刷新值
# 会在下次 update_all(17:50) 触发的 deploy 中被 rsync 到 trade 并 commit 推送上线。
"$REPO/.venv/bin/python" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞 backfill" | tee -a "$LOG"
exit $RC
