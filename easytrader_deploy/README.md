# easytrader 交易服务端 · 部署包

把本目录整体拷到装有同花顺 `xiadan.exe` 的 Windows 交易电脑上即可使用。

## 1. 环境要求
- Windows 10/11，并已安装、且**手动登录**过同花顺 `xiadan.exe`（同花顺必须手动登录一次，服务端无法代登）
- Python 3.10 ~ 3.14（实测 3.14 可跑，32 位客户端 + 64 位 python 的告警无害）
- 调用方（策略机/Mac）与服务端在同一局域网，或经 VPN/隧道可达

## 2. 安装依赖
```bat
pip install -r requirements.txt
```

## 3. 启动（推荐用管理器，带守护进程）
```bat
python easytrader_manager.py start      # 后台启动
python easytrader_manager.py daemon     # 守护进程（崩溃自动重启，推荐长期运行）
python easytrader_manager.py status     # 查看运行状态
python easytrader_manager.py stop       # 停止
python easytrader_manager.py logs       # 查看日志
```
也可直接运行核心服务（无守护）：
```bat
python easytrader_server_auth.py
```

## 4. 防火墙（允许局域网远端访问）
以**管理员**身份运行 `add_firewall_rule.bat`，放行 1430 端口入站。
或手动：
```bat
netsh advfirewall firewall add rule name="easytrader" dir=in action=allow protocol=TCP localport=1430
```

## 5. 访问
- 本地面板（浏览器）： http://localhost:1430/
- 健康检查（免 Token）： http://localhost:1430/health

## 6. 鉴权
- 默认 Token： `easytrader-secret-2024`
- **改 Token 首选改 `config.json`**（与脚本同目录，首次启动自动生成）：把 `"token"` 字段改成你自己的随机字符串。
  ```json
  { "token": "你的密钥", "host": "0.0.0.0", "port": 1430, "exe_path": "D:\\路径\\xiadan.exe" }
  ```
- 也可用环境变量覆盖（优先级高于 `config.json`）： `set EASYTRADER_TOKEN=你的密钥`
- 调用方式：请求头 `X-Token: <token>` 或查询参数 `?token=<token>`
- 免鉴权路由： `/`、`/test`、`/health`（面板与健康检查）

## 7. 远端调用（Mac / 策略服务器）
- 完整接口文档： `easytrader_api_doc.md`
- 客户端示例： `easytrader_client.py` / `mac_trader_client.py`
- 调用地址： `http://<交易电脑IP>:1430`

## 8. 文件说明
| 文件 | 用途 |
|---|---|
| `easytrader_server_auth.py` | 核心增强服务端（Token 鉴权 + 多账户切换 + 内置面板） |
| `easytrader_test.html` | 内置测试面板（`/` 路由读取） |
| `easytrader_manager.py` | 服务管理器（启停 / 守护进程） |
| `easytrader_api_doc.md` | 网络请求 API 文档 |
| `easytrader_client.py` / `mac_trader_client.py` | 远端 HTTP 客户端示例 |
| `easytrader_mac_demo.md` | Mac 端调用示例 |
| `add_firewall_rule.bat` / `easytrader_start.bat` / `easytrader_stop.bat` | 运维批处理 |

## 9. 切换账户说明（重要）
服务端切换账户采用**点击账户下拉框列表项**的方式（非 Alt+N 快捷键），
会自动发现并排除末尾的「编辑账户」项，避免弹窗卡死。
切换接口支持三种定位：`?account=资金账号` / `?hotkey=N` / `?label=标签`。
详见 `easytrader_api_doc.md` 的 `/switch` 章节。
