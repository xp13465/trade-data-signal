#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""噪音计数尺子（★6 的可测量部分，2026-10-28）。

回答一个问题：**某一天飞书告警群（alert）里，机制噪音几条、真故障几条？**
后面几批降噪（★4、重采失败去重、warning/恢复并摘要）都靠这把尺子验收。

数据源：单点台账 `data/alerts/alert_ledger.jsonl`（scripts/notify.py 每次实际外发追加一行）。
真实字段（2026-10-28 用云上 815 行真实样本核实，不是按文档猜的）：
    ts       "YYYY-MM-DD HH:MM:SS"（发送时刻，本机本地时间，无时区后缀）
    tree     运行树绝对路径
    tier     critical / warning / notice / digest / subscribe / agent_done
    key      去重键（dedup_key，或 subject 的 sha1 前 12 位）
    subject  消息标题（单行）
    channels {"email": bool, "feishu": bool[, "telegram": bool]}
    source   发送脚本名（notify.py / upload_r2.py / schedule_monitor.sh ...）
    group    飞书群 key：alert / report / agent_done / follow（少数行为 null）
    merged_count  可选，聚合消息「被并入的条数」

口径（用户 2026-10-27 拍板，全文 docs/ops/alert-denoise-spec-20261027.md ★6）
    机制噪音 0~3 条/天；真故障不设上限。
    只统计 group == "alert"（report/follow/agent_done 是业务输出，不在口径内）。
    分类优先级：
      ① 行内已有非空 noise_class ⇒ 直接用（为 notify.py 将来打标预留；
         **未标注 = 真故障/业务，不计数**；标签只应取下面六个噪音类之一）
         ⚠️ 打标值与计数分类名不是一回事（标签 ≠ 分类名）：打标值 `routine_notice`
            对应计数分类 `routine`；其余五个同名。映射见 NOISE_CLASS_TO_CATEGORY，
            未知标签原样保留（不静默改写成别的类）。
         **发送侧打标值域（单一事实源，与 scripts/notify.py:_record_ledger docstring
         逐字一致）= digest / warning_batch / recovery / escalation；routine_notice 是
         尺子预测值、不在发送侧打标；repeat 由读侧按 24h 谓词算出、不发标签。**
         critical 兜底（批次3-B 2026-10-28）：`tier == "critical"` 的行除 escalation 外，
         任何显式 noise_class 都不得把它降级成噪音（critical 一律按真故障计）。
      ② 否则按谓词回算，**按下表顺序首个命中为准**（互斥，保证各构成之和 = 噪音总数）：
         digest         tier == "digest"
         warning_batch  subject 以 "[告警·聚合]" 开头
         escalation     subject 含 "升级 critical" 或 "持续故障升级"
         recovery       subject 以 "[恢复]" 开头
         routine        subject 含 孤儿买 / 缺失历史信号 / 历史行改写-提示 / 锁跳过
                        （tier == "critical" 的行**不算** routine）
         repeat         同一 (tier, 归一化 subject) 在 **前 24h 内已出现过**
                        （归一化 = 去日期/时间/纯数字，保留任务名/单位名；
                          恰好在 24h00m 的算「在内」，24h01m 的算「不在内」）
                        （tier == "critical" 的行**不算** repeat）
      ③ 都不命中 ⇒ 真故障首报（不设上限）
    谓词表照抄规格 ★6 交叉校验表，不得为了数字好看调整。
    重复判定只在 group == "alert" 的行之间比较（report 群消息不会让 alert 行变成 repeat）。

    critical 与噪音的关系（2026-10-28 审查补，用户口径「真故障不设上限」）
        critical 行**仍是 repeat 的历史参照**（后续同签名行照常可比），但**不许被打上
        repeat / routine 标签**——它们是真故障事件（同一事件当天再发生也是新事件）。
        escalation 保持规格原样（升级提醒暂按噪音计，是否改口径待用户拍板）。
        因此输出会同时给两种读法：`噪音 M`（含升级提醒）与
        `噪音(不含升级) M-E`（E = 升级提醒条数）；验收判定仍按 M 与阈值比较
        （escalation 口径未定，不擅改判定）。

    坏行与无数据（2026-10-28 审查补，防「0 条 ⇒ PASS」骗人）
        - JSON 解析不了的行、非对象行、**group=alert 但缺/空 subject 的行**
          一律计入 skipped_bad_lines 并打印，不参与计数。
        - 台账不存在 / 台账为空 / 该日无 alert 行 ⇒ 该日 `pass = null`（无数据，不判达标）；
          顶层 `no_data = true`。绝不用「噪音 0」冒充「达标」。

已知局限（诚实标注，不静默）
    repeat 的归一化会把「N 项计划任务异常」这类**不带任务名**的 subject 误并成同一签名
    （规格附录 A3 尚未修）⇒ repeat 可能高估、个别真故障可能被记成噪音。
    本脚本每次输出都会打印这一行提示，JSON 里也有 repeat_caveat 字段。

交叉校验（防漏标）
    若台账里**部分行**已带 noise_class，对未标注的行跑谓词；命中谓词却没标 ⇒ 输出
    WARN 清单（日期 + subject + 建议类别），**不判 FAIL**（避免误伤）。全部未标时不输出
    WARN（打标功能还没上线，属正常状态）。

