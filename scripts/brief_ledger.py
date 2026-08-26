#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brief_ledger.py - AI 预测反思重构 Phase1:融合底座「每日对账底稿」brief_ledger.json。

调研方案: docs/ai-predict/ai-predict-reflection-quality-rebuild-20260826.md §四(2026-08-26 定稿)。
把影子骨架(brief_shadow.json 只记方向锚 7 字段)升格为每日一行完整对账底稿:
预测侧(pred_side)+因子侧(factor_states,含未注入面快照)+引用审计(cite_audit/missed_faces)
+实际侧(actual_side/hit,次日起回填)。旧 reflections「错账罗列」通道 Phase2 才替换,
本 Phase 纯数据层新增:不动线上预测输出/deepseek prompt/前端/shadow md 渲染链。

双写过渡(Phase1):record_shadow 影子记录保留不停用,Phase2 才并档停写;
本文件只新增旁路落盘,失败不阻塞主链(与 shadow 同模式)。

每日一行 JSON 数组(data/,gitignored 区,不进 git),幂等:同 date 重跑覆盖当日行:
  {
    "schema_version": 1,
    "date": "20260826",
    "pred_side": {version/direction_call/range/index_ranges/sector_ranges/
                  confidence_reason/risk_items/highlights/text{review,trend,watch,risk}},
    "pred_confidence": int|null,
    "factor_states": {
      "anchor": {turns[]/ma_bull/rate_down_channel/us10y/gold/nq_chg/nq_open_low},
                 # 与 record_shadow/_compute_direction_anchor 同源同因子,绝不再造口径
      "shadow_lean"/"shadow_basis"/"strength",     # 影子合成结果(与 brief_shadow.json 同值)
      "risk_items": [...],                          # 预测 risk_items 全量(weight_suppressed 判定素材)
      "extra_faces": {                              # 未注入面当日快照(漏数据归因素材,成本≈0):
        "nhnl_20d"/"nhnl_52w",                      #   a_nh/a_nl 新高新低(daily_metric)
        "board_concept_top",                        #   board_daily 概念板块 pct+net_inflow
        "cov_premium_median", "a_div_yield",        #   可转债溢价中位数 / 股息率
        "amount_forecast"(+turnover 附带),          #   预估成交额
        "sentiment_pctile": {score_id: {value,pctile,n}}   # 情绪分自身历史百分位(expanding≤date 防前视 §5.1⑥)
      },
      "extra_faces_note": {...|null}                # 取不到的原因(诚实标注,不伪造)
    },
    "cite_audit": {"referenced_faces": [...], "audit_method": "token_v1"},
                    # Phase1 机械层=面级特征 token 锚定比对(粗审计观察期);
                    # Phase2 升级数值级锚定+deepseek 归因(audit_method 随之升版)
    "missed_faces": [{"face": "...", "value": "..."}],
                    # 在库但未进 cite_audit.referenced_faces 的面清单(机械可算);
                    # injected 面 value="injected_but_uncited"(注入了却没引用也是重要审计信号)
    "actual_side": null|{"next_date","actual_sh_pct","actual_direction"},
    "hit": null|{"direction","direction_call_hit","range_hit","middle_hits","sector_hits"},
                   # 回填口径:history.meta.hit(backfill_hits 三层命中)搬运优先,保证与前端
                   # 展示位同源一致(§22);history 断档时 sh_map 兜底只判方向层(R1 断档防护:
                   # 下一交易日 pct 未入库不硬判,留待下次滚动清账)
  }

CLI(幂等可重复跑):
  python scripts/brief_ledger.py                        # reconcile 回填全部可回填行(默认动作)
  python scripts/brief_ledger.py --date 20260825        # 只回填指定行
  python scripts/brief_ledger.py --migrate-shadow       # 存量 brief_shadow.json 并入 ledger(一次性)
  python scripts/brief_ledger.py --check                # 软机检(最新行存在性+关键字段非空;不挂 deploy 硬链)

调度挂载:scripts/run_daily_brief.sh 尾部对账点(gen 完成后,17:50 update_all 数据已入库,
T-1 及更早行可回填;每日滚动清账不留断档)。写入挂载:gen_daily_brief.py 主流程尾部
write_outputs 之后(brief/meta 此时已定,AI 降级 rule/minimal 版也照记因子状态不断档)。

