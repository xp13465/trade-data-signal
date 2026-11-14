#!/usr/bin/env python
"""NAV 发布 journal 自愈步(2026-11-14 B 批, NAV 发布自动恢复接线)。

挂在 scripts/fund_nav_upload_async.sh 主链 rc 判定之后、exit 之前, 只做三件事:

  ① 状态可见: 只读扫描 data/.r2-protected/*.json(SafeWriter 主 journal, 不新造第二套
     状态库), 输出状态分布摘要 + 未决键投影(对象域/业务日期/来源轮次/代次/hash/失败阶段/
     首次未决时间/已重试次数; 字段由 r2_safe_write.prepare 落盘, 旧 row 缺字段按 None 投影)。
  ② 自动恢复: journal 存在 unknown 键 ⇒ 恰好调用一次既有 `upload_r2.py recover-protected`
     (env R2_RECOVER_AUTO=1 自动模式: 幂等/零删除/全走既有键锁+共享工作预算; 每对象重试
     上限 3 且超龄只报不试; 拒绝旧输出覆盖新输出由 CAS if-match 412 天然保证)。
     preparing 不重试(下一轮同通道正常上传重建 journal 自愈, 设计报告 ③ 状态矩阵)。
  ③ 积压事件: 超期(business_date ≤ T-1 的非 confirmed 键, 或首次未决 >24h)⇒ 恰一条
     可行动事件(notify.py --dedup-key nav_pending_overdue --dedup-window 21600, 6h 窗内
     不重复首报); 同一事件不按尝试次数刷屏。恢复判据 = journal 全部 confirmed(unknown
     不得直接清绿; rc=0/HTTP 200 只是过程信号), 恢复后只对已通知事件发一次恢复通知。

不阻断主链: 本脚本任何内部失败只打日志, 退出码恒 0(主链 rc 由调用方保留)。
不做的: 不重写 upload_r2 主流程 / 不改 SafeWriter 协议 / 不扩大单次超时 / 不新增无限重试。

作用范围(2026-11-15 审查 F15 显式声明): journal 根 data/.r2-protected/ 是**全站受保护键共用**
(SafeWriter 主 journal, 除 fund_nav 的 nav_bucket/ 外还有 nextday_plan/overfit-pair 等)。
本脚本不按前缀过滤: ①自动恢复调用的是既有 recover-protected, 对全部 unknown 键走同一套
键锁+CAS 安全路径(与人工执行同一个命令), 不新增覆盖面; ②超期事件的对象范围按实际键域
(domain_of)逐条列出, 正文不用「fund_nav journal」误标 —— 本步主责是 NAV 发布键, 非 NAV
受保护键一并可见/可恢复属设计取舍(声明不隐藏)。

已知口径偏差(P1-4, 二选一取「接交易日历」+ 缺历回退声明): 自动重试龄上限「超 3 业务日」
的业务日计数以 data/trade_dates.txt 交易日历为准(排周末+节假日, 与 app.calendar 同源);
**日历缺失/覆盖不到目标日期时回退只排周末**(节假日周会提前耗尽 3 业务日 ⇒ 提前只报不试,
仍由超期事件兜底告警, 不影响正确性)。超期判定里 business_date 的比较仍用**日历日**
(「漏过任一日即视为跨轮」), 与龄上限的交易日口径分工不同, 刻意不合并。

老 row 兜底(审查 F8): 过渡期遗留的 unknown 行可能缺 business_date/first_unresolved_at,
此时用 journal 文件 mtime 作为「首次未决」兜底, 超过 24h 照样进超期事件; 半写/损坏 journal
(state=unreadable)同样按 mtime 兜底, 保证坏文件不静默失告警。

preparing 跨日常驻(审查 F16, 人工处置路径): 自动模式永不重试 preparing(设计: 下轮同通道正常
上传会重建 journal 自愈)。若某键已不再产出(永远停在 preparing), 恢复通知会一直 withheld;
人工处置 = 确认该键确实无需发布后, 用既有 `python scripts/upload_r2.py recover-protected`
人工模式核验(不限次数), 或让该通道下一轮上传把它覆盖为 confirmed; 事件正文「需人工动作」
一行给出同一命令。

工作预算(审查 P1-3): 自动恢复子进程注入 R2_UPLOAD_WORK_TIMEOUT(默认 600s, 见
RECOVER_WORK_BUDGET; 与 upload_r2 内层工作预算同一套机制), R2 大面积不可达时自愈步有界
退出(rc=124), 不占满下一轮上传锁等待窗口; 自愈步自身仍恒 0, 不改主链 rc。

恢复通知清状态(审查 F5): 只有 send_recovery 返回码 0(真发出)才清状态; 发送失败保留状态,
下次运行重试 —— 恢复信号不因一次发送失败永久丢失。

测试桩: NAV_SELFHEAL_NOW=ISO 冻结时钟; NAV_SELFHEAL_NOTIFY_DRY_RUN=1 → notify 走
--dry-run(零外发, L48); invoke_recover/send_event/send_recovery 为模块级函数可 monkeypatch。
"""
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FMT = "%Y-%m-%dT%H:%M:%SZ"
DEDUP_KEY = "nav_pending_overdue"
RECOVERY_DEDUP_KEY = "nav_pending_overdue_recovered"
DEDUP_WINDOW = 21600  # 6h, 与 with_lock 排队超时同档(设计报告 D3)
STATE_FILE = "data/.nav_autorecover_state.json"  # 运行时状态(已通知事件), 不进 git
OVERDUE_UNRESOLVED_HOURS = 24
RECOVER_WORK_BUDGET = "600"   # 自愈步内层工作预算秒(P1-3): upload_r2 的 R2_UPLOAD_WORK_TIMEOUT 同一机制


