#!/usr/bin/env python3
"""check_preupload_backup.py — pre-upload 覆盖前备份护栏「存活观测」巡检(#237 D③, 2026-10-10)。

【为什么要它】#237 根因 = 护栏自 10-05 切桶起 100% 失败却**无人察觉**(失败只 print、不阻断、
  不进任何告警链、无观测点 ⇒ §25「备份先于覆盖」实际能力 = 0)。修法 A(客户端中转)上线后,
  仍必须有「护栏是否真在工作」的机器可见性,否则同类静默复发仍无人知(设计文
  docs/ops/237-r2-overwrite-backup-guard-design-20261009.md §4.0 D③ / §5.1 改点 5)。

【判定口径】(自锚定, 不依赖人工断言)
  · landed   = 备份桶 `pre-upload/<YYYYMMDD>/` 前缀对象数(R2 **只读 LIST**, 不采信日志自证)
  · 当日日志里上传通道打的结构化行(由 upload_r2._incremental_upload 输出):
      `[label] 备份完成 copied=X skipped=Y failed=Z`  ⇒ runs/copied/skipped/failed 求和
      `[label] 备份 N/M 已备份 …`(进度行)          ⇒ 候选数锚 = max(M)
  · 判定:
      ① runs == 0                 → OK(NO_RUN): 当日无备份完成记录(未跑/在飞/休市), 不判定不告警
      ② failed != 0               → FAIL: 备份失败(failed=-1 = 备份段整体异常早退, 同判 FAIL)
      ③ claimed(copied+skipped) > 0 且 landed == 0
                                  → FAIL: **护栏空转**(日志自称备了 N 个, R2 上零对象 = 铁证矛盾)
      ④ 其余                       → OK
  方向 fail-closed: 「日志说备了, R2 却说没有」一律报; 但「无记录 / 无待备 key」不报(免噪音)。
    ③ 刻意**不**用候选数(candidates)判: 首次上传的新 key 源侧 404 = 合法"无备份必要",
      那一轮 copied=skipped=0 且 landed=0, 用候选数会每周首次全量假 FAIL。

【告警】--notify 才真发: notify.py --tier warning 入既有聚合队列(schedule_monitor 尾部
  --flush-warnings 统一批发), **--dedup-key preupload_backup_fail --dedup-window 21600**(6h 去重,
  防 15min 周期轰炸)。默认 dry 只打印(自测/手动排查安全, §18 L48 精神: 真发链路先打桩)。
  落签判据 = scripts/notify_sent.py(真实路由结果, 不看 rc; 与 #240 F1 / #241 同实现)。

【输入依赖】--repo(默认按 REPO/GIT_REPO/MAIN_REPO env 候选, 回退本机 trade-data)+ data/logs/。
【输出】stdout 判定行 + exit 0=OK / 1=FAIL / 2=无法判定(R2 或日志不可达)
【dry 单测】--dump JSON({"landed": N, "log_lines": [...]})替代 R2 LIST + 日志扫描 ⇒ 判定纯函数可测。
【用法】
  python3 scripts/check_preupload_backup.py                 # dry 打印, 不告警
  python3 scripts/check_preupload_backup.py --notify        # 真发(入聚合队列)
  python3 scripts/check_preupload_backup.py --dump /tmp/x.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

# absolute() 非 resolve(): 保持 <REPO>/scripts symlink 字面路径, 使子进程 notify.py 的 REPO
# 探测落在与调用方(schedule_monitor flusher)同一棵树(同 check_s06_freshness 先例注释)。
SCRIPT_DIR = Path(__file__).absolute().parent

# 当日日志读取的尾部窗口: 固定名 *_launchd.log 累积全部历史(intraday 实测 11 万行),
# 当日行必在文件尾部 ⇒ 只读尾部 2MiB, 不做全文件扫描(避免无界 IO; 也不用 find)。
_TAIL_BYTES = 2 * 1024 * 1024

_RE_DONE = re.compile(r"备份完成 copied=(\d+) skipped=(\d+) failed=(-?\d+)")
_RE_PROG = re.compile(r"备份 (\d+)/(\d+) 已备份 \d+ 跳过 \d+")

DEFAULT_REPO_CANDIDATES = [
    Path(c) for c in (
        os.environ.get("REPO", ""),
        os.environ.get("GIT_REPO", ""),
        os.environ.get("MAIN_REPO", ""),
        "/Users/linhuichen/code/trade-data",
    ) if c
]
DEFAULT_REPO = next((p for p in DEFAULT_REPO_CANDIDATES if (p / "data" / "logs").exists()),
                    DEFAULT_REPO_CANDIDATES[0])


def parse_log_lines(lines) -> dict:
    """从日志行里汇总 {runs, copied, skipped, failed, candidates}。纯函数(可单测)。"""
    runs = copied = skipped = failed = 0
    max_total = 0
    for ln in lines:
        m = _RE_DONE.search(ln)
        if m:
            runs += 1
            copied += int(m.group(1))
            skipped += int(m.group(2))
            failed += int(m.group(3))
            continue
        m2 = _RE_PROG.search(ln)
        if m2:
            max_total = max(max_total, int(m2.group(2)))
    candidates = max(max_total, copied + skipped)
    return {"runs": runs, "copied": copied, "skipped": skipped,
            "failed": failed, "candidates": candidates}


def scan_today_logs(logs_dir: Path, day: str) -> list:
    """扫当日被写过的 *.log 的**尾部窗口**取行(不整树 grep / 不 find)。"""
    lines = []
    if not logs_dir.exists():
        return lines
    for p in sorted(logs_dir.glob("*.log")):
        try:
            st = p.stat()
        except OSError:
            continue
        if datetime.date.fromtimestamp(st.st_mtime).strftime("%Y%m%d") != day:
            continue
        try:
            with open(p, "rb") as f:
                size = st.st_size
                if size > _TAIL_BYTES:
                    f.seek(size - _TAIL_BYTES)
                    f.readline()   # 丢弃可能被截半的首行
                data = f.read()
        except OSError:
            continue
        lines.extend(data.decode("utf-8", errors="replace").splitlines())
    return lines


def count_landed(ur, day: str) -> int:
    """备份桶 `pre-upload/<day>/` 对象数(R2 只读 LIST)。

    **不直接复用 ur._list_keys**:后者对非 200 **吞掉返回 [])**(打印一行 ⚠ 后 return out),
    若 R2 临时不可达,`landed=0` 会被判成「护栏空转」假 FAIL —— 巡检自身网络抖动不该惊动用户。
    故先做一次 max-keys=1 探针确认通道可用(非 200 ⇒ 抛错 ⇒ 上层 exit 2 无法判定,不告警),
    再用 _list_keys 拿**全量分页计数**(复用 #126 的续页逻辑,不重造轮子)。
    """
    prefix = f"pre-upload/{day}/"
    st, data = ur.s3_request("GET", "",
                             query=f"list-type=2&prefix={quote(prefix, safe='')}&max-keys=1",
                             bucket=ur.BACKUP_BUCKET)
    if st != 200:
        raise RuntimeError(f"备份桶 LIST 探针失败 status={st} {data[:200]!r}")
    return len(ur._list_keys(prefix, bucket=ur.BACKUP_BUCKET))


def judge(landed: int, stat: dict) -> tuple:
    """返回 (rc, verdict, msg)。判定口径见模块 docstring(纯函数, 可单测)。

    ③ 的判据用「日志自称(claimed=copied+skipped) vs R2 实见(landed)」而非「候选数 vs landed」:
      候选数(candidates)只说明"这一轮有 N 个待备 key",**不代表应当落地** —— 首次上传的
      新 key 源侧 HEAD 404(无备份必要)是合法常态 ⇒ 那一轮 copied=skipped=0 且 landed=0,
      用候选数判会**每周首次全量必假 FAIL**。claimed>0 而 landed==0 才是铁证矛盾(§5.2-7
      「不许只看日志自证」)。
    """
    if stat["runs"] == 0:
        return 0, "NO_RUN", (f"当日无备份完成记录(未跑/过渡期/在飞; landed={landed}), 不判定")
    if stat["failed"] != 0:
        return 1, "FAIL", (f"备份失败 failed={stat['failed']} (copied={stat['copied']} "
                           f"skipped={stat['skipped']} runs={stat['runs']}, landed={landed})")
    claimed = stat["copied"] + stat["skipped"]
    if claimed > 0 and landed == 0:
        return 1, "FAIL", (f"护栏空转: 日志自称已备份 {claimed} 个(copied={stat['copied']} "
                           f"skipped={stat['skipped']})但备份桶 pre-upload 零对象 —— "
                           f"日志与 R2 实测矛盾(§5.2-7 不许只看日志自证)")
    return 0, "OK", (f"护栏正常: copied={stat['copied']} skipped={stat['skipped']} failed=0 "
                     f"claimed={claimed} candidates={stat['candidates']} landed={landed} "
                     f"runs={stat['runs']}")


def do_notify(subject: str, detail: str) -> bool:
    """真发(--notify); 落签判据 = notify_sent(真实路由结果, 不看 rc)。异常一律返回 False。"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from notify_sent import notify_sent  # noqa: E402
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "notify.py"), subject,
             detail.replace("\n", "<br>"),
             "--tier", "warning", "--from-prefix", "[告警·聚合]",
             "--dedup-key", "preupload_backup_fail", "--dedup-window", "21600"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        sent = notify_sent(out)
        if not sent:
            print(f"[preupload] notify.py 未真发出(rc={proc.returncode}), 下轮重试: "
                  f"{out.strip()[-200:]}", file=sys.stderr)
        return sent
    except Exception as e:  # noqa: BLE001
        print(f"[preupload] notify 异常(下轮重试): {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="pre-upload 覆盖前备份护栏存活观测(#237 D③)")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="数据仓根(含 data/logs)")
    ap.add_argument("--day", default=None, help="查证日 YYYYMMDD(默认今天)")
    ap.add_argument("--logs-dir", default=None, help="日志目录(默认 <repo>/data/logs)")
    ap.add_argument("--notify", action="store_true", help="FAIL 时真发(入聚合队列; 默认 dry)")
    ap.add_argument("--dump", default=None,
                    help="自测桩: JSON {'landed': N, 'log_lines': [...]}(替代 R2 LIST + 日志扫描)")
    args = ap.parse_args()

    day = args.day or datetime.date.today().strftime("%Y%m%d")
    repo = Path(args.repo)
    logs_dir = Path(args.logs_dir) if args.logs_dir else repo / "data" / "logs"

    if args.dump:
        try:
            dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
            landed = int(dump["landed"])
            lines = list(dump.get("log_lines", []))
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"PREUPLOAD_ERROR dump 不可用: {type(e).__name__}: {e}")
            return 2
    else:
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            import upload_r2 as ur  # noqa: E402  (顶层 load_env; 云上 unit 有 EnvironmentFile)
            landed = count_landed(ur, day)
        except Exception as e:  # noqa: BLE001
            print(f"PREUPLOAD_ERROR R2 LIST 不可达(备份桶={ur_bkt_hint()}): {type(e).__name__}: {e}")
            return 2
        if not logs_dir.exists():
            print(f"PREUPLOAD_ERROR 日志目录不存在: {logs_dir}")
            return 2
        lines = scan_today_logs(logs_dir, day)

    stat = parse_log_lines(lines)
    rc, verdict, msg = judge(landed, stat)
    print(f"PREUPLOAD_{verdict} day={day} {msg}")

    if rc == 1 and args.notify:
        ok = do_notify(f"pre-upload 覆盖前备份护栏异常({verdict})",
                       f"day={day} {msg}。pre-upload 为 §25「备份先于覆盖」的唯一回滚层, "
                       f"护栏失效=覆盖不可逆。查 upload_r2.py _backup_overwritten_keys 与当日通道日志。")
        if ok:
            print("[preupload] 告警已入聚合队列", file=sys.stderr)
    return rc


def ur_bkt_hint() -> str:
    """尽力给出桶名提示(不引入 import 失败依赖)。"""
    return os.environ.get("R2_BACKUP_BUCKET") or os.environ.get("R2_BACKUP2_BUCKET") or "?"


if __name__ == "__main__":
    sys.exit(main())