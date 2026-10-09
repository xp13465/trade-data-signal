"""retry_failed_metrics.py - 单项指标失败自动重采(自动修复机制 2026-07-31)。

读 collect_log 当日最新 status=error 的 metric_id,对每个 error 指标调对应
重采函数(collect_snapshot/collect_direct)。成功则 upsert daily_metric + 写
collect_log ok(覆盖 error,让 collect_health 变 ok);失败则保留 error(等下次
self_heal 重试或明日 update_all 兜底)。

触发:self_heal.sh 每15分钟调用(在任务级 force-heal 之前,轻量重采优先)。
非交易日跳过。返回重采结果摘要。

设计要点:
- 复用 fetchers.collect_snapshot/collect_direct(含 2026-07-31 zt_pool 交叉验证修复:
  跌停池空+涨停池有数据=真0跌停,写0+ok,不再误报 error)
- 只重采当日 error 项(不重采历史),避免长跑
- 不受 self_heal 每日3次上限限制(单项重采轻量,不像 force 重跑整个 update_all)
- 重采成功写 collect_log ok + 清旧非 ok 记录,queries.collect_health 取最新一条变 ok
- 重采仍失败保留 error,下次 self_heal(15分钟后)再试,直到成功或当日结束

场景(2026-07-31 7/31 跌停池空事故):
- 17:50 update_all 采 stock_zt_pool_dtgc_em 空,collect_log error
- collect_health level=error,线上小红点
- 18:07 self_heal 调本脚本 -> retry a_width_dt_count -> collect_snapshot 交叉验证
  涨停池99只 -> 跌停池空=真0,写0+ok -> collect_health 变 ok,红点消失

连续失败通知(2026-09-30 资金面 6 源全败被静默成正常缺口盲点根治#3):
- 背景: 2026-09-30 02:37 起 a_fund_main(主力净流入, direct:market_fund_flow 6源串行)重采
  连续失败 17 轮零告警(只 return False 打日志,不 notify, 三层消音叠加的其中一层)。
- 本模块修复: 真实采集类失败(非 no config/disabled/TODO 配置类)连续 >=3 轮 → 调 notify.py
  发邮件+飞书(复用既有通道)。计数跨轮持久化(独立 state 文件 data/retry_failed_metrics_count.json,
  按 mid 计), 达阈值发一次后清零暂歇, 防每轮轰炸(memory alert-dedup-mechanism 同精神)。
- 配置/disabled/no-func 类失败不累计(重试无意义, 告警无价值, 防噪音)。
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

# 定位 REPO(脚本所在目录的父目录)。用 .absolute() 不用 .resolve():
# trade-data/scripts 是 symlink -> trade/scripts,.resolve() 会解析到 trade 致 sys.path 加 trade,
# app.db 加载自 trade/app/db.py 读 trade/data/sentiment.db(滞后镜像,§9 事故根因)。
# .absolute() 不解析 symlink,从 trade-data 跑时 __file__=trade-data/scripts/retry_...,
# parent.parent=trade-data,sys.path 加 trade-data,app.db 读 trade-data/data/sentiment.db(主库)。
_ROOT = Path(__file__).absolute().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# notify_sent 唯一判据(scripts/notify_sent.py)所在目录, 供 import。脚本以
# `python scripts/retry_failed_metrics.py` 跑时 sys.path[0] 已是 scripts/, 此处显式补一次
# 防被当模块导入(cwd=repo 根)时找不到。
_SCRIPTS_DIR = Path(__file__).absolute().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from notify_sent import notify_sent  # noqa: E402

from app.calendar import is_trading_day
from app.collector.base import log_collect
from app.collector.fetchers import load_config, collect_snapshot, collect_direct
from app.collector.runner import upsert_metric, upsert_metrics_many
from app.db import get_conn

# ── 连续失败通知(2026-09-30 资金面 6 源全败盲点根治#3) ──
RETRY_NOTIFY_THRESHOLD = 3        # 重采失败连续 >=3 轮发 notify(防 17 轮静默)
COUNT_FILE = _ROOT / "data" / "retry_failed_metrics_count.json"  # {mid: 当前连续失败轮数}
_CONFIG_FAIL_PREFIX = ("no config", "disabled", "no func")  # 配置类失败不累计(重试也无意义)


def _load_counts() -> dict:
    """读连续失败计数文件(跨轮持久化)。读失败/缺失返回 {}。"""
    try:
        c = json.loads(COUNT_FILE.read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _save_counts(counts: dict) -> None:
    """原子写计数文件(tmp+replace, 防半截被并发 self_heal 读走)。

    2026-10-01 #132 fail-loud 修复: 写失败**直接抛异常**(不再只打日志), main() 捕获后
    置非零退出 → self_heal.sh `|| echo "⚠..."` 分支接管(chain: pipefail → audit log 标记)。
    原实现「失败仅打日志不抛」= 计数永远写不进 → 连续失败永远到不了阈值 → 永久静默,
    正是 #131 要修的病灶(counter 写失败 = 防静默机制本身静默, 同类)。
    """
    COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COUNT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(counts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(COUNT_FILE)


def _notify_count_file_write_fail(e: Exception) -> None:
    """计数文件写失败告警(2026-10-01 #132): 连续失败计数无法持久化 = #131 防静默
    机制本体失效, 必须被告警——只留 audit 日志一行无人主动查=仍静默(教训 L46:
    「latest.md 沉默≠无告警」同精神)。复用 notify.py 通道(邮件+飞书)。

    分级判断: tier warning(非 SEVERE) — 计数盘写失败是本地基础设施故障(权限/磁盘),
    不是数据源故障; 数据级失败仍由内存计数在达阈值瞬间发 _notify_repeat_failure(不依赖
    写盘成功), 数据告警不丢, 故本告警仅需 warning 提醒"防静默机制本体降级"。6h dedup
    对齐 with_lock 排队超时(P2 降噪)惯例, 持久故障最多 ~2-4 封/天, 防轰炸。

    仅写失败时触发; notify 自身失败不阻塞 exit 非0(self_heal `||` 分支仍留 audit 标记)。
    RETRY_NOTIFY_DRY_RUN=1 时走 --dry-run(不真发, 本地自测用, 对齐 with_lock 的
    WITH_LOCK_NOTIFY_DRY_RUN / on_skip_notify.sh 的 ON_SKIP_DRY_RUN 惯例)。
    """
    subject = "[告警][重采计数] 计数文件写失败, 连续失败告警机制失效"
    body = (
        f"<b>retry_failed_metrics 计数文件写失败</b>: <code>{COUNT_FILE}</code><br>"
        f"异常: <code>{e}</code><br>"
        f"影响: 连续失败计数(阈值 {RETRY_NOTIFY_THRESHOLD})无法跨轮持久化,"
        f"#131 防静默机制本体失效——写盘恢复前, 连续失败跨轮累计被打断,"
        f"可能重演 17 轮失败零告警盲点。<br>"
        f"建议: 检查 data/ 目录/磁盘权限或空间, 修复后计数自动恢复。"
    )
    cmd = [sys.executable, str(_ROOT / "scripts" / "notify.py"),
           subject, body, "--tier", "warning", "--from-prefix", "[告警]",
           "--dedup-key", "retry_fm_count_file_write_fail", "--dedup-window", "21600"]
    if os.environ.get("RETRY_NOTIFY_DRY_RUN") == "1":
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[notify] 计数写失败告警退出码 {r.returncode}: {(r.stderr or '')[-200:]}", file=sys.stderr)
            return
        # P3 订正(2026-10-01 #132 复审 2): 旧文案「已发(dedup 6h)」在 dedup suppress 时
        # 照打属误导——主窗口 suppress 不代表本次有送达/入队动作。按 notify.py 实际
        # stderr 区分三态: 真入聚合队列 / 被 dedup 抑制 / buffer 追加失败(未占窗)。
        stderr = r.stderr or ""
        if "dedup 窗口内 suppress" in stderr:
            print(f"[notify] 计数写失败告警已被 dedup 抑制(6h 窗内已处理过, 本次未入队)", flush=True)
        elif "buffer 追加失败" in stderr:
            print(f"[notify] 计数写失败告警 buffer 追加失败(未入队、未占窗, 下轮重试)", flush=True)
        else:
            print(f"[notify] 计数写失败告警已入聚合队列(30min 批发, dedup 6h)", flush=True)
    except Exception as ne:  # noqa: BLE001
        print(f"[notify] 计数写失败告警发送异常(不阻塞, exit 非0 兜底): {ne}", file=sys.stderr)


def _is_collect_failure(msg: str) -> bool:
    """是否真实采集类失败(值得累计告警)。配置类失败(no config/disabled/no func)不累计——重试无意义。"""
    return not (msg or "").startswith(_CONFIG_FAIL_PREFIX)


def _notify_repeat_failure(mid: str, count: int, date: str, msg: str) -> bool:
    """重采连续失败达阈值 → 调 notify.py 发邮件+飞书(复用既有通道, 不另起炉灶)。

    返回**是否真发出**(notify_sent 判据, rc 不可信: notify.py main() 全出口恒 return 0)。
    调用方据此决定是否清零计数(2026-10-09 #241 同族B波): 未送达 ⇒ **不清零** ⇒ 保留计数
    下轮重试; 送达才清零暂歇, 否则「先清零后 fire-and-forget」会让达标告警永久丢失。
    """
    subject = f"[告警][重采失败] {mid} 连续 {count} 轮重采失败"
    body = (f"<b>{mid}</b> 在 <b>{date}</b> 自愈重采(每15min一轮)已连续 <b>{count}</b> 轮失败"
            f"(阈值 {RETRY_NOTIFY_THRESHOLD})。<br>"
            f"最近失败原因: <code>{msg}</code><br>"
            f"这是 2026-09-30 资金面 6 源全败盲区根治#3: 前序 17 轮失败零告警(只 return False 打日志)。<br>"
            f"建议: 查该数据源(fetch_market_fund_flow 等)是否封禁/停服, 必要时手动补采或人工介入。")
    cmd = [sys.executable, str(_ROOT / "scripts" / "notify.py"),
           subject, body, "--from-prefix", "[告警]"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        sent = notify_sent(out)
        if r.returncode != 0:
            print(f"[notify] retry_failed 通知退出码 {r.returncode}: {(r.stderr or '')[-200:]}", file=sys.stderr)
        elif sent:
            print(f"[notify] {mid} 连续 {count} 轮失败已发通知", flush=True)
        else:
            print(f"[notify] {mid} 连续 {count} 轮失败告警**未确认送达** ⇒ 不清零计数, 下轮重试: {out[-200:]}",
                  file=sys.stderr)
        return sent
    except Exception as e:  # noqa: BLE001
        print(f"[notify] retry_fail 通知异常: {e}", file=sys.stderr)
        return False


def get_failed_metrics(date: str) -> list[dict]:
    """读 collect_log 当日最新 status=error 的 metric_id 列表(去重,取最新一条)。

    与 queries.collect_health 同逻辑:ORDER BY run_at DESC,_seen 去重保留最新。
    只返回最新状态为 error 的指标(warn 不进重试:warn 是"已知/降级"告警,重采也
    无济于事,只会像 2026-09-15 那样四轮 "no config" 白转到每日上限)。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT metric_id, status, message FROM collect_log "
            "WHERE run_date=? ORDER BY run_at DESC",
            (date,),
        ).fetchall()
        seen: set[str] = set()
        failed: list[dict] = []
        for r in rows:
            mid = r["metric_id"]
            if mid in seen:
                continue
            seen.add(mid)
            if r["status"] != "error":
                continue
            msg = r["message"] or ""
            # 防空转(2026-09-15):"指数今日数据缺失"是 index_backfill 凌晨补采时
            # 目标日期未开盘导致的三源全空误报(盘中 intraday 反哺后 index_daily
            # 已有当日 close)。复核 index_daily 当日 close,有值则跳过不重试。
            if "指数今日数据缺失" in msg:
                _chk = conn.execute(
                    "SELECT close FROM index_daily WHERE index_id=? AND date=?",
                    (mid, date),
                ).fetchone()
                if _chk and _chk["close"] is not None:
                    continue  # 实际已有数据,跳过陈旧误报
            failed.append({"metric_id": mid, "message": msg})
        return failed
    finally:
        conn.close()


def _clear_old_errors(date: str, mid: str) -> None:
    """清同 run_date 同 metric_id 旧非 ok 记录(让 collect_health 干净,同 backfill_metrics.sh 逻辑)。"""
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM collect_log WHERE run_date=? AND metric_id=? AND status<>?",
            (date, mid, "ok"),
        )
        conn.commit()
    finally:
        conn.close()


