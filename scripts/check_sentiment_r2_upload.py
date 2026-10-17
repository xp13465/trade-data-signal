#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_sentiment_r2_upload.py — #231 H1:盘中链尾收口「sentiment R2 上传连续失败」→ SEVERE

【病灶 / 为什么需要它】(2026-10-17,依据 /tmp/decide-pack-report.md §8 + b4a §6)
  `app/collector/intraday_snapshot.py::_export_affected_json`(主流程 L2631 调)对 6 个
  `EXPORT_RANGES` 各起一个子进程 `upload_r2.py upload <local> data/sentiment-{rng}.json`;
  失败走两路之一:
    ① 正常路径 `_ok < _total` → `log_collect(..., "sentiment_r2_upload", "error", ...)`
    ② 异常路径(子进程 timeout / 读文件失败)→ 同上 log_collect error
  而 `scripts/upload_r2.py` 的 `cmd_upload` 失败改 **rc=1**(#231 H3,2026-10-17;此前静默
  exit 0,只 `print ✗`)——采集层判据 `intraday_snapshot.py:2183`(`returncode == 0 and "✓" in
  stdout`)对 rc 变化不敏感(失败早已走 else),故采集层行为不变、**仍不发外发**;
  且 `sentiment_r2_upload` 全仓**无任何告警消费者** ⇒ 失败只剩 UI 数据健康度小红点,
  monitor 十维均不覆盖。残余静默窗 = `sentiment-3y/5y/all` 三个单文件
  (3m/6m/1y 另有 `upload-intraday` 通道、失败走 SEVERE,已覆盖)。
  ⇒ 本脚本 = H1「链尾收口」:由链作者 `scripts/intraday_snapshot.sh` 在**链尾**调用,
  不进采集层(采集层只管落 log_collect,告警出口归链)。