复现(自验):
  REPO=/tmp/<隔离目录> python scripts/gen_daily_brief.py --date <D> --mock --no-upload --no-tts \
    --notify-dry-run && cat /tmp/<隔离目录>/data/brief_ledger.json
  REPO=/tmp/<隔离目录> python scripts/brief_ledger.py --reconcile(连跑两次行数不变=幂等)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_repo import pick_repo, candidate_repos  # noqa: E402

LEDGER_FILE = "brief_ledger.json"
SHADOW_FILE = "brief_shadow.json"
HISTORY_FILE = "daily_brief_history.json"
# 与 aggregate_shadow/gen_daily_brief 同口径(防口径分叉):涨跌幅绝对值 >0.5% 才 up/down,否则 flat
HIT_THRESHOLD = 0.5
SCHEMA_VERSION = 1


# ── 基础 IO(幂等读写,与 record_shadow/_load_shadow 同模式)─────────────────
def ledger_path(repo: Path) -> Path:
    return Path(repo) / "data" / LEDGER_FILE


def load_ledger(repo: Path) -> list[dict]:
    p = ledger_path(repo)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)]
    except Exception:
        pass
    return []


def save_ledger(repo: Path, rows: list[dict]) -> None:
    p = ledger_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_db(explicit: str = "") -> Path:
    """挑 daily_metric MAX(date) 最新的 sentiment.db(REPO env → trade-data → trade),
    与 gen_daily_brief.pick_db 同口径;显式 --db 优先(自验/回放用)。"""
    if explicit:
        return Path(explicit)
    best, best_date = None, ""
    for r in candidate_repos():
        db = r / "data" / "sentiment.db"
        if not db.exists():
            continue
        m = ""
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            m = (conn.execute("SELECT MAX(date) FROM daily_metric").fetchone() or [""])[0] or ""
            conn.close()
        except Exception:
            m = ""
        if m > best_date:
            best_date, best = m, db
    return best or Path("/Users/linhuichen/code/trade-data/data/sentiment.db")


def _actual_direction(pct) -> str | None:
    """与 aggregate_shadow._actual_direction 同口径(HIT_THRESHOLD=0.5 三分类)。"""
    if pct is None:
        return None
    if pct > HIT_THRESHOLD:
        return "up"
    if pct < -HIT_THRESHOLD:
        return "down"
    return "flat"


def _load_sh_pct_map(db_path: Path) -> dict:
    """index_daily sh 全表 date->pct_change(与 backfill_hits/aggregate_shadow 同源)。"""
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


def _load_history_items(repo: Path) -> list[dict]:
    """读 static-site/data/daily_brief_history.json 条目(hit 三层回填搬运源)。"""
    p = Path(repo) / "static-site" / "data" / HISTORY_FILE
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        items = obj.get("items") if isinstance(obj, dict) else obj
        if isinstance(items, list):
            return items
    except Exception:
        pass
    return []


# ── 未注入面当日快照(extra_faces;调研报告 §3.2 清单逐项落实)───────────────
# 2026-08-26 实测(trade-data/data/sentiment.db):
#   新高新低/可转债/股息率/预估成交额当日值在库 ✓;board_daily 表存在但 0 行且无采集方
#   (调研报告 §3.2「概念板块在库」与实测不符——本快照如实记 empty_table note,不伪造数据;
#    Phase2 若升格注入面需先补采集链路)。
_NHNL_20D = ("a_nh_20d", "a_nl_20d")
_NHNL_52W = ("a_nh_52w", "a_nl_52w", "a_nhnl_52w")
_SENTIMENT_IDS_LIKE = "sentiment_%"
_SENTIMENT_EXTRA_IDS = ("a_sentiment", "fear_greed")

EXTRA_FACE_KEYS = (
    "nhnl_20d", "nhnl_52w", "board_concept_top", "cov_premium_median",
    "a_div_yield", "amount_forecast", "sentiment_pctile",
)


