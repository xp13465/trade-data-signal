#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
easytrader 增强版服务端 - Token 鉴权 + 内置测试面板 + 健康检查

在 easytrader 原版 server.py 基础上新增:
  1. 固定 Token 鉴权 (X-Token 请求头 或 ?token= 查询参数)
  2. 健康检查 /health (免 token, 快速验证服务存活)
  3. 内置测试面板 / (浏览器打开即用)
  4. CORS 支持 (Mac 浏览器跨域调用无障碍)
  5. 保留 easytrader 原有全部 API 接口

启动: py easytrader_server_auth.py
测试: 浏览器打开 http://localhost:1430/
"""

import os
import json
import time
import pywinauto
from flask import request, jsonify, Response
from easytrader.server import app, global_store, error_handle as _orig_error_handle
import easytrader
import easytrader.api as _et_api
from easytrader.clienttrader import ClientTrader

# ==================== 兼容性补丁 ====================
# 1. easytrader 0.23.x 把 ClientTrader.prepare 重命名为 connect,
#    但 server.py 仍然调用 user.prepare(). 这里把 prepare 重新指向 connect.
# 2. 增强 connect 支持 pid 参数, 用于多账户场景按 PID 连接特定 xiadan.exe 实例.
_orig_connect = ClientTrader.connect

def _patched_connect(self, exe_path=None, **kwargs):
    pid = kwargs.pop("pid", None)
    if pid:
        self._app = pywinauto.Application().connect(process=int(pid), timeout=10)
        self._close_prompt_windows()
        self._main = self._app.top_window()
        self._init_toolbar()
    else:
        return _orig_connect(self, exe_path=exe_path, **kwargs)

ClientTrader.connect = _patched_connect
ClientTrader.prepare = _patched_connect

# ==================== 配置区 ====================
# 配置优先级: 环境变量 > easytrader_local.json(本地, 不进 git) > config.json(模板, 进 git) > 默认值
# 真实 token 放 easytrader_local.json (已 .gitignore), config.json 的 token 留空作模板.
# 首次运行若 config.json 不存在会自动生成模板(此时 token 为空, 需在 easytrader_local.json 配置).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")
LOCAL_CONFIG_PATH = os.path.join(_BASE_DIR, "easytrader_local.json")


def _read_json(path):
    """读 JSON 文件, 失败返回空 dict 并告警."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[warn] 读取 %s 失败: %s" % (path, e))
        return {}


def load_config():
    """读取配置.

    优先级: easytrader_local.json(本地, 不进 git) > config.json(模板, 进 git) > 默认值.
    token 在 config.json 里是空模板, 真实 token 放 easytrader_local.json 覆盖.
    首次运行会自动生成 config.json 模板(若不存在).
    """
    defaults = {
        "token": "",
        "host": "0.0.0.0",
        "port": 1430,
        "exe_path": r"D:\同花顺软件\同花顺\同花顺\同花顺\xiadan.exe",
    }
    cfg = dict(defaults)
    # 1. config.json (模板, 进 git)
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
            print("[info] 已生成配置模板:", CONFIG_PATH,
                  "(token 为空模板, 请在 easytrader_local.json 配置真实 token)")
        except Exception as e:
            print("[warn] 生成 config.json 模板失败:", e)
    cfg.update({k: v for k, v in _read_json(CONFIG_PATH).items() if k in defaults})
    # 2. easytrader_local.json (本地真实配置, 不进 git) 覆盖模板
    if os.path.exists(LOCAL_CONFIG_PATH):
        cfg.update({k: v for k, v in _read_json(LOCAL_CONFIG_PATH).items() if k in defaults})
        print("[info] 已加载本地配置:", LOCAL_CONFIG_PATH)
    else:
        print("[info] 未找到 easytrader_local.json (本地配置, 不进 git). "
              "token 将为空, 请创建该文件配置真实 token, 见 README 第 6 节.")
    return cfg


