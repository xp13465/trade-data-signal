#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ab_direction_anchor.py - 方向锚「开锚 vs 关锚」严格 7 日线上 A/B harness(B 方案核心,2026-09-01)

目的
----
验证「方向锚注入文本到底帮不帮 AI 预测方向」,用 7 个真实交易日数据说话定去留。
方向锚自身回测(n=642)lean 方向预测 ≈0.51 纯随机、无显著方向优势;影子模式线上 0/3 单边偏置,
当前 `direction_anchor_enabled: true`(2026-08-28 用户拍板)依据=3 样本离线前测,非严格 A/B。
本 harness 搭「开锚生产 vs 关锚参考」双通道对照:

  - 生产通道(开锚):gen_daily_brief.py 每天 20:40 真实预测照旧(direction_anchor_enabled: true),
    输出落 daily_brief_history.json —— 本脚本【严禁触碰】,只引用其同日 meta.direction。
  - 参考通道(关锚):本脚本每天盘后(21:15,低价期)额外调 1 次「关锚」参考——用单 prompt 路径
    (便宜),同日期同数据,唯一变量=不注入方向锚(cfg["direction_anchor_enabled"]=False)。

7 个真实交易日后,对比两通道方向预测(up/down/flat)对次日的命中率,数据说话定注入去留。

口径
----
- 关锚参考 direction 由 parse_ai_output 的 meta.direction 取(区间推导,lo>0→up/hi<0→down/跨0→flat,
  与生产同 _derive_direction 口径)。
- 开锚生产 direction 由 daily_brief_history.json 同日 meta.direction 取(与生产同源 §22 一致性)。
- 对账 actual_direction 用 _actual_direction(与 gen_daily_brief.HIT_THRESHOLD=0.5 同口径):
  下一真实交易日 sh 涨跌幅 >0.5%→up, < -0.5%→down, 否则 flat。
- 严格对照:两通道均用「区间推导 direction」对次日判命中(pred == actual_direction)。

只写本地·零触主链
------------------
本脚本每天 21:15 额外调 1 次关锚参考 API(有真实 API 调用成本,非零成本,
约 $0.001-0.01/次低价期);只写 data/ab_direction_anchor.json(本地 A/B 记录)
+ docs/ai-predict/out/ab_direction_anchor_7d.json(对账聚算报告产物,§23.5)。
【严禁】触碰:生产 daily_brief.json/daily_brief_history.json/主链/通知/R2/static-site/data。
绝不调 gen_daily_brief.main(),只 import 复用 build_prompt/call_deepseek/parse_ai_output/
HIT_THRESHOLD/_actual_direction。

输入依赖
- sentiment.db(futures_position/daily_metric/index_daily,只读 ro,由 pick_db 按 date 取最新)
- static-site/data 当日 JSON 快照(load_data,与 gen_daily_brief 同构)
- daily_brief_history.json(生产通道同日 direction 引用,只读)
- deepseek API key(.env,DEEPSEEK_API_KEY),provider 走 config/daily_brief.yaml

用法/复现命令
  # 每日定时(盘后 21:15):对当日 date 生成「关锚」参考并落盘(同日幂等跳过)
  bash scripts/run_ab_direction_anchor.sh
  # 手动单日
  python3 scripts/ab_direction_anchor.py --date 20260901
  # 对账聚算(回填 actual + 两通道命中率对比)
  python3 scripts/ab_direction_anchor.py --reconcile
  # 7 日满后出最终 A/B 结论表(不新调 API)
  python3 scripts/ab_direction_anchor.py --reconcile --force
  # dry-run(0 成本,构建关锚 prompt 落盘校验:direction_anchor_enabled=False 无「9a.方向锚」段)
  python3 scripts/ab_direction_anchor.py --date 20260901 --no-call --dump /tmp/ab_da_test.prompts.json

输出
- data/ab_direction_anchor.json:每日 A/B 记录列表(本地,不进 git)
- docs/ai-predict/out/ab_direction_anchor_7d.json:对账聚算 A/B 结论(§23.5 报告产物)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # trade/
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── 与 gen_daily_brief 同口径(防口径分叉)──────────────────────────────
# 对账用 HIT_THRESHOLD=0.5:涨跌幅 >0.5% 才 up/down,否则 flat(2026-08-14 口径)。
HIT_THRESHOLD = 0.5
# 7 个真实交易日为 A/B 样本上限(用户 7 日验证期)
AB_7D_LIMIT = 7
# 本地 A/B 记录文件(根 data/,不进 git,只本机)
AB_FILE = "ab_direction_anchor.json"
# 对账聚算报告产物(§23.5,进 git)
AB_OUT_DIR = "docs/ai-predict/out"
AB_OUT_FILE = "ab_direction_anchor_7d.json"
# 生产 history(只读引用生产方向)
HISTORY_FILE = "daily_brief_history.json"

