#!/usr/bin/env python3
"""check_preupload_backup.py — pre-upload 覆盖前备份护栏「存活观测」巡检(#237 D③, 2026-10-10)。

【为什么要它】#237 根因 = 护栏自 10-05 切桶起 100% 失败却**无人察觉**(失败只 print、不阻断、
  不进任何告警链、无观测点 ⇒ §25「备份先于覆盖」实际能力 = 0)。修法 A(客户端中转)上线后,
  仍必须有「护栏是否真在工作」的机器可见性,否则同类静默复发仍无人知(设计文
  docs/ops/237-r2-overwrite-backup-guard-design-20261009.md §4.0 D③ / §5.1 改点 5)。

【判定口径】
  · landed = 查询日备份桶 pre-upload/<YYYYMMDD>/ 对象数(R2 只读 LIST)。
  · 日志按备份入口 day/run_id 配对完成行；旧格式按备份前缀日期或标准任务开始轮次。
    入口日期是 helper 选定的实际备份目录日期，跨午夜完成也不挪到次日；绝不依赖 mtime。
  · failed 只累计非负失败数，负值单独计 exceptions，任意一次异常均不能被成功/失败相抵。
  · 当日失败、历史未解决错误、日期未知错误任一存在 ⇒ FAIL；后续成功不自动解除历史错误。
    历史事件保留日期、轮次、通道和失败样本，与当日计数分开。PhaseA 是否阻断上传不在本脚本修改。
  · 可靠当前轮次边界之前、同日志族的旧无日期纯成功另列审计；未知日期错误不随边界清除。
  · 其余无日期完成记录或日志读取失败 ⇒ UNKNOWN(exit 2)，不能报护栏正常。
  · 无完成记录 ⇒ NO_RUN；当日 claimed(copied+skipped)>0 而 landed==0 ⇒ FAIL(护栏空转)。
    候选数不参与空转判据：新 key 源侧 404 可合法无备份。
  · 全量流式读取留存 *.log 及数字轮换(.log.1/.log.2.gz)，不裁尾丢弃旧错；
    已被外部日志保留策略永久删除的事件无法重建，本检查器不是永久事故账本。

【告警】--notify 才真发: notify.py --tier warning 入既有聚合队列(schedule_monitor 尾部
  --flush-warnings 统一批发), **--dedup-key preupload_backup_fail --dedup-window 21600**(6h 去重,
  防 15min 周期轰炸)。默认 dry 只打印(自测/手动排查安全, §18 L48 精神: 真发链路先打桩)。
  落签判据 = scripts/notify_sent.py(真实路由结果, 不看 rc; 与 #240 F1 / #241 同实现)。

【输入依赖】--repo(默认按 REPO/GIT_REPO/MAIN_REPO env 候选, 回退本机 trade-data)+ data/logs/。
【输出】stdout 判定行 + exit 0=OK/NO_RUN / 1=FAIL / 2=无法判定(日期/日志/R2 证据不足)
【dry 单测】--dump JSON({"landed": N, "log_lines": [...]})替代 R2 LIST + 日志扫描 ⇒ 判定纯函数可测。
【用法】
  python3 scripts/check_preupload_backup.py                 # dry 打印, 不告警
  python3 scripts/check_preupload_backup.py --notify        # 真发(入聚合队列)
  python3 scripts/check_preupload_backup.py --dump /tmp/x.json
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import os
os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))  # #245 批2 W1: 台账 source 溯源
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

# absolute() 非 resolve(): 保持 <REPO>/scripts symlink 字面路径, 使子进程 notify.py 的 REPO
# 探测落在与调用方(schedule_monitor flusher)同一棵树(同 check_s06_freshness 先例注释)。
SCRIPT_DIR = Path(__file__).absolute().parent

# 完成行本身不带日期；只信备份入口、备份目标日期或标准任务轮次，绝不借 mtime/普通日志时间。
_RE_DONE = re.compile(r"备份完成 copied=(\d+) skipped=(\d+) failed=(-?\d+)")
_RE_PROG = re.compile(r"备份 (\d+)/(\d+) 已备份 \d+ 跳过 \d+")
_RE_BEGIN = re.compile(r"备份开始 day=(\d{8}) run_id=([\w-]+)")
_RE_BANNER = re.compile(r"^=== (\S+) (开始|结束).*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_RE_LABEL = re.compile(r"^\[([^]]+)\] ")
_RE_TARGET = re.compile(r"将被覆盖 key -> \S+/pre-upload/(\d{8})/")
_RE_LOG_FILE = re.compile(r"^(.*\.log)(?:\.(\d+))?(\.gz)?$")

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
    """从日志行里汇总 {runs, copied, skipped, failed, exceptions, candidates}。纯函数(可单测)。"""
    runs = copied = skipped = failed = exceptions = 0
    max_total = 0
    for ln in lines:
        m = _RE_DONE.search(ln)
        if m:
            runs += 1
            copied += int(m.group(1))
            skipped += int(m.group(2))
            value = int(m.group(3))
            failed += max(0, value)
            exceptions += int(value < 0)
            continue
        m2 = _RE_PROG.search(ln)
        if m2:
            max_total = max(max_total, int(m2.group(2)))
    candidates = max(max_total, copied + skipped)
    return {"runs": runs, "copied": copied, "skipped": skipped,
            "failed": failed, "exceptions": exceptions, "candidates": candidates}


def _dated_log_events(lines, source):
    """同一日志族(含轮换)顺序解析；普通 INFO 时间和结束时间不能给下一条事件授时。"""
    scopes, channels, ordinals = [], {}, {}
    events, end_days = [], {}
    for number, ln in enumerate(lines, 1):
        banner = _RE_BANNER.search(ln)
        if banner:
            name, action, stamp = banner.groups()
            if action == "开始":
                # 同名新轮次替换未正常结束的旧轮次；pipeline 可嵌套在 shell 轮次内。
                for i, scope in enumerate(scopes):
                    if scope[0] == name:
                        del scopes[i:]
                        break
                scopes.append((name, stamp))
            else:
                for i in range(len(scopes) - 1, -1, -1):
                    if scopes[i][0] == name:
                        for scope in scopes[i:]:
                            end_days[scope] = stamp[:10].replace("-", "")
                        del scopes[i:]
                        break
            channels.clear()
            continue
        label_match = _RE_LABEL.match(ln)
        if not label_match and not (_RE_DONE.search(ln) or _RE_PROG.search(ln)):
            continue
        label = label_match.group(1) if label_match else "unknown-channel"
        begin = _RE_BEGIN.search(ln)
        if begin:
            channels[label] = {"day": begin[1], "run_id": begin[2], "rows": [], "exact": True}
            continue
        if "R2_BYTES_TOTAL=" in ln:
            channels.pop(label, None)   # 新上传调用，不能继承上一批的目标日期。
            continue
        if not (_RE_DONE.search(ln) or _RE_PROG.search(ln) or _RE_TARGET.search(ln)
                or "备份失败样本" in ln or "覆盖前备份异常" in ln):
            continue
        context = channels.setdefault(label, {"day": None, "run_id": None, "rows": [], "exact": False})
        context["rows"].append(ln.rstrip())
        target = _RE_TARGET.search(ln)
        if target and not context["exact"]:
            context["day"] = target[1]  # 旧格式跨午夜时，以实际备份前缀日期为准。
        if not _RE_DONE.search(ln):
            continue
        stage_day = context["day"]
        legacy_scope = None
        run_id = context["run_id"]
        if not context["exact"]:
            scope = scopes[-1] if scopes else None
            if stage_day is None and scope:
                legacy_scope = scope
                stage_day = scope[1][:10].replace("-", "")  # 旧格式按开始轮次归属。
            ordinal_key = (scope, label)
            ordinals[ordinal_key] = ordinals.get(ordinal_key, 0) + 1
            run_id = f"legacy:{scope}:{label}:{ordinals[ordinal_key]}"
            if scope is None:
                run_id += f":{source}:{number}"
        try:
            datetime.datetime.strptime(stage_day or "", "%Y%m%d")
        except ValueError:
            stage_day = None
        events.append({"day": stage_day, "run_id": run_id, "label": label, "source": source,
               "_legacy_scope": legacy_scope,
               "line": number, "stat": parse_log_lines(context["rows"]),
               "samples": [row for row in context["rows"]
                           if "备份失败样本" in row or "覆盖前备份异常" in row]})
        channels.pop(label, None)
    for event in events:
        scope = event.pop("_legacy_scope")
        if scope and scope in end_days and end_days[scope] != event["day"]:
            # 旧格式仅有外层开始日且运行跨日，无法推断备份阶段是哪天；不冒充精确日期。
            event["day"] = None
        yield event


def scan_today_logs(logs_dir: Path, day: str) -> dict:
    """流式扫描完整留存日志及数字轮换(含 gzip)，不按 mtime、不裁尾静音历史错误。

    返回当日统计 + 历史/日期未知失败证据。后续成功不能证明旧版本备份已恢复，故不自动解除。
    日志被外部保留策略永久移除后本函数无法重建其证据；不声称它是永久事故账本。
    """
    stat = parse_log_lines([])
    stat.update(current_failures=[], historical_failures=[], undated_failures=[],
                prior_undated_successes=[], undated_runs=0, log_errors=[])
    families = {}
    for path in sorted(logs_dir.iterdir()):
        match = _RE_LOG_FILE.match(path.name)
        if match and path.is_file():
            families.setdefault(match[1], []).append((int(match[2] or 0), path))
    seen = set()
    for family, parts in families.items():
        pending_undated_successes = []

        def rows():
            # log.2(.gz) -> log.1 -> log，允许开始标记和完成行落在相邻轮换文件。
            for _, path in sorted(parts, reverse=True):
                try:
                    opener = gzip.open if path.suffix == ".gz" else open
                    with opener(path, "rt", encoding="utf-8", errors="replace") as stream:
                        yield from stream
                except (OSError, EOFError) as exc:
                    stat["log_errors"].append(f"{path}: {type(exc).__name__}")
        for event in _dated_log_events(rows(), family):
            if event["day"] == day and pending_undated_successes:
                # 同一日志族中可靠当前轮次之前的无日期纯成功，只留作审计。
                # 在镜像去重之前推进覆盖边界；任何未知日期错误均不进入此队列。
                stat["prior_undated_successes"].extend(pending_undated_successes)
                stat["undated_runs"] -= len(pending_undated_successes)
                pending_undated_successes.clear()
            identity = (event["run_id"], event["label"])
            if identity in seen:
                continue  # 同一精确 run_id 或相同旧轮次的 tee 镜像，只计一次。
            seen.add(identity)
            event_stat = event["stat"]
            if event["day"] == day:
                for key in ("runs", "copied", "skipped", "failed", "exceptions"):
                    stat[key] += event_stat[key]
                stat["candidates"] = max(stat["candidates"], event_stat["candidates"])
            elif event["day"] is None:
                stat["undated_runs"] += 1
                if not event_stat["failed"] and not event_stat["exceptions"]:
                    pending_undated_successes.append(event)
            if event_stat["failed"] or event_stat["exceptions"]:
                if event["day"] == day:
                    stat["current_failures"].append(event)
                elif event["day"] is None:
                    stat["undated_failures"].append(event)
                elif event["day"] < day:
                    stat["historical_failures"].append(event)
    stat["candidates"] = max(stat["candidates"], stat["copied"] + stat["skipped"])
    return stat


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
    current = (f"failed={stat['failed']} exceptions={stat.get('exceptions', 0)} "
               f"copied={stat['copied']} skipped={stat['skipped']} runs={stat['runs']} landed={landed}")
    historical = stat.get("historical_failures", [])
    undated = stat.get("undated_failures", [])
    evidence = []
    for title, events in (("当日", stat.get("current_failures", [])),
                          ("历史未解决", historical), ("日期未知", undated)):
        if events:
            evidence.append(f"{title}备份错误 " + json.dumps(events, ensure_ascii=False))
    if stat["failed"] != 0 or stat.get("exceptions", 0) or evidence:
        return 1, "FAIL", "备份失败 " + current + ("; " + "; ".join(evidence) if evidence else "")
    if stat.get("undated_runs", 0) or stat.get("log_errors"):
        return 2, "UNKNOWN", (f"日期/日志证据不完整 {current} "
                              f"undated_runs={stat.get('undated_runs', 0)} "
                              f"log_errors={stat.get('log_errors', [])}")
    if stat["runs"] == 0:
        return 0, "NO_RUN", (f"当日无备份完成记录(未跑/过渡期/在飞; landed={landed}), 不判定")
    claimed = stat["copied"] + stat["skipped"]
    if claimed > 0 and landed == 0:
        return 1, "FAIL", (f"护栏空转: 日志自称已备份 {claimed} 个(copied={stat['copied']} "
                           f"skipped={stat['skipped']})但备份桶 pre-upload 零对象 —— "
                           f"日志与 R2 实测矛盾(§5.2-7 不许只看日志自证)")
    prior_successes = stat.get("prior_undated_successes", [])
    return 0, "OK", (f"护栏正常: copied={stat['copied']} skipped={stat['skipped']} failed=0 exceptions=0 "
                     f"claimed={claimed} candidates={stat['candidates']} landed={landed} "
                     f"runs={stat['runs']} prior_undated_successes="
                     f"{json.dumps(prior_successes, ensure_ascii=False)}")


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
    try:
        datetime.datetime.strptime(day, "%Y%m%d")
    except ValueError:
        print(f"PREUPLOAD_ERROR 无效查询日: {day}")
        return 2
    repo = Path(args.repo)
    logs_dir = Path(args.logs_dir) if args.logs_dir else repo / "data" / "logs"

    if args.dump:
        try:
            dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
            landed = int(dump["landed"])
            lines = list(dump.get("log_lines", []))
            # dump 是显式提供的同轮测试桩；线上输入必须走日期解析。
            stat = parse_log_lines(lines)
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
        try:
            stat = scan_today_logs(logs_dir, day)
        except OSError as e:
            print(f"PREUPLOAD_ERROR 日志不可读: {type(e).__name__}: {e}")
            return 2
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