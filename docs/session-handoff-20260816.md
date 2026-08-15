# 会话移交 20260816 (AI监控卡二次迭代进行中)

> 触发=重启会话/compact 后恢复。本文件记录 2026-08-16 会话的关键状态,重启后可据此恢复。
> 关联 memory: session-handoff-20260813 / user-usage-memory-beats-my-inference / compact-recovery-checklist

## 1. 当前在跑 agent(实施中,勿重复派单)

| 任务 | agent | 状态 |
|---|---|---|
| **AI监控卡二次迭代 5合一** | implementer `a2f6d2c9c7400e724` | 🔄 后台跑, 正在改 app.js + overfit_monitor.py(git 显示 M) |

**进度**: implementer 已收到「K档×降亏=两开关独立(首页同款)」修正(2026-08-16 用户拍板), 正在改。改动文件: static-site/app.js + scripts/overfit_monitor.py + 重跑数据产物。

## 2. 任务清单(TASKS.md 对应)

- **#18 ✅ 已上线**(0a408b022): 监控卡三合一(默认开+K档UI预留+轻量SVG)
- **#19 ✅ 已上线**(f5d218492): K2C5比值4.55+文案精简
- **#20 🔄 in_progress**: AI监控卡二次迭代(K档交互+SVG/echarts对齐+窗口语义+❓教学弹窗+reviewer返修)
- **#21 🔄 in_progress**: 实施AI监控卡二次迭代(5合一) = 上面 implementer 正在跑的

## 3. 二次迭代 5 块方案(已全部拍板, implementer 正在实施)

1. **K档启用(后端补 by_k 4档)**: overfit_monitor.py 生成 by_k[k] K=1/2/3/4。
   - **K档数据 = 全信号集 top-K**(不是过滤集!用户两次确认, 和首页一致: 降亏开关只门控「top-K 输入人口是否先滤」, 降亏关→K 从全信号选, 两开关正交独立)
   - 前端 K 档改可点选(像 lab.js「AI仓位建议K」), 与 AI降亏过滤开关**同一行**
   - 排序口径复用首页 `_posCapSortedFn`(app.js L2453-2467): track_score DESC → rating(high>mid>low) → signal(buy_backup>buy>buy_aux>buy_special) → buy_date ASC
2. **SVG 3色为基准**: echarts fallback 去掉固定色(L1706 `#409eff`)让 visualMap 3色生效
3. **reviewer返修4项**: P1 localStorage try/catch(L1826-1828, catch默认true) + P2-1 空态摘除 _lwRenderers(L1574-1580/L1650-1658) + P2-2 dataZoom pb 26→44(L1591/L1670) + P2-3 lite y轴固定0-100(_lwValueExtent L12046 加 min/max 参数)
4. **窗口语义改「显示范围」**: 横轴截取最近N日, 统计口径固定60日滚动。更名「窗口」→「显示范围」, tooltip 补说明。附带: rolling 只留 60 一套省体积
5. **❓弹窗重写**: hover 短1-2句 + click 弹详版使用指南(复用 .rule-modal, 对齐 _SIGNAL_HELP_ITEMS 范式; 新增 _overfitHelpModalHTML + _openOverfitHelpModal + _initOverfitHelpDelegation 绑 [data-overfit-help])

## 4. 实施完成后必做(上线链路, 未做不算 done)

- 版本串 bump(app.js a274→a275): `node scripts/build_min.js` + `python scripts/bump_asset_version.py` + sw.js CACHE_VERSION 同 commit
- 重跑 overfit_monitor.py(在 trade-data 下跑, `--rebuild` 全量)产出 by_k
- 数据产物改了 → `bash scripts/deploy.sh` 推 R2/static-site(§22 三步)
- §8 三查: ①main链含commit ②curl 线上 overfit_monitor.json 有 by_k ③curl 线上 app.min.js 含新字符串/class
- 公示同步(§21/§23.6): 监控卡 tooltip/purpose-notes.js
- **⚠️ 避盘后时点**: 15:35/16:00/17:50/20:35/22:00 不推 main
- commit 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`

## 5. 实施完成后待派 reviewer 回归(§15 B级必审)

- 审查: K档后端数据正确性(by_k 结构/排序口径/top-K 与首页一致性) + 前端K档交互/降亏同行 + 窗口语义 + ❓弹窗 + reviewer返修4项 + SVG/echarts对齐 + 版本串/上线三查 + 没改坏老功能
- 尤其: K档×降亏叠加(降亏开→对K档数据再滤, 降亏关→纯K档全信号), 与首页口径一致

## 6. 本次会话已收尾(不需再做)

- #17 ✅ 公示同步+清理(364e6a97f)
- #18 ✅ 监控卡三合一(0a408b022, reviewer FAIL 1P1+3P2 已并进 #20)
- #19 ✅ K2C5比值(4.55, f5d218492)
- 每日总结 ✅ 落档(b46660a1c, L34-L39/E27-E30)
- cron 索引同步 ✅ 上 main(553e4c276)
- 落档 memory: user-usage-memory-beats-my-inference(K档×降亏两次忽悠教训)

## 7. 时点/恢复注意

- 用户睡前指示: 「连轴转后自己总结整理, 醒来可以clear」→ 本文件即交接文档, 重启后先 Read 本文件 + MEMORY.md 恢复
- 若 implementer 已完成且通知未收到, 检查其 output 文件最后时间戳; 完成后立即: 派 reviewer 回归 → PASS 后 merge → 三查上线
