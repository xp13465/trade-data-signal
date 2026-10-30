#!/usr/bin/env python3
"""
sensenova-proxy-ctl.py - 商汤轮换代理跨平台统一控制工具(纯标准库,mac/windows/linux 通用)

把 sensenova-rotate-proxy.py 的启停/状态/测试/key 编辑/配置生成统一到一个命令,
不依赖 .sh(mac)或 .bat(windows)作主入口。一行启动:
  mac/linux: python3 sensenova-proxy-ctl.py
  windows:   python sensenova-proxy-ctl.py

子命令:
  start                后台拉起代理(写 PID 到 ~/.sensenova-proxy/proxy.pid)
  stop                 读 PID 停止,删 PID 文件
  status               查 PID/进程/端口/key 数
  keys                 用 $EDITOR 打开同目录 keys.txt 编辑(首次从 example 复制)
  test                 经代理发最小 glm-5.2 请求验证可用(http.client,不依赖 curl)
  config claude        生成/切换 Claude Code 配置指向本地代理(改前备份 ~/.claude/settings.json)
  config codex         生成/切换 codex 配置(改前备份 ~/.codex/config.toml)
  config status        显示 claude/codex 当前指向(代理 or 直连)
  config restore [t]   恢复配置(优先回首次生成的 ORIGINAL 原始备份;没有则回最新备份)
  (无参数)            打印交互菜单

真实 key 禁进 git:本脚本不硬编码 key,运行时从 keys.txt / 代理运行实例读。
"""
import os, sys, re, subprocess, time, json, socket, http.client, shutil, signal, tempfile

IS_WIN = sys.platform == "win32"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 脚本同目录(找 sensenova-rotate-proxy.py / keys.txt)
_HOME = os.path.expanduser("~")
_DATA_DIR = os.path.join(_HOME, ".sensenova-proxy")
_LOG_DIR = os.path.join(_DATA_DIR, "logs")
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    pass
PID_FILE = os.path.join(_DATA_DIR, "proxy.pid")
PROXY_SCRIPT = os.path.join(_BASE_DIR, "sensenova-rotate-proxy.py")
CTL_LOG = os.path.join(_LOG_DIR, "proxy-ctl.log")
DEFAULT_PORT = int(os.environ.get("TTP_PORT", "8899"))


def _port():
    return int(os.environ.get("TTP_PORT", "8899"))


def _echo(s):
    print(s)
    sys.stdout.flush()


def _read_pid():
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _proc_alive(pid):
    if pid is None:
        return False
    if IS_WIN:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "PID eq %d" % pid, "/NH", "/FO", "CSV"],
                stderr=subprocess.DEVNULL, creationflags=0x08000000).decode(errors="replace")
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _pid_cmdline(pid):
    """取 pid 的完整命令行;取不到返回 None(调用方据此拒绝误杀)。"""
    try:
        if IS_WIN:
            try:
                out = subprocess.check_output(
                    ["wmic", "process", "where", "processid=%d" % pid, "get", "commandline"],
                    stderr=subprocess.DEVNULL, creationflags=0x08000000).decode(errors="replace")
                rows = [l.strip() for l in out.splitlines()
                        if l.strip() and l.strip().lower() != "commandline"]
                if rows:
                    return " ".join(rows)
            except Exception:
                pass
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid],
                    stderr=subprocess.DEVNULL, creationflags=0x08000000).decode(errors="replace")
                return out.strip() or None
            except Exception:
                return None
        out = subprocess.check_output(["ps", "-o", "command=", "-p", str(pid)],
                                      stderr=subprocess.DEVNULL).decode(errors="replace")
        return out.strip() or None
    except Exception:
        return None


def _is_proxy_cmdline(cmdline):
    """命令行为空(读不到)时返回 False = 不敢认定,拒绝杀。"""
    low = (cmdline or "").lower()
    return "sensenova-rotate-proxy" in low or "sensenova-proxy.exe" in low


