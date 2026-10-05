# 全站告警系统性排查报告(2026-10-05)

> 任务:用户「告警再系统性的排查下 是否都当bug解决了或者优化了」。
> 角色:researcher 只读调研(未改任何业务代码/配置;报告本体落档,commit 与 pending-index/TASKS 更新交主控)。
> 方法:双机(本机 mac 开发 + 云上 122.51.111.173 生产)事件驱动扫描(find -mmin 分档 + 逐文件 tail)+ 逐条四态判定(①已修 / ②已优化(降噪·豁免·调阈值) / ③仍待办 / ④误报判定)。
> 数据快照时点:2026-10-05 13:30~14:10(云上 latest.md 最新告警 10-05 13:30:30)。

## 0. 结论速览

- 在册告警全部完成四态判定(明细见第二~四部分),**无「未分类」遗留**。
- **当前唯一活跃告警链 = R2 上传管道 kill 链**:10-03 引入(export-guard L5 备份串行)→ 10-05 凌晨根因定位 → 11:17 修复上云(9faf92d8e)→ 残余登记 #180。10-05 12:25 新判据下仍 1 次 kill(停滞 300s),13:03 SEVERE「保留告警」= #177 设计语义(被 kill 通道不适用对账静音)。**数据侧已实证无陈旧**(抽样 md5 逐位一致 + PUT 未执行,无半新半旧)。
- **最吵告警 = fetch_news SKIPPED_LOCKED SEVERE**(10-04 22:30 起 5 封):**真阳性**(上游锁真实持续被占),随锁释放恢复;降噪候选**待拍板**(见 A2)。
- baostock 封禁类告警近 4 天 0 复现,但**假期无采集 → 10-08 开市才是真检验**(#166 替代源未见交付、#163 断档回填未清)。
- 盲区 6 项(见第三部分),其中 3 项已在跑专项(#164/#160/#162),3 项为本报告新提(飞书心跳监控空转 / utf-8 截断仅 warn / dry-run 写 latest.md)。

## 一、告警源全景(谁在告警、出口在哪)

| 告警源 | 触发方式 | 出口 | 频率 |
|---|---|---|---|
| notify.py | 各任务脚本 --severe / schedule_monitor 调用 | 邮件(SEVERE 始终发)+ 飞书 + telegram;[severe-mirror] 统一镜像 latest.md(防旁路出口,§18 L46 教训后已实施) | 事件驱动 |
| schedule_monitor.sh(9 维度) | 云上 systemd timer,每 15min | notify.py | 每 15min |
| r2 看门狗(r2_upload_async.sh / deploy.sh 段2) | 停滞 300s(主)/ 低速(辅)/ 7200s 硬兜底(#174 后) | 收尾统一告警 + verify-channels 轻量对账 | 每上传轮 |
| check_monitor_heartbeat.py | 元监控(monitor 心跳 >1800s 告警,dedup 3600s) | notify.py | 每 15min(10-03 新增) |
| check_data_gap / self_heal / 交易记录断档类 | 各业务链路 | notify.py / latest.md | 各异 |
| 告警落点 | 云上 data/alerts/latest.md(主)+ alert_state.json(去重状态,本机快照 93 条)+ 本机 data/alerts/latest.md(镜像) | | |

## 二、逐条四态判定

### A 组:当前活跃链(10-03~10-05,5 条)

**A1【R2 upload-etf-hist / upload-accum-nav 被看门狗 kill → 死循环 + 轻量对账链】**
- 最近出现:10-05 12:25 轮 kill(「upload-etf-hist 停滞 300s 无日志输出, kill pid=508552」)→ 13:03 SEVERE R2 上传失败。
- 状态:**①已修(根因)+ 残余登记(#180 ㈠)**。
- 证据:
  - 根因(10-03 引入):export-guard L5 `_backup_overwritten_keys` 对 1718 key 串行 HEAD+COPY ≈2200s > 旧 900s 总时长判据 → 确定性 kill → marker 残留 → 下轮 force_full → 循环。见 `docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md`(commit 4fc1645c0 引入)。
  - 修复(9faf92d8e,10-05 11:17):备份 8 线程并行 + 判据换代(#174:停滞 300s 主判据)+ 解静音(#177:R2_KILLED 通道 verify-channels 不适用轻量对账静音,`r2_upload_async.sh` L55-56/L193-200)。
  - 新旧行为对照(同日实测):05:10 轮(旧码)=「超 900s kill pid=358286/362314」→ 结尾「R2 失败通道轻量对账通过(数据完整,疑似看门狗超时噪音,不告警)」(静音);12:25 轮(新码)= kill 后「不适用轻量对账静音,保留告警」(13:03 SEVERE)→ #177 语义生效。
  - **数据风险实证(无缺口)**:抽查 510300-all.json / 159915-all.json 三方 md5 逐位一致(云上本地 = R2 下载:75182ce604cb6f1acbc6bb69886fc061 / 815aa5adbc88defc20b68a1928b127a5);4 个 etf 文件 R2 last-modified 全为 09-30 14:29~14:33 GMT → 本轮 PUT 未执行,无「半新半旧」;12:25 轮内 verify-r2 另自动补传 36 个。
- 处置建议:13:03 告警「保留」正确,**无需手动补刷**(内容一致);人工确认点 = 下一轮上传(17:50 deploy 或下轮 r2_upload)未进入重复全量(#180 ㈠ 未结构性根治);10-08 开市后重负载复验。

**A2【fetch_news SKIPPED_LOCKED 连续 3 轮 SEVERE】**
- 最近出现:10-05 13:30:30(tail 窗口内 5 封:10-04 22:30 / 23:30 / 10-05 00:30 / 03:30 / 13:30)。
- 状态:**②已优化(连续 3 轮阈值)+ 真阳性 + 降噪待拍板**。
- 证据:schedule_monitor.sh L442-456(设计注释:单次=设计让路不告警,连续 3 轮≈45min 才 SEVERE)+ L765-839(实现);每封对应真实「R2 上传锁忙」;上游持锁者 = 10-04 22:30 update_all 大上传 + 10-05 凌晨/白天 kill 链各轮上传。
- 降噪候选(附注):时间线核对发现疑似「同一 skip 行被 15min monitor 轮重复消费」——12:25~13:03 持锁期间 fetch_news 实际至多 2 次 skip(:45/:01),而 13:30 即报「连续 3 轮」;计数新鲜窗口 30min 与 fetch_news 最短间隔 16min(:45→:01)存在错配疑点,**待验证**(验证命令见复现段 5.4);若不拍板降噪可不动。
- 处置建议:候选方案「持锁者=update_all/r2_upload 运行中时降为 warn」或错峰窗口豁免;涉及真故障判别维度保留原则(alert_denoise_keep_fault_discriminator),需用户拍板。

**A3【backfill_evening 超时(10-04 21:00 槽 90min 未完成)】**
- 状态:**已自愈**。证据:10-05 02:00 槽 1028s 正常完成(云上 backfill_evening 日志);归因=与周日 22:30 大上传/锁竞争窗口重叠。

**A4【update_all 超时(10-04 22:30 槽)】**
- 状态:**已自愈(8342s 完成,exit=0)**。注:8342s 略超 schedule_monitor 阈值 8100s → 告警为「超阈值边界」,实际完成;列为观测项(不建议动阈值,属真故障判别维度)。

**A5【R2 上传失败 13:03(upload-etf-hist 轻量对账确认缺口)】**
- 状态:**保留正确(设计)**;数据一致性已证(见 A1);等自然恢复,无需人工。

### B 组:09-28~09-30 告警群(R2 锁事故,6 条,全部已闭环)

| 告警 | 判定 | 证据 |
|---|---|---|
| R2 lag 640min | ①已修 | #129 事故(staticdata 备份 10h+ 持 trade_deploy.lock,3.2 万文件串行);P1 熔断/预算已实施(R2_LARGE_JSON_BUDGET=10800s/FAIL_LIMIT=30),10-01 后 0 复现 |
| 排队超时跳过(intraday R2 skip) | ①已修 | 同上;P2 锁分离 #149 于 10-02 交付(锁拆分 /tmp/trade_deploy.lock 与 /tmp/trade_r2_upload.lock) |
| staticdata 变更量超阈值 | ①已修 | 同上,文档 docs/ops/129-staticdata-backup-r2-lock-and-fuse-20260929.md |
| fetch_news 停摆(旧行为) | ①已修 | 后由 --skip-if-locked(fetch_news.py L690-749,绝不静默)+ 下一轮 :01/:45 + 17:50 deploy 兜底链兜住 |
| 交易记录断档 | ①已修 | 09-28 severe → 09-29 自愈 → 09-30 降为 warn(深度1),后续无复现 |
| R2 大 JSON 一致性 | ①已修 | #179 核实完成:large-json/ 整段不能配 lifecycle(会删 31,673 唯一副本);legacy 27,673 由代码 7 天宽限自动清(预计 10-06~10-08 清零),文档 docs/ops/r2-large-json-lifecycle-verdict-20261005.md |

### C 组:设计内正常 / 误报判定(6 条,均无需处置)

| 项 | 判定 | 依据 |
|---|---|---|
| rzhb_backfill dur=1s | ④误报 | T+1 源设计:早晨才发布 T 日数据,记 1s=正常(memory rzhb-dur-1s-t1-normal) |
| kelly_intraday exit=5 | ④误报 | 数据源 fail-closed 设计;10-01 起非交易日跳过 |
| nextday_plan 面板状态残留(hold) | ④误报(外观) | #151 已订正为真阳性、代码不改;面板残留=数据源不同步 → #162 在跑 |
| schedule_stats SKIPPED_LOCKED(rzhb/lhb/public_fund/update_lab 等) | 设计内 | ⚠ 日志级不告警;下轮重试 + 17:50 deploy upload-all-data 兜底 |
| verify_backup 每 21:0x | 正常 | 10-04 全 OK(integrity_check ok + 全部关键表行数一致,见复现段 5.5) |
| [防再犯E守卫] 09-30 本机拦截 | 设计内 | pick_repo.py L105/L151:写部署源树目标错误 → SystemExit 阻断,守卫按设计工作 |

### D 组:历史告警已闭环(5 条)

| 告警 | 判定 | 证据 |
|---|---|---|
| 飞书 hook 心跳告警(09-11~13) | ①已修 | 迁移后不再冒;但云上维度⑧判定有盲区(见三-1) |
| heartbeat 写 Permission denied(09-14) | ①已修 | check_monitor_heartbeat.py(10-03 新增,1800s 阈值)当前 OK(age≈656s) |
| 冻结表缺失 622(09-18) | ①已修(无复现) | 近 14 天 data/logs 全库 grep「冻结表」0 命中 |
| CSP console 刷屏(#133) | ①已修 | pending-index 标已修;**线上复验**:ss.fx8.store 响应无 content-security-policy 头(200) |
| upload-etf-hist 05:10 kill(旧判据) | 对照 | 旧码被轻量对账静音;新码保留告警(见 A1) |

### E 组:baostock 封禁(09-27~30,2 条,开市前必清)

| 项 | 判定 | 证据/建议 |
|---|---|---|
| baostock 登录失败 10002007 / 熔断 | 近 4 天 0 复现(但假期无采集,非确证) | 10-01~10-05 data/logs grep 0 命中;10-08 开市真检验 |
| #166 替代源 / #163 断档回填 | **③仍待办** | #166 未见交付 commit;#163(mootdx/industry_width 09-29~30 断档)10-08 开市前必清 |

## 三、盲区清单(该告警但没配 / 弱覆盖,6 项)

1. **飞书 hook 心跳(维度⑧)在云上永久空转**:schedule_monitor.sh L1835-1970 三层判定依赖 `~/.claude/projects/**/*.jsonl` mtime + claude 进程;但 monitor 已在云上跑(09-13 迁云),云上无 .claude/projects、无 claude 进程、无 /tmp/feishu_hook_heartbeat → 该维度云上无从判定 → **本机侧 hook 真的挂了没人知道**。建议:本机侧挂轻量看门狗,或心跳文件外移后由云上判。→ 建议新登记编号(本报告记 N2)。
2. **#164 磁盘/内存/inode 阈值**:无维度(专项在跑)。
3. **#160 check_r2_consistency 未接线**:§22 三站一致性零校验(专项在跑)。
4. **#162 s06 hold 数据源不同步**:面板 exit=0 vs monitor 判 hold(专项在跑,与本报告 #164 同批)。
5. **notify.py --dry-run + --alert-issue 仍写 latest.md**:dry-run 也污染告警落点(登记待决)。
6. **schedule_monitor utf-8 截断检查失败仅 warn**:R2 直连部分截断场景静默、无 severe 升级路径 → 建议评估升级(本报告记 N3)。

## 四、未处理项汇总(可直接转 pending,6 项)

| 建议编号 | 项 | 来源 | 时限 |
|---|---|---|---|
| N1 | fetch_news SKIPPED_LOCKED 降噪拍板(候选:持锁者=大上传运行中→warn;附计数窗口校准) | 本报告 A2 | 用户拍板 |
| N2 | 飞书 hook 心跳监控补位(云上空转) | 本报告 三-1 | 近期 |
| N3 | utf-8 截断检查 warn→severe 评估 | 本报告 三-6 | 近期 |
| N4 | dry-run 写 latest.md 处置 | 本报告 三-5 | 近期 |
| #166 | baostock 替代源(+17:50 槽跳过) | 已在册 | 10-08 开市前 |
| #163 | mootdx/industry_width 断档回填 | 已在册 | 10-08 开市前必清 |
| #180㈠ | R2 kill 后死循环结构性根治(上传管道韧性专项) | 已在册 | 专项 |
| #165/#164/#160/#162 | 回滚预案/监控盲区/一致性接线/s06 数据源(均在跑) | 已在册 | 在跑 |

另注:#179 已核实完成;#174/#175/#177 已实施;#151 已订正(真阳性不改码);#149 剩④timer 错峰+10-08 观测。

## 五、复现段(取证命令,逐条可复核)

> SSH 统一前缀:`ssh -i /Users/linhuichen/tdsignal.pem -o ConnectTimeout=15 -o BatchMode=yes ubuntu@122.51.111.173`,云上根 `/home/ubuntu/code/trade-data`。

### 5.1 告警源与最近告警
```
ssh ... 'tail -40 data/alerts/latest.md'          # 本报告"最近仍在冒"来源(尾部至 10-05 13:30:30)
# 本机镜像:data/alerts/latest.md;去重状态:data/alert_state.json
```

### 5.2 R2 kill 链(A1/A5)
```
ssh ... 'cd /home/ubuntu/code/trade-data && grep -h "停滞\|kill" data/logs/r2_upload_async_20261005_*.log | tail -8'
# 期望:旧判据 4 行(超 900s,02:16/05:10 两轮)+ 新判据 1 行(停滞 300s,12:25 轮)
ssh ... 'tail -15 data/logs/r2_upload_async_20261005_051055.log'   # 旧码静音对照(轻量对账通过不告警)
ssh ... 'tail -30 data/logs/r2_upload_async_20261005_122501.log'   # 新码保留告警轮
# 数据一致性实证(三方 md5 逐位):
curl -s --max-time 30 -o /tmp/r2_510300.json https://ssd.fx8.store/etf/510300-all.json && md5 -q /tmp/r2_510300.json
curl -s --max-time 30 -o /tmp/r2_159915.json https://ssd.fx8.store/etf/159915-all.json && md5 -q /tmp/r2_159915.json
ssh ... 'md5sum static-site/data/etf/510300-all.json static-site/data/etf/159915-all.json'
# 期望:R2 下载 = 云上本地 ×2(75182ce6... / 815aa5ad...)
```

### 5.3 看门狗 / #174 / #177 代码锚点
```
grep -n "R2_UPLOAD_STALL_SECS\|停滞\|7200" scripts/r2_upload_async.sh | head
sed -n '55,56p;193,200p' scripts/r2_upload_async.sh     # #177 解静音语义
git log --oneline -3 9faf92d8e                          # 10-05 11:17 修复
cat docs/ops/r2-residual-risks-20261005.md              # #180 残余登记
cat docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md  # 根因
```

### 5.4 fetch_news 连续阈值(A2)
```
grep -n "R2_SKIP_CONTINUOUS_THRESHOLD\|SKIPPED_LOCKED" scripts/schedule_monitor.sh | head
sed -n '442,456p;765,839p' scripts/schedule_monitor.sh  # 设计注释+实现(新鲜窗口/连续计数)
```

### 5.5 自愈确认 + verify_backup
```
ssh ... 'cat data/logs/verify_backup_20261004_2108.log | tail -25'   # 期望:integrity 全 ok + 行数全 [OK] + 退出码=0
ssh ... 'tail -5 data/logs/backfill_evening_launchd.log'              # 10-05 02:00 槽 1028s
ssh ... 'tail -5 data/logs/update_all_launchd.log'                    # 10-04 22:30 槽 8342s exit=0
```

### 5.6 盲区取证
```
ssh ... 'ls ~/.claude/projects 2>&1; ls /tmp/feishu_hook_heartbeat 2>&1; pgrep -c claude 2>&1'   # 云上均不存在 → 维度⑧空转
grep -n "1800\|STALE" scripts/check_monitor_heartbeat.py | head
```

### 5.7 baostock / 冻结表 / CSP
```
ssh ... 'grep -l "10002007" $(find data/logs -name "*.log" -mmin -5760) 2>/dev/null'      # 近 4 天期望 0
ssh ... 'grep -l "冻结表" $(find data/logs -name "*.log" -mmin -20160) 2>/dev/null'       # 近 14 天期望 0
curl -sI -A "Mozilla/5.0" --max-time 20 https://ss.fx8.store/ | grep -i "content-security"  # 期望无输出
```

### 5.8 部署一致性交叉验证(本机=云上代码)
```
# 三文件 md5 本机 vs 云上(截取时点已一致):
md5 -q scripts/r2_upload_async.sh    # 0a550fa1ecfbcc79b5fb9aa8115e0fcd(云上同)
md5 -q scripts/fetch_news.py         # 97c957031ceafd513a573b5323e14e45(云上同)
md5 -q scripts/schedule_monitor.sh   # 9b284f1019d44d8de942ddc205068441(云上同)
```

## 附:报告边界(诚实标注)

- 本报告为**时点快照**(2026-10-05 14:10 前后),活跃链(A 组)结论在此后可能随上传轮次变化;「自愈」类结论基于对应任务最近一次成功运行日志。
- B 组「10-01 后 0 复现」为 grep 取证(近档日志),非排除性证明。
- E 组 baostock「0 复现」受假期无采集影响,不代表已修复,开市前须按 #166/#163 落实。
- A2 的「重复消费疑似」为时间线推导,未读死计数实现细节,已在报告内标注待验证命令。

## 六、任务书候选点名项核对(逐项落点)

| 任务书点名 | 落点 | 结论 |
|---|---|---|
| fetch_news 周日夜 SEVERE 噪音(待拍板) | A2 | 真阳性(上游锁被占);已优化(连续3轮阈值);降噪候选待拍板 N1 |
| upload-etf-hist 被看门狗 kill(05:10 同款) | A1 + D 组 | 根因已修(9faf92d8e);05:10=旧码静音对照;12:25=新码保留告警;数据无缺口 |
| rzhb_backfill dur=1s | C 组 | 误报判定:T+1 源设计正常 |
| baostock 封禁 / 10002007 | E 组 | 近 4 天 0 复现(假期无采集);#166/#163 开市前必清 |
| 信号凯利异常演进 / accum_nav lag | B 组 + A1 | kelly trades 断档(=signal_kelly_trades.json 深度3,09-28)= B 组交易记录断档同链已自愈;近 7 天日志「异常演进」关键词 0 命中;accum-nav 通道被 kill = A1 |
| R2 large-json 残留/一致性 | B 组尾条 | #179 已核实(lifecycle 结论);legacy 7 天宽限自动清(预计 10-06~10-08) |
| 磁盘·内存·inode 阈值(#164) | 盲区 2 | 无维度,专项在跑 |
| CSP console 刷屏(#133) | D 组 | 已修;线上复验无 CSP 头 |
| 冻结表缺失/信号类型漂移 | D 组 | 近 14 天 0 复现(冻结表关键词) |
| latest.md 单通道旁路 | 全景表 + 盲区 5 | [severe-mirror] 已实施;残余=dry-run 写 latest.md(N4) |
