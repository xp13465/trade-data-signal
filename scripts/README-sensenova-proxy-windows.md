# 商汤轮换代理(Windows/跨平台)使用说明

这是商汤 token.sensenova.cn 的 **7-key 轮换本地代理**。商汤对 deepseek-v4-flash 等模型按 RPM(每分钟请求数)限流,单 token 撞 429 会卡死;本代理在本地轮换多把 key,把 RPM 摊到 N 个池 = 变相 xN 吞吐。给 Claude Code、codex、脚本统一一个本地入口分摊限流。

纯标准库实现,零第三方依赖,Python 3.9+ 跨平台(mac/windows/linux 都能跑)。

## 一、推荐主入口:ctl 控制工具(mac/windows/linux 通用)

一个命令控制启停、看状态、测可用、编辑 key、一键生成 Claude/codex 配置。

### 1. 安装
- 装 Python 3.9+(https://www.python.org/downloads/,Windows 安装时勾选 "Add Python to PATH")
- 把以下文件拷到任意目录(就叫代理目录):
  - `sensenova-rotate-proxy.py`(代理本体)
  - `sensenova-proxy-ctl.py`(控制工具,主入口)
  - `keys.txt.example`(key 模板)
- 复制 `keys.txt.example` 为 `keys.txt`,填入你的商汤 key(每行一把,建议 ≤7 把与设计池一致;代码不强制上限,有多少用多少,`#` 开头注释)
  - key 从 https://token.sensenova.cn 控制台获取

### 2. 启动
```
mac/linux: python3 sensenova-proxy-ctl.py start
windows:   python sensenova-proxy-ctl.py start
```
看到 `代理已启动: PID=..., 监听 http://127.0.0.1:8899` 即成功。

不带参数进交互菜单:`python3 sensenova-proxy-ctl.py`(1.启动 2.停止 3.状态 4.编辑key 5.测试 6.配置claude 7.配置codex 8.配置状态 9.恢复配置)

### 3. 接 Claude Code
```
python3 sensenova-proxy-ctl.py config claude
```
会自动备份 `~/.claude/settings.json`,改 env 把 `ANTHROPIC_BASE_URL` 指向 `http://127.0.0.1:8899`、`ANTHROPIC_MODEL=glm-5.2`(以及所有 HAIKU/SONNET/OPUS/FABLE/SUBAGENT 模型键),token 用 keys.txt 第一把(代理内部轮换,此 token 仅门禁用)。**重启 Claude Code 生效。**

恢复原配置:`python3 sensenova-proxy-ctl.py config restore claude`

### 4. 接 codex
```
python3 sensenova-proxy-ctl.py config codex
```
自动备份 `~/.codex/config.toml`,写入 `[model_providers.sensenova]` 段(base_url 指向代理,`wire_api = "responses"`),并在**顶层**写 `model_provider = "sensenova"` + `model = "glm-5.2"`。**重启 codex 生效。**

> wire_api 用 `responses`:codex 0.154.0 起 `chat` 已废弃(配置加载即报 "chat is no longer supported")。
> 本版已用本机 codex 0.154.0 实测:隔离 CODEX_HOME 加载生成配置正常,`codex exec` 经本地代理打通商汤
> `/v1/responses` 并正常返回。顶层 `model_provider` 必须写,否则 codex 仍走默认 openai provider、请求不发代理。
> 只改顶层 `model`/`model_provider`,`[profiles.*]` 等其它段内的同名键一律不动。

### 5. 查当前指向
```
python3 sensenova-proxy-ctl.py config status
```
显示 claude/codex 当前是走代理还是直连。

### 6. 验证代理可用
```
python3 sensenova-proxy-ctl.py test
```
经代理发一个最小 glm-5.2 请求,返回 HTTP 200 + JSON 即通。

## 二、Windows 双击便利入口(可选)

不装 Python 也能双击启动的前提是用 exe(见下)。装了 Python 的话双击:
- `sensenova-proxy-start.bat` —— 双击启动代理
- `sensenova-proxy-install-autostart.bat` —— 双击装开机自启(往启动文件夹放快捷方式)

## 三、exe 版(无需装 Python)

mac/linux 不能交叉编译 PyInstaller,**exe 必须在 Windows 机器上生成**:
1. 在 Windows 机器装 Python 3.9+
2. 双击 `build-exe.bat`(会自动 `pip install pyinstaller` + `pyinstaller --clean sensenova-proxy.spec`)
3. 产物在 `dist\sensenova-proxy.exe`
4. 把 `sensenova-proxy.exe` 与 `keys.txt` 放同目录,双击 exe 即用

> exe(PyInstaller onefile)运行时按 **exe 所在目录**找 `keys.txt`:onefile 的 `__file__` 指向临时解包目录,
> 本版已改用 `sys.executable` 目录做基准,所以"exe 与 keys.txt 同目录"确实可用(本机已模拟冻结态实测)。
> exe 版只能双击启动代理本体,**ctl 控制工具的 config/status/restore 等功能仍需 .py 版**(ctl 不打成 exe,因为它要读写用户家目录配置文件,Python 脚本更灵活)。要一键配置 Claude/codex 仍需装 Python 跑 ctl。

## 四、验证(curl 等价)

ctl 的 `test` 子命令等价于:
```
curl http://127.0.0.1:8899/v1/messages \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"glm-5.2","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}'
```
应返回 JSON。

## 五、当前可用模型实测表

经代理实测(主控环境):
| 模型 | 状态 |
|---|---|
| glm-5.2 | OK |
| deepseek-v4-flash | OK |
| deepseek-flash | OK |
| kimi-k3 | OK |
| sensenova-6.8-flash-lite | OK |
| u1.5-lite | 404(端点不存在) |
| v4.1-flash | 403(套餐不含) |

## 六、key 安全

- `keys.txt` 不进 git(`.gitignore` 已忽略 `scripts/keys.txt`)
- `keys.txt.example` 只放占位符,无真 key
- 别把 `keys.txt` 连同代理目录分享给别人时连带 key

## 七、mac 用户(对照)

mac 现状仍可用 `scripts/sensenova-rotate-proxy.sh`(从 trade-data/.env 导 key)+ launchd 守护;ctl 工具是跨平台统一入口,mac 也能用 `python3 sensenova-proxy-ctl.py start`。

mac 行为零变化的实现方式:默认路径已改为 `~/.sensenova-proxy/`,但生产 plist
(`scripts/com.trade.thinking-proxy.plist`)现**显式设全** `SENSENOVA_ENV_FILE` / `TTP_LOG` /
`TTP_COOLDOWN_FILE` / `TTP_REQDUMP_DIR` 指回原 `trade-data/...` 路径,所以重启后日志、冷却文件、
请求 dump 位置都不变(功能与路径均零变化)。env 设了仍然优先。

> mac 的 key 在 `trade-data/.env`(env 注入),不在代理目录 `keys.txt`,所以 ctl 的 `status` 显示 key 数 0、
> `test` 会提示无 key 拒跑;mac 上验证请直接看 8899 代理的 `/healthz` 或原有日志。

## 参考

商汤 token.sensenova.cn:https://token.sensenova.cn
PyInstaller:https://pyinstaller.org