def _port_listening(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _keys_txt_path():
    """返回首个存在的 keys.txt 路径;都没有返回同目录 keys.txt(供编辑/报错)。"""
    cand = [os.path.join(_BASE_DIR, "keys.txt"), os.path.join(_DATA_DIR, "keys.txt")]
    for p in cand:
        if os.path.exists(p):
            return p
    return cand[0]


def _load_keys_from_file(path):
    keys = []
    try:
        # utf-8-sig:去 Windows 记事本写入的 UTF-8 BOM(否则首行 key 带 BOM 变垃圾 key)
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                keys.append(line)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return keys


def cmd_start():
    port = _port()
    if _port_listening(port):
        _echo("端口 %d 已被占用(可能代理已在跑)。先 stop 或换 TTP_PORT。" % port)
        return 1
    if not os.path.exists(PROXY_SCRIPT):
        _echo("找不到代理脚本: %s" % PROXY_SCRIPT)
        return 1
    env = os.environ.copy()
    # 日志重定向到文件(追加)
    try:
        logf = open(CTL_LOG, "ab", buffering=0)
    except Exception:
        logf = subprocess.DEVNULL
    kwargs = {}
    if IS_WIN:
        # CREATE_NO_WINDOW + DETACHED_PROCESS,后台不弹窗
        kwargs["creationflags"] = 0x08000000 | 0x00000008
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            [sys.executable, PROXY_SCRIPT],
            cwd=_BASE_DIR, env=env,
            stdout=logf, stderr=subprocess.STDOUT,
            **kwargs)
    except Exception as e:
        _echo("启动失败: %s" % e)
        return 1
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    # 等最多 4s 起来
    for _ in range(20):
        if _port_listening(port):
            break
        time.sleep(0.2)
    if _port_listening(port):
        _echo("代理已启动: PID=%d, 监听 http://127.0.0.1:%d, 日志 %s" % (proc.pid, port, CTL_LOG))
    else:
        _echo("代理进程已拉起(PID=%d)但端口 %d 暂未监听,查看日志 %s" % (proc.pid, port, CTL_LOG))
    return 0


def cmd_stop():
    pid = _read_pid()
    if pid is None:
        _echo("无 PID 文件(%s),代理未通过本工具启动。" % PID_FILE)
        return 1
    if not _proc_alive(pid):
        _echo("PID %d 进程已不在,清理 PID 文件。" % pid)
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return 0
    # S2:杀前核命令行,防 PID 复用/stale PID 误杀无关进程(Windows taskkill /T 更会杀整棵树)
    cmdline = _pid_cmdline(pid)
    if not _is_proxy_cmdline(cmdline):
        _echo("PID %d 不是商汤轮换代理(cmdline: %s),拒绝停止以免误杀无关进程。已清理该 PID 文件。"
              % (pid, cmdline or "(读取失败)"))
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return 1
    try:
        if IS_WIN:
            subprocess.check_call(["taskkill", "/PID", str(pid), "/T", "/F"],
                                  creationflags=0x08000000)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        _echo("停止失败: %s" % e)
        return 1
    # 等 3s 退出
    for _ in range(15):
        if not _proc_alive(pid):
            break
        time.sleep(0.2)
    if _proc_alive(pid):
        _echo("SIGTERM 后 PID %d 仍在,尝试强杀。" % pid)
        try:
            if IS_WIN:
                subprocess.check_call(["taskkill", "/PID", str(pid), "/T", "/F"],
                                      creationflags=0x08000000)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    port = _port()
    if _port_listening(port):
        _echo("警告:停止后端口 %d 仍在监听(可能另一实例在跑)。" % port)
    else:
        _echo("已停止,端口 %d 已释放。" % port)
    return 0


def cmd_status():
    pid = _read_pid()
    port = _port()
    keys = _load_keys_from_file(_keys_txt_path())
    running = False
    if pid is not None:
        running = _proc_alive(pid)
    listen = _port_listening(port)
    _echo("=== sensenova-proxy 状态 ===")
    _echo("PID 文件: %s" % (PID_FILE if pid is not None else "(无)"))
    _echo("进程存活: %s" % ("是 PID=%d" % pid if running else "否"))
    _echo("端口 %d 监听: %s" % (port, "是" if listen else "否"))
    _echo("keys.txt: %s, key 数=%d" % (_keys_txt_path(), len(keys)))
    _echo("代理脚本: %s" % (PROXY_SCRIPT + (" (存在)" if os.path.exists(PROXY_SCRIPT) else " (缺失!)")))
    return 0


