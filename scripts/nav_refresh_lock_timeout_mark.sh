#!/usr/bin/env bash
# nav_refresh_lock_timeout_mark.sh — nav_bucket 刷新「等锁超时跳过」留痕钩子(#278)。
#
# 由 scripts/with_lock.py --on-timeout 调用(拿不到锁、等锁超预算时先执行本脚本再 exit 0)。
# 作用: 写一个标记文件(路径由调用方经 NAV_REFRESH_SKIP_MARK 传入), 让调用方 lib 能区分
#       「刷新成功」与「等锁超时跳过」—— with_lock.py 两种情况都 exit 0, 不能只靠退出码。
# **不发任何通知**(本链跳过不是故障: 持锁方正重出同一产物, deploy 闸门会按既有规则判定;
#   告警链由 deploy/failed-unit 既有通道负责, 不新开外发口子)。
# 参数 $1 = 锁路径(with_lock.py 传入; 本脚本只留痕, 不操作锁)。
set -u

MARK="${NAV_REFRESH_SKIP_MARK:-}"
if [ -n "$MARK" ]; then
  : > "$MARK" 2>/dev/null || true
fi
echo "[nav_bucket_refresh] 等锁超时跳过(锁=${1:-unknown}), 刷新未执行" >&2
exit 0