def _now():
    injected = os.environ.get("NAV_SELFHEAL_NOW")
    if injected:
        return datetime.datetime.strptime(injected, FMT)
    return datetime.datetime.utcnow()


def journal_root(repo):
    """SafeWriter 主 journal 根(与 r2_safe_write.SafeWriter.root 同源派生, 不另造路径)。"""
    return Path(repo) / "data" / ".r2-protected"


def _journal_mtime(path):
    """journal 文件 mtime → UTC ISO 串(F8 兜底: 老 row 缺时间字段时的「首次未决」代理)。"""
    try:
        return datetime.datetime.utcfromtimestamp(path.stat().st_mtime).strftime(FMT)
    except OSError:
        return None


def scan_journal(repo):
    """只读扫描主 journal(排除 gc-manifest); 坏文件如实入列不吞。

    每行附 `_journal_mtime`(文件 mtime, UTC ISO): 老 row 缺 business_date /
    first_unresolved_at 时的超期兜底, 也是坏文件(state=unreadable)唯一的年龄信号。
    """
    rows = []
    root = journal_root(repo)
    if not root.is_dir():
        return rows
    for path in sorted(root.glob("*.json")):
        if path.name == "gc-manifest.json":
            continue
        mtime = _journal_mtime(path)
        try:
            row = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            row = {"key": f"<unreadable:{path.name}>", "state": "unreadable",
                   "unreadable_error": str(exc)}
        if not isinstance(row, dict):
            row = {"key": f"<unreadable:{path.name}>", "state": "unreadable",
                   "unreadable_error": f"顶层非对象({type(row).__name__})"}
        row["_journal_mtime"] = mtime
        rows.append(row)
    return rows


def domain_of(key):
    parts = str(key).split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else str(key)


def project(row):
    """未决键投影(对象域/业务日期/来源轮次/代次/hash/失败阶段/首次未决时间/已重试次数)。"""
    return {"domain": domain_of(row.get("key", "")),
            "key": row.get("key"),
            "state": row.get("state"),
            "status": row.get("status"),
            "business_date": row.get("business_date"),
            "source_channel": row.get("source_channel"),
            "generation": row.get("generation"),
            "sha256": row.get("sha256"),
            "first_unresolved_at": row.get("first_unresolved_at"),
            "retry_count": row.get("retry_count", 0)}


def log_distribution(tag, rows):
    dist = {}
    for r in rows:
        dist[r.get("state", "?")] = dist.get(r.get("state", "?"), 0) + 1
    print(f"[nav-journal-selfheal] {tag} journal 状态分布: {json.dumps(dist, sort_keys=True)}")
    for r in rows:
        if r.get("state") != "confirmed":
            print(f"[nav-journal-selfheal] {tag} 未决键: " + json.dumps(project(r), sort_keys=True))
    return dist