def cmd_keys():
    path = _keys_txt_path()
    if not os.path.exists(path):
        ex = os.path.join(_BASE_DIR, "keys.txt.example")
        if os.path.exists(ex):
            shutil.copy(ex, path)
            _echo("已从 keys.txt.example 复制一份到 %s" % path)
        else:
            # 建空文件
            open(path, "w").close()
            _echo("已新建空 %s" % path)
    editor = os.environ.get("EDITOR")
    if not editor:
        if IS_WIN:
            editor = "notepad"
        else:
            for cand in ("nano", "vim", "vi"):
                if shutil.which(cand):
                    editor = cand
                    break
            if not editor:
                editor = "vi"
    _echo("用 %s 打开 %s(保存后退出编辑器)" % (editor, path))
    try:
        subprocess.call([editor, path])
    except Exception as e:
        _echo("打开编辑器失败(%s),手动编辑: %s" % (e, path))
    keys = _load_keys_from_file(path)
    _echo("当前 key 数: %d" % len(keys))
    return 0


def cmd_test():
    port = _port()
    keys = _load_keys_from_file(_keys_txt_path())
    if not keys:
        _echo("keys.txt 无 key,无法测试。先 sensenova-proxy-ctl.py keys 添加。")
        return 1
    if not _port_listening(port):
        _echo("代理未在 %d 监听,先 start。" % port)
        return 1
    body = json.dumps({
        "model": "glm-5.2",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "ping"}],
    })
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        conn.request("POST", "/v1/messages", body=body, headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            # S7:只发 authorization(与 Claude Code 真实接入一致);不再发 x-api-key,
            # 否则上游若优先 x-api-key,test 通过也证明不了轮换生效。
            "authorization": "Bearer " + keys[0],
        })
        resp = conn.getresponse()
        data = resp.read().decode(errors="replace")
        _echo("HTTP %d, body 前 300 字: %s" % (resp.status, data[:300]))
        return 0 if resp.status == 200 else 2
    except Exception as e:
        _echo("请求失败: %s" % e)
        return 1
    finally:
        conn.close()


# ───────────── config 子命令 ─────────────
def _backup_path(path):
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path + ".bak-sensenova-proxyctl-" + ts


def _original_bak_path(path):
    """首次 config 时固存的原始备份;后续 config 再多次也不覆盖,restore 优先回它。"""
    return path + ".bak-sensenova-proxyctl-ORIGINAL"


def _looks_already_proxied(path):
    """当前文件是否已是本工具写过的代理配置(codex provider 段 / claude 的 127.0.0.1 base_url)。

    S-2:迁移用户(老版本已 config 过)当前文件本身就带代理配置,拿它当"原始"备份,
    restore 就回不到真正原始 —— 所以先识别出来,不标 ORIGINAL。
    """
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except OSError:
        return False
    if re.search(r"^[ \t]*\[\s*model_providers\.sensenova\s*\]", text, re.M):
        return True
    # 只认 ANTHROPIC_BASE_URL 自己的值(避免 settings 里别的字段碰巧含 127.0.0.1 被误判 ⇒ 白丢 ORIGINAL)
    return re.search(r'"ANTHROPIC_BASE_URL"\s*:\s*"[^"]*127\.0\.0\.1', text) is not None


def _backup_before_write(path):
    """写前备份:首次额外固存 ORIGINAL,并总是留一份带时间戳备份(便于反查)。

    返回 (made_original, 时间戳备份路径)。
    S-2:当前文件若已是代理配置,不创建 ORIGINAL(否则"原始"是假话),只留时间戳备份 + 提示。
    """
    orig = _original_bak_path(path)
    made = False
    if not os.path.exists(orig):
        if _looks_already_proxied(path):
            _echo("当前配置已是代理配置(不是原始),不创建 ORIGINAL 原始备份;"
                  "原始配置不可追回,请自行确认。已另存时间戳备份,可用 config restore 回退到它。")
        else:
            shutil.copy2(path, orig)
            made = True
    bak = _backup_path(path)
    shutil.copy2(path, bak)
    return made, bak


