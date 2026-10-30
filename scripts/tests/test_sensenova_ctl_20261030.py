# -*- coding: utf-8 -*-
"""sensenova-proxy-ctl.py 回归单测(2026-10-30 新增,补 ctl 之前零测试覆盖)。

锁三处修复(复审 /tmp/report-review-sensenova2.md):
  F-1 段头识别:真实 TOML 段头 `[plugins."x@y"]` / `[projects."/abs/p"]` / `[[数组表]]`
      行首都是 `[` ⇒ 旧的"字符白名单"正则认不出它们,替换/删 sensenova 段时会把紧跟着的
      整段吞掉(真实 codex config 有 14 个这类段头)。本文件用真实形态样本 + tomllib 复核。
  S-1 CRLF:读侧 newline="" 才保得住 Windows 换行;之前文本模式已把 CRLF 统一成 LF,
      `_toml_join` 的"保留 CRLF"是死代码(说假话)。
  S-2 ORIGINAL 语义:迁移用户当前文件本身就是旧版工具写的代理配置,不能再把它标成"原始"
      (否则 restore 回不到真原始)。同时 F2 的"只改顶层区、profiles 段不动"一并锁住。

隔离铁律(不碰真实家目录):HOME / ~/.codex / ~/.claude / keys.txt 全部 tmp_path 隔离;
  本文件不启动代理、不发网络请求(env fixture 把 TTP_PORT 指到 8897,即便误调也碰不到
  mac 在跑的 8899 生产代理)。用例不写死"今天",与运行日无关。
"""
from __future__ import annotations

import importlib.util
import json
import os
import tomllib
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
CTL_PATH = SCRIPTS / "sensenova-proxy-ctl.py"

# 真实形态样本:带 @ 的插件段、带绝对路径的 projects 段、[[数组表]]、带空格引号段、profiles 段
SAMPLE = '''\
model = "gpt-5-codex"
model_provider = "openai"
notify = ["python3", "/opt/notify.py"]

[features]
web_search = true

[plugins]
enabled = true

[plugins."documents@openai-primary-runtime"]
enabled = true

[plugins."中文@插件"]
enabled = false

[projects."/Users/x/trade-new"]
trust_level = "trusted"

[[array.table]]
id = 1

[[array.table]]
id = 2

[quoted."my section"]
k = "v"

[profiles.fast]
model = "o4-mini"

[desktop]
x = 1
'''

PROXIED_CODEX = (
    'model = "glm-5.2"\n'
    'model_provider = "sensenova"\n'
    "\n[model_providers.sensenova]\n"
    'name = "sensenova"\n'
    'base_url = "http://127.0.0.1:8899/v1"\n'
    'wire_api = "responses"\n'
    'experimental_bearer_token = "sk-old-fake"\n'
    "\n[features]\n"
    "web_search = true\n"
)


