#!/usr/bin/env python3
"""gen_kelly_mode_s06_state.py - S06 降亏动态模式「单源快照」生成器(codex-task-20260825-001, B级, 用户已拍板)

【目的】为前端可选实验档 s06(大盘领先切换)生成唯一事实源快照 static-site/data/kelly_mode_s06_state.json。
S06 不是固定键组合: 按「中证1000 20日涨幅 - 沪深300 20日涨幅」与冻结阈值比较, 在 a9(A进攻王) 与
new15(NEW14+1·15键) 两个基座间动态切换。前端只读本快照按日期取 effective_mode, 禁止前端自算因子/阈值
(§23.6 同精神: 前端不自算宇宙; 本文件=阈值与状态机唯一事实源, 前端文案出现数值仅为 §21 公示)。

【方法口径】(与 codex 深度验证 /tmp/codex-auto/external_factor_v6.py sticky_array + external_factor_v6b.py
size_spread + s06_grid_selection_freeze.py 冻结值逐位对齐, 报告=docs/kelly/analysis/codex-auto-external-factor-final-20260825.md)
  - 因子: size_spread(t) = (csi1000_close[t]/csi1000_close[t-20] - 1)*100 - (hs300_close[t]/hs300_close[t-20] - 1)*100
    (纯 trailing 20 日收益, 不含未来 K 线; csi1000∩hs300 交集交易日序列, 前 20 日无值=null)
  - 判定: T 日收盘 premise(T) = size_spread(T) < THRESHOLD → T+1 日生效(防前视 §5.1⑥)
  - 状态机(sticky_array): 进入 A 立即(premise 真次日生效); 处于 A 时 premise 连续破坏 CONFIRM_DAYS 个
    交易日后切回兜底, 且 A 最短持有 MIN_HOLD_DAYS 个交易日; 首个交易日恒为兜底(off_base)
  - held 定义(codex008 F2 新语义, 2026-08-26 用户拍板): held = a9 生效交易日数——进入当日计 1,
    其后每个交易日递增(无论当日 premise 是否命中)。旧语义(held 只在命中日 +1)在持续非命中场景
    held 永久 < MIN_HOLD_DAYS → a9 锁死违反公示的 15 日确认退出语义, 已修复; 机检
    check_s06_state.py 独立第二实现同语义重写 + A5 锁死不变式断言防回归
  - 键集映射: effective_mode='a9' ↔ common.js _KELLY_FADE_MODE_PRESETS id=a9(A 进攻王);
              effective_mode='new15' ↔ id=new15(NEW14+1·15键)。回测对照锚点(codex008 F2 新语义
              引擎重跑 2026-08-26, 同引擎 s06_newsem_vs_14plus1.py): 验段净利 +100,572.43 /
              mdd -3,811.27 / 强平 +82,761.50 vs 静态 NEW14+1 +83,718.16。
              ⚠锚点漂移特性: S06 动态回测数字随输入指数序列每日更新而漂移(2026-08-25 首跑
              94,150.61 → 08-26 同引擎旧语义复跑 94,436.30), 公示取本注释同日重跑值;
              ⚠诚实标注 held 新语义分年差(vs 旧语义同日重跑): 2022 +1,014 / 2023 +2,019 /
              2024 +4,296 / 2025 -3,538(唯一变差年, 诚实标注不隐瞒) / 2026 +2,344,
              合计 +6,136(=100,572-94,436)

【输入依赖】$REPO/static-site/data/index/{csi1000,hs300}-all.json 的 ohlc.close 收盘序列(只读生产源,
  不写 DB 不碰根目录 data/)
【输出】${REPO}/static-site/data/kelly_mode_s06_state.json(schema 见 handoff docs/codex-reviews/
  s06-mode-implementation-handoff-20260825.md §四); 同步镜像一份到 ${GIT_REPO}/static-site/data/(rsync 渠道,
  deploy.sh 会 rsync ${REPO} 到 ${GIT_REPO}, 此处直写消除时序窗口, 同 deploy.sh 项6 先例)
【关键参数种子(⚠改任何一项必须同步: purpose-notes.js/app.js/lab.js 三处公示文案数值 + check_s06_state.py 机检)】
  THRESHOLD       = -3.524224785046781   # 2016-2020 选段 q30 冻结值(未用验段/全史分位调参, codex §三.5)
  CONFIRM_DAYS    = 15                   # A 前提连续破坏确认期(q20-q60×cd 敏感性全部胜静态 NEW14)
  MIN_HOLD_DAYS   = 10                   # A 最短持有交易日
【复现命令】python3 scripts/gen_kelly_mode_s06_state.py            # 默认 REPO=/Users/linhuichen/code/trade-data
           python3 scripts/gen_kelly_mode_s06_state.py --repo /path/to/trade-data [--git-repo /path/to/trade]
【确定性声明】状态机只依赖收盘历史序列, 同输入同输出; 新交易日只 append, 重跑不改变历史 daily 数组
  (指数历史 K 线若被数据源复权修正则整段重算——诚实标注: 属数据源修正而非算法变化)。

上线渠道(§22 三步, 由主控 merge 后执行或随盘后链): ①本脚本生成 $REPO+git 两处 static-site/data/
②R2 上传(upload_r2.py 对应命令) ③deploy.sh 随 export 链同步。前端 fetch=./data/kelly_mode_s06_state.json
(小文件本地渠), 备站经 app.js fetchJSON 主站 /data/ rewrite 兜底。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# ── 关键参数种子(S06 单一事实源; 前端禁第二份硬编码, 公示文案数值须与本处逐位一致) ──
THRESHOLD = -3.524224785046781   # 2016-2020 选段 q30 冻结值(codex s06_grid_selection_freeze.py)
CONFIRM_DAYS = 15                # A 前提连续破坏确认期(交易日)
MIN_HOLD_DAYS = 10               # A 最短持有交易日
ON_BASE = "a9"                   # premise 成立期间基座 = A 进攻王
OFF_BASE = "new15"               # 兜底基座 = NEW14+1·15键
LOOKBACK = 20                    # ret20 回看窗口(交易日)

MODE_ID = "s06"
SCHEMA_VERSION = 1


def load_closes(repo: str, name: str) -> dict[str, float]:
    path = os.path.join(repo, "static-site", "data", "index", f"{name}-all.json")
    with open(path, encoding="utf-8") as f:
        ohlc = json.load(f)["ohlc"]
    return {str(x["date"]): float(x["close"]) for x in ohlc if x.get("close") is not None}


def build_daily(dates: list[str], spread: dict[str, float]) -> list[dict]:
    """sticky_array 状态机(codex008 F2 新语义, 2026-08-26 用户拍板修复):
    T 日收盘判定、T+1 生效; 进入 on 立即(次日); held = a9 生效交易日数——进入当日计 1,
    其后每个交易日递增(无论当日 premise 是否命中); 退出需连续破坏 CONFIRM_DAYS 个交易日
    且 held 满 MIN_HOLD_DAYS。
    ⚠旧语义(held 只在命中日 +1, 逐位对齐 v6 sticky_array 抄袭无误但 v6 本身有锁死缺陷):
    持续非命中场景 held 永久 < MIN_HOLD_DAYS → `(broken<CD) or (held<MH)` 恒真 → a9 锁死,
    全史 457 天(16%) effective_mode 失真, 由 codex-claude2codex-20260826-008 F2 定性 P0;
    机检 check_s06_state.py 独立第二实现同语义 + A5 锁死不变式断言防回归。"""
    out: list[dict] = []
    cur = OFF_BASE          # cur = 上一交易日生效的基座
    broken = 0
    held = 0
    prev = None             # 决策日(前一交易日)
    for d in dates:
        sv = spread.get(d)
        p_today = (sv is not None and sv < THRESHOLD)      # d 日本身收盘出的信号(次日消费)
        if prev is None:
            ex = OFF_BASE                                   # 首日恒兜底(无决策日)
            dec_date = None
        else:
            p = spread.get(prev)
            hit = p is not None and p < THRESHOLD           # prev 日收盘判定 → d 日生效
            if cur == ON_BASE:
                if hit:
                    broken = 0
                else:
                    broken += 1
                held += 1   # 新语义: d 日仍处 a9 生效日则持有计数+1(无论当日 premise 是否命中)
                stay = (broken < CONFIRM_DAYS) or (held < MIN_HOLD_DAYS)
                ex = ON_BASE if stay else OFF_BASE
                if not stay:
                    held = 0
            else:
                ex = ON_BASE if hit else OFF_BASE
                if ex == ON_BASE:
                    held = 1    # 新语义: 进入当日计 1
                    broken = 0
            dec_date = prev
        out.append({
            "date": d,
            "size_spread": sv,                 # d 日收盘值(%); 回看窗内无值=null
            "premise": (None if sv is None else bool(p_today)),   # d 日收盘信号(供 T+1 用)
            "effective_mode": ex,              # d 日实际生效基座("a9"/"new15")
            "decision_date": dec_date,         # 产生该生效模式的决策日(=上一交易日)
        })
        cur = ex
        prev = d
    return out


def current_block(daily: list[dict]) -> dict:
    """current={date,mode,since}: 最新日生效基座 + 该模式连续生效起始日。"""
    if not daily:
        return {"date": None, "mode": OFF_BASE, "since": None}
    last = daily[-1]
    since = last["date"]
    mode = last["effective_mode"]
    for row in reversed(daily):
        if row["effective_mode"] != mode:
            break
        since = row["date"]
    return {"date": last["date"], "mode": mode, "since": since}


def main() -> int:
    ap = argparse.ArgumentParser(description="S06 降亏动态模式快照生成器(单源)")
    ap.add_argument("--repo", default="/Users/linhuichen/code/trade-data",
                    help="数据仓库根(static-site/data/index 输入与输出所在, 默认实时主库 trade-data)")
    ap.add_argument("--git-repo", default="/Users/linhuichen/code/trade",
                    help="git 仓库根(镜像输出 static-site/data/, 与 deploy.sh rsync 渠道一致)")
    args = ap.parse_args()

    csi = load_closes(args.repo, "csi1000")
    hs = load_closes(args.repo, "hs300")
    common_dates = sorted(set(csi) & set(hs))
    if not common_dates:
        print("✗ csi1000/hs300 无交集交易日", file=sys.stderr)
        return 1

    def roll_ret(series: dict[str, float], dates: list[str], n: int) -> dict[str, float]:
        vals = [series[d] for d in dates]
        return {dates[i]: (vals[i] / vals[i - n] - 1) * 100 for i in range(n, len(vals))}

    r_csi = roll_ret(csi, common_dates, LOOKBACK)
    r_hs = roll_ret(hs, common_dates, LOOKBACK)
    spread = {d: r_csi[d] - r_hs[d] for d in common_dates if d in r_csi and d in r_hs}
    # 快照覆盖期 = size_spread 有值的日期(交集序列去掉前 LOOKBACK 日)
    covered = [d for d in common_dates if d in spread]

    daily = build_daily(covered, spread)
    snap = {
        "version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode_id": MODE_ID,
        "threshold": THRESHOLD,
        "confirm_days": CONFIRM_DAYS,
        "min_hold_days": MIN_HOLD_DAYS,
        "lookback_days": LOOKBACK,
        "factor": "csi1000_ret20 - hs300_ret20 (%)",
        "on_base": ON_BASE,
        "off_base": OFF_BASE,
        "decision_timing": "T_close_signal_T_plus_1_execution",
        "coverage_start": covered[0] if covered else None,
        "coverage_end": covered[-1] if covered else None,
        "daily": daily,
        "current": current_block(daily),
        "_provenance": {
            "generator": "scripts/gen_kelly_mode_s06_state.py",
            "inputs": ["static-site/data/index/csi1000-all.json", "static-site/data/index/hs300-all.json"],
            "threshold_source": "2016-2020 选段 q30 冻结(codex s06_grid_selection_freeze.py, 未用验段/全史分位)",
            "backtest_anchor": "codex008-F2 新语义引擎重跑 2026-08-26(s06_newsem_vs_14plus1.py): val=+100572.43 mdd=-3811.27 forced=+82761.50 vs 静态NEW14+1 +83718.16; 分年差 vs 旧语义: 2022 +1014/2023 +2019/2024 +4296/2025 -3538(变差)/2026 +2344",
            "report": "docs/kelly/analysis/codex-auto-external-factor-final-20260825.md",
        },
    }

    body = json.dumps(snap, ensure_ascii=False, indent=1)
    targets = [
        os.path.join(args.repo, "static-site", "data", "kelly_mode_s06_state.json"),
        os.path.join(args.git_repo, "static-site", "data", "kelly_mode_s06_state.json"),
    ]
    for t in targets:
        os.makedirs(os.path.dirname(t), exist_ok=True)
        tmp = t + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, t)  # 原子写, 防半截文件被前端拉走
        print("✓ wrote", t, f"({len(body)} bytes)")

    n_a9 = sum(1 for r in daily if r["effective_mode"] == "a9")
    switches = sum(1 for i in range(1, len(daily)) if daily[i]["effective_mode"] != daily[i - 1]["effective_mode"])
    print(f"  coverage {covered[0]}~{covered[-1]} days={len(daily)} a9_days={n_a9} switches={switches} "
          f"current={snap['current']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
