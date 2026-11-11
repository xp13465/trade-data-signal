#!/usr/bin/env python3
"""check_s06_freshness.py - S06 快照新鲜度检查(S06 每日重生链路第三件, 2026-08-26)

【目的】kelly_mode_s06_state.json 的 coverage_end 落后最近已入库交易日 >1 个交易日时
  走告警路径(subject「S06 快照过期 N 日」), 防「生成链路断了/输入断更」静默过期——
  前端按信号日期取 effective_mode, 超覆盖期 fail-open 不拦截(README 公示), 快照过期
  = S06 档静默退化为不拦截, 用户无感知, 必须监控层可见。
【判定口径】
  - 「最近已入库交易日」锚 = csi1000-all.json ohlc 末日期(指数序列最后一天即最近入库
    交易日, 不另引日历源; csi1000 自身断更由 update_all 漏跑监控 schedule_monitor 维度1
    覆盖——本脚本只管「快照 vs 已入库数据」的相对新鲜度, 边界诚实标注)。
  - N = index ohlc 完整序列中「末日期」与「coverage_end」的下标差; **以 index ohlc 完整
    交易日序列为标尺**(指数日历天然完整含节假日对齐, 快照自身 daily 在落后时会缺新日期、
    不能当标尺——首版用 daily 当标尺的口径已在 dry 单测场景1 证伪修正)。coverage_end
    不在 index 日历中(理论不可能, 数据源重写历史才可能发生)→ 按 N=9999 无法判定处理,
    方向=宁可误报不漏报。
  - N > 1 → 过期(FRESH_FAIL): 盘后链正常时 T 日 20:35 重生后 coverage_end=T, 次日全天
    N=1(容忍, 当天 20:35 前属正常窗口); 连续漏跑一天到 T+2 才 N=2 触发, 与任务书
    「落后最近交易日 >1 个交易日」逐字一致。
  - generated_at 只打印供排查不参与判定: coverage_end 是数据语义锚, 「刚生成但输入没
    更新」(generated_at 新 / coverage_end 旧)同样能抓到。
【告警】--notify 才写事件/通知。持续故障复用 alert_state 中同一事件，warning 携带
  ops refs；每轮重新交 notify 检查入队/逐渠道回执，不能用「曾入队」替代投递成功。
  真实恢复更新 requires_action=false，既有 warning/digest 在发送前重验并作废旧事件。
  不发恢复邮件；下一次故障新 event_id，不继承旧 ACK/回执。旧无 refs 队列保留 unknown，
  不按标题删除。共享状态损坏时保留原字节、响亮报错并直发未知故障，不猜健康。
【dry 单测】--snap/--index 显式传构造样本路径即可验证判定与退出码(判定纯相对日期,
  无 now 依赖, 不需要假时钟)。复现命令见文件尾单测段注释。
【输入依赖】--repo(默认 trade-data): static-site/data/{kelly_mode_s06_state,index/csi1000-all}.json
【输出】stdout 判定行 + exit 0=新鲜 / 1=过期 / 2=无法判定(文件缺失或解析失败)
"""
from __future__ import annotations

import argparse
import json
import os
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))  # #245 批2 W1: 台账 source 溯源
import hashlib
import sys
from pathlib import Path

# absolute() 非 resolve(): 保持 trade-data/scripts symlink 字面路径,
# 使子进程 notify.py 的 REPO 探测落在与调用方(schedule_monitor flusher)同一棵树
SCRIPT_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPT_DIR))
from ops_legacy_events import observe, dispatch  # noqa: E402
# 数据仓候选: env 注入(REPO/GIT_REPO/MAIN_REPO, 与 pick_repo.candidate_repos 同类语义)优先,
# 云上单仓(REPO=GIT_REPO=MAIN_REPO=/home/ubuntu/code/trade-data-signal)env 排最前;
# env 缺失回退 macOS 本机 trade-data(向后兼容, 行为不变)。云上若仍用本机硬编码会读不到
# static-site/data → 每轮 rc=2 且新鲜度兜底告警失守(2026-09-13 迁移残留修)。
DEFAULT_REPO_CANDIDATES = [
    Path(c) for c in (
        os.environ.get("REPO", ""),
        os.environ.get("GIT_REPO", ""),
        os.environ.get("MAIN_REPO", ""),
        "/Users/linhuichen/code/trade-data",
    ) if c
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "static-site" / "data").exists()),
                    DEFAULT_REPO_CANDIDATES[0])


