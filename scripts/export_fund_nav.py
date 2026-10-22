#!/usr/bin/env python3
"""场外基金全史净值导出(桶化 JSON,#11 基金评分弹窗「净值走势」数据层)。

目的:
  从 public_fund.db fund_daily_nav 表导出每只基金的全历史日净值, **按确定性 hash 分桶**
  写入 static-site/data/nav_bucket/{xx}.json(xx=00-ff 共 256 桶, 每桶内含该桶基金 map),
  供前端基金评分弹窗(openFundScoreDetailModal)「净值走势」区块 period tab
  (30d/3m/6m/1y/3y/5y/all)懒加载渲染长历史走势。
  **桶化动机(2026-09-23, docs/ops/task-slow-rootcause-20260923.md §9B)**:
  原 per-code 输出(26458 个文件)致 R2 上传 PUT 次数随基金数增长(9-22 传 21957 个
  6225s 占 deploy 56%), 桶化后 PUT 次数固定 256, 上传耗时有界。
  分桶口径分叉说明: 任务书字面"按 code 前 2 位分桶"实测不可行(基金 code 6 位纯数字,
  前 2 位仅 71 种且分布极不均: 01 桶 201MB/00 桶 193MB 远超 100MB multipart 阈值,
  前端单拉 200MB 不可接受) → 改 **FNV-1a hash(code) 取末 8bit**(固定 256 桶, 均匀
  ~2MB/桶)。**前后端必须同一 hash 实现**(本脚本 _fund_bucket 与 app.js _fundNavBucket
  同源, 自测对账防第二份实现漂移, 见 §5.4⑦)。复刻 #10 ETF 弹窗长历史整套机制。

方法口径:
  - 覆盖范围 = fund_daily_nav 全部 distinct fund_code(26118 只, 含评分列表外基金,
    未来扩展零成本); 逐只查询走 idx_daily_nav_code 索引。
  - 输出结构(nav 升序旧->新; date=该基金最新净值日):
      桶文件 nav_bucket/{xx}.json = {"000001": {date/code/name/count/source/nav}, ...}
    即 {code: 单基金 payload} map; 单基金 payload 与原 per-code 文件逐位同构:
      {"date": "20260824", "code": "000001", "name": "华夏成长混合",
       "count": 1234, "source": "fund_daily_nav 表全史日净值(...)",
       "nav": [["20210705", 1.2345, 12.3456], ...]}
    nav 每行 [date, unit_nav, acc_nav](acc_nav 缺失为 null)。
  - **不放 exported_at 字段**(与 etf/{code}-all.json 的差异点): 桶内容只在净值序列
    真变化时变化 -> R2 增量指纹(cmd_upload_fund_nav 整文件 md5)天然免疫"天天判全变";
    清盘老基金序列冻结 -> 内容不变 -> 指纹不变 -> 自然跳过, 每日真重传仅活跃桶。
  - **流式分桶写(2026-09-23 codex 外审 P2 修复)**: 原实现把 26370 只 payload 全量
    累积进内存 buckets dict 再逐桶落盘(峰值 ~3.7GB, 导出机仅 3.6Gi 会 OOM/吃 swap
    慢到超时); 改为按 (桶, code) 排序后顺序遍历、遇新桶 flush 上一桶, 内存只驻留
    单桶 ~2MB(实测峰值 213MB)。输出逐位一致(桶内 {code: payload} map 按 code 升序,
    payload 同构), check_fund_nav + 全量 diff 对账验证通过。
  - 时效口径(诚实标注): 本脚本挂 update_all 17:50 链, 当日基金净值多在晚间公布,
    实际入图最新净值通常为 T-1 日(T 日净值次日 17:50 后可见), 走势图历史序列场景无感。
  - 桶化后 code 不进文件名(文件名为 {xx}.json 桶名, code 是桶内 map 的 key), 无路径注入面;
    code 为任意字符串(含 DB 脏值)时 FNV-1a 对同字符串两端仍一致, 不崩溃。

输入依赖: $REPO/data/public_fund.db fund_daily_nav 表(REPO env 缺省 trade 树;
  连接复用 app.collector.public_fund 的 DB_PATH/STATIC_DATA_DIR, 与 export_fund_score.py
  同机制——从 trade-data 跑读实时库写 trade-data/static-site/data/)。
输出: static-site/data/nav_bucket/{xx}.json(256 桶, 均匀 ~2MB/桶, 全量 ~527MB;
  gitignore 不进 git, R2 上传走 upload_r2.py upload-fund-nav -> R2 nav_bucket/ 前缀,
  2026-09-23 起由 update_all.sh 异步触发(fund_nav_upload_async.sh, 拆出主链等待区间),
  deploy.sh 不再接入)。
关键参数种子: 无采样/截断参数(全史全量); PF_STAGE0 无关。

增量刷新模式 `--daily-refresh`（#278, 2026-10-22 用户拍板方案 A）:
  公募日更(16:20/17:00)早于 17:50 全量链, 当日新净值/修正值已入库而 nav_bucket 产物还是旧值
  ⇒ deploy 内 fund_nav 闸门(阻断级)必 FAIL(根因 docs/ops/failed-units-rca-20261022.md)。
  修复 = 日更 deploy 前先用本脚本增量刷新净值桶。**与全量模式共用同一 `_build_payload`
  (同一 SQL/同一字段/同一 source 文案), 不写第二套口径**(§5.4⑦); 只重建「最近 N 天有净值
  写入的基金」所在桶, 且桶内容逐 code 比对未变则不重写(幂等, 无新净值时零写入)。
  候选窗口按 **DB 最新净值日期**往前推 N 天(默认 7), 不取本机时钟 ⇒ 非交易日/周末同样成立。
  桶间独立 ⇒ 默认按桶并行(min(4,CPU) 个 worker, `--workers`/`NAV_REFRESH_WORKERS` 可覆盖)。
  实测(2026-10-22 本机 mac, 26,126 只候选 / 256 桶 / 256 桶全变更): 串行 71.8s → 2 workers
  37.9s(产物与全量导出逐位一致); 云上按全量导出 43.6s→99s 的同比例估算 ≈86s(<2min 目标)。

用法:
  .venv/bin/python scripts/export_fund_nav.py                    # 全量 distinct code
  .venv/bin/python scripts/export_fund_nav.py --limit 3          # 小规模验证
  .venv/bin/python scripts/export_fund_nav.py --codes 000001,110011
  .venv/bin/python scripts/export_fund_nav.py --daily-refresh    # 公募日更 deploy 前增量刷新

定时链路: update_all.sh(export 后 rsync + 异步触发 fund_nav_upload_async.sh 走
  upload_r2.py upload-fund-nav; 2026-09-23 P1 起拆出主链等待区间, deploy.sh 不再含本通道)。
  public_fund_daily.sh 16:20/17:00(经 scripts/lib/nav_bucket_refresh.sh 调 --daily-refresh 增量刷新,
  2026-10-22 #278; 只对齐本地产物供 deploy 闸门, R2 上传仍由 17:50 全量链异步负责)。

复现命令:
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/export_fund_nav.py
  # 抽查核对(DB 逐位): sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db \
  #   "SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='000001' ORDER BY date DESC LIMIT 3;"
  # 校验: .venv/bin/python scripts/check_data_integrity.py (含 check_fund_nav 抽样 DB<->产物逐位一致)
  # 桶定位对账(前端同构): python3 -c \
  #   "from scripts.export_fund_nav import _fund_bucket; print(_fund_bucket('000001'))"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 不用 .resolve(): scripts 在两树间 hardlink/symlink, resolve() 会绕回 trade 致输出路径错树
# (同 export_etf_hist.py L52 注释 / export_fund_score.py 同机制)
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.collector.public_fund import DB_PATH, STATIC_DATA_DIR  # noqa: E402

OUT_DIR = STATIC_DATA_DIR / "nav_bucket"


def _fund_bucket(code: str) -> str:
    """确定性 FNV-1a hash(code) 末 8bit -> 桶名 {00..ff}(固定 256 桶, 均匀分布)。

    2026-09-23 桶化方案: 任务书字面「按 code 前 2 位分桶」实测不可行(6 位纯数字 code
    前 2 位仅 71 种且分布极不均, 01 桶 201MB 超 multipart 阈值) → 改 FNV-1a 均匀 256 桶
    (~2MB/桶)。**必须与 static-site/app.js `_fundNavBucket` 完全同构**(第二份实现防漂移
    §5.4⑦): 两端对同一 code 字符串算出同一桶名, 否则前端定位错桶。
    """
    h = 2166136261
    for ch in str(code or ""):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h & 0xFF:02x}"


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


def _build_payload(conn, code: str) -> dict:
    """单只基金 payload（**全量与增量刷新共用唯一实现**, 禁止第二套口径 §5.4⑦）。

    SQL / 字段 / source 文案与 2026-09-23 桶化后的全量导出逐字一致；全量模式与
    `--daily-refresh` 增量模式都只经本函数取数据, 任何口径调整改这一处即两端同步。
    """
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
    return {
        "date": (nav[-1][0] if nav else ""),
        "code": code,
        "name": (name_row["fund_name"] if name_row else code),
        "count": len(nav),
        # 口径标注(§21 公示精神:隐式规则显式化;前端 tooltip 引用)
        "source": "fund_daily_nav 表全史日净值(基金公司披露口径, T+1 入图)",
        "nav": nav,
    }


def _shift_date(date_str, days: int) -> str:
    """YYYYMMDD 文本日期平移 days 天；无法解析时原样返回(退化为「只看该日」)。"""
    from datetime import datetime, timedelta

    try:
        return (datetime.strptime(str(date_str), "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")
    except (ValueError, TypeError):
        return str(date_str)


def _refresh_one_bucket(task):
    """刷新**单个桶**(可并行;桶文件彼此独立 ⇒ 桶间无共享状态、无写冲突)。

    task = (db_path, out_dir, bucket, codes)。
    返回 dict(bucket, changed, written, error);任何异常都转成 error(不让 worker 静默吞掉)。
    """
    import sqlite3

    db_path, out_dir, b, codes = task
    path = Path(out_dir) / f"{b}.json"
    try:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                bmap = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            return {"bucket": b, "changed": 0, "written": 0,
                    "error": f"桶文件读取失败 {path.name}({e})"}
        if not isinstance(bmap, dict):
            return {"bucket": b, "changed": 0, "written": 0,
                    "error": f"桶文件顶层非对象 {path.name}({type(bmap).__name__})"}
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        changed = 0
        try:
            for code in codes:
                payload = _build_payload(conn, code)   # 与全量模式同一实现(§5.4⑦)
                if bmap.get(code) != payload:
                    bmap[code] = payload
                    changed += 1
        finally:
            conn.close()
        if changed:
            # 桶内 code 升序(与全量导出逐位同构) + 原子写
            _atomic_write_json(path, dict(sorted(bmap.items())))
        return {"bucket": b, "changed": changed, "written": 1 if changed else 0, "error": None}
    except Exception as e:  # noqa: BLE001 —— worker 内任何异常都必须变成失败结果
        return {"bucket": b, "changed": 0, "written": 0, "error": f"{type(e).__name__}: {e}"}


def daily_refresh(conn, out_dir: Path, recent_days: int, db_path=None, workers: int = 1) -> int:
    """增量刷新 nav_bucket（#278 公募日更 deploy 前用）。返回 0=成功, 2=失败。

    做法:
      1) 候选集 = 最近 `recent_days` 天(按 **DB 最新净值日期** 往前推)有净值写入行的基金。
         覆盖两种已发生形态: ①当日新净值未进产物(DB 领先) ②同日数值被修正(疑似净值修正)。
      2) 逐候选基金用 `_build_payload`(与全量同一实现)重建 payload, 按桶合并进现有桶文件。
      3) 桶内逐 code 比对: 内容未变则不重写(幂等; 无新净值时零写入、零空转报错)。
      4) 桶文件缺失/目录缺失/读取失败 = **明确失败**(写前预检桶文件存在性, 不写半套桶;
         由调用方阻断 deploy 并打印原因, §5.8 防假绿)。
      5) 桶间彼此独立 ⇒ 可按桶并行(默认 worker 数 = min(4, CPU), 环境变量
         NAV_REFRESH_WORKERS 可覆盖)。cloud 单机 CPU 少时并行是主要提速手段(#278 实测)。

    不改：写入范围仅 nav_bucket 桶文件(不动 R2, 不动其它产物; 17:50 全量链照旧全量重出)。
    """
    t0 = time.time()
    if not out_dir.is_dir() or not any(out_dir.glob("*.json")):
        print(f"✗ nav_bucket 刷新失败: 产物目录缺失或为空({out_dir}), 无法增量合并; "
              f"请先全量导出 scripts/export_fund_nav.py", file=sys.stderr, flush=True)
        return 2

    row = conn.execute("SELECT MAX(date) AS d FROM fund_daily_nav WHERE date IS NOT NULL AND date != ''").fetchone()
    max_date = row["d"] if row is not None else None
    if not max_date:
        print("nav_bucket 刷新: DB 无净值数据(fund_daily_nav 为空), 无需刷新", flush=True)
        return 0

    window_start = _shift_date(max_date, -abs(recent_days))
    codes = sorted(
        r["fund_code"] for r in conn.execute(
            "SELECT DISTINCT fund_code FROM fund_daily_nav "
            "WHERE date >= ? AND fund_code IS NOT NULL AND fund_code != ''",
            (window_start,),
        ).fetchall()
    )
    print(f"nav_bucket 增量刷新: DB 最新净值日 {max_date}, 候选窗口 >={window_start}"
          f"({recent_days} 天), 候选 {len(codes)} 只", flush=True)
    if not codes:
        print("nav_bucket 刷新: 窗口内无候选基金, 无需刷新(产物保持不变)", flush=True)
        return 0

    by_bucket: dict[str, list[str]] = {}
    for code in codes:
        by_bucket.setdefault(_fund_bucket(code), []).append(code)

    # 写前统一预检候选桶文件存在性: 缺任何一个就整体失败、**一个桶都不写**
    # (避免「先写了几桶再中途失败」留下新旧混杂的半套产物)
    for b in sorted(by_bucket):
        path = out_dir / f"{b}.json"
        if not path.is_file():
            print(f"✗ nav_bucket 刷新失败: 桶文件缺失 {path.name}(产物不完整, 增量合并会写出残缺桶); "
                  f"请先全量导出 scripts/export_fund_nav.py", file=sys.stderr, flush=True)
            return 2

    if db_path is None:
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    tasks = [(str(db_path), str(out_dir), b, by_bucket[b]) for b in sorted(by_bucket)]
    if workers > 1 and len(tasks) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
            results = list(ex.map(_refresh_one_bucket, tasks))
    else:
        results = [_refresh_one_bucket(t) for t in tasks]

    errors = [r for r in results if r["error"]]
    if errors:
        for r in errors[:4]:
            print(f"✗ nav_bucket 刷新失败: 桶 {r['bucket']}: {r['error']}", file=sys.stderr, flush=True)
        print(f"✗ nav_bucket 刷新失败: {len(errors)}/{len(results)} 桶刷新失败", file=sys.stderr, flush=True)
        return 2

    changed_codes = sum(r["changed"] for r in results)
    written = sum(r["written"] for r in results)
    unchanged = len(results) - written
    elapsed = time.time() - t0
    print(f"✓ nav_bucket 增量刷新完成: 候选 {len(codes)} 只 / 变更 {changed_codes} 只 / "
          f"写 {written} 桶 / 未变 {unchanged} 桶, 耗时 {elapsed:.1f}s", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="场外基金全史净值导出 nav_bucket/{xx}.json(256 桶)")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只(0=全部,小规模验证)")
    parser.add_argument("--codes", type=str, default="", help="逗号分隔指定 code 列表(覆盖全量)")
    parser.add_argument("--daily-refresh", action="store_true",
                        help="增量刷新(#278): 只重建最近 N 天有净值写入的基金所在桶(公募日更 deploy 前用)")
    parser.add_argument("--recent-days", type=int, default=7,
                        help="--daily-refresh 候选窗口(自然日, 按 DB 最新净值日期往前推; 默认 7)")
    parser.add_argument("--workers", type=int, default=0,
                        help="--daily-refresh 并行桶数(0=自动 min(4,CPU), 1=串行; 环境变量 NAV_REFRESH_WORKERS 可覆盖)")
    parser.add_argument("--db", default=str(DB_PATH), help="public_fund.db 路径(测试/沙箱用; 缺省=生产库)")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="nav_bucket 输出目录(测试/沙箱用; 缺省=生产目录)")
    args = parser.parse_args()

    import sqlite3

    if args.daily_refresh and (args.limit > 0 or args.codes):
        parser.error("--daily-refresh 不接受 --limit/--codes(增量模式按 DB 最近窗口自选基金)")
    if args.recent_days < 0:
        parser.error("--recent-days 需 >= 0")
    if args.workers < 0:
        parser.error("--workers 需 >= 0")

    workers = args.workers
    if workers <= 0:
        try:
            workers = int(os.environ.get("NAV_REFRESH_WORKERS", "0"))
        except ValueError:
            workers = 0
    if workers <= 0:
        workers = min(4, os.cpu_count() or 1)

    out_dir = Path(args.out_dir)
    t0 = time.time()
    conn = sqlite3.connect(args.db, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        if args.daily_refresh:
            raise SystemExit(daily_refresh(conn, out_dir, args.recent_days,
                                           db_path=args.db, workers=workers))

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

        out_dir.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        empty_count = 0
        done = 0
        bucket_size = {}

        def _flush_bucket(b: str, bmap: dict) -> None:
            """原子写单桶并累计字节数(桶内 map 已按 code 升序, 内容确定性强 -> 指纹稳定)。"""
            nonlocal total_bytes
            out = out_dir / f"{b}.json"
            _atomic_write_json(out, bmap)
            bucket_size[b] = out.stat().st_size
            total_bytes += bucket_size[b]

        # 流式分桶写: 按 (桶, code) 排序顺序遍历, 遇新桶 flush 上一桶 ——
        # 内存只驻留单桶 ~2MB(旧全量 buckets dict 累积 26370 只 payload 峰值 ~3.7GB,
        # 导出机仅 3.6Gi 会 OOM/吃 swap 慢到超时, 2026-09-23 实测)。排序 key 含 code,
        # 桶内天然 code 升序插入, json.dumps 保序 -> 输出与旧全量聚合(逐桶 sorted(code))
        # 逐位一致, 桶文件 {code: payload} map / payload 同构均不变。
        cur_bucket: str | None = None
        cur_map: dict[str, dict] = {}
        for code in sorted(codes, key=lambda c: (_fund_bucket(c), c)):
            b = _fund_bucket(code)
            if cur_bucket is not None and b != cur_bucket:
                _flush_bucket(cur_bucket, cur_map)
                cur_map = {}
            cur_bucket = b
            payload = _build_payload(conn, code)          # 与 --daily-refresh 同一实现
            if not payload["nav"]:
                empty_count += 1
            # 桶化: 确定性 FNV-1a -> 256 桶, 桶文件 {xx}.json 内含 {code: payload} map
            cur_map[code] = payload
            done += 1
            if done % 500 == 0:
                print(f"  [{done}/{len(codes)}] 已聚合 {len(bucket_size)} 桶 "
                      f"({time.time() - t0:.1f}s)", flush=True)

        # flush 最后一桶
        if cur_bucket is not None:
            _flush_bucket(cur_bucket, cur_map)
    finally:
        conn.close()

    elapsed = time.time() - t0
    big = sorted(bucket_size.items(), key=lambda kv: -kv[1])[:5]
    big_txt = ", ".join(f"{k}.json={v / 1024 / 1024:.1f}MB" for k, v in big)
    print(f"✓ 完成 {done} 只 -> {out_dir} (空数据 {empty_count} 只, 共 {len(bucket_size)} 桶) "
          f"总计 {total_bytes / 1024 / 1024:.1f}MB 耗时 {elapsed:.1f}s")
    print(f"  最大 5 桶: {big_txt}")


if __name__ == "__main__":
    main()
