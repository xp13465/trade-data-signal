# 商汤轮换代理心跳告警(/healthz 接线)

- 日期:2026-09-07
- 背景:docs/sensenova/out-of-range-locate-20260907.md §四.4「/healthz + 心跳告警」落地。
- 关联:8899 代理 sensenova-rotate-proxy.py 的 /healthz 端点(返回 status/rotate_keys/cooling_keys/uptime_sec/port)。

## 一句话

**定时 GET http://127.0.0.1:8899/healthz,连续 3 次失败走 notify.py --severe 告警(邮件 + 飞书 alert 群 + latest.md 镜像),恢复补 [恢复] 通知。健康时零通知。**

## 为什么(补的什么洞)

- launchd com.trade.thinking-proxy KeepAlive 已兜底「进程级重启」,但「进程在但卡死 / 端口无响应」级异常(卡死不退出,KeepAlive 不管)无监控,代理挂掉只有用户发现才暴露。
- /healthz 是代理已实现的端点(2026-09-07 P0-3 ③),此前只做不做监控 = 白做。本接线让端点真正产生告警价值。

## 组成

| 文件 | 作用 |
|---|---|
| `scripts/sensenova-proxy-healthcheck.py` | 心跳检测脚本(连续 3 次失败→告警,恢复→[恢复] 通知,幂等不轰炸) |
| `scripts/com.trade.sensenova-healthcheck.plist` | launchd 每 5 分钟跑一次(StartInterval 300) |
| 日志 `trade-data/data/logs/sensenova-healthcheck.log` / `.err` | 脚本 stdout/stderr(正常一轮只写一行「心跳正常」) |
| 状态 `trade-data/data/sensenova_health_state.json` | fired 去重状态(不进 git) |

## 脚本口径

- 一次探测 = GET /healthz 超时 5s,ok = HTTP 200 且 JSON `status=="ok"`。
- 一轮 = 最多 3 次探测,每次间隔 2s(给 launchd KeepAlive 重启窗口),全部失败才算异常。
- 幂等:fired 状态只告警一次,不重复轰炸;恢复后清 fired,再异常才再告警;健康时零通知且不写盘。
- 告警参数:`notify.py "[告警] 商汤代理 8899 心跳异常" body --severe --alert-issue "商汤代理8899心跳异常" --alert-log <err日志>`。
  - --severe = 邮件始终发(防飞书故障无通知)。
  - subject [告警] 前缀 → 飞书自动映射 alert 运维群。
  - --alert-issue 镜像 data/alerts/latest.md(L46④ 防旁路沉默)。

## 安装 / 自验

```bash
# 安装(merge 到 main 后在生产 tree 执行)
cp scripts/com.trade.sensenova-healthcheck.plist scripts/sensenova-proxy-healthcheck.py \
   /Users/linhuichen/code/trade/scripts/
launchctl load /Users/linhuichen/code/trade/scripts/com.trade.sensenova-healthcheck.plist
launchctl kickstart -k gui/$(id -u)/com.trade.sensenova-healthcheck   # 立即跑一次
tail -f /Users/linhuichen/code/trade-data/data/logs/sensenova-healthcheck.log   # 应见「心跳正常, 无异常不通知」

# 自验(不真发,不落盘)
python3 scripts/sensenova-proxy-healthcheck.py --self-test            # 两场景 code path 走一遍
python3 scripts/sensenova-proxy-healthcheck.py --dry-run --port 19099 # 模拟端口不通 → 触发 [告警] dry-run
python3 scripts/sensenova-proxy-healthcheck.py --fail-fast            # 冒烟:健康 exit 0 / 异常 exit 3

# 停用
launchctl unload /Users/linhuichen/code/trade/scripts/com.trade.sensenova-healthcheck.plist
```

## 复现

- 脚本:`scripts/sensenova-proxy-healthcheck.py`(活脚本,launchd 引用,不复制)。
- 输入依赖:`http://127.0.0.1:8899/healthz`(代理在线)。
- 重跑命令:上面「自验」三行。
- 数据截止:2026-09-07(落地当日)。
- 关键口径:连续 3 次失败(每次间隔 2s)才算异常;`--severe --alert-issue` 邮件+latest.md 镜像;健康零通知零写盘。
