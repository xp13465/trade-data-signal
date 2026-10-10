# 2026-10-09 两个真故障:根因定位与修法设计(只读调研)

- 调研日期:2026-10-09(云上时区 CST);调研人:researcher agent(**全程只读**:未改代码、未跑业务脚本、未做任何外发、未做任何 git 操作;探针 static-only)
- 任务:①故障 A(01:12 R2 上传通道 etf-hist 卡死)②故障 B(09:31 东财接口被拒/伪跳空校验失败)的根因定位 + 治本修法设计
- 数据源:云上 `~/code/trade-data/data/logs/*`(逐文件 tail)、双树 `data/notify_dedup.json` / `data/alerts/latest.md`、本地代码逐行核读
- 落档说明:按任务约束,本次调研未做任何 git 操作(本文件未 commit;是否落档提交由主控处理)
- 前置报告(已落档,本文引用其行级证据):`docs/ops/etf-hist-forcefull-stall-rootcause-20261009.md`(A 定因)、`docs/ops/etf-hist-lock-visibility-mitigation-20261009.md`(#239 止血)、`docs/ops/alert-triage-1009-20261009.md`(告警定性)、`docs/ops/149-lock-split-implementation-20261001.md`(#149 先例)

## 结论速览

| 故障 | 一句话最优修法 | 最大风险 |
|---|---|---|
| A(R2 etf-hist 卡死) | 「等待者判据停滞化 + 长持锁者分片 + 备份防双起」三层:4 个 run_to 调用点由"总时长 900s 硬杀"改为"tmp_log 停滞判据(与 #239 心跳兼容)不误杀排队者";staticdata large-json 上传(单会话持锁 1155s 传 4322 文件)改分片持锁;staticdata 备份加全局单实例锁防 00:22 双起(002224+002239 并存实证) | 停滞判据改造过松→真卡死不再被杀(必须保留 7200s 硬兜底);分片改造引入并发写 R2 竞态需对账兜底 |
| B(东财被拒/伪跳空失败) | 「兜底链修断 + 全 missing 兜底 + 三层告警收敛」:腾讯时间戳缺失时降级新浪(不是直接 raise)+ 主源成功但个别标的缺价时对全部 missing 启用新浪/腾讯单标的兜底(不只 16 前缀);告警按"py/sh 统一 dedup key + notify.py REPO 双树分裂修复 + monitor 豁免"收敛为 1 条 | notify.py REPO 切到运行树时旧 dedup 状态(在 signal 树)窗口内迁移空窗,可能重发一次历史 key;兜底触发面扩大后若兜底链自身质量差会掩盖主源问题(需兜底链先加固) |

---

# 故障 A:01:12 R2 上传通道 etf-hist 卡死

## A0. 完整事实链(全部行级实证)

1. **00:22:08** `r2-upload-002208` 实例启动(15 数据通道,`r2_upload_async_20261009_002208.log` L1"=== r2_upload_async 开始 2026-10-09 00:22:08 ===");etf-hist 是其一个通道。
2. **00:22:24** `staticdata_backup_async_20261009_002224.log` 启动(`trigger=etf-national-team`,即 etf_national_team 链触发 staticdata 备份);**00:23:39** 另一起 `staticdata_backup_async_20261009_002239.log`(backfill 链触发,`backfill_20261009_0007.log` L405-406"-> 触发 staticdata 备份(异步, 拆出主链等待区间)... Running as unit: staticdata-backup-002239.service")——**当晚至少两条链各自起了 staticdata 备份(双起,无互斥)**。
3. **00:22:50~00:42:05** 002224 的 `[step3.5b large-json R2 上传]` 段执行:**单会话批量上传 4322 个文件**(全集 31673/跳过 27351,含 108.3s 纯本地指纹扫描;日志逐文件"✓ ... -> signal-backup2/large-json/...gz"),段耗时 **1155s**(日志"`[step3.5 large-json 排除+R2] 1155s`"),00:42:05 才进入下一段(锁内 git)。**此期间持有 R2 上传锁**(上传经 upload_r2.py 的统一锁;**与 etf-hist 排队窗口 00:22:5x~00:37:5x 完全重叠**)。
4. **00:22:5x** etf-hist 通道子进程在 `_acquire_r2_upload_lock` 排队(2s 轮询 sleep;**故障当夜 #239 排队心跳尚未上线**→排队期间无任何输出)→ tmp_log mtime 停滞。
5. **00:37:5x** `⚠ upload-etf-hist 停滞 900s 无日志输出, kill pid=1928109`(002208.log L8);kill 前 tmp_log 尾部 30 行="(tmp_log 无任何输出——进程启动即无日志/缓冲未刷)"(L10,即排队静默,不是上传中卡死;**PUT 零执行、marker 无残留**)。
6. **00:42:05/00:42:23** 002224 段2(锁内 git)+完成。
7. **01:12:07** finalize_verify 轻量对账:`✗ R2 失败通道轻量对账发现缺口(verify-channels rc=1, 照常告警): upload-etf-hist`(L25)→ notify 完整链(即 alert-triage 报告表 #2)。
8. **01:13:32** 并发跳过补跑触发二次 finalize_verify 再报同 key → `[notify][dedup] suppress key=deploy_r2_upload_fail last_alerted=2026-10-09 01:12:07 age=85s < window=21600s, 不重发`(尾行)→ 实例退出码 0;verify-r2 自动补传 101 个。

## A① 谁是长持锁者 / 002208 实例是不是它

- **长持锁者 = `staticdata_backup_async` 的 step3.5b large-json 批量上传会话**(002224 实例,00:22:50~00:42:05):**单次 `upload_r2.py upload-large-json` 调用内串行传 4322 个文件、持统一上传锁 ~19 分钟**。锁层级(实读 upload_r2.py L3997-4000):dispatch 豁免名单 = {list, delete, download-db, clean-data-backup, upload(单文件小命令)},**upload-* 家族不在豁免** → large-json 持 `/tmp/trade_r2_upload.lock` 以排队语义上传(与 etf-hist 同一把锁);外层另持 `/tmp/trade_backup_r2.lock`(#149,非阻塞,仅防 staticdata 备份互斥,不参与 etf-hist 竞争)。证据:上节第 2/3 条 + upload_r2.py 锁段行级。
- **002208 实例不是长持锁者,是排队受害者侧**:它是当晚 R2 上传主 runner(15 通道并行),其 etf-hist 通道在锁处排队被停滞判据 kill。**锁竞争跨链发生**(etf_nt 链的 staticdata 备份 vs deploy 链的 r2-upload),不是同实例内部。
- 同类长持锁案例(行级证据见前置 A 定因报告 D 类清单):`upload-fund-nav` 一次 4089.8s(≈68min);`upload-large-json` 白天例 26~105min。**长持锁是常态结构**(staticdata 备份今天起了 5 次:00:22/00:23/00:39/02:17/05:11,每次 step3.5b 都可能长传)。
- 连带受损面:fetch_news 因拿不到 R2 上传锁连续 3 轮 `SKIPPED_LOCKED`(01:45/10:45 两段 SEVERE,11:00 恢复通知;triage #3/#9)。

## A② 900s 超时值谁定、依据在哪

- **停滞判据 900s**:`scripts/r2_upload_async.sh` L120 `_stall_secs="${R2_UPLOAD_STALL_SECS:-900}"`;判据 L139(`_now - _last_mtime >= _stall_secs` → kill)。引入 commit `9faf92d8e`(#174),梯度化(#217② commit `d714be25b`):设计依据=**"看门狗外层必须 > 内层 HTTP 超时(600s)"**,故 900 = 600+300 缓冲(详见 #239 止血报告 §4/§9③)。
- **run_to 900(纯总时长硬杀)**:`scripts/s06_snapshot.sh` L42-55 的 run_to(三平台 timeout 包装);调用点 L133 `run_to 900 upload-data-files kelly_mode_s06_state.json`、L161 `run_to 900 upload-kelly-snapshots`;`scripts/turnover_backfill.sh` L145/148 同。commit `8e9a2555a` 引入,口径与 R2_UPLOAD_STALL 对齐。
- **两种判据的行为差异(本案关键)**:mtime 停滞判据宽容"有持续输出的长任务"、只杀"静默者";run_to 是总时长硬杀,**排队等锁(静默)与真卡死无法区分**。
- **#239 止血的覆盖边界**(已上线,commit `88fecb1d7`):upload_r2.py 排队分支加 30s 心跳(刷新 tmp_log mtime)——**只救 mtime 型 15 通道**;**run_to 型 4 调用点(s06_snapshot L133/161、turnover_backfill L145/148)不受益,仍会被总时长 SIGTERM**;with_lock.py 阻塞等锁静默属同族未改。

## A③ 治本方案(选项 + 各自风险 + 社区调研)

### 方向 1:等待者判据改造(治"误杀",主推)

- **选项 1a(主推)**:4 个 run_to 调用点弃"纯总时长",改 **tmp_log 停滞判据包装**(与 r2_upload_async.sh 同款:无输出 900s 才杀,保留 7200s 硬兜底)。等锁期间 #239 心跳持续刷新 mtime → **不误杀**;真卡死(无输出 900s)→ 照杀。工程:给这 4 处调用配 tmp_log 捕获 + 判据循环(可与 r2_upload_async.sh 抽取共用函数)。
  - 风险:判据比"纯总时长"复杂,包装若有 bug 可能杀不掉(必须保留硬兜底);对"输出刷屏但实际卡住"的任务失效(低速判据兜底,同 r2_upload_async.sh L159-181)。
- **选项 1b**:4 处调用改 `--skip-if-locked`(60s 有界重试窗口,#217① 语义)+ 留痕 + 下一轮重试。
  - 风险:**可能丢数据**——s06 快照类文件若"只此一轮传"则成缺口(依赖下一轮覆盖,需逐调用点论证幂等/覆盖性,比 #149 的 staticdata 备份场景更险);且失败静默需 monitor 可见性配套。**故只适合"每轮都重传全量"的调用点**。
- **选项 1c**:保持 run_to 但加大预算(900→覆盖等锁上界)。
  - 风险:真卡死要等更久才杀(?);且等锁上界(7300s)远大于任何合理执行预算,一刀切加大=粗放。不推荐单独用。

### 方向 2:长持锁者治理(治"排队本身",辅助)

- **选项 2a(主推-分片)**:large-json 批量上传**分片持锁**——把 4322 文件拆成多个 `upload_r2.py` 调用(或进程内加"每 N 文件/每 30-60s 释放-重取锁"逻辑),给等待者让路。实证指向明确:*002224 单次调用内传 4322 文件、单会话持统一锁 1155s(本次事故持锁者)*;fund-nav 类 68min 同款结构。
  - 风险:释放/重取间隙里其他写者插入=上传吞吐下降(可接受);释放点的实现若用 flock 的 unlock/lock,间隙里**公平性无保证**(等待者未必抢到,但给了机会);需要重入逻辑正确(重取后继续,防中断半途)。
- **选项 2b(主推-防双起+错峰)**:staticdata 备份点全局单实例锁(防 002224+002239 这类双起;今晚实证双备份并存)+ 触发源(etf_nt/backfill/deploy)错峰,避免与 r2 数据链高峰重叠。
  - 风险:备份延迟(单实例锁下后到者跳过/排队);错峰需梳理各触发源时点表。
- **选项 2c(独立锁域)**:把 staticdata 备份的上传挪到独立锁。
  - 现状已有一层:`trade_backup_r2.lock`(#149)仅防 staticdata 备份互斥;**统一上传锁 `trade_r2_upload.lock` 必然共用**——它就是 upload_r2.py 上传器入口锁,取消/绕开=回到 9-23 三路并发抢带宽事故(upload_r2.py L3866-3876 注释)。风险:large-json 与数据链同 R2 桶、同上传器,再拆锁=并发写同一 R2 命名空间 + 验证/对账语义拆分成本高——**不建议**(问题不在锁分域,在持锁时长)。

### 方向 3:排队公平性(等待者优先 vs FCFS vs 跳过)

- **社区/机制结论**:`flock`/`fcntl` **无 FIFO 公平性保证**(内核实现不排队,释放瞬间竞争者重抢);业界公平队列做法=**显式队列**(pipe token / ticket lock / 中央调度器),或每等待者独立队列文件轮询。lock convoy(长链排队)是公认反模式,缓解手段首选=**缩短持锁时间(分片)+ 让等待者可见/可放弃**。
- 对本案:**"等待者优先"在 flock 层不可控**;务实=有界等待+心跳可见(#239 半成品)+ 分片让路(2a)+ 错峰减少并发需求(2b)。**不建议在单机 flock 上自建 ticket 队列**(复杂、脆弱、收益低)。
- systemd 服务互斥:**systemd 无内置互斥**,业界通例=flock CLI(`/usr/bin/flock`)/应用层锁+超时;本项目的 systemd-run transient unit(r2-upload-*)与文件锁已是这个模式,方向正确,缺的是"等待者处置"。

### A 打包推荐

**1a(判据停滞化,治误杀)+ 2a(分片持锁,缩减长锁)+ 2b(备份防双起/错峰,减少撞发)** 三层组合;1b 仅在论证"该调用点可安全跳过"后用于低价值通道;3 不单独实施。

## A④ "重发被 dedup suppress"的副作用

- **机制**:notify.py `check_dedup`(L1247-1279):窗口内 suppress 时**打印 suppress 行并 return(不发送、不写 latest.md)**;`update_dedup`(L1281+)仅在发送成功后更新(flock 串行化)。suppress 时**调用方日志之外无任何留痕**(不镜像 severe-mirror,见 L1205+ 镜像仅在 send 路径)。
- **10-09 实例**:01:13:32 的二次 finalize_verify(并发跳过补跑,同事件)被 suppress(age=85s < window=21600s)——**这是正确行为**(防同事件重发),当晚另有 verify-r2 补传兜底,**无实际损失**。
- **副作用(任务第四问的正面回答)**:**6h 窗口(此处 21600s)内,同 key 的"新独立真故障"会被完全静默**——不发送、不进 latest.md、无计数,用户零感知;只有发起方本地日志里一行 suppress。即"dedup 会把真故障也吞掉"——**成立,只是本案窗口内没发生**。
- **修法**:suppress 分支**至少留痕**——推荐 latest.md 同条目追加"(本窗口内重复触发 N 次)"计数(同 key 覆盖更新,不增条数防刷屏);或退一步:suppress 时写一行到 `data/alerts/` 的 info 流。**风险**:留痕若做成"每条都追加"会刷屏,必须节流(按 key 覆盖式计数)。

---

# 故障 B:09:31 东财接口被拒(伪跳空校验失败)

## B0. 完整事实链

1. **09:26** `nextday_gap_check.sh`(systemd `trade-nextday-gap-check`,ExecStart=运行树逻辑路径)启动;py 首拉开盘价:
   - 主源 `ak.fund_etf_spot_em()`(东财 push2,无参数)→ **ConnectionError(RemoteDisconnected)**;
   - 走全量兜底 `_fetch_intraday_open_via_http` → **腾讯对 159970 时间戳缺失 → 直接 raise("腾讯行情 ... 当日性无法确认"),不试新浪** → 整链 RuntimeError(`nextday_gap_check_launchd.log` 09:26 轮"第 1 次拉开盘价失败: akshare fund_etf_spot_em 拉取失败: ConnectionError: ('Connection aborted.', RemoteDisconn...)")。
2. 等 300s;09:31 重试:**主源未爆 ConnectionError 但仍取不到** → 抛"akshare 未返回任何目标 ETF/LOF 的真实开盘价(数据就绪闸 FAIL)"(signal_kelly_backtest.py L808-809 文本)→ 就绪闸 FAIL。
3. **09:31:37** py 内 `_severe_alert`(L65-77,key=`nextday_gap_check_gen_fail`)→ **真实外发 email+feishu**(第 1 条;实锤:signal 树 `data/notify_dedup.json` 有该 key `2026-10-09 09:31:37` + signal 树 `data/alerts/latest.md` L365 流水条目)。
4. **09:31:43** sh 外壳 rc=2 → notify(key=`nextday_gap_check_fail`)→ **真实外发**(第 2 条;运行树 dedup `2026-10-09 09:31:43` + 运行树 latest.md L337)。
5. **09:45:12** schedule_monitor 聚合告警「[cloud] 2项计划任务异常」(一条消息含 **2 段**:exit=2 段 + log 关键词段)→ **真实外发**(第 3 条;schedule_monitor_launchd.log L16224-16229 发送行、L16240-16242 内容;alert_state 两 key 09:45 落签)。
6. **10:00+** 轮次起,两 key 均 suppress(exit="退出失败持续中";关键词="异常持续中")。

**用户实际收到 3 条同一事实的消息**(09:31:37 / 09:31:43 / 09:45:12)。**triage 报告(alert-triage-1009)只记了 2 条(#6/#7)——它漏了 09:31:37 那条**,原因是其以**运行树** latest.md 为权威,**py 的条目落在 signal 树**(双树分裂,见下文 C 节)。本文修正此计数。

## B① 调用点精确定位

| 层 | 位置 | 内容 |
|---|---|---|
| 入口 | `scripts/nextday_gap_check.sh` L55-62 | `"$PY" scripts/nextday_gap_check.py`(cwd=$REPO) |
| 编排 | `scripts/nextday_gap_check.py` L165-191 | 就绪闸+重试(attempt1 → `time.sleep(300)` L190-191 → attempt2;`DEFAULT_RETRY_WAIT=300` L58) |
| 取数 | `scripts/nextday_gap_check.py` L104-120 | `return _fetch_intraday_open_prices(codes, expect_date=expect_date)`(复用回测同函数) |
| **主源** | `scripts/signal_kelly_backtest.py` **L772** | `df = ak.fund_etf_spot_em()`(**东财 push2 全市场 ETF 现货快照,无参数**) |
| 兜底 | `signal_kelly_backtest.py` L778-783 / **L813** | 主源异常 → `_fetch_intraday_open_via_http`(**腾讯 qt.gtimg.cn 主 → 新浪 hq.sinajs.cn 备**的直连 HTTP) |
| 主源成功分支 | L792-796、L804-807 | 空/缺列/日期校验(F4,`_verify_spot_data_date` L708)直接 raise;**missing 仅 16 前缀 LOF 补兜底** |
| 终检 | L808-809 | `if not out: raise`(本案例 09:31 轮的抛出点) |
| 告警 | py L195-201(`_severe_alert`)/ sh L62-69 | 两条不同 dedup key(gen_fail / fail) |

## B② 被拒的性质(限流/WAF/临时故障)

- **定性:东方财富 push2 家族的反爬/风控拦截,非本机网络故障、非纯临时超时。**
- 证据:①异常形态 `ConnectionError: ('Connection aborted.', RemoteDisconnected...)`=TCP 被对端断开(风控特征,非连接超时);②**同晨全站同源失败**:deploy 链日志同见"⚠ [etf-fallback] 东财主源 fund_etf_spot_em() 失败(ConnectionError...)"(多条 deploy/backfill 日志),即**跨任务、跨脚本**的同一源被拒;③**15:35 复测**:东财 push2 clist 接口 http=000(**长时段不可达**),同刻腾讯/新浪对 159970 正常(今开 0.919,字段完好)——**排除"数据源无数据",锁定"东财侧拒绝"**;④**9:26 首拉失败是连续 3 个交易日的常态**(9-29/10-08 同模式,9:31 重试才成功)——**时段性**:集合竞价后(9:25-9:26)东财请求高峰易被限。
- 社区(前期已查,结论沿用):东财 push2 系(含 fund_etf_spot_em 家族)对高频/非常规请求有风控,`RemoteDisconnected` 是典型信号;恢复期分钟级到 1-2 天;缓解=限频、指数退避、错峰、换源。9-23 本项目已有同源事故先例(注释存档:signal_kelly_backtest.py L775-777"2026-09-23 东财 push2 家族封禁(HTTP 000, 连续 6h+, 本机+云上双地实测)")。

## B③ 现有兜底源与缺口

- 已有(可用):①`_fetch_intraday_open_via_http`(腾讯→新浪单标的直连,带当日性校验);②`_etf_spot_fallback.fund_etf_spot_df()`(东财→新浪 Market_Center→腾讯全称,2053 只;**无开盘价列,不可用于 gap_check,但可参考其多源实现**);③memory 线索:index-backfill(baostock→腾讯)、industry 切换、intraday multisource(新浪主+腾讯备)——**全站已有多个"异源兜底范式",gap_check 链路是其中较弱的一环**。
- **缺口(10-09 实踩,均已行级定位)**:
  - **缺口 1:腾讯失败不降级新浪**——`_fetch_intraday_open_via_http` 中腾讯时间戳缺失/非当日 → `raise RuntimeError("腾讯行情 {code} 时间戳...当日性无法确认")(L854 附近)`,**该 raise 直接终止兜底链,新浪分支不可达**。10-09 晨 159970 即死在此(单标的拖垮全链)。
  - **缺口 2:主源"成功但个别标的缺价"不兜底**——L804-807 仅对 missing 中的 16 前缀 LOF 补兜底,注释明言"主源成功时行为零变化, 15 前缀主源已覆盖"(**刻意设计**,假设=主源成功则 15 前缀必覆盖)。该假设在"标的缺价/不在返回/开盘价无效"时破裂(09:31 轮 out 空的直接土壤)。
  - **缺口 3:空/缺列/日期陈旧路径不走兜底**——L792-796 直接 raise(df 空、缺列、日期陈旧[F4])。其中"日期陈旧"恰恰可能是"此时点东财给了昨日快照"——**兜底(新浪/腾讯实时)反而更新鲜**,却不走。

## B④ 修法设计(重试 + 兜底 + 告警合并)

### B4-1 兜底链修复(核心,先做)

- (i) `_fetch_intraday_open_via_http`:**腾讯失败(含时间戳缺失)→ 降级新浪**(新浪自带日期字段做当日性锚);**逐标的独立**(单标的失败记 missing,不拖累其他标的)。
- (ii) `_fetch_intraday_open_prices`:主源成功但部分 target 缺有效开盘价 → **对全部 missing(不只 16 前缀)启用单标的 HTTP 兜底**;日期陈旧路径也并入兜底优先(兜底拿即时行情,比陈旧快照强)。
- **行为变化标注**:修改后"原本被记'伪跳空校验未完成(待人工)'的标的"可能被兜底救回——**这是失败率改善,不是口径变化**(拿到的仍是真实当日开盘价);按 §5.4⑥,不动测试基准,是否发 patch 版本注记由用户拍板。

### B4-2 重试策略

- 现状:9:26 首拉失败 → 等 300s → 9:31 重试一次(即**经典单次长退避**,而 9:26 是东财时段性高峰——300s 后 9:31 仍在高峰边缘)。
- 建议:**短间隔指数退避多轮**(30s/60s/120s,总预算 ≤ 15min,带 jitter),或 60s×3;配合修复后的兜底链,主源失败第一轮就由兜底接管,重试的意义退为"兜底也失败时的二次窗口"。
- 风险:重试轮数增=告警延迟(最长 ~15min);9:26-9:45 窗口内下游(次日买入计划)可容忍(09:45 monitor 轮次自然对齐)。**推荐档**:兜底修复 + 60s×3 退避;保守档:只修兜底、保留现 300s 单次。
- **[后续定案 2026-10-10 #246 R1 审查]**:预算口径由上文「总预算 ≤15min」**降为硬顶 450s**(`RETRY_BUDGET_S=450`)。理由:实测云上本链外层 `TimeoutStartSec=600`(`KillMode=control-group`),预算设 900 会「超墙被 cgroup 静默硬杀 + 预算成死代码」;450 落在墙内留 150s 梯度给拉数/R2/通知,而默认 60×3 jitter 后仅 135~225s 远不触顶。上文原值保留为时点记录即可,实施以 450 为准。

### B4-3 告警三层收敛(同一事实 3 条 → 1 条)

| 层 | 现状 | 修法 |
|---|---|---|
| L1 双树分裂(**P0 根因,见 C 节**) | py 告警写 **signal 树** dedup/latest.md;sh 告警写**运行树**——互不可见,suppress 判定/对账全布朗运动 | `notify.py` L86 改 `REPO = Path(os.environ.get("REPO") or Path(__file__).absolute().parent.parent)`(**与本文件内 L2227/2267/2317 已存在的"env REPO 优先"局部先例、与 nextday_gap_check.py L43-45 头部"显式 REPO 优先"全司同款**) |
| L2 py/sh 双发 | 两条不同 dedup key(gen_fail / fail),sh 注释自认"包装层兜底重复告警(不同 dedup key 不互吞)" | **统一 key**(推荐 `nextday_gap_check_fail`:py 改 `--dedup-key`,sh 不变)——py 先发后 sh 6s 内被 suppress;py 崩时 sh 照发(兜底语义完整保留) |
| L3 monitor 聚合 | exit 段 + 关键词段**同轮双段**;且与任务自身告警重复 | ①关键词段加"exit!=0 时跳过"(其设计意图本就是"**exit=0 被吞异常**"的盲区兜底,L731-732 注释原文);②exit 段加**现成模板**豁免:`wrapper_channel_alerted(REPO, last_run_str, "nextday_gap_check_fail")` 判 True → `[r8-nextday-gap-suppress]`(复刻 r7/196 先例,schedule_monitor.sh L668-706;判定=notify_dedup.last_alerted >= 本次 last_run;**反例保证**:自身通道没发→判定 False→monitor 照发,双保险不吞真故障) |

- **净效果**:正常失败=1 条(py 详细版,含日志路径);py 崩=sh 兜底 1 条;py+sh 都崩=monitor 兜底 1 条。**三层兜底链完整保留,只去掉重复段**。
- 兼容提示:notify.py REPO 修复后,signal 树那份 dedup/latest.md 的历史记录不再更新(留存即可);修复瞬间"运行树 dedup 缺 gen_fail 历史"→ **窗口内(≤6h)若同 key 重发会补发一次**(低危;可配套把 signal 树 dedup 的 last_alerted 合并进运行树)。

### B4-4(可选)9:26 时点专项

东财在 9:26 时段性被拒(连续 3 日常态)——可评估"gap_check 场景新浪优先"(它只需今开+日期,不需东财全字段),或维持"东财优先+兜底接管"。**待兜底链修复后以数据观测决定,不预断**。

## B⑤ 举一反三:同类"单一外部源 + 无兜底 + 无重试"清单

口径:对 akshare 调用文件做三维粗筛(ak 调用数 / 兜底词 / 重试词),高危项已人工核读;**未逐行深挖,标注为粗筛**。

| 文件 | akshare 调用 | 兜底 | 重试 | 定性 |
|---|---|---|---|---|
| `scripts/lhb_history_backfill.py` | 2(stock_lhb_detail_em / jgmmtj_em,L47/L70) | **无** | **无**(L107/111 except 仅 print 继续 + 0.5s 节流) | **单源+无兜底+无重试(高危)** |
| `app/collector/industry_extras.py` | 2(同花顺 stock_board_industry_index_ths / summary_ths,L208/L357) | **无** | **无**(except continue 逐行业) | **单源+无兜底+无重试(高危)** |
| `app/backfill.py` | 4(zt_pool 系,L48-51) | **无** | 有(`safe_call` base.py L162,retries=2,连接类 2-5s×(i+1) 退避) | 单源+无兜底+有重试 |
| `app/calendar.py` | 1(tool_trade_date_hist_sina) | 有降级(akshare 缺→周末启发式,L8) | 双路调用(L21/L43) | 单源+有降级(低危) |
| `app/collector/stock_daily.py` / `width_history.py` / `scripts/fetch_lof_track_index.py` / `scripts/gen_etf_index_map.py` | 1~2 | 词频有(3~10) | 少 | 待细挖(中危) |
| `app/collector/public_fund.py` | **22** | 8 | 7 | 调用面最大,兜底密度低(待细挖) |
| `app/collector/overlap_fetcher.py` | 13 | 3 | 4 | 同上 |
| **正例(已是异源兜底范式,可复用)** | | | | `_etf_spot_fallback.py`(东财→新浪→腾讯)、`intraday_snapshot.py`、`index_backfill.py`、`fetchers.py`、`direct.py`、`etf_national_team.py`、`us_stock_morning.py` |
| 本次故障链(已入修法) | `signal_kelly_backtest._fetch_intraday_open_prices`(主源+兜底有,**链断在细节**) | | | B4-1 |

---

# C. 新发现(P0,横跨 A/B):双树 dedup/latest.md 分裂根因

- **现象**:云上 `~/code/trade-data/data/`(运行树)与 `~/code/trade-data-signal/data/`(代码树)各有一份 `notify_dedup.json` 与 `alerts/latest.md`,**同日晚间各写各的**:
  - 运行树:sh 外壳 key `nextday_gap_check_fail` 09:31:43;signal 树:py key `nextday_gap_check_gen_fail` 09:31:37。signal 树还独有 `nextday_plan_*` 系列(9-30/10-08)——**nextday_plan 同病**(9-30 22:35:08 vs 22:35:19 两条同构双写)。
- **根因(链已闭合)**:
  1. 云上 `~/code/trade-data/scripts` 是 **symlink** → `~/code/trade-data-signal/scripts`(ls 实证;app/config/web/.venv 同型);
  2. sh 外壳:`cd "$REPO"`(逻辑路径)+ `"$PY" scripts/notify.py` 相对路径 → notify.py `__file__` 相对 → **`Path.absolute()`(不解析 symlink)** → REPO=**运行树** ✓;
  3. py:`SCRIPT_DIR = Path(__file__).resolve()`(**`resolve()` 解析 symlink**)→ 传 subprocess 的 notify.py 为**物理路径**(signal 树)→ notify.py `absolute()` 得物理路径 → REPO=**signal 树** ✗;
  4. notify.py L86 自身**不吃 REPO 环境变量**(而 unit 已正确设 `Environment=REPO=/home/ubuntu/code/trade-data`;同文件 L2227/2267/2317 局部函数却用了 env 优先——**半修先例**)。
- **影响面**:凡是"py 内调 notify 子进程"的链路(现已知 nextday_gap_check.py L65-77 + nextday_plan_generator.py〔同 `_severe_alert` 先例,SCRIPT_DIR 同款 resolve L74〕)在云上全部写入 signal 树——**dedup 抑制判定、latest.md 稽核、monitor 汇总去重(其读运行树!)对这批告警全部失明**(B4-3 的 L3 豁免判定也依赖运行树 dedup,不修此分裂则该豁免对 py 告警无效)。
- **修法即 B4-3 L1**(notify.py L86 一行);**同类面**:`_severe_alert` 先例仅 2 个脚本(已列),但**任何 resolve 后传路径给子进程的调用都潜在同病**——修复 L86 后单个调用者无需改(py 传物理路径也无碍,notify.py 以 env 为准)。

---

# D. 诚实标注(§5.1④)

- **triage 报告修正**:09:31:37 一条(py)未被其记录(实为 3 条同事实消息);其 §2 R3"自身+聚合两条"应更正为"自身两条(py/sh 双 key)+ 聚合一条"。
- **未 100% 钉死**:①B 的 09:31 轮"主源未爆异常但 out 空"的精确形态(主源 df 是否 isin 零命中 / 开盘价无效两候选路径)——两种形态修法相同(全 missing 兜底),未再深挖;②00:22 段 002224/002239 双备份并存是否互相排队(未细读 002239 全文);③"持锁 1155s"的精确切分(108.3s 指纹扫描是否在持锁窗口内未细分);④10:45 段 fetch_news 被跳过的当持锁方未定位(triage 已标同款,本文未追加)。
- **口径说明**:A 的"1155s"= `staticdata_backup_async_20261009_002224.log` step3.5 段耗时(持锁窗口直接锚,来源=该日志原文);B 的告警条数=email+feishu 实发(三处 dedup/latest.md/日志三源交叉)。
- **未测项**:一切生产脚本未跑;东财风控恢复期未跟踪(15:35 仍不可达);社区调研受搜索通道泛化限制,部分结论依托既有落档(#239 报告/9-23 先例注释)。
- **涉及行为变化的修法(B4-1 全 missing 兜底、B4-3 统一 key)**:属失败路径加固,正常路径不变;按 §23.7/§5.4⑥ 是否发版本注记、由用户拍板。

# E. 关键证据与复现命令(只读)

```bash
# A:长持锁者(step3.5 段 1155s / 4322 文件)
cat ~/code/trade-data/data/logs/staticdata_backup_async_20261009_002224.log | grep -n "step3.5\|待传\|1155s"
# A:etf-hist 被 kill
sed -n '1,12p' ~/code/trade-data/data/logs/r2_upload_async_20261009_002208.log
# A:双备份并存
grep -n "staticdata 备份" ~/code/trade-data/data/logs/backfill_20261009_0007.log
# B:三源交叉(双树)
python3 -c "import json;d=json.load(open('/home/ubuntu/code/trade-data-signal/data/notify_dedup.json'));print(d.get('nextday_gap_check_gen_fail'))"
python3 -c "import json;d=json.load(open('/home/ubuntu/code/trade-data/data/notify_dedup.json'));print(d.get('nextday_gap_check_fail'))"
sed -n '16224,16249p' ~/code/trade-data/data/logs/schedule_monitor_launchd.log
# B:9:26/9:31 两轮失败原文
grep -n "第 1 次\|第 2 次\|就绪闸" ~/code/trade-data/data/logs/nextday_gap_check_launchd.log | tail -8
# C:symlink 结构
ls -ld /home/ubuntu/code/trade-data/scripts /home/ubuntu/code/trade-data-signal/scripts
```
