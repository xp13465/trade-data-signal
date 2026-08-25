#!/usr/bin/env python3
"""ETF 全史日K导出(per-ETF 懒加载 JSON,#10 ETF 评分弹窗「30天外长历史」数据层)。

目的:
  从 etf_daily 表导出每只 ETF 的全历史前复权日K OHLC 到 static-site/data/etf/{code}-all.json,
  供前端 ETF 评分弹窗(openEtfScoreDetailModal)period tab(3m/6m/1y/3y/5y/all)懒加载渲染
  30 天外长历史走势。复刻 index/{iid}-all.json 既有模式(docs/chart-refactor-config-plan.md 需求2
  + docs/chart-p2p3-data-source-research.md P2 节方案)。

方法口径:
  - 前复权逻辑**复用** scripts/export_etf_score_list.py 的 _fetch_recent_ohlc(days 给大值即全史),
    单一事实源不复制(adj_factor(t)=(accum_nav(t)/close(t))/(accum_nav(latest)/close(latest)),
    accum_nav 缺失行降级未复权 close,QDII 跨境 ETF 同现有兜底)。
  - 覆盖范围 = etf_daily 全部 distinct etf_code(1520+ 只,含评分列表外 ETF,未来扩展零成本);
    OHLC 不全的行由 _fetch_recent_ohlc 内部过滤(四列非空才入样)。
  - 输出结构(复用 e.ohlc 格式,前端零改造解析):
      {"date": "20260821", "code": "510050", "name": "50ETF华夏",
       "count": 5201, "adj": "forward_accum_nav", "ohlc": [[date,o,h,l,c],...]}
    ohlc 升序(旧->新);date=该 ETF 最新交易日;count=ohlc 行数。
  - 文件名安全化:code 只保留 [A-Za-z0-9_](防御 DB 脏值路径注入,index 侧 iid 受控未处理,
    本侧 DB 来源加同构防御)。

输入依赖: $REPO/data/etf_national_team.db etf_daily 表(REPO env 缺省 trade 树,与
  export_etf_score_list.py 同机制:trade-data/scripts 是 hardlink,从 trade-data 跑读实时库)。
输出: static-site/data/etf/{code}-all.json(~29KB/只均,全量 ~40MB;R2 上传走
  upload_r2.py upload-etf-hist -> R2 etf/ 前缀,deploy.sh/update_all.sh 已接入)。
关键参数种子: HIST_DAYS=99999(_fetch_recent_ohlc days 参数,cutoff=days*2 日历日回溯≈547 年前
  即无有效截断,LIMIT 同步放大 → 等价全史查询)。

用法:
  .venv/bin/python scripts/export_etf_hist.py                    # 全量 distinct code
  .venv/bin/python scripts/export_etf_hist.py --limit 3          # 小规模验证
  .venv/bin/python scripts/export_etf_hist.py --codes 510050,510300

定时链路: update_all.sh(etf_score_list 导出后同步跑 + rsync + upload-etf-hist);
  deploy.sh run_r2_upload 列表含 upload-etf-hist(R2 三步同步 §22)。

复现命令:
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/export_etf_hist.py
  # 抽查核对(DB 逐位): sqlite3 $REPO/data/etf_national_team.db \
  #   "SELECT date,open,high,low,close FROM etf_daily WHERE etf_code='510050' ORDER BY date DESC LIMIT 1;"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# 不用 .resolve(): trade-data/scripts 是 trade/scripts 的 hardlink (同 inode),
# resolve() 会跳回 trade 致输出路径绕回 trade (同 export_etf_score_list.py L81 注释)
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.collector.etf_national_team import get_conn  # noqa: E402

# 复用既有前复权查询(单一事实源,防双份维护分叉):days 大值 => cutoff/LIMIT 失效 => 全史
sys.path.insert(0, str(ROOT / "scripts"))
from export_etf_score_list import _fetch_recent_ohlc  # noqa: E402

OUT_DIR = ROOT / "static-site" / "data" / "etf"
# 全史天数参数(见 docstring 关键参数种子)
HIST_DAYS = 99999
# 文件名安全化:只允许字母数字下划线(ETF code 为 6 位数字,防御性过滤)
_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def _safe_code(code: str) -> str:
    return _SAFE_RE.sub("_", str(code or "").strip())


def _atomic_write_json(out: Path, payload: dict) -> None:
    """原子写 JSON(2026-08-25 同款修复, 与 export_fund_nav.py 一致)。

    先写同目录唯一 .tmp(pid 防并发), flush + os.fsync 落盘后 os.replace 为最终
    文件。进程 kill/磁盘满只留 .tmp 残留, 不会污染最终路径被部署链消费;
    异常清理 .tmp 再上抛。
    """
    tmp = out.with_name(f"{out.name}.tmp.{os.getpid()}")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="ETF 全史日K导出 etf/{code}-all.json")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只(0=全部,小规模验证)")
    parser.add_argument("--codes", type=str, default="", help="逗号分隔指定 code 列表(覆盖全量)")
    args = parser.parse_args()

    t0 = time.time()
    conn = get_conn()
    try:
        if args.codes:
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        else:
            rows = conn.execute(
                "SELECT DISTINCT etf_code FROM etf_daily WHERE etf_code IS NOT NULL AND etf_code != ''"
            ).fetchall()
            codes = sorted(r["etf_code"] for r in rows)
        if args.limit > 0:
            codes = codes[: args.limit]

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        export_date = time.strftime("%Y%m%d")
        total_bytes = 0
        empty_count = 0
        done = 0
        for code in codes:
            ohlc = _fetch_recent_ohlc(code, conn, days=HIST_DAYS)
            name_row = conn.execute(
                "SELECT etf_name FROM etf_daily WHERE etf_code=? "
                "AND etf_name IS NOT NULL AND etf_name != '' ORDER BY date DESC LIMIT 1",
                (code,),
            ).fetchone()
            payload = {
                "date": (ohlc[-1][0] if ohlc else ""),
                "exported_at": export_date,
                "code": code,
                "name": (name_row["etf_name"] if name_row else code),
                "count": len(ohlc),
                # 口径标注(§23.6 公示精神:隐式规则显式化;前端 tooltip 引用)
                "adj": "forward_accum_nav",
                "source": "etf_daily 表全史前复权日K(accum_nav 因子,缺失行降级未复权)",
                "ohlc": ohlc,
            }
            if not ohlc:
                empty_count += 1
            fname = f"{_safe_code(code)}-all.json"
            out = OUT_DIR / fname
            _atomic_write_json(out, payload)
            total_bytes += out.stat().st_size
            done += 1
            if done % 200 == 0:
                print(f"  [{done}/{len(codes)}] 累计 {total_bytes / 1024 / 1024:.1f}MB "
                      f"({time.time() - t0:.1f}s)", flush=True)
    finally:
        conn.close()

    elapsed = time.time() - t0
    print(f"✓ 完成 {done} 只 -> {OUT_DIR} (空数据 {empty_count} 只) "
          f"总计 {total_bytes / 1024 / 1024:.1f}MB 耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    main()