CONFIG = load_config()
TOKEN = os.environ.get("EASYTRADER_TOKEN", CONFIG["token"])
HOST = os.environ.get("EASYTRADER_HOST", CONFIG["host"])
PORT = int(os.environ.get("EASYTRADER_PORT", CONFIG["port"]))
EXE_PATH = os.environ.get("EASYTRADER_EXE_PATH", CONFIG["exe_path"])

if not TOKEN:
    print("[error] 未配置 Token: config.json 为空模板, 请在 easytrader_local.json (本地, 不进 git) "
          "设置 \"token\" 字段, 或用环境变量 EASYTRADER_TOKEN. 见 README 第 6 节. "
          "(未配置前所有鉴权接口将返回 401)")
HTML_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "easytrader_test.html",
)

# ==================== 多账户存储 ====================
# global_store["accounts"] = [{"label": "券商名-账户名", "account": "资金账号", "hotkey": 1}, ...]
# global_store["active_account"]       = 当前活跃账户的 label
# global_store["active_account_number"] = 当前活跃账户的资金账号
# global_store["user"]            = ClientTrader 实例 (单连接)
global_store.setdefault("accounts", [])
global_store.setdefault("active_account", None)
global_store.setdefault("active_account_number", None)


def _get_active_user():
    if "user" not in global_store:
        raise KeyError("user")
    return global_store["user"]


# ==================== CORS 跨域支持 ====================
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Token"
    return resp


# ==================== Token 鉴权中间件 ====================
@app.before_request
def check_token():
    # CORS 预检直接放行
    if request.method == "OPTIONS":
        return "", 200

    # 公开路由: 测试页面 + 健康检查 (不验证 token)
    if request.path in ("/", "/test", "/health"):
        return

    # 其余所有 API 必须携带正确 token
    token = request.headers.get("X-Token") or request.args.get("token", "")
    if token != TOKEN:
        return jsonify({"error": "invalid or missing token"}), 401


# ==================== 健康检查 ====================
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "easytrader-enhanced-server",
        "logged_in": "user" in global_store,
        "accounts": len(global_store.get("accounts", [])),
        "active": global_store.get("active_account"),
        "active_account": global_store.get("active_account_number"),
        "port": PORT,
    })


# ==================== 多账户管理 (同花顺 xiadan.exe 单进程多账户) ====================
# xiadan.exe 不允许多实例. 单实例内通过顶栏账户下拉 (ComboBox 2322) 切换账户.
# 切换方式: 点击账户 ComboBox 打开下拉列表 (ComboLBox), 按坐标点击列表项.
# 注: Alt+N 合成键盘输入在本机窗口状态下完全失效, 故改用下拉点击, 更稳定.
# 因此: 1 个连接 (user) + 多个账户标签, 切换时只改活跃标签, 不创建新连接.

from pywinauto import keyboard as _pa_keyboard
from pywinauto import mouse as _mouse

# 存储账户标签和热键索引的映射
# global_store["accounts"] = [{"label": "券商名-账户名", "account": "资金账号", "hotkey": 1}, ...]
global_store.setdefault("accounts", [])
global_store.setdefault("active_account", None)
global_store.setdefault("active_account_number", None)


def _read_account_dropdown():
    """读取 xiadan.exe 顶栏账户下拉框当前选中账户名 (ComboBox control_id=2322)"""
    user = global_store.get("user")
    if not user:
        return None
    try:
        app = user._app
        # 定位主窗口: 找含 id=2322 的窗口
        main = None
        for w in app.windows():
            try:
                for ch in w.descendants():
                    if ch.class_name() == "ComboBox":
                        try:
                            cid = ch.control_id()
                        except Exception:
                            cid = 0
                        if cid == 2322:
                            main = w
                            break
            except Exception:
                pass
            if main:
                break
        if not main:
            main = user._main
        for child in main.descendants():
            if child.class_name() == "ComboBox" and child.control_id() == 2322:
                return child.window_text()
    except Exception:
        pass
    return None


