---
name: role-tester
description: 测试 agent 专属规范 — 由 .claude/agents/tester.md 的 skills 字段启动全文注入。含 smoke 清单执行、数据完整性校验(check_data_integrity/check_r2_consistency)、curl 验证要点(§8 三查清单操作化)、R2/CF 一致性校验、测试专属教训蒸馏。共享核心(§6/§22/§23/§8§14摘要/§18索引)在根 CLAUDE.md 自动注入,本 skill 只放角色专属。
---

# 测试 agent 专属规范(role-tester)

> 本 skill 由 tester agent 定义 `skills: [role-tester]` 启动全文注入,确定性加载。共享核心在根 CLAUDE.md(自动注入),此处只放角色专属规范。

## 1. smoke 清单执行
- 读 `docs/smoke-checklist.md`(P0/P1 主功能点清单+数据校验规则,进 git 维护),逐项执行
- 主功能点示例:首页KPI角标/指数表现ETF/分时图hover/情绪分/信号/策略实验室入口等
- 验证方式:curl 数据层(JSON 字段有值/结构正确)+ 关键交互文字描述验证(模型只文本不能看 UI,回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层)
- 失败项立即报,不掩藏

## 2. 数据完整性校验
- **check_data_integrity.py**:deploy.sh 前置,校验关键 JSON"该有的数据在不在"(缺失/滞后/空 key 超标即 FAIL)。规则示例:`board_etf_map.json` 空key占比<30% / `overview.json` a_amount非空 / `intraday_snapshot.json` collected_at今日
- **check_r2_consistency.py**:本地 static-site vs R2 一致性审计(定期跑)
- C 级(数据/后端)改动:本地 static-site + R2 + CF 三处同值校验(§22 一致性铁律)
- 2026-08-06 教训:`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组,致指数表现模块 ETF 全失效("全部无ETF")用户发现时已上线。根因=数据产物损坏无校验拦截

## 3. curl 验证要点(§8「功能 done」三查清单操作化)
- 验收"已上线/done"必须三查齐:
  - ①main 链含 commit:`git log origin/main` 含 hash
  - ②数据层生效:curl 线上 JSON 字段有值/无旧字段残留(教训:amount_forecast={} 空对象没写数值、signals_today 残留 s.sentiment_cyb)
  - ③前端展示层上线:curl 线上 app.min.js/lab.js 含新功能 class/中文字符串(只验①②不验③=前端代码写了但从未 commit main+上线,用户看不到)
- ⚠️ **min 版 JS 验证用字符串非变量名**:terser mangle 重命名 let 局部变量,验证 min 版用 class 名/中文字符串(kst-comp-fill/分项构成/优秀)非变量名
- ⚠️ **curl 带认证头诊断禁止 -v/-i**(会打印请求头泄漏 token);token 从 .env 读不硬编码不 echo(L22)
- 线上验证任一域名到新版即算 OK,不卡单域名 404(ss.fx8.store CF 主站优先 / sss.sugas.site / s.sugas.site)

## 4. R2/CF 一致性校验
- 走 R2 的类别(全量品种多/大 range 历史序列/类别整体大)上传后验证 R2 可达(ssd.fx8.store/{prefix}/);走 CF 的小文件验证 ss.fx8.store/data/* 
- 大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀
- R2 架构 checklist:①该类别的 upload-{prefix} 命令存在? ②前端 fetch 走 R2 URL 或 dataUrl? ③upload-data-large exclude 含该前缀(防双副本)?

## 5. 测试专属教训蒸馏(来自 §18 索引,操作化防重犯)
- **L16 数据没上线R2(漏检重灾区)**:新数据类别上线后确认上传链路完整三步:①export.py upload_r2 清单含该类别 ②launchd 定时覆盖或 deploy.sh 含 ③backfill 补跑上传;独立脚本(无 launchd)的 backfill 手动补跑上传 R2。测完自查"是否还有其他同类文件没传 R2"(§23.2 排查同类)
- **L22 curl -v泄漏token**:curl 带认证头诊断禁止 -v/-i
- **L09 hoverpop"无数据"误判**:测试"无数据/加载失败"类,先验证数据产物层(R2 旧版 vs 新版字段值差异),不只看代码分支
- **L20 grep字面量漏常量**:验"值/配置/阈值"类,grep 字面量无结果先怀疑封装成常量,改 grep 常量名+查赋值行

## 6. 相关文件指针
- docs/smoke-checklist.md(P0/P1 主功能清单+数据校验规则,必读执行)
- docs/data-deploy-quickstart.md(数据上线类速查)
- 根 CLAUDE.md §8「功能 done」三查清单 + §22 数据一致性铁律 + §18 防重犯索引表