def _atomic_write(path, content_bytes):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)  # S3:~/.codex 等目录不存在时先建,别在 mkstemp 抛 Traceback
    fd, tmp = tempfile.mkstemp(prefix=".sensenova-ctl-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content_bytes)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _settings_path():
    return os.path.expanduser("~/.claude/settings.json")


def _codex_path():
    return os.path.expanduser("~/.codex/config.toml")


def _toml_join(lines, content):
    """按原文件换行风格(LF/CRLF)拼回,避免改 Windows 配置时整文件换行风格被换掉。

    ⚠️ 调用方读文件时必须 `open(..., newline="")`:文本模式默认的 universal newline
    已在读入时把 CRLF 统一成 LF,那样这里就永远判不出 CRLF(死代码,S-1)。
    """
    nl = "\r\n" if "\r\n" in content else "\n"
    return nl.join(lines)


# 段头判定:TOML 段头必须独占一行,行首(可含缩进)是 `[` 即为段头 ——
# `[a]` / `[[a]]` / `[plugins."x@y"]` / `[projects."/abs/path"]` / `[quoted."中文 段"]` 全满足。
# 故意不用"字符白名单"正则:白名单会把带引号/`@`/`/`/中文的真实段头当普通行,
# 替换或删段时把紧随其后的段整段吞掉(F-1 回归,真实 codex config 里这类段头 14 个)。
# 裸数组值 `[1, 2]` 不会独占行首(TOML 要求 `key = [...]`),故无歧义。
def _is_section_header(line):
    return line.lstrip().startswith("[")


def _replace_toml_table(content, header, new_block):
    """替换(或追加)一个 TOML 表的内容行。

    只吞该表自身行:遇到下一个段头(行首 `[`,含 `[[数组表]]`/带引号段)立即停
    ⇒ 既不误伤后续表(S4),也不吞带引号/含 @ / 中文的真实段头(F-1)。
    """
    lines = content.splitlines()
    header_re = re.compile(r"^\s*\[%s\]\s*(#.*)?$" % re.escape(header))
    out, i, found = [], 0, False
    while i < len(lines):
        if header_re.match(lines[i]):
            found = True
            j = i + 1
            while j < len(lines) and not _is_section_header(lines[j]):
                j += 1
            out.extend(new_block.rstrip("\r\n").splitlines())
            if j < len(lines) and (not out or out[-1].strip() != ""):
                out.append("")  # 与下一个段之间留空行,保持原文件排版风格
            i = j
            continue
        out.append(lines[i])
        i += 1
    if not found:
        out.extend(new_block.rstrip("\r\n").splitlines())
    return _toml_join(out, content).rstrip() + ("\r\n" if "\r\n" in content else "\n")


def _set_top_level_key(content, key, value):
    """只在顶层区(文件开头到第一个段头之前)设置 key = "value"。

    进入任何 `[...]`/`[[...]]` 段后一律不动 ⇒ 不误改 [profiles.*] 等段内的同名键(F3)。
    """
    lines = content.splitlines()
    end = len(lines)
    for i, line in enumerate(lines):
        if _is_section_header(line):
            end = i
            break
    key_re = re.compile(r"^\s*%s\s*=" % re.escape(key))
    out, replaced = [], False
    for i, line in enumerate(lines):
        if i < end and key_re.match(line):
            out.append('%s = "%s"' % (key, value))
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, '%s = "%s"' % (key, value))
    return _toml_join(out, content).rstrip() + ("\r\n" if "\r\n" in content else "\n")


def _top_level_value(content, key):
    """读顶层 key 的字符串值;只扫第一个段头之前,读不到返回 None。"""
    val_re = re.compile(r"^\s*%s\s*=\s*\"([^\"]*)\"" % re.escape(key))
    for line in content.splitlines():
        if _is_section_header(line):
            break
        m = val_re.match(line)
        if m:
            return m.group(1)
    return None


