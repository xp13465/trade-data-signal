# 云服务器系统性体检报告集(2026-10-03)

> 本文件为 7 份分维度体检报告的**索引 + 摘抄归并**,只搬运各报告「结论速览 / 分级问题表 / 反证项」原文,不新增判断、不改写结论。7 份报告本体见同目录 `D1~D7-*.md`。

## 一、背景与范围

- **为何做**:2026-09-12 迁云后首次全面系统性体检(此前 D0 及单点诊断已出,D1-D7 为 7 维度并行的完整体检集)。
- **7 个维度**:
  1. D1 云服务器资源与配置体检(磁盘/内存/inode/日志轮转/systemd 单元 vs 文档漂移)
  2. D2 定时任务逐个可靠性体检(38 个 timer 逐个对账,含静默失败排查/时点冲突/依赖顺序)
  3. D3 告警体系覆盖面体检(通道可用性/38 任务×告警覆盖矩阵/降噪反噬回放/latest.md 双区/元监控)
  4. D4 数据源与数据链路可靠性体检(数据源全景/降级切换实证/换源判据/gap 检测覆盖/R2 链路)
  5. D5 发布/部署链路与回滚体检(发布链全图/闸门失效测试/回滚能力/三站一致性/未收口项)
  6. D6 备份/灾备可恢复性实测(4 层灾备逐层抽样取回 + md5/逻辑对账,非"应该有")
  7. D7 安全/密钥/权限体检(凭据清单/PURGE_SECRET 事件收口/误 tracked 扫描/暴露面/文件权限)
- **全程只读口径**:所有报告云上零写入、本仓除各报告文件外零提交;**只诊断不治疗**——所有 P0/P1/P2 建议均为后续动作,与本次体检隔离。
- **观察窗口**:2026-10-03(国庆休市,A 股 10-01~10-08 休市,休市跳过属正常);D2/D4 等含近 14 天(09-20~10-03)或上一交易日 09-30 的窗口回看。

## 二、报告索引表

