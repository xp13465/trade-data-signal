#!/usr/bin/env python3
"""静态化导出脚本：从 SQLite (data/sentiment.db) 导出所有 API 端点数据为静态 JSON。

查询逻辑统一在 app/queries.py（与 main.py 路由共用）。本文件只保留：
- 进程级缓存层（series 全量缓存 + stats 缓存，包装 queries 调用，P1-2 性能优化）
- JSON 写盘（write_json + gzip）
- industry 拆分导出（write_industry_split）
- main() 导出流水线

可重复跑（python static-site/export.py），覆盖 data/ 下 JSON。

导出端点：
  - data/overview.json                 （今日快照 + 指数 sparkline + 宽度 + 分数 + 行业热力图 + 买卖点 + 冰点日）
  - data/a-stock-{3m,6m,1y,3y,5y,all}.json
  - data/hk-{3m,6m,1y,3y,5y,all}.json
  - data/global-{3m,6m,1y,3y,5y,all}.json
  - data/sentiment-{3m,6m,1y,3y,5y,all}.json
  - data/industry-{3m,6m,1y,3y,5y,all}.json
  - data/index/{index_id}-all.json     （44 个指数 ohlc + signals 全历史）

range 处理方案（备注）：
  - tab 端点（a-stock/hk/global/sentiment/industry）预生成多 range JSON（各 5 个文件），
    前端按 state.range 直接读对应文件，逻辑最简（无需客户端切片）。
  - index 端点仅预生成 all 全历史（44 文件），前端读后用 ohlc 日期范围客户端过滤 signals
    （signals 数组小，过滤开销可忽略；避免 44×5=220 文件膨胀）。

数据源：仅读 data/sentiment.db（API 只用此库；stock_daily.db 仅供采集器用，API 不读）。
"""
import gzip
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# 复用 app 包代码（与 API 完全一致的查询逻辑）
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from app.collector.fetchers import load_config  # noqa: E402
from app.compute import signal_stats as sigstats  # noqa: E402
from app.db import get_conn  # noqa: E402
from app import queries  # noqa: E402

STATIC_DIR = Path(__file__).absolute().parent
DATA_DIR = STATIC_DIR / "data"
INDEX_DIR = DATA_DIR / "index"

# 1m 周期已废弃删除：前端 range 选项仅 3m/6m/1y/3y/5y/all（无 1m 按钮），1m JSON 无人 fetch（冗余）
EXPORT_RANGES = ["3m", "6m", "1y", "3y", "5y", "all"]


# ============ 进程级缓存层（P1-2 性能优化）============
# 5 tab × 6 range = 30 次 range 循环，同一 id 被查 6 次。优化：每个 id 只查全量一次，
# 后续按 start/end 字符串切片。date 是 YYYYMMDD 字符串，字典序=时间序，可直接字符串比较过滤。
# cache dict 传给 queries building block 函数（cache 参数），queries 不创建/存储 cache，
# 只在非空时读缓存。进程级缓存，export 跑完即释放（不跨进程持久化）。
_series_cache: dict = {}

# signal_stats 现算缓存（与 export 其他 export_* 保持一致，避免重复算）
_stats_cache: dict | None = None


def _get_stats() -> dict:
    """进程内缓存 signal_stats.compute() 结果。"""
    global _stats_cache
    if _stats_cache is None:
        _stats_cache = queries.stats_all()
    return _stats_cache


# ============ 端点导出函数（薄包装 queries 调用 + 缓存注入）============

def export_overview(conn, cfg):
    """复刻 /api/overview。"""
    return queries.overview(conn, cfg)


def export_a_stock(conn, cfg, rng):
    """复刻 /api/a-stock（含 ETF 候选列表，P2-新-G）。"""
    start, end = queries.range_for(rng)
    return queries.a_stock(conn, cfg, start, end, cache=_series_cache, include_etf=True)