def _config_claude():
    path = _settings_path()
    port = _port()
    keys = _load_keys_from_file(_keys_txt_path())
    if not keys:
        _echo("keys.txt 无 key,先 sensenova-proxy-ctl.py keys 添加。")
        return 1
    base_url = "http://127.0.0.1:%d" % port
    token = keys[0]
    # 读现有
    data = {}
    if os.path.exists(path):
        made, bak = _backup_before_write(path)
        _echo("已备份: %s%s" % (bak, "(另存原始备份 ORIGINAL)" if made else ""))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _echo("读取现有 settings.json 失败(%s),将基于空对象写入。" % e)
            data = {}
    else:
        _echo("settings.json 不存在,新建。")
    env = data.get("env", {})
    if not isinstance(env, dict):
        env = {}
    changed = []
    updates = {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_MODEL": "glm-5.2",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.2",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.2",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.2",
        "ANTHROPIC_DEFAULT_FABLE_MODEL": "glm-5.2",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": "glm-5.2",
        "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "glm-5.2",
        "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": "glm-5.2",
        "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME": "glm-5.2",
        "CLAUDE_CODE_SUBAGENT_MODEL": "glm-5.2",
    }
    for k, v in updates.items():
        env[k] = v
        changed.append(k)
    data["env"] = env
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
    _echo("已写入 %s" % path)
    _echo("更新键: %s" % ", ".join(changed))
    _echo("BASE_URL=%s  MODEL=glm-5.2" % base_url)
    _echo("重启 Claude Code 生效。")
    return 0


def _config_codex():
    path = _codex_path()
    port = _port()
    keys = _load_keys_from_file(_keys_txt_path())
    if not keys:
        _echo("keys.txt 无 key,先 sensenova-proxy-ctl.py keys 添加。")
        return 1
    base_url = "http://127.0.0.1:%d/v1" % port
    token = keys[0]
    # codex 0.154.0 起 wire_api="chat" 已废弃(加载即报错);实测 "responses" 与商汤
    # /v1/responses 协议兼容(codex exec 经代理端到端跑通),故固定 responses。
    wire_api = "responses"
    had_existing = os.path.exists(path)
    if had_existing:
        made, bak = _backup_before_write(path)
        _echo("已备份: %s%s" % (bak, "(另存原始备份 ORIGINAL)" if made else ""))
        # newline="":保住原文件 CRLF,否则文本模式已把它统一成 LF,写回就换了 Windows 换行风格(S-1)
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            content = f.read()
    else:
        _echo("config.toml 不存在,新建。")
        content = ""
    new_block = (
        "\n[model_providers.sensenova]\n"
        "name = \"sensenova\"\n"
        "base_url = \"%s\"\n"
        "wire_api = \"%s\"\n"
        "experimental_bearer_token = \"%s\"\n"
    ) % (base_url, wire_api, token)
    # ① 替换/追加 sensenova provider 段(段感知,不吞 [[数组表]] 与后续段)
    content = _replace_toml_table(content, "model_providers.sensenova", new_block)
    # ② 顶层 model_provider 指向 sensenova(否则 codex 仍走默认 openai,请求不发代理)
    content = _set_top_level_key(content, "model_provider", "sensenova")
    # ③ 顶层 model:只在顶层区改,不动 [profiles.*] 等段内的 model
    content = _set_top_level_key(content, "model", "glm-5.2")
    _atomic_write(path, content.encode("utf-8"))
    _echo("已写入 %s" % path)
    _echo("provider sensenova: base_url=%s wire_api=%s" % (base_url, wire_api))
    _echo("顶层 model_provider = sensenova, model = glm-5.2(原有文件已备份)")
    _echo("重启 codex 生效。")
    return 0