【阈值依据(实测数据分布,2026-10-17 云上只读普查)】
  · 云上盘中轮日志(990 个)统计:`sentiment R2上传 6/6` **1070 次成功** / `0/6` **22 轮失败**
    / `sentiment R2上传异常` **4 次**。**失败是双峰** —— 要么全成功、要么全失败(0/6),
    **无任何部分失败(如 5/6)样本** ⇒ 「同轮失败个数」这一维度**无判别力**
    (任何失败都等于 0/6),照它发告警 = 单轮抖动也发 = 噪声。
  · 失败轮时间线:单轮失败且下一轮自愈的 **5 例**(20260812 / 0928_2035 / 0929_1315 /
    1013_1405 / 1015_2035,后 3 例是上面的「异常」形态);**长连败 1 例**
    (20261016 09:25→15:35 **连 21 轮** + 当日 20:35)。⇒ **真故障判别维度 = 持续性(连续轮数)**,
    不是单轮严重度。
  · 故阈值 = **连续 M 轮失败(M 默认 3 ≈ 30 分钟)**;单轮 / 两轮失败**不发**
    (10min 自愈 + 17:50 日链兜底已覆盖该形态,见 #231 缓解说明)。
    降噪纪律(CLAUDE.md 精神 + memory `alert-denoise-keep-fault-discriminator`):
    **保留「持续失败」这个真故障判别维度**,只把「自愈性单轮抖动」排除 ——
    不是把判别维度降没,而是换成有判别力的那个维度。

【口径(写清,免歧义)】
  · **连续** = 同一自然日内、按轮日志文件名(`intraday_snapshot_YYYYMMDD_HHMM.log`)降序
    向前走,**遇到第一个非失败轮(成功/中性/无法判定)即停**;跨日**不累加**(每日从 0 起算,
    R2 故障跨夜属另一故障域,由 check_r2_consistency 等承接)。
  · **失败** = 该轮日志里 `[intraday] sentiment R2上传 x/y` 且 `x < y`(取最后一次出现),
    或出现 `[intraday] sentiment R2上传异常`(异常路径,计数未知,记 1 轮失败)。
  · **中性** = `x/y` 且 `y == 0`(本地无 sentiment 文件可传,非上传失败,也非成功)→ 停走。
  · **无法判定** = 日志里两种记号都无(该轮没跑到该段)→ 停走(fail-safe:不累加、不发)。
  · **恢复**:连续失败中断即 streak=0;**不发「恢复」通知**(与同脚本既有 3 条 SEVERE 模板
    同口径:恢复由下一轮成功自动体现,免恢复轰炸)。
  · **去重**:沿用同脚本模板 `--dedup-key intraday_sentiment_r2_upload_fail --dedup-window 1800`
    (30min 窗口:持续故障每 ~30min 最多一条,与同域兄弟一致;跨通道聚合归 #264b)。
  · **不阻塞**:恒 exit 0(链尾钩子,绝不影响采集链退出码)。

【四元组声明(#264 包3 件F 硬要求,缺一不上线)】
  默认 tier = critical(`--severe`) / dedup window = 1800s /
  聚合域 = `r2`(与 intraday_snapshot.sh 同域,登记表 docs/ops/alert-checker-registry-20261015.md
  §2.1 #21 同族) / 首报策略 = 首报必达(新 key 直发,不受预算抑制)。
  证据用例见 `scripts/tests/test_231_sentiment_r2_upload_alert_20261017.py`。

【无 now() 依赖】判定只用**日志文件名里的日期**与日志正文,不读系统日期 ⇒ 不受「跨天变红」
  一类时敏陷阱影响(CLAUDE.md §18 L51);打印行的 `ALERT_TIME` 仅装饰。

【用法】
  scripts/check_sentiment_r2_upload.py --log <本轮日志> [--logdir <轮日志目录>]
                                       [--rounds 3] [--notify <notify.py 路径>] [--notify-send] [--dry-run]
  缺省 **dry**:只判定 + 打印,不发外发(需真发须显式 `--notify-send`);
  `--dry-run` 追加传 notify.py --dry-run(#184:notify.py --dry-run 全渠道只 print、零落盘)。
"""
from __future__ import annotations

import argparse
import os
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))  # #245 批2 W1: 台账 source 溯源
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# absolute() 非 resolve(): 保持 <repo>/scripts symlink 字面路径,
# 使子进程 notify.py 的 REPO 探测落在与调用方(intraday_snapshot.sh)同一棵树(同 check_s06_freshness)。
SCRIPT_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPT_DIR))
from notify_sent import notify_state  # noqa: E402  #241 判据唯一实现(不看 rc;三态 sent/suppressed/failed)

ROUND_LOG_RE = re.compile(r"^intraday_snapshot_(\d{8})_(\d{4})\.log$")
OK_RE = re.compile(r"\[intraday\] sentiment R2上传 (\d+)/(\d+)")
EXC_RE = re.compile(r"\[intraday\] sentiment R2上传异常")

DEDUP_KEY = "intraday_sentiment_r2_upload_fail"
DEDUP_WINDOW = "1800"
DEFAULT_ROUNDS = 3

FAIL, NEUTRAL, UNKNOWN, OK = "fail", "neutral", "unknown", "ok"


def parse_round_log(text: str) -> tuple[str, str]:
    """单轮日志 → (判定, 明细)。判定 ∈ {fail, neutral, ok, unknown}。

    优先级:① 异常记号(该轮子进程抛错,`x/y` 汇总行不会打印)② `x/y` 汇总行(取最后一次)。
    """
    if EXC_RE.search(text):
        return FAIL, "异常"
    hits = OK_RE.findall(text)
    if not hits:
        return UNKNOWN, "无记号"
    ok, total = (int(v) for v in hits[-1])
    if total == 0:
        return NEUTRAL, f"{ok}/{total}(无可传文件)"
    if ok < total:
        return FAIL, f"{ok}/{total}"
    return OK, f"{ok}/{total}"


def _round_logs(logdir: Path, date: str) -> list[Path]:
    """同一天、命名匹配的轮日志,按名(≈时间)降序 —— 排除 intraday_snapshot_launchd.log 等汇总日志。"""
    if not logdir.is_dir():
        return []
    out = []
    for p in logdir.iterdir():
        m = ROUND_LOG_RE.match(p.name)
        if m and m.group(1) == date:
            out.append(p)
    return sorted(out, key=lambda p: p.name, reverse=True)


def compute_streak(logdir: Path, date: str, rounds: int) -> tuple[int, str]:
    """连续失败轮数(同一天、由新到旧,遇非失败即停)。返回 (streak, 末轮明细)。"""
    logs = _round_logs(logdir, date)
    if not logs:
        return 0, "无轮日志"
    last_detail = ""
    streak = 0
    for i, p in enumerate(logs):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        state, detail = parse_round_log(text)
        if i == 0:
            last_detail = detail
        if state != FAIL:
            break
        streak += 1
        if streak >= rounds:
            break
    return streak, last_detail


def _send_alert(notify_py: Path, subject: str, body: str, dry_run: bool) -> tuple[str, str]:
    """调 notify.py 发 SEVERE。返回 (三态判定 sent/suppressed/failed, 输出尾部)。

    判据用 notify_state(唯一实现),**不看 rc** —— notify.py 各出口恒 return 0;
    suppressed = dedup 窗口内已发过(成功且已知,非失败,勿当未发出重试)。
    """
    cmd = [
        sys.executable, str(notify_py), subject, body,
        "--severe", "--from-prefix", "[告警]",
        "--dedup-key", DEDUP_KEY, "--dedup-window", DEDUP_WINDOW,
    ]
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as e:  # noqa: BLE001
        return "failed", f"notify 异常: {type(e).__name__} {e}"
    out = (r.stdout or "") + (r.stderr or "")
    return notify_state(out), out.strip()[-300:]


def main() -> int:
    ap = argparse.ArgumentParser(description="#231 H1 链尾收口:sentiment R2 上传连续失败 → SEVERE")
    ap.add_argument("--log", required=True, help="本轮日志(intraday_snapshot_YYYYMMDD_HHMM.log)")
    ap.add_argument("--logdir", default=None, help="轮日志目录(默认取 --log 所在目录)")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                    help=f"连续失败轮数阈值(默认 {DEFAULT_ROUNDS})")
    ap.add_argument("--notify", default=str(SCRIPT_DIR / "notify.py"), help="notify.py 路径(测试可指桩)")
    ap.add_argument("--notify-send", action="store_true", help="真发(缺省只判定 + 打印,不发外发)")
    ap.add_argument("--dry-run", action="store_true",
                    help="追加传 notify.py --dry-run(全渠道只 print、零落盘)")
    args = ap.parse_args()

    log = Path(args.log).absolute()
    logdir = Path(args.logdir).absolute() if args.logdir else log.parent
    m = ROUND_LOG_RE.match(log.name)
    if not m:
        print(f"[sentiment-r2-check] 非法轮日志名(非 intraday_snapshot_YYYYMMDD_HHMM.log): {log.name}",
              file=sys.stderr)
        return 0  # 不阻塞链
    date = m.group(1)

    streak, last_detail = compute_streak(logdir, date, args.rounds)
    fired = streak >= args.rounds
    print(f"[sentiment-r2-check] date={date} streak={streak}/{args.rounds} 末轮={last_detail} "
          f"alert={'yes' if fired else 'no'}", flush=True)
    if not fired:
        return 0

    alert_time = datetime.now().strftime("%m-%d %H:%M")
    subject = f"[告警] intraday sentiment R2上传连续失败 {streak} 轮 {alert_time}"
    body = (
        f"sentiment-3m/6m/1y/3y/5y/all 的 R2 上传在 {date} **连续 {streak} 轮失败**"
        f"(末轮 {last_detail})。该单点此前只有 UI 小红点、无告警消费者(#231),"
        f"残余静默窗 = sentiment-3y/5y/all(前端读旧数据)。<br>"
        f"排查:① R2 凭证/权限(403 NotEntitled?)② R2 上传锁竞争 ③ 单文件过大"
        f"<br>本地补刷: bash scripts/upload_r2.py upload <local> data/sentiment-<rng>.json"
        f"<br>日志: {log}"
    )
    if not args.notify_send:
        print(f"[sentiment-r2-check] dry(未传 --notify-send): 应发 subject={subject}", flush=True)
        return 0

    state, tail = _send_alert(Path(args.notify).absolute(), subject, body, args.dry_run)
    print(f"[sentiment-r2-check] notify 判定={state} tail={tail}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())