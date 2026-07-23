#!/usr/bin/env python3
"""P1-新-C §ETF 买卖清单 AI评分 tab(阶段2: 全市场 A股股票型 ETF 扩采集 + OHLC + H3/L2)。

阶段1(commit b8fbed75): 12 国家队 ETF 评分清单(买8+卖12)。
阶段2(本版,~285 行后端):
  - 扩到全市场 A股股票型 ETF(动态读 akshare fund_etf_fund_daily_em 过滤 类型='指数型-股票')
  - etf_daily 表加 open/high/low 列,fetcher C 返回的 OHLC 全量入库(原只存 close/amount)
  - compute_target_dims H3/L2 ETF 专属:对 ETF close 现算 RSI 上穿30(C1)+BB 下轨回归(B1 辅买)
    +20日高回落5%(D1 卖点)事件化后滚动10日计数填 H3/L2(原 ETF H3/L2=NA 因无 signal_daily)
  - buy_list/sell_list 容量从 12 扩到 top N(可配置,默认 buy_top=20/sell_top=30)

复用 compute_alert_for_target(target_type="etf") (app/alert_score.py L527 已支持 ETF)
+ build_reason (app/alert_reason.py L363) 取 human_text 摘要。

输出: static-site/data/etf_score_list.json (+ .json.gz)
  {
    "date": "20260722",
    "updated_at": "...",
    "source": "全市场 A股股票型 ETF (XXXX 只) - 阶段2 扩采集",
    "universe_count": XXXX,
    "buy_list": [
      {etf_code, name, score, hands, high_alert, low_alert, is_national_team, reason_summary},
      ... (top N=20, 按 low_alert DESC)
    ],
    "sell_list": [
      {etf_code, name, score, high_alert, low_alert, sell_signal, is_national_team, reason_summary},
      ... (top N=30, 按 high_alert DESC)
    ],
    "errors": [...]
  }

排序与过滤口径(与阶段1 一致,仅容量扩到 top N):
- buy_list: high_alert<60 (非过热) + low_alert>=50 (有机会), 按 low_alert DESC 排序, 取 top N=20
  手数 3/2/1/0 映射: low_alert>=70 -> 3手 / 60-70 -> 2手 / 50-60 -> 1手 / <50 -> 0手不入清单
  score = low_alert (机会分, 越高越适合买)
- sell_list: 全部 ETF 按 high_alert DESC 排序, 取 top N=30
  sell_signal: high_alert>70 建议卖 / >60 观察 / 否则持有
  score = high_alert (过热分, 越高越适合卖)
- reason_summary: build_reason human_text.low (buy) / human_text.high (sell) 前 100 字摘要
- is_national_team: 从 ETF_LIST 12 国家队宽基清单判断(app.collector.etf_national_team.is_national_team)

动态采集(自包含,不依赖外部 backfill):
- 首次跑全市场:对每只 ETF 先 fetch_etf_ohlc + upsert(近252日 OHLC,sina 0.3s/只),
  再 compute_alert_for_target。~1371只 ETF 全量约 20 分钟(7分钟采集+12分钟算分)。
- 后续跑增量:DB 已有近5日数据的 ETF 跳过采集,直接 compute_alert(0.5s/只),约 12 分钟。
  (注: universe 数量由 akshare fund_etf_fund_daily_em 过滤 类型=='指数型-股票' 动态返回,
   随市场变动,2026-07-20 实测 1371 只 sh=736 sz=635)

异常处理: 单只 ETF 失败进 errors[], 不中断主流程。

用法:
  .venv/bin/python scripts/export_etf_score_list.py
  .venv/bin/python scripts/export_etf_score_list.py --no-fetch    # 跳过采集,仅算分(快速验证)
  .venv/bin/python scripts/export_etf_score_list.py --buy-top 30 --sell-top 50   # 自定义 top N
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import json
import sys
import time
import traceback
from pathlib import Path

# 不用 .resolve(): trade-data/scripts 是 trade/scripts 的 hardlink (同 inode),
# resolve() 会跳回 trade 致输出路径绕回 trade
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.alert_reason import build_reason  # noqa: E402
from app.alert_score import compute_alert_for_target, ETF_ADJUST_ENABLED  # noqa: E402
from app.collector.etf_national_team import (  # noqa: E402
    DB_PATH, ETF_LIST, fetch_etf_ohlc, get_conn, init_db, is_national_team,
    universe_etf_codes, _upsert_daily,
)

DATA_DIR = ROOT / "static-site" / "data"

# 默认 top N(阶段2 扩容:从阶段1 的 8/12 扩到 20/30)
DEFAULT_BUY_TOP = 20
DEFAULT_SELL_TOP = 30
# 动态采集拉近252日(1年,够 RSI14 + MA60 + 252日分位)
FETCH_DAYS = 252

# 代表性 ETF 清单(62 只):核心宽基12 + 行业ETF~30 + 主题ETF~20
# 阶段2 不跑全市场 ~1371 只(慢+大部分信号质量低),用代表性清单覆盖主要赛道
# (全市场数量由 akshare 动态返回,加 --full-market 跑全市场)
# name 字段为占位,fetch_etf_ohlc 采集时会用 akshare 返回的基金简称覆盖
REPRESENTATIVE_ETF_CODES: list[tuple[str, str, str]] = [
    # ── 核心宽基 12(ETF_LIST 国家队)──
    ("510050", "50ETF华夏", "sh"),
    ("510300", "300ETF华泰柏瑞", "sh"),
    ("510310", "300ETF易方达", "sh"),
    ("159919", "300ETF嘉实", "sz"),
    ("510500", "500ETF南方", "sh"),
    ("159922", "500ETF嘉实", "sz"),
    ("512100", "1000ETF南方", "sh"),
    ("159845", "1000ETF华夏", "sz"),
    ("159915", "创业板ETF易方达", "sz"),
    ("159952", "创业板ETF广发", "sz"),
    ("588000", "科创50ETF华夏", "sh"),
    ("588050", "科创50ETF工银", "sh"),
    # ── 行业 ETF ~30(金融/医药/半导体/新能源/军工/消费/周期)──
    ("512000", "券商ETF", "sh"),
    ("512800", "银行ETF", "sh"),
    ("512070", "非银ETF", "sh"),
    ("512010", "医药ETF", "sh"),
    ("512170", "医疗ETF", "sh"),
    ("159929", "医药ETF汇添富", "sz"),
    ("512480", "半导体ETF", "sh"),
    ("159995", "芯片ETF", "sz"),
    ("515030", "新能源车ETF", "sh"),
    ("515790", "光伏ETF", "sh"),
    ("512660", "军工ETF", "sh"),
    ("512680", "国防ETF", "sh"),
    ("159928", "消费ETF", "sz"),
    ("510150", "消费ETF汇添富", "sh"),
    ("515170", "食品饮料ETF", "sh"),
    ("512690", "酒ETF", "sh"),
    ("515220", "煤炭ETF", "sh"),
    ("512400", "有色金属ETF", "sh"),
    ("512200", "房地产ETF", "sh"),
    ("159611", "电力ETF", "sz"),
    ("515210", "钢铁ETF", "sh"),
    ("159825", "农业ETF", "sz"),
    ("159996", "家电ETF", "sz"),
    ("562990", "物流ETF", "sh"),
    ("159766", "旅游ETF", "sz"),
    ("515880", "通信ETF", "sh"),
    ("159870", "化工ETF", "sz"),
    ("516950", "基建50ETF", "sh"),
    ("512980", "传媒ETF", "sh"),
    ("512720", "计算机ETF", "sh"),
    ("159698", "建材ETF", "sz"),
    # ── 主题 ETF ~20(AI/创新药/碳中和/央企/红利/黄金/机器人)──
    ("159819", "人工智能ETF", "sz"),
    ("515980", "人工智能ETF国联", "sh"),
    ("516510", "云计算ETF", "sh"),
    ("515400", "大数据ETF", "sh"),
    ("159891", "物联网ETF", "sz"),
    ("515050", "5G通信ETF", "sh"),
    ("515120", "创新药ETF", "sh"),
    ("159992", "创新药ETF华宝", "sz"),
    ("159775", "碳中和ETF", "sz"),
    ("159755", "电池ETF", "sz"),
    ("159682", "创业板50ETF", "sz"),
    ("159783", "科创创业50ETF", "sz"),
    ("159920", "北证50ETF", "sz"),
    ("159790", "央企ETF", "sz"),
    ("510880", "红利ETF", "sh"),
    ("515080", "中证红利ETF", "sh"),
    ("512890", "红利低波ETF", "sh"),
    ("518880", "黄金ETF华安", "sh"),
    ("562500", "机器人ETF", "sh"),
]


def _write_json_gz(out_path: Path, payload: dict) -> None:
    """写 JSON + 同名 .json.gz (前端 fetchJSON 优先 .gz 通道)。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out_path.write_text(text, encoding="utf-8")
    with gzip.open(out_path.with_suffix(out_path.suffix + ".gz"), "wb") as f:
        f.write(text.encode("utf-8"))


