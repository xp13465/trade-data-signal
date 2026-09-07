# kimi 代理停用操作说明(给主控,P2-1 落地)

- 日期:2026-09-07
- 背景:任务 B⑤(P2-1,依据 docs/sensenova/sensenova-5key-rotation-audit-20260906.md 表 P2-1)
  - 8898(kimi-k3 版轮换代理,`sensenova-rotate-proxy-kimi.py`)自 09-05 21:03 起无流量,`settings.json` 的 `ANTHROPIC_BASE_URL` 已指向 8899(v4-flash 版 7key 轮换代理)。
  - 停用目的:省一个常驻进程;需要 k3 评测时再 load 回。
- 本 agent 只写步骤**不执行**(红线:不碰 launchd 卸载/加载),由主控按用户时点操作。

## 卸载步骤(主控执行)

1. 确认当前无 kimi 代理流量后停服:
   ```bash
   # 方式 A(推荐,launchd 托管卸载)
   launchctl unload ~/code/trade/scripts/com.trade.thinking-proxy-kimi.plist
   # 若 unload 报错,用 bootout(新版 launchd 语法):
   launchctl bootout gui/$(id -u)/com.trade.thinking-proxy-kimi
   ```
2. 验证已停止:
   ```bash
   launchctl list | grep thinking-proxy-kimi        # 应无输出
   lsof -i :8898 -sTCP:LISTEN                        # 应无监听
   pgrep -f sensenova-rotate-proxy-kimi              # 应无进程
   ```

## 恢复步骤(需要 k3 评测时)

```bash
launchctl load ~/code/trade/scripts/com.trade.thinking-proxy-kimi.plist
# 或 launchctl bootstrap gui/$(id -u) ~/code/trade/scripts/com.trade.thinking-proxy-kimi.plist
# settings.json ANTHROPIC_BASE_URL 切换由 scripts/kimi-proxy-switch.sh 双向切换:
bash scripts/kimi-proxy-switch.sh kimi        # 切 8898 kimi
bash scripts/kimi-proxy-switch.sh v4flash     # 切 8899 v4-flash
```

## 备注

- `sensenova-rotate-proxy-kimi.py` 头部已加停用横幅(2026-09-07),运行逻辑未改,防误启动占 8898。
- 停用后如需彻底清理,`com.trade.thinking-proxy-kimi.plist` 文件保留(不删),便于恢复。
