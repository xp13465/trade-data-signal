#!/usr/bin/env python3
"""场外基金全史净值导出(per-fund 懒加载 JSON,#11 基金评分弹窗「净值走势」数据层)。

目的:
  从 public_fund.db fund_daily_nav 表导出每只基金的全历史日净值到
  static-site/data/fund_nav/{code}.json, 供前端基金评分弹窗(openFundScoreDetailModal)
  「净值走势」区块 period tab(30d/3m/6m/1y/3y/5y/all)懒加载渲染长历史走势。
  复刻 #10 ETF 弹窗长历史整套机制(commit fa1ca6e3b: export_etf_hist.py /
  upload-etf-hist 增量指纹 / check_etf_hist / update_all.sh 挂载 / period tab)。

方法口径:
  - 覆盖范围 = fund_daily_nav 全部 distinct fund_code(26118 只, 含评分列表外基金,
    未来扩展零成本); 逐只查询走 idx_daily_nav_code 索引。
  - 输出结构(nav 升序旧->新; date=该基金最新净值日):
      {"date": "20260824", "code": "000001", "name": "华夏成长混合",
       "count": 1234, "source": "fund_daily_nav 表全史日净值(...)",
       "nav": [["20210705", 1.2345, 12.3456], ...]}
    nav 每行 [date, unit_nav, acc_nav](acc_nav 缺失为 null)。
  - **不放 exported_at 字段**(与 etf/{code}-all.json 的差异点): 文件内容只在净值序列
    真变化时变化 -> R2 增量指纹(cmd_upload_fund_nav 整文件 md5)天然免疫"天天判全变";
    清盘老基金序列冻结 -> 内容不变 -> 指纹不变 -> 自然跳过, 每日真重传仅活跃基金。
  - 时效口径(诚实标注): 本脚本挂 update_all 17:50 链, 当日基金净值多在晚间公布,
    实际入图最新净值通常为 T-1 日(T 日净值次日 17:50 后可见), 走势图历史序列场景无感。
  - 文件名安全化: code 只保留 [A-Za-z0-9_](防御 DB 脏值路径注入, 同 export_etf_hist.py)。

输入依赖: $REPO/data/public_fund.db fund_daily_nav 表(REPO env 缺省 trade 树;
  连接复用 app.collector.public_fund 的 DB_PATH/STATIC_DATA_DIR, 与 export_fund_score.py
  同机制——从 trade-data 跑读实时库写 trade-data/static-site/data/)。
输出: static-site/data/fund_nav/{code}.json(~26KB/只均, 全量 ~700MB; gitignore 不进 git,
  R2 上传走 upload_r2.py upload-fund-nav -> R2 fund_nav/ 前缀, deploy.sh/update_all.sh 已接入)。
关键参数种子: 无采样/截断参数(全史全量); PF_STAGE0 无关。

用法:
  .venv/bin/python scripts/export_fund_nav.py                    # 全量 distinct code
  .venv/bin/python scripts/export_fund_nav.py --limit 3          # 小规模验证
  .venv/bin/python scripts/export_fund_nav.py --codes 000001,110011

定时链路: update_all.sh(fund_score 导出后同步跑 + rsync + upload-fund-nav);
  deploy.sh run_r2_upload 列表含 upload-fund-nav(R2 三步同步 §22)。

复现命令:
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/export_fund_nav.py
  # 抽查核对(DB 逐位): sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db \
  #   "SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='000001' ORDER BY date DESC LIMIT 3;"
  # 校验: .venv/bin/python scripts/check_data_integrity.py (含 check_fund_nav 抽样 DB<->产物逐位一致)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# 不用 .resolve(): scripts 在两树间 hardlink/symlink, resolve() 会绕回 trade 致输出路径错树
# (同 export_etf_hist.py L52 注释 / export_fund_score.py 同机制)
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.collector.public_fund import DB_PATH, STATIC_DATA_DIR  # noqa: E402

OUT_DIR = STATIC_DATA_DIR / "fund_nav"
# 文件名安全化:只允许字母数字下划线(基金 code 为 6 位数字,防御性过滤)
_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def _safe_code(code: str) -> str:
    return _SAFE_RE.sub("_", str(code or "").strip())


def _atomic_write_json(out: Path, payload: dict) -> None:
    """原子写 JSON（2026-08-25 codex review high 修复）。

    先写同目录唯一 .tmp（带 pid 防并发），flush + os.fsync 落盘后，
    再 os.replace 为最终文件。进程被 kill / 磁盘满 / 异常时只留 .tmp 残留，
    不会污染最终路径被部署链消费；异常时清理 .tmp 再向上抛，由调用方 gate。
    """
    tmp = out.with_name(f"{out.name}.tmp.{os.getpid()}")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)  # 原子替换，POSIX 保证不会读到半截文件
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="场外基金全史净值导出 fund_nav/{code}.json")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只(0=全部,小规模验证)")
    parser.add_argument("--codes", type=str, default="", help="逗号分隔指定 code 列表(覆盖全量)")
    args = parser.parse_args()

    import sqlite3

    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        if args.codes:
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        else:
            rows = conn.execute(
                "SELECT DISTINCT fund_code FROM fund_daily_nav "
                "WHERE fund_code IS NOT NULL AND fund_code != ''"
            ).fetchall()
            codes = sorted(r["fund_code"] for r in rows)
        if args.limit > 0:
            codes = codes[: args.limit]

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        empty_count = 0
        done = 0
        for code in codes:
            nav_rows = conn.execute(
                "SELECT date, unit_nav, acc_nav FROM fund_daily_nav "
                "WHERE fund_code=? AND unit_nav IS NOT NULL ORDER BY date ASC",
                (code,),
            ).fetchall()
            name_row = conn.execute(
                "SELECT fund_name FROM fund_daily_nav WHERE fund_code=? "
                "AND fund_name IS NOT NULL AND fund_name != '' "
                "ORDER BY date DESC LIMIT 1",
                (code,),
            ).fetchone()
            nav = [[r["date"], r["unit_nav"], r["acc_nav"]] for r in nav_rows]
            payload = {
                "date": (nav[-1][0] if nav else ""),
                "code": code,
                "name": (name_row["fund_name"] if name_row else code),
                "count": len(nav),
                # 口径标注(§21 公示精神:隐式规则显式化;前端 tooltip 引用)
                "source": "fund_daily_nav 表全史日净值(基金公司披露口径, T+1 入图)",
                "nav": nav,
            }
            if not nav:
                empty_count += 1
            out = OUT_DIR / f"{_safe_code(code)}.json"
            _atomic_write_json(out, payload)
            total_bytes += out.stat().st_size
            done += 1
            if done % 500 == 0:
                print(f"  [{done}/{len(codes)}] 累计 {total_bytes / 1024 / 1024:.1f}MB "
                      f"({time.time() - t0:.1f}s)", flush=True)
    finally:
        conn.close()

    elapsed = time.time() - t0
    print(f"✓ 完成 {done} 只 -> {OUT_DIR} (空数据 {empty_count} 只) "
          f"总计 {total_bytes / 1024 / 1024:.1f}MB 耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    main()