def invoke_recover(repo):
    """调用既有 recover-protected(自动模式)。单点函数, 供测试 monkeypatch。

    工作预算(P1-3): 注入 R2_UPLOAD_WORK_TIMEOUT(默认 600s; 调用方若已设别的值则沿用,
    setdefault 不覆盖), 由 upload_r2 内层预算在同一套拦截点上到期退出(rc=124),
    防 R2 大面积不可达时自愈步长时间占锁/拖到下一轮。
    """
    env = dict(os.environ)
    env["R2_RECOVER_AUTO"] = "1"
    env.setdefault("REPO", str(repo))
    env.setdefault("R2_UPLOAD_LOCK_TIMEOUT", "1800")
    env.setdefault("R2_UPLOAD_WORK_TIMEOUT", RECOVER_WORK_BUDGET)
    cmd = [sys.executable, str(Path(repo) / "scripts" / "upload_r2.py"), "recover-protected"]
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def unresolved_since(row):
    """「首次未决」时间: first_unresolved_at 优先, 缺字段时用 journal mtime 兜底(F8)。"""
    fu = row.get("first_unresolved_at")
    if fu:
        try:
            return datetime.datetime.strptime(fu, FMT)
        except ValueError:
            pass
    mt = row.get("_journal_mtime")
    if mt:
        try:
            return datetime.datetime.strptime(mt, FMT)
        except ValueError:
            pass
    return None


def overdue_rows(rows, now):
    """超期判定(设计 D4): business_date ≤ T-1 的非 confirmed 键, 或首次未决 >24h。

    超期条件 ①(业务日期)用**日历日**比较(漏过任一日即视为跨轮);条件 ②(年龄)用小时,
    输入取 first_unresolved_at, 缺字段(过渡期老 row / 坏文件)取 journal mtime 兜底。
    """
    out = []
    for r in rows:
        if r.get("state") == "confirmed":
            continue
        bd = r.get("business_date")
        if bd:
            try:
                bdate = datetime.date.fromisoformat(bd)
            except ValueError:
                bdate = None
            if bdate and bdate < now.date():  # 早于今天 ⇒ business_date ≤ T-1
                out.append((r, "business_date_overdue"))
                continue
        started = unresolved_since(r)
        if started and (now - started).total_seconds() > OVERDUE_UNRESOLVED_HOURS * 3600:
            reason = ("unresolved_over_24h" if r.get("first_unresolved_at")
                      else "journal_mtime_over_24h")
            out.append((r, reason))
    return out


def _notify_cmd(repo, subject, body, dedup_key, severe, prefix, alert_issue):
    cmd = [sys.executable, str(Path(repo) / "scripts" / "notify.py"), subject, body,
           "--dedup-key", dedup_key, "--dedup-window", str(DEDUP_WINDOW)]
    if severe:
        cmd.append("--severe")
    if prefix:
        cmd += ["--from-prefix", prefix]
    if alert_issue:
        cmd += ["--alert-issue", alert_issue]
    if os.environ.get("NAV_SELFHEAL_NOTIFY_DRY_RUN") == "1":
        cmd.append("--dry-run")
    return cmd


def send_event(repo, subject, body):
    """超期事件单点(一条可行动事件)。供测试 monkeypatch。"""
    return subprocess.run(_notify_cmd(repo, subject, body, DEDUP_KEY,
                                      severe=True, prefix="[告警]",
                                      alert_issue="NAV 发布未决积压超期"),
                          capture_output=True, text=True)


def send_recovery(repo, subject, body):
    """恢复通知单点(只对已通知事件发一次, 非告警不写 latest.md)。供测试 monkeypatch。"""
    return subprocess.run(_notify_cmd(repo, subject, body, RECOVERY_DEDUP_KEY,
                                      severe=False, prefix="[恢复]", alert_issue=None),
                          capture_output=True, text=True)


def _load_state(repo):
    path = Path(repo) / STATE_FILE
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return state if state.get("event") == DEDUP_KEY else None


def _write_state(repo, now, keys):
    path = Path(repo) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps({"event": DEDUP_KEY,
                               "notified_at": now.strftime(FMT),
                               "overdue_keys": keys}, sort_keys=True))
    os.replace(tmp, path)


