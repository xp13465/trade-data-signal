# 商汤 Sensenova 3-token 轮换本地代理方案(2026-09-01)

> 本文档记录「纯 key 轮换本地代理」缓解商汤 Sensenova RPM 限流的完整方案:
> 动机 / 方案构成 / key 存放 / 切换状态 / 8899 端口历史 / 验证证据 / 诚实待改进 / 回退 / 复现。
> 纯文档归档任务,不改任何业务逻辑。

## 背景与动机

商汤 `token.sensenova.cn` 对 deepseek-v4-flash 按 **RPM(每分钟请求数)限流,约 1 req/min/account**。
单 token 撞 429(`inference tpm exhausted`)会导致 implementer 反复死在限流上(terminated early / 任务重跑)。

关键约束:客户端退避间隔**写死 4 秒封顶、调不了**,只有 `CLAUDE_CODE_MAX_RETRIES` 可调(已设 16)。
既然单 token 的 RPM 池打不穿,就做**多 token 轮换**:把 1 个池的吞吐摊到 3 个池 = 变相 ~3 req/min 总吞吐。

## 方案构成(纯 key 轮换,无任何 thinking 注入/别名逻辑)

| 文件 | 作用 |
|---|---|
| `scripts/sensenova-rotate-proxy.py` | **独立主脚本**。纯 round-robin key 轮换本地代理:监听本地端口 → 每请求 round-robin 选 key → 转发 `https://token.sensenova.cn/`(base=/)。**无任何 thinking 注入 / 别名逻辑**,文件名与 thinking 完全无关。429 时换下一把 key 重试(轻退避,默认 0.3s),`rotate_keys=3` 三把已加载。round-robin 游标推进见源码 L121-123(对 `len(KEYS)` 取模);429 换 key 逻辑见 L136-138(未到尝试序列末尾才换,不产生死循环)。 |
| `scripts/sensenova-rotate-proxy.sh` | wrapper 包装脚本。从 `../trade-data/.env`(仓外)只导出 `SENSENOVA_KEY1/2/3` 三个键到子进程 env,再 `exec` 主脚本。launchd 守护入口。 |
| `scripts/com.trade.thinking-proxy.plist` | launchd 守护定义,ProgramArguments 改指 `sensenova-rotate-proxy.sh`,EnvironmentVariables 传 `SENSENOVA_ENV_FILE` 指向 `trade-data/.env`。守护 127.0.0.1:8899。 |
| `scripts/thinking-proxy-rollback.sh` | 新增 `sento` 一键回退:还原 settings 到商汤单 token 直连原状(备份 `settings.json.bak-sensenova-rotate-<日期>`) + unload plist + pkill 双代理(`thinking_proxy.py` + `sensenova-rotate-proxy.py`)。幂等。 |

与 `thinking_proxy.py`(思考注入,走方舟/官方)完全独立,互不影响。

## key 存哪

三把 key 存 `../trade-data/.env` 的 `SENSENOVA_KEY1 / SENSENOVA_KEY2 / SENSENOVA_KEY3`(**仓外,禁进 git**)。
- 主脚本读取顺序:先看 env,回退读 `.env`;缺 key 则只轮换已有 key(round-robin 长度=已有 key 数)。
- 文档 / git / 日志均只写变量名,不出现真实 key 值。

## 切换状态(settings 已切,需用户拍板 + 重启会话生效)

- `~/.claude/settings.json` 已切:`ANTHROPIC_BASE_URL=http://127.0.0.1:8899`、`MODEL=deepseek-v4-flash`、`CLAUDE_CODE_MAX_RETRIES=16`(保留)。
- 切换前自动备份:`~/.claude/settings.json.bak-sensenova-rotate-switch-20260901-022443`。
- **生效前提**:settings 改动需**重启 Claude Code 会话**才生效;切换动作须用户拍板确认后才算定案(本次已切,但保留回退能力)。

## 8899 端口历史(孤儿 static-site 清理)

8899 曾有一个**孤儿 static-site 服务**:2026-08-22 手动起的 `python -m http.server 8899 -d static-site`,PPID=1 没人管、无守护。
轮换代理要占 8899 前必须清掉它 → 已 kill 清理。**根因 = 手动起的服务没有登记/守护,事后没人清理**。

