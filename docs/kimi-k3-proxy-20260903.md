# kimi-k3 5key 轮询代理落地说明(2026-09-03)

## 背景

现网商汤代理 `scripts/sensenova-rotate-proxy.py`(8899)是纯 key 轮换透传代理:round-robin 轮换
SENSENOVA_KEY1-5 转发到 https://token.sensenova.cn/,429 换 key 重试。当前 Claude 会话模型
=deepseek-v4-flash 走这个 8899 代理。

用户要求:复制一份做 kimi-k3 版代理(商汤新支持模型,ID=kimi-k3,支持 thinking/non-thinking +
1M context + 工具,和 v4-flash 同形态),去掉 v4-flash 为解决 400 问题做的参数剔除逻辑;换新端口跑,
老 8899 代理继续守护不碰;提供切换脚本(只改 ~/.claude/settings.json 的 BASE_URL+MODEL 即切换两个代理)。

## 改动文件(commit e0acfb332)

| 文件 | 说明 |
|---|---|
| scripts/sensenova-rotate-proxy-kimi.py | kimi 版代理本体:复制 v4-flash 版,删 `_strip_thinking_adaptive` 函数+调用点(body 原样转发);LOG→sensenova-rotate-kimi-req.log;REQDUMP_DIR→sensenova-req-dump-kimi;TTP_PORT 默认 8898 |
| scripts/sensenova-rotate-proxy-kimi.sh | kimi wrapper:exec 指向 kimi py |
| scripts/com.trade.thinking-proxy-kimi.plist | launchd 守护(Label=com.trade.thinking-proxy-kimi,TTP_PORT=8898,独立 stdout/err 日志) |
| scripts/kimi-proxy-switch.sh | kimi/v4flash 双向切换(备份后写 settings.json,幂等,不碰 launchd) |

保留逻辑:5key 加载/429 换 key/单 key 分层冷却/高峰限频/轮换,与 v4-flash 版完全一致。

## 怎么起

```bash
# 手动拉起(测试实例;正式用 launchd):
SENSENOVA_ENV_FILE=/Users/linhuichen/code/trade-data/.env \
TTP_PORT=8898 python3 scripts/sensenova-rotate-proxy-kimi.py

# 正式(launchd 守护,由用户拍板后执行):
launchctl load scripts/com.trade.thinking-proxy-kimi.plist
```

## 怎么切(只改 ~/.claude/settings.json,不碰 launchd;两代理常驻靠 BASE_URL 切换)

```bash
bash scripts/kimi-proxy-switch.sh kimi      # -> BASE_URL=http://127.0.0.1:8898,所有模型键=kimi-k3
bash scripts/kimi-proxy-switch.sh v4flash   # -> BASE_URL=http://127.0.0.1:8899,所有模型键=deepseek-v4-flash
```

切换脚本每次先 `cp settings.json settings.json.bak-kimi-switch-<日期>` 再写,可回退、幂等可重复。

## 停/回退

```bash
launchctl unload scripts/com.trade.thinking-proxy-kimi.plist   # 停 kimi 守护
bash scripts/kimi-proxy-switch.sh v4flash                       # 切回 v4-flash 代理
```

## 验证记录(2026-09-03)

- python3 -m py_compile scripts/sensenova-rotate-proxy-kimi.py PASS
- bash -n 两个 sh PASS(pre-commit lint_scripts.sh 全量 bash -n + $VAR 非 ASCII 扫描 0 命中)
- 冒烟:临时实例 TTP_PORT=8898 + SENSENOVA_KEY1,curl -H "Authorization: Bearer <key1>"
  http://127.0.0.1:8898/v1/models → HTTP 200,8 个模型,含 `kimi-k3`(透传+轮换链路通);测完 kill,8898 已释放
- 8899 老代理未动(ps PID 35148 仍在,launchctl com.trade.thinking-proxy loaded)
- ~/.claude/settings.json 未被修改(冒烟未跑切换脚本,md5 对照见下方复现)

## 复现

- 脚本:scripts/sensenova-rotate-proxy-kimi.py(依赖 ../trade-data/.env 的 SENSENOVA_KEY1/2/3/4/5,仓外)
- 冒烟重跑命令(只注入 key1 即可验证链路):
  ```bash
  cd /Users/linhuichen/code/trade && SENSENOVA_KEY1=$(grep -E '^SENSENOVA_KEY1=' /Users/linhuichen/code/trade-data/.env | head -1 | cut -d= -f2-) TTP_PORT=8898 python3 scripts/sensenova-rotate-proxy-kimi.py &
  sleep 1
  curl -s -m 30 -H "Authorization: Bearer $SENSENOVA_KEY1" http://127.0.0.1:8898/v1/models | python3 -c "import json,sys; d=json.load(sys.stdin); print('kimi-k3 in models:', 'kimi-k3' in [m['id'] for m in d['data']])"
  kill %1   # 测完必 kill,不留脏进程
  ```
- 数据截止:2026-09-03(商汤模型列表实测含 kimi-k3)
- 关键口径一句话:kimi-k3 版 kimi 代理=纯 key 轮换(去 v4-flash 的 adaptive thinking 剔除),body 原样转发