# easytrader 增强服务端 · 网络请求 API 文档

> 适用版本：`easytrader_server_auth.py`（在 easytrader 原版 `server.py` 基础上增强）
> 文档生成时间：2026-08-06 · 与线上代码（端口 1430）一致

---

## 1. 服务概览

| 项 | 值 |
|---|---|
| 默认地址 | `http://<交易电脑IP>:1430` |
| 本地面板 | `http://localhost:1430/` |
| 默认 Token | 无（真实 Token 放 `easytrader_local.json`，不进 git；见下方「自定义 Token」） |
| 交易客户端 | 同花顺 `xiadan.exe`（单进程、内置多账户） |
| 架构 | 1 个 `ClientTrader` 连接 + 多账户标签，切换只改活跃标签 |

**CORS**：已开启 `Access-Control-Allow-Origin: *`，Mac / 浏览器跨域调用无障碍。

---

## 2. 鉴权

除公开路由外，所有接口必须携带 Token，二选一：

- 请求头：`X-Token: YOUR_TOKEN`
- 查询参数：`?token=YOUR_TOKEN`

**公开路由（免 Token）**：`/`、`/test`、`/health`

未携带或错误 Token 返回：

```json
{ "error": "invalid or missing token" }   // HTTP 401
```

### 自定义 Token

Token 已从代码中抽出，真实 Token 放 **`easytrader_local.json`**（与脚本同目录，**不进 git**，已加入 `.gitignore`），`config.json` 是**模板**（进 git，`token` 留空）。直接改 `easytrader_local.json` 的 `"token"` 字段即可，无需碰代码：

```json
{
  "token": "你的密钥"
}
```

`config.json`（模板）保留 `host` / `port` / `exe_path` 等非敏感默认值：`exe_path` 为 xiadan.exe 默认路径（首次 `prepare` 也可通过请求体覆盖）。

优先级：**环境变量 > `easytrader_local.json`(本地, 不进 git) > `config.json`(模板, 空)**。环境变量覆盖写法：
- Windows (cmd)：`set EASYTRADER_TOKEN=你的新密钥`
- Windows (PowerShell)：`$env:EASYTRADER_TOKEN="你的新密钥"`
- Linux / macOS：`export EASYTRADER_TOKEN=你的新密钥`

> 改完后，所有调用方（浏览器面板、远端客户端、curl）都必须使用**同一个新 Token**，否则返回 401。面板 `/` 会自动读取服务端当前 Token，无需手动改 HTML。

---

## 3. 接口总览

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/health` | 免 | 健康检查 |
| GET/POST | `/`、`/test` | 免 | 内置测试面板（浏览器打开即用） |
| POST | `/prepare` | 需 | 连接 xiadan.exe 并自动发现账户（增强版） |
| GET | `/accounts` | 需 | 列出所有已发现账户 + 当前活跃账户 |
| POST | `/accounts/refresh` | 需 | 从客户端重新读取账户列表 |
| GET | `/switch` | 需 | 切换账户（按 资金账号 / hotkey / 标签） |
| GET | `/balance` | 需 | 资金账户信息 |
| GET | `/position` | 需 | 持仓 |
| GET | `/auto_ipo` | 需 | 可转债/新股申购 |
| GET | `/today_entrusts` | 需 | 当日委托 |
| GET | `/today_trades` | 需 | 当日成交 |
| GET | `/cancel_entrusts` | 需 | 可撤委托列表 |
| POST | `/buy` | 需 | 限价买入 |
| POST | `/sell` | 需 | 限价卖出 |
| POST | `/market_buy` | 需 | 市价买入（服务端新增） |
| POST | `/market_sell` | 需 | 市价卖出（服务端新增） |
| POST | `/cancel_entrust` | 需 | 按委托号撤单 |
| GET | `/cancel_all_entrusts` | 需 | 撤销全部可撤委托 |
| GET | `/exit` | 需 | 退出客户端连接 |

---

## 4. 详细接口

### 4.1 GET `/health`
快速探活，免 Token。

```bash
curl http://localhost:1430/health
```

返回：

```json
{
  "status": "ok",
  "service": "easytrader-enhanced-server",
  "logged_in": true,
  "accounts": 2,
  "active": "券商A-账户甲",
  "active_account": "10000000001",
  "port": 1430
}
```

---

### 4.2 POST `/prepare`（增强版 · 自动发现账户）
连接交易客户端，并在登录后**自动枚举账户列表**（排除末尾「编辑账户」项）。

**请求体（JSON）**：

| 字段 | 必填 | 说明 |
|---|---|---|
| `broker` | 是 | 券商类型，同花顺固定为 `"ths"` |
| `exe_path` | 二选一 | xiadan.exe 绝对路径 |
| `pid` | 二选一 | 已运行实例的进程 PID（优先于 exe_path） |
| `user` / `password` | 否 | 客户端已登录时可不传 |

```bash
curl -X POST http://localhost:1430/prepare \
  -H "X-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"broker":"ths","exe_path":"D:\\同花顺软件\\同花顺\\同花顺\\同花顺\\xiadan.exe"}'
