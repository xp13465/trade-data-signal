#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_direct_metrics.py - backfill-evening 槽位 direct:类指标补采(独立可测版)。

目的:补采 direct:类指标(主力净流入 a_fund_main 等;东财封禁时 direct.py 内置
akshare 等多源 fallback 兜底,间歇封禁后 backfill-evening 槽位补回当日值)。
被 scripts/backfill_metrics.sh 第 2 步调用(2026-09-09 从内嵌 python 提取为独立
脚本,便于对退出码语义做可复现测试;逻辑与内嵌版逐行一致,唯一变更=缺口判定)。

口径:
- ok  = 补采成功(rows 非空),写 ok 并清同 run_date 该 metric 旧非 ok 记录
       (让 collect_health 反映最新状态)
- gap = 数据源无数据(collect_direct 返回空且 msg 含「两源皆败无数据」)=
       正常缺口非任务失败。仍 log_collect error 让 collect_health 通道反映,
       但**不计 fail、不影响退出码**。2026-09-09 #84 reviewer P1-1: 02:00 槽
       a_fund_main 每日必现该缺口,旧逻辑计 fail → backfill 每日 exit 1 →
       schedule_monitor 每日假 SEVERE「backfill_evening 退出失败」+16:35 恢复
       邮件,每日 2 封循环,违背降噪主旨。缺口由 collect_health(前端健康红点)
       反映,不靠退出码。
- fail = 真失败(采集异常崩溃:no direct.fetch_* 配置缺失 / direct:* error:
       采集异常 / 抛异常),计入退出码 → backfill 总退出码非 0 → schedule_monitor
       照常报,保留 C4(#84)修「主采集失败静默 exit 0」盲区的监控价值。

退出码:0=无真失败(全成功或仅数据源缺口);1=存在至少一个真失败。

输入依赖:REPO 环境变量指向主库目录(由 backfill_metrics.sh 设定,默认
/Users/linhuichen/code/trade-data);cwd 须在 REPO(app.* import 依赖)。

输出:stdout 进度(追加进 backfill_{STAMP}.log),collect_log 状态。
复现:bash scripts/backfill_metrics.sh(3 槽位 launchd 调用)。
"""
import os
import sys

# REPO 环境变量优先(backfill_metrics.sh 已 export), 与 signal_kelly_snapshot.py 同模式:
# 独立脚本 sys.path[0]=脚本目录(REPO/scripts), 不含 REPO 主目录, 需显式注入才能 import app.*。
_REPO = os.environ.get("REPO", "/Users/linhuichen/code/trade-data")
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from app.calendar import last_trading_day
from app.collector.base import log_collect
from app.collector.fetchers import collect_direct, load_config
from app.collector.runner import upsert_metrics_many
from app.db import get_conn

GAP_MARKER = "两源皆败无数据"  # collect_direct 空返回的固定 msg(数据源无数据=正常缺口)


def main() -> int:
    cfg = load_config()
    date = last_trading_day()
    ok = gap = fail = 0
    for m in cfg.get("metrics", []):
        if not m.get("enabled"):
            continue
        if not m.get("func", "").startswith("direct:"):
            continue
        mid = m["id"]
        try:
            rows, msg = collect_direct(m)
            if rows:
                upsert_metrics_many(mid, rows)
                # 补采成功=告警解除:清同 run_date 该 metric 旧非 ok 记录,
                # 让 collect_health 反映最新状态(同任务2清 disabled 误报同理)
                _c = get_conn()
                _c.execute(
                    "DELETE FROM collect_log WHERE run_date=? AND metric_id=? AND status<>?",
                    (date, mid, "ok"),
                )
                _c.commit()
                _c.close()
                ok += 1
                print(f"[ok] {mid} +{len(rows)} rows", flush=True)
                log_collect(date, mid, "ok", f"{len(rows)} rows")
            elif GAP_MARKER in msg:
                # 数据源无数据(两源皆败)=正常缺口,非任务失败:仍记 error 供
                # collect_health 反映,但不计 fail、不进退出码。
                gap += 1
                print(f"[gap] {mid} {msg}", flush=True)
                log_collect(date, mid, "error", msg)
            else:
                # 真失败(配置缺失 no direct.fetch_* / 采集异常 direct:* error:)
                fail += 1
                print(f"[fail] {mid} {msg}", flush=True)
                log_collect(date, mid, "error", msg)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"[fail] {mid} {e}", flush=True)
            log_collect(date, mid, "error", str(e))
    print(f"=== direct metrics 补采 ok={ok} gap={gap} fail={fail} ===", flush=True)
    # 退出码: 任一 direct metric 真失败即非 0(供 backfill 总退出码聚合; 2026-09-09 #84 C4)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