def _read_account_number():
    """读取 xiadan.exe 当前资金账号 (ComboBox control_id=1711).
    定位主窗口: 找含 id=1711 的窗口, 避免 app.top_window() 返回子面板.
    """
    user = global_store.get("user")
    if not user:
        return None
    try:
        app = user._app
        main = None
        for w in app.windows():
            try:
                for ch in w.descendants():
                    if ch.class_name() == "ComboBox":
                        try:
                            cid = ch.control_id()
                        except Exception:
                            cid = 0
                        if cid == 1711:
                            main = w
                            break
            except Exception:
                pass
            if main:
                break
        if not main:
            main = user._main
        for child in main.descendants():
            if child.class_name() == "ComboBox":
                try:
                    cid = child.control_id()
                except Exception:
                    cid = 0
                txt = child.window_text().strip()
                if cid == 1711 and txt:
                    return txt
    except Exception:
        pass
    return None


def _read_account_info():
    """同时读取账户标签和资金账号"""
    return {
        "label": _read_account_dropdown(),
        "account": _read_account_number(),
    }


def _find_main_window(app):
    """扫描所有窗口, 找含资金账号 ComboBox (id=1711) 或标签 ComboBox (id=2322) 的主窗口.
    app.top_window() 可能返回子面板/弹窗, 不可靠.
    返回 HwndWrapper 或 None.
    """
    try:
        for w in app.windows():
            try:
                for child in w.descendants():
                    if child.class_name() == "ComboBox":
                        try:
                            cid = child.control_id()
                        except Exception:
                            cid = 0
                        if cid in (1711, 2322):
                            return w
            except Exception:
                pass
    except Exception:
        pass
    return None


# ==================== ComboBox 下拉切换 (替代 Alt+N, 兼容性更好) ====================
# 实测: 同花顺 xiadan.exe 在某窗口状态下 Alt+N 合成键盘输入完全失效,
# 但点击账户 ComboBox(control_id=2322) 打开下拉列表 (ComboLBox) 后,
# 按坐标点击列表项可稳定切换账户, 且会正确触发 xiadan 的账户切换 (资金账号 1711 同步变化).
# 因此切换/发现账户统一改用"打开下拉 -> 坐标点击列表项"方式.

def _find_combo2322(win):
    """定位账户标签 ComboBox (control_id=2322)."""
    try:
        for c in win.descendants():
            try:
                if c.class_name() == "ComboBox" and c.control_id() == 2322:
                    return c
            except Exception:
                pass
    except Exception:
        pass
    return None


def _find_combolb(app):
    """找当前可见的 ComboLBox (下拉列表). 返回 HwndWrapper 或 None."""
    try:
        for w in app.windows():
            try:
                if w.class_name() == "ComboLBox" and w.is_visible():
                    return w
            except Exception:
                pass
    except Exception:
        pass
    return None


