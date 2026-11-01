# #333 批1 systemd unit 模板(生成源, 云上部署待批1 验证后由主控派部署任务)

> 本文件是 unit 生成源(四副本纪律 L54/L55 之一)。**云上真实 unit 部署不在本批范围**——
> 批1 只产代码 + 本模板;上线 timer 由主控派部署任务,届时同步四副本(代码/.sh/快照/云上 unit)。

## 时点
- OnCalendar: `*-*-* 21:10:00`(仅交易日,脚本内 `is_trading_day` 闸门 + force 绕过)
- 依据:21:00 backfill-evening 写 sentiment.db(不撞 public_fund.db)、21:20 futures 写期货;
  public_fund.db 写入任务只 16:20/17:00 daily + 03:00 quarterly(ssh list-timers 实测)

## 预算(内外层成对 L55)
- 内层 `run_to 600`(1162+ FOF ×0.3s ≈ 350s + 单只 15s 上限, 最坏 ~500s)
- 外层 systemd `TimeoutStartSec=900`(梯度 400s)

## trade-fof-nav-collect.service
```ini
[Unit]
Description=Trade FOF/QDII net-value collector (#333 batch1, 源 com.trade.fof-nav-collect)
After=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=REPO=/home/ubuntu/code/trade-data
ExecStart=/bin/bash -c '/home/ubuntu/code/trade-data/scripts/run_fof_nav_collect.sh'
TimeoutStartSec=900
```

## trade-fof-nav-collect.timer
```ini
[Unit]
Description=Trade FOF/QDII nav collect daily 21:10

[Timer]
OnCalendar=*-*-* 21:10:00
Persistent=true

[Install]
WantedBy=timers.target
```

## run_fof_nav_collect.sh(包装层, 交易日闸门 + 超时)
```bash
#!/bin/bash
set -uo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh"
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"; mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/fof_nav_collect_${STAMP}.log"
echo "=== fof_nav_collect 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
# 交易日闸门
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
if [ "$IS_TRADING" != "1" ]; then
  echo "非交易日，跳过 FOF/QDII 净值采集" | tee -a "$LOG"; exit 0
fi
run_to() {
  local t="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$t" "$@"
  else perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; fi
}
run_to 600 "$PY" -m scripts.collect_fof_nav 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== fof_nav_collect 结束 rc=$RC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
exit "$RC"
```
