#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻三源采集:东财7x24 / 财联社电报 / 金十flash → data/news_digest.json

目的:盘后(16:45 launchd)采集当日重要财经快讯,供 AI 每日预测(gen_daily_brief.py)的
      新闻面/宏观事件日历维度消费(见 docs/ai-predict-news-macro-research-sources.md 实测报告)。

口径:
  - 三源独立 try/except,单源失败不影响其他源落盘。
  - 只保留「目标日期当天」的条目;总量 ≤ NEWS_CAP 条,重要(important/level)优先。
  - title 跨源相似去重(归一化:转大写 + 去空白/标点 后比较)。
  - 预告提取:标题含「预告/将于/公布/举行/发布」等关键词 → kind=upcoming,另入 upcoming 段。
  - 交易日闸门:默认仅交易日写文件(is_trading_day,读 trade/data/trade_dates.txt 缓存,
    non-交易日不写);--force 跳过闸门(测试采集链路用,临时跑)。

输入依赖:
  - 数据源:三源公开 HTTP 接口(免签,仅 UA / 固定 header)。
  - 交易日:app.calendar.is_trading_day()(读 trade/data/trade_dates.txt 本地缓存)。
  - 日期:默认 datetime.date.today();可用 --date YYYY-MM-DD 指定(测试历史/补采)。

输出:
  - data/news_digest.json,单日文件,当天重复跑覆盖当天,不累积(幂等)。

schema(钉死):
  {
    "date": "2026-08-16",
    "generated_at": "2026-08-16 16:45:00",
    "sources": {"eastmoney": 42, "cls": 15, "jin10": 21},
    "news": [{"source":"eastmoney|cls|jin10","time":"HH:MM","title":"...","summary":"...",
              "important": true/false,"kind":"news|upcoming"}],
    "upcoming": [{"source":"...","title":"国新办17日下午发布会...","time":"..."}]
  }

复现命令:
  # 交易日默认跑(非交易日自动跳过)
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/fetch_news.py
  # 测试采集链路(非交易日 --force 也能落盘,验证三源可达)
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/fetch_news.py --force
  # 指定日期
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/fetch_news.py --date 2026-08-14 --force

关键示例口径:东财 page_size=50 取第一页当天;财联社 rn 上限 20 用 lastTime 循环翻页;
  金十 max_time 翻页取当天;时效取三源各自字段 showTime / ctime / time 归一化。

历史教训引用:§23.2 L37/L38 非交易日不触发(launchd 与脚本双重交易日闸门)。
"""
import argparse
import datetime as dt
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
OUT_FILE = DATA_DIR / "news_digest.json"

# 允许 app.calendar 被 import（同 daily_summary_email.py 做法）
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NEWS_CAP = 40          # news 总量上限
SCORE_IMPORTANT = 2    # important 条目 +2 分
SCORE_BASE = 1         # 普通当天条目 +1 分
SCORE_KIND_UPCOMING = 3  # 预告类额外加权,保证预告优先保留

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# ── 交易日判断(读项目缓存,较 akshare 每次联网最快且不依赖 akshare)──
def is_trading_day(d=None) -> bool:
    from app.calendar import is_trading_day as _isd
    return _isd(d)


# ── 三源 HTTP 采集 ──
def _http_get_json(url, headers=None, timeout=15, retries=2):
    """GET 并解析 JSON;失败重试。SSL 不校验 (CERT_NONE,本环境有自签 CA 链,
    同 fetch_etf_track_index.py / feishu_missed_fetch.py 既有做法)。"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last_err = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"[fetch_news] http 失败 url={url} err={last_err}")
    return None


def _norm_title(t: str) -> str:
    """title 归一化,用于跨源相似去重。"""
    if not t:
        return ""
    return re.sub(r"[\s·—\-:：,，。.、()（）\'\"“”]+", "", t.upper())


