#!/bin/bash
# backfill_metrics.sh - backfill-evening 兜底：补采缺失指数 + direct:类指标(主力净流入等)
# 替代 backfill_indices.sh：原补指数(index_backfill.main 多源校验补采) + 新增 direct
# metrics 补采(a_fund_main 等;东财封禁时 direct.py 内置 akshare fallback 兜底,7-13/7-17
# 间歇封禁后 backfill-evening 槽位补回当日值)。
# launchd 02:00/16:35/20:00 触发(由 com.trade.backfill-evening.plist 调用)。
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &
REPO="${REPO:-/Users/linhuichen/code/trade}"
cd "$REPO"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$REPO/data/logs/backfill_${STAMP}.log"
mkdir -p "$REPO/data/logs"

echo "=== backfill_metrics.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 1) 补采缺失指数（原 backfill_indices.sh 逻辑：index_backfill.main 校验 + 多源补采 + 重算情绪分）
"$REPO/.venv/bin/python" -c "from app.collector.index_backfill import main; main()" 2>&1 | tee -a "$LOG"

# 2) 补采 direct:类指标（主力净流入 a_fund_main 等；东财封禁时 direct.py 内置 akshare fallback）
"$REPO/.venv/bin/python" -c "
from app.collector.fetchers import load_config, collect_direct
from app.collector.runner import upsert_metrics_many
from app.collector.base import log_collect
from app.db import get_conn
from app.calendar import last_trading_day
cfg = load_config()
date = last_trading_day()
ok = fail = 0
for m in cfg.get('metrics', []):
    if not m.get('enabled'):
        continue
    if not m.get('func', '').startswith('direct:'):
        continue
    mid = m['id']
    try:
        rows, msg = collect_direct(m)
        if rows:
            upsert_metrics_many(mid, rows)
            # 补采成功=告警解除:清同 run_date 该 metric 旧非 ok 记录,
            # 让 collect_health 反映最新状态(同任务2清 disabled 误报同理)
            _c = get_conn()
            _c.execute('DELETE FROM collect_log WHERE run_date=? AND metric_id=? AND status<>?',
                       (date, mid, 'ok'))
            _c.commit(); _c.close()
            ok += 1
            print(f'[ok] {mid} +{len(rows)} rows', flush=True)
            log_collect(date, mid, 'ok', f'{len(rows)} rows')
        else:
            fail += 1
            print(f'[fail] {mid} {msg}', flush=True)
            log_collect(date, mid, 'error', msg)
    except Exception as e:
        fail += 1
        print(f'[fail] {mid} {e}', flush=True)
        log_collect(date, mid, 'error', str(e))
print(f'=== direct metrics 补采 ok={ok} fail={fail} ===', flush=True)
" 2>&1 | tee -a "$LOG"

RC=${PIPESTATUS[0]}
echo "=== backfill_metrics.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json：deploy.sh 在 backfill 内部(index_backfill.main L884)被触发时，
# backfill "结束"行尚未写入日志，gen_schedule_stats 解析 backfill_evening 为 pending(null exit/dur)，
# 致前端"执行统计"backfill_evening 行永显 null。此处 backfill 已结束、日志含完整"开始+结束"对，
# 重跑拿到正确 exit/dur（根治 git log 近10个 commit backfill_evening last_exit=null 的时序竞态）。
# 只写 REPO(trade-data) 版本 schedule_stats.json，trade 版本(static-site/data/)等下次 deploy.sh
# 的 rsync(95-100) 同步；若 backfill 内部 index_backfill 已触发 deploy（有新数据时），本次刷新值
# 会在下次 update_all(17:50) 触发的 deploy 中被 rsync 到 trade 并 commit 推送上线。
"$REPO/.venv/bin/python" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞 backfill" | tee -a "$LOG"
exit $RC