| 维度 | 报告文件 | 一句话结论(摘抄自各报告「## 0 结论速览」) |
|---|---|---|
| D1 资源与配置 | `D1-cloud-resource-audit.md` | 「磁盘比 09-30 好转:可用 4.7G → 11G(已用 52G→47G,83%),09-30 清理建议绝大部分已执行;但今日 10:47 新出现 public_fund.db.bak 双仓各 5G(共 10G)一次性残留、无脚本生成者,是当前最大单点风险;37+1 个周期任务 38/38 enabled+active 零漂移;磁盘/内存/inode 阈值告警是盲区」 |
| D2 定时任务 | `D2-timer-reliability-audit.md` | 「38 个 timer 全在位、38 个 service 最近结果全 success、0 failed;未发现真正『exit 0 假成功/静默失败』;已定位 2 个需跟进异常(nextday-plan 09-30 R2 超时失败 exit=1 无重试、schedule_monitor 对 s06 的状态残留 hold);149 锁拆分根治已落地云上、149d 错峰待办未执行」 |
| D3 告警覆盖 | `D3-alert-coverage-audit.md` | 「通道健康:email+feishu 双通道近 14 天 50/50 全 OK、0 FAIL;但 38 个周期任务里 12 个完全裸奔 + brief_push 退出码恒 0(失败永久静默)+ schedule-monitor 自身 heartbeat 无消费方 → P0;latest.md 双区结构严重告警可被静默覆盖;降噪反噬风险总体低(5 个历史真故障套现行 R1~R6 规则全部仍会发)」 |
| D4 数据源链路 | `D4-datasource-chain-audit.md` | 「自动切换真生效且有日志(mootdx→baostock fallback 9/21-9/28 每天命中、东财 ETF 行情被封→新浪+腾讯兜底 9/25、10/3 实锤命中);但 9/29-9/30 出现『双腿同死』窗口(mootdx 主源空 + baostock 登录失败)→ mootdx_daily_raw/industry_width_daily 断档 2 天无人告警 → P1 回填;akshare stock_daily 第三源伪兜底依旧;R2 增量已生效未根除(fetch_news SKIPPED_LOCKED 10/1、10/3 仍 3/3 severe);迁云后异源可达性未重测(8/27 结论不可沿用)」 |
| D5 部署/回滚 | `D5-deploy-chain-audit.md` | 「链路架构已正确(main-merge.sh 唯一 push main 入口 + 云上 deploy.sh 两段式,149a 锁拆分 + export-guard 7 层防护均合 main 且云上确认落地);但存在 8 项 fail-open 闸门清单(重点:R2 上传 18 通道失败不阻断、with_lock.py 排队超时=优雅跳过 exit 0 静默丢代码、verify-r2 平日抽样兜不住批量残留);回滚能力:能回滚、最快约 30 分钟;三站一致性核心校验器 check_r2_consistency.py 是死的(全仓无自动调度点);149d timer 错峰未落地」 |
| D6 备份可恢复 | `D6-backup-recoverability-audit.md` | 「4 层中 3 层抽样恢复全 PASS、1 层(DB 子集)存在 P0 缺口——public_fund.db(2.76GB)/ stock_daily.db(145MB)无任何 R2/git 异地备份、本机副本过时(停 9-12/9-13),盘毁即丢近 3 周数据;large-json 固定前缀全量清单一一对应(MISSING=0 / EXTRA=0,31673 key 三方吻合);每日 21:00 verify_backup.sh 自动恢复演练已跑 21 天、最近 3 次全 PASS」 |
| D7 安全/密钥 | `D7-security-audit.md` | 「P0 #1:PURGE_SECRET 未轮换,现值=2026-09-12 public 仓泄漏值(公开 21 天仍为线上在用值);P0 #2:本机 9 处含密文件/私钥权限过宽(644/444,云上侧全部 600 无此问题);P1:sshd PermitRootLogin yes + fail2ban 未启用(14 天 81 次 Invalid user 爆破噪音);反证:外部暴露面仅 22、密码登录关、敏感配置本地+云上 git 历史零提交、当前 tracked 文件零处含泄漏值」 |

## 三、P0 汇总表(合计 10 条)

> 逐条从各报告「分级问题表」搬运,一个问题不漏、不合并、不淡化。

| 来源维度 | 问题(现象+影响) | 建议 | 锚点 |
|---|---|---|---|
| D3 | **schedule-monitor 自身挂停无告警**(heartbeat 无消费方)→ 监控体系整体停摆无人知 | heartbeat 消费方(独立 cron 检查心跳新鲜度,超时告警) | D3 §6 / P0-1 |
| D3 | **brief_push 退出码恒 0+无 notify** → 用户订阅推送断了没人知道 | wrapper 失败时 notify --severe;或 monitor 按产物新鲜度检查推送结果 | D3 §3-2 / P0-2 |
| D3 | **12 个任务完全裸奔**(etf_track/lof_track/fapi_daily/ab_direction/daily_summary/pf_score×2/pf_stage0×4)→ 挂停无人知,评分/指数/日报用旧值 | 纳入 monitor 漏跑名单(TASKS)+按产物新鲜度补数据层检查 | D3 §3-1 / P0-3 |
| D3 | **latest.md 双区结构:严重告警被恢复/后续覆盖** → 用户开工看到"恢复"以为没事,真 severe 沉流水区 | 覆盖区语义改为"最新 severe"或覆盖区含最近一次 SEVERE 引用 | D3 §5 / P0-4 |
| D5 | **§22 三站一致性校验器 check_r2_consistency.py 未接线**(local vs R2 vs CF r2-proxy 9 个核心产物)→ 10-02 事故同款若再发生无自动探测;§22 铁律"校验是否真在跑"不成立 | 接入 schedule_monitor(15min 巡检)或 deploy 段1(每次 deploy 后),FAIL → notify --severe;补主站 /data/ 与两备站受检 | D5 §6 / P0-1 |
| D5 | **verify-r2 平日模式仍兜不住批量残留**(lab/trade_sim changed=0 时抽样 100 查不到 482)→ 批量"本地没变但 R2 被外部覆盖"场景只能等周日全量对账(最长 7 天) | verify-r2 平日对账加"全通道 key 数/规模指纹"级检查(全量 HEAD 成本可控化)或异源覆盖告警阈值降敏 | D5 §2 #11 / P0-2 |
| D6 | **public_fund.db(2.76GB)+ stock_daily.db(145MB)无任何异地备份,唯一最新副本=云上单机** → 盘毁/R2 数据损坏同时发生时,场外基金持仓净值(近 3 周)+ 日行情数据只能回退到 9-12/9-13 本机旧快照 | ①将两个 DB 纳入每日异地备份(upload-db 扩展 targets 或走 R2 大文件通道;public_fund gz 压缩预计 ~15-25min,21:00 窗口可容纳)②或至少建"云上→本机每日同步"异地副本 ③修复前 P0 悬置,不销账 | D6 §1 补充事实 / P0-1 |
| D7 | **PURGE_SECRET 未轮换,现值=2026-09-12 public 仓泄漏值**(公开 21 天且仍为线上在用值)→ 任何人可从 public 历史提取调用 CF /api/purge-cache(可清缓存,无数据篡改/泄露) | 轮换:改本地+云上 .env → wrangler secret put → purge 回归验证;或用户重新拍板长期保留并给"关闭敞口"时点 | D7 §2 / P0 #1 |
| D7 | **本机 9 处含密文件/私钥权限过宽(644/444)**:trade/.env、trade-data/.env、config/{email,feishu,telegram,sub_pwd,brief_push}.json、~/Desktop/tdsignal.pem(444)、~/Desktop/id_rsa(644)、~/Downloads/…/应用私钥2048.txt(644)→ 实际利用者=其他本地账户/未来新增用户/后台进程,违反最小权限 | 一键 chmod 600 全部;Desktop/Downloads 私钥副本删除或移入加密卷 | D7 §1.2 / P0 #2 |
| D7 | **生产私钥同值副本 444 散落 Desktop**(~/Desktop/tdsignal.pem,hash 与在用值一致)→ 生产服务器 root 权限等价物以明文可读存桌面 | 删除副本或 600+移入安全位置;若怀疑已暴露则轮换服务器密钥 | D7 §1.2 / P0 #3 |

## 四、P1 汇总表(合计 22 条)

> 逐条从各报告「分级问题表」搬运。

| 来源维度 | 问题(现象+影响) | 建议 | 锚点 |
|---|---|---|---|
| D1 | **磁盘/内存/inode 无阈值告警**(schedule_monitor 9 维度清单无资源维度)→ 磁盘写满→任务失败/DB 报错/告警链断裂,无人最先知道 | 在 schedule_monitor 加维度⑩:df 使用率≥85%→warn / ≥95%→severe,inode≥90%,内存可用<500M 或 swap>80%;或独立 df -h + notify.py 每小时检查 | D1 §5 / P1-1 |
| D1 | **public_fund.db.bak 双仓各 5G(共 10G),10-03 10:47 生成,无脚本生成者** → 占可用磁盘 45%;若每日生成将 5 天打满(当前证据=单次) | 主控确认 10-03 上午是否有手动备份(#154 相关?);确认用途后两仓同删(mtime 已 3 天且 R2 signal-backup 有 db 备份+verify 演练可恢复);若确认是重复性操作→修脚本进 backup_db.sh 并加保留策略 | D1 §2 / P1-2 |
| D1 | **fetch-news 10-01 4 次 timeout 失败且 09-30 曾 permission 崩溃** → 10-01 新闻采集缺口 | 已自愈(success 10-03 18:01);补充观察:若再 timeout,查 journal 该时点锁竞争(deploy_lock 排队超时 09-30 曾 5 次) | D1 §3 / P1-3 |
| D2 | **P1-a nextday-plan 09-30 失败(exit=1)且无重试**:R2 上传超时 300s 判失败,产物已全部落盘、告警已发(email+飞书+latest.md),失败后无重试 → 10-01 计划生成失败;10-07 22:30 自动重跑补 | ①给 nextday-plan 的 R2 上传段加失败重试(如重试 2 次 + 超时放宽);②或在失败时把"产物已落盘但 R2 未上传"标记交给次日 update-all 补推兜底;失败语义改为"产物已落盘则非致命,仅告警不 exit 1"(需 implementer 评估) | D2 §6 / P1-a |
| D2 | **P1-b schedule_monitor 对 s06 的状态残留 hold**(监控数据源不同步):s06 09-28 exit=143 已恢复(schedule_stats.json last_exit=0),但巡查日志仍持续 [hold] → s06 旧异常持续展示;若 s06 再失败,suppress 逻辑可能因"已告警过"而不重发,造成漏报 | 核查 schedule_monitor 中 s06 的"exit/dur"读取来源与 last_exit 更新路径,确认 09-30 成功为何没清 hold;开市前(10-08 前)处理 | D2 §6 / P1-b |
| D3 | **kelly_intraday_rerun/gold_night/backup_db 自身 notify 只在真跑时触发,timer 挂=静默** → 漏跑无人知 | 纳入 monitor TASKS 漏跑名单 | D3 §3-3 / P1-1 |
| D3 | **daily_brief/fetch_news EXTRA 只查 log 异常,漏跑无** → 漏跑无人知 | 补漏跑名单或产物新鲜度检查 | D3 §3-3 / P1-2 |
| D3 | **public_fund 系列 4 个任务层无监控**(数据层 checker 11/12 有兜)→ 直接挂没人知道,滞后到 nav 缺才反映 | 任务层补漏跑监控(优先级低于 P0) | D3 §2.2 / P1-3 |
| D3 | **monitor_72h 失效残留**(72h_ 键 + /tmp 哨兵缺失)→ 曾承担 public_fund 漏跑检查,现无覆盖 | 清理残留 or 决定是否重建 72h 监控 | D3 §6 / P1-4 |
| D4 | **mootdx_daily_raw + industry_width_daily 9/29/9/30 断档 2 天,需回填** → 全A日线/行业宽度历史序列缺 2 天;width_history run_recent(30天窗)10-08 开市后无法自愈(源表无当日行) | baostock_daily_raw 9/29/9/30 有 5199 只,10-08 前重跑 fallback 回填 mootdx_daily_raw 两日 + 补算 industry_width_daily | D4 §2.3 / P1-1 |
| D4 | **baostock 间歇封禁/网络错误,fallback 每日 17:50 时不可用**(9/21 尾部 688 段、9/29/9/30 login 失败;21:00 槽却成功)→ mootdx_daily_raw 依赖 baostock 补最后几段;封禁窗口整条宽度链断 | 8/27 T1 方案「封禁期间自动改走替代源(akshare/腾讯)」落地;baostock 恢复后单连接串行+限速;封禁期 17:50 槽直接跳过不空转 | D4 §2.3 / P1-2 |
| D4 | **akshare stock_daily 第三源伪兜底(8/27 已报,迁云后依旧)**:每日 skip "no progress yet" → 全A日线真第三备不存在,双腿(mootdx+baostock)同死即断 | 手工 stock_daily full backfill 一次初始化 progress;此后 runner 自动增量(8/27 T3) | D4 §2.4 / P1-3 |
| D4 | **R2 fetch_news SKIPPED_LOCKED 未根除**(10/1、10/3 3/3 severe)→ news_digest 收盘/每日版可能滞留未上 R2,前端读旧 | 查 149a lock-split 后 fetch_news 与谁争锁(疑似 long 任务超时持锁);锁按任务拆分或加超时强制释放 | D4 §5.1 / P1-4 |
| D4 | **ETF close 双源空无第三备**(深市/QDII 段 9/30 集中,561/562/589 段常发)→ ETF 当日 close 缺失 → 份额/信号/前端卡读昨日 | 给 ETF close 加腾讯 qt.gtimg 第三备(sina+mootdx+tencent 三源);缺失名单进 gap 检测 | D4 §2.5 / P1-5 |
| D5 | **149d timer 错峰未执行**:20:05 futures 对 20:07 etf 双全量 deploy 段1 同刻并发(锁拆分后段1 无锁)→ 段1 并发窗口互相覆盖 static-site JSON 写中间态(§22 一致性)+ R2 带宽放大 | 按 149d §5 建议 1-4 执行(需云上 systemd 写授权):futures→19:45、public-fund→16:20、lhb→18:50、futures 点2→21:20 | D5 §7 / P1-1 |
| D5 | **无集中发布回滚预案文档**:代码回滚约 30-40min 且流程靠 agent 规范,无文档化 → 真出 P0 事故时回滚决策链长,靠现场推演 | 新增 docs/ops/rollback-playbook.md:代码回滚(revert+bump 新串+校验链)、数据回滚(恢复源四层+顺序)、版本串/SW 回滚(前进式+验证)三步预案 | D5 §5.3 / P1-2 |
| D5 | **with_lock.py 排队超时 = 优雅跳过 exit 0**:deploy 段2 git push 若排队超 3600s,deploy 整体 rc=0 但代码 min 未推(静默丢代码)→ "rc=0≠git 已推"是认知盲区 | 段2 with_lock 超时改 exit 非 0 或超时前告警升级;至少日志标注"git 段被跳过" | D5 §2 #12 / P1-3 |
| D6 | **本机 staticdata 镜像过时且无自动同步**(09-26 vs 10-03,落后 7 天)→ 本机作为"异地副本"的时效性失效(当前靠 R2 large-json 兜底,风险可控) | ①明确"本机 staticdata 镜像非实时灾备、仅回退保险"降级标注 ②或加周度手动 git fetch origin && git merge --ff-only origin/main | D6 §1 / P1-1 |
| D6 | **large-json 唯一完整副本无版本历史**(固定前缀覆盖,旧版即丢)→ 只能恢复到"最近一次完整上传"的快照,无法恢复到特定历史日 | 保持现状(设计决策);每季度 restore-large-json.sh --all 演练一次,确认全量可拉回 | D6 §1 / P1-2 |
| D7 | **sshd PermitRootLogin yes** → root SSH 登录开放(密码登录已关缓解,实际风险有限) | 收紧为 no,root 走 ubuntu+sudo | D7 §4.2 / P1 #4 |
| D7 | **fail2ban 未启用** → 爆破噪音(14 天 81 次/24 IP)无主动拦截层 | 装并启用 fail2ban(限 22 端口,可观察期后决定) | D7 §4.4 / P1 #5 |
| D7 | **支付宝应用私钥/163 RSA 私钥 644 散落 Downloads**(~/Downloads/hnflzfb01@163.com/,2022 年文件)→ 第三方支付密钥明文可读 | 600 + 移入加密卷;确认是否仍在使用,不用则归档加密 | D7 §1.2 / P1 #6 |

## 五、反证项汇总(查过没问题的)

> 各报告「反证项/确认正常」节原文条目汇总,让读者看见"哪些是好的"。

**D1(资源,§6,12 项)**:时区/时间同步(NTP sync=yes)✓ / CPU/负载(4 vCPU,top 98.4% idle)✓ / 内存(2.7G avail,无 OOM)✓ / inode(根分区 8%)✓ / 内核/启动(单内核 20 天无重启)✓ / 网络出口(无 TIME_WAIT 堆积,overview 200)✓ / journal 完整性(verify PASS)✓ / 系统日志轮转(syslog/auth.log 每周轮转)✓ / staticdata 备份健康度(heartbeat ok,monitor C3 已接线)✓ / 静态产物与 DB(public_fund.db 16:01 每日刷新,9 目录无爆炸)✓ / 备份恢复演练(verify_backup.sh Result=success)✓ / 出网超时频次(近 7 天无连接超时类记录)✓

**D2(定时任务,§5,16 项)**:38/38 timer 在位且 OnCalendar 真值与文档一致、38/38 service 最近结果全 success 0 failed、休市跳过 10 个"1 秒极短"任务全部有「非交易日,跳过」文案、未发现 exit 0 静默失败(日志有输出+产物 mtime 吻合);16 条逐项反证:daily-summary-supplement 邮件已发送(.err 真实日志)✓ / etf-national-team 休市跳过✓ / futures-backfill 休市跳过✓ / lhb-backfill 休市跳过✓ / s06 09-30 机检六项全 PASS✓ / turnover-backfill 休市跳过✓ / public-fund-full 休市跳过✓ / overfit-monitor 09-30 exit=0✓ / check-data-gap 09-30 exit=0(带 warn 提示)✓ / nextday-gap-check 09-30 无伪跳空✓ / update-all 今天休市补推 18:13:47 exit=0✓ / gold-night 无夜盘跳过✓ / daily-brief 休市跳过✓ / backup-db 10-02 两份 DB 备份在位✓ / pf-stage0-nav/manager 大任务成功✓ / intraday-snapshot 09-30 交易日 29/30 档 STAMP 日志在位✓

**D3(告警,§8,7 项)**:主监控链正常(schedule_monitor 15+EXTRA 2 轮询正常,10-03 18:15 最新轮 OK 无漏跑无退出失败)✓ / 通道 50/50 全成功(近 14 天 50 条 severe 流水零 FAIL,SMTP 254 次全成功)✓ / systemd 近 7 天无意外(仅 fetch-news timeout 4 次已被 EXTRA 覆盖)✓ / fapi_daily 今日正常(10-03 18:10 exit 0)✓ / 休市期行为正确(10-02/10-03 无交易日任务告警)✓ / 数据层覆盖面可观(checker 1-12 + check_s06_freshness + check_r2_consistency)✓ / 降噪测试完备(R1~R6 35 项断言全 PASS)✓

**D4(数据源,§7,6 项)**:核心指数链 9/28-9/30 全齐(157/158 条,新浪主源+baostock+腾讯补采)✓ / gap-check 9/29-9/30 零 severe(9/29 还有 kelly 断档恢复通知)✓ / 9/25 交易日判定正确(双源互证为休市调休日)✓ / 换手率分布链 9/29/9/30 未断(a_turnover_mean 2.482/2.505 有值)✓ / 全市场宽度 9/29/9/30 正常(3471/1932/57/14213 有值)✓ / news 采集/新闻看板正常(唯一问题 R2 上传锁)✓

**D5(部署,§8,6 项)**:今天(非交易日)主链全 PASS(check_version_consistency 3 项 + check_version_progress A/B + 占位残留 0 + verify-r2 补传 35 + 段2 git 5 秒 + 退出码 0)✓ / 云上代码=本地 main=fc951666a 干净,sync_cloud_pull 工作正常✓ / 10-02 事故已闭环(fixed 541/skipped 21/missing 0/failed 0,10-03 继续补传 35)✓ / export-guard 判据零误伤(云上恒 True 放行/本机恒 False 拒)✓ / 锁拆分根治实证(段2 秒级,async 独立非阻塞锁)✓ / R2 灾备四层齐全(signal-backup+pre-upload+mac-backups+staticdata git 历史)✓

**D6(备份,§8,5 层可恢复,附 md5 证据)**:①trade git(clone 远端 HEAD=本机=云上=101073af8,deploy.sh md5 6d0281ea / upload_r2.py md5 9f42511b 逐位一致)✓ / ②staticdata git(HEAD=云上=0a64585,news_digest md5 9fdc6f9d / README 488538e2 一致)✓ / ③R2 large-json(固定前缀 31673 key == 磁盘 31673,MISSING=0;抽样 fund_nav/000011.json md5 02cb43fd 一致)✓ / ③R2 DB(integrity ok + 7 关键表行数逐表一致:38555/232257/71371/494512/80780/9975/44340)✓ / ④R2 公开桶(industry-5y-concepts.json md5 5d81db76 一致,15741370B)✓

**D7(安全,§7,8 项)**:云上含密文件权限全 600(.env+config 5 件)且未 tracked✓ / 外部暴露面仅 22(数据库/缓存/应用端口全闭)✓ / 密码登录关闭(14 天爆破 0 Failed password,成功登录唯一来源 IP=用户本机)✓ / 敏感配置本地+云上 git 历史零提交✓ / 当前 tracked 文件零处含泄漏值,systemd 37 个 unit 零内嵌明文(全走 EnvironmentFile)✓ / .gitignore 受管块完整,本地/云上 md5 一致✓ / 云上 git remote 走 SSH deploy key,URL 无 token✓ / 无云厂商之外的凭据文件(AWS/rclone/gh/gcloud/azure 全无)✓

## 六、口径说明与局限

- **只诊断未治疗**:7 份报告全程只读(云上零写入、本仓除各报告文件外零提交);本 README 亦只做索引摘抄,所有 P0/P1/P2 建议均为后续动作,与本次体检隔离。
- **各报告观察窗口**:
  - D1:10-03 18:13-18:25 CST(对比基线 09-12 部署基准 / 09-30 磁盘诊断 / 09-12 systemd 配置)
  - D2:最近 7 天(09-26~10-03)+ 上一交易日 09-30;10-01~10-08 国庆休市,休市跳过属正常
  - D3:2026-10-03(判"最近"= 09-20~10-03)
  - D4:2026-09-20 ~ 2026-10-03(迁云后近 14 天)
  - D5:10-03 非交易日当天(主链全 PASS 为当日实测)
  - D6:10-03 实测(含 R2 枚举、本机/云上取回对账、21 天演练日志回看)
  - D7:迁云(09-12)后 + 14 天登录/爆破窗口
- **未执行/未验证项(诚实标注,各报告原文)**:
  - D6 **未做正式 `--all` 全量取回演练**(本次仅单文件实测 + 窗口评估);large-json --all 全量演练、public_fund/stock_daily 恢复演练均未执行
  - D2 **锁拆分(149a)后无交易日样本**:「17:50 主链不再排队」「双段1 并发实测」需 10-08 开市后首个交易日验证;149d §8 云上验证命令未执行(需写权限/交易日)
  - D5 **export-guard L5(pre-upload 备份)10-03 上线后尚无交易日样本**,未观察到 pre-upload 打点;首个交易日增量后需巡检确认
  - D4 **迁云后异源可达性未重测**:8/27 那份 38/38 PASS 是迁云前本机家宽出口证据,出口(阿里云 vs 家宽)不同,结论不可沿用
  - D7 **PURGE_SECRET 轮换未执行**(09-12 用户拍板跳过,现需重新评估/拍板);R2 lifecycle 未实测(S3 API 403,D6 P2-3)
  - **149d timer 错峰未执行**(纯待办,需云上 systemd 写授权)
  - D6 国庆休市精确日:10-05~10-08 休市为数据实证(0 行)+ 惯例推断,首个交易日 10-09 为推测(外部查询受限未获官方链接,见下节不一致)
- **诚实标注已含在各报告**:如 D6 DB 备份 md5 不一致已确证非缺陷(物化方式不同,逻辑数据逐表一致);D2 对锁拆分判定=「代码形态已落地 + 非交易日无竞争样本」,结论覆盖范围有限;D3 降噪后 info/warn 类只进 info_log.jsonl 且无自动消费方(已知代价)。

## 七、待主控裁决的不一致

> 任务约定:发现各报告内部自相矛盾或互相冲突,不自行裁决,原样列出两方说法 + 各自出处。

### 7.1 check_r2_consistency 状态冲突(D3 视为在跑的监控源 vs D5 实证未接线)

- **D3 说法**(视为在跑):D3 §2.1 监控源分层把 `check_r2_consistency` 列入 **M5 数据层**(「check_data_gap checker 1-12(...)、check_s06_freshness、check_r2_consistency」);D3 §8 反证项 #6 称「数据层覆盖面可观:check_data_gap checker 1-12(...)+ check_s06_freshness + check_r2_consistency」。
- **D5 说法**(实证是死的):D5 §6「`check_r2_consistency.py`(§22 三版本一致性审计器...)存在但**全仓无自动调度点**(schedule_monitor.sh 仅注释引用 L157,systemd 无,日志无运行痕迹)」;D5 §0「三站一致性核心校验器是死的」,并列为 **P0-1 未接线**。
- 冲突点:同一脚本,D3 当作在跑的数据层监控源,D5 证明其从未被调度。影响:P0-1(是否补接线)的处理优先级与 D3 反证项 #6 的可信度。需主控裁决(倾向 D5 结论,但不在本 README 裁决)。

### 7.2 A 股开市日表述冲突(10-08 vs 10-09)

- **D1/D2/D4 说法**:10-08 开市——D1「A 股 10-08 开市」;D2「10-08 开市后首个交易日验证(149a)」、P1-b「开市前(10-08 前)处理」;D4「A 股 10-08 开市」、P1-1「10-08 开市前必须清掉」。
- **D6 说法**:D6 §7「数据实证(云上 sentiment.db index_daily 逐日行数):10-01/02=4 行、10-03/05/06/07/08=0 行……首个可能交易日 **10-09 周五**,精确以交易所公告为准,外部查询受限未获官方链接」。
- 冲突点:D6 与其余 3 份报告对"下一个交易日"的时点表述相差 1 天。影响:D4 P1-1(回填)与 D2 锁拆分验证等"开市前必须完成"项的时点口径。需主控/用户确认 2026 国庆实际开市日。

## 八、疑似笔误(照抄原文,未动正文)

- **D7 §复现段**:`D7-security-audit.md` 第 167 行与第 168 行连续出现两个 `# 复现段` 标题(重复标题,正文内容紧随其后正常)。按任务约定不动原文,仅在此列示。
