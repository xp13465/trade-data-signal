# #219 根因报告:verify-r2 每轮固定补传 34~36 个(kelly parts 17+17 家族)

> 日期:2026-10-06 | 角色:researcher | 类型:只读取证(未写 R2、未跑任何上传器/业务脚本主体)
> 关联:#219(pending-index)、#218(R2 上传链族 B)、#196、`docs/ops/alert-triage-3d-20261006.md` §2.2/§6
> 方法:读码(upload_r2.py / export.py / signal_kelly_backtest.py / lab.js / app.js)+ 云上只读取证(state/文件/日志)+ 独立指纹实验

## 1. 定性结论(先给答案)

**判定 = 甲(噪音)+ 丙(口径错位),不是乙(真缺口)。**

- 34~36 个补传 = **「两级指纹判定口径结构性错位」× 「parts 元数据字段每轮被 export 重写」的必然产物**,不是上传失败、不是 R2 对象丢失。
- (2026-10-06 21:16 轮追加实证)失败轮会在此基数上**叠加真兜底**:该轮 49 = 34(设计内代差)+ 15(真兜底:all-data 通道超时失败未传完 + news_digest/schedule_stats 独立链滞后的文件)→ 同一清单内**混着"设计内噪音"与"真缺口兜底"两类**,这是"必须分类降噪、绝不可整类豁免"的当日鲜活证据(详见 §4.3)。
- 机制一句话:**上传链按"B 档结构化指纹"(剔除 generated_at/period_cutoffs/buy_amount)判"内容没变→跳过不传";而 verify-r2 按"整文件 md5"对账;而这三个被剔除字段每轮 export 都被重写 ⇒ 每轮 verify 必然全量"对不上"(34 个)→ 每轮补传整文件。**
- 对线上数据本体影响 = **零**:B 档指纹(即"剔除三字段后的数据本体")跨轮稳定(实证 state 指纹 == 本地重算 B 档指纹);R2 上的对象是上一轮补传的整文件,其数据本体与当前本地一致。补传甚至把 R2 刷新到最新版(比"上传链跳过"的语义上更"新鲜"),补传 rc=0 全成功。
- 次生判定:`schedule_stats.json` 偶发 +1(35/36 元)= **不是噪音**,是 #188「独立链产物平日对账」机制的正常工作(它由 intraday 链更新,见 §4.2)。

## 2. 机制链(五环,逐环带证据)

### 环 1:kelly parts 每轮被 export 重生成,元数据字段每轮变

- parts 生产者:`scripts/signal_kelly_backtest.py` 的 `_export_trades_parts`(L2148-2267,产出 `recent.json` + `t2011.json`..`t2026.json` = 17 个/目录);由 `static-site/export.py` L1210-1266 每轮 subprocess 调用(NDO 主档 L1211-1214 + SDC 对比档 L1247-1254),**不受 incremental 跳过**(无 _incremental_skip 守卫)。
- 文件头实证(云上 trade-data 树,2026-10-06 当晚):
  ```json
  {"generated_at":"2026-10-06 17:56","buy_amount":10000,"period_cutoffs":{"y1":"20251006","y3":"20231007","y5":"20211007","y10":"20161008","all":"0"},"fields":[...],...}
  ```
  - `generated_at` = 生成时刻(每轮 export 变);`period_cutoffs.y1/y3/y5/y10` = **滚动日期切点**(y1="一年前的今天",每天变);`buy_amount` 常量。
- mtime 实证:17:56(17:50 update_all 轮)→ 21:12:18/21:12:43(21:05 deploy 轮段1 export 又重写)—— **同日两轮 export = 两代元数据**。
- 目录规模:parts 17 个(88,896,202 B)+ sdc parts 17 个(90,273,762 B)。

### 环 2:上传链(upload-kelly-parts)按 B 档指纹判"没变"→ 跳过

- `scripts/upload_r2.py` L1017-1036 `_kelly_parts_md5`:B 档指纹 = 剔除三字段后规范化序列化 md5;L1815-1816/L1831-1832 通道绑定该指纹。
- 增量引擎 L1281-1285:`md5 = fingerprint(p)`(B 档);与 state 比对,相同 → 不进 changed;L1324-1335 全未变 → 写 state(changed=[]) 直接返回,**零 PUT**。
- 云上实证(2026-10-06):
  - `.r2_kelly_parts_state.json`:`"changed": []`,count=17,updated_at 18:12,mode/version 完整(上传链跑过且判定零待传)。
  - **独立指纹实验**(云上 python 独立小脚本,未 import 业务模块):
    | 文件 | 整文件 md5 | B 档指纹(重算) | state 存值 | B档==state | 整文件==state |
    |---|---|---|---|---|---|
    | recent.json | 40344236…7046 | 4f4b5f6e…7bb6 | 4f4b5f6e…7bb6 | **True** | False |
    | t2011.json | 0c7e6d6d…4812 | 92ae0d7c…d9da | 92ae0d7c…d9da | **True** | False |
    | t2026.json | 0ef17ab5…329c | 8c8836c4…e324 | 8c8836c4…e324 | **True** | False |
  ⇒ **上传链视角"内容没变"是自洽的**(B 档指纹稳定);整文件 md5 则每轮都变。

