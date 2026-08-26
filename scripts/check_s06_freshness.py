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
  - N = (index 末日期在快照 daily 交易日序列中的下标) - (coverage_end 下标); 用快照自身
    daily 序列做交易日标尺(与 coverage_end 同源, 无节假日误判)。
  - N > 1 → 过期(FRESH_FAIL): 盘后链正常时 T 日 20:35 重生后 coverage_end=T, 次日全天
    N=1(容忍, 当天 20:35 前属正常窗口); 连续漏跑一天到 T+2 才 N=2 触发, 与任务书
    「落后最近交易日 >1 个交易日」逐字一致。
  - generated_at 只打印供排查不参与判定: coverage_end 是数据语义锚, 「刚生成但输入没
    更新」(generated_at 新 / coverage_end 旧)同样能抓到。
【告警】--notify 时才真发: notify.defer_warning 入聚合队列(schedule_monitor 尾部统一
  flush 批发), 同一 (coverage_end, N) 状态只 defer 一次(N 加深才再报), 状态记
  data/s06_fresh_alert_state.json(防 15min 监控周期重复轰炸); 恢复(N<=1)清状态不发恢复
  邮件(快照链正常重生本身即恢复, 免恢复轰炸)。默认 dry 只打印(单测/手动排查安全)。
【dry 单测】--snap/--index 显式传构造样本路径即可验证判定与退出码(判定纯相对日期,
  无 now 依赖, 不需要假时钟)。复现命令见文件尾单测段注释。
【输入依赖】--repo(默认 trade-data): static-site/data/{kelly_mode_s06_state,index/csi1000-all}.json
【输出】stdout 判定行 + exit 0=新鲜 / 1=过期 / 2=无法判定(文件缺失或解析失败)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# absolute() 非 resolve(): 保持 trade-data/scripts symlink 字面路径,
# 使子进程 notify.py 的 REPO 探测落在与调用方(schedule_monitor flusher)同一棵树
SCRIPT_DIR = Path(__file__).absolute().parent
DEFAULT_REPO_CANDIDATES = [
    Path("/Users/linhuichen/code/trade-data"),
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "static-site" / "data").exists()),
                    DEFAULT_REPO_CANDIDATES[0])
STATE_PATH_NAME = "s06_fresh_alert_state.json"   # data/s06_fresh_alert_state.json(不进 git)


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

    try:
        dates, snap = load_daily_dates(snap_path)
        idx_ohlc = json.loads(idx_path.read_text(encoding="utf-8"))["ohlc"]
    except FileNotFoundError as e:
        print(f"S06_FRESH_ERROR 文件缺失: {e.filename}")
        return 2
    except (json.JSONDecodeError, KeyError) as e:
        print(f"S06_FRESH_ERROR 解析失败: {type(e).__name__}: {e}")
        return 2
    if not idx_ohlc or not dates:
        print("S06_FRESH_ERROR index ohlc 或快照 daily 为空")
        return 2

    idx_dates = [str(x["date"]) for x in idx_ohlc]
    idx_last_date = str(idx_ohlc[-1]["date"])
    cov_end = dates[-1]
    gen_at = snap.get("generated_at", "?")
    n = judge(idx_dates, cov_end, idx_last_date)
    if n <= 1:
        print(f"S06_FRESH_OK coverage_end={cov_end} index末={idx_last_date} 落后={n}个交易日 generated_at={gen_at}")
        _clear_state(repo)
        return 0
    msg = f"S06 快照过期 {n} 日"
    detail = (f"coverage_end={cov_end} 落后最近已入库交易日 {idx_last_date} 共 {n} 个交易日 "
              f"(阈值>1 触发); generated_at={gen_at}。前端超覆盖期 fail-open 不拦截=S06 档静默退化, "
              f"请查 s06_snapshot_launchd.log(gen/check/R2 三段)与 update_all 是否漏跑。")
    print(f"S06_FRESH_FAIL {msg}: {detail}")

    if args.notify:
        if _defer_once(repo, cov_end, n, msg, detail):
            try:
                # 子进程调 notify.py CLI(--tier warning → defer_warning 入聚合 buffer),
                # 不用 import: Path(__file__).resolve() 会穿透 trade-data/scripts→trade/scripts
                # symlink 致 notify.REPO 锁到 trade 树, 而 flusher(schedule_monitor)在
                # trade-data 树 → 告警写错 buffer 永不被消费(静默丢失)。
                # absolute() 保持 symlink 字面路径, 与调用方同树。
                subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "notify.py"),
                     msg, detail.replace("\n", "<br>"),
                     "--tier", "warning", "--from-prefix", "[告警·聚合]"],
                    capture_output=True, text=True, timeout=60, check=False,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[s06-fresh] defer_warning 失败(不影响退出码): {e}", file=sys.stderr)
        else:
            print("[s06-fresh] 同状态已告警过, 抑制重复(defer 跳过)", file=sys.stderr)
    return 1


def _state_path(repo: Path) -> Path:
    return repo / "data" / STATE_PATH_NAME


def _defer_once(repo: Path, cov_end: str, n: int, msg: str, detail: str) -> bool:
    """同一 (coverage_end, N) 状态只 defer 一次; N 加深再报。返回是否需要真 defer。"""
    p = _state_path(repo)
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    if st.get("coverage_end") == cov_end and st.get("n") == n:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"coverage_end": cov_end, "n": n, "msg": msg}, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)
    return True


def _clear_state(repo: Path) -> None:
    """恢复新鲜即清状态(下次过期可再报); 不发恢复邮件。"""
    try:
        _state_path(repo).unlink(missing_ok=True)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