def _load_ctl(tmp_home: Path):
    """加载 ctl 模块。顶层会 makedirs ~/.sensenova-proxy ⇒ 必须先把 HOME 指到临时目录。"""
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp_home)
    try:
        spec = importlib.util.spec_from_file_location("sensenova_ctl_mod_20261030", CTL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


@pytest.fixture(scope="module")
def ctl(tmp_path_factory):
    return _load_ctl(tmp_path_factory.mktemp("ctl-home"))


@pytest.fixture
def env(ctl, tmp_path, monkeypatch):
    """每个用例一套隔离文件:codex config / claude settings / keys.txt 全在 tmp_path。"""
    monkeypatch.setenv("TTP_PORT", "8897")  # 防误触 mac 在跑的 8899 生产代理
    codex = tmp_path / "codex" / "config.toml"
    settings = tmp_path / "claude" / "settings.json"
    keys = tmp_path / "keys.txt"
    keys.write_text("sk-fake-test-0001\n", encoding="utf-8")
    state = tmp_path / "state" / "config.json"
    monkeypatch.setattr(ctl, "_codex_path", lambda: str(codex))
    monkeypatch.setattr(ctl, "_settings_path", lambda: str(settings))
    monkeypatch.setattr(ctl, "_keys_txt_path", lambda: str(keys))
    monkeypatch.setattr(ctl, "_state_config_path", lambda: str(state))
    return types.SimpleNamespace(mod=ctl, codex=codex, settings=settings, keys=keys,
                                 state=state, dir=tmp_path)


def _baks(env, path: Path):
    return sorted(path.parent.glob(path.name + ".bak-sensenova-proxyctl-*"))


# ───────── F-1 段头识别 ─────────
def test_01_section_header_recognizes_real_world_forms(ctl):
    yes = [
        '[plugins."documents@openai-primary-runtime"]',
        '[projects."/Users/x/trade-new"]',
        '[quoted."my section"]',
        '  [quoted."缩进带空格"]',
        "[[array.table]]",
        "[features]",
        "[plugins.\"中文@插件\"]  # 尾注释",
    ]
    no = [
        'key = [1, 2]',
        '# [plugins."a@b"]',
        "",
        'model = "x"',
        '  name = "y"',
    ]
    for line in yes:
        assert ctl._is_section_header(line) is True, line
    for line in no:
        assert ctl._is_section_header(line) is False, line


def test_02_replace_table_stops_at_quoted_section(ctl):
    src = (
        '[model_providers.sensenova]\n'
        'name = "old"\n'
        '\n[plugins."a@b"]\n'
        "enabled = true\n"
    )
    out = ctl._replace_toml_table(
        src, "model_providers.sensenova",
        '\n[model_providers.sensenova]\nname = "sensenova"\n')
    assert out.count("[model_providers.sensenova]") == 1
    assert '[plugins."a@b"]' in out, "带 @ 的段头不许被吞(F-1)"
    data = tomllib.loads(out)
    assert data["model_providers"]["sensenova"]["name"] == "sensenova"
    assert data["plugins"]["a@b"]["enabled"] is True


# ───────── F-1 端到端:两次 config 全部段保留、不重复 ─────────
def test_03_config_codex_twice_keeps_every_section(env):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    env.codex.write_text(SAMPLE, encoding="utf-8")
    for _ in range(3):
        assert env.mod._config_codex() == 0
    text = env.codex.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["model_provider"] == "sensenova"
    assert data["model"] == "glm-5.2"
    prov = data["model_providers"]["sensenova"]
    assert prov["base_url"].startswith("http://127.0.0.1:8897/v1")
    assert prov["wire_api"] == "responses"
    # 所有非 sensenova 段(含带引号/带 @ 段)全部保留、内容不变
    assert data["features"]["web_search"] is True
    assert data["plugins"]["enabled"] is True
    assert data["plugins"]["documents@openai-primary-runtime"]["enabled"] is True
    assert data["plugins"]["中文@插件"]["enabled"] is False
    assert data["projects"]["/Users/x/trade-new"]["trust_level"] == "trusted"
    assert data["array"]["table"] == [{"id": 1}, {"id": 2}]
    assert data["quoted"]["my section"]["k"] == "v"
    assert data["profiles"]["fast"]["model"] == "o4-mini"
    assert data["desktop"]["x"] == 1
    # 不重复:段头只出现一次,顶层 key 不重复
    assert text.count("[model_providers.sensenova]") == 1
    assert len([ln for ln in text.splitlines() if ln.startswith("model_provider")]) == 1


# ───────── S-1 CRLF + BOM ─────────
def test_04_crlf_bom_roundtrip_keeps_sections_and_crlf(env):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    body = SAMPLE.replace("\n", "\r\n")
    env.codex.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    for _ in range(2):
        assert env.mod._config_codex() == 0
    raw = env.codex.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM 应被清掉(utf-8-sig 写入)"
    text = raw.decode("utf-8")
    assert "\n" not in text.replace("\r\n", ""), "CRLF 必须保留(S-1:读侧 newline=\"\")"
    data = tomllib.loads(text)
    assert data["projects"]["/Users/x/trade-new"]["trust_level"] == "trusted"
    assert data["plugins"]["documents@openai-primary-runtime"]["enabled"] is True


# ───────── F2 顶层 key 只改顶层区 ─────────
def test_05_top_level_keys_only_profiles_untouched(env):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    env.codex.write_text(SAMPLE, encoding="utf-8")
    assert env.mod._config_codex() == 0
    text = env.codex.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["model"] == "glm-5.2"
    assert data["model_provider"] == "sensenova"
    assert data["profiles"]["fast"]["model"] == "o4-mini", "profiles 段内同名 key 不许被改(F3)"
    assert env.mod._top_level_value(text, "model") == "glm-5.2"


# ───────── S1 ORIGINAL 固存 + restore 逐字节 ─────────
def test_06_original_created_once_and_restore_byte_exact(env):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    env.codex.write_text(SAMPLE, encoding="utf-8")
    assert env.mod._config_codex() == 0
    orig = Path(env.mod._original_bak_path(str(env.codex)))
    assert orig.exists(), "首次 config 必须固存 ORIGINAL"
    assert orig.read_bytes() == SAMPLE.encode("utf-8")
    assert env.mod._config_codex() == 0
    assert orig.read_bytes() == SAMPLE.encode("utf-8"), "ORIGINAL 不许被后续 config 覆盖"
    assert env.mod._config_restore("codex") == 0
    assert env.codex.read_bytes() == SAMPLE.encode("utf-8"), "restore 必须逐字节回到原始"


# ───────── S-2 已代理化场景不误标 ORIGINAL ─────────
def test_07_codex_already_proxied_no_original(env, capsys):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    env.codex.write_text(PROXIED_CODEX, encoding="utf-8")
    assert env.mod._config_codex() == 0
    orig = env.mod._original_bak_path(str(env.codex))
    assert not Path(orig).exists(), "已代理化文件不能被标成 ORIGINAL(S-2)"
    baks = _baks(env, env.codex)
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == PROXIED_CODEX
    assert "已是代理配置" in capsys.readouterr().out
    # restore 无 ORIGINAL 时如实提示回退到时间戳备份(不谎称"原始")
    assert env.mod._config_restore("codex") == 0
    assert "无 ORIGINAL" in capsys.readouterr().out
    assert env.codex.read_text(encoding="utf-8") == PROXIED_CODEX


def test_08_claude_already_proxied_no_original(env):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    old = json.dumps({"env": {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8899",
        "ANTHROPIC_AUTH_TOKEN": "sk-old-fake",
    }}, ensure_ascii=False, indent=2)
    env.settings.write_text(old, encoding="utf-8")
    assert env.mod._config_claude() == 0
    assert not Path(env.mod._original_bak_path(str(env.settings))).exists()
    data = json.loads(env.settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:8897")
    assert data["env"]["ANTHROPIC_MODEL"] == "glm-5.2"


def test_09_claude_clean_settings_gets_original(env):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    clean = json.dumps({"env": {"FOO": "bar"}}, ensure_ascii=False, indent=2)
    env.settings.write_text(clean, encoding="utf-8")
    assert env.mod._config_claude() == 0
    orig = Path(env.mod._original_bak_path(str(env.settings)))
    assert orig.exists() and orig.read_text(encoding="utf-8") == clean


# ───────── 模型可选(2026-10-31 增量) ─────────
CLA_MODEL_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]


def test_10_claude_model_written_to_every_model_key_others_kept(env):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    old = json.dumps({"env": {
        "FOO": "bar",
        "API_TIMEOUT_MS": "600000",
        "ANTHROPIC_MODEL": "glm-5.2",
    }}, ensure_ascii=False, indent=2)
    env.settings.write_text(old, encoding="utf-8")
    assert env.mod.cmd_config(["claude", "--model", "deepseek-v4-flash"]) == 0
    envd = json.loads(env.settings.read_text(encoding="utf-8"))["env"]
    for k in CLA_MODEL_KEYS:
        assert envd[k] == "deepseek-v4-flash", k
    # 非模型 env 键原样保留
    assert envd["FOO"] == "bar"
    assert envd["API_TIMEOUT_MS"] == "600000"
    assert envd["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:8897")
    # --model=X 等价写法
    assert env.mod.cmd_config(["claude", "--model=kimi-k3"]) == 0
    envd = json.loads(env.settings.read_text(encoding="utf-8"))["env"]
    for k in CLA_MODEL_KEYS:
        assert envd[k] == "kimi-k3", k
    assert envd["API_TIMEOUT_MS"] == "600000"


def test_11_codex_model_only_toplevel_profiles_untouched(env):
    env.codex.parent.mkdir(parents=True, exist_ok=True)
    env.codex.write_text(SAMPLE, encoding="utf-8")
    assert env.mod.cmd_config(["codex", "--model", "kimi-k3"]) == 0
    data = tomllib.loads(env.codex.read_text(encoding="utf-8"))
    assert data["model"] == "kimi-k3"
    assert data["model_provider"] == "sensenova"
    assert data["profiles"]["fast"]["model"] == "o4-mini", "profiles 段内 model 不许被改"
    assert data["plugins"]["documents@openai-primary-runtime"]["enabled"] is True


def test_12_invalid_model_rejected_available_listed_no_write(env, capsys):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    before = json.dumps({"env": {"FOO": "bar"}}, ensure_ascii=False, indent=2)
    env.settings.write_text(before, encoding="utf-8")
    rc = env.mod.cmd_config(["claude", "--model", "gpt-9-ultra"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "不支持" in out
    for m in env.mod.AVAILABLE_MODELS:
        assert m in out, "报错须列出可用模型: %s" % m
    assert env.settings.read_text(encoding="utf-8") == before, "非法模型不许写文件"
    assert env.mod.cmd_config(["codex", "--model", "nope"]) != 0
    assert env.mod.cmd_config(["claude", "--model"]) != 0, "--model 缺值须报错"


def test_13_persisted_model_is_default_next_time(env, capsys):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    assert env.mod.cmd_config(["claude", "--model", "deepseek-flash"]) == 0
    assert json.loads(env.state.read_text(encoding="utf-8"))["model"] == "deepseek-flash"
    # 下次不传 --model(非交互)⇒ 用上次持久化的
    assert env.mod.cmd_config(["codex"]) == 0
    data = tomllib.loads(env.codex.read_text(encoding="utf-8"))
    assert data["model"] == "deepseek-flash"
    out = capsys.readouterr().out
    assert "上次选的 deepseek-flash" in out
    assert env.mod.cmd_config(["status"]) == 0
    assert "持久化模型: deepseek-flash" in capsys.readouterr().out


def test_14_menu_selection_by_number(env, monkeypatch, capsys):
    env.settings.parent.mkdir(parents=True, exist_ok=True)

    class _FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(env.mod.sys, "stdin", _FakeStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": "4")
    assert env.mod.cmd_config(["claude"]) == 0
    out = capsys.readouterr().out
    for i, m in enumerate(env.mod.AVAILABLE_MODELS, 1):
        assert "%d) %s" % (i, m) in out, "菜单必须带序号列出全部可用模型"
    envd = json.loads(env.settings.read_text(encoding="utf-8"))["env"]
    assert envd["ANTHROPIC_MODEL"] == env.mod.AVAILABLE_MODELS[3]
    assert json.loads(env.state.read_text(encoding="utf-8"))["model"] == env.mod.AVAILABLE_MODELS[3]


def test_15_test_subcommand_uses_given_model(env, monkeypatch):
    """test --model X 必须真把 X 发到代理(本地假代理收包核对,不碰 8899 生产)。"""
    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            seen.append(json.loads(self.rfile.read(n).decode("utf-8")))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        monkeypatch.setenv("TTP_PORT", str(port))
        assert env.mod.cmd_config(["claude", "--model", "sensenova-6.8-flash-lite"]) == 0
        assert env.mod.cmd_test("sensenova-6.8-flash-lite") == 0
        assert seen and seen[0]["model"] == "sensenova-6.8-flash-lite"
        # 不传 --model ⇒ 用持久化的那一个
        assert env.mod.cmd_test() == 0
        assert seen[-1]["model"] == "sensenova-6.8-flash-lite"
        # 非法模型:拒绝且不发请求
        n0 = len(seen)
        assert env.mod.cmd_test("bad-model") != 0
        assert len(seen) == n0
    finally:
        srv.shutdown()
        srv.server_close()