```

返回（HTTP 201）：

```json
{
  "msg": "login success",
  "label": "main",
  "active": "券商A-账户甲",
  "active_account": "10000000001",
  "accounts": [
    {"label": "券商A-账户甲", "account": "10000000001", "hotkey": 1},
    {"label": "券商B-账户乙", "account": "20000000002", "hotkey": 2}
  ],
  "accounts_count": 2
}
```

> 注：`hotkey` 为下拉框中的序号（1 起），对应本次切换逻辑的下拉第 `hotkey-1` 项。`account` 为资金账号（纯数字），是切换的最可靠标识。

---

### 4.3 GET `/accounts`
列出已发现的账户及当前活跃账户。

```bash
curl http://localhost:1430/accounts -H "X-Token: YOUR_TOKEN"
```

返回：

```json
{
  "accounts": [
    {"label": "券商A-账户甲", "account": "10000000001", "hotkey": 1, "active": true},
    {"label": "券商B-账户乙", "account": "20000000002", "hotkey": 2, "active": false}
  ],
  "active": "券商A-账户甲",
  "active_account": "10000000001",
  "count": 2,
  "switch_via": "Alt+hotkey / account=资金账号 / label=标签"
}
```

---

### 4.4 POST `/accounts/refresh`
从客户端下拉框**重新读取**账户列表（例如新增/删除了账户后）。安全可靠，**不会触发「编辑账户」弹窗卡死**。

```bash
curl -X POST http://localhost:1430/accounts/refresh -H "X-Token: YOUR_TOKEN"
```

返回格式同 `/accounts`，并刷新服务端 `active_account` / `active_account_number`。

---

### 4.5 GET `/switch`（切换账户）⭐ 本次核心更新
切换当前活跃账户。**三种定位方式互斥，至少传一个**：

| 参数 | 说明 | 示例 |
|---|---|---|
| `account` | 资金账号（最可靠） | `20000000002` |
| `hotkey` | 下拉序号（整数，≥1） | `2` |
| `label` | 账户标签 | `券商B-账户乙` |

- `hotkey=0`（即「编辑账户」）**禁止用于切换**，返回 400。
- 切换方式：点击账户下拉框（`ComboBox 2322`）打开列表，按坐标点击对应列表项 —— **真实触发 xiadan 切换**，资金账号同步变化（已弃用失效的 `Alt+N` 与只改标签的 `.select()`）。
- 切换后会回读实际活跃账户做校验。

```bash
# 按资金账号切到银河
curl "http://localhost:1430/switch?account=20000000002" -H "X-Token: YOUR_TOKEN"

# 按序号切到中山
curl "http://localhost:1430/switch?hotkey=1" -H "X-Token: YOUR_TOKEN"

# 按标签切换
curl "http://localhost:1430/switch?label=%E4%B8%AD%E5%B1%B1%E8%AF%81%E5%88%B8-%E9%99%88*%E8%BE%89" \
  -H "X-Token: YOUR_TOKEN"