JSON 结构（--json，字段稳定）
    {
      "date": "2026-10-27",                     # 窗口末日
      "date_range": ["2026-10-27", "2026-10-27"],  # --days N 时是 N 天窗口
      "ledger": "<绝对路径>",
      "ledger_exists": true,
      "no_data": false,                         # 台账不存在/为空/窗口内无 alert 行 ⇒ true
      "noise_max": 3,
      "days": [
        {"date": "...", "alert": 47, "noise": 41, "real": 6,
         "escalation": 2, "noise_excl_escalation": 39,
         "breakdown": {"digest": 2, "warning_batch": 0, ...},
         "pass": false, "no_data": false}
      ],
      "totals": {"alert": 47, "noise": 41, "real": 6,
                 "escalation": 2, "noise_excl_escalation": 39,
                 "breakdown": {...}, "pass": false, "no_data": false},
      "repeat_caveat": "repeat 类在 A3 修复前可能高估（不带任务名的 subject 会被误并）",
      "warn_untagged": [{"date": "...", "subject": "...", "suggested_class": "..."}],
      "skipped_bad_lines": 0,             # JSON 解析不了的行数 + group=alert 却缺 subject 的行数
      "skipped_undated_alert_rows": 0,    # group=alert 但 ts 解析不了的行数（无法归日，显式计数不静默丢）
      "records_scanned": 815
    }
    判定 PASS = 窗口内**每一天**噪音 <= noise_max（真故障不参与判定）。
    该日无 alert 行 ⇒ pass = null（无数据，无法判定）；窗口内全无 alert 行 ⇒ totals.pass = null。

退出码三态（2026-10-28 #321，供定时任务/机检直接判结果）：
    0 = PASS（有数据且每天噪音 <= noise_max）
    1 = FAIL（有数据且至少一天超阈值）
    2 = 测不了（参数错误 / 台账不存在 / 窗口内无 alert 数据 ⇒ pass=null）
改道到 report 群的 digest/recovery/escalation 条数只在输出里单列（diverted），
**不参与 PASS 判定**：尺子的口径始终是「飞书 alert 群里有几条机制噪音」。

用法
    python scripts/alert_noise_count.py --date 2026-10-27
    python scripts/alert_noise_count.py --date 2026-10-27 --days 7
    python scripts/alert_noise_count.py --date 2026-10-27 --json
    python scripts/alert_noise_count.py --ledger /path/to/alert_ledger.jsonl
默认台账 = $REPO/data/alerts/alert_ledger.jsonl（REPO 缺省 = 本仓库根），
与 scripts/alert_meter.py / notify.py:_ledger_path() 同一约定，不写死任何机器路径。

--all-groups 显式切换为只读运维通知补充视图，可用 --extra-ledger 增加台账。
该视图不判健康/PASS，不改变上面的旧单群合同；字段/覆盖边界见
docs/ops/alert-all-groups-20261106.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# 2026-10-28 #321: 用 absolute() 而非 resolve() —— scripts/ 是 trade-data -> trade 的
# symlink, resolve() 会穿透到真实仓库根(云上/开发树不一致), 致默认台账路径落到另一棵树,
# 表现为「台账不存在 ⇒ pass=null」。absolute() 保留调用侧路径形状, 与 $REPO 约定一致。
ROOT = Path(__file__).absolute().parent.parent
LEDGER_REL = Path("data") / "alerts" / "alert_ledger.jsonl"

# 用户拍板阈值：机制噪音 0~3 条/天（真故障不设上限）。
NOISE_MAX = 3

# repeat 判定窗口（规格 ★6：同一 (tier, 归一化 subject) 在 24h 内已出现过）。
REPEAT_WINDOW = timedelta(hours=24)

ALERT_GROUP = "alert"
REPORT_GROUP = "report"
# 改道到 report 群、但本质是「告警流水」的三类 noise_class（#321 出口分层后出现）。
DIVERTED_CLASSES = ("digest", "recovery", "escalation")

# 谓词表（照抄规格 ★6，顺序 = 分类优先级，互斥）。
WARNING_BATCH_PREFIX = "[告警·聚合]"
RECOVERY_PREFIX = "[恢复]"
ESCALATION_MARKERS = ("升级 critical", "持续故障升级")
ROUTINE_MARKERS = ("孤儿买", "缺失历史信号", "历史行改写-提示", "锁跳过")

# 构成输出顺序（固定六类在前，未来新增标签追加在后）。
CANONICAL_CLASSES = ("digest", "warning_batch", "escalation", "recovery", "routine", "repeat")

# tier 为 critical 的行 = 真故障事件：不进 repeat / routine 噪音分类（规格 ★6 2026-10-28 审查补）。
CRITICAL_TIER = "critical"

# 打标值 → 计数分类名（标签 ≠ 分类名：规格 ★6 里标签叫 routine_notice，计数分类叫 routine）。
# 未列出的标签原样保留，避免将来新增标签被静默改写。
NOISE_CLASS_TO_CATEGORY = {
    "digest": "digest",
    "warning_batch": "warning_batch",
    "escalation": "escalation",
    "recovery": "recovery",
    "routine_notice": "routine",
    "repeat": "repeat",
}

REPEAT_CAVEAT = "repeat 类在 A3 修复前可能高估（不带任务名的 subject 会被误并成同一签名）"

# 归一化：先去日期/时间（整段丢掉），再把纯数字换成占位符，保留任务名/单位名。
_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|\d{8}"
    r"|\d{1,2}-\d{1,2}"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def default_ledger_path() -> Path:
    """默认台账路径（与 notify.py / alert_meter.py 同一约定：REPO env 覆盖 > 仓库根）。"""
    return Path(os.environ.get("REPO") or ROOT) / LEDGER_REL


