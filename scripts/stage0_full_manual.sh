#!/bin/bash
# stage0_full_manual.sh - 公募基金筛选器阶段0 手动全量串联采集
#
# 场景: 手动全量初始化(非 launchd 周期性触发)。周末休盘适合跑, 工作日盘中可续跑。
#
# 串行顺序(避免并发反爬+DB写撞):
#   1. overview  补 fund_basic 15 新列(逐只 fund_overview_em) ~6.2h
#   2. nav       5 年净值 27409 只断点续采(逐只 fund_open_fund_info_em) 可能十几 h
#   3. risk      risk_indicator + fee_detail ~4.5h(逐只 xq + 费率)
#   4. manager   自爬 fundf10 任职历史 ~3h(appoint_date + managed_history)
#
# 每步调用对应 stage0_*.sh(已含 caffeinate + fcntl 互斥 + 断点续采)
# 某步失败不阻塞下一步(|| true 继续)
# 整体 caffeinate -i 防休眠(跨多天长任务)
#
# 进度: /tmp/stage0-full-manual-progress.md(每步开始/完成 echo, 时间戳+耗时)
# 日志: data/logs/stage0_full_manual.log(nohup stdout/stderr, 整体)
#       data/logs/stage0-{overview,nav,risk,manager}.log(各步详细日志, append)
# PID : /tmp/stage0-full-manual-pid.txt
#
# 断点续采: overview/nav 有 progress.json, 中断后重跑 stage0_*.sh 自动续采
# 撞 update_all 17:50: stage0 与 update_all 写不同表, 不撞 public_fund.lock, 安全
set -uo pipefail

REPO="/Users/linhuichen/code/trade-data"
PROGRESS="/tmp/stage0-full-manual-progress.md"
PY="$REPO/.venv/bin/python"

cd "$REPO" || { echo "cd $REPO failed" >> "$PROGRESS"; exit 1; }

# 整体 caffeinate 防休眠(跨多天长任务必须防休眠, -w $$ 绑定本进程)
caffeinate -i -w $$ >/dev/null 2>&1 &

ts() { date '+%F %T'; }

echo_step() {
  # 追加一行带时间戳的进度
  printf '\n## [%s] %s\n' "$(ts)" "$1" >> "$PROGRESS"
}

# 进度文件初始化(覆盖写, 每次启动重置)
{
  printf '# stage0 手动全量串联采集进度\n\n'
  printf -- '- 启动时间: %s\n' "$(ts)"
  printf -- '- PID: %s\n' "$$"
  printf -- '- 串行顺序: overview -> nav -> risk -> manager\n'
  printf -- '- 每步耗时累加, 断点续采可中断续跑\n\n'
} > "$PROGRESS"

echo_step "stage0_full_manual 启动 (PID=$$, cwd=$REPO)"

# ---------- 步骤1: overview (补 fund_basic 15新列, ~6.2h) ----------
echo_step "步骤 1/4 overview 开始 (补 fund_basic 15新列, ~6.2h)"
START=$(date +%s)
bash "$REPO/scripts/stage0_overview.sh" || true
END=$(date +%s)
ELAPSED=$((END-START))
echo_step "步骤 1/4 overview 完成 (耗时 ${ELAPSED}s = $((ELAPSED/3600))h$(((ELAPSED%3600)/60))m)"
{
  printf '  overview.log 尾部:\n'
  tail -3 "$REPO/data/logs/stage0-overview.log" 2>/dev/null | sed 's/^/    /'
} >> "$PROGRESS"

# ---------- 步骤2: nav (5年净值27409只断点续采, 可能十几h) ----------
echo_step "步骤 2/4 nav 开始 (5年净值27409只断点续采, 可能十几h)"
START=$(date +%s)
bash "$REPO/scripts/stage0_nav.sh" || true
END=$(date +%s)
ELAPSED=$((END-START))
echo_step "步骤 2/4 nav 完成 (耗时 ${ELAPSED}s = $((ELAPSED/3600))h$(((ELAPSED%3600)/60))m)"
{
  printf '  nav.log 尾部:\n'
  tail -3 "$REPO/data/logs/stage0-nav.log" 2>/dev/null | sed 's/^/    /'
} >> "$PROGRESS"

# ---------- 步骤3: risk (risk_indicator+fee_detail, ~4.5h) ----------
# stage0_risk.sh 有月份闸门(仅 1/4/7/10 月季报披露完成月才跑)。
# 手动全量初始化场景需要绕过闸门: 先调 stage0_risk.sh, 若被闸门跳过则
# fallback 直接调 python 模块跑全量(此时 launchd stage0_risk 每月15日不触发,
# 不需 shell 层 fcntl 锁; python 层 public_fund.lock 防与其他 public_fund 命令撞)。
echo_step "步骤 3/4 risk 开始 (risk_indicator+fee_detail, ~4.5h)"
START=$(date +%s)
bash "$REPO/scripts/stage0_risk.sh" || true
# 检测月份闸门跳过(非 1/4/7/10 月)
if tail -5 "$REPO/data/logs/stage0-risk.log" 2>/dev/null | grep -q "skip (month="; then
  echo_step "risk 被月份闸门跳过(非季报月), fallback 直接调 python 绕过闸门(手动全量初始化)"
  {
    printf '=== %s stage0-risk manual fallback start ===\n' "$(ts)"
    "$PY" -m app.collector.public_fund stage0-risk
    RC=$?
    printf '=== %s stage0-risk manual fallback end rc=%s ===\n' "$(ts)" "$RC"
  } >> "$REPO/data/logs/stage0-risk.log" 2>&1
fi
END=$(date +%s)
ELAPSED=$((END-START))
echo_step "步骤 3/4 risk 完成 (耗时 ${ELAPSED}s = $((ELAPSED/3600))h$(((ELAPSED%3600)/60))m)"
{
  printf '  risk.log 尾部:\n'
  tail -3 "$REPO/data/logs/stage0-risk.log" 2>/dev/null | sed 's/^/    /'
} >> "$PROGRESS"

# ---------- 步骤4: manager (任职历史, ~3h) ----------
echo_step "步骤 4/4 manager 开始 (自爬 fundf10 任职历史, ~3h)"
START=$(date +%s)
bash "$REPO/scripts/stage0_manager.sh" || true
END=$(date +%s)
ELAPSED=$((END-START))
echo_step "步骤 4/4 manager 完成 (耗时 ${ELAPSED}s = $((ELAPSED/3600))h$(((ELAPSED%3600)/60))m)"
{
  printf '  manager.log 尾部:\n'
  tail -3 "$REPO/data/logs/stage0-manager.log" 2>/dev/null | sed 's/^/    /'
} >> "$PROGRESS"

echo_step "stage0_full_manual 全部 4 步完成"
{
  printf -- '\n- 结束时间: %s\n' "$(ts)"
} >> "$PROGRESS"
