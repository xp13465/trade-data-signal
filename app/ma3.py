"""MA3 连续 3 日降亏判定(单一事实源, 2026-11-24 从 app/queries.py 抽出)。

抽取动机: 首页信号打标(app/queries.py)与信号凯利回测(scripts/signal_kelly_backtest.py)
必须用**同一份判定逻辑与同一份数据源解析**, 否则两条链路静默漂移(§5.4⑦ 复现脚本同构
对账铁律)。本模块只放纯函数 + 数据读取辅助, 不依赖数据库连接; DB 侧收盘序列由调用方
经 `load_index_close_map` 回调注入。

规则变体名: 「ETF consec w3 p3(post)」—— 取信号自身 top1 ETF 的收盘序列, MA3=最近 3 个
交易日简单均线; 连续 3 个交易日收盘都低于各自 MA3 → 该买入信号标「MA3连3日下·建议回避」。
首页前端开关默认关(tds_home_ma3), 纯展示层; 回测侧是 lab 独立 post 过滤开关(默认关,
tds_kelly_ma3_post), 先选 K 再剔除、不补位。

防前视(硬约束, §5.1⑥): 只用信号日 T 及之前的收盘; T 日收盘未入库/历史不足 → status="na"
保守放行(不误灰/不误剔除)。

数据源(必须与回测同源): static-site/data/etf/{code}-all.json 的「前复权 close」(ohlc 第 5 列),
不是 etf_daily.accum_nav —— 两者在 QDII/跨境 ETF 上因复权因子/汇率/分红处理不同会岔开,
2026-11-21 实测 8/271 条信号判定翻转。self ETF(指数本体即 ETF, 如 cgb_10y_etf=511260)
无 etf/{code}-all.json, 走 index_daily.close。

回测口径与依据: /tmp/ma5-extension-research-20261121.md §5.1(落档见
docs/kelly/analysis/ 同批次报告); 首页公示见 static-site/purpose-notes.js home.ma3filter。
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 只给买入 4 类打标(卖类/波段不判降亏; 与前端 _BUY_UNI_SIGS/_CONS_BUY 常量集合逐键相等,
# 机检见 scripts/tests/test_ma3_filter_20261121.py::test_buy_signal_set_matches_frontend_constants)
_MA3_BUY_SIGNALS = {"buy", "buy_aux", "buy_special", "buy_backup"}
# 进程内 ETF 前复权收盘缓存: code -> (mtime, {date: close}); mtime 变化(每日导出重写)自动重载。
# 说明: 键只用 code, 同一进程假定只读一个 ETF 目录(生产/测试均是); 若同进程要读多个目录,
# 调用方应传独立的 cache 字典(回测侧即用独立 _MA3_BT_ETF_CACHE, 与首页侧互不影响)。
_MA3_ETF_CLOSE_CACHE: dict = {}


def ma3_etf_data_dir(static_data_dir):
    """静态站 ETF 历史文件目录(static-site/data/etf)。

    static_data_dir 由调用方传入(按其模块 __file__ 推导, 生产布局差异由调用方负责)。
    解析顺序: 环境变量 MA3_ETF_DATA_DIR(测试/特殊部署显式指定) → static_data_dir/etf。
    ⚠ 调用方禁用 Path.resolve() 推导 static_data_dir: trade-data/app 是到 trade/app 的
    symlink, resolve() 会跳回代码仓 trade 读那里的旧导出产物(生产静默读旧数据/全 na),
    同 scripts/export_etf_hist.py 顶部警告。
    返回约定: 环境变量分支显式指定但目录不存在 → 返回 None(判定转 na 保守放行);
    默认分支(static_data_dir/etf)不在此处探测存在性, 目录/单文件缺失由下游
    ma3_etf_close_map 返回空映射(同样转 na 保守放行)兜住。
    """
    _env = os.environ.get("MA3_ETF_DATA_DIR")
    if _env:
        return _env if os.path.isdir(_env) else None
    return str(Path(static_data_dir) / "etf")


def ma3_etf_close_map(code, data_dir, cache=None):
    """读 etf/{code}-all.json 的前复权收盘序列 -> {YYYYMMDD: close}。

    - 只读实际被判定到的 code(懒加载, 不全量扫目录); 文件缺失/损坏 -> {} (=数据缺失, 保守放行)。
    - 按文件 mtime 缓存, 每日重导出后自动失效重载; 不改任何文件。
    - cache: 调用方进程内缓存 dict(code -> (mtime, map)), 原地读写; None 则不缓存。
    """
    code = str(code or "")
    if not code or not data_dir:
        return {}
    _p = Path(data_dir) / ("%s-all.json" % code)
    try:
        _mtime = _p.stat().st_mtime
    except OSError:
        return {}
    if cache is not None:
        _hit = cache.get(code)
        if _hit and _hit[0] == _mtime:
            return _hit[1]
    _m: dict = {}
    try:
        with open(_p, "r", encoding="utf-8") as _f:
            _d = json.load(_f)
        for _r in (_d.get("ohlc") or []):
            if not _r or len(_r) < 5:
                continue
            _c = _r[4]
            if isinstance(_c, (int, float)):
                _m[str(_r[0])] = float(_c)
    except Exception as _e:  # 文件损坏/权限 -> 数据缺失(保守放行), 不阻断调用方
        logger.warning("MA3 ETF 历史读取失败 code=%s: %s", code, _e)
        _m = {}
    if cache is not None:
        cache[code] = (_mtime, _m)
    return _m


def ma3_pick_top_etf(etfs):
    """与前端 app.js _topEtfByScore 同源取 top1: 冻结权威(_bk_top, _bk_ts 覆盖分数)优先,
    否则 track_score 降序、similarity 降序取第一。判定 ETF 必须=页面信号灯/回测成交同一只。"""
    if not etfs:
        return None
    for _e in etfs:
        if isinstance(_e, dict) and _e.get("_bk_top") is True:
            if isinstance(_e.get("_bk_ts"), (int, float)):
                _fz = dict(_e)
                _fz["track_score"] = _e["_bk_ts"]
                return _fz
            return _e

    def _key(_e):
        _ts = _e.get("track_score")
        _sim = _e.get("similarity")
        return (_ts if isinstance(_ts, (int, float)) else -1.0,
                _sim if isinstance(_sim, (int, float)) else -1.0)

    _cands = [_e for _e in etfs if isinstance(_e, dict)]
    if not _cands:
        return None
    return sorted(_cands, key=_key, reverse=True)[0]


def ma3_consec_below(closes_by_date, sig_date, days=3):
    """MA3 连续 `days` 日收盘 < MA3 判定; 返回 (hit, detail)。

    - 防前视: 只取 date <= sig_date 的收盘(字符串 YYYYMMDD 可直接比较), 未来数据不参与。
    - 序列最后一日必须 == sig_date(T 日收盘出标志, 次日生效语义); 否则数据未到 → 不可判。
    - 至少需要 days+2 个收盘(最后 days 天各自 MA3 需再往前 2 天)。
    - 数据不足/缺失 → hit=None + status="na"(调用方保守放行, 不误灰/不误剔除)。
    """
    if not closes_by_date or not sig_date:
        return None, {"status": "na", "reason": "no_data"}
    _dates = sorted(
        _d for _d in closes_by_date
        if isinstance(_d, str) and _d <= sig_date and isinstance(closes_by_date[_d], (int, float))
    )
    if not _dates or _dates[-1] != sig_date:
        # T 日收盘还没进库(盘中/数据滞后/已退市) → 不可判, 保守放行
        return None, {"status": "na", "reason": "no_sig_date_close"}
    if len(_dates) < days + 2:
        return None, {"status": "na", "reason": "short_history"}
    _closes = [float(closes_by_date[_d]) for _d in _dates]
    _hit = True
    _ma3_last = None
    for _i in range(len(_closes) - days, len(_closes)):
        _ma3 = (_closes[_i - 2] + _closes[_i - 1] + _closes[_i]) / 3.0
        if not (_closes[_i] < _ma3):
            _hit = False
        _ma3_last = _ma3
    return _hit, {
        "status": "ok",
        "ma3": round(_ma3_last, 4),
        "close": round(_closes[-1], 4),
        "days": days,
    }


def ma3_tag_etf(etf_code, match_method, sig_date, index_id, load_index_close_map, load_etf_close_map):
    """对「已确定的一只 ETF」打 MA3 标(回测侧入口: 打标 ETF = 该笔交易成交 ETF)。

    - 非 self ETF: load_etf_close_map(code) 读 etf/{code}-all.json 前复权 close。
    - self ETF: load_index_close_map(index_id) 读 index_daily.close(该类无 etf 历史文件)。
    - 无代码 → status="na" reason="no_etf"。返回 dict(hit/status/reason/etf/ma3/close)。
    """
    if not etf_code:
        return {"hit": None, "status": "na", "reason": "no_etf", "etf": None}
    _code = str(etf_code)
    if match_method == "self":
        _cm = load_index_close_map(index_id) if load_index_close_map else {}
    else:
        _cm = load_etf_close_map(_code) if load_etf_close_map else {}
    _hit, _detail = ma3_consec_below(_cm, sig_date)
    return {
        "hit": (bool(_hit) if _hit is not None else None),
        "status": _detail.get("status"),
        "reason": _detail.get("reason"),
        "etf": _code,
        "ma3": _detail.get("ma3"),
        "close": _detail.get("close"),
    }


def ma3_tag_sig(sig, load_index_close_map, load_etf_close_map):
    """单条信号打标(首页侧入口): 返回要写入信号 dict 的 _ma3 字段(不改入参, 便于单测)。

    - top1 ETF 选取与前端 _topEtfByScore 同源(ma3_pick_top_etf)。
    - 其余与 ma3_tag_etf 相同(非 self 读 etf 文件 / self 读 index 收盘)。
    - 无 ETF/无代码 → status="na" reason="no_etf"(前端保守放行)。
    """
    _top = ma3_pick_top_etf((sig or {}).get("etfs") or [])
    if not _top or not _top.get("code"):
        return {"hit": None, "status": "na", "reason": "no_etf", "etf": None}
    return ma3_tag_etf(_top.get("code"), _top.get("match_method"), (sig or {}).get("date"),
                       (sig or {}).get("index_id"), load_index_close_map, load_etf_close_map)