def normalize_subject(subject: str) -> str:
    """subject 归一化：去日期/时间/纯数字，折叠空白。"""
    s = str(subject or "")
    s = _DATETIME_RE.sub(" ", s)
    s = _NUM_RE.sub("#", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_ts(value) -> datetime | None:
    """台账 ts（"YYYY-MM-DD HH:MM:SS"，无时区）→ datetime；解析不了返回 None。"""
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def predicate_class(rec: dict) -> str | None:
    """按规格 ★6 谓词表回算类别（不含 repeat；顺序即优先级）。

    tier == "critical" 的行不落 routine（critical 一律按真故障事件计）。
    """
    tier = str(rec.get("tier") or "")
    subject = str(rec.get("subject") or "")
    if tier == "digest":
        return "digest"
    if subject.startswith(WARNING_BATCH_PREFIX):
        return "warning_batch"
    if any(m in subject for m in ESCALATION_MARKERS):
        return "escalation"
    if subject.startswith(RECOVERY_PREFIX):
        return "recovery"
    if tier != CRITICAL_TIER and any(m in subject for m in ROUTINE_MARKERS):
        return "routine"
    return None


def load_records(path: Path, *, all_groups: bool = False) -> tuple[list[dict], int, int]:
    """读 JSONL 台账。

    返回 (记录列表, JSON 坏行数, group=alert 缺 subject 的坏行数)；文件不存在返回 ([], 0, 0)。
    缺 subject 的 alert 行无法判别事件身份，按坏行跳过（规格 ★4.2，2026-10-28 审查补 F4），
    不静默当成真故障计入。
    """
    records: list[dict] = []
    bad = 0
    bad_subject = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if not isinstance(rec, dict):
                    bad += 1
                    continue
                if (not all_groups and str(rec.get("group") or "") == ALERT_GROUP
                        and not str(rec.get("subject") or "").strip()):
                    bad_subject += 1
                    continue
                if all_groups:
                    rec = dict(rec, _ledger=str(path), _line=line_number)
                records.append(rec)
    except FileNotFoundError:
        return [], 0, 0
    return records, bad, bad_subject


def _ordered_breakdown(counter: Counter) -> dict:
    out = {k: int(counter.get(k, 0)) for k in CANONICAL_CLASSES}
    for k in sorted(counter):
        if k not in out:
            out[k] = int(counter[k])
    return out


def classify_rows(records: list[dict], days: list[str]) -> dict:
    """纯函数：给定台账记录与日期窗口，算出每天噪音/真故障（不读表、不取墙钟）。

    返回 {"days": [...], "totals": {...}, "warn_untagged": [...], "any_labeled": bool}。
    无行/空台账均返回 0/0，不做除法。
    """
    day_set = set(days)
    alert_rows: list[tuple[datetime, dict]] = []
    undated = 0
    for rec in records:
        if str(rec.get("group") or "") != ALERT_GROUP:
            continue
        ts = parse_ts(rec.get("ts"))
        if ts is None:
            # group=alert 却没有可解析的 ts ⇒ 无法归日；显式计数，不静默丢。
            undated += 1
            continue
        alert_rows.append((ts, rec))
    alert_rows.sort(key=lambda pair: pair[0])

    any_labeled = any(str(rec.get("noise_class") or "").strip() for _, rec in alert_rows)

    per_day = {d: {"alert": 0, "noise": 0, "real": 0, "breakdown": Counter()} for d in days}
    warn: list[dict] = []
    history: dict[tuple[str, str], list[datetime]] = {}

    for ts, rec in alert_rows:
        tier = str(rec.get("tier") or "")
        sig = (tier, normalize_subject(rec.get("subject")))
        prior = history.setdefault(sig, [])
        # 只留 24h 窗口内的历史（含恰好 24h），防长跑内存增长。
        prior[:] = [t for t in prior if (ts - t) <= REPEAT_WINDOW]
        is_repeat = bool(prior)
        # critical 行仍进历史（后续同签名行照常可比），但自己不被打 repeat 标签。
        prior.append(ts)

        day = ts.strftime("%Y-%m-%d")
        if day not in day_set:
            continue  # 窗口外的行只用来当 repeat 的历史参照

        tag = str(rec.get("noise_class") or "").strip()
        if tag:
            # 标签 → 分类名映射（routine_notice 标签对应 routine 分类；未知标签原样保留）。
            label = NOISE_CLASS_TO_CATEGORY.get(tag, tag)
            # C2(2026-10-28 批次3-B): critical 行 = 真故障事件（用户口径「真故障不设上限」），
            # 除升级提醒(escalation)外, **任何显式 noise_class 都不得把它降级成噪音**。
            # 发送侧(_noise_class_of)已不产 repeat/routine 标签 ⇒ 本处是读侧兜底, 防将来
            # 有人在发送侧误打标把真故障洗成噪音。升级提醒仍单列(escalation, 口径待拍板)。
            if tier == CRITICAL_TIER and label != "escalation":
                label = None
        else:
            label = predicate_class(rec)
            if label is None and is_repeat and tier != CRITICAL_TIER:
                label = "repeat"
            if any_labeled and label is not None:
                warn.append({
                    "date": day,
                    "subject": str(rec.get("subject") or ""),
                    "suggested_class": label,
                })

        bucket = per_day[day]
        bucket["alert"] += 1
        if label is None:
            bucket["real"] += 1
        else:
            bucket["noise"] += 1
            bucket["breakdown"][label] += 1

    day_reports = []
    totals = {"alert": 0, "noise": 0, "real": 0, "breakdown": Counter()}
    for d in days:
        b = per_day[d]
        esc = int(b["breakdown"].get("escalation", 0))
        has_rows = b["alert"] > 0
        day_reports.append({
            "date": d,
            "alert": b["alert"],
            "noise": b["noise"],
            "real": b["real"],
            "escalation": esc,
            "noise_excl_escalation": b["noise"] - esc,
            "breakdown": _ordered_breakdown(b["breakdown"]),
            # 无 alert 行 ⇒ 无数据，pass = null（不许用「噪音 0」冒充达标）
            "pass": (b["noise"] <= NOISE_MAX) if has_rows else None,
            "no_data": not has_rows,
        })
        totals["alert"] += b["alert"]
        totals["noise"] += b["noise"]
        totals["real"] += b["real"]
        totals["breakdown"].update(b["breakdown"])

    judged = [r for r in day_reports if r["alert"] > 0]
    total_esc = int(totals["breakdown"].get("escalation", 0))
    return {
        "days": day_reports,
        "totals": {
            "alert": totals["alert"],
            "noise": totals["noise"],
            "real": totals["real"],
            "escalation": total_esc,
            "noise_excl_escalation": totals["noise"] - total_esc,
            "breakdown": _ordered_breakdown(totals["breakdown"]),
            # 窗口 PASS = 有数据的天每一天都达标（验收口径是「每天」0~3，不是平均值）
            "pass": all(r["pass"] for r in judged) if judged else None,
            "no_data": not judged,
        },
        "warn_untagged": warn,
        "any_labeled": any_labeled,
        "skipped_undated_alert_rows": undated,
    }


def count_diverted(records: list[dict], days: list[str]) -> dict:
    """纯函数：#321 出口分层后改道 report 群的告警流水条数（只展示，不参与 PASS）。

    口径：同一天、group == "report"、noise_class ∈ {digest, recovery, escalation}。
    升级 escalation 若 fail-open 直发则仍在 alert 群，由 classify_rows 正常计数，不重复算。
    """
    day_set = set(days)
    c: Counter = Counter()
    for rec in records:
        if str(rec.get("group") or "") != REPORT_GROUP:
            continue
        ts = parse_ts(rec.get("ts"))
        if ts is None or ts.strftime("%Y-%m-%d") not in day_set:
            continue
        tag = str(rec.get("noise_class") or "").strip()
        label = NOISE_CLASS_TO_CATEGORY.get(tag, tag)
        if label in DIVERTED_CLASSES:
            c[label] += 1
    return {
        "digest": int(c.get("digest", 0)),
        "recovery": int(c.get("recovery", 0)),
        "escalation": int(c.get("escalation", 0)),
        "total": sum(int(c.get(k, 0)) for k in DIVERTED_CLASSES),
    }


def _fmt_breakdown(breakdown: dict) -> str:
    return " / ".join(f"{k} {v}" for k, v in breakdown.items())


def render(payload: dict) -> str:
    """人读输出（日期 / 告警群 N = 噪音 M + 真故障 K / 升级提醒 E + 噪音不含升级 / 构成 / 验收）。"""
    lines: list[str] = []
    days = payload["days"]
    if len(days) == 1:
        d = days[0]
        if d["alert"] == 0:
            lines.append(f"日期 {d['date']}  告警群 0 条（无数据，无法判定；"
                         f"请核对 --ledger 路径与该日是否真无告警）")
            lines.append(f"验收：无数据，pass=null（不判 PASS）")
        else:
            lines.append(f"日期 {d['date']}  告警群 {d['alert']} 条 = "
                         f"噪音 {d['noise']} 条 + 真故障 {d['real']} 条")
            lines.append(f"其中：升级提醒 {d['escalation']} 条；"
                         f"噪音(不含升级) {d['noise_excl_escalation']} 条")
            lines.append(f"构成：{_fmt_breakdown(d['breakdown'])}")
            lines.append(f"验收：噪音 {d['noise']} <= {NOISE_MAX} ? "
                         f"{'PASS' if d['pass'] else 'FAIL'}（真故障不设上限）")
    else:
        lines.append(f"窗口 {payload['date_range'][0]} ~ {payload['date_range'][1]}"
                     f"（{len(days)} 天）")
        for d in days:
            if d["alert"] == 0:
                lines.append(f"  {d['date']}  告警群 0 条（无数据）")
                continue
            lines.append(f"  {d['date']}  告警群 {d['alert']} = 噪音 {d['noise']}"
                         f" + 真故障 {d['real']}（其中升级提醒 {d['escalation']}）"
                         f"  |  {_fmt_breakdown(d['breakdown'])}")
        t = payload["totals"]
        if t["no_data"]:
            lines.append(f"  合计 告警群 0 条（无数据）")
            lines.append(f"验收：无数据，pass=null（不判 PASS）")
        else:
            avg = (t["noise"] / len(days)) if days else 0.0
            lines.append(f"  合计 告警群 {t['alert']} = 噪音 {t['noise']} + 真故障 {t['real']}")
            lines.append(f"  其中：升级提醒 {t['escalation']} 条；"
                         f"噪音(不含升级) {t['noise_excl_escalation']} 条")
            lines.append(f"  构成：{_fmt_breakdown(t['breakdown'])}")
            lines.append(f"  日均噪音 {avg:.2f} 条/天")
            lines.append(f"验收：噪音每天 <= {NOISE_MAX} ? "
                         f"{'PASS' if t['pass'] else 'FAIL'}（真故障不设上限；"
                         f"无数据的天不参与判定）")

    dv = payload.get("diverted") or {}
    if dv.get("total"):
        lines.append(f"改道 report 群（不计入告警群、不参与验收）：摘要 {dv['digest']} 条 / "
                     f"恢复 {dv['recovery']} 条 / 升级 {dv['escalation']} 条 = 共 {dv['total']} 条")
    lines.append(f"提示：{REPEAT_CAVEAT}")

    warn = payload["warn_untagged"]
    if warn:
        lines.append(f"WARN 漏标 {len(warn)} 条（台账已部分打标，但下列行命中谓词却没标；"
                     f"仅供参考，不判 FAIL）：")
        for w in warn:
            subj = w["subject"]
            subj = subj[:90] + "…" if len(subj) > 90 else subj
            lines.append(f"  [{w['date']}] {subj}  → 建议 {w['suggested_class']}")
    return "\n".join(lines)


# 补充视图只认通知类型，不套用旧尺子的 repeat/真故障/PASS 推断。
ALL_GROUPS = ("alert", "report", "follow", "agent_done", "unknown")
OPS_SOURCES = {"schedule_monitor.sh", "monitor_72h.sh", "check_failed_units.py"}
BUSINESS_SOURCES = {"brief_push.py", "daily_summary_email.py"}
OPS_PREFIX = re.compile(r"^\[[^\]]*(告警|恢复|监控)[^\]]*\]")
RECOVERY_SUBJECT = re.compile(r"^\[[^\]]*恢复[^\]]*\]")
BUSINESS_PREFIXES = (
    "[完成]", "[codex]", "🤖 agent ", "[每日速递]", "[情绪速递", "[补充速递",
    "[买卖点", "[盘中", "[汪汪", "[收盘", "[订阅", "[明日买入",
    "盘中异动", "盘中实时", "买卖点信号", "买卖点提醒", "汪汪队", "明日买入计划",
)


def operations_kind(rec: dict) -> tuple[str, str]:
    """现行标签/主题/来源的保守识别；不认识的记录显式归 unknown。"""
    subject = rec.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return "unknown", "missing_or_invalid_subject"
    subject = subject.strip()
    tag = str(rec.get("noise_class") or "").strip()
    if tag and tag not in NOISE_CLASS_TO_CATEGORY:
        return "unknown", "unknown_noise_class"
    tier = str(rec.get("tier") or "")
    source = Path(str(rec.get("source") or "")).name
    business = (source == "codex_notify_bridge.py"
                or subject.startswith(BUSINESS_PREFIXES))
    if business:
        if tag or tier in {"critical", "warning", "digest"}:
            return "unknown", "conflicting_business_operations_metadata"
        return "business", "business_subject_or_completion_source"
    if tag:
        return NOISE_CLASS_TO_CATEGORY[tag], "noise_class"
    if subject.startswith("[告警·摘要]") or tier == "digest":
        return "digest", "digest_subject_or_tier"
    if subject.startswith(WARNING_BATCH_PREFIX):
        return "warning_batch", "warning_batch_subject"
    if any(m in subject for m in ESCALATION_MARKERS):
        return "escalation", "escalation_subject"
    if RECOVERY_SUBJECT.match(subject):
        return "recovery", "recovery_subject"
    if (OPS_PREFIX.match(subject) or subject.startswith("[状态说明]")
            or any(m in subject for m in ROUTINE_MARKERS)):
        return "operations", "operations_subject"
    if tier in {"critical", "warning"} or source in OPS_SOURCES:
        return "operations", "operations_tier_or_source"
    if tier in {"subscribe", "agent_done"} or source in BUSINESS_SOURCES:
        return "business", "business_tier_or_source"
    return "unknown", "unrecognized_subject_tier_source"


def _delivery_counts() -> dict:
    return {k: 0 for k in (
        "rows", "feishu_sent", "feishu_not_successful", "feishu_unknown",
        "declared_merged_slots", "merged_count_missing_rows", "merged_count_invalid_rows",
    )}


def _group_counts() -> dict:
    return {"ledger_rows": 0, "no_data": True, "business_rows": 0, "unknown_rows": 0,
            "operations": _delivery_counts(),
            "by_kind": {k: _delivery_counts() for k in ("operations",) + CANONICAL_CLASSES}}


def outbound_account(records: list[dict], days: list[str]) -> dict:
    """Additive strict account of the existing outbound ledger, never a PASS.

    status=sent/info_logged/deferred is not transport evidence. Event references
    and attempts are independent identities; legacy key/subject cannot replace
    either. Missing fields remain unknown, including all-failed attempts which
    the historical success-only ledger never recorded.
    """
    channels = {name: Counter() for name in ("email", "feishu", "telegram")}
    metadata = {"deferred", "info_logged", "tier", "defer_status"}
    channel_attempts, channel_successes = {}, {}
    events, attempts, problems, refs_seen = set(), {}, [], []
    accepted, root_causes, event_keys = {}, {}, {}
    populations = Counter()
    for rec in records:
        ts = parse_ts(rec.get("ts"))
        if not ts or ts.date().isoformat() not in days:
            continue
        kind, _ = operations_kind(rec)
        if rec.get("noise_class") == "routine_notice":
            kind = "routine"
        # Exact, source-verified old update_all completion call (49fe9:424).
        # Do not change the shared classifier or broad [完成] business prefix.
        if re.fullmatch(r"\[完成\] update_all \d+min \d{2}-\d{2} \d{2}:\d{2}", str(rec.get("subject") or "")):
            source = Path(str(rec.get("source") or "")).name
            if source in {"notify.py", "update_all.sh"} and rec.get("tier") in {"notice", "info"}:
                kind = "routine"
            elif source != "codex_notify_bridge.py":
                kind = "unknown"
        if kind == "routine" and rec.get("tier") == "critical":
            kind = "unknown"  # contradictory severity must not hide a real fault
        # A contradictory business label cannot hide explicitly linked ops.
        if rec.get("ops_event_refs") and kind == "business":
            kind = "operations"  # native explicit ops refs outrank a broad title
        elif kind == "unknown" and isinstance(rec.get("ops_event_refs"), list) and any(
                isinstance(ref, dict) and all(isinstance(ref.get(k), str) and ref[k].strip() for k in ("key", "event_id"))
                for ref in rec["ops_event_refs"]):
            if not (rec.get("tier") == "critical" and rec.get("noise_class") == "routine_notice"):
                kind = "operations"
        population = "unknown" if kind == "unknown" else "business" if kind == "business" else "operations"
        populations[population] += 1
        if population == "business":
            continue
        reasons = []
        aid = rec.get("attempt_id")
        if not isinstance(aid, str) or not aid.strip():
            aid = None
            reasons.append("attempt_id_unknown")
        else:
            # Keep raw message rows visible; only explicit attempt identity is
            # deduplicated, never subject, time, event_id or source_run.
            canonical = json.dumps({k: v for k, v in rec.items() if not k.startswith("_")},
                                   ensure_ascii=False, sort_keys=True)
            if aid in attempts:
                populations["repeated_attempt_rows"] += 1
                if attempts[aid] != canonical:
                    reasons.append("conflicting_attempt_id")
            else:
                attempts[aid] = canonical
        refs = rec.get("ops_event_refs")
        if not isinstance(refs, list) or not refs:
            reasons.append("event_refs_unknown")
        else:
            for ref in refs:
                if not isinstance(ref, dict):
                    reasons.append("invalid_event_ref")
                    continue
                refs_seen.append(dict(ref, attempt_id=aid))
                eid, key, phase = ref.get("event_id"), ref.get("key"), ref.get("phase")
                if isinstance(eid, str) and eid.strip():
                    events.add(eid)
                else:
                    reasons.append("event_id_unknown")
                if not isinstance(ref.get("source_run"), str) or not ref["source_run"].strip():
                    reasons.append("source_run_unknown")  # nullable in native contract
                if not isinstance(phase, str) or phase not in {"active", "recovery", "escalation"}:
                    reasons.append("unknown_event_phase")
                if not isinstance(key, str) or not key.strip():
                    reasons.append("event_key_unknown")
                if not isinstance(eid, str) or not eid.strip() or not isinstance(key, str) or not key.strip():
                    continue
                event_keys.setdefault(key, set()).add(eid)
                root_cause = ref.get("root_cause_id", rec.get("root_cause_id"))
                if isinstance(root_cause, str) and root_cause.strip():
                    root_causes.setdefault(root_cause, set()).add(eid)
                if phase not in ("active", "recovery", "escalation") or not aid:
                    continue
                for channel, success in (rec.get("channels") or {}).items() if isinstance(rec.get("channels"), dict) else []:
                    declared = rec.get("attempted_channels")
                    if (success is not True or channel in metadata or
                            (channel not in {"email", "feishu", "telegram"} and
                             not (isinstance(declared, list) and channel in declared))):
                        continue
                    identity = (eid, phase, channel, aid)
                    item = {"key": key, "event_id": eid, "phase": phase, "channel": channel, "attempt_id": aid,
                            "ts": rec["ts"]}
                    if identity not in accepted or ts < parse_ts(accepted[identity]["ts"]):
                        accepted[identity] = item
        attempted = rec.get("attempted_channels")
        attempted_valid = (isinstance(attempted, list) and all(isinstance(x, str) and x and x not in metadata for x in attempted)
                           and len(attempted) == len(set(attempted)))
        if not attempted_valid:
            reasons.append("attempted_channels_unknown")
            attempted = []
        raw = rec.get("channels")
        raw = raw if isinstance(raw, dict) else {}
        # Metadata keys (notably deferred/info_logged) are NOT channels.
        for extra in set(raw) - {"email", "feishu", "telegram"} - metadata:
            if extra not in attempted:
                reasons.append("unidentified_channel:" + extra)
        for name in set(channels) | set(attempted):
            c = channels.setdefault(name, Counter())
            c["rows"] += 1
            value = raw.get(name)
            if value is True:
                c["declared_success_rows"] += 1
                if kind == "routine":
                    c["routine_declared_success_rows"] += 1
                if aid:
                    channel_successes.setdefault(name, set()).add(aid)
                c["success_with_attempt_id" if aid else "success_attempt_unknown"] += 1
                if attempted_valid and name not in attempted:
                    reasons.append("success_without_attempt:" + name)
            elif value is False:
                c["declared_not_successful_rows"] += 1
            else:
                c["result_unknown_rows"] += 1
            if attempted_valid:
                c["attempted_rows" if name in attempted else "not_attempted_rows"] += 1
                if name in attempted and aid:
                    channel_attempts.setdefault(name, set()).add(aid)
                if name in attempted and value is False:
                    c["failed_attempt_rows"] += 1
                if name in attempted and type(value) is not bool:
                    reasons.append("attempt_result_unknown:" + name)
            else:
                c["attempt_unknown_rows"] += 1
            evidence = rec.get("receipt_evidence")
            if isinstance(evidence, dict) and name in evidence:
                c["receipt_evidence_declared_rows"] += 1
        if population == "unknown":
            reasons.append("operations_classification_unknown")
        if reasons:
            problems.append({"ledger": rec.get("_ledger"), "line": rec.get("_line"),
                             "attempt_id": aid, "reasons": sorted(set(reasons))})
    fields = ("rows", "declared_success_rows", "declared_not_successful_rows", "result_unknown_rows",
              "attempted_rows", "not_attempted_rows", "failed_attempt_rows", "attempt_unknown_rows",
              "success_with_attempt_id", "success_attempt_unknown", "receipt_evidence_declared_rows",
              "routine_declared_success_rows")
    grouped = {}
    for item in accepted.values():
        grouped.setdefault((item["event_id"], item["phase"], item["channel"]), set()).add(item["attempt_id"])
    duplicates = [{"event_id": event, "phase": phase, "channel": channel, "attempt_ids": sorted(ids),
                   "excess_acceptances": len(ids) - 1}
                  for (event, phase, channel), ids in sorted(grouped.items()) if len(ids) > 1 and phase in {"active", "recovery"}]
    labelled_events = set().union(*root_causes.values()) if root_causes else set()
    recurrence = [{"root_cause_id": cause, "event_ids": sorted(ids), "recurrences": len(ids) - 1}
                  for cause, ids in sorted(root_causes.items()) if len(ids) > 1]
    return {"scope": "operations_and_unclassified_all_groups", "dataset": "unknown", "evidence_scope": "unknown",
            "verification_scope": "explicit_ledger_statistics_only", "populations": dict(populations),
            "channels": {name: dict({k: c[k] for k in fields},
                                   distinct_known_attempts=len(channel_attempts.get(name, set())),
                                   distinct_known_successful_attempts=len(channel_successes.get(name, set())))
                         for name, c in sorted(channels.items())},
            "known_event_ids": sorted(events), "known_attempt_ids": sorted(attempts),
            "event_references": refs_seen, "uncertainties": problems,
            "successful_event_deliveries": sorted(accepted.values(), key=lambda item: (item["ts"], item["attempt_id"], item["channel"])),
            "duplicate_event_acceptances": duplicates,
            "root_cause_recurrence": {"known_recurrences": recurrence, "unlabelled_event_ids": sorted(events - labelled_events),
                                      "coverage": "unknown" if not events or events - labelled_events else "labelled_inputs_only",
                                      "caveat": "只计同声明根因下不同event数减一，不证明修复因果/关闭再发；缺标签不等于0复发，同key不是root cause。"},
            "same_key_new_events": [{"key": key, "event_ids": sorted(ids)} for key, ids in sorted(event_keys.items()) if len(ids) > 1],
            "independently_received": None, "all_attempts_covered": False, "pass": None,
            "caveats": ["旧alert群口径独立保留；移至report不减少本账渠道条数。",
                        "channels=true仅为发送侧声明成功，不是独立收件证明；status不作发送判据。",
                        "不同事件引用及merged_count不增加消息/attempt数；缺ID不推测。",
                        "旧成功台账可能遗漏全失败attempt；仅显式输入文件，不证明全部渠道覆盖。"]}


def all_groups_view(paths: list[Path], days: list[str], *, cutoff: datetime | None = None) -> dict:
    """只读已有台账；同 inode 只读一次，不按 key/内容跨文件消重。"""
    coverage, records, seen = [], [], {}
    bad_total = 0
    for raw_path in paths:
        path = raw_path.absolute()
        info = {"path": str(path), "status": "missing", "records_scanned": 0,
                "bad_lines": 0, "observed_date_range": None, "rows_in_window": 0}
        coverage.append(info)
        try:
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen:
                info.update(status="duplicate_physical_file", duplicate_of=seen[identity])
                continue
            seen[identity] = str(path)
            rows, bad, _ = load_records(path, all_groups=True)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            info.update(status="unreadable", error=str(exc))
            continue
        dates = sorted(ts.date().isoformat() for r in rows
                       if (ts := parse_ts(r.get("ts"))) is not None)
        info.update(status="read" if rows or bad else "empty", records_scanned=len(rows),
                    bad_lines=bad, observed_date_range=[dates[0], dates[-1]] if dates else None,
                    rows_in_window=sum(d in days for d in dates))
        bad_total += bad
        if cutoff is not None:
            info["after_cutoff_rows"] = sum(bool(ts and ts > cutoff) for r in rows if (ts := parse_ts(r.get("ts"))))
            rows = [r for r in rows if not (ts := parse_ts(r.get("ts"))) or ts <= cutoff]
        records.extend(rows)

    totals = {g: _group_counts() for g in ALL_GROUPS}
    daily = {d: {g: _group_counts() for g in ALL_GROUPS} for d in days}
    uncertainties = []
    undated = outside = 0
    for rec in records:
        ts = parse_ts(rec.get("ts"))
        day = ts.date().isoformat() if ts else None
        if day is not None and day not in daily:
            outside += 1
            continue
        reasons = []
        if day is None:
            undated += 1
            reasons.append("unparseable_ts_not_assigned_to_window")
        raw_group = rec.get("group")
        group = raw_group if isinstance(raw_group, str) and raw_group in ALL_GROUPS[:-1] else "unknown"
        if group == "unknown":
            reasons.append("unknown_or_missing_group")
        kind, evidence = operations_kind(rec)
        if kind == "unknown":
            reasons.append(evidence)
        tier = rec.get("tier")
        if (not isinstance(tier, str)
                or tier not in {"critical", "warning", "info", "notice", "digest", "subscribe", "agent_done", "ops"}):
            reasons.append("unknown_or_missing_tier")
        channels = rec.get("channels")
        feishu = channels.get("feishu") if isinstance(channels, dict) else None
        delivery = ("feishu_sent" if feishu is True else
                    "feishu_not_successful" if feishu is False else "feishu_unknown")
        if delivery == "feishu_unknown":
            reasons.append("unknown_or_missing_feishu_delivery")
        merged = rec.get("merged_count")
        merged_valid = type(merged) is int and merged >= 0
        if "merged_count" in rec and not merged_valid:
            reasons.append("invalid_merged_count")
        if reasons:
            uncertainties.append({"ledger": rec["_ledger"], "line": rec["_line"],
                                  "date": day, "group": raw_group,
                                  "subject": rec.get("subject"), "tier": rec.get("tier"),
                                  "noise_class": rec.get("noise_class"),
                                  "source": rec.get("source"), "kind": kind, "reasons": reasons})
        if day is None:
            continue
        for groups in (totals, daily[day]):
            bucket = groups[group]
            bucket["ledger_rows"] += 1
            bucket["no_data"] = False
            if kind in {"unknown", "business"}:
                bucket[f"{kind}_rows"] += 1
                continue
            for counts in (bucket["operations"], bucket["by_kind"].setdefault(kind, _delivery_counts())):
                counts["rows"] += 1
                counts[delivery] += 1
                if merged_valid:
                    counts["declared_merged_slots"] += merged
                elif "merged_count" not in rec:
                    counts["merged_count_missing_rows"] += 1
                else:
                    counts["merged_count_invalid_rows"] += 1

    rows_in_window = sum(g["ledger_rows"] for g in totals.values())
    incomplete = (bool(uncertainties) or bool(bad_total)
                  or any(c["status"] in {"missing", "unreadable", "empty"} for c in coverage))
    status = "no_data" if not rows_in_window else "partial" if incomplete else "observed"
    return {
        "view": "all_groups_operations", "date_range": [days[0], days[-1]],
        "data_status": status, "no_data": not rows_in_window,
        "coverage": {"scope": "explicit_ledgers_only", "all_trees_verified": False,
                     "ledgers": coverage, "records_scanned": len(records),
                     "skipped_bad_lines": bad_total, "undated_rows": undated,
                     "outside_window_rows": outside},
        "groups": totals, "days": [{"date": d, "groups": daily[d]} for d in days],
        "uncertainties": uncertainties, "current_unresolved_incidents": None,
        "outbound_account": outbound_account(records, days),
        "caveats": [
            "历史通知记录/声明 merged 槽位均不是独立事故数；不推断当前未恢复故障。",
            "feishu=false 仅表示未成功，不区分未选择/未配置/发送失败；缺字段为未知。",
            "全渠道失败通常不入本台账；未入账、摘要 buffer、消息正文不在读取范围。",
            "merged_count 缺失不代表实际并入零条；各类 rows 是台账记录数，feishu_sent 才是成功投递数。",
            "仅覆盖列出的文件/日期；不同物理文件即使 key/内容相同仍分别计数。",
            "补充视图不作健康/PASS 判定；旧 alert 0~3 噪音判定不变。",
        ],
        "rc": 0 if status == "observed" else 2,
    }


def render_all_groups(payload: dict) -> str:
    lines = [f"全群运维通知补充视图 {payload['date_range'][0]} ~ {payload['date_range'][1]}",
             f"数据状态：{payload['data_status']}（无健康/PASS 判定）"]
    for info in payload["coverage"]["ledgers"]:
        lines.append(f"台账 {info['path']}：{info['status']}；读取 {info['records_scanned']} 行；"
                     f"文件日期 {info['observed_date_range']}；窗口 {info['rows_in_window']} 行；坏行 {info['bad_lines']}")
    for day in payload["days"] + [{"date": "合计", "groups": payload["groups"]}]:
        lines.append(day["date"])
        for group, bucket in day["groups"].items():
            ops = bucket["operations"]
            lines.append(f"  {group}（{'无台账数据' if bucket['no_data'] else '有台账数据'}）："
                         f"运维记录 {ops['rows']} / 飞书成功 {ops['feishu_sent']} / "
                         f"未成功 {ops['feishu_not_successful']} / 投递未知 {ops['feishu_unknown']}；"
                         f"声明 merged 槽位 {ops['declared_merged_slots']} "
                         f"(未声明 {ops['merged_count_missing_rows']} / 非法 {ops['merged_count_invalid_rows']})；"
                         f"业务 {bucket['business_rows']} / 未知分类 {bucket['unknown_rows']}")
            for kind, counts in bucket["by_kind"].items():
                lines.append(f"    {kind}：记录 {counts['rows']} / 飞书成功 {counts['feishu_sent']} / "
                             f"未成功 {counts['feishu_not_successful']} / 未知 {counts['feishu_unknown']}")
    lines.append(f"无法归日 {payload['coverage']['undated_rows']} 行；不确定记录 {len(payload['uncertainties'])} 行")
    for item in payload["uncertainties"]:
        lines.append(f"  {item['ledger']}:{item['line']} {item['subject']!r} → {', '.join(item['reasons'])}")
    lines.extend(payload["caveats"])
    account = payload["outbound_account"]
    lines.append("严格补充账（不改变旧尺子/不判PASS）：事件ID "
                 f"{len(account['known_event_ids'])} / attemptID {len(account['known_attempt_ids'])}")
    for name, counts in account["channels"].items():
        lines.append(f"  {name}：声明成功 {counts['declared_success_rows']} / "
                     f"已尝试失败 {counts['failed_attempt_rows']} / attempt未知 {counts['attempt_unknown_rows']}")
    lines.append(f"严格账不确定记录 {len(account['uncertainties'])}；独立收件=unknown")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="噪音计数尺子：某天/某窗口飞书告警群(alert)的机制噪音 vs 真故障条数")
    ap.add_argument("--date", default=None,
                    help="窗口末日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--days", type=int, default=1,
                    help="向前回看天数（1=只看 --date 当天；N=窗口 N 天，含末日）")
    ap.add_argument("--ledger", default=None,
                    help="台账路径（默认 $REPO/data/alerts/alert_ledger.jsonl）")
    ap.add_argument("--json", action="store_true", dest="as_json", help="机读 JSON 输出")
    ap.add_argument("--all-groups", action="store_true", help="只读全群运维通知补充视图（不判 PASS）")
    ap.add_argument("--extra-ledger", action="append", default=[],
                    help="补充台账路径，可重复；仅与 --all-groups 一起使用，不自动扫描其他树")
    args = ap.parse_args(argv)

    day = args.date or date.today().isoformat()
    try:
        end = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        print(f"[alert_noise_count] --date 需 YYYY-MM-DD，收到：{day}", file=sys.stderr)
        return 2
    if args.days < 1:
        print(f"[alert_noise_count] --days 需 >= 1，收到：{args.days}", file=sys.stderr)
        return 2
    days = [(end - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]

    path = Path(args.ledger) if args.ledger else default_ledger_path()
    if args.extra_ledger and not args.all_groups:
        ap.error("--extra-ledger 需与 --all-groups 一起使用")
    if args.all_groups:
        payload = all_groups_view([path] + [Path(p) for p in args.extra_ledger], days)
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.as_json
              else render_all_groups(payload))
        return payload["rc"]
    exists = path.exists()
    if not exists:
        print(f"[alert_noise_count] 台账不存在，无数据（不判 PASS）：{path}", file=sys.stderr)
    records, bad, bad_subject = load_records(path)
    if bad:
        print(f"[alert_noise_count] 跳过 {bad} 行无法解析的台账行", file=sys.stderr)
    if bad_subject:
        print(f"[alert_noise_count] 跳过 {bad_subject} 行 group=alert 但缺 subject 的台账行"
              f"（无法判别事件身份，按坏行计）", file=sys.stderr)

    res = classify_rows(records, days)
    if res["skipped_undated_alert_rows"]:
        print(f"[alert_noise_count] {res['skipped_undated_alert_rows']} 行 group=alert 但 ts "
              f"解析不了，无法归日，已跳过（不计入任何一天）", file=sys.stderr)
    payload = {
        "date": days[-1],
        "date_range": [days[0], days[-1]],
        "ledger": str(path),
        "ledger_exists": exists,
        "no_data": (not exists) or res["totals"]["no_data"],
        "noise_max": NOISE_MAX,
        "days": res["days"],
        "totals": res["totals"],
        "repeat_caveat": REPEAT_CAVEAT,
        "warn_untagged": res["warn_untagged"],
        "skipped_bad_lines": bad + bad_subject,
        "skipped_undated_alert_rows": res["skipped_undated_alert_rows"],
        "records_scanned": len(records),
        "diverted": count_diverted(records, days),
    }

    # 退出码三态（#321）：无数据 = 测不了(2)，超阈值 = FAIL(1)，达标 = PASS(0)。
    # 与 PASS 判定同源（totals.pass），避免机检读 rc 和人读 PASS 两套口径分叉。
    if payload["no_data"] or payload["totals"]["pass"] is None:
        rc = 2
    elif payload["totals"]["pass"]:
        rc = 0
    else:
        rc = 1
    payload["rc"] = rc

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(payload))
    return rc


if __name__ == "__main__":
    sys.exit(main())
