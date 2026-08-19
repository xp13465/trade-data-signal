#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻三源采集:东财7x24 / 财联社电报 / 金十flash → data/news_digest.json

目的:每30分钟(7×24,launchd :01/:31 两档)采集财经快讯,供 AI 每日预测(gen_daily_brief.py)的
      新闻面/宏观事件日历维度消费 + 前端「今日要闻/明日关键事件」实时展示。

核心口径(2026-08-16 用户定,时间窗口根治):
  - 新闻无「交易日/工作日」概念(主控认知修正):交易盘面(指数/分时/K线)才用 is_trading_day,
    新闻采集 365 天 7×24 每30分钟照采,周末/节假日就是当日新闻(对周一预测有价值)。
  - 每30分钟增量采集 + 按当天累积归档:每次采集把「当前这一时间段内新增/回归」的条目
    合并进当天归档 news_digest/<date>.json + 当日 news_digest.json(title 归一化去重,幂等);
    重复跑不重复,弥补「16:45 后 ~23:59 新闻永远丢失」的固定窗口缺陷。
  - 每月/每天不变式:date 字段=采集的自然日(日历日),不随交易日概念变化。

口径(单次采集内的稳定部分,与之前一致):
  - 三源独立 try/except,单源失败不影响其他源落盘。
  - 只保留「目标日期当天」的条目;总量 ≤ NEWS_CAP 条,重要(important/level)优先。
  - title 跨源相似去重(归一化:转大写 + 去空白/标点 后比较)。
  - 排序口径(2026-08-18 用户定):upcoming 段最前 → 段内(重要度 → 时间新)优先,
    今日要闻按重要程度排序(不用时间序)。
  - 明日关键事件(upcoming)判定(2026-08-18 修 bug):基于标题日期解析,仅当解析出的
    事件日期 == 目标日+1(明天)才进 upcoming;今天已发布/已发生(日期=今天或解析不出
    明确未来日期)一律 news,宁缺毋滥,绝不把当日新闻/隔多天事件当「明日关键事件」。

输入依赖:
  - 数据源:三源公开 HTTP 接口(免签,仅 UA / 固定 header)。
  - 日期:默认 datetime.date.today();可用 --date YYYY-MM-DD 指定(测试历史/补采)。

输出:
  - data/news_digest.json,单日「累积快照」文件,前端今日要闻实时读。
  - data/news_digest/<date>.json,按日期归档累积:每小时把当天新增合并进去(累积幂等),
    历史 AI 预测重跑/校对按目标日期读对应归档(_load_news_inject 读侧增量续接)。

schema(钉死):
  {
    "date": "2026-08-16",
    "generated_at": "2026-08-16 16:45:00",
    "sources": {"eastmoney": 42, "cls": 15, "jin10": 21},
    "news": [{"source":"eastmoney|cls|jin10","time":"HH:MM","title":"...","summary":"...",
              "important": true/false,"kind":"news|upcoming"}],
    "upcoming": [{"source":"...","title":"国新办17日下午发布会...","time":"..."}]
  }

复现命令(7×24 直接跑,无交易日闸门):
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/fetch_news.py
  # 指定日期补采
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/fetch_news.py --date 2026-08-14

关键示例口径:东财 page_size=50 取第一页当天;财联社 rn 上限 20 用 lastTime 循环翻页;
  金十 max_time 翻页取当天;时效取三源各自字段 showTime / ctime / time 归一化。

历史教训引用:§23.2 L37/L38(非交易日不触发的教训)已被 2026-08-16 用户/主控认知修正取代——
  该教训只适用于交易盘面数据,不适用于新闻采集(新闻 7×24 无日历概念)。