def _collect_extra_faces(conn: sqlite3.Connection, date: str) -> tuple[dict, dict]:
    """未注入面当日值快照。返回 (faces, notes);notes 仅在取不到时给原因(诚实标注)。"""
    faces: dict = {}
    notes: dict = {}

    def _m(mid: str):
        r = conn.execute(
            "SELECT value FROM daily_metric WHERE date=? AND metric_id=?", (date, mid)).fetchone()
        return r[0] if r and r[0] is not None else None

    # ① 新高新低(大面积0是数据源现状,guard 注释同源;0 照实记录不拦)
    #    口径:每日行 schema 恒定——EXTRA_FACE_KEYS 7 槽位全部在位,取不到写 None+note
    #    (诚实标注不伪造;反思层读字段免判键存在,--check 机检按全占位校验)
    nh20, nl20 = _m(_NHNL_20D[0]), _m(_NHNL_20D[1])
    if nh20 is not None or nl20 is not None:
        faces["nhnl_20d"] = {"nh": nh20, "nl": nl20}
    else:
        faces["nhnl_20d"] = None
        notes["nhnl_20d"] = "missing_in_db"
    nh52, nl52, diff52 = _m(_NHNL_52W[0]), _m(_NHNL_52W[1]), _m(_NHNL_52W[2])
    if any(v is not None for v in (nh52, nl52, diff52)):
        faces["nhnl_52w"] = {"nh": nh52, "nl": nl52, "diff": diff52}
    else:
        faces["nhnl_52w"] = None
        notes["nhnl_52w"] = "missing_in_db"

    # ② 概念板块日线(board_daily:pct_change/net_inflow;空表如实标注)
    try:
        bmax = (conn.execute("SELECT MAX(date) FROM board_daily").fetchone() or [None])[0]
        brows = []
        if bmax:
            brows = conn.execute(
                "SELECT board_name,pct_change,net_inflow FROM board_daily WHERE date=? "
                "ORDER BY pct_change DESC LIMIT 10", (bmax,)).fetchall()
        if brows:
            faces["board_concept_top"] = [
                {"name": r[0], "pct_change": r[1], "net_inflow": r[2]} for r in brows]
            if bmax != date:
                notes["board_concept_top"] = f"stale_latest_{bmax}"
        elif bmax is None:
            faces["board_concept_top"] = None
            notes["board_concept_top"] = "empty_table_no_collector"
        else:
            faces["board_concept_top"] = None
            notes["board_concept_top"] = f"no_data_for_{date}_latest_{bmax}"
    except Exception as e:
        faces["board_concept_top"] = None
        notes["board_concept_top"] = f"query_error:{type(e).__name__}"

    # ③④⑤ 可转债溢价中位数 / 股息率 / 预估成交额(+换手中位/换手率附带,有就带)
    cov = _m("cov_premium_median")
    if cov is not None:
        faces["cov_premium_median"] = cov
    else:
        faces["cov_premium_median"] = None
        notes["cov_premium_median"] = "missing_in_db"
    dv = _m("a_div_yield")
    if dv is not None:
        faces["a_div_yield"] = dv
    else:
        faces["a_div_yield"] = None   # 例:股息率 T-1 出数,T 日行如实 None+note
        notes["a_div_yield"] = "missing_in_db"
    amt = _m("a_amount_forecast")
    if amt is not None:
        item = {"forecast": amt}
        to_med = _m("a_turnover_median")
        to_rate = _m("a_turnover_rate")
        if to_med is not None:
            item["turnover_median"] = to_med
        if to_rate is not None:
            item["turnover_rate"] = to_rate
        faces["amount_forecast"] = item
    else:
        faces["amount_forecast"] = None
        notes["amount_forecast"] = "missing_in_db"

    # ⑥ 情绪分自身历史百分位:expanding 口径(只用 <=date 全史,防前视 §5.1⑥;
    #    分位 = 序列内 <=当日值的比例×100)
    sp: dict = {}
    try:
        rows = conn.execute(
            "SELECT score_id,value FROM score_daily WHERE date=? AND value IS NOT NULL",
            (date,)).fetchall()
        for sid, val in rows:
            if not (sid.startswith("sentiment_") or sid in _SENTIMENT_EXTRA_IDS):
                continue
            seq = [r[0] for r in conn.execute(
                "SELECT value FROM score_daily WHERE score_id=? AND date<=? AND value IS NOT NULL "
                "ORDER BY date", (sid, date))]
            if seq:
                pctile = round(100.0 * sum(1 for x in seq if x <= val) / len(seq), 1)
                sp[sid] = {"value": val, "pctile": pctile, "n": len(seq)}
        if sp:
            faces["sentiment_pctile"] = sp
        else:
            faces["sentiment_pctile"] = None
            notes["sentiment_pctile"] = f"no_scores_for_{date}"
    except Exception as e:
        faces["sentiment_pctile"] = None
        notes["sentiment_pctile"] = f"query_error:{type(e).__name__}"
    return faces, notes


