#!/usr/bin/env python3
"""P1-新-C §ETF 买卖清单 AI评分 tab: 12 国家队 ETF 评分排序输出。

复用 compute_alert_for_target(target_type="etf") (app/alert_score.py L527 已支持 ETF)
+ build_reason (app/alert_reason.py L363) 取 human_text 摘要。

输出: static-site/data/etf_score_list.json (+ .json.gz)
  {
    "date": "20260722",
    "updated_at": "...",
    "buy_list": [
      {etf_code, name, score, hands, high_alert, low_alert, is_national_team, reason_summary},
      ...
    ],
    "sell_list": [
      {etf_code, name, score, high_alert, low_alert, sell_signal, is_national_team, reason_summary},
      ...
    ],
    "errors": [...]
  }

排序与过滤口径:
- buy_list: high_alert<60 (非过热) + low_alert>=50 (有机会), 按 low_alert DESC 排序
  手数 3/2/1/0 映射: low_alert>=70 -> 3手 / 60-70 -> 2手 / 50-60 -> 1手 / <50 -> 0手不入清单
  score = low_alert (机会分, 越高越适合买)
- sell_list: 全部 12 ETF 按 high_alert DESC 排序
  sell_signal: high_alert>70 建议卖 / >60 观察 / 否则持有
  score = high_alert (过热分, 越高越适合卖)
- reason_summary: build_reason human_text.low (buy) / human_text.high (sell) 前 100 字摘要
- is_national_team: 本清单 12 只全是国家队 ETF, 恒为 true

异常处理: 单只 ETF 失败进 errors[], 不中断主流程。

用法:
  .venv/bin/python scripts/export_etf_score_list.py
"""
from __future__ import annotations

import gzip
import json
import sys
import time
import traceback
from pathlib import Path

# 不用 .resolve(): trade-data/scripts 是 trade/scripts 的 hardlink (同 inode),
# resolve() 会跳回 trade 致输出路径绕过 trade-data 写到 trade
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.alert_reason import build_reason  # noqa: E402
from app.alert_score import compute_alert_for_target  # noqa: E402
from app.collector.etf_national_team import ETF_LIST  # noqa: E402

DATA_DIR = ROOT / "static-site" / "data"


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


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"-> 预生成 {len(ETF_LIST)} 只国家队 ETF 评分清单 (etf_score_list.json) ...")
    t_start = time.time()
    buy_list: list[dict] = []
    sell_list: list[dict] = []
    errors: list[dict] = []
    payload_date = ""

    for i, (code, name, _idx, _mkt) in enumerate(ETF_LIST, 1):
        try:
            t0 = time.time()
            alert = compute_alert_for_target(code, "etf")
            reason = build_reason(code, "etf", alert_result=alert, include_analogy=True)
            high_alert = alert.get("high")
            low_alert = alert.get("low")
            date = alert.get("date") or ""
            if date and not payload_date:
                payload_date = date

            human = reason.get("human_text", {})
            low_text = _summarize(human.get("low"))
            high_text = _summarize(human.get("high"))

            dt = time.time() - t0
            print(f"  [{i:2d}/{len(ETF_LIST)}] {code} {name}: "
                  f"high={high_alert} low={low_alert} ({dt:.1f}s)")

            # buy_list: high_alert<60 非过热 + low_alert>=50 有机会, 入清单后按 low DESC 排序
            if high_alert is not None and high_alert < 60:
                hands = _hands_for_low(low_alert)
                if hands > 0:  # 0 手不入清单
                    buy_list.append({
                        "etf_code": code,
                        "name": name,
                        "score": low_alert,
                        "hands": hands,
                        "high_alert": high_alert,
                        "low_alert": low_alert,
                        "is_national_team": True,
                        "reason_summary": low_text,
                    })

            # sell_list: 全部 12 ETF, 按 high DESC 排序, 给卖出建议
            sell_list.append({
                "etf_code": code,
                "name": name,
                "score": high_alert,
                "high_alert": high_alert,
                "low_alert": low_alert,
                "sell_signal": _sell_signal_for_high(high_alert),
                "is_national_team": True,
                "reason_summary": high_text,
            })
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc(limit=3)
            errors.append({
                "etf_code": code, "name": name,
                "error": f"{type(e).__name__}: {e}", "traceback": tb,
            })
            print(f"  [{i:2d}/{len(ETF_LIST)}] {code} {name} FAILED: "
                  f"{type(e).__name__}: {e}")

    # 排序
    buy_list.sort(key=lambda x: (x.get("low_alert") or 0), reverse=True)
    sell_list.sort(key=lambda x: (x.get("high_alert") or 0), reverse=True)

    payload = {
        "date": payload_date,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "12 国家队宽基 ETF (etf_national_team.ETF_LIST)",
        "buy_list": buy_list,
        "sell_list": sell_list,
    }
    if errors:
        payload["errors"] = errors

    out_path = DATA_DIR / "etf_score_list.json"
    _write_json_gz(out_path, payload)
    elapsed = time.time() - t_start
    print(f"\n✓ 完成: buy={len(buy_list)} sell={len(sell_list)} err={len(errors)} "
          f"耗时={elapsed:.1f}s")
    print(f"  输出: {out_path}")


if __name__ == "__main__":
    main()