教训:手动起常驻服务要登记(落档/launchd),用完或换用途前必须确认端口占用方并清理,防孤儿进程占用端口。

## 验证证据

### 1. reviewer PASS(4 硬约束全过)

feat 分支 `feat/sensenova-token-rotate`(commit `1c63ffd09`)reviewer 评审 PASS:
- 纯 key 轮换、无任何 thinking 注入残留;
- 真实 key 不进 git;
- settings 可一键回退直连;
- 429 轮换逻辑正确、无死循环。

### 2. 端到端冒烟三层证据

干净子进程 `claude -p "回复ok" --model deepseek-v4-flash` 返回 ok,且代理日志同步记录
(02:27:43/48/51 三条 POST 200,含 31252B 最终回复),确证流量走代理而非绕过。

- `rotate_keys=3` 三把 key 已加载;
- round-robin 游标 L121-123 每请求推进、对 3 取模;
- 本次窗口 15 条请求全 200,真实 429 = 0。

## 诚实待改进(非本次范围,待用户决定)

代理日志(`scripts/sensenova-rotate-proxy.py` L141)只记:
```
RESP {command} {path} -> {status} bytes=
```
**不记录本次用的具体 key**,因此「本次 ≠ 上次的 key」无法从日志逐位确证。
如需逐请求 key 证据,得改代理日志(在 L141 加 key 标识)——属待用户决定的改进项,非本次落档范围。

## 回退方法

```
bash scripts/thinking-proxy-rollback.sh sento
```

还原 settings 到商汤单 token 直连原状(`https://token.sensenova.cn`,从 `settings.json.bak-sensenova-rotate-*` 备份恢复,备份含原 token)
+ unload launchd plist + pkill 双代理。幂等,可重复执行。

如需恢复代理:`launchctl load scripts/com.trade.thinking-proxy.plist`。

## 复现

- **脚本路径**:
  - 主代理:`/Users/linhuichen/code/trade/scripts/sensenova-rotate-proxy.py`
  - 包装脚本:`/Users/linhuichen/code/trade/scripts/sensenova-rotate-proxy.sh`
  - 回退脚本:`/Users/linhuichen/code/trade/scripts/thinking-proxy-rollback.sh`
- **输入依赖**:`/Users/linhuichen/code/trade-data/.env`(仓外,含 `SENSENOVA_KEY1/2/3`,禁进 git)
- **启动代理**:
  ```
  # launchd 守护(常驻 127.0.0.1:8899)
  launchctl load /Users/linhuichen/code/trade/scripts/com.trade.thinking-proxy.plist
  # 或手动前台跑(wrapper 从 .env 读 key 再 exec 主脚本)
  bash /Users/linhuichen/code/trade/scripts/sensenova-rotate-proxy.sh
  ```
- **端到端验证命令**(须先确保 settings 已切 `ANTHROPIC_BASE_URL=http://127.0.0.1:8899`):
  ```
  # 1) 确认代理在听
  lsof -nP -iTCP:8899 -sTCP:LISTEN
  # 2) 干净子进程走代理
  claude -p "回复ok" --model deepseek-v4-flash
  # 3) 代理日志应新增 RESP POST / 200(含最终回复 bytes),证明流量走代理
  tail -n 20 /Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log
  ```
- **验证判据**:①8899 有 LISTEN;②子进程返回 ok;③代理日志同步出现本次请求的 `RESP ... -> 200`,三者齐 = 走代理非绕过。
- **回退验证**:`bash scripts/thinking-proxy-rollback.sh sento` 后,`~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL` 恢复为 `https://token.sensenova.cn`,8899 无监听、双代理进程无残留。
- **数据截止日期**:2026-09-01;代理日志最新见当次冒烟记录。
- **关键口径一句话**:本地 127.0.0.1:8899 纯 round-robin 轮换 3 把商汤 key 转发 `token.sensenova.cn`,把单 account 的 ~1 req/min RPM 摊到 3 池 = 变相 ~3 req/min;429 时换下一把 key 轻退避重试,round-robin 游标每请求对 key 数取模推进。