from pick_repo import pick_repo, pick_git_repo  # noqa: E402


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pick_db(repo: Path) -> Path:
    """与 gen_daily_brief.pick_db 同口径挑最新 sentiment.db(主库→镜像兜底)。"""
    import gen_daily_brief
    return gen_daily_brief.pick_db(repo)


def _load_sh_pct_map(db_path: Path) -> dict:
    """index_daily sh 全表 date->pct_change(与 aggregate_shadow 同源)。"""
    sh_map: dict = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        for r in conn.execute(
                "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date"):
            sh_map.setdefault(r[0], r[1])
        conn.close()
    except Exception:
        pass
    return sh_map


def _actual_direction(pct) -> str | None:
    if pct is None:
        return None
    if pct > HIT_THRESHOLD:
        return "up"
    if pct < -HIT_THRESHOLD:
        return "down"
    return "flat"


def _load_records(path: Path) -> list[dict]:
    obj = _read_json(path)
    if isinstance(obj, list):
        return obj
    return []


def _default_date(repo: Path) -> str:
    """默认预测日 = overview.json.date(当日最新交易日,与 gen_daily_brief 同取法)。"""
    ov = _read_json(repo / "static-site" / "data" / "overview.json") or {}
    return str(ov.get("date") or _dt.date.today().strftime("%Y%m%d"))


def _load_production_direction(repo: Path, date: str) -> str | None:
    """从生产 daily_brief_history.json 读同日开锚通道 direction(只读,不触碰生产)。"""
    hist = _read_json(repo / "static-site" / "data" / HISTORY_FILE)
    if not hist or not isinstance(hist, dict):
        return None
    for it in hist.get("items") or []:
        if it.get("date") == date:
            meta = it.get("meta") or {}
            return meta.get("direction")
    return None


def _production_hit(repo: Path, date: str) -> dict | None:
    """引用生产 history 该日 hit 回填(仅引用展示,不写生产)。"""
    hist = _read_json(repo / "static-site" / "data" / HISTORY_FILE)
    if not hist or not isinstance(hist, dict):
        return None
    for it in hist.get("items") or []:
        if it.get("date") == date:
            meta = it.get("meta") or {}
            hit = meta.get("hit")
            if isinstance(hit, dict):
                return hit
    return None


def _reconcile_records(records: list[dict], db_path: Path) -> tuple[list[dict], int]:
    """为可回填记录写入 actual(下一交易日 sh 实际方向)。幂等,已回填跳过。"""
    sh_map = _load_sh_pct_map(db_path)
    dates = sorted(sh_map.keys())
    if not dates:
        return records, 0
    changed = 0
    for rec in records:
        d = rec.get("date")
        if rec.get("actual") is not None or rec.get("actual_direction") is not None:
            continue
        if not d:
            continue
        nxt = next((x for x in dates if x > d), None)
        if nxt is None:
            continue
        pct = sh_map.get(nxt)
        if pct is None:
            # 下一交易日有行但 pct 未入库(采集晚到/缺失)→ 不写 actual 留待下次补
            continue
        rec["actual"] = {
            "next_date": nxt,
            "actual_sh_pct": round(pct, 2) if pct is not None else None,
            "actual_direction": _actual_direction(pct),
        }
        changed += 1
    return records, changed