# ── 引用审计(Phase1 机械层:面级特征 token 锚定;audit_method=token_v1)────────
# 已注入面(load_data 注入域的关键可 token 化面;value 恒标 injected,missed 时提示
# 「注入了却没引用」——这也是反思素材:给了料没用上)。tokens 为宽匹配,Phase1 观察期
# 接受噪音,误报/漏报由 Phase2 数值级锚定收紧(诚实标注 audit_method)。
_INJECTED_FACE_TOKENS: list[tuple[str, list[str]]] = [
    ("futures_inst", ["中信", "top20", "机构", "净空", "净多", "席位"]),
    ("margin", ["两融", "融资余额", "融券"]),
    ("hk_south", ["南向"]),
    ("north_flow", ["北向", "外资"]),
    ("qvix", ["QVIX", "波动率"]),
    ("ad_line", ["腾落", "涨跌比", "宽度"]),
    ("lhb", ["龙虎榜"]),
    ("unlock_ipo", ["解禁", "IPO"]),
    ("daban", ["打板", "连板", "涨停溢价"]),
    ("valuation", ["估值"]),
    ("us_futures", ["纳指", "标普", "道琼"]),
    ("us10y", ["美债", "美十债", "10Y"]),
    ("gold_oil", ["黄金", "原油", "白银", "金价"]),
    ("fx_cnh", ["人民币", "汇率", "USDCNH", "离岸"]),
    ("signal_today", ["信号", "买点"]),
]
# 未注入面(与 extra_faces 键一一对应;命中说明模型自发提及了未注入的数据面)
_EXTRA_FACE_TOKENS: list[tuple[str, list[str]]] = [
    ("nhnl", ["新高", "新低"]),
    ("board_concept", ["概念板块", "题材板块"]),
    ("cov_premium", ["可转债", "转债", "转股溢价"]),
    ("div_yield", ["股息"]),
    ("amount_forecast", ["成交额预估", "预估成交额", "成交额预测"]),
]


def build_face_registry(data: dict | None) -> list[dict]:
    """候选面全集 = 已注入静态面 + 未注入面 + ind_flow 动态行业名面(注入域 top5/bottom5)。"""
    reg: list[dict] = []
    for fid, tokens in _INJECTED_FACE_TOKENS:
        reg.append({"face_id": fid, "tokens": tokens, "kind": "injected"})
    for fid, tokens in _EXTRA_FACE_TOKENS:
        reg.append({"face_id": fid, "tokens": tokens, "kind": "extra"})
    ind = (data or {}).get("ind_flow") or {}
    for side in ("top", "bottom"):
        for it in (ind.get(side) or []):
            nm = (it or {}).get("name")
            if nm:
                reg.append({"face_id": f"ind_flow.{nm}", "tokens": [nm], "kind": "injected"})
    return reg


def _extra_value_desc(extra_faces: dict, notes: dict, key_prefix_map: dict) -> str:
    """missed_faces[].value 的未注入面当日值摘要(拿真实数字说话,§23.9 精神)。"""
    out = []
    for face_id, ek in key_prefix_map.items():
        v = extra_faces.get(ek)
        if v is None:
            out.append(f"{face_id}={notes.get(ek, 'N/A')}")
        elif isinstance(v, dict):
            out.append(f"{face_id}={json.dumps(v, ensure_ascii=False)}")
        else:
            out.append(f"{face_id}={v}")
    return ";".join(out)


