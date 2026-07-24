"""FastAPI 后端：提供看板数据 + 手动补录 + 静态前端。

查询逻辑统一在 app/queries.py（main.py 路由 + export.py 导出共用）。
本文件只保留：路由薄化（调 queries.xxx）+ 订阅管理 + 手动补录 + 静态文件渲染。
"""
import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .collector.fetchers import load_config
from .compute import signal_stats as sigstats
from .db import get_conn
from . import queries

app = FastAPI(title="市场温度看板")
# 单版架构：前端统一在 static-site/，动态版挂载到根 /（/api/* 读 DB 不变）。
WEB_DIR = Path(__file__).absolute().parent.parent / "static-site"

_DATE_RE = re.compile(r"^\d{8}$")

# ---- 缓存策略中间件：对齐 static-site/_headers ----
# 版本化静态资源（index.html 引用均带 ?v=，内容变则 ?v= 变，可长缓存 immutable）
_VERSIONED_ASSETS = {"style.css", "app.min.js", "lab.min.js", "lab.css", "qr.js", "vendor/echarts.min.js"}

@app.middleware("http")
async def cache_control_middleware(request, call_next):
    resp = await call_next(request)
    # 路由已显式设置 Cache-Control（如 / index 路由）则不覆盖
    if resp.headers.get("cache-control"):
        return resp
    path = request.url.path
    has_v = "v=" in (request.url.query or "")
    # 版本化静态资源（根路径挂载：/style.css?v=xxx 等，带 ?v= 可长缓存 immutable）
    asset_name = path.lstrip("/")
    if asset_name in _VERSIONED_ASSETS and has_v:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/api/") or path == "/" or path.startswith("/data/") or path.startswith("/trade_sim") or path == "/og.png":
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


def range_dep(range: str = "1y"):
    """range 参数校验：非法值返回 400 而非静默回退。"""
    if range not in queries.VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 range 参数: {range}，可选 {', '.join(sorted(queries.VALID_RANGES))}",
        )
    return range


# ============ API ============

@app.get("/api/overview")
def overview():
    return queries.overview(get_conn(), load_config())


@app.get("/api/a-stock")
def a_stock(range: str = Depends(range_dep)):
    start, end = queries.range_for(range)
    return queries.a_stock(get_conn(), load_config(), start, end)


@app.get("/api/hk")
def hk(range: str = Depends(range_dep)):
    start, end = queries.range_for(range)
    return queries.hk(get_conn(), load_config(), start, end)


@app.get("/api/global")
def global_(range: str = Depends(range_dep)):
    start, end = queries.range_for(range)
    return queries.global_market(get_conn(), load_config(), start, end)


@app.get("/api/sentiment")
def sentiment(range: str = Depends(range_dep)):
    start, end = queries.range_for(range)
    conn = get_conn()
    # 注意：API 版 sentiment 含 futures（前端 sentiment tab 内嵌期货卡片，免单独 fetch）；
    # export.py 版 sentiment JSON 不含 futures（前端读 futures.json 独立加载）。
    result = queries.sentiment(conn, load_config(), start, end)
    result["futures"] = queries.futures_data(conn)
    conn.close()
    return result


@app.get("/api/industry")
def industry(range: str = Depends(range_dep)):
    start, end = queries.range_for(range)
    return queries.industry(get_conn(), load_config(), start, end)


@app.get("/api/futures")
def futures_data():
    """期货机构净多空持仓：日度净持仓序列 + 最新准确率。"""
    return queries.futures_data(get_conn())


@app.get("/api/ad_line")
def ad_line():
    """AD Line（腾落线）+ 涨跌家数比，最近 250 个交易日。"""
    return queries.ad_line(get_conn())


@app.get("/api/volume_ratio")
def volume_ratio():
    """成交量对比（放量/缩量标注），最近 250 个交易日。"""
    return queries.volume_ratio(get_conn())


@app.get("/api/new_high_low")
def new_high_low():
    """新高新低家数：8 个主要指数的 52周/20日 NH-NL 统计。"""
    return queries.new_high_low(get_conn())


@app.get("/api/ma_alignment")
def ma_alignment():
    """均线排列状态：8 个主要指数的 MA5/MA10/MA20/MA60 多头/空头/震荡统计。"""
    return queries.ma_alignment(get_conn())


@app.get("/api/position")
def position():
    """大盘位置感：8 个 A 股指数的 1年/3年/5年分位 + 标签。"""
    return queries.position()


