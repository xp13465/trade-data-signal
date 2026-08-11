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
- 收到回执：合法需求落盘成功后，立即调用飞书 API **引用回复**用户那条具体消息
  （body 带 reply_to_message_id=msg.message_id，飞书引用回复；用户连续发多条时每条
  都能看到对应「收到」回执）。文案「已收到需求…，主控 1 分钟内开始处理」。best-effort，
  发送失败仅 log 不阻塞落盘。
- 跨群转发：告警群/报告群的**人类用户**消息（无论有无需求前缀）自动抄送一份到开发群
  （agent_done），文案带来源标记（[转自告警群]/[转自报告群]），供开发群查完整聊天记录。
  防循环铁律：只转发 sender_type=='user'（人类用户），bot 自己（sender_type=='app'）发的
  告警/回执/转发消息一律不转发；取不到 sender_type 宁可不转发。message_id 进程内 Set +
  jsonl 落盘去重，SDK 重推不重复转发。转发 best-effort，失败仅 log 不阻塞落盘。

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
                               dedup_path: Path | None = None) -> bool:
    """跨群转发：告警群/报告群的**人类用户**消息自动抄送一份到开发群（agent_done）。

    - 只转发 sender_type=='user'（人类用户）；bot 自己（sender_type=='app'）、系统消息、其他
      应用一律不转发（防循环——bot 发到告警/报告群的告警/回执/转发也会触发 receive_v1 事件）。
    - 取不到 sender_type 宁可不转发（防循环优先）。
    - 开发群消息不转发（已在群里）；其他群不转发。
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
                  dedup_path: Path | None = None) -> str | None:
    """处理一条 im.message.receive_v1 事件（模块级，便于测试）。

    白名单需求群：免前缀直接当需求落盘；其他群：保留前缀过滤（全角/半角冒号都认）。
    合法需求落盘 inbox_dir/<ts>-<message_id>.json。
    跨群转发：告警群/报告群的用户消息抄送开发群（见 maybe_forward_user_message），与落盘
    解耦——用户问询不一定带需求前缀，无论是否落盘都转发；bot 自己的消息不转发（防循环）。
    返回落盘文件名（未落盘返回 None）。once=True 且落盘后调用方退出。"""
    try:
        msg = data.event.message
        chat_id = str(msg.chat_id or "")
        msg_type = str(msg.message_type or "")
        content = content_plain(str(msg.content or ""), msg_type)
        if not content:
            log("跳过空内容消息")
            return None
        # 跨群转发（best-effort，失败不阻塞落盘）：在前缀过滤之前执行，保证用户问询（无前缀）也转发
        maybe_forward_user_message(data, chat_id, content, chat_map=chat_map,
                                   forwarded_ids=forwarded_ids, dedup_path=dedup_path)
        # 非白名单群必须带需求前缀才接收（白名单需求群免前缀直接落盘）
        if chat_id not in whitelist and not _match_prefix(content, prefixes):
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
        # 收到回执：best-effort 引用回复用户那条具体消息，秒级回一条已收到（失败不阻塞落盘）
        excerpt = content if len(content) <= 40 else content[:40] + "…"
        send_receipt(chat_id, f"✅ 已收到需求「{excerpt}」，主控 1 分钟内开始处理",
                     message_id=msg.message_id)
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
    log(f"监听配置：白名单群 {len(whitelist)} 个，前缀 {prefixes}，落盘 {inbox_dir}")
    log(f"跨群转发配置：alert={chat_map.get('alert')} report={chat_map.get('report')} "
        f"agent_done={chat_map.get('agent_done')}，已载入去重 {len(forwarded_ids)} 条")

    def handle(data) -> None:  # P2ImMessageReceiveV1
        process_event(data, whitelist, prefixes, inbox_dir, once=once,
                      chat_map=chat_map, forwarded_ids=forwarded_ids,
                      dedup_path=dedup_path)

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