"""
import argparse
import datetime as dt
import html as _html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
OUT_FILE = DATA_DIR / "news_digest.json"
ARCHIVE_DIR = DATA_DIR / "news_digest"  # 按日期归档累积: news_digest/<date>.json

# launchd 主库/主数据 = 部署源树(trade-data),update_all/deploy.sh 从它 rsync 到 trade 上线
MAIN_REPO = Path("/Users/linhuichen/code/trade-data")


# 统一部署源树/上传 helper(防再犯机制 E, 2026-08-18): pick_repo/pick_git_repo/force_env/guard
# 写部署源树(static-site/data) + R2 上传 + staticdata 同步统一走 scripts/pick_repo.py,
# env 用 force_env 强制覆盖 REPO/GIT_REPO(不用 setdefault),防子进程解析到与写入不一致的目录
# (2026-08-18 断点根因: fetch_news/项6 写错源树 → deploy rsync 反覆盖线上, §23.11 不静默)。
try:
    from scripts.pick_repo import (  # noqa: E402  (REPO 在 sys.path 时)
        candidate_repos, pick_repo, pick_git_repo, force_env, guard_deploy_source_tree,
    )
except Exception:  # noqa: BLE001  (scripts/ 在 sys.path 时)
    from pick_repo import (  # noqa: E402
        candidate_repos, pick_repo, pick_git_repo, force_env, guard_deploy_source_tree,
    )

# 允许 app.calendar 被 import（同 daily_summary_email.py 做法）
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NEWS_CAP = 40          # news 总量上限

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


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


def _clean_html(text) -> str:
    """HTML 纯文本化清洗(2026-08-16 修 bug:金十 title/summary 直接存 HTML 源码泄漏)。

    剥标签(<br>/<b>/<span class=...> 等) → 标签换成空白/换行, 解 HTML 实体(html.unescape),
    连续空白折叠为单空格, 收尾 strip。三源 title/summary 都过此清洗(源头根治);
    前端另有 _dbNewsCleanHtml 兜底清洗(双层,防历史/未来脏数据 XSS + 纯文本化)。
    不碰 _norm_title(去重仍用原始粗粒度归一化,清洗只影响存储文本,不影响去重幂等)。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # 块级/换行标签换成换行, 其余标签(<b>/<span>/... )换成空, 保留实体待 unescape
    text = re.sub(r"<(br|/br|p|/p|div|/div|li|/li|tr|/tr)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    # 兜底: title 由 content[:120] 截断可能留下未闭合标签残尾(如 "…<span class=\"secti" 无 ">"),
    # 剥掉「行尾以 < 开头的未闭合标签残尾」(新闻纯文本里基本不出现此形态, 剥之安全)。
    text = re.sub(r"<\s*/?\s*[a-zA-Z][^>]*$", "", text).strip()
    # 连续空白(含换行)折叠为单空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm_title(t: str) -> str:
    """title 归一化,用于跨源相似去重。"""
    if not t:
        return ""
    return re.sub(r"[\s·—\-:：,，。.、()（）\'\"“”]+", "", t.upper())