@app.get("/api/summary")
def summary(date: str | None = None):
    """一句话市场总结：情绪+涨跌+家数+量能+热点板块。"""
    return queries.summary(date)


@app.get("/api/summary/history")
def summary_history(offset: int = 0, limit: int = 15):
    """历史一句话总结（时间倒序，实时回算当页）。"""
    return queries.summary_history(get_conn(), offset, limit)


@app.get("/api/signal_freq")
def signal_freq():
    """全局信号频率统计：汇总所有品种 buy/buy_aux/sell 的今年次数/总计/月均。"""
    return queries.signal_freq()


@app.get("/api/schedule_stats")
def schedule_stats():
    """计划任务执行统计：各 launchd 任务的预估耗时 + 最后执行时间。
    由 scripts/gen_schedule_stats.py 在部署时刷新写入 static-site/data/schedule_stats.json。
    动态版直接读该静态文件返回（数据本身与动态/静态无关，都是日志解析结果）。
    """
    p = Path(__file__).absolute().parent.parent / "static-site" / "data" / "schedule_stats.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/rotation")
def rotation():
    """板块轮动速度：SW 行业 + 同花顺概念板块领涨变化频率，最近 250 日。"""
    return queries.rotation(get_conn())


@app.get("/api/intraday_snapshot")
def intraday_snapshot():
    """盘中实时快照：9 指数实时行情 + 31 行业实时涨跌幅。"""
    return queries.intraday_snapshot()


@app.get("/api/index/{index_id}")
def index_detail(index_id: str, range: str = Depends(range_dep)):
    cfg = load_config()
    if index_id not in queries.valid_index_ids(cfg):
        raise HTTPException(status_code=404, detail=f"未知的指数代码: {index_id}")
    start, end = queries.range_for(range)
    return queries.index_detail(get_conn(), cfg, index_id, start, end)


@app.get("/api/etf-national-team")
def etf_national_team(range: str = Depends(range_dep)):
    """国家队宽基 ETF 资金动向：12 只宽基 ETF 近份额+成交额+信号。
    口径声明：本指标为代理推断，非真实国家队席位数据。基于 ETF 每日份额变动+成交额放量，
    结合季度机构持仓占比校准，推断疑似大资金进场/离场。无法精确区分汇金/证金/社保/险资/公募。
    range 参数：1m/3m/6m/1y/3y/5y/all，按日历日切片 daily（默认1y，避免全量裸传卡手机）。
    """
    return queries.etf_national_team(range)


@app.get("/api/etf-national-team/quarterly")
def etf_national_team_quarterly():
    """季度持有人结构（机构占比历史轨迹，半年报+年报）。"""
    return queries.etf_national_team_quarterly()


@app.get("/api/etf-national-team/holders")
def etf_national_team_holders():
    """v2 具名持有人：cninfo 年报/半年报 PDF 解析的前十大持有人（含汇金/证金识别）。
    仅深市5只ETF有cninfo orgId；沪市7只待补。含历史汇金/证金公开增持事件 seed。
    """
    return queries.etf_national_team_holders()


@app.get("/api/metrics")
def metrics_list():
    """供手动补录表单用的指标列表。"""
    return queries.metrics_list(load_config())


class ManualEntry(BaseModel):
    date: str
    metric_id: str
    value: float
    note: str = ""


def _validate_date(date: str) -> None:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="日期格式错误，要求 yyyyMMdd（如 20260703）")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的日期: {date}")


