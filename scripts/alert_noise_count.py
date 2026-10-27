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
    本脚本是量具：永远 exit 0（不因 FAIL 非零退出，避免误伤调用方；参数错误才 exit 2）。

用法
    python scripts/alert_noise_count.py --date 2026-10-27
    python scripts/alert_noise_count.py --date 2026-10-27 --days 7
    python scripts/alert_noise_count.py --date 2026-10-27 --json
    python scripts/alert_noise_count.py --ledger /path/to/alert_ledger.jsonl
默认台账 = $REPO/data/alerts/alert_ledger.jsonl（REPO 缺省 = 本仓库根），
与 scripts/alert_meter.py / notify.py:_ledger_path() 同一约定，不写死任何机器路径。
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

ROOT = Path(__file__).resolve().parent.parent
LEDGER_REL = Path("data") / "alerts" / "alert_ledger.jsonl"

# 用户拍板阈值：机制噪音 0~3 条/天（真故障不设上限）。
NOISE_MAX = 3

# repeat 判定窗口（规格 ★6：同一 (tier, 归一化 subject) 在 24h 内已出现过）。
REPEAT_WINDOW = timedelta(hours=24)

ALERT_GROUP = "alert"

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


def load_records(path: Path) -> tuple[list[dict], int, int]:
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
            for raw in f:
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
                if (str(rec.get("group") or "") == ALERT_GROUP
                        and not str(rec.get("subject") or "").strip()):
                    bad_subject += 1
                    continue
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
    }

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())