def run_cite_audit(brief: dict | None, data: dict | None,
                   extra_faces: dict, notes: dict) -> tuple[dict, list]:
    """机械引用审计:预测文本(text 四段+risk_items+highlights)拼接后对面 token 锚定比对。
    返回 (cite_audit_dict, missed_faces_list)。"""
    meta = (brief or {}).get("meta") or {}
    text = (brief or {}).get("text") or {}
    corpus = " ".join(filter(None, [
        text.get("review"), text.get("trend"), text.get("watch"), text.get("risk"),
        " ".join(str(x) for x in (meta.get("risk_items") or [])),
        " ".join(str(x) for x in (meta.get("highlights") or [])),
    ]))
    referenced: list[str] = []
    missed: list[dict] = []
    extra_desc = _extra_value_desc(extra_faces, notes, {
        "nhnl_20d/52w": "nhnl_20d", "board_concept": "board_concept_top",
        "cov_premium": "cov_premium_median", "div_yield": "a_div_yield",
        "amount_forecast": "amount_forecast", "sentiment_pctile": "sentiment_pctile",
    })
    extra_face_to_ek = {
        "nhnl": "nhnl_20d", "board_concept": "board_concept_top",
        "cov_premium": "cov_premium_median", "div_yield": "a_div_yield",
        "amount_forecast": "amount_forecast", "sentiment_pctile": "sentiment_pctile",
    }
    for f in build_face_registry(data):
        hit = any(t and t in corpus for t in f["tokens"])
        if hit:
            referenced.append(f["face_id"])
            continue
        if f["kind"] == "injected":
            val = "injected_but_uncited"
        else:
            ek = extra_face_to_ek.get(f["face_id"])
            v = extra_faces.get(ek) if ek else None
            if v is None:
                val = notes.get(ek, "missing_in_db") if ek else "missing_in_db"
            else:
                val = json.dumps(v, ensure_ascii=False)
        missed.append({"face": f["face_id"], "value": val})
    _ = extra_desc  # 保留变量便于调试(不再单独使用)
    return ({"referenced_faces": referenced, "audit_method": "token_v1"}, missed)


# ── 当日行写入(gen_daily_brief 主流程尾部调用;幂等同 date 覆盖)──────────────
_ANCHOR_KEYS = ("turns", "ma_bull", "rate_down_channel", "us10y", "gold",
                "nq_chg", "nq_open_low")


def record_ledger(date: str, cfg: dict, db_path: Path, repo: Path,
                  brief: dict | None = None, data: dict | None = None,
                  shadow_rec: dict | None = None) -> dict | None:
    """写当日 ledger 行(主流程尾部 write_outputs 之后调)。返回记录 dict,失败 None。

    anchor 因子优先复用 shadow_rec(record_shadow 同源缓存已算,零额外 DB 读);
    shadow 关闭/缺失时兜底现算(延迟 import 防循环,gen_daily_brief 此时已加载)。"""
    try:
        anchor = None
        lean = basis = strength = None
        if isinstance(shadow_rec, dict):
            f = shadow_rec.get("factors") or {}
            anchor = {k: f.get(k) for k in _ANCHOR_KEYS}
            lean = shadow_rec.get("pred_shadow")
            basis = shadow_rec.get("basis") or []
            strength = shadow_rec.get("strength")
        else:
            try:
                from gen_daily_brief import _compute_direction_anchor, _shadow_lean
                factors = _compute_direction_anchor(db_path, date)
                s = _shadow_lean(factors)
                anchor = {k: factors.get(k) for k in _ANCHOR_KEYS}
                lean, basis, strength = s["lean"], s["basis"], s["strength"]
            except Exception:
                anchor = None  # 因子计算失败不阻塞底稿其余部分(notes 由 anchor=None 表达)

        meta = (brief or {}).get("meta") or {}
        text = (brief or {}).get("text") or {}

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        try:
            extra_faces, face_notes = _collect_extra_faces(conn, date)
        finally:
            conn.close()

        audit, missed = run_cite_audit(brief, data, extra_faces, face_notes)

        pred_side = {
            "version": meta.get("version"),
            # direction_call=R3 强制二选一(2026-08-24);老条目 fallback direction
            "direction_call": meta.get("direction_call") or meta.get("direction"),
            "range": meta.get("range"),
            "index_ranges": meta.get("index_ranges"),
            "sector_ranges": meta.get("sector_ranges"),
            "confidence_reason": meta.get("confidence_reason"),
            "risk_items": meta.get("risk_items"),
            "highlights": meta.get("highlights"),
            "text": {k: text.get(k) for k in ("review", "trend", "watch", "risk")},
        }
        rec = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "pred_side": pred_side,
            "pred_confidence": meta.get("confidence"),
            "factor_states": {
                "anchor": anchor,
                "shadow_lean": lean,
                "shadow_basis": basis,
                "strength": strength,
                "risk_items": meta.get("risk_items") or [],
                "extra_faces": extra_faces,
                "extra_faces_note": face_notes or None,
            },
            "cite_audit": audit,
            "missed_faces": missed,
            "actual_side": None,   # 次日由 reconcile_ledger 回填
            "hit": None,
            "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        rows = load_ledger(repo)
        rows = [r for r in rows if r.get("date") != date] + [rec]
        save_ledger(repo, rows)
        return rec
    except Exception:
        return None


