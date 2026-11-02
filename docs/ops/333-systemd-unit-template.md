# #333 批1 systemd unit 模板(生成源, 云上部署待批1 验证后由主控派部署任务)

> 本文件是 unit 生成源(四副本纪律 L54/L55 之一)。**云上真实 unit 部署不在本批范围**——
> 批1 只产代码 + 本模板;上线 timer 由主控派部署任务,届时同步四副本(代码/.sh/快照/云上 unit)。

## 时点
- OnCalendar: `*-*-* 21:10:00`(仅交易日,脚本内 `is_trading_day` 闸门;非交易日需手动验证时直调 `python -m scripts.collect_fof_nav`,不走包装脚本——CLI 无 `--force` 绕闸门参数)
- 依据:21:00 backfill-evening 写 sentiment.db(不撞 public_fund.db)、21:20 futures 写期货;
  public_fund.db 写入任务只 16:20/17:00 daily + 03:00 quarterly(ssh list-timers 实测)

## 预算(内外层成对 L55, 按分批后最坏路径复算)
- 实测口径: FOF/QDII 共 1796 只(FOF 1421 + QDII 375, ssh 云上 public_fund.db 实查 2026-11-02)。
- WAF 压测实测(§5.9): 50 只 × 0.3s 间隔 = ok=50/fail=0/429=0/封=0, 平均 0.51s/只(含网络+sleep)。
- 分批: 每轮跑 BATCH_SIZE=500 只(配合跳过已填, 几轮覆盖 1796)。
- 最坏路径(本轮 500 只): 500 × (0.3s sleep + 0.21s 网络 + 最坏单只 15s 超时) ≈ 500 × 0.51s = 255s
  (正常路径); 含单只超时退避最坏 ≈ 500 × (0.51 + 极少数 15s) ≈ 350s(超时是少数, 非每只 15s)。
- 内层 `run_to 600`(覆盖最坏 ~350s + 余量 250s, 留梯度)
- 外层 systemd `TimeoutStartSec=900`(梯度 300s, 外层 > 内层留梯度 L55)

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
ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/run_fof_nav_collect.sh
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