def _eval_records(records: list[dict]) -> dict:
    """聚算「开锚生产 vs 关锚参考」两通道方向命中率对比。"""
    evaled = [r for r in records if (r.get("actual") or {}).get("actual_direction") is not None]
    rows = []
    for r in evaled:
        act = r["actual"]["actual_direction"]
        prod_dir = r.get("production_direction")
        ref_dir = r.get("ref_direction")
        row = {
            "date": r.get("date"),
            "next_date": r["actual"]["next_date"],
            "actual_sh_pct": r["actual"]["actual_sh_pct"],
            "actual_direction": act,
            "production_direction": prod_dir,
            "production_hit": (prod_dir == act) if prod_dir else None,
            "ref_direction": ref_dir,
            "ref_hit": (ref_dir == act) if ref_dir else None,
            "same_direction": (prod_dir == ref_dir) if (prod_dir and ref_dir) else None,
        }
        rows.append(row)

    def _rate(sub):
        n = len(sub)
        p_hit = sum(1 for r in sub if r["production_hit"])
        r_hit = sum(1 for r in sub if r["ref_hit"])
        p_rate = round(p_hit / n, 3) if n else None
        r_rate = round(r_hit / n, 3) if n else None
        return {
            "n": n,
            "production_hit": p_hit,
            "production_hit_rate": p_rate,
            "ref_hit": r_hit,
            "ref_hit_rate": r_rate,
            "delta_prod_minus_ref": (round(p_rate - r_rate, 3)) if (p_rate is not None and r_rate is not None) else None,
        }

    nonflat_prod = [r for r in rows if r["production_direction"] and r["production_direction"] != "flat"]
    nonflat_ref = [r for r in rows if r["ref_direction"] and r["ref_direction"] != "flat"]
    same = [r for r in rows if r["same_direction"] is True]
    diff = [r for r in rows if r["same_direction"] is False]
    return {
        "n_eval": len(rows),
        "overall": _rate(rows),
        "nonflat_production": _rate(nonflat_prod),
        "nonflat_ref": _rate(nonflat_ref),
        "same_direction": len(same),
        "diff_direction": len(diff),
        "rows": rows,
        "note": "开锚=生产(方向锚注入);关锚=参考(不注入)。两通道唯一变量=方向锚注入文本。"
                "7日样本仅累积参考(7 样本二项分布下 Δ≈±3.8pp≈1 sigmas 属正常噪声),"
                "不构成严格统计显著性;|Δ|<10pp 不做去留决策,只 |Δ|≥10pp 才给倾向判断(§5.1 诚实标注)。",
        "reached_7d": len(evaled) >= AB_7D_LIMIT,
    }


def _dump_prompt(messages: list[dict], dump: str, log) -> None:
    Path(dump).write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
    sys_text = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    if "9a.【方向锚" in sys_text or "方向锚" in sys_text:
        log(f"⚠️ 关锚参考 prompt 仍含『方向锚』(build_prompt 注入逻辑异常,dump={dump})")
    else:
        log(f"✅ 关锚参考 prompt 无『方向锚』段(dump={dump},direction_anchor_enabled=False)")


def _build_ref(cfg: dict, date: str, repo: Path):
    """构建关锚参考单 prompt(不注入方向锚)。返回 (messages, data, db_path)。"""
    import gen_daily_brief
    cfg = dict(cfg)
    cfg["direction_anchor_enabled"] = False  # 关锚唯一变量
    cfg["review_enabled"] = False            # 参考通道关 review 注入,排除已知偏差干扰
    static_dir = repo / "static-site" / "data"
    db_path = _pick_db(repo)
    data = gen_daily_brief.load_data(static_dir, db_path, date)
    messages = gen_daily_brief.build_prompt(date, data, cfg, known_bias="")
    return messages, data, db_path