# ── 次日回填(reconcile;history 三层搬运优先 + sh_map 方向兜底,R1 断档防护)────
def reconcile_ledger(repo: Path, db_path: Path, only_date: str | None = None) -> dict:
    """对 ledger 中未回填行回填 actual_side/hit。幂等可重复跑;返回统计 dict。"""
    rows = load_ledger(repo)
    hist_items = _load_history_items(repo)
    hist_by_date = {it.get("date") or (it.get("meta") or {}).get("date"): it
                    for it in hist_items if isinstance(it, dict)}
    sh_map = _load_sh_pct_map(db_path)
    dates = sorted(sh_map.keys())
    n_changed = 0
    for rec in rows:
        d = rec.get("date")
        if not d or (only_date and d != only_date):
            continue
        changed = False

        # ① actual_side(方向实际)
        if rec.get("actual_side") is None:
            h = hist_by_date.get(d)
            hhit = ((h or {}).get("meta") or {}).get("hit") or {}
            if h and hhit.get("direction") is not None:
                # history 已三层回填 → 搬运(与前端展示位同源,§22)
                nb = h.get("_backfilled_via") or next((x for x in dates if x > d), None)
                rec["actual_side"] = {
                    "next_date": nb,
                    "actual_sh_pct": hhit.get("actual_sh_pct"),
                    "actual_direction": hhit.get("actual_direction"),
                }
                changed = True
            elif dates:
                nxt = next((x for x in dates if x > d), None)
                pct = sh_map.get(nxt) if nxt else None
                if pct is not None:
                    rec["actual_side"] = {
                        "next_date": nxt,
                        "actual_sh_pct": round(pct, 2),
                        "actual_direction": _actual_direction(pct),
                    }
                    changed = True
                # pct 未入库(采集晚到)→ 不硬判留待下次滚动清账(R1 断档防护同款)

        # ② hit(三层搬运优先;history 断档时按 pred vs actual 判方向级)
        if rec.get("hit") is None:
            h = hist_by_date.get(d)
            hhit = ((h or {}).get("meta") or {}).get("hit") or {}
            if h and hhit.get("direction") is not None:
                rec["hit"] = {
                    "direction": hhit.get("direction"),
                    "direction_call_hit": hhit.get("direction_call_hit"),
                    "range_hit": hhit.get("range_hit"),
                    "middle_hits": hhit.get("middle_hits"),
                    "sector_hits": hhit.get("sector_hits"),
                    "source": "history_backfill",
                }
                changed = True
            else:
                adir = (rec.get("actual_side") or {}).get("actual_direction")
                pd = ((rec.get("pred_side") or {}).get("direction_call"))
                if adir is not None:
                    rec["hit"] = {
                        "direction": (pd == adir) if pd else None,
                        "direction_call_hit": (pd == adir) if (pd and adir) else None,
                        "range_hit": None, "middle_hits": None, "sector_hits": None,
                        "source": "ledger_fallback_direction_only",
                    }
                    changed = True
                # actual 也没有 → 整行继续留空待下次
        if changed:
            n_changed += 1
    if n_changed:
        save_ledger(repo, rows)
    return {"rows": len(rows), "changed": n_changed}