```

成功（HTTP 200）：

```json
{
  "msg": "switched",
  "from": "券商B-账户乙",
  "active": "券商A-账户甲",
  "active_account": "10000000001",
  "hotkey_used": 1
}
```

失败（HTTP 500，已执行但校验不符 / 下拉未打开）：

```json
{
  "msg": "switch executed but active account mismatch",
  "previous": "券商B-账户乙",
  "expected": "券商A-账户甲",
  "actual": "券商B-账户乙",
  "hotkey_used": 1
}
```

未找到目标（HTTP 404）：

```json
{ "error": "account 'xxx' not found", "available": [{"account":"10000000001","label":"券商A-账户甲"}] }
```

---

### 4.6 查询类接口（GET，沿用 easytrader 原版）

| 接口 | 说明 | 返回 |
|---|---|---|
| `/balance` | 资金账户 | 总资产/可用/冻结等 |
| `/position` | 持仓 | 证券代码/数量/成本/市值等 |
| `/auto_ipo` | 新股/可转债申购 | 可申购列表 |
| `/today_entrusts` | 当日委托 | 委托明细 |
| `/today_trades` | 当日成交 | 成交明细 |
| `/cancel_entrusts` | 可撤委托 | 待撤单列表 |

示例：

```bash
curl http://localhost:1430/balance -H "X-Token: YOUR_TOKEN"
curl http://localhost:1430/position -H "X-Token: YOUR_TOKEN"
```

---

### 4.7 交易类接口（POST）

#### 4.7.1 `/buy` `/sell`（限价，原版）
请求体 JSON 透传给 `user.buy()` / `user.sell()`：

| 字段 | 说明 |
|---|---|
| `security` | 证券代码，如 `600000` |
| `price` | 委托价格 |
| `amount` | 委托数量（股） |

```bash
curl -X POST http://localhost:1430/buy -H "X-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"security":"600000","price":10.5,"amount":100}'
```

#### 4.7.2 `/market_buy` `/market_sell`（市价，服务端新增）
请求体 JSON 透传给 `user.market_buy()` / `user.market_sell()`：

| 字段 | 说明 |
|---|---|
| `security` | 证券代码 |
| `amount` | 委托数量（股） |

```bash
curl -X POST http://localhost:1430/market_sell -H "X-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"security":"600000","amount":100}'
```

返回（HTTP 201）为 easytrader 原生结构（含委托号等）。

---

### 4.8 撤单类

#### 4.8.1 POST `/cancel_entrust`
| 字段 | 说明 |
|---|---|
| `entrust_no` | 委托号（从 `/today_entrusts` 获取） |

```bash
curl -X POST http://localhost:1430/cancel_entrust -H "X-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" -d '{"entrust_no":"1234567890"}'
```

#### 4.8.2 GET `/cancel_all_entrusts`
撤销全部可撤委托。

```bash
curl http://localhost:1430/cancel_all_entrusts -H "X-Token: YOUR_TOKEN"
```

---

### 4.9 GET `/exit`
断开客户端连接（关闭 xiadan 交互）。慎用。

```bash
curl http://localhost:1430/exit -H "X-Token: YOUR_TOKEN"
```

---

## 5. 错误码速查

| HTTP | 含义 |
|---|---|
| 200 / 201 | 成功 |
| 400 | 参数错误 / 未登录 / `hotkey=0` 禁止 |
| 401 | Token 缺失或错误 |
| 404 | 账户/序号/标签未找到 |
| 500 | 服务端执行异常（切换校验不符、下拉未打开、GUI 操作失败等） |

---

## 6. 客户端调用示例（远端 M1 Mac）

```python
import requests

BASE = "http://192.168.x.x:1430"
TOKEN = "YOUR_TOKEN"
H = {"X-Token": TOKEN}

# 1) 连接并发现账户
r = requests.post(f"{BASE}/prepare", json={"broker":"ths","exe_path":"D:\\...\\xiadan.exe"}, headers=H)

# 2) 查看账户
accs = requests.get(f"{BASE}/accounts", headers=H).json()

# 3) 按资金账号切换到银河
requests.get(f"{BASE}/switch", params={"account":"20000000002"}, headers=H)

# 4) 卖出
requests.post(f"{BASE}/market_sell", json={"security":"600000","amount":100}, headers=H)

# 5) 查持仓
pos = requests.get(f"{BASE}/position", headers=H).json()
```

---

## 7. 本次（2026-08-06）更新要点

1. **账户切换改为下拉框坐标点击**：废弃失效的 `Alt+N` 合成键与只改标签的 `.select()`，改用点击 `ComboBox 2322` 列表项，真实触发 xiadan 切换（资金账号同步变化）。
2. **账户发现不再卡死**：读 `ComboBox 2322.item_texts()` 发现账户，自动排除末尾「编辑账户」项，从根上杜绝「备注弹窗 → 卡死后续操作」问题。
3. **`/switch` 支持三种切换键**：`account`（资金账号，最可靠）/ `hotkey` / `label`，互斥，带切换后回读校验。
4. **`/accounts/refresh` 安全重扫**：不会触发弹窗卡死。
5. **新增 `/market_buy` `/market_sell`**（市价买卖）。
6. 网页测试面板（`/`）切换按钮刷新逻辑修复（等切换响应回来再刷新，不再用固定 1500ms 提前刷新导致状态陈旧）。
