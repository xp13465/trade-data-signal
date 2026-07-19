#!/usr/bin/env python3
"""check_nt_signals.py - 检测汪汪队(ETF国家队)当日信号 + 共振 + 发邮件通知。

查询 etf_national_team.db 的 etf_signal 表最新日信号，后端聚合共振
(复用前端 THR={surge:2,outflow:2,volume:3} 阈值，12只宽基同日同步异动=国家队共振)，
复用 check_signals.py 邮件机制(SMTP 163->QQ, config/email.json)。

ETF份额T+1发布：交易所盘后次日发布，20:07采集通常到T-1，标题注明数据日期避免误导。

用法:
  python scripts/check_nt_signals.py                  # 最新数据日
  python scripts/check_nt_signals.py --date 20260717  # 指定日期
  python scripts/check_nt_signals.py --no-send        # 仅打印不发邮件(测试用)

由 scripts/etf_national_team_backfill.sh 在 daily 采集后调用，第一时间通知。
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# 复用 check_signals.py 邮件机制（SMTP 163->QQ, config/email.json, 不硬编码密码）
from check_signals import load_email_config, send_email  # noqa: E402

from app.collector.etf_national_team import ETF_BY_CODE, DB_PATH as NT_DB_PATH  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("check_nt_signals")

# 共振阈值（与前端 app.js:3178 THR 一致）：≥N只宽基同日同步异动=国家队共振
THR = {"surge": 2, "outflow": 2, "volume": 3}

# 信号类型 -> 中文标签
SIG_LABEL = {
    "share_surge": "进",
    "share_outflow": "出",
    "volume_surge": "量",
}
SIG_COLOR = {  # 邮件表格用色（与前端 pin 配色一致）
    "share_surge": "#e6492e",
    "share_outflow": "#2e8b57",
    "volume_surge": "#ff9800",
}
# 展示顺序：进 -> 出 -> 量
SIG_ORDER = ["share_surge", "share_outflow", "volume_surge"]


def query_nt_signals(date: str | None = None) -> tuple[str, list[dict]]:
    """查询 etf_signal 表指定日信号；date=None 时取最新数据日。

    返回 (data_date, signals)。signals 排除 split_suspect（折算日，非真实信号）。
    """
    if not NT_DB_PATH.exists():
        log.error("etf_national_team.db 不存在：%s", NT_DB_PATH)
        return "", []
    conn = sqlite3.connect(NT_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        if date is None:
            row = conn.execute(
                "SELECT max(date) AS d FROM etf_signal WHERE signal_type!='split_suspect'"
            ).fetchone()
            date = row["d"] if row and row["d"] else ""
            if not date:
                log.warning("etf_signal 表无信号数据")
                return "", []
        rows = conn.execute(
            "SELECT date, etf_code, signal_type, share_change, amount_ratio, intensity, note "
            "FROM etf_signal WHERE date=? AND signal_type!='split_suspect' "
            "ORDER BY signal_type, etf_code",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    return date, [dict(r) for r in rows]


def aggregate_resonance(signals: list[dict]) -> dict:
    """聚合共振：统计各信号类型的 ETF 只数，套 THR 阈值判断是否共振。

    返回 {n_surge, n_outflow, n_volume, resonance:{surge,outflow,volume}, is_resonance}。
    """
    # 每类信号去重 etf_code（同一ETF同日可能同时触发 share_surge + volume_surge，
    # 但同类不会重复因 PK(date,etf_code,signal_type)）
    codes_by_type: dict[str, set] = {"share_surge": set(), "share_outflow": set(), "volume_surge": set()}
    for s in signals:
        st = s["signal_type"]
        if st in codes_by_type:
            codes_by_type[st].add(s["etf_code"])
    n_surge = len(codes_by_type["share_surge"])
    n_outflow = len(codes_by_type["share_outflow"])
    n_volume = len(codes_by_type["volume_surge"])
    res = {
        "surge": n_surge >= THR["surge"],
        "outflow": n_outflow >= THR["outflow"],
        "volume": n_volume >= THR["volume"],
    }
    return {
        "n_surge": n_surge,
        "n_outflow": n_outflow,
        "n_volume": n_volume,
        "resonance": res,
        "is_resonance": any(res.values()),
    }


def _etf_name(code: str) -> str:
    """etf_code -> 易记名（如 510300 -> 300ETF华泰柏瑞）。"""
    info = ETF_BY_CODE.get(code)
    return info[0] if info else code


def _share_yi(sc) -> str:
    """份额变动(份) -> 亿份展示。None 返回 '-'。"""
    if sc is None:
        return "-"
    return f"{sc / 1e8:.2f}"


def _data_date_label(data_date: str) -> str:
    """数据日期标签：ETF份额T+1，标注与今天的差距避免误导。

    返回如 "20260717(T-1数据)" 或 "20260715(今日数据)"。
    """
    if not data_date or len(data_date) < 8:
        return data_date or ""
    today = datetime.now().strftime("%Y%m%d")
    if data_date == today:
        return f"{data_date}(今日数据)"
    try:
        d = datetime.strptime(data_date, "%Y%m%d")
        t = datetime.strptime(today, "%Y%m%d")
        gap = (t - d).days
        return f"{data_date}(T-{gap}数据)"
    except ValueError:
        return data_date


def build_email(data_date: str, signals: list[dict], agg: dict) -> tuple[str, str]:
    """构建邮件主题 + HTML 正文。返回 (subject, html_body)。"""
    label = _data_date_label(data_date)
    n_surge = agg["n_surge"]
    n_outflow = agg["n_outflow"]
    n_volume = agg["n_volume"]
    is_res = agg["is_resonance"]

    # === 标题 ===
    parts = []
    if n_surge:
        parts.append(f"进{n_surge}只")
    if n_outflow:
        parts.append(f"出{n_outflow}只")
    if n_volume:
        parts.append(f"量{n_volume}只")
    summary = " ".join(parts) if parts else "无信号"
    res_tag = " | 🐾共振" if is_res else ""
    subject = f"[汪汪队信号] {label} {summary}{res_tag}"

    # === HTML 正文 ===
    res_banner = ""
    if is_res:
        res_types = []
        if agg["resonance"]["surge"]:
            res_types.append(f"进场≥{THR['surge']}只(实际{n_surge}只)")
        if agg["resonance"]["outflow"]:
            res_types.append(f"离场≥{THR['outflow']}只(实际{n_outflow}只)")
        if agg["resonance"]["volume"]:
            res_types.append(f"放量≥{THR['volume']}只(实际{n_volume}只)")
        res_banner = (
            f'<div style="background:linear-gradient(90deg,#fff8e1,#fff3cd);'
            f'border:2px solid #ffd700;border-radius:8px;padding:12px 16px;margin-bottom:16px;">'
            f'<b style="font-size:16px;color:#b8860b;">🐾 国家队共振信号！</b><br>'
            f'<span style="color:#4e5969;font-size:13px;">'
            f'{"、".join(res_types)}只宽基ETF同日同步异动，疑似国家队集中操作。</span></div>'
        )

    html_parts = [f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:720px;">
<h2 style="margin:0 0 8px 0;color:#1d2129;">🐶 汪汪队信号 - ETF国家队资金动向</h2>
<p style="margin:0 0 16px 0;color:#86909c;font-size:13px;">数据日期 {label} · 共 <b>{len(signals)}</b> 个信号（进 {n_surge} / 出 {n_outflow} / 量 {n_volume}）</p>
{res_banner}"""]

    if not signals:
        html_parts.append('<p style="color:#86909c;">该日无汪汪队信号。</p>')
    else:
        # 信号表格
        html_parts.append("""<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px;">
<thead><tr style="background:#f2f3f5;text-align:left;">
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;">ETF</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:48px;">类型</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;text-align:right;">份额变动(亿份)</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;text-align:right;">量比</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;text-align:right;">z-score</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;">备注</th>
</tr></thead><tbody>""")
        # 按 SIG_ORDER 分组展示
        for sig_type in SIG_ORDER:
            grp = [s for s in signals if s["signal_type"] == sig_type]
            for s in grp:
                name = _etf_name(s["etf_code"])
                lbl = SIG_LABEL.get(sig_type, sig_type)
                color = SIG_COLOR.get(sig_type, "#1d2129")
                note = (s["note"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                z = s["intensity"]
                z_str = f"{z:.2f}" if z is not None else "-"
                ratio = s["amount_ratio"]
                ratio_str = f"{ratio:.2f}倍" if ratio is not None else "-"
                html_parts.append(f"""<tr style="border-bottom:1px solid #f2f3f5;">
<td style="padding:8px 10px;"><b>{name}</b><br><span style="color:#c9cdd4;font-size:11px;">{s['etf_code']}</span></td>
<td style="padding:8px 10px;font-weight:600;color:{color};">{lbl}</td>
<td style="padding:8px 10px;text-align:right;color:{color};">{_share_yi(s['share_change'])}</td>
<td style="padding:8px 10px;text-align:right;">{ratio_str}</td>
<td style="padding:8px 10px;text-align:right;">{z_str}</td>
<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{note}</td>
</tr>""")
        html_parts.append("</tbody></table>")

    # 规则说明 + 免责
    html_parts.append(f"""<div style="background:#f7f8fa;border-radius:6px;padding:12px 16px;margin-bottom:12px;font-size:12px;color:#4e5969;line-height:1.8;">
<div style="font-weight:600;margin-bottom:4px;color:#1d2129;">📋 信号规则</div>
• 进(share_surge)：份额增 + z-score&gt;2 + 量比&gt;1.5（疑似大资金进场）<br>
• 出(share_outflow)：份额减 + z-score&lt;-2 + 量比&gt;1.5（疑似大资金离场）<br>
• 量(volume_surge)：成交额 &gt; 近5日均2倍（放量，独立信号）<br>
• 共振：进/出≥{THR['surge']}只、量≥{THR['volume']}只宽基同日同步异动 = 国家队共振（🐾）<br>
• 注意：这是代理推断，无法100%确认是国家队，份额变动可能来自任何机构/大户申赎
</div>
<div style="background:#f7f8fa;border-radius:6px;padding:12px 16px;font-size:12px;color:#86909c;line-height:1.8;">
<div style="font-weight:600;margin-bottom:4px;color:#1d2129;">⚠️ 免责声明</div>
本信号由历史数据量化生成，仅供研究参考，不构成任何投资建议。<br>
ETF份额为T+1数据（交易所盘后次日发布），20:07采集通常到T-1，次日补全。<br>
市场有风险，投资需谨慎。
</div>
<p style="color:#c9cdd4;font-size:11px;margin-top:16px;">-- 汪汪队ETF国家队资金动向看板 · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>""")

    body = "\n".join(html_parts)
    return subject, body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检测汪汪队(ETF国家队)当日信号 + 共振 + 发邮件")
    parser.add_argument("--date", help="查询日期 YYYYMMDD（默认最新数据日）")
    parser.add_argument("--no-send", action="store_true", help="仅打印不发邮件（测试用）")
    args = parser.parse_args(argv)

    log.info("=== check_nt_signals 开始 ===")
    data_date, signals = query_nt_signals(args.date)
    if not data_date:
        log.info("无汪汪队信号数据，退出")
        return 0

    agg = aggregate_resonance(signals)
    log.info(
        "数据日期=%s 信号数=%d (进=%d 出=%d 量=%d) 共振=%s",
        data_date, len(signals), agg["n_surge"], agg["n_outflow"],
        agg["n_volume"], "是" if agg["is_resonance"] else "否",
    )

    subject, body = build_email(data_date, signals, agg)
    log.info("===== 邮件主题 =====")
    log.info("%s", subject)
    log.info("===== 邮件正文 =====")
    log.info("%s", body)

    if args.no_send:
        log.info("--no-send 模式，跳过实际发送")
        return 0

    cfg = load_email_config()
    if cfg is None:
        log.warning("未配置 config/email.json -- 跳过实际发送（邮件内容已打印到日志）")
        return 0

    # 无信号不发邮件（避免噪音）；共振日必发
    if not signals:
        log.info("无信号，不发邮件")
        return 0

    try:
        send_email(cfg, subject, body)
    except Exception as e:  # noqa: BLE001
        log.error("✗ 邮件发送失败：%s（不阻塞流程）", e)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