### 环 3:verify-r2 平日对账把 17+17 全部选中

- `cmd_verify_r2`(upload_r2.py L3404-3546):平日 to_check = changed(状态文件)+ 独立链台账 + **全池均匀抽样 100**(L3476-3483)。
- kelly-parts 目录仅 17 个文件 < 100 ⇒ `_uniform_sample`(L3396-3397)m<=n 全收 ⇒ **每轮 17 个全查**;sdc 通道同理 ⇒ 17+17=34 个/轮固定进对账池。

### 环 4:verify 判据 = 整文件 md5 vs 本地(与环 2 口径错位)

- L3493-3510 `_check`:`local_md5 = _file_md5(f)`(**整文件字节 md5**,L1003-1005);`ok = etag.strip('"') == local_md5`。
- R2 上的对象 = 上一轮"某次把最新整文件 PUT 上去"的版本(平日 = 上一轮 verify 自己补的;周日 = 上传链 force_full 传的)。本轮 export 已重写元数据 ⇒ **整文件 md5 必然不等 ⇒ 34 个全 mismatch**。
- R2 单 PUT 的 ETag=内容 md5 的前提在设计文档 §3.4 有(kelly parts 各文件 0.2~19MB,均 < MULTIPART 100MB 阈值 ⇒ 单 PUT)⇒ 判据本身有效,错的只是"两边指的不是同一把尺子"(设计文档 L154 已声明"口径分离不冲突"——**未预见"元数据每轮变 ⇒ 平日每轮必然全量不符"**)。

### 环 5:补传 = 整文件直传(无跳过),成功 rc=0,下一轮循环

- L3539-3544:`_upload_glob(..., only_files=mismatches, verify_etag=True)`;only_files 路径 L908-910 **直接 PUT,不再判指纹**;PUT 后 ETag 对账通过 → ok=total。
- 于是 R2 被刷新为本轮最新整文件;**下一轮 export 再重写元数据 → 再 34 个** ⇒ 自锁循环,除非三字段不再每轮变或口径统一。

## 3. 时间序列证据(轮次级,云上日志)

| 日期 | 轮 | 补传数 | 备注 |
|---|---|---|---|
| 10-03 | 02:05/05:00/09:16/15:34/16:40/17:50/21:05 | 35/34/38/34/36/35/34 | deploy 链内 verify(当时 async 未上线) |
| 10-04(周日) | 02:05 | **114** | 周日全量对账(全通道全 key) |
| 10-04 | 05:00 / 17:50 | **0 / 0** | **关键反证**:周日上传链(weekday==6 force_full)真传最新整文件后,verify 复查 0 个 ⇒ 判据链在"R2==本地"时正常工作 |
| 10-04 | 16:40 / 21:05 / 22:30 | 8 / 34 / 1 | 周日非必然 0(与上传链/verify 时序竞态有关,不作强归因) |
| 10-05 | 02:16/05:10/12:25/21:16 | 35/34/36/34 | (16:51 轮 verify 被看门狗 kill 无完成行) |
| 10-06 | 02:16/05:10/18:00 | 34/34/35 | (16:52 轮 kill) |
| 10-06 | 21:16(21:05 deploy 轮) | **49** | =34(设计内)+15(真兜底,见 §4.3) |