def _main() -> int:
    ap = argparse.ArgumentParser(description="方向锚「开锚 vs 关锚」严格 7 日线上 A/B harness")
    ap.add_argument("--date", default="", help="预测日 YYYYMMDD(默认 overview.date)")
    ap.add_argument("--no-call", action="store_true", help="不调 API,只构建关锚 prompt 落盘(0 成本 dry)")
    ap.add_argument("--dump", default="", help="构建的 messages 落盘到该 JSON 文件(dry 校验)")
    ap.add_argument("--reconcile", action="store_true", help="对账聚算:回填 actual + 两通道命中率对比")
    ap.add_argument("--force", action="store_true", help="配合 --reconcile:强制出最终 A/B 结论表(不新调 API)")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出对账聚算结果")
    args = ap.parse_args()

    import gen_daily_brief
    gen_daily_brief.load_env()
    cfg = gen_daily_brief.load_config()
    repo = pick_repo()
    git_repo = pick_git_repo()
    rec_path = repo / "data" / AB_FILE
    date = args.date or _default_date(repo)

    def log(msg: str) -> None:
        print(f"[ab_direction_anchor] {msg}")

    log(f"repo={repo} git_repo={git_repo} date={date}")

    # ── 对账聚算模式 ──────────────────────────────────────────────────
    if args.reconcile:
        records = _load_records(rec_path)
        db_path = _pick_db(repo)
        records, n_new = _reconcile_records(records, db_path)
        if n_new:
            rec_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        agg = _eval_records(records)
        agg["records_path"] = str(rec_path)
        agg["records_total"] = len(records)
        agg["reconciled_new"] = n_new
        # 落盘报告产物(§23.5)
        out_path = git_repo / AB_OUT_DIR / AB_OUT_FILE
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(agg, ensure_ascii=False, indent=2))
        else:
            print(f"[ab_direction_anchor] A/B 记录 {len(records)} 条,本次新回填 {n_new} 条")
            print(f"可评估样本 {agg['n_eval']} 条")
            ov = agg["overall"]
            print(f"  开锚生产方向命中率: {ov['production_hit']}/{ov['n']} "
                  f"({ov['production_hit_rate'] if ov['production_hit_rate'] is not None else '--'})")
            print(f"  关锚参考方向命中率: {ov['ref_hit']}/{ov['n']} "
                  f"({ov['ref_hit_rate'] if ov['ref_hit_rate'] is not None else '--'})")
            print(f"  Δ(开锚-关锚): {ov['delta_prod_minus_ref'] if ov['delta_prod_minus_ref'] is not None else '--'}pp")
            if agg["reached_7d"]:
                print("✅ 已满 7 个真实交易日:A/B 结论可定。决策建议见 docs/ai-predict/ab-direction-anchor-7d-ab-20260901.md")
            else:
                print(f"⏳ 已评估 {agg['n_eval']}/{AB_7D_LIMIT} 日,未满 7 日继续累积")
            print(f"报告产物: {out_path}")
        return 0

    # ── 每日生成模式:关锚参考通道 ────────────────────────────────────
    records = _load_records(rec_path)
    # 幂等:同日已跑跳过
    if any(r.get("date") == date for r in records):
        log(f"⚠️ {date} 关锚参考已存在,幂等跳过(如需重跑请手动删对应记录)。")
        return 0
    # 7 日上限:已满 7 个真实交易日记录 → 不再新调 API,提示跑 --reconcile --force
    if len(records) >= AB_7D_LIMIT and not args.force:
        log(f"已满 {AB_7D_LIMIT} 日,不再新调 API。跑 --reconcile --force 出最终结论。")
        return 0

    # 构建关锚 prompt(dry 或实调共用)
    messages, data, db_path = _build_ref(cfg, date, repo)

    # dry-run:只构建 + 落盘,不调 API
    if args.no_call:
        if args.dump:
            _dump_prompt(messages, args.dump, log)
        else:
            log("--no-call 未给 --dump:仅构建未落盘(0 成本 dry 校验通过)")
        log("--no-call:0 成本 dry 校验完成,未调 API、未写任何生产文件。")
        return 0

    # 实调 deepseek(关锚参考)
    log("调用 call_deepseek(关锚参考通道,direction_anchor_enabled=False)...")
    t0 = time.time()
    raw = gen_daily_brief.call_deepseek(messages, cfg, log)
    elapsed = round(time.time() - t0, 1)
    if not raw:
        log(f"❌ AI 调用失败({date}),见 DEEPSEEK_API_KEY/provider 配置。本次不落盘,下次重试。")
        return 1
    parsed = gen_daily_brief.parse_ai_output(raw, data, date)
    if not parsed:
        log(f"❌ 解析失败({date}),本次不落盘,下次重试。")
        return 1
    meta = parsed.get("meta") or {}
    ref_dir = meta.get("direction")
    if not ref_dir or ref_dir == "N/A":
        log(f"⚠️ {date} 关锚参考方向降级(N/A),仍落盘留痕(诚实标注),不硬判。")
    # 引用生产通道同日方向
    prod_dir = _load_production_direction(repo, date)
    prod_hit = _production_hit(repo, date)
    rec = {
        "date": date,
        "channel": "ab",
        "production_direction": prod_dir,       # 开锚生产侧同日 direction 引用
        "production_hit_ref": prod_hit,          # 生产 hit 引用(仅展示,不触碰生产)
        "ref_direction": ref_dir,                # 关锚参考 direction
        "ref_confidence": meta.get("confidence"),
        "ref_confidence_reason": meta.get("confidence_reason"),
        "ref_meta": meta,                        # 关锚参考完整 meta
        "ref_basis": [meta.get("confidence_reason")] if meta.get("confidence_reason") else [],
        "ref_strength": "flat" if ref_dir == "flat" else "strong",
        "actual": None,
        "created_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": elapsed,
    }
    records.append(rec)
    rec_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ {date} 关锚参考已落盘({len(records)} 条)。direction={ref_dir} "
        f"prod_direction={prod_dir} 耗时{elapsed}s")
    log(f"记录文件: {rec_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
