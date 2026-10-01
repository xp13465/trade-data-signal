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
- gap = 数据源无数据(collect_direct 返回空且 msg 含「多源皆败无数据」),归属按凌晨槽判定
       (2026-09-30 资金面监控盲点修复 + 2026-10-01 #132 时点漂移修复,
       memory alert-denoise-keep-fault-discriminator):
       **凌晨槽(02:00, 判定= BACKFILL_SLOT 存在且实际时点 < 05:00)** = 结构性预期缺口
       (新浪源 T+1、目标日=当日必败),仍计 gap 静默
       (9/14-9/30 十七次 gap/五次 ok),仍 log_collect error 让 collect_health 通道反映,
       但不计 fail、不影响退出码——2026-09-09 #84 reviewer P1-1 降噪保留此槽;
       **非凌晨槽(16:35/21:00)** = 真正兜底槽每次都补回来,此刻六源全败=真故障
       (前端 fetch_market_fund_flow 6 源串行兜底全败被静默=监控盲区根因),必须计 fail
       → 退出码非 0 → schedule_monitor 照常报。
- fail = 真失败(采集异常崩溃 / 非凌晨槽多源皆败 / no direct.fetch_* 配置缺失 / direct:* error:
       采集异常 / 抛异常),计入退出码 → backfill 总退出码非 0 → schedule_monitor 照常报,
       保留 C4(#84)修「主采集失败静默 exit 0」盲区的监控价值。

退出码:0=无真失败(全成功或仅凌晨槽数据源缺口);1=存在至少一个真失败
       (含非凌晨槽多源皆败)。

输入依赖:REPO 环境变量指向主库目录(由 backfill_metrics.sh 设定,默认
/Users/linhuichen/code/trade-data);cwd 须在 REPO(app.* import 依赖)。
BACKFILL_SLOT 环境变量(backfill_metrics.sh L25 export,`date +%H%M`)用于槽位判定:
02:00 凌晨槽、16:35/21:00 兜底槽。凌晨槽判定(2026-10-01 #132)不再依赖 env 串前缀
(「0200」),改为 BACKFILL_SLOT 存在 + 实际时点 < 05:00 的宽限窗口——mac 休眠唤醒延迟致
02:00 槽在 03:00+ 才启动(BACKFILL_SLOT=0300)仍判凌晨槽,摘掉"唤醒晚几小时"的时点漂移;
05:00 后(或手动/update_all 无 env)一律按非凌晨槽保守处理(该有数据而没有=真故障须报)。

输出:stdout 进度(追加进 backfill_{STAMP}.log),collect_log 状态。
复现:bash scripts/backfill_metrics.sh(3 槽位 launchd 调用)。
"""
import datetime as dt
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

GAP_MARKER = "多源皆败无数据"  # collect_direct 空返回的固定 msg(数据源无数据=正常缺口)


def _is_morning_slot(now: dt.datetime | None = None) -> bool:
    """槽位判定: 是否为凌晨预期缺口槽(02:00)。

    2026-10-01 #132 时点漂移修复: 原实现用 `BACKFILL_SLOT.startswith("02")` 判凌晨槽,
    但 mac 休眠唤醒延迟会致 02:00 槽在 03:00+ 才启动 → BACKFILL_SLOT=0300 → 被判非凌晨
    → 02:00 槽的结构性预期缺口误判为真故障 → exit 1 → schedule_monitor 假 SEVERE。
    现改为**按实际时点判定**: BACKFILL_SLOT 存在(本槽语义为 backfill-evening 槽位)
    且实际时点 < 05:00(宽限窗口)即仍视为凌晨槽, 不再依赖 env 串前缀。

    为什么 02:00 是结构性预期缺口: 新浪源 T+1、该槽目标日=当日, 必败
    (2026-09-30 实测 9/14-9/30 十七次 gap/五次 ok)。16:35/21:00 是真正兜底槽每次
    都能补回来——它们出现「多源皆败」=真故障(16:35/21:00 六源全败)。
    返回 True = 凌晨槽, gap 属结构性预期应静默(仍 log_collect error 反映 collect_health)。

    保留真故障判别维度(memory alert-denoise-keep-fault-discriminator):
    - 仍报: 非 gap 失败(direct:* error/抛异常/no config)无条件计 fail 与本判定无关;
      05:00 后(唤醒延迟超整夜)仍六源全败=该有数据而没有=真故障计 fail。
    - 不再报: 02:00 槽唤醒延迟几小时(实际时点 < 05:00)的 gap。
    - 无 env(手动跑/update_all)= 非凌晨槽, gap 按真故障计 fail(保守不放过)。
    """
    slot = os.environ.get("BACKFILL_SLOT", "")
    if not slot:
        return False
    now = now or dt.datetime.now()
    return now.hour < 5


def main() -> int:
    cfg = load_config()
    date = last_trading_day()
    morning = _is_morning_slot()
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
                # 数据源无数据(多源皆败)的归属按槽位区分(2026-09-30 资金面监控盲点修复,
                # memory alert-denoise-keep-fault-discriminator):
                # - 凌晨槽(02:00): 结构性预期缺口(新浪源 T+1、目标日=当日必败), 仍计 gap
                #   静默(9/14-9/30 十七次 gap/五次 ok), 缺口由 collect_health + check_fund
                #   freshness 检查器反映, 不计 fail、不进退出码。
                # - 非凌晨槽(16:35/21:00): 真正兜底槽每次都补回来, 此刻六源全败=真故障
                #   (六源全败被当正常缺口的盲区根因), 必须计 fail → 退出码非 0 →
                #   schedule_monitor 照常告警。不再静默。
                if morning:
                    gap += 1
                    print(f"[gap] {mid} {msg} (02:00 槽预期缺口, 静默)", flush=True)
                    log_collect(date, mid, "error", msg)
                else:
                    fail += 1
                    print(f"[fail] {mid} {msg} (非凌晨槽多源全败=真故障, 计入退出码)", flush=True)
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