# ── 东财 7x24 ──
def fetch_eastmoney(day_str: str):
    """东财 getNewsByColumns,page_size=50 取第一页当天。返回 list[raw dict]。"""
    # 东财需 req_trace 参数(/comm/web 接口校验),用时间戳伪随机生成;带 Referer 更稳
    trace = "".join(f"{dt.datetime.now().timestamp():.6f}".split("."))
    url = (
        "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        "?client=web&biz=web_724&column=*&order=1&needInteractData=0"
        f"&page_index=1&page_size=50&req_trace={trace}"
    )
    headers = {"Referer": "https://finance.eastmoney.com/"}
    data = _http_get_json(url, headers=headers)
    out = []
    if not data or not isinstance(data, dict):
        return out
    items = data.get("data") or []
    if isinstance(items, dict):
        # 部分响应 data 为 dict {list: [...]}
        items = items.get("list") or []
    for it in items:
        show = (it.get("showTime") or "").strip()
        if not show.startswith(day_str):
            continue
        out.append({
            "source": "eastmoney",
            "time": show[11:16] if len(show) >= 16 else "",
            "title": (it.get("title") or "").strip(),
            "summary": (it.get("summary") or "").strip().replace("\n", " "),
            "url": it.get("url") or it.get("uniqueUrl") or "",
            "important": _is_important_title(it.get("title") or ""),
        })
    return out


# ── 财联社电报 ──
def fetch_cls(day_str: str, today_ts: float, max_pages: int = 30):
    """财联社 api/cache telegraph,lastTime 循环翻页取当天。
    翻页语义:第一页不带 lastTime(拿最新 20 条),每页用「本页最后一条 ctime」
    作下一页 lastTime 往前取更早数据,直到越过当天。"""
    base = "https://www.cls.cn/api/cache?name=telegraph&app=CailianpressWeb&os=web&sv=8.7.9"
    out = []
    last_time = None  # 第一页不带 lastTime,拿最新
    for _ in range(max_pages):
        url = base + (f"&lastTime={last_time}" if last_time else "")
        data = _http_get_json(url)
        if not data or not isinstance(data, dict):
            break
        items = (data.get("data") or {}).get("roll_data") or []
        if not items:
            break
        crossed_day = False
        for it in items:
            ctime = it.get("ctime")
            if not ctime:
                continue
            ctime_f = int(ctime)
            if ctime_f < today_ts - 3600:
                # 已越过当天往后(留 1h 缓冲),停
                crossed_day = True
                break
            dt_local = dt.datetime.fromtimestamp(ctime_f)
            if dt_local.strftime("%Y-%m-%d") != day_str:
                continue
            title = (it.get("title") or "").strip()
            if not title:
                continue
            level_raw = (it.get("level") or "C").strip().lower()
            out.append({
                "source": "cls",
                "time": dt_local.strftime("%H:%M"),
                "title": title,
                "summary": (it.get("brief") or it.get("content") or "").strip().replace("\n", " "),
                "url": f"https://www.cls.cn/detail/{it.get('id')}" if it.get("id") else "",
                "important": level_raw in ("a", "b"),  # A/B 级视为重要
            })
        if crossed_day:
            break
        # 下一页:本页最后一条 ctime 往前
        last_record = items[-1]
        nc = last_record.get("ctime")
        last_time = int(nc) if nc else None
        if last_time is None:
            break
        if (data.get("data") or {}).get("has_more") is False:
            break
    return out


# ── 金十 flash ──
def fetch_jin10(day_str: str, max_pages: int = 30):
    """金十 get_flash_list,固定 header + max_time 翻页取当天。"""
    base = "https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1"
    headers = {
        "x-app-id": "bVBF4FyRTn5NJF5n",
        "x-version": "1.0.0",
        "Referer": "https://www.jin10.com/",
    }
    out = []
    max_time = None
    for _ in range(max_pages):
        max_time_q = urllib.parse.quote(str(max_time)) if max_time else None
        url = base + (f"&max_time={max_time_q}" if max_time else "")
        data = _http_get_json(url, headers=headers)
        if not data or not isinstance(data, dict):
            break
        items = data.get("data") or []
        if not items:
            break
        for it in items:
            ts = it.get("time")
            if not ts:
                continue
            ts_str = str(ts)
            if not ts_str.startswith(day_str):
                continue
            inner = it.get("data") or {}
            content = (inner.get("content") or "").strip()
            title = (inner.get("title") or "").strip() or content[:120]
            if not title:
                continue
            important = bool(it.get("important"))
            t = ts_str[11:16] if len(ts_str) >= 16 else ""
            out.append({
                "source": "jin10",
                "time": t,
                "title": title,
                "summary": content,
                "url": inner.get("link") or "",
                "important": important,
            })
        max_time = items[-1].get("time")
        if not max_time:
            break
    return out