def _read_json(path: Path):
    """读 JSON;缺失/解析失败返回 None(不抛)。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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
            "title": _clean_html(it.get("title") or ""),
            "summary": _clean_html(it.get("summary") or ""),
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
            title = _clean_html(it.get("title") or "")
            if not title:
                continue
            level_raw = (it.get("level") or "C").strip().lower()
            out.append({
                "source": "cls",
                "time": dt_local.strftime("%H:%M"),
                "title": title,
                "summary": _clean_html(it.get("brief") or it.get("content") or ""),
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
            content = _clean_html(inner.get("content") or "")
            raw_title = (inner.get("title") or "").strip()
            title = _clean_html(raw_title) or content[:120]
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


# ── 预告提取(2026-08-18 修 bug:基于「标题日期解析」判定是否明日事件,不再用关键词) ──
# 背景(用户点名):upcoming 段被「今天已发布/已发生的新闻」污染(海康威视发布/黄金震荡/英国失业率
#   公布/高盛发布研报等,全是含「发布/公布」等动词的当日新闻),也有隔多天的未来事件(上合论坛 9/14、
#   商务部 8/20、交通部 8/20)。根因 = 旧 classify_kind 用 _UPCOMING_KW=("预告","将于","公布","举行","发布")
#   只要标题含任一关键词就归 upcoming,完全没解析标题里的日期 → 今日新闻被误判为「明日关键事件」。
# 修法(§23.2 修完整/宁缺毋滥,用户原话「明日关键事件必须全是明天的事件」):
#   - upcoming 判定的唯一依据 = 标题解析出的明确事件日期 == 目标日+1(明天);
#   - 今天已发布/已发生(日期=今天或解析不出明确未来日期)一律 news,绝不进 upcoming;
#   - 解析不出明确「明天」日期的宁缺毋滥不进 upcoming。


def _parse_event_date(title: str, target) -> "dt.date | None":
    """从标题解析「事件发生的绝对日期」,返回 dt.date 或 None(解析不出/不明确)。

    支持模式(宁缺毋滥,解析不出明确未来日期返回 None):
      - 「YYYY年X月X日」(显式年份,处理跨年)
      - 「明日」/「明天」→ target+1
      - 「X月X日」/「X月X-Y日」/「X月X日至X日」(取起始日;无年份时 mo<target.month 视为跨年次年)
      - 「X日」(无月份,归属 target 当月,当月已过则归属下月)
      - 「周X」(星期X:只收「==明天」的周X,其余跨周边界宁缺毋滥返回 None)
    返回的日期用于与 target+1 比较判定是否「明日事件」。
    """
    # 显式年份 + 月日(如「2026年8月20日」;「2027年预算」的 2027 不是事件日期,不匹配)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]", title)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    # 明日 / 明天
    if re.search(r"明日|明天", title):
        return target + dt.timedelta(days=1)
    # X月X日(可能带范围 至/到/[-—],取起始日)
    m = re.search(r"(\d{1,2})月(\d{1,2})(?:[日号])(?:\s*(?:至|到|[-—])\s*\d{1,2}[日号])?", title)
    if m:
        mo, d = int(m[1]), int(m[2])
        y = target.year
        if mo < target.month:  # 无年份且月份已过 → 跨年(如 12月→次年1月)
            y += 1
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    # X日(无月份):归属 target 当月(若已过则下月)
    m = re.search(r"(?<![0-9月])(\d{1,2})[日号]", title)
    if m:
        d = int(m[1])
        cands = [(target.year, target.month)]
        if target.month == 12:
            cands.append((target.year + 1, 1))
        else:
            cands.append((target.year, target.month + 1))
        for y, mo in cands:
            try:
                cand = dt.date(y, mo, d)
            except ValueError:
                continue
            if cand >= target:
                return cand
        return None
    # 周X(星期):只收「==明天」的周X,否则不确定(跨周边界)宁缺毋滥
    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    m = re.search(r"周([一二三四五六日天])", title)
    if m:
        wd = weekday_map[m.group(1)]
        tomorrow = target + dt.timedelta(days=1)
        return tomorrow if tomorrow.weekday() == wd else None
    return None


# 东财 7x24 无重要度字段,用「前瞻/重磅/宏观机构」等关键词做重要度近似(cls/jin10 用数据源自带 important)。
# 2026-08-18 收紧:去掉「发布/公布/举行」等纯状态动词(它们不表示重要,是「发生了」),避免营销/行情标题
#   (黄金震荡—增强版发布/新版发布/高盛发布研报)被标重要挤占「今日要闻按重要度排序」的头部。
_IMPORTANT_KW = ("预告", "将于", "定于", "即将", "重磅", "突发", "首次", "首发",
                 "央行", "国常会", "证监会", "统计局", "发布会", "国务院", "财政部")


def _is_important_title(t: str) -> bool:
    return any(k in t for k in _IMPORTANT_KW)


def classify_kind(title: str, target) -> str:
    """upcoming 判定 = 标题解析出的事件日期 == 明天(target+1);否则 news(宁缺毋滥)。"""
    try:
        d = _parse_event_date(title, target)
    except Exception:  # noqa: BLE001
        d = None
    return "upcoming" if (d is not None and d == target + dt.timedelta(days=1)) else "news"


# ── 汇总 + 去重 + 排序 ──
def build_digest(day_str, sources_map, target):
    """三源 raw 列表 → (news, upcoming) 两个已排序截断列表。

    排序口径(2026-08-18 用户定「今日要闻按重要程度排序,不要时间序」):
      - upcoming 段整体排最前(防被 cap 截断,保证明日事件优先保留);
      - 段内统一 (重要度 important 优先 → 时间新优先) 二级排序;
      - news 段 = 重要度优先 → 时间新优先,不再让时间主导。
    """
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
        kind = classify_kind(it["title"], target)
        it["kind"] = kind
        unique.append(it)

    # 排序:upcoming 段最前 → 段内 (重要度 → 时间新) 优先
    def sort_key(it):
        return (1 if it["kind"] == "upcoming" else 0,
                1 if it.get("important") else 0,
                it.get("time", ""))

    unique.sort(key=sort_key, reverse=True)

    # news 总量控制
    capped = unique[:NEWS_CAP]

    upcoming = [it for it in capped if it["kind"] == "upcoming"]
    news = [it for it in capped if it["kind"] != "upcoming"]
    return news, upcoming


def _dedup_news_items(items: list) -> list:
    """按 (归一化 title, time) 去重(跨源相似 title 同判),返回去重后的 items(保持给出顺序)。"""
    seen = set()
    out = []
    for it in items:
        key = (_norm_title(it.get("title") or ""), it.get("time") or "")
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _merge_new_into_archive(archive_raw: dict, new_raw: list, sources_map: dict, target) -> tuple:
    """把本次采集的当天条目(new_raw)合并进既有归档(archive_raw),累积幂等。

    新闻数据源(东财 page_size=50 / 财联社 / 金十)每次拉取基本是「当天全量快照」,
    叠加每小时跑 = 把既有归档所有条目 union 本次条目再整体去重/排序/截断:
      - 既有 + 本次 一起 title 归一化去重(补之前因数据源翻页波动漏掉的条目 / 新到条目)。
      - 2026-08-18 修 bug:kind 一律用新日期解析重算(不沿用归档旧 kind,清掉旧代码误分的
        「今天已发布却标 upcoming」残留,保证明日关键事件全为明天事件)。
      - 排序规则沿用 build_digest(upcoming 段最前 → 段内 重要度 → 时间新优先),截断 NEWS_CAP。
    返回 (news, upcoming)。archive_raw 可为 None(首采/无归档)。
    """
    combined = list((archive_raw or {}).get("news") or []) + list(new_raw)
    combined = _dedup_news_items(combined)

    # 补 kind(强制用新日期解析重算,不沿用归档旧 kind)
    for it in combined:
        it["kind"] = classify_kind(it.get("title") or "", target)

    # 排序 + 截断(复用 build_digest 内联规则,保证首采/合并同序)
    def sort_key(it):
        return (1 if it["kind"] == "upcoming" else 0,
                1 if it.get("important") else 0,
                it.get("time", ""))

    combined.sort(key=sort_key, reverse=True)
    capped = combined[:NEWS_CAP]
    upcoming = [it for it in capped if it["kind"] == "upcoming"]
    news = [it for it in capped if it["kind"] != "upcoming"]
    return news, upcoming


# ── 归档路径(按年分目录 news_digest/<YYYY>/<date>.json,2026-08-16 主控存储结构决定)──
def archive_path(day_str: str) -> Path:
    """当日归档路径 = news_digest/<YYYY>/<date>.json。
    年目录下旧扁平路径 data/news_digest/<date>.json(迁移期)兼容读/写(见 _read_existing_archive)。"""
    y = day_str[:4]
    return ARCHIVE_DIR / y / f"{day_str}.json"


def read_existing_archive(day_str: str) -> dict:
    """读当日既有归档以便增量合并。优先读年目录, fallback 旧扁平路径(迁移兼容)。"""
    p = archive_path(day_str)
    raw = _read_json(p)
    if isinstance(raw, dict):
        return raw
    legacy = ARCHIVE_DIR / f"{day_str}.json"
    if legacy.exists():
        return _read_json(legacy) or {}
    return {}


def _write_index() -> None:
    """写 news_digest/_index.json: 每天一条 {date, count, path},供前端"有哪些天有数据"展示。
    扫描年目录下所有 <today.json 及今天}(避免把未来日期误列; 已存在的扁平旧档也计入)。"""
    index_file = ARCHIVE_DIR / "_index.json"
    entries = []
    seen_dates = set()
    if ARCHIVE_DIR.is_dir():
        # 年目录 2026/2026-08-16.json
        for ydir in sorted(ARCHIVE_DIR.iterdir()):
            if not ydir.is_dir() or not ydir.name.isdigit():
                continue
            for pf in sorted(ydir.glob("*.json")):
                dd = pf.stem  # YYYY-MM-DD
                if dd[:4] != ydir.name or dd in seen_dates:
                    continue
                seen_dates.add(dd)
                cnt = 0
                try:
                    cnt = len((json.loads(pf.read_text(encoding="utf-8")) or {}).get("news") or [])
                except Exception:
                    cnt = 0
                entries.append({"date": dd, "count": cnt,
                                "path": f"news_digest/{ydir.name}/{pf.name}"})
        # 旧扁平路径(迁移期)仍存在的也计入(去重)
        for pf in ARCHIVE_DIR.glob("*.json"):
            if pf.name == "_index.json":
                continue
            dd = pf.stem
            if dd in seen_dates:
                continue
            seen_dates.add(dd)
            cnt = 0
            try:
                cnt = len((json.loads(pf.read_text(encoding="utf-8")) or {}).get("news") or [])
            except Exception:
                cnt = 0
            entries.append({"date": dd, "count": cnt, "path": f"news_digest/{pf.name}"})
    entries.sort(key=lambda e: e["date"], reverse=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        index_file.write_text(
            json.dumps({"generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "days": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ [fetch_news] 写 _index.json 失败(不阻塞): {e}")


def main():
    ap = argparse.ArgumentParser(description="新闻三源采集 → data/news_digest.json(7×24 每30分钟:01/:31 增量累积)")
    ap.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD,默认今天")
    ap.add_argument("--force", action="store_true",
                    help="兼容保留: 新闻采集无交易日概念,本参数已无闸门作用(历史调用兼容)")
    args = ap.parse_args()

    if args.date:
        target = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = dt.date.today()
    day_str = target.strftime("%Y-%m-%d")
    today_ts = dt.datetime.combine(target, dt.time()).timestamp()

    # 新闻采集无交易日/工作日概念(2026-08-16 主控认知修正): 7×24 每30分钟照采,无闸门。
    # 交易盘面(指数/分时/K线)才有 is_trading_day,新闻无日历概念。

    # 三源独立采集(本次抓到当天条目)
    sources_map = {
        "eastmoney": fetch_eastmoney(day_str),
        "cls": fetch_cls(day_str, today_ts),
        "jin10": fetch_jin10(day_str),
    }
    new_news, new_upcoming = build_digest(day_str, sources_map, target)
    new_items = new_news + new_upcoming

    # 每30分钟增量合并: 先读既有当日归档,把本次 new_items 合并进去累积(首采 archive 为空)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = archive_path(day_str)  # news_digest/<YYYY>/<date>.json
    archive_raw = read_existing_archive(day_str)
    news, upcoming = _merge_new_into_archive(archive_raw, new_items, sources_map, target)
    merge_from = "合并已有归档" if isinstance(archive_raw, dict) and archive_raw else "首采新建"

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

    # 当日 news_digest.json(累积快照,前端实时读) + 归档同写(年目录) + 每天索引
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    _write_index()
    print(f"[fetch_news] 已写 {OUT_FILE} + 归档 {archive_file} date={day_str} "
          f"[{merge_from}] news={len(news)} upcoming={len(upcoming)} "
          f"sources={digest['sources']}")

    # ── 采集成功后直接同步上线(2026-08-16 §22/reviewer#1: 不依赖 gen_daily_brief 20:40 上传链)──
    # 问题: 16:45 采完只落 data/news_digest.json,上线完全依赖 gen_daily_brief 20:40 的上传链,
    #       导致 16:45→20:40 线上 news_digest.json 还是昨日,前端展示旧闻+「明日关键事件」日期错位;
    #       且 gen_daily_brief 当天失败时当日新闻面滞后。
    # 修法: 采完当日 news_digest.json + 归档后,直接 copy 到 static-site/data/ + 上传 R2 data/ 前缀
    #       + staticdata 同步(与 gen_daily_brief 同链路,gen_daily_brief 20:40 再跑幂等覆盖不冲突)。
    sync_news_digest_live(day_str)


# ── 采集后直接同步上线(2026-08-16 §22/reviewer#1: 不依赖 gen_daily_brief 上传链)─────────────
def sync_news_digest_live(day_str: str) -> None:
    """把当日 news_digest.json + 全部日期归档,同步到 static-site/data/ + R2 + staticdata。

    参考 gen_daily_brief.py 的上传链(copy → upload-data-files → staticdata_sync.sh),
    让 fetch_news(launchd 每30分钟 :01/:31)采集完即上线,前端随即读到当日新闻,不等 20:40。
    写位置 = pick_repo()(同 gen_daily_brief,优先 trade-data=部署源树):
    部署链 update_all/deploy.sh 从 trade-data rsync 到 trade 上线,若只写 trade/static-site/data,
    下一次 deploy(REPO=trade-data)会把 trade-data/static-site/data 旧版 rsync 覆盖新版(8/18 断点根因)。
    故写 + 上传/staticdata 源目录全部走 pick_repo() 选中的同一树,保证部署链读到新版不 clobber。
    失败不阻塞主流程(采集已落盘,盘后 gen_daily_brief 20:40 兜底再同步)。
    """
    try:
        repo = pick_repo()
        static_dir = repo / "static-site" / "data"
        static_dir.mkdir(parents=True, exist_ok=True)
        # 0. 把当日根快照 + 归档也镜像到所选 repo 的 data/(部署源树根数据,gen_daily_brief news_src 先读它)
        try:
            (repo / "data").mkdir(parents=True, exist_ok=True)
            if OUT_FILE.exists():
                shutil.copy2(OUT_FILE, repo / "data" / "news_digest.json")
            if ARCHIVE_DIR.is_dir():
                dst_arch = repo / "data" / "news_digest"
                dst_arch.mkdir(parents=True, exist_ok=True)
                for ydir in sorted(ARCHIVE_DIR.iterdir()):
                    if not ydir.is_dir() or not ydir.name.isdigit():
                        continue
                    d_y = dst_arch / ydir.name
                    d_y.mkdir(parents=True, exist_ok=True)
                    for f in sorted(ydir.glob("*.json")):
                        shutil.copy2(f, d_y / f.name)
                if (ARCHIVE_DIR / "_index.json").exists():
                    shutil.copy2(ARCHIVE_DIR / "_index.json", dst_arch / "_index.json")
        except Exception as _e:  # noqa: BLE001
            print(f"⚠ [fetch_news] 根 data 镜像失败(不阻塞): {_e}")
        # ① copy 当日 news_digest.json -> static-site/data/
        if OUT_FILE.exists():
            shutil.copy2(OUT_FILE, static_dir / "news_digest.json")
        # ② 归档目录累积(按年分目录 news_digest/<YYYY>/<date>.json 全量 copy,含 _index.json):
        #    让历史日归档也被前端/README 历史入口读到(幂等覆盖,不删历史)。
        #    兼容: 旧扁平 data/news_digest/<date>.json(迁移期)也一并 copy 到 static-site 对应扁平位,
        #    保证前端旧路径 fallback 仍读得到(不破坏 #13 已上线前端)。
        arch_files: list[str] = ["news_digest.json"]
        if ARCHIVE_DIR.is_dir():
            sd_nd = static_dir / "news_digest"
            sd_nd.mkdir(parents=True, exist_ok=True)
            # 年目录结构
            for ydir in sorted(ARCHIVE_DIR.iterdir()):
                if not ydir.is_dir() or not ydir.name.isdigit():
                    continue
                dest_y = sd_nd / ydir.name
                dest_y.mkdir(parents=True, exist_ok=True)
                for arch_f in sorted(ydir.glob("*.json")):
                    shutil.copy2(arch_f, dest_y / arch_f.name)
                    arch_files.append(f"news_digest/{ydir.name}/{arch_f.name}")
            # 索引
            idx = ARCHIVE_DIR / "_index.json"
            if idx.exists():
                shutil.copy2(idx, sd_nd / "_index.json")
                arch_files.append("news_digest/_index.json")
            # 旧扁平路径(迁移期)仍存在的 copy 到 static-site 扁平位(前端旧路径 fallback)
            for arch_f in ARCHIVE_DIR.glob("*.json"):
                if arch_f.name == "_index.json":
                    continue
                shutil.copy2(arch_f, sd_nd / arch_f.name)
                if f"news_digest/{arch_f.name}" not in arch_files:
                    arch_files.append(f"news_digest/{arch_f.name}")
        # ③ R2 上传(data/ 前缀,upload-data-files 支持相对 data_dir 的子目录路径) — 读 .env 拿凭证
        # 统一 helper force_env(防再犯机制 E, 2026-08-18): 强制覆盖 REPO/GIT_REPO(不用 setdefault),
        # REPO=pick_repo() 选中的部署源树, GIT_REPO=trade git 仓, 使上传/staticdata 源目录
        # 与上面 static_dir 一致, 读新版上传, 不读另一树旧版(818-fix 精神, 扩展到部署源树)。
        env = force_env(dict(os.environ), repo)
        _load_dotenv(env)
        r = subprocess.run(
            [str(repo / ".venv/bin/python"), str(repo / "scripts/upload_r2.py"),
             "upload-data-files"] + arch_files,
            cwd=str(repo), env=env, timeout=120, capture_output=True, check=False)
        if r.returncode == 0:
            out = (r.stdout or b"").decode("utf-8", errors="replace").strip()
            print(f"[fetch_news] R2 同步 OK {out.splitlines()[-1] if out else ''}")
        else:
            err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
            print(f"⚠ [fetch_news] R2 上传 rc={r.returncode} {(r.stdout or b'').decode('utf-8','replace')[-300:] if r.stdout else ''} {err[-300:] if err else ''}")
        # ④ staticdata 同步(best-effort,防 deploy 外生成器留旧版;触发名 news-fetch)
        r2 = subprocess.run(
            ["bash", str(repo / "scripts/staticdata_sync.sh"), "news-fetch"] + arch_files,
            cwd=str(repo), env=env, timeout=600, capture_output=True, check=False)
        if r2.returncode != 0:
            err2 = (r2.stderr or b"").decode("utf-8", errors="replace").strip()
            print(f"⚠ [fetch_news] staticdata 同步 rc={r2.returncode} {(r2.stdout or b'').decode('utf-8','replace')[-200:] if r2.stdout else ''} {err2[-200:] if err2 else ''}")
        print(f"[fetch_news] 同步上线完成 date={day_str} (news_digest.json + {len(arch_files)-1} 个日期归档, repo={repo})")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ [fetch_news] 同步上线异常(不阻塞,盘后 gen_daily_brief 20:40 兜底): {e}")


def _load_dotenv(env: dict) -> None:
    """把 .env(R2 凭证)读进 env(仿 gen_daily_brief load_config 的候选路径,setdefault 不覆盖)。"""
    cands = [
        REPO / ".env",
        Path(env.get("REPO", "")) / ".env" if env.get("REPO") else None,
        Path(env.get("GIT_REPO", "")) / ".env" if env.get("GIT_REPO") else None,
        Path("/Users/linhuichen/code/trade/.env"),
    ]
    for c in cands:
        if not c or not c.exists():
            continue
        for line in c.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())


if __name__ == "__main__":
    main()