@app.get("/api/manual/check")
def manual_check(date: str, metric_id: str):
    """查某日期+指标是否已有数据，供前端覆盖确认。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT value, source FROM daily_metric WHERE date=? AND metric_id=?",
        (date, metric_id),
    ).fetchone()
    conn.close()
    if row:
        return {"exists": True, "value": row["value"], "source": row["source"]}
    return {"exists": False}


@app.post("/api/manual")
def manual(entry: ManualEntry):
    _validate_date(entry.date)
    cfg = load_config()
    if entry.metric_id not in queries.valid_metric_ids(cfg):
        raise HTTPException(status_code=400, detail=f"未知的指标 ID: {entry.metric_id}")
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO manual_entry (date, metric_id, value, note, created_at) VALUES (?,?,?,?,?)",
        (entry.date, entry.metric_id, entry.value, entry.note, now),
    )
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, source='manual', updated_at=excluded.updated_at",
        (entry.date, entry.metric_id, entry.value, "manual", now),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ============ 前端静态文件 ============
# 单版架构：?v= 由 bump_asset_version.py 注入到 static-site/index.html，
# 动态版直接返回该文件（不再动态注入版本号，与静态站完全一致）。
_INDEX_CACHE = {"sig": None, "html": None}


# ============ A12 订阅推送管理 API（2026-07-24 P2-新-K）============
# 订阅存储：config/subscriptions.json（含邮箱/chat_id 敏感，已 gitignore，模板见 .example）
# 推送逻辑：scripts/check_signals.py 检测信号后读本文件匹配标的，调 notify.send_to 推送
# 去重：data/subscriptions_notified.json（每订阅每日每信号只推一次，7 天清理）
import threading

_SUBS_PATH = WEB_DIR.parent / "config" / "subscriptions.json"
_SUBS_LOCK = threading.Lock()  # 读写锁，防并发写冲突


def _load_subscriptions_file() -> dict:
    """读 config/subscriptions.json。不存在/解析失败返回空结构。"""
    if not _SUBS_PATH.exists():
        return {"_help": "A12 订阅推送配置", "subscriptions": []}
    try:
        data = json.loads(_SUBS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("subscriptions"), list):
            return {"_help": "A12 订阅推送配置", "subscriptions": []}
        return data
    except Exception:
        return {"_help": "A12 订阅推送配置", "subscriptions": []}


def _save_subscriptions_file(data: dict) -> None:
    """原子写 config/subscriptions.json。"""
    _SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = _SUBS_PATH.parent / (_SUBS_PATH.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(_SUBS_PATH)


class SubscriptionIn(BaseModel):
    """订阅创建/更新请求体。id 为空=新建（自动生成），非空=更新。"""
    id: str = ""
    name: str = ""
    email: str = ""
    telegram_chat_id: str = ""
    targets: list[str] = []  # 订阅的 index_id 列表（如 sh/sz300/cyb）
    signals: list[str] = []  # 订阅的信号类型（空=全部；buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss）
    enabled: bool = True


_VALID_SIGNAL_TYPES = {"buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss"}


@app.get("/api/subscribe")
def subscribe_list():
    """列出所有订阅。返回 {subscriptions: [...]}。

    敏感字段 email/telegram_chat_id 做脱敏（隐藏中间），前端展示用；
    原始值仅后端推送时读文件使用（API 不返回原始敏感值）。
    """
    with _SUBS_LOCK:
        data = _load_subscriptions_file()
    subs = data.get("subscriptions", [])
    # 脱敏：邮箱保留首字符+域名，chat_id 保留末 4 位
    out = []
    for s in subs:
        out.append({
            "id": s.get("id", ""),
            "name": s.get("name", ""),
            "email_masked": _mask_email(s.get("email", "")),
            "telegram_chat_id_masked": _mask_chat_id(s.get("telegram_chat_id", "")),
            "has_email": bool(s.get("email")),
            "has_telegram": bool(s.get("telegram_chat_id")),
            "targets": s.get("targets", []),
            "signals": s.get("signals", []),
            "enabled": s.get("enabled", True),
            "created_at": s.get("created_at", ""),
        })
    return {"subscriptions": out}


@app.post("/api/subscribe")
def subscribe_create(sub: SubscriptionIn):
    """添加或更新订阅。id 为空=新建（自动生成 sub_<timestamp>），非空=更新现有。

    校验：targets 非空；email/telegram_chat_id 至少一个非空；
    signals（若非空）每一项在 _VALID_SIGNAL_TYPES 内。
    """
    if not sub.targets:
        raise HTTPException(status_code=400, detail="targets 不能为空（至少订阅一个标的）")
    if not sub.email and not sub.telegram_chat_id:
        raise HTTPException(status_code=400, detail="email 和 telegram_chat_id 至少填一个")
    for sig in sub.signals:
        if sig not in _VALID_SIGNAL_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的信号类型: {sig}，可选 {','.join(sorted(_VALID_SIGNAL_TYPES))}")
    with _SUBS_LOCK:
        data = _load_subscriptions_file()
        subs = data.get("subscriptions", [])
        now = datetime.now().isoformat(timespec="seconds")
        if sub.id:
            # 更新现有
            target_idx = None
            for i, s in enumerate(subs):
                if s.get("id") == sub.id:
                    target_idx = i
                    break
            if target_idx is None:
                raise HTTPException(status_code=404, detail=f"订阅 {sub.id} 不存在")
            subs[target_idx].update({
                "name": sub.name,
                "email": sub.email,
                "telegram_chat_id": sub.telegram_chat_id,
                "targets": sub.targets,
                "signals": sub.signals,
                "enabled": sub.enabled,
            })
            action = "updated"
            sub_id = sub.id
        else:
            # 新建
            sub_id = f"sub_{int(datetime.now().timestamp())}"
            subs.append({
                "id": sub_id,
                "name": sub.name or f"订阅-{len(subs) + 1}",
                "email": sub.email,
                "telegram_chat_id": sub.telegram_chat_id,
                "targets": sub.targets,
                "signals": sub.signals,
                "enabled": sub.enabled,
                "created_at": now,
            })
            action = "created"
        data["subscriptions"] = subs
        _save_subscriptions_file(data)
    return {"ok": True, "id": sub_id, "action": action}


@app.delete("/api/subscribe/{sub_id}")
def subscribe_delete(sub_id: str):
    """删除订阅。sub_id 为订阅唯一标识。"""
    with _SUBS_LOCK:
        data = _load_subscriptions_file()
        subs = data.get("subscriptions", [])
        new_subs = [s for s in subs if s.get("id") != sub_id]
        if len(new_subs) == len(subs):
            raise HTTPException(status_code=404, detail=f"订阅 {sub_id} 不存在")
        data["subscriptions"] = new_subs
        _save_subscriptions_file(data)
    return {"ok": True, "deleted": sub_id}


def _mask_email(email: str) -> str:
    """邮箱脱敏：保留首字符 + 域名，中间用 *** 替代。"""
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


def _mask_chat_id(chat_id: str) -> str:
    """Telegram chat_id 脱敏：保留末 4 位，前面用 *** 替代。"""
    if not chat_id:
        return ""
    if len(chat_id) <= 4:
        return "***" + chat_id
    return "***" + chat_id[-4:]


# ============ C7 P4-β 交互式自定义分析 (docs §9) ============
@app.get("/api/alert/analyze")
def alert_analyze(target: str, type: str | None = None, limit: int = 20):
    """交互式自定义分析: 输入标的 -> 候选 + 预警分 + 原因 4 部分 + 合规底栏。

    Args:
        target: 用户输入 (指数代码/中文名/ETF代码/ETF名/行业名)
        type:   'index' / 'etf' (None=自动判定)
        limit:  候选列表最大条数

    Returns:
        {query, candidates: [...], result: {target_id, target_type, alert, reason} or None}
        - 当唯一精确匹配(score=100)时直接返回 result
        - 多候选时 candidates 非空, result 可能为 None(让前端让用户选定)
        - 指定 type 且 target 能精确匹配某候选 code 时直接分析
    """
    from .alert_match import match_candidates
    from .alert_reason import build_reason
    from .alert_score import compute_alert_for_target

    q = (target or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="target 参数不能为空")
    cands = match_candidates(q, limit=limit)
    if not cands:
        return {"query": q, "candidates": [], "result": None,
                "hint": "未找到匹配标的,请尝试行业名/宽基名/指数代码/ETF代码"}

    # 判定是否直接分析:
    # 1) 用户指定了 type 且某候选 code 精确等于 target(大小写不敏感)
    # 2) 唯一 score=100 的候选
    chosen = None
    if type:
        for c in cands:
            if c["type"] == type and c["code"].lower() == q.lower():
                chosen = c
                break
    if not chosen:
        perfect = [c for c in cands if c["score"] == 100]
        if len(perfect) == 1:
            chosen = perfect[0]

    result = None
    if chosen:
        alert = compute_alert_for_target(chosen["code"], chosen["type"])
        reason = build_reason(chosen["code"], chosen["type"], alert_result=alert)
        result = {
            "target_id": chosen["code"],
            "target_type": chosen["type"],
            "target_name": chosen["name"],
            "alert": alert,
            "reason": reason,
        }
    return {"query": q, "candidates": cands, "result": result}


def _render_index():
    """读 static-site/index.html 返回（?v= 已由 bump_asset_version.py 注入）；mtime 变化才重读。"""
    idx = WEB_DIR / "index.html"
    sig = idx.stat().st_mtime
    if _INDEX_CACHE["sig"] != sig:
        _INDEX_CACHE["sig"] = sig
        _INDEX_CACHE["html"] = idx.read_text("utf-8")
    return _INDEX_CACHE["html"]


@app.get("/")
def root():
    return HTMLResponse(_render_index(), headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/trade_sim.html")
def trade_sim():
    return FileResponse(WEB_DIR / "trade_sim.html")


@app.get("/og.png")
def og_image():
    return FileResponse(WEB_DIR / "og.png", media_type="image/png")


app.mount("/", StaticFiles(directory=WEB_DIR, html=True, follow_symlink=True), name="root")