# ── 预告提取 ──
_UPCOMING_KW = ("预告", "将于", "公布", "举行", "发布")


def _is_important_title(t: str) -> bool:
    return any(k in t for k in _UPCOMING_KW)


def classify_kind(title: str) -> str:
    return "upcoming" if _is_important_title(title) else "news"


# ── 汇总 + 去重 + 排序 ──
def build_digest(day_str, sources_map):
    """三源 raw 列表 → (news, upcoming) 两个已排序截断列表。"""
    # 评分排序准备
    combined = []
    for src, items in (
        ("eastmoney", sources_map.get("eastmoney")),
        ("cls", sources_map.get("cls")),
        ("jin10", sources_map.get("jin10")),
    ):
        for it in items or []:
            if not it.get("title"):
                continue
            combined.append(it)

    # title 去重(含跨源相似)
    seen_titles = set()
    unique = []
    for it in combined:
        nt = _norm_title(it["title"])
        if not nt or nt in seen_titles:
            continue
        seen_titles.add(nt)
        kind = classify_kind(it["title"])
        it["kind"] = kind
        unique.append(it)

    # 排序:重要优先 → 预告优先 → 时间新优先
    def score(it):
        s = SCORE_IMPORTANT if it.get("important") else 0
        if it.get("kind") == "upcoming":
            s += SCORE_KIND_UPCOMING
        s += SCORE_BASE
        return s

    unique.sort(key=lambda it: (score(it), it.get("time", "")), reverse=True)

    # news 总量控制
    capped = unique[:NEWS_CAP]

    upcoming = [it for it in capped if it["kind"] == "upcoming"]
    news = [it for it in capped if it["kind"] != "upcoming"]
    return news, upcoming


def main():
    ap = argparse.ArgumentParser(description="新闻三源采集 → data/news_digest.json")
    ap.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD,默认今天")
    ap.add_argument("--force", action="store_true", help="非交易日也写文件(测试采集链路用)")
    args = ap.parse_args()

    if args.date:
        target = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = dt.date.today()
    day_str = target.strftime("%Y-%m-%d")
    today_ts = dt.datetime.combine(target, dt.time()).timestamp()

    # 交易日闸门:非交易日不写新文件(L37/L38 教训)
    if not is_trading_day(target) and not args.force:
        print(f"[fetch_news] {day_str} 非交易日,跳过(不写文件)。如需测试链路加 --force")
        return

    # 三源独立采集
    sources_map = {
        "eastmoney": fetch_eastmoney(day_str),
        "cls": fetch_cls(day_str, today_ts),
        "jin10": fetch_jin10(day_str),
    }

    news, upcoming = build_digest(day_str, sources_map)

    digest = {
        "date": day_str,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {
            "eastmoney": len(sources_map["eastmoney"]),
            "cls": len(sources_map["cls"]),
            "jin10": len(sources_map["jin10"]),
        },
        "news": [{
            "source": it["source"],
            "time": it["time"],
            "title": it["title"],
            "summary": it["summary"],
            "important": it["important"],
            "kind": it["kind"],
        } for it in news],
        "upcoming": [{
            "source": it["source"],
            "time": it["time"],
            "title": it["title"],
            "important": it["important"],
        } for it in upcoming],
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    print(f"[fetch_news] 已写 {OUT_FILE} date={day_str} "
          f"news={len(news)} upcoming={len(upcoming)} "
          f"sources={digest['sources']}")


if __name__ == "__main__":
    main()
