#!/usr/bin/env python3
"""feishu_missed_fetch.py - 飞书漏收消息补拉（P0-2 / TASKS㉟「漏收消息 API 拉回」）。

背景：飞书长连接（receive_v1 实时推送）断线/重启窗口期间，群消息飞书不补推→窗口消息
永久丢失。本脚本用飞书 im/v1/messages 列表 API 按时间窗口拉各群最近消息，对比已落盘去重
（data/feishu_requests/*.json + forwarded/autodone jsonl），找出断线窗口丢失的消息，
补落盘 + 进 TASKS 待办 + 回执开发群（可选）。

两条运行路径：
  1) 独立 CLI：bash scripts/feishu_missed_fetch.py [--dry-run] [--window-hours N] ...
  2) feishu_ws_listener.py 启动时自动执行一次（补拉重启窗口，best-effort 不阻塞监听）。

权限：需要应用有 im:message 读权限（能拉群消息列表）；无权限时脚本明确报错，
不误报"已补拉"（宁可告警不漏）。

去重口径与 process_event 一致：白名单（开发）群人类用户消息接收；报告群真需求接收
（纯闲聊不落盘）；告警群仅带需求前缀接收；bot 自己/系统消息一律不接收（防循环/防把
自己发的告警回执当需求）。

用法:
  python scripts/feishu_missed_fetch.py [--dry-run] [--window-hours 24]
                                        [--start-ms <ms>] [--end-ms <ms>] [--no-receipt]
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# 复用 listener 的配置/凭证/落盘/进TASKS/意图过滤等实现（同一链路同一口径）
from feishu_ws_listener import (  # noqa: PLC0415
    AUTODONE_DEDUP_PATH,
    FORWARD_DEDUP_PATH,
    _get_tenant_access_token,
    _load_autodone_ids,
    _load_forwarded_ids,
    _mark_autodone,
    _match_prefix,
    append_todo_to_tasks,
    content_plain,
    is_chitchat,
    load_config,
    load_env,
    log,
    send_receipt,
    summarize,
)

REPO = Path(__file__).absolute().parent.parent
FEISHU_API_BASE = "https://open.feishu.cn"
# 补拉游标：记录上次检查到的时间点（ms），下次从该点继续，断线/重启窗口=游标→now
CURSOR_PATH = REPO / "data" / "feishu_requests" / "missed_fetch_cursor.json"
# API 分页大小（飞书 im/v1/messages 列表，默认 50/页）
PAGE_SIZE = 50


def _feishu_http_get_json(url: str, headers: dict, timeout: int = 15) -> dict:
    """GET JSON 到飞书 API。本地 MITM 代理自签证书致默认校验失败时，
    遇到 CERTIFICATE_VERIFY_FAILED 退化为不校验重试一次（仅飞书 API 调用）。"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        log("补拉：飞书 SSL 校验失败，退化为不校验重试一次（本地 MITM 代理）")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _get_token() -> str | None:
    """复用 listener 的 tenant_access_token 获取（含缓存）。失败返回 None。"""
    return _get_tenant_access_token()


