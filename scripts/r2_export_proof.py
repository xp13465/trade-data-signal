"""Pure export inventory and per-run local output proof. No network/DB/S3 credentials."""
import hashlib, json, os
from pathlib import Path
EXPORT_RANGES = ["3m", "6m", "1y", "3y", "5y", "all"]
EXPORT_MANIFEST_WARN = {
    "signal_kelly_backtest.json": "subprocess 失败不阻塞 export, 前端 fallback null(设计内可缺)",
    "signal_kelly_trades.json": "signal_kelly_backtest.py 附带产出(R2 类), 同上设计内可缺",
    "signal_kelly_backtest_sdc.json": "#91 当日收盘对比档(7.9.2b), subprocess 失败不阻塞 export(设计内可缺)",
    "signal_kelly_trades_sdc.json": "#91 当日收盘对比档附带产物(R2 类), 同上设计内可缺",
}
EXPORT_MANIFEST_WARN["signals_today.json"] = "export_boot C3 split when overview contains signals_today; proof requires actual successful write"
EXPORT_TAB_NAMES = ('a-stock', 'hk', 'global', 'sentiment', 'industry')
def build_export_manifest() -> dict[str, str]:
    """导出产物全量清单: {json 文件名: 生成条件一句话}(单一事实源, 见上段注释)。"""
    m: dict[str, str] = {}
    for name in EXPORT_TAB_NAMES:
        for rng in EXPORT_RANGES:
            if name == "industry" and rng in ("all", "5y", "3y"):
                continue  # industry all/5y/3y 为拆分目录(concepts/meta/indices), 见下
            m[f"{name}-{rng}.json"] = f"tab {name} × range {rng}(main 循环)"
    m["global-extras-all.json"] = "global-all 循环附带轻量版(extras 四件套)"
    for rng in ("all", "5y", "3y"):
        m[f"industry-{rng}-concepts.json"] = f"industry-{rng} 拆分(概念+当日实时行)"
        m[f"industry-{rng}-meta.json"] = f"industry-{rng} 拆分(热力图 meta)"
    m["overview.json"] = "main 必更白名单首件"
    m["boot.json"] = "main 末尾 export_boot 合并首屏 11 JSON"
    m["intraday_snapshot.json"] = "盘中实时快照, 盘后 export 也从 DB 最新行重写"
    m["futures.json"] = "futures_position 采集表日更"
    m["futures_acc_trend.json"] = "期货同向准确度每日趋势"
    m["futures_acc_conclusion.json"] = "期货准确度规律结论(4 规律+触发状态)"
    m["ad_line.json"] = "腾落线+涨跌家数比派生"
    m["volume_ratio.json"] = "量比分布"
    m["position.json"] = "持仓快照"
    m["summary.json"] = "每日总结"
    m["summary_history.json"] = "总结历史(读旧件合并重写)"
    m["signal_freq.json"] = "信号频次统计"
    m["signal_stats.json"] = "per-index 回测统计(_get_stats 现算)"
    m.update(EXPORT_MANIFEST_WARN)  # WARN 级也入清单(存在性检查降级为 WARN)
    m["rotation.json"] = "行业轮动"
    m["new_high_low.json"] = "新高新低"
    m["ma_alignment.json"] = "均线多排"
    m["market_tier_history.json"] = "沪深300 四档大盘状态全历史"
    for rng in EXPORT_RANGES:
        m[f"etf_national_team-{rng}.json"] = f"国家队 6 range 拆分(range {rng})"
    m["etf_national_team_quarterly.json"] = "国家队季度汇总"
    m["etf_national_team_holders.json"] = "国家队具名持有人(v2)"
    for k in (
        "public_fund_summary", "public_fund_holdings", "public_fund_industry",
        "public_fund_top20", "public_fund_asset_alloc", "public_fund_industry_fund_map",
        "public_fund_manuf_subind_fund_map", "public_fund_position_backtest",
        "public_fund_scale_change_ts", "public_fund_industry_rotation_ts",
        "public_fund_position_estimate", "public_fund_sw_industry_alloc",
    ):
        m[f"{k}.json"] = "公募基金 queries 薄包装(public_fund.db 直连无容错, export 跑完必生成)"
    return m

def output_record(payload):
    return {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

def write_run_proof(path, run_id, static_dir, outputs):
    if not path or not run_id:
        return
    root = Path(static_dir).resolve()
    body = {"version": 1, "run_id": run_id, "static_dir": str(root),
            "outputs": {k: v for k, v in outputs.items() if k in build_export_manifest()}}
    target = Path(path)
    # Caller allocates a private directory and unguessable run token; no shared latest pointer.
    tmp = target.with_name(target.name + ".tmp." + str(os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

def load_run_proof(path, run_id, static_dir):
    if not path or not run_id:
        return {}
    try:
        p = Path(path)
        if p.stat().st_size > 1024 * 1024 or p.stat().st_mode & 0o077:
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
        if (raw.get("version") != 1 or raw.get("run_id") != run_id
                or raw.get("static_dir") != str(Path(static_dir).resolve())):
            return {}
        owned = build_export_manifest()
        return {k: v for k, v in raw["outputs"].items()
                if k in owned and isinstance(v, dict)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}

def proof_matches(path, payload, proof, static_dir):
    try:
        rel = Path(path).resolve().relative_to((Path(static_dir) / "data").resolve()).as_posix()
        return proof.get(rel) == output_record(payload)
    except (ValueError, OSError):
        return False


def load_pending_contexts(batch_path, static_dir):
    if not batch_path:
        return None, []
    try:
        p = Path(batch_path)
        if p.stat().st_size > 1024 * 1024:
            return None, []
        batch = json.loads(p.read_text(encoding="utf-8"))
        if batch.get("version") != 1 or batch.get("static_dir") != str(Path(static_dir).resolve()):
            return None, []
        loaded = []
        for row in batch.get("records", [])[:32]:
            try:
                if not row.get("proof_sha256") or row.get("state") != "pending":
                    continue
                proof_path = Path(row["proof_path"])
                if proof_path.stat().st_size > 1024 * 1024:
                    continue
                if hashlib.sha256(proof_path.read_bytes()).hexdigest() != row["proof_sha256"]:
                    continue
                outputs = load_run_proof(proof_path, row["run_id"], static_dir)
                if outputs:
                    loaded.append((row, outputs))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue  # one missing proof cannot suppress another valid request
        return batch.get("batch_id"), loaded
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, []