def _ensure_dropdown_open(app, win):
    """确保账户下拉已打开, 返回 ComboLBox; 已打开则直接返回, 否则点击箭头打开."""
    cl = _find_combolb(app)
    if cl:
        return cl
    cb = _find_combo2322(win)
    if not cb:
        return None
    rect = cb.rectangle()
    for _ in range(4):
        try:
            win.set_focus()
            time.sleep(0.3)
            _mouse.click(coords=(rect.right - 8, rect.top + rect.height() // 2))
            time.sleep(0.9)
        except Exception:
            pass
        cl = _find_combolb(app)
        if cl:
            return cl
        time.sleep(0.3)
    return None


def _click_dropdown_item(app, win, idx):
    """打开账户下拉并点击第 idx 项 (0-based), 完成账户切换. 返回是否成功."""
    cl = _ensure_dropdown_open(app, win)
    if not cl:
        return False
    cb = _find_combo2322(win)
    try:
        count = cb.item_count() if cb else (idx + 2)
    except Exception:
        count = idx + 2
    if not count or count < 1:
        count = idx + 2
    r = cl.rectangle()
    item_h = (r.bottom - r.top) / count
    x = r.left + (r.right - r.left) // 2
    y = r.top + int((idx + 0.5) * item_h)
    try:
        _mouse.click(coords=(x, y))
    except Exception:
        return False
    time.sleep(1.2)
    return True


def _close_any_popup(win):
    """关闭任何意外弹出的对话框 (#32770), 防止卡死. 返回是否关闭了弹窗."""
    closed = False
    try:
        for c in win.descendants():
            if c.class_name() == "#32770":
                for b in c.descendants():
                    try:
                        if b.class_name() == "Button" and b.window_text() in ("取消", "关闭", "确定", "OK"):
                            b.click()
                            time.sleep(0.3)
                            closed = True
                    except Exception:
                        pass
    except Exception:
        pass
    return closed


def _discover_accounts():
    """通过打开账户下拉框 (ComboBox 2322) 读取并切换账户, 发现所有账户.

    做法:
      1. 打开下拉 -> 用 pywinauto 读 item_texts()/item_count() 得到全部选项
         (末尾一项是"编辑账户", 不是真实账户, 排除).
      2. 逐个点击账户项 (坐标点击 ComboLBox 列表项, 会真实触发 xiadan 切换),
         读取该账户的资金账号 (ComboBox 1711).
      3. 切回初始账户.

    相比旧版 Alt+N 枚举: 不依赖合成键盘 (本机已失效), 也不会误按到
    (账户数+1) 的"编辑账户"按钮而弹出备注框导致卡死.
    """
    user = global_store.get("user")
    if not user:
        return []
    try:
        app = user._app
        # 不用 user._main (可能过期), 每次重新定位主窗口
        win = _find_main_window(app) or user._main
        win.set_focus()
        time.sleep(0.8)  # 等窗口稳定
    except Exception:
        return []

    initial_label = _read_account_dropdown()

    # 打开下拉并读取选项
    cl = _ensure_dropdown_open(app, win)
    cb = _find_combo2322(win)
    if not cl or not cb:
        # 兜底: 至少记录当前账户
        info = _read_account_info()
        if info["label"]:
            return [(info["label"], {"hotkey": 1, "account": info["account"]})]
        return []
    try:
        texts = cb.item_texts()
        count = cb.item_count()
    except Exception:
        info = _read_account_info()
        if info["label"]:
            return [(info["label"], {"hotkey": 1, "account": info["account"]})]
        return []

    # 账户 = 排除"编辑账户"/"账户管理"等编辑类项 (通常在末尾)
    acct_texts = [t for t in texts if t and "编辑" not in t and "管理" not in t]
    if not acct_texts:
        acct_texts = texts[:max(len(texts) - 1, 1)]

    found = {}
    for i, t in enumerate(acct_texts):
        _click_dropdown_item(app, win, i)
        time.sleep(1.3)
        _close_any_popup(win)
        label = _read_account_dropdown()
        acct = _read_account_number()
        # 校验: 实际标签与预期不符时再尝试一次 (点击可能落在行间隙)
        if label != t:
            _click_dropdown_item(app, win, i)
            time.sleep(1.3)
            _close_any_popup(win)
            label = _read_account_dropdown()
            acct = _read_account_number()
        found[t] = {"hotkey": i + 1, "account": acct}

    # 切回初始账户
    if initial_label and initial_label in found:
        _click_dropdown_item(app, win, found[initial_label]["hotkey"] - 1)
        time.sleep(1.2)
        _close_any_popup(win)

    sorted_acc = sorted(found.items(), key=lambda x: x[1]["hotkey"])
    return sorted_acc


@app.route("/accounts")
def list_accounts():
    """列出同花顺内已配置的所有账户 (按 Alt+N 顺序)"""
    items = global_store.get("accounts", [])
    active = global_store.get("active_account")
    active_acct = global_store.get("active_account_number")
    info = [
        {
            "label": a["label"],
            "account": a.get("account"),
            "hotkey": a["hotkey"],
            "active": a["label"] == active,
        }
        for a in items
    ]
    return jsonify({
        "accounts": info,
        "active": active,
        "active_account": active_acct,
        "count": len(info),
        "switch_via": "Alt+hotkey / account=资金账号 / label=标签",
    }), 200


@app.route("/accounts/refresh", methods=["POST"])
def refresh_accounts():
    """从 xiadan.exe 下拉框重新读取账户列表"""
    if "user" not in global_store:
        return jsonify({"error": "not logged in"}), 400
    raw = _discover_accounts()  # [(label, {"hotkey": n, "account": "xxx"}), ...]
    accounts = [
        {"label": label, "hotkey": v["hotkey"], "account": v.get("account")}
        for label, v in raw
        if v["hotkey"] > 0 and "编辑" not in label
    ]
    global_store["accounts"] = accounts

    info = _read_account_info()
    current = info["label"]
    current_acct = info["account"]
    if current:
        global_store["active_account"] = current
        global_store["active_account_number"] = current_acct
        if not any(a["label"] == current for a in accounts):
            accounts.insert(0, {"label": current, "hotkey": 0, "account": current_acct})

    return jsonify({
        "accounts": accounts,
        "active": global_store.get("active_account"),
        "active_account": global_store.get("active_account_number"),
        "count": len(accounts),
    }), 200


@app.route("/switch")
def switch_account():
    """切换账户. 接受 hotkey=N / label=账户标签 / account=资金账号"""
    if "user" not in global_store:
        return jsonify({"error": "not logged in"}), 400

    accounts = global_store.get("accounts", [])
    hotkey = request.args.get("hotkey")
    label = request.args.get("label")
    account = request.args.get("account")

    target_idx = None
    target_label = None
    target_acct = None
    if account:
        for a in accounts:
            if a.get("account") == account:
                target_idx = a["hotkey"]
                target_label = a["label"]
                target_acct = a.get("account")
                break
        if target_idx is None:
            return jsonify({
                "error": f"account '{account}' not found",
                "available": [{"account": a.get("account"), "label": a["label"]} for a in accounts],
            }), 404
    elif hotkey:
        try:
            hotkey = int(hotkey)
        except ValueError:
            return jsonify({"error": f"hotkey must be integer, got '{hotkey}'"}), 400
        for a in accounts:
            if a["hotkey"] == hotkey:
                target_idx = hotkey
                target_label = a["label"]
                target_acct = a.get("account")
                break
        if target_idx is None:
            return jsonify({
                "error": f"hotkey {hotkey} not found in account list",
                "available": [a["hotkey"] for a in accounts],
            }), 404
    elif label:
        for a in accounts:
            if a["label"] == label:
                target_idx = a["hotkey"]
                target_label = label
                target_acct = a.get("account")
                break
        if target_idx is None:
            return jsonify({
                "error": f"label '{label}' not found",
                "available": [a["label"] for a in accounts],
            }), 404
    else:
        return jsonify({"error": "must provide 'account' or 'hotkey' or 'label' parameter"}), 400

    if target_idx == 0:
        return jsonify({"error": "hotkey=0 (编辑账户) cannot be used for switching"}), 400

    # 通过下拉列表坐标点击切换 (替代失效的 Alt+N)
    # target_idx 是 hotkey (1-based), 对应下拉第 (target_idx-1) 项
    user = global_store["user"]
    try:
        app = user._app
        win = _find_main_window(app) or user._main
        win.set_focus()
        time.sleep(0.5)
        ok = _click_dropdown_item(app, win, target_idx - 1)
        if not ok:
            return jsonify({"error": "failed to open/switch account dropdown"}), 500
        _close_any_popup(win)
        time.sleep(0.8)  # 等 xiadan.exe 完成切换
    except Exception as e:
        return jsonify({"error": f"failed to switch account: {e}"}), 500

    # 验证切换结果
    info = _read_account_info()
    actual = info["label"]
    actual_acct = info["account"]
    previous = global_store.get("active_account")
    global_store["active_account"] = actual
    global_store["active_account_number"] = actual_acct

    if actual != target_label:
        return jsonify({
            "msg": "switch executed but active account mismatch",
            "previous": previous,
            "expected": target_label,
            "actual": actual,
            "hotkey_used": target_idx,
        }), 500

    return jsonify({
        "msg": "switched",
        "from": previous,
        "active": actual,
        "active_account": actual_acct,
        "hotkey_used": target_idx,
    }), 200


# ==================== 覆盖原版 /prepare (单实例 + 账户发现) ====================
def _enhanced_prepare():
    json_data = request.get_json(force=True)
    broker = json_data.pop("broker")
    label = json_data.pop("label", "main")

    user = _et_api.use(broker)
    # json_data 里剩余: exe_path / pid (patched connect 优先用 pid) / user / password 等
    user.prepare(**json_data)

    global_store["user"] = user
    global_store["active_account"] = None
    global_store["active_account_number"] = None
    global_store["accounts"] = []

    # 自动发现账户列表 (Alt+N 暴力枚举)
    try:
        time.sleep(1.0)  # 等窗口稳定
        raw = _discover_accounts()  # [(label, {"hotkey": n, "account": "xxx"}), ...]
        accounts = [
            {"label": lbl, "hotkey": v["hotkey"], "account": v.get("account")}
            for lbl, v in raw
            if v["hotkey"] > 0 and "编辑" not in lbl
        ]
        global_store["accounts"] = accounts
        info = _read_account_info()
        global_store["active_account"] = info["label"]
        global_store["active_account_number"] = info["account"]
        # 确保当前账户也在列表里 (初始 hotkey 可能是 0)
        if info["label"] and not any(a["label"] == info["label"] for a in accounts):
            accounts.insert(0, {"label": info["label"], "hotkey": 0, "account": info["account"]})
    except Exception:
        pass

    return jsonify({
        "msg": "login success",
        "label": label,
        "active": global_store.get("active_account"),
        "active_account": global_store.get("active_account_number"),
        "accounts": global_store.get("accounts", []),
        "accounts_count": len(global_store.get("accounts", [])),
    }), 201

app.view_functions["post_prepare"] = _orig_error_handle(_enhanced_prepare)


# ==================== 内置测试面板 ====================
@app.route("/")
@app.route("/test")
def test_page():
    html = "<html><body><h1>easytrader_test.html not found</h1><p>请确保该文件与本脚本在同一目录</p></body></html>"
    if os.path.exists(HTML_FILE):
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    # 将模板占位符替换为实际配置
    html = html.replace("__TOKEN__", TOKEN)
    html = html.replace("__EXE_PATH__", EXE_PATH)
    return Response(html, content_type="text/html; charset=utf-8")


# ==================== 市价委托 (原版 server.py 没有, 新增) ====================
@app.route("/market_buy", methods=["POST"])
@_orig_error_handle
def post_market_buy():
    json_data = request.get_json(force=True)
    user = global_store["user"]
    res = user.market_buy(**json_data)
    return jsonify(res), 201


@app.route("/market_sell", methods=["POST"])
@_orig_error_handle
def post_market_sell():
    json_data = request.get_json(force=True)
    user = global_store["user"]
    res = user.market_sell(**json_data)
    return jsonify(res), 201


@app.route("/cancel_all_entrusts", methods=["GET"])
@_orig_error_handle
def get_cancel_all_entrusts():
    user = global_store["user"]
    res = user.cancel_all_entrusts()
    return jsonify(res), 200


# ==================== 启动 ====================
if __name__ == "__main__":
    print("=" * 55)
    print("  easytrader 增强服务端 (Token + 测试面板)")
    print(f"  监听:   http://0.0.0.0:{PORT}")
    print(f"  面板:   http://localhost:{PORT}/")
    print(f"  健康检查: http://localhost:{PORT}/health")
    print(f"  Token:  {TOKEN}")
    print("=" * 55)
    print("  限价: /buy /sell  市价: /market_buy /market_sell")
    print("  查询: /balance /position /today_entrusts /today_trades")
    print("  撤单: /cancel_entrust /cancel_all_entrusts")
    print("  多账户: /accounts /accounts/refresh")
    print("  切换: /switch?account=资金账号 /switch?hotkey=N /switch?label=xxx")
    print("  切换原理: 点击账户下拉框(2322)列表项坐标切换, 单实例内多账户")
    print("=" * 55)
    app.run(host=HOST, port=PORT, debug=False)