def load_daily_dates(snap_path: Path) -> tuple[list[str], dict]:
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    return [str(r["date"]) for r in snap["daily"]], snap


def judge(idx_dates: list[str], cov_end: str, idx_last_date: str) -> int:
    """N = (index 末日期下标 - coverage_end 下标), 以 index ohlc 完整交易日序列为标尺。

    标尺必须用 index 序列而非快照 daily: 快照落后时 index 新增日期不在快照 daily 里,
    用 daily 当标尺会走「超覆盖期」分支失真(首版 bug, dry 单测场景1 抓出)。"""
    if cov_end not in idx_dates:
        # 快照 coverage_end 不在 index 日历中(理论上不可能: 快照由该序列生成;
        # 数据源复权重写历史时可能发生) → 按无法判定最深处理, 方向=宁可误报不漏报
        return 9999
    return idx_dates.index(idx_last_date) - idx_dates.index(cov_end)


def main() -> int:
    ap = argparse.ArgumentParser(description="S06 快照新鲜度检查(coverage_end vs 最近已入库交易日)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="数据仓根(trade-data)")
    ap.add_argument("--snap", default=None, help="显式指定快照 JSON(dry 单测用, 默认 <repo>/static-site/data/kelly_mode_s06_state.json)")
    ap.add_argument("--index", default=None, help="显式指定 csi1000-all.json(dry 单测用)")
    ap.add_argument("--notify", action="store_true",
                    help="过期真发 defer_warning 入聚合队列(默认 dry 只打印, 单测安全)")
    args = ap.parse_args()
    repo = Path(args.repo)
    snap_path = Path(args.snap) if args.snap else repo / "static-site" / "data" / "kelly_mode_s06_state.json"
    idx_path = Path(args.index) if args.index else repo / "static-site" / "data" / "index" / "csi1000-all.json"

    key = "producer_s06|" + hashlib.sha256(
        json.dumps([str(snap_path.absolute()), str(idx_path.absolute())]).encode()).hexdigest()

    def probe():
        dates, snap = load_daily_dates(snap_path)
        idx_dates = [str(x["date"]) for x in json.loads(idx_path.read_text(encoding="utf-8"))["ohlc"]]
        if not idx_dates or not dates:
            raise ValueError("index ohlc 或快照 daily 为空")
        cov_end, idx_last = dates[-1], idx_dates[-1]
        n = judge(idx_dates, cov_end, idx_last)
        # A future/unordered snapshot cannot certify recovery.
        if n < 0 or idx_dates != sorted(set(idx_dates)) or dates != sorted(set(dates)):
            raise ValueError("日期序列乱序、重复或快照超前，不能证明恢复")
        detail = (f"coverage_end={cov_end} 落后最近已入库交易日 {idx_last} 共 {n} 个交易日 "
                  f"(阈值>1 触发); generated_at={snap.get('generated_at', '?')}。"
                  "前端超覆盖期 fail-open 不拦截=S06 档静默退化，请查快照生成和输入链路。")
        return {"action": n > 1, "message": detail, "coverage_end": cov_end, "n": n}

    refs = None
    try:
        facts, refs = observe(repo, key, probe) if args.notify else (probe(), None)
    except Exception as exc:
        print(f"S06_FRESH_ERROR 状态/输入无法判定: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.notify:
            try:
                dispatch(repo, SCRIPT_DIR / "notify.py", "[告警] S06 新鲜度无法判定",
                         "检查输入或共享事件状态失败，不能证明恢复：" + str(exc), None,
                         source="check_s06_freshness.py")
            except Exception as send_exc:
                print(f"[s06-fresh] 未确认告警: {send_exc}", file=sys.stderr)
        return 2
    if not facts["action"]:
        print("S06_FRESH_OK " + facts["message"])
        return 0
    print("S06_FRESH_FAIL " + facts["message"])
    if args.notify:
        try:
            status = dispatch(repo, SCRIPT_DIR / "notify.py", f"S06 快照过期 {facts['n']} 日",
                              facts["message"], refs, warning=True, source="check_s06_freshness.py")
            if status not in ("deferred", "digested", "sent", "suppressed", "superseded"):
                print(f"[s06-fresh] 告警未完成({status})，下轮重试", file=sys.stderr)
        except Exception as exc:
            print(f"[s06-fresh] 告警未完成，下轮重试: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