def _load_cursor() -> int:
    try:
        if CURSOR_PATH.exists():
            return int(json.loads(CURSOR_PATH.read_text(encoding="utf-8"))
                       .get("last_checked_ms", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _save_cursor(ms: int) -> None:
    try:
        CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        CURSOR_PATH.write_text(
            json.dumps({"last_checked_ms": int(ms), "updated_ts": int(time.time())},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"补拉：游标写入失败（不阻塞）：{e}")


def _known_message_ids(inbox_dir: Path) -> set:
    """已落盘去重集合：inbox *.json + *.processed.json + forwarded/autodone jsonl 全部 message_id。

    注意：*.pending.json（P0-1 异常落盘待补拉文件）**不占去重位**——missed_fetch 需从 API
    找到该消息补落盘为正式记录（pending 只作证据+告警线索）。"""
    ids: set = set()
    if inbox_dir and inbox_dir.exists():
        try:
            for p in inbox_dir.glob("*.json"):
                if p.name.endswith(".pending.json"):
                    continue  # pending 不占去重位，待 API 拉回补正式记录
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                    mid = rec.get("message_id")
                except Exception:  # noqa: BLE001
                    mid = ""
                if not mid:
                    name = p.name
                    mid = name.rsplit("-", 1)[-1]
                    for suffix in (".processed.json", ".json"):
                        if mid.endswith(suffix):
                            mid = mid[: -len(suffix)]
                            break
                if mid:
                    ids.add(str(mid))
        except Exception as e:  # noqa: BLE001
            log(f"补拉：扫描 inbox 去重失败（不阻塞）：{e}")
    ids |= _load_forwarded_ids(FORWARD_DEDUP_PATH)
    ids |= _load_autodone_ids(inbox_dir)
    return ids


def _fetch_group_messages(token: str, chat_id: str, start_ms: int,
                          end_ms: int) -> tuple[list, str | None]:
    """拉取群 chat_id 在 [start_ms, end_ms] 窗口的最近消息列表（自动翻页）。
    返回 (items, error)；error 非空表示 API 拉取失败（权限/网络等）。

    注意：im/v1/messages 的 start_time/end_time 是**10 位秒**时间戳（非 13 位毫秒），
    实测传 ms 会静默返回 0 条（2026-08-11 实测：秒->34 条，ms->0 条）。"""
    items: list = []
    page_token = ""
    url_base = (f"{FEISHU_API_BASE}/open-apis/im/v1/messages"
                f"?container_id_type=chat&container_id={chat_id}"
                f"&start_time={int(start_ms / 1000)}&end_time={int(end_ms / 1000)}"
                f"&page_size={PAGE_SIZE}&sort_type=ByCreateTimeAsc")
    for _ in range(50):  # 防死循环上限 50 页
        url = url_base + (f"&page_token={page_token}" if page_token else "")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            data = _feishu_http_get_json(url, headers)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return items, f"无权限（im:message 读权限，HTTP 403）"
            return items, f"HTTP {e.code}: {e}"
        except Exception as e:  # noqa: BLE001
            return items, str(e)
        if data.get("code") != 0:
            return items, f"API code={data.get('code')} msg={data.get('msg')}"
        d = data.get("data") or {}
        batch = d.get("items") or []
        items.extend(batch)
        if not d.get("has_more") or not d.get("page_token"):
            break
        page_token = str(d.get("page_token"))
    return items, None


def _should_record(item: dict, whitelist: set, prefixes: list[str],
                   chat_ids: dict) -> tuple[bool, str, str, str, str]:
    """与 process_event 同口径判定某条 API 消息是否该补落盘。

    返回 (should, chat_id, msg_type, content, sender)；should=False 时不落盘。
    只处理人类用户消息（sender_type=='user'，防把 bot 自己发的告警/回执/转发当需求）。
    """
    chat_id = str(item.get("chat_id") or "")
    msg_type = str(item.get("msg_type") or "")
    raw = str((item.get("body") or {}).get("content") or item.get("content") or "")
    content = content_plain(raw, msg_type)
    sender = str((item.get("sender") or {}).get("id") or "")
    if not content:
        return False, chat_id, msg_type, content, sender
    if str((item.get("sender") or {}).get("sender_type") or "") != "user":
        return False, chat_id, msg_type, content, sender
    if chat_id in whitelist:
        return True, chat_id, msg_type, content, sender
    report_id = str(chat_ids.get("report") or "")
    if chat_id == report_id:
        # 报告群：带前缀 或 真需求（非闲聊）→ 补落盘；纯闲聊不落盘（与 process_event 一致）
        if _match_prefix(content, prefixes) or not is_chitchat(content):
            return True, chat_id, msg_type, content, sender
        return False, chat_id, msg_type, content, sender
    return _match_prefix(content, prefixes), chat_id, msg_type, content, sender


def run_fetch(repo: Path | None = None, default_window_h: int = 24,
              dry_run: bool = False, with_receipt: bool = True,
              start_ms: int | None = None, end_ms: int | None = None,
              inbox_dir_override: Path | None = None) -> dict:
    """执行漏收补拉主流程。返回 {group: {"found":n,"recovered":n,"skipped":n}}。"""
    repo = repo or REPO
    cfg = load_config()
    if not cfg:
        log("补拉：config/feishu.json 缺失，跳过")
        return {}
    receive = cfg.get("receive") or {}
    whitelist = set(receive.get("chat_id_whitelist") or [])
    prefixes = [str(p) for p in (receive.get("keyword_prefixes") or [])]
    chat_ids = {str(k): str(v) for k, v in (cfg.get("chat_ids") or {}).items() if v}
    inbox_dir = inbox_dir_override or Path(str(receive.get("inbox_dir", "data/feishu_requests")))
    if not inbox_dir.is_absolute():
        inbox_dir = repo / inbox_dir
    if not chat_ids:
        log("补拉：未配置任何群 chat_id，跳过")
        return {}
    token = _get_token()
    if not token:
        log("补拉：获取 tenant_access_token 失败，跳过")
        return {}

    now_ms = int(time.time() * 1000)
    if end_ms is None:
        end_ms = now_ms
    if start_ms is None:
        cursor = _load_cursor()
        if cursor and cursor < end_ms:
            start_ms = cursor
        else:
            start_ms = end_ms - int(default_window_h * 3600 * 1000)
    # 窗口防呆：不允许负数窗口
    if start_ms >= end_ms:
        start_ms = end_ms - int(default_window_h * 3600 * 1000)
    known = _known_message_ids(inbox_dir)
    log(f"补拉：窗口 [{datetime.fromtimestamp(start_ms / 1000):%Y-%m-%d %H:%M:%S} → "
        f"{datetime.fromtimestamp(end_ms / 1000):%Y-%m-%d %H:%M:%S}]，"
        f"已落盘去重 {len(known)} 条，dry_run={dry_run}")

    summary: dict = {}
    all_ok = True
    dev_id = str(chat_ids.get("agent_done") or "")
    report_id = str(chat_ids.get("report") or "")
    for key, chat_id in chat_ids.items():
        items, err = _fetch_group_messages(token, chat_id, start_ms, end_ms)
        if err:
            all_ok = False
            log(f"补拉：群 {key}({chat_id}) API 拉取失败：{err}")
            summary[key] = {"found": 0, "recovered": 0, "skipped": 0, "error": err}
            continue
        found = len(items)
        recovered = 0
        skipped = 0
        for item in items:
            should, cid, msg_type, content, sender = _should_record(item, whitelist, prefixes, chat_ids)
            msg_id = str(item.get("message_id") or "")
            if not should:
                skipped += 1
                continue
            if msg_id and msg_id in known:
                skipped += 1
                continue
            if dry_run:
                log(f"[dry-run] 将补落盘：{key} msg_id={msg_id} content={content[:60]}")
                recovered += 1
                continue
            # 补落盘（recovered 标记，与正常落盘同格式）
            ts_ms = int(item.get("create_time") or (start_ms + (end_ms - start_ms) // 2))
            ts = int(ts_ms / 1000) if ts_ms > 1e12 else int(ts_ms)
            filename = f"{ts}-{msg_id or 'x'}.json"
            record = {
                "ts": ts,
                "ts_iso": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "sender": sender,
                "chat_id": cid,
                "msg_type": msg_type,
                "content": content,
                "message_id": msg_id,
                "raw_content": str((item.get("body") or {}).get("content") or item.get("content") or ""),
                "recovered": True,
                "recovered_via": "feishu_missed_fetch",
                "recovered_ts": int(time.time()),
            }
            known.add(msg_id)
            try:
                inbox_dir.mkdir(parents=True, exist_ok=True)
                (inbox_dir / filename).write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                log(f"补拉：落盘失败 {filename}：{e}")
                skipped += 1
                continue
            # 进 TASKS 待办（复用 listener 的实现，含文件锁）
            append_todo_to_tasks(summarize(content), ts)
            # 标记 autodone（写入 jsonl + 进程内 Set，防止 WS 重推/下次启动重复进 TASKS/回执）
            _mark_autodone(msg_id, path=AUTODONE_DEDUP_PATH)
            # 报告群补拉消息补转发开发群（不在已转发去重时）
            if cid == report_id and cid not in whitelist and dev_id and \
                    str(msg_id) not in _load_forwarded_ids(FORWARD_DEDUP_PATH):
                send_receipt(dev_id, f"[转自报告群-补拉] {content}")
            # 回执用户（可选，独立 CLI 默认开；启动补拉默认关防大窗口轰炸）
            if with_receipt:
                send_receipt(cid, f"✅ 已收到你的需求（补拉）：{summarize(content)}，已纳入待办，主控将跟进处理",
                             message_id=msg_id or None)
            recovered += 1
        log(f"补拉：群 {key} found={found} recovered={recovered} skipped={skipped}")
        summary[key] = {"found": found, "recovered": recovered, "skipped": skipped}
    # 全部群无硬错误才推进游标（某群失败说明链路有问题，下次仍从原游标补，防窗口跳漏）
    if all_ok:
        _save_cursor(end_ms)
        log(f"补拉：游标推进至 {end_ms}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="飞书漏收消息补拉（P0-2/TASKS㉟）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不真写，只打印将补拉的消息")
    parser.add_argument("--window-hours", type=int, default=24,
                        help="无游标时默认拉取窗口小时数（默认 24h）")
    parser.add_argument("--start-ms", type=int, default=None, help="显式窗口起点 ms（覆盖游标）")
    parser.add_argument("--end-ms", type=int, default=None, help="显式窗口终点 ms（默认 now）")
    parser.add_argument("--no-receipt", action="store_true",
                        help="不发回执（默认发）")
    args = parser.parse_args(argv)
    summary = run_fetch(default_window_h=args.window_hours, dry_run=args.dry_run,
                        with_receipt=not args.no_receipt,
                        start_ms=args.start_ms, end_ms=args.end_ms)
    if not summary:
        print("[feishu_missed_fetch] 未执行（无配置/无 token/异常）", file=sys.stderr)
        return 1
    total = sum(v.get("recovered", 0) for v in summary.values())
    print(f"[feishu_missed_fetch] 完成：{summary} 合计补拉 {total} 条"
          + ("（dry-run 未真写）" if args.dry_run else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
