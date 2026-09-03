#!/bin/bash
# sensenova-rotate-proxy-kimi.sh — 商汤多 token 轮换代理包装脚本(kimi-k3 版,launchd 守护入口)
#
# 用途:从 ../trade-data/.env(仓外)读 SENSENOVA_KEY1/2/3/4/5,注入 env 后 exec 纯 key 轮换代理(kimi-k3 版)。
#      真实 key 禁进 git/plist;key 只存在于 .env 与本进程 env。
#      与 v4-flash 版(sensenova-rotate-proxy.sh/8899)独立:本版 8898,两者可同时常驻互不干扰。
# 用法(由 launchd plist 调,或手动):
#   bash scripts/sensenova-rotate-proxy-kimi.sh
# 切换:bash scripts/kimi-proxy-switch.sh kimi / v4flash(双向切换 settings.json BASE_URL+MODEL)
set -u
ENV_FILE="${SENSENOVA_ENV_FILE:-/Users/linhuichen/code/trade-data/.env}"
if [ -f "$ENV_FILE" ]; then
  # 只导出 SENSENOVA_KEY* 这几个键(不 source 整文件,避免带出其他敏感键到子进程环境)
  for k in SENSENOVA_KEY1 SENSENOVA_KEY2 SENSENOVA_KEY3 SENSENOVA_KEY4 SENSENOVA_KEY5; do
    v=$(grep -E "^${k}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
    [ -n "$v" ] && export "$k=$v"
  done
else
  echo "WARN .env not found: $ENV_FILE (will try proxy-internal read)" >&2
fi
exec /usr/bin/python3 /Users/linhuichen/code/trade/scripts/sensenova-rotate-proxy-kimi.py "$@"