# ── 存量迁移(一次性;brief_shadow.json 并入,0/4 战绩如实保留当首批活案例)──────
def migrate_shadow(repo: Path, db_path: Path) -> dict:
    """把 data/brief_shadow.json 存量并入 ledger。幂等:已有 date 行只补缺字段不全量覆盖
    (保护可能已由 record_ledger 写入的当日内容);历史行 extra_faces 无法补采(T 日快照
    已过)→ 置 {} + note 诚实标注 migrated_pre_phase1。"""
    sp = Path(repo) / "data" / SHADOW_FILE
    try:
        srows = [r for r in json.loads(sp.read_text(encoding="utf-8")) if isinstance(r, dict)]
    except Exception:
        srows = []
    rows = load_ledger(repo)
    by_date = {r.get("date"): r for r in rows}
    hist_items = _load_history_items(repo)
    hist_by_date = {it.get("date") or (it.get("meta") or {}).get("date"): it
                    for it in hist_items if isinstance(it, dict)}
    sh_map = _load_sh_pct_map(db_path)
    dates = sorted(sh_map.keys())
    n_added = n_patched = 0
    for s in srows:
        d = s.get("date")
        if not d:
            continue
        f = s.get("factors") or {}
        anchor = {k: f.get(k) for k in _ANCHOR_KEYS}
        if d in by_date:
            rec = by_date[d]
            patched = False
            if rec.get("factor_states", {}).get("anchor") is None and anchor.get("turns"):
                rec.setdefault("factor_states", {})["anchor"] = anchor
                rec["factor_states"].setdefault("shadow_lean", s.get("pred_shadow"))
                rec["factor_states"].setdefault("shadow_basis", s.get("basis") or [])
                patched = True
            if rec.get("actual_side") is None and s.get("actual"):
                rec["actual_side"] = s["actual"]
                patched = True
            if patched:
                n_patched += 1
            continue
        # 新行:pred_side 尽量从 history 搬(meta/text 本就归档于 history)
        h = hist_by_date.get(d)
        hmeta = (h or {}).get("meta") or {}
        htext = (h or {}).get("text") or {}
        has_pred = bool(h)
        pred_side = None
        if has_pred:
            pred_side = {
                "version": hmeta.get("version"),
                "direction_call": hmeta.get("direction_call") or hmeta.get("direction"),
                "range": hmeta.get("range"),
                "index_ranges": hmeta.get("index_ranges"),
                "sector_ranges": hmeta.get("sector_ranges"),
                "confidence_reason": hmeta.get("confidence_reason"),
                "risk_items": hmeta.get("risk_items"),
                "highlights": hmeta.get("highlights"),
                "text": {k: htext.get(k) for k in ("review", "trend", "watch", "risk")},
            }
        # actual/hit:shadow 已回填的搬;s.actual 与 actual_side 结构同构直接用。
        # hit 不造占位 dict(留 None)——reconcile 以 hit is None 判「未回填」,占位会把
        # migrated 行永久挡在滚动清账外(history 后续可搬时也搬不上)= 断档,违背 R1 精神。
        actual = s.get("actual")
        hit = None
        hhit = hmeta.get("hit") or {}
        if h and hhit.get("direction") is not None:
            hit = {"direction": hhit.get("direction"),
                   "direction_call_hit": hhit.get("direction_call_hit"),
                   "range_hit": hhit.get("range_hit"),
                   "middle_hits": hhit.get("middle_hits"),
                   "sector_hits": hhit.get("sector_hits"),
                   "source": "history_backfill"}
        elif not actual and dates:
            nxt = next((x for x in dates if x > d), None)
            pct = sh_map.get(nxt) if nxt else None
            if pct is not None:
                actual = {"next_date": nxt, "actual_sh_pct": round(pct, 2),
                          "actual_direction": _actual_direction(pct)}
        rec = {
            "schema_version": SCHEMA_VERSION,
            "date": d,
            "migrated_from": SHADOW_FILE,
            "pred_side": pred_side,
            "pred_confidence": hmeta.get("confidence") if has_pred else None,
            "factor_states": {
                "anchor": anchor,
                "shadow_lean": s.get("pred_shadow"),
                "shadow_basis": s.get("basis") or [],
                "strength": s.get("strength"),
                "risk_items": (hmeta.get("risk_items") or []) if has_pred else [],
                "extra_faces": {},
                "extra_faces_note": "migrated_pre_phase1_not_snapshotted",
            },
            "cite_audit": None,       # 历史行引用审计不可回溯补算(token 比对可做但无当日
            "missed_faces": [],       # ind_flow 动态面注册表),诚实置空待 Phase2 决策
            "actual_side": actual,
            "hit": hit,
        }
        rows.append(rec)
        by_date[d] = rec
        n_added += 1
    if n_added or n_patched:
        rows.sort(key=lambda r: r.get("date") or "")
        save_ledger(repo, rows)
    return {"shadow_rows": len(srows), "added": n_added, "patched": n_patched}