def _clear_state(repo):
    (Path(repo) / STATE_FILE).unlink(missing_ok=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = REPO
    if "--root" in argv:
        repo = Path(argv[argv.index("--root") + 1])
    now = _now()
    try:
        rows = scan_journal(repo)
        log_distribution("扫描", rows)
        unknown = [r for r in rows if r.get("state") == "unknown"]
        if unknown:
            # 门控: 仅 journal 存在 unknown 才调用(设计 D2; preparing 留给下一轮正常上传自愈)。
            # 逐对象上限/超龄/计数由 upload_r2 自动模式单点裁决, 此处不重复第二份判定逻辑。
            print(f"[nav-journal-selfheal] 检测到 unknown 键 {len(unknown)} 个, 调用一次 recover-protected(自动模式)")
            result = invoke_recover(repo)
            print(f"[nav-journal-selfheal] recover-protected rc={result.returncode}(失败不阻断主链)")
            if result.stdout:
                print("\n".join(result.stdout.splitlines()[-10:]))
            if result.returncode != 0 and result.stderr:
                print("\n".join(result.stderr.splitlines()[-10:]))
            rows = scan_journal(repo)
            log_distribution("恢复后", rows)
        else:
            print("[nav-journal-selfheal] 无 unknown 键, 零调用(门控生效)")
        overdue = overdue_rows(rows, now)
        state = _load_state(repo)
        if overdue:
            keys = sorted(r.get("key", "?") for r, _ in overdue)
            reasons = sorted({reason for _, reason in overdue})
            if state and (now - datetime.datetime.strptime(state["notified_at"], FMT)).total_seconds() <= DEDUP_WINDOW:
                print(f"[nav-journal-selfheal] 超期持续 {len(overdue)} 键, 6h 去重窗内不重复首报")
            else:
                starts = [s for s in (unresolved_since(r) for r, _ in overdue) if s]
                oldest = min(starts).strftime(FMT) if starts else "?"
                domains = sorted({domain_of(r.get("key", "")) for r, _ in overdue})
                confirmed = sum(1 for r in rows if r.get("state") == "confirmed")
                subject = "[告警] NAV 发布未决积压超期"
                body = (f"受保护对象 journal 存在超期未决对象 {len(overdue)} 个(原因: {','.join(reasons)})。"
                        f"<br>对象范围: {', '.join(domains)} {keys}(journal 为全站受保护键共用根, 非 NAV 键一并列出)"
                        f"<br>保留版本: journal 已 confirmed {confirmed}/{len(rows)}"
                        f"<br>数据年龄: 最早未决 {oldest}"
                        f"<br>需人工动作: cd {repo} && python scripts/upload_r2.py recover-protected(人工模式不限次数); "
                        f"超龄/超重试上限的键不会被自动重试, 需人工核验。")
                send_event(repo, subject, body)
                _write_state(repo, now, keys)
                print(f"[nav-journal-selfheal] 超期事件已发(恰一条, dedup-key={DEDUP_KEY} window={DEDUP_WINDOW}s)")
        elif state:
            unresolved = [r.get("key") for r in rows if r.get("state") != "confirmed"]
            if not rows:
                # P1-1(2026-11-15 审查): 空 journal 不是「全部 confirmed」。0/0 清绿 = 假恢复
                # (根目录配错/扫描树不对时立刻误报), 一律 withheld 且状态保留。
                print("[nav-journal-selfheal] journal 为空(0/0), 无法判定恢复, 恢复通知 withheld, 状态保留")
            elif unresolved:
                # 恢复判据: journal 非空且全部 confirmed(unknown 不得直接清绿; rc=0 不是发布凭证)。
                states = sorted({r.get("state") for r in rows if r.get("state") != "confirmed"})
                hint = ("; preparing 跨日常驻时自动恢复永不重试 —— 确认该键无需发布后按"
                        " recover-protected 人工模式核验" if "preparing" in states else "")
                print(f"[nav-journal-selfheal] 超期条件已消失但仍有非 confirmed 键 {len(unresolved)} 个"
                      f"(状态: {','.join(str(s) for s in states)}), 恢复通知 withheld{hint}")
            else:
                res = send_recovery(repo, "[恢复] NAV 发布未决积压已清",
                                    f"受保护对象 journal 已全部 confirmed({len(rows)}/{len(rows)}), 此前超期事件恢复。")
                if getattr(res, "returncode", 1) == 0:
                    _clear_state(repo)
                    print("[nav-journal-selfheal] 恢复通知已发(只对已通知事件发一次), 状态已清")
                else:
                    # F5: 发送失败不占「已恢复」——状态保留, 下次运行重试, 恢复信号不丢。
                    print(f"[nav-journal-selfheal] 恢复通知发送失败 rc={getattr(res, 'returncode', '?')}, "
                          f"状态保留, 下次运行重试")
    except Exception as exc:  # 不阻断主链: 自愈步任何内部失败只留日志
        print(f"[nav-journal-selfheal] 自愈步内部异常(不阻断主链): {type(exc).__name__}: {exc}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