def _summarize(text: str | None, max_len: int = 100) -> str:
    """human_text 前 N 字摘要, 末尾加省略号。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _hands_for_low(low_alert: float | None) -> int:
    """low_alert -> 建议手数: >=70 -> 3 / 60-70 -> 2 / 50-60 -> 1 / <50 -> 0"""
    if low_alert is None:
        return 0
    if low_alert >= 70:
        return 3
    if low_alert >= 60:
        return 2
    if low_alert >= 50:
        return 1
    return 0


def _sell_signal_for_high(high_alert: float | None) -> str:
    """high_alert -> 卖出建议: >70 建议卖 / >60 观察 / 否则持有"""
    if high_alert is None:
        return "数据不足"
    if high_alert > 70:
        return "建议卖出(过热)"
    if high_alert > 60:
        return "观察(过热风险)"
    return "持有(未过热)"


def _fetch_and_upsert_ohlc(code: str, name: str, conn) -> int:
    """动态采集单只 ETF 近 FETCH_DAYS 日 OHLC 并 upsert 入 etf_daily(含 open/high/low)。
    返回入库行数。失败返 0。自包含:不依赖外部 backfill 命令。
    """
    start_yyyymmdd = (_dt.datetime.now() - _dt.timedelta(days=FETCH_DAYS)).strftime("%Y%m%d")
    try:
        rows = fetch_etf_ohlc(code, start_yyyymmdd=start_yyyymmdd)
        if not rows:
            return 0
        for r in rows:
            r["etf_name"] = name
        return _upsert_daily(conn, rows, ["etf_name", "open", "high", "low", "close", "amount"])
    except Exception:  # noqa: BLE001
        return 0


def _has_recent_data(conn, code: str, days: int = 5) -> bool:
    """检查 etf_daily 是否有近 days 日数据(有则跳过采集,节省时间)。"""
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days * 2)).strftime("%Y%m%d")
    r = conn.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE etf_code=? AND date>=? AND close IS NOT NULL",
        (code, cutoff),
    ).fetchone()
    return r[0] > 0


def main() -> None:
    parser = argparse.ArgumentParser(description="P1-新-C 阶段2 全市场 ETF 评分清单")
    parser.add_argument("--no-fetch", action="store_true",
                        help="跳过动态采集,仅用 DB 已有数据算分(快速验证)")
    parser.add_argument("--buy-top", type=int, default=DEFAULT_BUY_TOP,
                        help=f"buy_list 容量(默认 {DEFAULT_BUY_TOP})")
    parser.add_argument("--sell-top", type=int, default=DEFAULT_SELL_TOP,
                        help=f"sell_list 容量(默认 {DEFAULT_SELL_TOP})")
    parser.add_argument("--limit", type=int, default=0,
                        help="只跑前 N 只 ETF(0=全部,用于小规模验证)")
    parser.add_argument("--full-market", action="store_true",
                        help="跑全市场 A股股票型 ETF(universe_etf_codes,~1300-1400 只,慢)"
                             " 默认跑代表性 62 只清单(核心宽基12+行业~30+主题~20)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()  # 幂等:首次跑加 open/high/low 列
    if args.full_market:
        universe = universe_etf_codes(refresh=True)
    else:
        universe = list(REPRESENTATIVE_ETF_CODES)
        print(f"  [universe] 用代表性清单 {len(universe)} 只 "
              f"(核心宽基12+行业~30+主题~20,加 --full-market 跑全市场)", flush=True)
    if args.limit > 0:
        universe = universe[:args.limit]
    print(f"-> 预生成 {len(universe)} 只全市场 ETF 评分清单 (etf_score_list.json) ...")
    print(f"   buy_top={args.buy_top} sell_top={args.sell_top} fetch={'skip' if args.no_fetch else 'on'}")
    t_start = time.time()
    buy_list: list[dict] = []
    sell_list: list[dict] = []
    errors: list[dict] = []
    payload_date = ""
    fetch_count = 0
    skip_count = 0

    conn = get_conn()
    try:
        for i, (code, name, _mkt) in enumerate(universe, 1):
            try:
                t0 = time.time()
                # 动态采集(自包含):DB 无近5日数据 -> fetch+upsert
                if not args.no_fetch:
                    if _has_recent_data(conn, code):
                        skip_count += 1
                    else:
                        n = _fetch_and_upsert_ohlc(code, name, conn)
                        if n > 0:
                            fetch_count += 1

                # 定期 checkpoint 防 WAL 膨胀损坏(阶段2 事故:跑 530 只时 WAL 损坏回滚
                # 致 open/high/low 列丢失,后续 INSERT 报 no such column: open)
                if i % 100 == 0:
                    try:
                        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    except Exception:  # noqa: BLE001
                        pass

                alert = compute_alert_for_target(code, "etf")
                high_alert = alert.get("high")
                low_alert = alert.get("low")
                date = alert.get("date") or ""
                if date and not payload_date:
                    payload_date = date

                # 阶段2 全市场太慢,先按阈值过滤,只对入围的算 reason_summary
                is_nt = is_national_team(code)
                in_buy = (high_alert is not None and high_alert < 60
                          and _hands_for_low(low_alert) > 0)
                in_sell = (high_alert is not None)  # sell_list 按 high DESC 取 top N

                human = {"high": "", "low": ""}
                if in_buy or in_sell:
                    reason = build_reason(code, "etf", alert_result=alert, include_analogy=True)
                    human = reason.get("human_text", {})
                low_text = _summarize(human.get("low"))
                high_text = _summarize(human.get("high"))

                elapsed = time.time() - t0
                if i % 50 == 0 or i <= 5 or in_buy:
                    print(f"  [{i:4d}/{len(universe)}] {code} {name[:10]}: "
                          f"high={high_alert} low={low_alert} ({elapsed:.1f}s)"
                          f"{' [BUY]' if in_buy else ''}", flush=True)

                if in_buy:
                    hands = _hands_for_low(low_alert)
                    buy_list.append({
                        "etf_code": code,
                        "name": name,
                        "score": low_alert,
                        "hands": hands,
                        "high_alert": high_alert,
                        "low_alert": low_alert,
                        "is_national_team": is_nt,
                        "reason_summary": low_text,
                    })

                if in_sell:
                    sell_list.append({
                        "etf_code": code,
                        "name": name,
                        "score": high_alert,
                        "high_alert": high_alert,
                        "low_alert": low_alert,
                        "sell_signal": _sell_signal_for_high(high_alert),
                        "is_national_team": is_nt,
                        "reason_summary": high_text,
                    })
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc(limit=3)
                errors.append({
                    "etf_code": code, "name": name,
                    "error": f"{type(e).__name__}: {e}", "traceback": tb,
                })
                if len(errors) <= 5:
                    print(f"  [{i:4d}/{len(universe)}] {code} {name} FAILED: "
                          f"{type(e).__name__}: {e}", flush=True)
    finally:
        conn.close()

    # 排序 + 取 top N
    buy_list.sort(key=lambda x: (x.get("low_alert") or 0), reverse=True)
    sell_list.sort(key=lambda x: (x.get("high_alert") or 0), reverse=True)
    buy_list = buy_list[:args.buy_top]
    sell_list = sell_list[:args.sell_top]

    payload = {
        "date": payload_date,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": (f"全市场 A股股票型 ETF ({len(universe)} 只) - 阶段2 扩采集"
                   f" [ETF调权={'on' if ETF_ADJUST_ENABLED else 'off(待回测验证)'}]"
                   if args.full_market
                   else f"代表性 ETF 清单 ({len(universe)} 只: 核心宽基12+行业~30+主题~20) - 阶段2"
                   f" [ETF调权={'on' if ETF_ADJUST_ENABLED else 'off(待回测验证)'}]"),
        "universe_count": len(universe),
        "full_market": args.full_market,
        "etf_adjust": ETF_ADJUST_ENABLED,  # 阶段2: 是否启用 ETF 专属调权(默认 off,待回测验证)
        "buy_top": args.buy_top,
        "sell_top": args.sell_top,
        "fetch_count": fetch_count,
        "skip_count": skip_count,
        "buy_list": buy_list,
        "sell_list": sell_list,
    }
    if errors:
        payload["errors"] = errors

    out_path = DATA_DIR / "etf_score_list.json"
    _write_json_gz(out_path, payload)
    elapsed = time.time() - t_start
    print(f"\n✓ 完成: universe={len(universe)} buy={len(buy_list)} sell={len(sell_list)} "
          f"err={len(errors)} fetch={fetch_count} skip={skip_count} 耗时={elapsed:.1f}s")
    print(f"  输出: {out_path}")


if __name__ == "__main__":
    main()
