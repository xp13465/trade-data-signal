#!/usr/bin/env bash
# FAPI 日线采集 → 北交所宽度重算 链式 wrapper（#101 方案C, 2026-09-06）
#
# 背景: FAPI daily-k-10d dump 每日 18:10 采集(launchd com.trade.fapi-daily),
# 含北交所 920 段(341 只)。bj_width 需在 FAPI 采集"之后"跑才能拿到当天北交所数据,
# 故将 fapi_daily + bj_width 串成一条链(18:10 单一时点, 不加新定时, 不撞 §14 时点)。
#
# 依赖: fapi_daily 失败则中止(北交所宽度依赖 FAPI 数据); bj_width 失败仅告警不阻断
#       (北交所宽度是新增指标, 缺供不影响既有功能, runner step 同语义)。
#
# 时点: 18:10(launchd StartCalendarInterval 保持原值), 晚于 17:50 update_all, 与
#       15:35/16:00/17:50/20:35/22:00 既有时点无冲突。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="${REPO}/.venv/bin/python"

echo "=== [fapi-daily-syn] $(date '+%F %T') start ==="

# 1) FAPI T+0 日线 dump 采集(含北交所 920 段)
"$PY" -m app.collector.fapi_daily || {
  echo "[fapi-daily-syn] FATAL: fapi_daily 采集失败, 中止(北交所宽度依赖 FAPI 数据)"
  exit 1
}

# 2) 北交所宽度独立指标组 a_bj_*(30% 档, 不动主宽度)
"$PY" -m app.collector.bj_width --days=35 || {
  echo "[fapi-daily-syn] WARN: bj_width 计算失败(新增指标缺供, 不阻断, 次日 17:50 runner 会重试)"
}

echo "=== [fapi-daily-syn] $(date '+%F %T') done ==="
exit 0