# ── 软机检(Phase1 观察期;不挂 deploy 硬链)─────────────────────────────────
def check_ledger(repo: Path, db_path: Path) -> tuple[bool, list[str]]:
    """ledger 当日行存在性 + factor_states 关键字段非空。PASS=True。"""
    problems: list[str] = []
    rows = load_ledger(repo)
    if not rows:
        return False, ["ledger 文件不存在或为空(生成链未跑/写入挂载失效)"]
    # 数据侧「当日」= daily_metric 最新日期(生成以 overview.date 对齐 DB 最新交易日)
    expect = ""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        expect = (conn.execute("SELECT MAX(date) FROM daily_metric").fetchone() or [""])[0] or ""
        conn.close()
    except Exception:
        pass
    latest = max((r.get("date") or "") for r in rows)
    if expect and latest != expect:
        problems.append(f"最新行 date={latest or '∅'} ≠ DB 最新交易日 {expect}(当日行缺失,生成链断)")
    rec = next((r for r in rows if r.get("date") == latest), None)
    if rec is None:
        problems.append("最新行解析失败")
        return False, problems
    fs = rec.get("factor_states") or {}
    anchor = fs.get("anchor") or {}
    if anchor.get("turns") is None:
        problems.append("factor_states.anchor.turns 缺失(None=因子计算失败未兜底)")
    if not isinstance(anchor.get("ma_bull"), (bool, type(None))):
        problems.append("factor_states.anchor.ma_bull 类型异常")
    ef = fs.get("extra_faces") or {}
    missing_keys = [k for k in EXTRA_FACE_KEYS if k not in ef]
    if missing_keys:
        problems.append(f"extra_faces 缺键: {missing_keys}(应含全部未注入面槽位,取不到也须占位)")
    ca = rec.get("cite_audit") or {}
    if not isinstance(ca.get("referenced_faces"), list):
        problems.append("cite_audit.referenced_faces 非列表(引用审计未跑)")
    if not isinstance(rec.get("missed_faces"), list):
        problems.append("missed_faces 非列表")
    if not (rec.get("pred_side") or {}).get("direction_call"):
        problems.append("pred_side.direction_call 空(预测侧未写入)")
    ok = not problems
    return ok, problems


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 预测融合底座 brief_ledger(Phase1):回填/迁移/软机检")
    ap.add_argument("--date", default="", help="只回填指定行 date(YYYYMMDD)")
    ap.add_argument("--reconcile", action="store_true", help="回填全部可回填行(默认动作)")
    ap.add_argument("--migrate-shadow", dest="migrate_shadow", action="store_true",
                    help="存量 brief_shadow.json 并入 ledger(幂等一次性)")
    ap.add_argument("--check", action="store_true", help="软机检(最新行存在+关键字段非空)")
    ap.add_argument("--db", default="", help="显式指定 sentiment.db 路径(自验/回放用)")
    args = ap.parse_args()

    repo = pick_repo()
    db_path = _pick_db(args.db)
    print(f"[brief_ledger] repo={repo} db={db_path}")

    if args.migrate_shadow:
        st = migrate_shadow(repo, db_path)
        print(f"[brief_ledger] migrate: shadow_rows={st['shadow_rows']} "
              f"added={st['added']} patched={st['patched']}")
    if args.check:
        ok, problems = check_ledger(repo, db_path)
        for p in problems:
            print(f"[brief_ledger] ✗ {p}")
        print(f"[brief_ledger] check={'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    # 默认动作:reconcile(幂等滚动清账)
    st = reconcile_ledger(repo, db_path, only_date=args.date or None)
    print(f"[brief_ledger] reconcile: rows={st['rows']} changed={st['changed']}")
    if args.date and st["changed"] == 0:
        print(f"[brief_ledger] --date {args.date}: 无改动(已回填过=幂等,或下一交易日 pct 未入库留待补)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