def retry_metric(mid: str, date: str, cfg: dict) -> tuple[bool, str]:
    """重采单个指标。返回 (success, msg)。

    复用 collect_snapshot/collect_direct(含 zt_pool 交叉验证修复)。
    成功:upsert daily_metric + 清旧 error + 写 collect_log ok。
    失败:保留原 error(不写新记录,避免 collect_log 膨胀)。
    """
    m = next((x for x in cfg.get("metrics", []) if x.get("id") == mid), None)
    if not m:
        return False, f"no config for {mid}"
    if not m.get("enabled", True):
        return False, f"disabled {mid}"
    func = m.get("func", "")
    if not func or func == "TODO":
        return False, f"no func/TODO {mid}"
    try:
        if func.startswith("direct:"):
            rows, msg = collect_direct(m)
            if rows:
                upsert_metrics_many(mid, rows)
                _clear_old_errors(date, mid)
                log_collect(date, mid, "ok", f"{len(rows)} rows (retry)")
                return True, f"{len(rows)} rows"
            return False, msg or "direct empty"
        # 快照型(含 zt_pool 系列,collect_snapshot 内置交叉验证)
        val, msg = collect_snapshot(m, date)
        if val is not None:
            upsert_metric(date, mid, val)  # source 默认 akshare
            _clear_old_errors(date, mid)
            log_collect(date, mid, "ok", f"{val} (retry: {msg})")
            return True, f"{val} ({msg})"
        return False, msg or "snapshot None"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    today = dt.date.today().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"[retry] 非交易日({today}),跳过", flush=True)
        return 0
    cfg = load_config()
    failed = get_failed_metrics(today)
    if not failed:
        print(f"[retry] {today} 无 error 指标,无需重采", flush=True)
        return 0
    failed_ids = [f["metric_id"] for f in failed]
    print(f"[retry] {today} 发现 {len(failed)} 个 error 指标: {failed_ids}", flush=True)
    ok = fail = 0
    counts = _load_counts()  # 本轮统一加载, 末尾一次性落盘(防并发 self_heal 踩踏计数文件)
    for f in failed:
        mid = f["metric_id"]
        success, msg = retry_metric(mid, today, cfg)
        if success:
            ok += 1
            counts.pop(mid, None)  # 成功清零连续失败计数
            print(f"  [ok] {mid}: {msg}", flush=True)
        else:
            fail += 1
            print(f"  [fail] {mid}: {msg} (原 error: {f['message']})", flush=True)
            if _is_collect_failure(msg):
                n = counts.get(mid, 0) + 1
                if n >= RETRY_NOTIFY_THRESHOLD:
                    # 先通知后落盘(2026-10-01 #132): 阈值告警依赖内存计数, 必须发出,
                    # 不因计数文件写失败被吞(原实现先 _save_counts 再通知, 一旦写失败
                    # 直接冒泡会把本次 _notify_repeat_failure 一起吞掉=双静默)。
                    # 送达才清零(2026-10-09 #241 同族B波): 旧实现「先 counts.pop 后
                    # fire-and-forget」= 先落签(记 已告警)后通知且丢返回值 ⇒ 通道全挂时
                    # 计数已被清零暂歇, 达标告警永久丢失(下轮从 0 重新累计)。改为
                    # 判 notify_sent 返回: 未送达 ⇒ 保留计数下轮重试(不占「已发一次」位)。
                    if _notify_repeat_failure(mid, n, today, msg):
                        counts.pop(mid, None)  # 送达后清零暂歇, 防每轮轰炸(去重)
                    else:
                        counts[mid] = n  # 未送达: 保留计数, 下轮重试(不静默丢告警)
                else:
                    counts[mid] = n  # 未达阈值, 累加后下次再判
            else:
                counts.pop(mid, None)  # 配置类失败不累计(重试无意义)
    # 末尾一次性落盘(fail-loud, 2026-10-01 #132):
    # 原实现「达标路径循环内 + 末尾各写一次」, 注释却写「末尾一次性落盘」, 注释与实现不符。
    # 收敛为仅末尾写: ①写失败须 fail-loud 置非零退出, 循环内预写会让写失败冒泡吞掉阈值
    # 通知(见上), 必须先通知后落盘; ②收敛后少一次 IO、注释与实现一致; ③代价=通知后进程
    # 若被杀致清零未落盘, 后果仅下次多一轮计数(非静默类风险), 可接受。
    try:
        _save_counts(counts)
    except Exception as e:  # noqa: BLE001
        print(f"[retry] 计数文件原子写失败(连续失败告警机制失效, fail-loud): {e}", file=sys.stderr)
        _notify_count_file_write_fail(e)
        return 1
    print(f"=== retry 完成 ok={ok} fail={fail} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