def _config_status():
    port = _port()
    expect = "127.0.0.1:%d" % port
    # claude
    sp = _settings_path()
    claude_state = "未配置/直连"
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                d = json.load(f)
            base = (d.get("env") or {}).get("ANTHROPIC_BASE_URL", "")
            if expect in base:
                claude_state = "走代理 (%s)" % base
            else:
                claude_state = "直连/其它 (%s)" % base
        except Exception as e:
            claude_state = "读取失败: %s" % e
    _echo("claude: %s" % claude_state)
    # codex
    cp = _codex_path()
    codex_state = "未配置"
    if os.path.exists(cp):
        try:
            with open(cp, "r", encoding="utf-8-sig") as f:
                content = f.read()
            m = re.search(r"\[model_providers\.sensenova\][\s\S]*?base_url\s*=\s*\"([^\"]+)\"", content)
            provider = _top_level_value(content, "model_provider")
            if m and expect in m.group(1) and provider == "sensenova":
                codex_state = "走代理 (%s)" % m.group(1)
            elif m and expect in m.group(1):
                codex_state = "provider 段已配但顶层 model_provider=%s(请求不会走代理)" % (provider or "(缺省=openai)")
            elif m:
                codex_state = "sensenova provider 存在但指向 %s" % m.group(1)
            else:
                codex_state = "未配 sensenova provider(直连)"
        except Exception as e:
            codex_state = "读取失败: %s" % e
    _echo("codex: %s" % codex_state)
    return 0


def _config_restore(target):
    targets = [target] if target else ["claude", "codex"]
    done = 0
    for t in targets:
        if t == "claude":
            path = _settings_path()
        elif t == "codex":
            path = _codex_path()
        else:
            _echo("未知 config 目标: %s(应为 claude|codex)" % t)
            continue
        d = os.path.dirname(path) or "."
        base = os.path.basename(path)
        import glob
        # 优先回首次固存的 ORIGINAL;连跑多次 config 后仍能回到最初原始配置(S1)。
        orig = _original_bak_path(path)
        src = ""
        if os.path.exists(orig):
            src = orig
        else:
            baks = [b for b in sorted(glob.glob(os.path.join(d, base + ".bak-sensenova-proxyctl-*")))
                    if not b.endswith("-ORIGINAL")]
            if baks:
                src = baks[-1]
                _echo("[%s] 无 ORIGINAL 原始备份,回退到最近时间戳备份(可能是旧版工具写的代理配置,不保证是真正的原始配置)。" % t)
        if not src:
            _echo("[%s] 无备份文件。" % t)
            continue
        _atomic_write(path, open(src, "rb").read())
        _echo("[%s] 已从 %s 恢复。" % (t, src))
        done += 1
    return 0 if done else 1


def cmd_config(args):
    if not args:
        _echo("用法: config [claude|codex|status|restore [claude|codex]]")
        return 1
    sub = args[0]
    if sub == "claude":
        return _config_claude()
    if sub == "codex":
        return _config_codex()
    if sub == "status":
        return _config_status()
    if sub == "restore":
        return _config_restore(args[1] if len(args) > 1 else None)
    _echo("未知 config 子命令: %s" % sub)
    return 1


def interactive_menu():
    _echo("=== sensenova-proxy 控制台(端口 %d)===" % _port())
    _echo("1.启动  2.停止  3.状态  4.编辑key  5.测试  6.配置claude  7.配置codex  8.配置状态  9.恢复配置  0.退出")
    try:
        choice = input("选择: ").strip()
    except (EOFError, KeyboardInterrupt):
        return 0
    mapping = {
        "1": cmd_start, "2": cmd_stop, "3": cmd_status, "4": cmd_keys, "5": cmd_test,
        "6": lambda: cmd_config(["claude"]),
        "7": lambda: cmd_config(["codex"]),
        "8": lambda: cmd_config(["status"]),
        "9": lambda: cmd_config(["restore"]),
        "0": lambda: 0,
    }
    fn = mapping.get(choice)
    if fn is None:
        _echo("无效选择")
        return 1
    return fn() if callable(fn) else 0


def main():
    args = sys.argv[1:]
    if not args:
        return interactive_menu()
    cmd = args[0]
    rest = args[1:]
    if cmd == "start":
        return cmd_start()
    if cmd == "stop":
        return cmd_stop()
    if cmd == "status":
        return cmd_status()
    if cmd == "keys":
        return cmd_keys()
    if cmd == "test":
        return cmd_test()
    if cmd == "config":
        return cmd_config(rest)
    _echo(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
