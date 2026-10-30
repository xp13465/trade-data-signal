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
  config restore [t]   从最新备份恢复(claude|codex,不填则都恢复)
  (无参数)            打印交互菜单

真实 key 禁进 git:本脚本不硬编码 key,运行时从 keys.txt / 代理运行实例读。
"""
import os, sys, subprocess, time, json, socket, http.client, shutil, signal, tempfile

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
        with open(path) as f:
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
            "x-api-key": keys[0],
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


def _atomic_write(path, content_bytes):
    d = os.path.dirname(path) or "."
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
        bak = _backup_path(path)
        shutil.copy2(path, bak)
        _echo("已备份: %s" % bak)
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
    wire_api = "chat"  # 默认 chat(OpenAI 兼容);限流恢复后实测校准
    had_existing = os.path.exists(path)
    if had_existing:
        bak = _backup_path(path)
        shutil.copy2(path, bak)
        _echo("已备份: %s" % bak)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        _echo("config.toml 不存在,新建。")
        content = ""
    # 用 tomllib 读现有顶层 model/model_provider(只读不改结构,Python 3.11+)
    new_block = (
        "\n[model_providers.sensenova]\n"
        "name = \"sensenova\"\n"
        "base_url = \"%s\"\n"
        "wire_api = \"%s\"\n"
        "experimental_bearer_token = \"%s\"\n"
    ) % (base_url, wire_api, token)
    # 替换或追加 sensenova provider 段
    import re
    pattern = re.compile(r"\n\[model_providers\.sensenova\][\s\S]*?(?=\n\[[^\]]+\]\n|\Z)", re.MULTILINE)
    if pattern.search("\n" + content):
        content = pattern.sub(new_block.rstrip() + "\n", "\n" + content).lstrip("\n")
    else:
        content = (content.rstrip() + "\n" + new_block).lstrip("\n")
    # 顶层 model 行:有则替换,无则在文件开头加
    model_pattern = re.compile(r"^model\s*=.*$", re.MULTILINE)
    model_line = "model = \"glm-5.2\""
    if model_pattern.search(content):
        content = model_pattern.sub(model_line, content)
    else:
        content = model_line + "\n" + content
    _atomic_write(path, content.encode("utf-8"))
    _echo("已写入 %s" % path)
    _echo("provider sensenova: base_url=%s wire_api=%s" % (base_url, wire_api))
    _echo("顶层 model = glm-5.2(原有 model 行已备份)")
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
            with open(cp, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            m = re.search(r"\[model_providers\.sensenova\][\s\S]*?base_url\s*=\s*\"([^\"]+)\"", content)
            if m and expect in m.group(1):
                codex_state = "走代理 (%s)" % m.group(1)
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
        baks = sorted(glob.glob(os.path.join(d, base + ".bak-sensenova-proxyctl-*")))
        if not baks:
            _echo("[%s] 无备份文件。" % t)
            continue
        latest = baks[-1]
        _atomic_write(path, open(latest, "rb").read())
        _echo("[%s] 已从 %s 恢复。" % (t, latest))
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