def export_hk(conn, cfg, rng):
    """复刻 /api/hk。"""
    start, end = queries.range_for(rng)
    return queries.hk(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_global(conn, cfg, rng):
    """复刻 /api/global。"""
    start, end = queries.range_for(rng)
    return queries.global_market(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_sentiment(conn, cfg, rng):
    """复刻 /api/sentiment（不含 futures，前端读 futures.json 独立加载）。"""
    start, end = queries.range_for(rng)
    return queries.sentiment(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_industry(conn, cfg, rng):
    """复刻 /api/industry。"""
    start, end = queries.range_for(rng)
    return queries.industry(conn, cfg, start, end, cache=_series_cache, stats_all_dict=_get_stats())


def export_index_detail(conn, cfg, index_id):
    """复刻 /api/index/{index_id}?range=all。全历史 ohlc + signals + stats + strategy + etfs。"""
    start, end = queries.range_for("all")
    return queries.index_detail(conn, cfg, index_id, start, end,
                                cache=_series_cache, stats_all_dict=_get_stats(), include_etf=True)


def export_futures(conn):
    """复刻 /api/futures。"""
    return queries.futures_data(conn)


def export_ad_line(conn):
    """复刻 /api/ad_line。"""
    return queries.ad_line(conn)


def export_volume_ratio(conn):
    """复刻 /api/volume_ratio。"""
    return queries.volume_ratio(conn)


def export_new_high_low(conn):
    """复刻 /api/new_high_low。"""
    return queries.new_high_low(conn)


def export_ma_alignment(conn):
    """复刻 /api/ma_alignment。"""
    return queries.ma_alignment(conn)


def export_rotation(conn):
    """复刻 /api/rotation（latest 统一用 compute_rotation 含门控）。"""
    return queries.rotation(conn)


def export_position():
    """复刻 /api/position。"""
    return queries.position()


def export_summary():
    """复刻 /api/summary。"""
    return queries.summary()


def export_summary_history(days: int = 90):
    """复刻 /api/summary/history：最近 N 天一句话总结（时间倒序）。

    静态站无后端，预生成 summary_history.json 供前端"更多"弹窗本地分页。
    """
    return queries.summary_history(get_conn(), 0, days)


def export_signal_freq():
    """复刻 /api/signal_freq：全局信号频率统计。"""
    return queries.signal_freq(_get_stats())


def export_intraday_snapshot():
    """复刻 /api/intraday_snapshot：从 DB 读最新盘中实时快照。"""
    return queries.intraday_snapshot()


def export_etf_national_team(rng="all"):
    """国家队宽基 ETF 资金动向（12 只宽基 ETF 份额+成交额+信号）。"""
    return queries.etf_national_team(rng)


def export_etf_national_team_quarterly():
    """季度持有人结构（机构占比历史轨迹）。"""
    return queries.etf_national_team_quarterly()


def export_etf_national_team_holders():
    """v2 具名持有人（cninfo PDF 解析的前十大持有人，含汇金/证金识别）。"""
    return queries.etf_national_team_holders()


# ============ JSON 序列化 + 写盘 ============

def _json_default(o):
    """处理 sqlite3 可能返回的非标准 JSON 类型。"""
    if isinstance(o, (sqlite3.Row,)):
        return dict(o)
    raise TypeError(f"not serializable: {type(o)}")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 紧凑输出（separators 无空白）--industry-all.json 全历史约 26MB，
    # 默认 ', '/': ' 分隔会让其超 Cloudflare Pages 25MB 单文件限制。
    text = json.dumps(data, ensure_ascii=False, default=_json_default,
                      separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    # JSON gz 方案B(MaoziYun 不支持 Content-Encoding: gzip,前端 DecompressionStream 显式解压)
    # 方案Y: GZ_THRESHOLD=0 全量生成 .json.gz(含小文件),原 .json 保留作 fallback
    # 旧 100KB 阈值仅大文件生成 .gz,小文件不生成致 fetchJSON .gz 优先 404 fallback;全量后无 404
    GZ_THRESHOLD = 0
    if len(text) >= GZ_THRESHOLD:
        gz_path = path.with_suffix(path.suffix + ".gz")
        with gzip.open(gz_path, "wb") as f:
            f.write(text.encode("utf-8"))
    return len(text)


def write_industry_split(conn, cfg, rng="all") -> tuple[dict, int, int]:
    """导出 industry-{rng} 拆分文件并返回 (counts, n_indices, n_concepts)。

    生成（rng 替换下方 {rng}）：
    - industry-{rng}-indices/{iid}.json × 31 行业
    - industry-{rng}-concepts.json（概念 + 当日实时行）
    - industry-{rng}-meta.json（热力图 + index_ids + concept_ids）
    - 仅 all range 额外产 {iid}-detail.json × 31（tooltip 专属字段，按需加载）

    all range 主文件瘦身（全历史 29MB 超 Cloudflare Pages 25MB 限制，瘦身省 ~68%），
    tooltip 专属字段拆到 {iid}-detail.json 按需加载。非 all range（5y 等）主文件保留
    全字段：单文件 <25MB 无需瘦身，且前端 _preloadIndDetail 检测 width[0] 含 zt_count
    即走内存分支（app.js _indHasDetail），免 detail 二次请求，故不产 detail.json。

    供 main() 收盘全量导出 与 intraday_snapshot._export_affected_json 盘中导出共用。
    盘中调用时 index_daily 已含当日行业/概念实时行（_backfill_industry_daily /
    _backfill_concept_daily），故导出 JSON 含当日 -> 前端读 JSON 即可盘中可见当日。
    """
    ind_all = export_industry(conn, cfg, rng)
    ind_split_dir = DATA_DIR / f"industry-{rng}-indices"
    ind_split_dir.mkdir(parents=True, exist_ok=True)
    counts: dict = {}
    slim = rng == "all"  # 仅 all 瘦身（全历史 29MB 超 25MB 限制）
    if slim:
        # B2 折中瘦身：主文件只保留渲染必需字段，tooltip 专属字段拆到 {iid}-detail.json
        _KEEP_DATA = ("date", "close", "pct_change", "amount")
        _KEEP_WIDTH = ("date", "up_count", "down_count")
        _DET_OHLC = ("open", "high", "low")
        _DET_WIDTH = ("zt_count", "dt_count", "zb_count", "seal_rate", "amount")
    for iid, ind in ind_all["indices"].items():
        if slim:
            slim_obj = {k: v for k, v in ind.items() if k not in ("data", "width")}
            slim_obj["data"] = [{k: x.get(k) for k in _KEEP_DATA} for x in ind["data"]]
            slim_obj["width"] = [{k: x.get(k) for k in _KEEP_WIDTH} for x in ind["width"]]
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", slim_obj)
            detail = {
                "ohlc": [{k: x.get(k) for k in _DET_OHLC} for x in ind["data"]],
                "width": [{k: x.get(k) for k in _DET_WIDTH} for x in ind["width"]],
            }
            counts[f"industry-{rng}-indices/{iid}-detail.json"] = write_json(
                ind_split_dir / f"{iid}-detail.json", detail)
        else:
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", ind)
    counts[f"industry-{rng}-concepts.json"] = write_json(
        DATA_DIR / f"industry-{rng}-concepts.json", {"concepts": ind_all["concepts"]})
    counts[f"industry-{rng}-meta.json"] = write_json(
        DATA_DIR / f"industry-{rng}-meta.json",
        {"heatmap": ind_all["heatmap"], "index_ids": list(ind_all["indices"].keys()),
         "concept_ids": list(ind_all["concepts"].keys())})
    n_indices = len(ind_all["indices"])
    n_concepts = len(ind_all["concepts"])
    print(f"  industry-{rng} 拆分: {n_indices} 行业 + {n_concepts} 概念 + meta")
    return counts, n_indices, n_concepts


def write_industry_all_split(conn, cfg) -> tuple[dict, int, int]:
    """兼容别名 -> write_industry_split(conn, cfg, "all")。"""
    return write_industry_split(conn, cfg, "all")


def main():
    cfg = load_config()
    conn = get_conn()
    counts = {}

    # 1. overview
    counts["overview.json"] = write_json(DATA_DIR / "overview.json", export_overview(conn, cfg))
    print(f"  overview.json ({counts['overview.json']} bytes)")

    # 2-6. tab 端点 × 5 ranges
    tab_exporters = {
        "a-stock": export_a_stock,
        "hk": export_hk,
        "global": export_global,
        "sentiment": export_sentiment,
        "industry": export_industry,
    }
    for name, fn in tab_exporters.items():
        for rng in EXPORT_RANGES:
            if name == "industry" and rng in ("all", "5y", "3y"):
                continue  # industry-all/5y/3y 拆分为多文件（见下方），避免大单文件拖慢首屏
            fname = f"{name}-{rng}.json"
            data = fn(conn, cfg, rng)
            counts[fname] = write_json(DATA_DIR / fname, data)
            print(f"  {fname} ({counts[fname]} bytes)")
            # 信号弹窗只需 extras 四件套（不含 indices），单独导出轻量版省 ~68% 体积
            if name == "global" and rng == "all":
                counts["global-extras-all.json"] = write_json(
                    DATA_DIR / "global-extras-all.json",
                    {k: data[k] for k in ("extras", "extras_signals", "extras_stats", "extras_strategy")})
                print(f"  global-extras-all.json ({counts['global-extras-all.json']} bytes)")

    # industry-all/5y/3y 拆分：31 行业各一个文件 + concepts + meta。
    # all 全历史 29MB 超 Cloudflare Pages 25MB 单文件限制须拆；5y 14MB / 3y 9.2MB 虽未超限，
    # 但拆成 31 个小文件按需 fetch 提速首屏（前端 all/5y/3y 并发组装，见 app.js _loadIndustryData）。
    for rng in ("all", "5y", "3y"):
        ind_counts, _n_ind, _n_concept = write_industry_split(conn, cfg, rng)
        counts.update(ind_counts)

    # 7. metrics（已废弃：前端无 fetch 引用，2026-07-15 删除上线产物，不再生成）
    # counts["metrics.json"] = write_json(DATA_DIR / "metrics.json", export_metrics(cfg))
    # print(f"  metrics.json ({counts['metrics.json']} bytes)")

    # 7.5. futures
    counts["futures.json"] = write_json(DATA_DIR / "futures.json", export_futures(conn))
    print(f"  futures.json ({counts['futures.json']} bytes)")

    # 7.6. ad_line
    counts["ad_line.json"] = write_json(DATA_DIR / "ad_line.json", export_ad_line(conn))
    print(f"  ad_line.json ({counts['ad_line.json']} bytes)")

    # 7.7. volume_ratio
    counts["volume_ratio.json"] = write_json(DATA_DIR / "volume_ratio.json", export_volume_ratio(conn))
    print(f"  volume_ratio.json ({counts['volume_ratio.json']} bytes)")

    # 7.8. position
    counts["position.json"] = write_json(DATA_DIR / "position.json", export_position())
    print(f"  position.json ({counts['position.json']} bytes)")

    # 7.9. summary
    counts["summary.json"] = write_json(DATA_DIR / "summary.json", export_summary())
    print(f"  summary.json ({counts['summary.json']} bytes)")
    counts["summary_history.json"] = write_json(
        DATA_DIR / "summary_history.json", export_summary_history())
    print(f"  summary_history.json ({counts['summary_history.json']} bytes)")
    counts["signal_freq.json"] = write_json(DATA_DIR / "signal_freq.json", export_signal_freq())
    print(f"  signal_freq.json ({counts['signal_freq.json']} bytes)")
    # 7.9.1 signal_stats（per-index 回测统计，6类信号含 sell_stop_loss；供前端❓弹窗分析概况聚合）
    # 用 _stats_all() 现算内存结果（不读根 data/signal_stats.json 旧文件，避免缺品种/过期）
    counts["signal_stats.json"] = write_json(DATA_DIR / "signal_stats.json", _get_stats())
    print(f"  signal_stats.json ({counts['signal_stats.json']} bytes)")

    # 7.10. rotation
    counts["rotation.json"] = write_json(DATA_DIR / "rotation.json", export_rotation(conn))
    print(f"  rotation.json ({counts['rotation.json']} bytes)")

    # 7.11. new_high_low
    counts["new_high_low.json"] = write_json(DATA_DIR / "new_high_low.json", export_new_high_low(conn))
    print(f"  new_high_low.json ({counts['new_high_low.json']} bytes)")

    # 7.12. ma_alignment
    counts["ma_alignment.json"] = write_json(DATA_DIR / "ma_alignment.json", export_ma_alignment(conn))
    print(f"  ma_alignment.json ({counts['ma_alignment.json']} bytes)")

    # 7.13. intraday_snapshot（盘中实时快照，从 DB 读最新行）
    counts["intraday_snapshot.json"] = write_json(
        DATA_DIR / "intraday_snapshot.json", export_intraday_snapshot())
    print(f"  intraday_snapshot.json ({counts['intraday_snapshot.json']} bytes)")

    # 7.14. etf_national_team × range（默认1y≈0.67MB，all≈7.6MB；手机默认只下1y，避免7.6MB裸传卡顿）
    # 仿 sentiment 拆分：预生成 3m/6m/1y/3y/5y/all 六个文件，前端按 state.range 按需 fetch。
    from app.collector.etf_national_team import export_data as _nt_export_data
    _nt_daily, _nt_quarterly, _nt_holders = _nt_export_data()
    for rng in EXPORT_RANGES:
        fname = f"etf_national_team-{rng}.json"
        counts[fname] = write_json(DATA_DIR / fname, export_etf_national_team(rng))
        print(f"  {fname} ({counts[fname]} bytes)")
    counts["etf_national_team_quarterly.json"] = write_json(
        DATA_DIR / "etf_national_team_quarterly.json", _nt_quarterly)
    print(f"  etf_national_team_quarterly.json ({counts['etf_national_team_quarterly.json']} bytes)")
    counts["etf_national_team_holders.json"] = write_json(
        DATA_DIR / "etf_national_team_holders.json", _nt_holders)
    print(f"  etf_national_team_holders.json ({counts['etf_national_team_holders.json']} bytes)")

    # 8. index/{id}-all.json（44 个指数）
    all_indices = [i["id"] for i in cfg.get("indices", []) if i.get("enabled", True)]
    for iid in all_indices:
        fname = f"{iid}-all.json"
        data = export_index_detail(conn, cfg, iid)
        counts[f"index/{fname}"] = write_json(INDEX_DIR / fname, data)
    print(f"  index/*.json ({len(all_indices)} files)")

    conn.close()

    total_files = len(counts) + len(all_indices)
    total_bytes = sum(counts.values())
    print(f"\n导出完成：{len(counts)} 个 JSON 文件，{total_bytes / 1024 / 1024:.1f} MB")
    print(f"  - overview: 1")
    print(f"  - tab ranges: 5 tabs × {len(EXPORT_RANGES)} ranges")
    print(f"  - metrics: 1")
    print(f"  - index detail: {len(all_indices)} (all range, full history)")
    print(f"输出目录: {DATA_DIR}")

    # 批量 gzip DATA_DIR 下所有 *.json（含非本脚本导出的，如 alert.json / lab_*.json /
    # schedule_stats.json / etf_national_team-1m.json 等）。
    # 注意：industry-{all,5y,3y} 单文件已拆分为 indices/ 子目录（见上方 write_industry_split），
    # 不再生成 industry-3y.json 等单文件；此处 rglob 不会扫到已删除的 stale 单文件。
    # write_json 已对 export.py 导出的 JSON 生成 .gz，但非本脚本导出的 JSON 不会有 .gz，
    # 致前端 fetchJSON .gz 优先命中 404（Console 红）。此处统一补齐，确保所有 .json 都有 .gz。
    # rglob 递归扫描子目录：lab/*.json（scripts/lab/*.py 生成，不走 write_json，否则无 .gz）、
    # index/ industry-*-indices/（write_json 已生成 .gz，此处幂等覆盖，无害）。
    _gz_count = 0
    for _p in sorted(DATA_DIR.rglob("*.json")):
        _gz_path = _p.with_suffix(".json.gz")
        with open(_p, "rb") as _src, gzip.open(_gz_path, "wb") as _dst:
            _dst.write(_src.read())
        _gz_count += 1
    print(f"  批量 gzip: {_gz_count} 个 JSON -> .gz（含子目录 lab/ 等，rglob 递归）")

    # 生成文件后自动走 R2 优化（用户规则：不等超 300MB 才发起）
    # EXPORT_SKIP_R2=1 时跳过（deploy.sh/intraday_snapshot.sh 自己跑 R2，避免重复）
    if os.environ.get("EXPORT_SKIP_R2") != "1":
        print("\n-> 自动上传 R2 (EXPORT_SKIP_R2=1 可跳过)...", flush=True)
        for _cmd in ["upload-lab", "upload-trade-sim-json", "upload-index", "upload-industry", "upload-data-large"]:
            try:
                _r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/upload_r2.py"), _cmd],
                    env={**os.environ, "REPO": str(ROOT)},
                    capture_output=True, text=True, timeout=300)
                print(f"  {_cmd}: rc={_r.returncode}", flush=True)
                if _r.stderr and _r.returncode != 0:
                    print(f"    stderr: {_r.stderr[:200]}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"  {_cmd}: 超时(300s)跳过", flush=True)
            except Exception as _e:  # noqa: BLE001
                print(f"  {_cmd}: 异常 {_e}", flush=True)
        print("-> R2 上传完成(失败不阻塞)", flush=True)


if __name__ == "__main__":
    main()
