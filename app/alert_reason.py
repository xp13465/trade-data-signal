"""交互式自定义分析: 原因 4 部分生成 (docs/alert-design.md §8 + §9.4)。

4 部分:
1. 命中维度明细 (dims hit=True 按 contribution 降序)
2. 数据阈值 (各维度当前值 + 阈值 + 百分位 + 命中状态)
3. 历史类比 (Jaccard + 余弦双轨相似度, Top3 相似日期 + 后续走势)
4. 人话解读 (模板拼接, 中性白名单用词 + 禁用词过滤)

合规底栏 (§9.5):
- 固定风险提示 + 历史类比免责
- 中性白名单: 分析/参考/风险提示/关注/留意/谨慎/防范/留意追高风险/关注超跌反弹
- 禁用词: 买入/卖出/加仓/减仓/清仓/满仓/抄底/逃顶 -> 替换为中性表述
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .alert_score import (
    HIGH_WEIGHTS,
    LOW_WEIGHTS,
    _compute_rsi,
    _load_target_close_amount,
    _weighted_score,
    compute_target_dims,
    MIN_DIMS_TARGET,
    _WINDOW,
)

# 维度中文名 (与 export_alert.py 对齐)
HIGH_DIM_NAMES = {
    "H1": "情绪过热", "H2": "量价背离", "H3": "卖点密集", "H4": "位置偏高",
    "H5": "动量衰退", "H6": "均线转弱", "H7": "汪汪队离场", "H8": "全球走弱",
}
LOW_DIM_NAMES = {
    "L1": "情绪冰点", "L2": "买点密集", "L3": "位置偏低", "L4": "汪汪队入场",
    "L5": "量能异动", "L6": "新低极端", "L7": "波指飙升", "L8": "价值显现",
}

# 各维度的数据阈值与含义描述(§9.4 数据阈值展示)
DIM_THRESHOLDS = {
    "H1": {"threshold": 60, "unit": "分", "desc": "情绪过热线(RSI或综合情绪分百分位)"},
    "H2": {"threshold": 60, "unit": "分", "desc": "量价背离(缩量上涨+高位)"},
    "H3": {"threshold": 60, "unit": "分", "desc": "卖点密集(近10日sell信号)"},
    "H4": {"threshold": 60, "unit": "%", "desc": "1年位置分位"},
    "H5": {"threshold": 60, "unit": "分", "desc": "动量衰退(新高回落)"},
    "H6": {"threshold": 60, "unit": "分", "desc": "均线转弱(空头排列)"},
    "H7": {"threshold": 60, "unit": "分", "desc": "汪汪队离场(近30日share_outflow)"},
    "H8": {"threshold": 60, "unit": "分", "desc": "全球走弱(不适用单标的)"},
    "L1": {"threshold": 60, "unit": "分", "desc": "情绪冰点(100-RSI百分位)"},
    "L2": {"threshold": 60, "unit": "分", "desc": "买点密集(近10日buy信号)"},
    "L3": {"threshold": 60, "unit": "%", "desc": "1年位置低位(100-分位)"},
    "L4": {"threshold": 60, "unit": "分", "desc": "汪汪队入场(近30日share_surge)"},
    "L5": {"threshold": 60, "unit": "分", "desc": "量能异动(地量分高)"},
    "L6": {"threshold": 60, "unit": "分", "desc": "新低极端(52周新低百分位)"},
    "L7": {"threshold": 60, "unit": "分", "desc": "波指飙升(不适用单标的)"},
    "L8": {"threshold": 60, "unit": "分", "desc": "价值显现(不适用单标的)"},
}

HIT_THRESHOLD = 60.0  # §8.2① 强度>=60 算命中
HISTORY_WINDOW_DAYS = 252 * 3  # 近3年作类比窗口
HISTORY_TOP_N = 3  # Top3 相似日期
FORWARD_WINDOWS = [5, 10, 20]  # 后续 N 日收益

# §9.5 合规
COMPLIANCE_FOOTER = (
    "⚠️ 本分析基于历史数据统计,仅供学习参考,不构成投资建议或交易指令,"
    "市场有风险,决策需谨慎。历史类比仅作统计参考,不代表未来必然走势。"
)
NO_DATA_HINT = (
    "该标的暂无足够数据进行有效分析,建议选择数据更全的宽基/行业指数。"
)

# 禁用词 -> 替换词映射 (§9.5)
_FORBIDDEN_REPLACE = {
    "买入": "关注低位机会", "卖出": "留意高位风险",
    "加仓": "逢低关注", "减仓": "逢高谨慎",
    "清仓": "防范风险", "满仓": "控制仓位",
    "抄底": "关注超跌反弹", "逃顶": "留意追高风险",
}


def _filter_forbidden(text: str) -> str:
    """禁用词替换为中性表述(§9.5 白名单)。"""
    for bad, good in _FORBIDDEN_REPLACE.items():
        text = text.replace(bad, good)
    return text


# ---------------------------------------------------------------------------
# 第1部分: 命中维度明细 (按 contribution 降序)
# ---------------------------------------------------------------------------
def build_dim_hits(dims_row: dict, weights: dict, names: dict, is_high: bool) -> list[dict]:
    """命中维度详情列表(hit=True 按 contribution 降序)。

    Args:
        dims_row: {H1: v, H2: v, ...} 已 round 过的当前日维度值
        weights: HIGH_WEIGHTS / LOW_WEIGHTS
        names: HIGH_DIM_NAMES / LOW_DIM_NAMES
        is_high: True=高位预警, False=低位预警
    """
    out = []
    for k in weights:
        v = dims_row.get(k)
        if v is None:
            continue
        w = weights[k]
        out.append({
            "k": k,
            "name": names[k],
            "score": round(float(v), 2),
            "weight": w,
            "contribution": round(float(v) * w, 2),
            "hit": bool(float(v) >= HIT_THRESHOLD),
            "direction": "high" if is_high else "low",
        })
    out.sort(key=lambda x: x["contribution"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# 第2部分: 数据阈值 (当前值 + 阈值 + 百分位 + 命中状态)
# ---------------------------------------------------------------------------
def build_data_thresholds(dims_row: dict, weights: dict, names: dict) -> list[dict]:
    """各维度当前值 + 阈值 + 百分位 + 命中状态。"""
    out = []
    for k in weights:
        v = dims_row.get(k)
        th = DIM_THRESHOLDS.get(k, {})
        if v is None:
            out.append({
                "k": k, "name": names[k], "value": None,
                "threshold": th.get("threshold"), "unit": th.get("unit"),
                "desc": th.get("desc", ""), "hit": False, "status": "无数据",
            })
            continue
        v_f = float(v)
        th_v = th.get("threshold", 60)
        hit = v_f >= th_v
        out.append({
            "k": k, "name": names[k], "value": round(v_f, 2),
            "threshold": th_v, "unit": th.get("unit"),
            "desc": th.get("desc", ""), "hit": hit,
            "status": "命中" if hit else ("接近" if v_f >= th_v * 0.85 else "未命中"),
        })
    return out


# ---------------------------------------------------------------------------
# 第3部分: 历史类比 (Jaccard + 余弦双轨相似度, Top3 + 后续走势)
# ---------------------------------------------------------------------------
def _hit_set(dims_row: dict) -> set[str]:
    """命中维度集合(强度>=60)。"""
    return {k for k, v in dims_row.items() if v is not None and float(v) >= HIT_THRESHOLD}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _forward_returns(close: pd.Series, date_idx: int, windows: list[int]) -> dict:
    """date_idx 后 N 交易日收益(%)。date_idx 是 close.index 的位置。"""
    out = {}
    n = len(close)
    for w in windows:
        end_idx = date_idx + w
        if end_idx >= n:
            out[f"ret_{w}d"] = None
            continue
        start_v = close.iloc[date_idx]
        end_v = close.iloc[end_idx]
        if start_v <= 0:
            out[f"ret_{w}d"] = None
            continue
        out[f"ret_{w}d"] = round(float((end_v / start_v - 1) * 100), 2)
    return out


def build_history_analogy(target_id: str, target_type: str, cur_date: str,
                          cur_dims_row: dict, top_n: int = HISTORY_TOP_N) -> dict:
    """历史类比: 找 Top3 相似日期 + 当时后续走势。

    Args:
        target_id: 标的 id
        target_type: 'index' / 'etf'
        cur_date: 当前日 'YYYYMMDD'
        cur_dims_row: 当日 dims dict
        top_n: 返回 Top N 相似日

    Returns:
        {cur_date, top_n, matches: [{date, jaccard, cosine, combined,
                                     hit_overlap, forward_returns: {ret_5d, ret_10d, ret_20d}}],
         window_days, stats: {avg_ret_5d, avg_ret_10d, avg_ret_20d, n_up, n_down}}
    """
    dims_df = compute_target_dims(target_id, target_type)
    if dims_df.empty:
        return {"cur_date": cur_date, "top_n": 0, "matches": [],
                "window_days": 0, "stats": {}}
    close, _ = _load_target_close_amount(target_id, target_type)
    if close.empty:
        return {"cur_date": cur_date, "top_n": 0, "matches": [],
                "window_days": 0, "stats": {}}

    # 近 3 年窗口
    cur_pos = dims_df.index.get_loc(cur_date) if cur_date in dims_df.index else len(dims_df) - 1
    start_pos = max(0, cur_pos - HISTORY_WINDOW_DAYS)
    hist_df = dims_df.iloc[start_pos:cur_pos]  # 排除当日
    if hist_df.empty:
        return {"cur_date": cur_date, "top_n": 0, "matches": [],
                "window_days": 0, "stats": {}}

    cur_hit = _hit_set(cur_dims_row)
    cur_keys = [k for k in cur_dims_row if cur_dims_row[k] is not None]
    if not cur_keys:
        return {"cur_date": cur_date, "top_n": 0, "matches": [],
                "window_days": int(len(hist_df)), "stats": {}}
    cur_vec = np.array([float(cur_dims_row[k]) for k in cur_keys], dtype=float)

    # close 也要对齐到 dims_df.index
    close_aligned = close.reindex(dims_df.index)

    matches = []
    for date, row in hist_df.iterrows():
        # 该历史日的特征向量(与 cur_keys 对齐, 若该日任一对应维度缺则跳过)
        vals = []
        ok = True
        for k in cur_keys:
            v = row.get(k)
            if v is None or pd.isna(v):
                ok = False
                break
            vals.append(float(v))
        if not ok:
            continue
        hist_vec = np.array(vals, dtype=float)
        hist_hit = {k for k in cur_keys if float(cur_dims_row[k]) is not None
                    and float(row[k]) >= HIT_THRESHOLD}
        jac = _jaccard(cur_hit, hist_hit)
        cos = _cosine(cur_vec, hist_vec)
        combined = 0.5 * jac + 0.5 * cos
        matches.append({
            "date": str(date),
            "jaccard": round(jac, 4),
            "cosine": round(cos, 4),
            "combined": round(combined, 4),
            "hit_overlap": sorted(list(cur_hit & hist_hit)),
        })

    # 按 combined 降序取 Top N
    matches.sort(key=lambda x: x["combined"], reverse=True)
    top = matches[:top_n]

    # 算 Top N 的后续收益
    rets_5d, rets_10d, rets_20d = [], [], []
    for m in top:
        if m["date"] not in close_aligned.index:
            continue
        pos = close_aligned.index.get_loc(m["date"])
        fwd = _forward_returns(close_aligned, pos, FORWARD_WINDOWS)
        m["forward_returns"] = fwd
        if fwd.get("ret_5d") is not None:
            rets_5d.append(fwd["ret_5d"])
        if fwd.get("ret_10d") is not None:
            rets_10d.append(fwd["ret_10d"])
        if fwd.get("ret_20d") is not None:
            rets_20d.append(fwd["ret_20d"])

    stats = {
        "avg_ret_5d": round(float(np.mean(rets_5d)), 2) if rets_5d else None,
        "avg_ret_10d": round(float(np.mean(rets_10d)), 2) if rets_10d else None,
        "avg_ret_20d": round(float(np.mean(rets_20d)), 2) if rets_20d else None,
        "n_up_10d": int(sum(1 for r in rets_10d if r > 0)),
        "n_down_10d": int(sum(1 for r in rets_10d if r < 0)),
        "n_total_10d": len(rets_10d),
    }
    return {
        "cur_date": cur_date,
        "top_n": len(top),
        "matches": top,
        "window_days": int(len(hist_df)),
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# 第4部分: 人话解读 (模板拼接, 中性白名单)
# ---------------------------------------------------------------------------
_HIGH_TEMPLATES = {
    "高危": "多维度过热共振,风险显著,留意追高风险,防范阶段性回调",
    "警示": "过热信号密集,警惕阶段性顶部,逢高谨慎,留意风险",
    "关注": "市场偏热,部分指标进入高位区,留意风险,谨慎追高",
    "中性": "高位风险指标处于中性区间,暂无明显过热信号",
    "数据不足": "数据不足,暂无法判断高位风险",
}
_LOW_TEMPLATES = {
    "机遇": "多维度冰点共振,机会显著,关注超跌反弹,留意布局机会",
    "机会": "冰点信号密集,关注阶段性机会,留意企稳信号",
    "关注": "市场偏冷,部分指标进入低位区,关注企稳信号",
    "中性": "低位机会指标处于中性区间,暂无明显冰点信号",
    "数据不足": "数据不足,暂无法判断低位机会",
}


def build_human_text(level: str, hit_dims: list[dict], is_high: bool,
                     analogy: dict | None = None) -> str:
    """人话解读: 等级文案 + 命中维度前2 + 历史类比摘要。

    Args:
        level: 等级文本
        hit_dims: build_dim_hits 返回的维度列表
        is_high: True=高位, False=低位
        analogy: build_history_analogy 返回的 dict (可选)
    """
    base = _HIGH_TEMPLATES.get(level, "") if is_high else _LOW_TEMPLATES.get(level, "")
    if level == "数据不足":
        return _filter_forbidden(base)
    if level == "中性":
        # 中性档(总分<=60): 若有单维度命中(>=60), 拼接说明
        # 避免用户困惑"显示中性但维度表有命中"(单维度强但加权总分被弱维度拉低)
        hit_labels = [f"{d['k']} {d['name']}" for d in hit_dims if d["hit"]][:2]
        if hit_labels:
            base = (f"{base},但 {'/'.join(hit_labels)} 有命中,"
                    f"整体加权后未达关注线")
        return _filter_forbidden(base)
    parts = [base]
    # 命中维度前2
    hit_names = [d["name"] for d in hit_dims if d["hit"]][:2]
    if hit_names:
        parts.append(f"主要风险来自{'+'.join(hit_names)}")
    # 历史类比摘要
    if analogy and analogy.get("matches"):
        stats = analogy.get("stats", {})
        avg10 = stats.get("avg_ret_10d")
        n_up = stats.get("n_up_10d", 0)
        n_down = stats.get("n_down_10d", 0)
        if avg10 is not None:
            direction = "上涨" if avg10 > 0 else "下跌"
            parts.append(
                f"历史{len(analogy['matches'])}次相似特征后10日平均{direction}{abs(avg10):.2f}%"
                f"(涨{n_up}次/跌{n_down}次),历史统计参考不代表未来必然走势"
            )
    text = ";".join(parts)
    return _filter_forbidden(text)


# ---------------------------------------------------------------------------
# 主入口: 组装 4 部分
# ---------------------------------------------------------------------------
def build_reason(target_id: str, target_type: str, alert_result: dict | None = None,
                 include_analogy: bool = True) -> dict:
    """组装原因 4 部分 + 合规底栏。

    Args:
        target_id: 标的 id
        target_type: 'index' / 'etf'
        alert_result: compute_alert_for_target 返回的 dict (None 则现算)
        include_analogy: True=含历史类比(慢,需读 DB 全历史); False=跳过类比(快速模式)

    Returns:
        {dim_hits: {high, low}, data_thresholds: {high, low},
         history_analogy: {high, low} or None,
         human_text: {high, low},
         compliance_footer, no_data_hint}
    """
    from .alert_score import compute_alert_for_target
    if alert_result is None:
        alert_result = compute_alert_for_target(target_id, target_type)
    dims = alert_result.get("dims", {})
    cur_date = alert_result.get("date")
    high_level = alert_result.get("high_level", "数据不足")
    low_level = alert_result.get("low_level", "数据不足")

    # 数据不足检查
    avail_h = alert_result.get("adapt", {}).get("available_high", 0)
    avail_l = alert_result.get("adapt", {}).get("available_low", 0)
    no_data = avail_h < MIN_DIMS_TARGET and avail_l < MIN_DIMS_TARGET

    # 1. 命中维度明细
    h_hits = build_dim_hits(dims, HIGH_WEIGHTS, HIGH_DIM_NAMES, is_high=True)
    l_hits = build_dim_hits(dims, LOW_WEIGHTS, LOW_DIM_NAMES, is_high=False)

    # 2. 数据阈值
    h_th = build_data_thresholds(dims, HIGH_WEIGHTS, HIGH_DIM_NAMES)
    l_th = build_data_thresholds(dims, LOW_WEIGHTS, LOW_DIM_NAMES)

    # 3. 历史类比
    analogy = None
    if include_analogy and cur_date and not no_data:
        try:
            h_analogy = build_history_analogy(target_id, target_type, cur_date, dims)
            l_analogy = h_analogy  # 同一标的同一日, 类比共用
            analogy = {"high": h_analogy, "low": l_analogy}
        except Exception as e:  # 历史类比失败不阻塞主流程
            analogy = {"high": None, "low": None, "error": str(e)}

    # 4. 人话解读
    h_text = build_human_text(high_level, h_hits, is_high=True,
                              analogy=analogy.get("high") if analogy else None)
    l_text = build_human_text(low_level, l_hits, is_high=False,
                              analogy=analogy.get("low") if analogy else None)

    return {
        "dim_hits": {"high": h_hits, "low": l_hits},
        "data_thresholds": {"high": h_th, "low": l_th},
        "history_analogy": analogy,
        "human_text": {"high": h_text, "low": l_text},
        "compliance_footer": COMPLIANCE_FOOTER,
        "no_data_hint": NO_DATA_HINT if no_data else None,
    }


if __name__ == "__main__":
    import sys
    import json
    tid = sys.argv[1] if len(sys.argv) > 1 else "hs300"
    ttype = sys.argv[2] if len(sys.argv) > 2 else "index"
    r = build_reason(tid, ttype)
    print(json.dumps(r, ensure_ascii=False, indent=2))
