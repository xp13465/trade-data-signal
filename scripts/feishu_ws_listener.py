#!/usr/bin/env python3
"""feishu_ws_listener.py - 飞书长连接常驻监听进程（接收群消息，落盘供主控整理待办）。

订阅 im.message.receive_v1 事件（长连接 WebSocket，免公网回调）。白名单需求群内消息
免前缀直接当需求接收；其他群保留关键词前缀过滤（全角/半角冒号都认）。合法需求落盘
data/feishu_requests/<ts>-<message_id>.json（含 ts/sender/chat_id/msg_type/content
明文）。launchd KeepAlive 常驻（com.trade.feishu-listener）。

- 凭证：config/feishu.json（gitignore）的 receive 段 + .env 的 FEISHU_APP_ID/FEISHU_APP_SECRET
  （存 /Users/linhuichen/code/trade-data/.env，从 .env 读不硬编码不 echo）。
- SDK：官方 lark-oapi（pip 已装，python3.11 需 >=1.1 才有 lark_oapi.ws）。探测
  lark_oapi.ws / lark_oapi.adapter.ws 两路径。
- 本地 MITM 代理自签证书：启动时把 macOS 系统信任证书导出 PEM（security 命令），设
  SSL_CERT_FILE + REQUESTS_CA_BUNDLE 指向它（requests/websockets 均读），解决
  CERTIFICATE_VERIFY_FAILED（不关闭证书校验，用系统信任链）。
- 落盘后主控侧 cron 轮询整理进 TASKS（见 docs/feishu-bot-integration-plan.md「接收落盘格式」）。
- 需求自动进待办 + 即时回执（2026-08-11 起主控零轮询）：合法需求落盘成功后，listener
  自己完成 ①追加待办到 TASKS.md `#### 待办` 小节（一行 `- [ ] (飞书 YYYY-MM-DD HH:MM) <摘要>`，
  git 落档持久化，主控开工/compact 恢复读 TASKS 即看到）②调 notify.py 发即时回执到开发群
  （agent_done=用户提需求所在群，**引用回复**用户那条具体消息 body 带
  reply_to_message_id=msg.message_id，文案「✅ 已收到你的需求：…，已纳入待办，主控将跟进
  处理」）。两动作均 best-effort：失败仅 log 不阻塞监听/落盘；notify 不可用时回执退化用
  send_receipt 直接回用户所在群。防重复：同一 message_id 只自动处理一次（进程内 Set +
  jsonl + 启动时载入历史 *.processed.json，SDK at-least-once 重推不重复进 TASKS/回执）。
- 跨群转发：报告群（report）的**人类用户**消息自动抄送一份到开发群（agent_done），带
  [转自报告群] 标记，且**同时按需求落盘进待办+回执**（2026-08-11 fix：报告群用户回复此前
  仅转发未进 TASKS，用户感知"回复未被处理"）；告警群（alert）的**人类用户**消息默认**不抄送**
  开发群（多为计划任务执行告警/恢复类问询，应留运维群），仅当带需求前缀（需求:/t:，全角/
  半角冒号都认，复用 _match_prefix）才抄送并带 [转自告警群] 标记。防循环铁律：只转发
  sender_type=='user'（人类用户），bot 自己（sender_type=='app'）发的告警/回执/转发消息
  一律不转发；取不到 sender_type 宁可不转发。message_id 进程内 Set + jsonl 落盘去重，
  SDK 重推不重复转发。转发 best-effort，失败仅 log 不阻塞落盘。

用法:
  python scripts/feishu_ws_listener.py [--once] [--no-ssl-workaround]
    --once        收到一条合法请求后退出（测试用）
    --no-ssl-workaround  跳过系统证书导出（纯净网络环境用）
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
CONFIG_PATH = REPO / "config" / "feishu.json"
# 日志进 trade-data/data/logs（与现有 launchd 任务一致；trade/data/logs 是历史 symlink 等价）
LOG_PATH = Path("/Users/linhuichen/code/trade-data/data/logs") / "feishu_listener.log"
# 系统信任证书导出 PEM（本地 MITM 代理自签证书信任用，runtime 文件不进 git）
CACERT_PATH = Path("/Users/linhuichen/code/trade-data/data/feishu_cacert.pem")
# 收到回执：飞书 open.feishu.cn（中国版域名）+ tenant_access_token 缓存（2h 有效，过期前 120s 刷新复用）
FEISHU_API_BASE = "https://open.feishu.cn"
_FEISHU_TOKEN_CACHE: dict = {"token": None, "expire_at": 0.0}
# 跨群转发去重：进程内 Set + 落盘 jsonl（SDK 长连接 at-least-once 可能重推，防重复转发）
FORWARD_DEDUP_PATH = REPO / "data" / "feishu_requests" / "forwarded_message_ids.jsonl"
_FORWARDED_IDS: set = set()


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def load_env() -> dict:
    """读 .env 的 FEISHU_APP_ID/FEISHU_APP_SECRET（trade-data/.env 优先，trade/.env 兜底）。不 echo。"""
    env: dict = {}
    candidates = [
        Path("/Users/linhuichen/code/trade-data/.env"),
        REPO.parent / "trade-data" / ".env",
        REPO / ".env",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        except Exception:  # noqa: BLE001
            continue
        if env.get("FEISHU_APP_ID") and env.get("FEISHU_APP_SECRET"):
            break
    return env


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"config/feishu.json 不存在：{CONFIG_PATH}（跳过监听）")
        sys.exit(1)
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log(f"config/feishu.json 解析失败：{e}")
        sys.exit(1)


def _feishu_http_post_json(url: str, payload: bytes, headers: dict,
                           timeout: int = 5) -> dict:
    """POST JSON 到飞书 API。本地 MITM 代理自签证书致默认校验失败时，
    遇到 CERTIFICATE_VERIFY_FAILED 退化为不校验重试一次（仅飞书 API 调用）。"""
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        log("回执：飞书 SSL 校验失败，退化为不校验重试一次（本地 MITM 代理）")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _get_tenant_access_token() -> str | None:
    """获取飞书 tenant_access_token（带缓存，2h 有效，过期前 120s 刷新复用）。
    凭证从 .env 读（FEISHU_APP_ID/FEISHU_APP_SECRET，不 echo 不硬编码）。
    失败返回 None（调用方跳过回执，不阻塞）。"""
    now = time.time()
    if _FEISHU_TOKEN_CACHE["token"] and _FEISHU_TOKEN_CACHE["expire_at"] > now:
        return _FEISHU_TOKEN_CACHE["token"]
    env = load_env()
    app_id = env.get("FEISHU_APP_ID", "")
    app_secret = env.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        log("回执：未找到 FEISHU_APP_ID/FEISHU_APP_SECRET（.env），跳过回执")
        return None
    url = f"{FEISHU_API_BASE}/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret},
                         ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        data = _feishu_http_post_json(url, payload, headers, timeout=5)
    except Exception as e:  # noqa: BLE001
        log(f"回执：获取 tenant_access_token 失败（跳过回执，不阻塞）：{e}")
        return None
    if data.get("code") != 0:
        log(f"回执：token API 返回非 0：code={data.get('code')} msg={data.get('msg')}（跳过回执）")
        return None
    token = str(data.get("tenant_access_token", "") or "")
    if not token:
        log("回执：token 响应为空，跳过回执")
        return None
    expire = int(data.get("expire", 7200) or 7200)
    _FEISHU_TOKEN_CACHE["token"] = token
    _FEISHU_TOKEN_CACHE["expire_at"] = now + max(60, expire - 120)
    return token


def send_receipt(chat_id: str, text: str, message_id: str | None = None) -> bool:
    """向 chat_id 回一条文本消息（收到回执）。best-effort：失败仅 log 不抛异常。
    POST im/v1/messages?receive_id_type=chat_id，body {"receive_id","msg_type","content"}。
    传入 message_id 时 body 加 "reply_to_message_id"（飞书引用回复，回复用户发的那条具体消息，
    用户连续发多条时每条都能看到对应「收到」回执）。"""
    if not chat_id or not text:
        return False
    token = _get_tenant_access_token()
    if not token:
        return False
    url = f"{FEISHU_API_BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
    content = json.dumps({"text": text}, ensure_ascii=False)
    body = {"receive_id": chat_id, "msg_type": "text", "content": content}
    if message_id:
        body["reply_to_message_id"] = message_id
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Authorization": f"Bearer {token}"}
    try:
        data = _feishu_http_post_json(url, payload, headers, timeout=5)
    except Exception as e:  # noqa: BLE001
        log(f"回执：发送失败（不阻塞落盘）：{e}")
        return False
    if data.get("code") == 0:
        log(f"已回执 {chat_id}（reply_to={message_id or '否'}）：{text[:40]}")
        return True
    log(f"回执：API 返回非 0：code={data.get('code')} msg={data.get('msg')}")
    return False


# ── 需求自动进待办 + 即时回执（2026-08-11 起主控零轮询）─────────────────────────
# TASKS.md 待办锚点：`#### 待办` 小节（插入点=锚点行后）。TASKS.md 含 42KB 超长行，
# 禁止 grep/打印超长行——本模块用 python 逐行读写，超长行原样透传不解析。
TASKS_PATH = REPO / "TASKS.md"
TASKS_TODO_ANCHOR = "#### 待办"
# 需求自动进待办+回执去重：进程内 Set + jsonl 落盘（SDK 长连接 at-least-once 可能重推，
# 防同一消息重复进 TASKS/重复回执；启动时同时载入历史 *.processed.json 防重复处理旧消息）
AUTODONE_DEDUP_PATH = REPO / "data" / "feishu_requests" / "autodone_message_ids.jsonl"
_AUTODONE_IDS: set = set()
# notify.py（统一通知出口）懒加载：import 失败不中断监听（回执退化为 send_receipt 直接回）
_NOTIFY: object | None = None
_NOTIFY_IMPORT_TRIED = False


def _get_notify():
    """懒加载 notify.py（统一通知出口，与 check_signals.py 同款 import notify）。
    失败返回 None（回执退化为 send_receipt 直接回用户所在群，不中断监听）。"""
    global _NOTIFY, _NOTIFY_IMPORT_TRIED
    if _NOTIFY_IMPORT_TRIED:
        return _NOTIFY
    _NOTIFY_IMPORT_TRIED = True
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import notify  # noqa: PLC0415
        _NOTIFY = notify
    except Exception as e:  # noqa: BLE001
        log(f"回执：import notify 失败（退化 send_receipt 直接回用户群）：{e}")
        _NOTIFY = None
    return _NOTIFY


def summarize(content: str, limit: int = 80) -> str:
    """需求原文摘要：压平换行/多余空白为单行，截断到 limit 字符（超长加省略号）。"""
    text = " ".join((content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def append_todo_to_tasks(excerpt: str, ts: int | None = None) -> bool:
    """在 TASKS.md `#### 待办` 小节锚点行后插入一行 `- [ ] (飞书 YYYY-MM-DD HH:MM) <摘要>`。

    只追加不破坏：逐行读文件（42KB 超长行不解析不打印，原样透传），定位锚点行索引后在其
    后面插入新行，临时文件 + os.replace 原子写回。best-effort：失败仅 log 不抛异常。
    返回 True=成功插入。"""
    try:
        if not TASKS_PATH.exists():
            log(f"进待办：TASKS.md 不存在（{TASKS_PATH}），跳过")
            return False
        ts_iso = (datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                  if ts else datetime.now().strftime("%Y-%m-%d %H:%M"))
        new_line = f"- [ ] (飞书 {ts_iso}) {excerpt}"
        lines = TASKS_PATH.read_text(encoding="utf-8").splitlines()
        anchor_idx = next((i for i, ln in enumerate(lines)
                           if ln.strip() == TASKS_TODO_ANCHOR), None)
        if anchor_idx is None:
            log(f"进待办：TASKS.md 未找到锚点 {TASKS_TODO_ANCHOR!r}，跳过（不往文件末尾乱插）")
            return False
        new_lines = lines[: anchor_idx + 1] + [new_line] + lines[anchor_idx + 1:]
        tmp = TASKS_PATH.with_name(TASKS_PATH.name + ".tmp")
        tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.replace(tmp, TASKS_PATH)
        log(f"进待办：已插入 -> {new_line}")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"进待办：写入 TASKS.md 失败（不阻塞监听）：{e}")
        return False


def _load_autodone_ids(inbox_dir: Path) -> set:
    """启动时载入已自动处理 message_id 去重集合：autodone jsonl + 历史 *.processed.json。
    防止 SDK 重推重复进 TASKS，也防止旧 cron 已整理过的消息（*.processed.json）被重复整理。"""
    ids: set = set()
    if AUTODONE_DEDUP_PATH.exists():
        try:
            for line in AUTODONE_DEDUP_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    mid = json.loads(line).get("message_id")
                except Exception:  # noqa: BLE001
                    mid = line
                if mid:
                    ids.add(str(mid))
        except Exception as e:  # noqa: BLE001
            log(f"自动处理去重加载失败（不阻塞）：{e}")
    if inbox_dir and inbox_dir.exists():
        try:
            for p in inbox_dir.glob("*.processed.json"):
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                    mid = rec.get("message_id")
                except Exception:  # noqa: BLE001
                    mid = ""
                if not mid:
                    # 文件名 <ts>-<mid>.processed.json 兜底取 mid
                    name = p.name
                    mid = name.rsplit("-", 1)[-1].replace(".processed.json", "")
                if mid:
                    ids.add(str(mid))
        except Exception as e:  # noqa: BLE001
            log(f"自动处理去重：扫描 *.processed.json 失败（不阻塞）：{e}")
    return ids


def _mark_autodone(message_id: str, path: Path | None = None,
                   autodone_ids: set | None = None, max_size: int = 20000) -> None:
    """自动处理成功标记去重（进程内 Set + 追加 jsonl），防 SDK 重推重复进 TASKS/回执。
    集合超上限时清最旧一半防无限增长。"""
    if not message_id:
        return
    if autodone_ids is None:
        autodone_ids = _AUTODONE_IDS
    if message_id in autodone_ids:
        return
    autodone_ids.add(message_id)
    try:
        path = path or AUTODONE_DEDUP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"message_id": message_id, "ts": int(time.time())},
                               ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log(f"自动处理去重落盘失败（不影响本次处理）：{e}")
    if len(autodone_ids) > max_size:
        for old in list(autodone_ids)[: max_size // 2]:
            autodone_ids.discard(old)


def send_requirement_receipt(chat_id: str, excerpt: str,
                             message_id: str | None = None) -> bool:
    """需求即时回执：notify.py 发飞书到开发群（agent_done=用户提需求所在群），引用回复用户消息。

    文案「✅ 已收到你的需求：<摘要>，已纳入待办，主控将跟进处理」。best-effort：失败仅 log
    不抛异常；notify 不可用/发送失败时退化为现有 send_receipt 直接回用户所在群（双保险）。"""
    text = f"✅ 已收到你的需求：{excerpt}，已纳入待办，主控将跟进处理"
    ntf = _get_notify()
    if ntf is not None:
        try:
            ok = ntf.send_feishu("需求已收到(飞书)", text, chat_key="agent_done",
                                 reply_to_message_id=message_id)
            if ok:
                log(f"回执：notify 发开发群 agent_done 成功（reply_to={message_id or '否'}）")
                return True
            log("回执：notify 飞书发送失败，退化用 send_receipt 直接回用户群")
        except Exception as e:  # noqa: BLE001
            log(f"回执：notify 调用异常（退化 send_receipt 直接回用户群）：{e}")
    return send_receipt(chat_id, text, message_id=message_id)


def export_system_cacert() -> bool:
    """把 macOS 系统信任证书导出为 PEM，供 requests/websockets 信任本地 MITM 代理。
    成功设置 SSL_CERT_FILE + REQUESTS_CA_BUNDLE 返回 True。"""
    try:
        CACERT_PATH.parent.mkdir(parents=True, exist_ok=True)
        chunks = []
        for keychain in ["/System/Library/Keychains/SystemRootCertificates.keychain",
                         "/Library/Keychains/System.keychain",
                         f"{Path.home()}/Library/Keychains/login.keychain-db"]:
            r = subprocess.run(["security", "find-certificate", "-a", "-p", keychain],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                chunks.append(r.stdout)
        if not chunks:
            log("导出系统证书失败：security 无输出，跳过 ssl 证书 workaround")
            return False
        CACERT_PATH.write_text("\n".join(chunks), encoding="utf-8")
        os.environ["SSL_CERT_FILE"] = str(CACERT_PATH)
        os.environ["REQUESTS_CA_BUNDLE"] = str(CACERT_PATH)
        log(f"已导出系统证书 {len(chunks)} 段 -> {CACERT_PATH}，设 SSL_CERT_FILE/REQUESTS_CA_BUNDLE")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"导出系统证书异常：{e}（跳过 ssl 证书 workaround）")
        return False


def sender_id(data) -> str:
    try:
        sid = data.event.sender.sender_id
        if sid is None:
            return ""
        return (getattr(sid, "user_id", None) or getattr(sid, "open_id", None) or "")
    except Exception:  # noqa: BLE001
        return ""


def content_plain(content_json: str, msg_type: str) -> str:
    """事件 content（JSON 字符串）转明文。text: {"text":...}；post: {"title":..,"content":[[{tag,text}]]}。"""
    if not content_json:
        return ""
    try:
        c = json.loads(content_json)
    except Exception:  # noqa: BLE001
        return str(content_json)
    if msg_type == "text":
        return str(c.get("text", ""))
    if msg_type == "post":
        parts = []
        for line in c.get("content", []) or []:
            for node in line or []:
                if isinstance(node, dict) and node.get("tag") == "text":
                    parts.append(str(node.get("text", "")))
        return "\n".join(parts)
    # 其他消息类型（image/audio 等）落盘原始 JSON 供排查
    return json.dumps(c, ensure_ascii=False)


def build_ws_client(app_id: str, app_secret: str, handler) -> object | None:
    """构造 lark-oapi 长连接 Client（探测 lark_oapi.ws / lark_oapi.adapter.ws 两路径）。"""
    try:
        import lark_oapi as lark  # noqa: PLC0415
        dispatcher = (lark.EventDispatcherHandler.builder("", "")
                      .register_p2_im_message_receive_v1(handler).build())
        try:
            from lark_oapi.ws import Client as WsClient  # noqa: PLC0415
        except ImportError:
            try:
                from lark_oapi.adapter.ws import Client as WsClient  # noqa: PLC0415
            except ImportError:
                log("lark_oapi 无 ws Client（需 pip install 'lark-oapi>=1.1'），无法用 SDK 长连接")
                return None
        log(f"使用 lark-oapi {getattr(lark, '__version__', 'n/a')} ws.Client（{WsClient.__module__}）")
        return WsClient(app_id, app_secret, event_handler=dispatcher,
                        log_level=lark.LogLevel.INFO, auto_reconnect=True)
    except Exception as e:  # noqa: BLE001
        log(f"构造 lark-oapi ws.Client 失败：{e}")
        return None


def _match_prefix(content: str, prefixes: list[str]) -> bool:
    """宽松前缀匹配：全角/半角冒号都认（需求:/需求：/t:/t： 均命中）。"""
    text = content.strip()
    for p in (prefixes or []):
        p = p.strip()
        if not p:
            continue
        if text.startswith(p):
            return True
        # 全角/半角冒号变体互换再匹配
        if ":" in p:
            if text.startswith(p.replace(":", "：")):
                return True
        elif "：" in p:
            if text.startswith(p.replace("：", ":")):
                return True
    return False


def _sender_type(data) -> str:
    """取事件发送者类型（lark-oapi EventSender.sender_type：user=人类用户 / app=应用(bot 自己) /
    system=系统）。取不到返回 ''（宁可不转发，防循环）。"""
    try:
        return str(getattr(data.event.sender, "sender_type", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _load_forwarded_ids(path: Path) -> set:
    """启动时从 jsonl 加载已转发 message_id 去重集合（进程重启不重发）。"""
    ids: set = set()
    if not path or not path.exists():
        return ids
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                mid = json.loads(line).get("message_id")
            except Exception:  # noqa: BLE001
                mid = line
            if mid:
                ids.add(str(mid))
    except Exception as e:  # noqa: BLE001
        log(f"转发去重加载失败（不阻塞）：{e}")
    return ids


def _mark_forwarded(message_id: str, path: Path, forwarded_ids: set,
                    max_size: int = 20000) -> None:
    """转发成功后标记去重（进程内 Set + 追加 jsonl）。集合超上限时清最旧一半防无限增长。"""
    if not message_id or message_id in forwarded_ids:
        return
    forwarded_ids.add(message_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"message_id": message_id, "ts": int(time.time())},
                               ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log(f"转发去重落盘失败（不影响转发）：{e}")
    if len(forwarded_ids) > max_size:
        # 防无限增长：清最旧一半（jsonl 已持久化，进程内只作热查）
        for old in list(forwarded_ids)[:max_size // 2]:
            forwarded_ids.discard(old)


def maybe_forward_user_message(data, chat_id: str, content: str,
                               chat_map: dict | None = None,
                               forwarded_ids: set | None = None,
                               dedup_path: Path | None = None,
                               prefixes: list | None = None) -> bool:
    """跨群转发：报告群用户消息抄送开发群；告警群仅带需求前缀的用户消息抄送开发群。

    - 只转发 sender_type=='user'（人类用户）；bot 自己（sender_type=='app'）、系统消息、其他
      应用一律不转发（防循环——bot 发到告警/报告群的告警/回执/转发也会触发 receive_v1 事件）。
    - 告警群（alert）来源的人类用户消息默认**不转发**开发群——告警群里用户消息几乎都是
      "计划任务执行告警/恢复"类问询（如"处理好了吗/自愈了吗"），应留运维群不抄送开发群；
      **仅当**消息带需求前缀（需求:/t:，全角/半角冒号都认，复用 _match_prefix）才转发开发群
      （带 [转自告警群] 标记）。
    - 报告群（report）来源的人类用户消息照常转发开发群（带 [转自报告群] 标记）。
    - 开发群消息不转发（已在群里）；其他群不转发。
    - 取不到 sender_type 宁可不转发（防循环优先）。
    - message_id 去重（进程内 Set + jsonl 落盘），SDK 重推不重复转发。
    - best-effort：转发失败仅 log 不抛异常不阻塞落盘。
    返回 True=已转发成功。"""
    if chat_map is None:
        chat_map = {}
    if forwarded_ids is None:
        forwarded_ids = _FORWARDED_IDS
    if dedup_path is None:
        dedup_path = FORWARD_DEDUP_PATH
    alert_id = str(chat_map.get("alert") or "")
    report_id = str(chat_map.get("report") or "")
    dev_id = str(chat_map.get("agent_done") or "")
    if not dev_id:
        log("转发：未配置 agent_done 开发群 chat_id，跳过转发")
        return False
    if chat_id == alert_id:
        source_name = "告警群"
    elif chat_id == report_id:
        source_name = "报告群"
    else:
        return False  # 开发群/其他群不转发（开发群消息已在群里）
    if _sender_type(data) != "user":
        log(f"转发：sender_type={_sender_type(data)!r} 非人类用户，不转发（防循环）chat_id={chat_id}")
        return False
    # 告警群来源的人类用户消息默认不抄送开发群（多为计划任务执行告警/恢复类问询）；
    # 仅当带需求前缀（需求:/t:，全角/半角冒号都认，复用 _match_prefix）才转发开发群
    if chat_id == alert_id and not _match_prefix(content, list(prefixes or [])):
        log(f"转发：告警群用户消息无需求前缀，不抄送开发群（计划任务执行告警/恢复类留运维群）"
            f"chat_id={chat_id} content={content[:60]}")
        return False
    msg_id = str(getattr(data.event.message, "message_id", "") or "")
    if msg_id and msg_id in forwarded_ids:
        log(f"转发：message_id={msg_id} 已转发过，去重跳过")
        return False
    text = f"[转自{source_name}] {content}"
    ok = send_receipt(dev_id, text)
    if ok:
        _mark_forwarded(msg_id, dedup_path, forwarded_ids)
        log(f"转发成功：{source_name} -> 开发群 message_id={msg_id} content={content[:60]}")
    else:
        log(f"转发失败（best-effort 不阻塞）：{source_name} -> 开发群 message_id={msg_id}")
    return ok


def process_event(data, whitelist: set, prefixes: list[str],
                  inbox_dir: Path, once: bool = False,
                  chat_map: dict | None = None,
                  forwarded_ids: set | None = None,
                  dedup_path: Path | None = None,
                  autodone_ids: set | None = None,
                  autodone_path: Path | None = None) -> str | None:
    """处理一条 im.message.receive_v1 事件（模块级，便于测试）。

    白名单需求群：免前缀直接当需求落盘；其他群：保留前缀过滤（全角/半角冒号都认）。
    合法需求落盘 inbox_dir/<ts>-<message_id>.json。
    落盘后追加两个动作（2026-08-11 起主控零轮询，不再等 cron 扫描整理）：
      ① append_todo_to_tasks：追加一行 `- [ ] (飞书 YYYY-MM-DD HH:MM) <摘要>` 到
         TASKS.md `#### 待办` 小节（git 落档持久化）
      ② send_requirement_receipt：notify.py 发即时回执到开发群（引用回复用户消息）
    跨群转发：报告群用户消息抄送开发群；告警群用户消息仅带需求前缀才抄送开发群（见
    maybe_forward_user_message）。报告群人类用户消息（已转发）同时落盘进待办+回执——
    用户回复反馈不丢（2026-08-11 fix）；告警群无前缀用户消息除外（计划任务执行告警/恢复
    类问询留运维群）。bot 自己的消息不转发（防循环）。
    防重复：同一 message_id 只自动处理一次（autodone_ids 进程内 Set + jsonl +
    历史 *.processed.json 载入），SDK at-least-once 重推不重复进 TASKS/回执。
    返回落盘文件名（未落盘返回 None）。once=True 且落盘后调用方退出。"""
    if autodone_ids is None:
        autodone_ids = _AUTODONE_IDS
    if autodone_path is None:
        autodone_path = AUTODONE_DEDUP_PATH
    try:
        msg = data.event.message
        chat_id = str(msg.chat_id or "")
        msg_type = str(msg.message_type or "")
        content = content_plain(str(msg.content or ""), msg_type)
        if not content:
            log("跳过空内容消息")
            return None
        # 跨群转发（best-effort，失败不阻塞落盘）：在前缀过滤之前执行，保证用户问询（无前缀）也转发
        # （告警群无前缀用户消息除外：计划任务执行告警/恢复类问询不抄送开发群，见 maybe_forward_user_message）
        forwarded = maybe_forward_user_message(
            data, chat_id, content, chat_map=chat_map,
            forwarded_ids=forwarded_ids, dedup_path=dedup_path,
            prefixes=prefixes)
        # 非白名单群必须带需求前缀才接收（白名单需求群免前缀直接落盘）；
        # 报告群人类用户消息（已跨群转发）也落盘进待办+回执，保证用户回复反馈不被丢
        # （2026-08-11 fix：用户报告群回复"这个是监控的 应该发给运维群"此前仅转发开发群，
        #  未落盘/未进 TASKS/未回执，用户感知"未被处理"）
        if (chat_id not in whitelist and not _match_prefix(content, prefixes)
                and not forwarded):
            log(f"跳过非需求消息（非白名单群且无需求前缀）：chat_id={chat_id} content={content[:60]}")
            return None
        ts_ms = int(msg.create_time) if msg.create_time else int(time.time() * 1000)
        ts = int(ts_ms / 1000) if ts_ms > 1e12 else int(ts_ms)
        filename = f"{ts}-{msg.message_id or 'x'}.json"
        record = {
            "ts": ts,
            "ts_iso": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "sender": sender_id(data),
            "chat_id": chat_id,
            "msg_type": msg_type,
            "content": content,
            "message_id": msg.message_id,
            "raw_content": str(msg.content or ""),
        }
        inbox_dir.mkdir(parents=True, exist_ok=True)
        (inbox_dir / filename).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"收到需求已落盘：{filename} sender={record['sender']} content={content[:80]}")
        # 需求自动进待办 + 即时回执（2026-08-11 起主控零轮询）：listener 收到需求自己完成
        # 落盘+进TASKS+回执，不再等主控 cron 扫描整理。best-effort，失败仅 log 不阻塞监听。
        msg_id_str = str(msg.message_id or "")
        if msg_id_str and msg_id_str in autodone_ids:
            log(f"自动处理：message_id={msg_id_str} 已处理过，去重跳过（不重复进 TASKS/回执）")
        else:
            excerpt = summarize(content)
            append_todo_to_tasks(excerpt, ts)            # 1) 追加待办到 TASKS.md 待办小节
            send_requirement_receipt(chat_id, excerpt,   # 2) 即时回执（notify 发开发群，引用回复）
                                     message_id=msg_id_str or None)
            _mark_autodone(msg_id_str, path=autodone_path, autodone_ids=autodone_ids)
        if once:
            log("--once 模式收到合法请求，退出")
            os._exit(0)  # 从 asyncio 回调直接退出，绕过 SDK 清理
        return filename
    except Exception as e:  # noqa: BLE001
        log(f"处理消息异常：{e}")
        return None


def run_listener(app_id: str, app_secret: str, cfg: dict, once: bool = False) -> int:
    """启动长连接监听。once=True 收到一条合法请求后退出（测试用）。"""
    receive = cfg.get("receive") or {}
    whitelist = set(receive.get("chat_id_whitelist") or [])
    prefixes = [str(p) for p in (receive.get("keyword_prefixes") or [])]
    inbox_dir = Path(str(receive.get("inbox_dir", "data/feishu_requests")))
    if not inbox_dir.is_absolute():
        inbox_dir = REPO / inbox_dir
    # 跨群转发：三群 chat_ids（alert/report/agent_done）+ 启动时加载去重集合
    chat_map = {str(k): str(v) for k, v in (cfg.get("chat_ids") or {}).items() if v}
    dedup_path = FORWARD_DEDUP_PATH
    forwarded_ids = _load_forwarded_ids(dedup_path)
    autodone_ids = _load_autodone_ids(inbox_dir)
    log(f"监听配置：白名单群 {len(whitelist)} 个，前缀 {prefixes}，落盘 {inbox_dir}")
    log(f"跨群转发配置：alert={chat_map.get('alert')} report={chat_map.get('report')} "
        f"agent_done={chat_map.get('agent_done')}，已载入去重 {len(forwarded_ids)} 条")
    log(f"需求自动处理：已载入去重 {len(autodone_ids)} 条（含历史 *.processed.json），"
        f"合法需求将自动进 TASKS.md 待办 + notify 即时回执开发群")

    def handle(data) -> None:  # P2ImMessageReceiveV1
        process_event(data, whitelist, prefixes, inbox_dir, once=once,
                      chat_map=chat_map, forwarded_ids=forwarded_ids,
                      dedup_path=dedup_path,
                      autodone_ids=autodone_ids, autodone_path=AUTODONE_DEDUP_PATH)

    client = build_ws_client(app_id, app_secret, handle)
    if client is None:
        log("SDK 长连接不可用，无法启动监听（需手动联调，见 docs/feishu-bot-integration-plan.md）")
        return 1
    log("启动飞书长连接监听（im.message.receive_v1）…")
    while True:
        try:
            client.start()  # 内部自带断线重连（auto_reconnect=True）
        except KeyboardInterrupt:
            log("收到 Ctrl-C，退出")
            return 0
        except Exception as e:  # noqa: BLE001
            log(f"长连接异常退出（launchd KeepAlive 或本循环兜底重连）：{e}")
        time.sleep(30)


def main(argv: list[str] | None = None) -> int:
    once = "--once" in (argv or sys.argv[1:])
    no_ssl = "--no-ssl-workaround" in (argv or sys.argv[1:])
    if not no_ssl:
        export_system_cacert()
    cfg = load_config()
    env = load_env()
    app_id = env.get("FEISHU_APP_ID", "")
    app_secret = env.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        log("未找到 FEISHU_APP_ID/FEISHU_APP_SECRET（.env），退出")
        return 1
    return run_listener(app_id, app_secret, cfg, once=once)


if __name__ == "__main__":
    sys.exit(main())