- 10-06 轮清单实证(#188 已落文件名):
  - 02:16 轮 34 = `signal_kelly_trades_parts/*` 17 个 + `signal_kelly_trades_sdc_parts/*` 17 个(全名单,非抽样);
  - 18:00 轮 35 = 上述 34 + `data/schedule_stats.json`;
  - 命中清单逐轮与"该通道全部文件"精确重合 ⇒ 不是"随机缺口",是"全池代差"。
- 与"每轮 export 重写"对账:10-06 02:05/05:00/16:41/17:50/21:05 每轮 deploy 段1 都跑 export.py(日志见 `deploy_20261006_*.log` 段1 头),parts mtime 随轮推进(17:56→21:12)⇒ 每轮 verify 面对的必然是"元数据新代"。

## 4. 影响面评估

### 4.1 真实代价(为什么要降)

- **带宽**:34 个 ≈ 179MB/轮(88.9MB+90.3MB);按 deploy 时点 5~7 轮/天 ≈ **0.9~1.2GB/天**跨境上传。这是本现象最主要代价。
- **判别维度稀释(关键)**:verify-r2 的"发现 N 个不一致"行被 34 常驻底噪占据;真缺口(如某对象 404/被覆盖)混在同一清单里,运维无法从"34/35/36"里一眼区分"设计内"与"要修的"。9-23 事故(「kelly-parts/sdc-parts 共 27 个 R2 缺口,--dry-run 显示待传 0」,upload_r2.py L1229-1234 注释)恰恰说明该对账网是真兜底,**不能整类豁免**。
- **mass_mismatch 阈值(>50)**:34 常驻使总数基线抬高(10-04 周日 114 触发),属"更易触发",未构成掩盖;但"噪音+故障混流"的排查成本实存。

### 4.2 schedule_stats.json(+1,偶发)——**不是噪音,勿降**

- 它由 `cmd_upload_intraday`(upload_r2.py L2122-2148)上传(每 10 分钟 intraday 链),并在 L2148 `_record_standalone_keys` 登记进台账(云上 `.r2_standalone_keys.json` 35 项含 `data/schedule_stats.json`)。
- 台账内的对象被 verify-r2 平日无条件纳入对账(L3466-3488)→ 若"生成后最后一条 intraday 轮未跟上"(如 17:50 update_all 又重生成而 intraday 链已收工),verify 补传 + 走 `standalone_stale` 链(L3580-3598)——10-06 18:19:38 首冒的 standalone_stale 即此(18:00 轮清单含它)。**属 #188 机制按设计工作**;其文案(「排期上传链如 s06/nextday_plan」)与实际来源(intraday 链)→ 文案建议扩写(alert-triage §5.3 已提,维持)。

### 4.3 当日晚间实证:49 轮 = 34 噪音 + 15 真兜底(两类混流)

- 2026-10-06 21:05 deploy 轮(段1 export 21:11-21:12 重写 parts/统计件)→ 21:16:36 async → **verify-r2 补传 49 个**(21:45:44 收尾 rc=0):
  - 34 个 = kelly parts/sdc parts 全名单(设计内代差,§2);
  - 15 个 = `etf_national_team-1m/1y/6m/holders/quarterly`(5)+ `export_manifest` + `global-3m/1y` + `news_digest.json` + `news_digest/2026/2026-10-06.json` + `news_digest/_index.json` + `schedule_stats.json` + `signal_stats.json` + `signal_kelly_backtest.json` + `signal_kelly_backtest_sdc.json`。
- 本轮同期事实:`⚠ upload-all-data 失败/超时,继续`(该通道未把 export 新文件传完);news_digest 家族=fetch_news 链当日曾 SKIPPED_LOCKED(alert-triage §2.1),schedule_stats=intraday 链收盘后停跑 → **这 15 个多为"真滞后被 verify 兜上"**(与 9-23 事故 27 个缺口的兜底机制同源)。
- 结论:即便在"每轮固定 34 底噪"已成常态的当下,**verify 的补传网仍在承担真兜底职能** ⇒ 任何降噪方案只能"分类",不能"关闸/豁免整类"。

## 5. 降噪方案(保留真判别维度;按"是否动物产物"分叉)

### P1(治本,推荐):parts 元数据三字段稳定化/撤出,让两把尺子合流

- **依据**:三字段前端零消费——复核过:`_simParseTrades`(app.js L3775-3779)/`_labKellyParseTrades`(lab.js L8699-8703)只取 `fields`/`quadrants`/`fIdx`;lab.js 全部 `period_cutoffs`/`buy_amount` 消费点(L8970-8971/L10646/L12958-12960/L13112)读的是 `data.config.*` = **signal_kelly_backtest.json 的 config 段**(另一文件,非 parts);`_labKellySetCache` 定义残留无调用。脚本侧 grep(scripts/*.py)`generated_at` 消费均指向其它文件(trades 整档/backtest.json)。设计文档 r2-incremental-upload-design-20260915.md §风险4 亦早有预案("若被消费→降 A 档")。
- **做法(二选一,建议 a)**:a) 三字段从 parts 文件撤出(如需保留可观测性,写 sidecar `*_meta.json` 或并入 backtest.json);b) `generated_at` 改为"数据本体变化才更新"。
- **效果**:文件本体稳定 ⇒ 整文件 md5 = B 档指纹实质对齐 ⇒ 上传链判"没变"(正确)+ verify 0 补传(正确);R2 被破坏/丢失/异源覆盖 ⇒ ETag≠本地 ⇒ 照旧补传+告警。**省 179MB/轮 + 消 34 底噪 + 判别力全保留**。
- **风险/边界**:产物 schema 变更需走 §23.7(已上线产物结构动了字段,前端不读→行为不变,但建议 reviewer 全量核对消费方清单+键集审计;若用户拍板冻结 parts 结构,则退 P2)。`period_cutoffs` 若未来要在前端做"周期语义"展示,可从 backtest.json config(仍在,照旧产出)取。

### P2(不改产物,先恢复判别维度):verify-r2 对 B 档通道做"两分类计数"

- mismatch 分类:①「元数据代差」= 本地 B 档指纹 == state 指纹 且 R2 对象存在(非 404);②「真缺口」= 其余(含 404/无 state 可比/late 指纹不等)。
- **补传行为不变**(仍是把 R2 拉正,零风险);仅把"①"从计数/告警维度剥离(打一行"元数据代差 N 个(设计内)"汇总),mass_mismatch 阈值只统计②。判别力:404/真变化未上传全落入②照旧告警;丢失的仅是"异源覆盖成同 size 内容"这类在①里的可见性(该场景另有周日全量与 ETag 强对账兜底——周日设计内仍按整文件强对账)。
- 成本:verify-r2 一个分支 + 输出分流;不动产物、不动上传链。

### P3(不推荐,仅备案):元数据代差不补传

- 省带宽但引入理论漏检面(「R2 被同 size 异内容覆盖 + 本地无变化」轮,补传网被解除),与 9-23 事故兜底精神相悖。若走 P1 则无必要;若 P1 暂缓又必须省带宽,须先与用户拍板并写明残余风险。

## 6. 诚实标注(未知/未验证,不下断言)

- 10-03 的 36/38 与 10-04 的 8/1 浮动位构成**未逐一定因**(10-05 前日志无文件名行,#188 落清单后才有);推断为"其它通道偶发/独立链产物",**不作断言**。10-05 12:25 轮 36 的 +2 同因未定。
- **未直连 R2 做 ETag 实测**:云上无 rclone/aws/s3cmd,且为恪守"绝不写 R2/不跑上传器"约束未自建带凭据客户端;"R2 对象数据本体与本地一致"由三重间接证据支撑:①B 档指纹跨轮稳定(state==本地重算)②10-04 两轮 0 补传证明"R2==本地时判据通过"③9-15 设计文档实测("剔除三字段后 t2019/t2016 跨天本体逐位一致")。
- `period_cutoffs` 语义上仍是"滚动切点",撤出 parts 后若他日需要"口径切点"展示,消费方应改读 backtest.json config(现前端即如此)。
- 21:05 轮(2026-10-06 21:16:36 async)已纳入:补传 49 个,构成与分解见 §3/§4.3(kelly 34 精确重现 = 第 8 个见证轮);其中 15 个浮动位的归因基于同期通道状态推断(all-data 超时 + 独立链滞后),未逐文件直连 R2 复验。

## 7. 证据锚点汇总(可复核)

- 代码:upload_r2.py L1003-1036(B/A 档指纹)、L1192-1335(增量引擎判定+state 语义)、L3404-3546(verify-r2)、L3539-3544(补传直传)、L2119-2151(intraday/schedule_stats 链)、L2148(台账登记);export.py L1210-1266(每轮 subprocess 生成);signal_kelly_backtest.py L2138-2267(parts 产出);app.js L3775-3779 / lab.js L8699-8703(解析层零消费);lab.js L12958-12960(config.period_cutoffs 消费,非 parts)。
- 设计文档:docs/kelly/analysis/r2-incremental-upload-design-20260915.md L83-88(B 档剔除表)/L100-104(层2/层3 口径)/L154(口径分离声明)。
- 云上:`r2_upload_async_20261006_211636.log`(49 轮全清单+通道状态);`.r2_kelly_parts_state.json`(changed=[]、files 17、B 档指纹);两目录 17+17(ls);文件头 generated_at/period_cutoffs;`.r2_standalone_keys.json` 35 项(含 schedule_stats.json,不含 kelly parts);日志 `r2_upload_async_2026*.log`(各轮补传数+10-06 清单)与 `deploy_20261003/04/06_*.log`(补传数+段1 export 头)。
- 指纹实验命令(可复跑,云上只读):对 recent/t2011/t2026 三文件,现场重算"整文件 md5 / 剔三字段 B 档指纹"与 state 比对(结果见 §2 环 2 表格)。
