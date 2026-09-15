# R2 上传增量化方案设计(2026-09-15)

> 背景:09-14 晚云上连锁超时根因 = R2 上传慢(服务器 4.2Mbps,利用率 84%)+ deploy 每天「全量重传」大文件,deploy 锁被占死,后续 service 排队超时。昨晚只调大超时值=治标。本方案=增量上传(治本)。
> 调研:researcher(role-researcher),证据=本机 static-site/data 实测(与服务器同构,symlink 同源,memory trade-data-code-dirs-are-symlinks)+ R2 线上对象抽样下载对比 + deploy 日志。

---

## 一、现状盘点表(全部通道)

数据来源:本机 /Users/linhuichen/code/trade-data/static-site/data 实测 du/find(2026-09-15);云上全量耗时按 4.2Mbps 实测带宽折算(传输时间=大小/0.525MBps)。

| # | deploy.sh 通道 | 命令 | 增量? | 文件数 | 大小 | 云上全量耗时 | 每日内容变化特性(实证) | 增量预期 |
|---|---|---|---|---|---|---|---|---|
| 1 | upload-lab | cmd_upload_lab | 无,串行自写循环 | 65 | 94MB | ~3min | 盘后 17:50 全重算,天天变 | 非交易日全省 |
| 2 | upload-trade-sim | cmd_upload_trade_sim | 无 | 103 | 5.3MB | ~10s | html 自 08-02 起未变(mtime 实证) | ~100% 省 |
| 3 | upload-trade-sim-json | cmd_upload_trade_sim_json | 无,8线程 | 504 | 370MB | ~12min(739s) | JSON 自 09-11 20:17 起未变(mtime 实证,4天) | ~100% 省 |
| 4 | upload-index | cmd_upload_index | 无 | 173 | 66MB | ~2min | 盘中重写+盘后重算,天天变 | 非交易日全省 |
| 5 | upload-etf-hist | cmd_upload_etf_hist | **已增量**(先例) | 1553 | 93MB | 增量秒级/周日全量~3min | 剔除 exported_at 指纹,只传数据本体变者 | 现状保持 |
| 6 | upload-fund-nav | cmd_upload_fund_nav | **已增量**+checkpoint | 26370 | 574MB | 增量≈470MB/天(~15min)/周日全量 3504.3s 实测 | 活跃基金 91.5% 天天有新净值,增量失效 | 上传层无解(二期产品重构) |
| 7 | upload-industry | cmd_upload_industry | 无 | 134 | 123MB | ~4min | 行情天天变 | 非交易日全省 |
| 8 | upload-public-fund | cmd_upload_public_fund | 无 | 13 | 7MB | 小 | 低变 | 顺手增量 |
| 9 | upload-etf-score | cmd_upload_etf_score | 无 | 3 | 29MB | ~1min | 盘后重算 | 非交易日全省 |
| 10 | upload-data-large | cmd_upload_data_large | 无,**串行 for 循环** | 23 | 234MB | ~8min(468s) | 混合:kelly_loss_features 实证稳定;signal_kelly_trades 76MB×2/accum_nav_map 19MB/overfit 13MB/range 文件天天变 | 工作日省稳定件,非交易日全省 |
| 11 | upload-kelly-parts | cmd_upload_kelly_parts | 无 | 382 | 170MB | ~5.7min(340s) | 深历史片(t2019/t2016)剔除三字段后跨天本体一致;recent/t2023+ 天天变 | 工作日省~10-15MB,非交易日全省 |
| 12 | upload-kelly-parts-sdc | cmd_upload_kelly_parts_sdc | 无 | 381 | 153MB | ~5min | 同 #11 | 同 #11 |
| 13 | upload-all-data | cmd_upload_all_data | 无 | 130 | 46.7MB | ~1.5min | **其中 ~34MB 与 data-large 双传同一 key**(见 §1.1) | 修双传省 34MB/天 |
| 14 | upload-kelly-snapshots | cmd_upload_kelly_snapshots | 无 | 12 | 1.1MB | 小 | 每日新增快照(新文件自然增量) | 顺手增量 |
| 15 | upload-feed | cmd_upload_data_files | 无 | 1 | 小 | - | RSS 天天重生成 | 不动(单文件) |
| 16 | purge-low-freq | cmd_purge_low_freq | 无(purge) | 126 keys | - | purge 类 | - | 不动 |
| — | upload-intraday(盘中链,intraday_snapshot.sh) | cmd_upload_intraday | 无 | 23 | 小 | 秒级(10分钟一次) | 盘中高频 | **不动**(冻结契约,盘中时效敏感) |

**每日 deploy 总传输量(平日)≈ lab 94 + ts-html 5.3 + ts-json 370 + index 66 + etf-hist 增量 + fund-nav 470 + industry 123 + pf 7 + etf-score 29 + data-large 234 + kelly 170 + sdc 153 + all-data 46.7 + snapshots ≈ 1.77GB ≈ 56min 纯传输**;加上 purge 分批(数千 keys × 0.5s 批间隔)与连接开销,deploy 锁独占 >1 小时 → 连锁超时根因。

### 1.1 双传浪费实证(upload-all-data × upload-data-large 同一 key)
- cmd_upload_all_data 排除清单(scripts/upload_r2.py L1271-1283)只排 industry-/public_fund/offshore_fund/fund_score/etf_score_list/signal_kelly_trades 前缀与大 range,**没有排 >=1MB 文件**。
- cmd_upload_data_large(L1040-1078)传 >=1MB + 大 range + overfit_monitor 前缀。
- 本地口径模拟:all-data 实际覆盖 130 文件 46.7MB,top5 含 accum_nav_map 18.5MB、overfit_monitor_ext 9.2MB、overfit_monitor 3.7MB、boot 1.7MB、kelly_loss_features 1.1MB——**这 5 个文件(34MB)同时被 data-large 上传同一 R2 key**(data-large 23 文件清单里都有)。每天双传 34MB ≈ 68s@4.2Mbps 纯浪费。

---

## 二、etf-hist 增量先例实现要点(复用模板)

位置:scripts/upload_r2.py L588-707 cmd_upload_etf_hist(docstring L597-612 含设计说明)。

1. **状态清单**:与数据同仓 `X/data/.r2_etf_hist_state.json`,结构 `{version, updated_at, mode, count, files:{文件名:指纹}}`(L664-678 `_save_state` tmp+os.replace 原子写)。
2. **指纹算法**(L632-649 `_fingerprint`):md5(json 解析后规范化序列化,**剔除天天变字段 exported_at**);json 解析失败退化为整文件字节 md5(坏文件必与上次不同→触发重传,宁多勿漏);json.dumps(sort_keys=True, separators) 同一解释器内序列化稳定,跨版本差异只会多传不漏传。
3. **为什么不用 mtime**(L603-607):export 每天全量重写所有文件,mtime 全变,mtime 口径会天天判「全变」致增量失效。
4. **判定与全量退化**(L653-660):`changed = [p for p in all_json if old_files.get(p.name) != sigs[p.name]]`;首跑/状态缺失/损坏 → 自动退化全量;每周日强制全量一次(防「R2 侧对象丢失而本地状态无感知」漂移)。
5. **宁多传不漏传**(L696-702):全部上传成功才写状态;部分失败保持旧状态,下次重传面更大。
6. **增量 0 待传=正常路径**(L680-685):直接完成不报错(防 deploy 把「今天没变化」当失败告警)。
7. **only_files 复用 _upload_glob 8 线程**(L416-447,only_files 参数 2026-08-23 加);purge_cache 只清本次实际上传的 key(L707)。

fund-nav 版(scripts/upload_r2.py L710-883)在 etf-hist 基础上多两点:整文件字节 md5(其 payload 无 exported_at)、每 500 只分片 checkpoint 断点续传(L844-856,治「超时 kill→状态缺失→下次更慢全量→再被 kill」恶性循环);跳过 purge(worker 对 fund_nav/ no-store,memory edge-cache-ttl-stretch-no-cache)。

---

## 三、增量方案设计

### 3.1 核心:通用增量引擎(一次实现,12 通道复用)

新写 `_incremental_upload()` 放进 scripts/upload_r2.py,参数化 etf-hist 全套机制:

```
_incremental_upload(local_dir, glob_patterns, r2_prefix, state_name, *,
                    fingerprint=None,     # 默认整文件字节 md5(A 档);B 档传结构化剔除函数
                    exclude_fn=None,      # all-data 的排除(含新增 >=1MB 排除)
                    checkpoint_every=0,   # 0=关;500=fund-nav 模式
                    on_success=None)      # checkpoint 回调复用
返回 (ok, total, failed_rels, uploaded_keys) —— 与 _upload_glob 同签名,调用方照旧 purge。
```

内置机制(逐条继承 etf-hist):
- 读状态 → 指纹扫描 → 增量判定 → only_files 调 _upload_glob(8 线程)→ 全部成功原子写状态 → 返回
- 首跑/状态损坏退化全量;周日强制全量;0 待传正常完成;部分失败保旧状态(宁多传不漏传)
- 新增:**上传后 ETag 对账**(见 §3.4 机检层2)——本次实际 PUT 的每个 key,PUT 响应后立即 HEAD 取 ETag 与本地整文件 md5 比对,不一致记入 failed_rels(传上去的内容不对=失败,告警)。比「只信 200」多一道上传正确性闭环。

etf-hist / fund-nav 迁移复用本引擎(行为逐位等价:同状态文件路径、同指纹口径、同退化/周日/checkpoint 语义;fund-nav 传 checkpoint_every=500 + 无 purge)。两者是已上线冻结资产(§23.7),迁移后必须 reviewer 对账「迁移前后日志模式行一致」。

### 3.2 指纹算法分档

| 档 | 算法 | 适用通道 | 依据 |
|---|---|---|---|
| A | 整文件字节 md5 | trade-sim-json / trade-sim / index / lab / industry / public-fund / etf-score / data-large / all-data / snapshots | 这些文件无天天变元数据字段;实证:kelly_loss_features.json R2(09-14 版)与本地(09-13 版)md5 逐字节一致(9dc05b42) |
| B | 结构化剔除:md5(json.dumps(payload 剔除 generated_at + period_cutoffs + buy_amount, sort_keys)) | kelly-parts / kelly-parts-sdc | 实证:剔除三字段后 t2019.json、t2016.json 跨天(R2 09-14 22:10 vs 本地 09-13 05:10)本体逐位一致;不剔除则天天变。三字段=生成器元数据(生成时刻+滚动周期切点+本金常量),前端零消费(接入实施时逐字段 grep app.js/lab.js 复核,复现 etf-hist exported_at 先例) |
| C | 保持现状 | etf-hist(剔除 exported_at)/ fund-nav(整文件+checkpoint) | 冻结不动(迁移进引擎但口径不变) |

- 状态 files 存双字段 `{size, md5}`:先 size 快筛(不等直接判变,免读文件),size 同再 md5 确认(读一次)。大文件 234MB 读 md5 本地 ~1-2s/云上 ~3-5s,可接受。
- 剔除字段清单随通道记录来源:signal_kelly_trades_parts/*.json 顶层 5 键 = generated_at / buy_amount / period_cutoffs / fields / quadrants(本机 head 实证),前三剔除后 fields+quadrants 为数据本体。

### 3.3 状态清单规范
- 每通道独立:`data/.r2_<channel>_state.json`(命名对齐 .r2_etf_hist_state.json 先例),结构 `{version:1, updated_at, mode, count, files:{name:{size,md5}}}`
- 放 `$REPO/data/`(untracked,不进 git;现有 etf-hist/fund-nav 状态文件已在 trade-data/data/ 与 trade/data/ 各一份,macOS 双树由 REPO 决定路径,无漂移;服务器单仓 REPO=GIT_REPO 天然单份)
- 本地删除的文件自然剔除状态(R2 残留旧 key 无害,不做删除,同 etf-hist)

### 3.4 防漏传机检(四层)

| 层 | 机制 | 频率 | 防什么 |
|---|---|---|---|
| 1 语义兜底 | 全部成功才写状态;失败宁多传;首跑全量;周日强制全量 | 每次 | 状态与实际不符→重传方向偏多 |
| 2 上传正确性对账 | **引擎内置:本次 PUT 的 key 逐一 HEAD 取 ETag == 本地整文件 md5**,不一致记失败 | 每次上传后 | 传上去的内容不对(截断/错文件/网络中间人改写) |
| 3 周期全量对账(新命令 verify-r2) | list R2 前缀 keys + HEAD 每 key 取 ETag,与本地文件逐位比对:本地有 R2 无→**自动补传**;ETag≠本地 md5→**自动补传**;R2 有本地无→记录不删(残留无害)。**内部按 weekday==6 自适应:周日=全量对账(补传+报告),平日=只对账当日增量通道的 key 清单(秒级)** | deploy 链每日调用(内部自适应) | R2 对象丢失/状态清单污染导致的漏传→自动修复+告警 |
| 4 告警链 | verify-r2 发现并补传不一致 → 打印修复清单;补传失败/命令失败 → exit 1 → deploy.sh R2_FAIL 收尾 notify(现有链 L827) | 每次 | 人感知 |

技术前提:R2 单 PUT 的 ETag=内容 md5(本项目 upload_r2.py 纯单 PUT 无 multipart,恒成立;multipart 才不是)。verify-r2 用新增 `s3_head(key, bucket)`(http.client HEAD + SigV4,读 ETag header,不下载 body),8 线程并发,单请求 RTT ~0.3s:data-large 23 个 ~1s、kelly-parts 382 个 ~15s、index 173 个 ~7s、industry 134 个 ~6s、trade-sim-json 504 个 ~20s、etf-hist 1553 个 ~60s;fund-nav 26370 个 ~16min → fund-nav 特判:平日对账仅本次 PUT 数(日常 2.4 万~16min 也不可)→ **fund-nav 平日抽样 100 只,周日全量对账**(周日 7200s 通道内可容纳)。

### 3.5 各通道接入映射(改动点清单)

| 通道 | 改动 | 指纹 | 状态文件 | 超时建议 |
|---|---|---|---|---|
| upload-lab | 串行自写循环(L382-413)→ 引擎;lab 回退 ROOT 逻辑保留 | A | .r2_lab_state.json | 900s 不变 |
| upload-trade-sim | _upload_glob→引擎 | A | .r2_trade_sim_html_state.json | 900s |
| upload-trade-sim-json | _upload_glob→引擎 | A | .r2_trade_sim_json_state.json | **900→1800s**(全量 370MB@4.2Mbps=739s+连接开销,数据还在涨,仿 fund-nav 7200s 先例留 2 倍余量) |
| upload-index | →引擎 | A | .r2_index_state.json | 900s |
| upload-industry | →引擎(4 组 glob pattern 保留) | A | .r2_industry_state.json | 900s |
| upload-public-fund | →引擎 | A | .r2_public_fund_state.json | 900s |
| upload-etf-score | →引擎 | A | .r2_etf_score_state.json | 900s |
| upload-data-large | 串行自写循环(L1082-1099)→引擎(**顺手改 8 线程**);overfit purge 分叉(L1107-1112 cache_prefix="/")保留在通道函数 | A | .r2_data_large_state.json | 900s(全量 468s,够) |
| upload-kelly-parts | →引擎 | B(剔除三字段) | .r2_kelly_parts_state.json | 900s(全量 340s) |
| upload-kelly-parts-sdc | →引擎 | B | .r2_kelly_sdc_state.json | 900s |
| upload-all-data | →引擎 + **exclude_fn 增加「sz>=1MB 或 overfit_monitor 前缀」排除(修双传 §1.1)**,与 data-large 文件集互斥 | A | .r2_all_data_state.json | 900s |
| upload-kelly-snapshots | →引擎 | A | .r2_kelly_snapshots_state.json | 900s |
| upload-etf-hist / fund-nav | 迁移复用引擎,口径零变化 | C | 沿用现有文件名 | 900s / 7200s 不变 |
| upload-feed / purge-low-freq / upload-intraday | 不动 | - | - | - |
| 新增 verify-r2 | 新子命令(§3.4 层3),deploy.sh 每日调用一次(内部周日自适应) | - | 无状态 | 900s |

### 3.6 deploy.sh 改动
- L437 trade-sim-json 超时 900→1800s(其余不变)
- 上传段后新增一行 `run_r2_upload "verify-r2" 900 verify-r2 || R2_FAIL+=...`(失败同样走收尾 notify 链)
- 引擎的层2 ETag 对账在 upload_r2.py 内部完成,deploy.sh 无需感知

### 3.7 量化收益预估(4.2Mbps 服务器,平日单次 deploy)
- 现在 ~1.77GB ≈ 56min 纯传输 + purge 批间隔
- 增量后平日:省 trade-sim-json 370MB(-12min)+ trade-sim 5.3MB + 双传 34MB(-68s)+ kelly 深历史 ~15-20MB + 稳定件(kelly_loss_features 1.1MB 等)→ **~1.35GB ≈ 43min,省 ~13min(-23%)**
- **非交易日 deploy(update_all 非交易日分支 L67-74 每天照跑):~1.77GB → 接近 0(全部通道指纹不变,deploy 秒级)**——这是增量机制最大确定性收益(全年周末+节假日 ~1/3 天)
- 同日重复 deploy(修 bug/手动补推):第二次起 ~0
- fund-nav 470MB/天(15min)上传层无解,列二期

---

## 四、风险清单

| # | 风险 | 对策 |
|---|---|---|
| 1 | **漏传**(最大风险:状态清单说已传但 R2 对象丢失/被删/旧版) | 层1 周日强制全量 + 层3 verify-r2 周日全量对账自动补传 + 层4 告警;平日 verify-r2 也查当日通道 |
| 2 | 状态清单损坏 | 读失败退化全量(etf-hist 既有语义) |
| 3 | 状态清单被回滚旧版(rsync/git restore) | 状态在 data/ untracked 不进 git;即使被回滚:旧指纹 vs 新内容→判变→多传,方向安全;唯一组合「数据文件也回滚旧版」→本地旧内容与旧指纹匹配→跳过→R2 保持新版,线上不受影响,下次更新自然恢复 |
| 4 | 剔除字段(generated_at/period_cutoffs/buy_amount)未来被前端消费 | 实施时逐字段 grep app.js/lab.js/common.js 核实零消费(etf-hist exported_at 先例);若被消费→该通道降为 A 档(多传不漏) |
| 5 | 指纹 md5 碰撞 | 概率 2^-64 级,可接受;层2/层3 同口径(整文件 md5)不引入新碰撞面 |
| 6 | 上传过程中文件被 export 重写(指纹旧) | 时序不变(deploy 在 export 后串行);增量判定单次扫描内完成;扫描后文件再变=下次多传,不漏 |
| 7 | json 序列化跨版本差异 | 只会多传不漏传(etf-hist 注释 L635-636 已论证) |
| 8 | all-data 排除条件变更(修双传)口径兼容 | data-large 同 key 已覆盖,前端无感;实施后机检断言「all-data 文件集 ∩ data-large 文件集 = ∅」(两命令清单互斥) |
| 9 | 周日全量日耗时不变(fund-nav 3504s 实测)+ verify-r2 全量对账 ~16min | 设计内兜底成本,周日一次;平日不再受影响 |
| 10 | 状态文件数量增多(11 个新文件) | 全部 data/ untracked,不进 git,不污染仓库 |
| 11 | 层2 ETag 对账对「B 档结构化指纹」通道 | 层2 用整文件 md5 口径(非结构化指纹)做对账,验证的是「R2 对象==本地文件」,与「该不该传」的判定口径分离,不冲突 |

## 五、实证数据汇总(全部可复现)

- 通道体量:本机 /Users/linhuichen/code/trade-data/static-site/data 实测(与服务器同构 symlink 同源):etf 1553 文件 93MB / fund_nav 26370 文件 574MB / index 173 文件 66MB / lab 65 文件 94MB / trade_sim 504 文件 370MB / kelly-parts 382 文件 170MB / sdc-parts 381 文件 153MB / snapshots 12 文件 1.1MB / industry 134 文件 123MB;data-large 口径 23 文件 233.6MB(top3:signal_kelly_trades 76.5MB、signal_kelly_trades_sdc 76.5MB、accum_nav_map 19MB);all-data 口径 130 文件 46.7MB
- trade_sim JSON mtime = Sep 11 20:17:24 起未变(4 天),html mtime = Aug 2 23:11 起未变——但每天全量重传
- 跨天本体稳定性抽样(R2 对象=09-14 22:10 export 后上传,本地=09-13 05:10 export,逐位对比):
  - t2019/t2016(深历史年片):剔除 generated_at/period_cutoffs/buy_amount 后**本体一致**
  - t2023/t2024/t2025/recent/lab_etf_approx__A_p1:**不一致**(含未平仓持仓,current_price/real_current_price 天天变)
  - kelly_loss_features.json 整文件 md5 一致(9dc05b42);boot.json 不一致(7d311824 vs eedff597)
  - 结论:kelly-parts 增量收益集中在深历史片(~10-15MB/170MB 工作日)+ 非交易日全省;trade_sim 370MB 工作日即可省
- deploy_20260913_0208.log(本机 09-13 周日 02:08):fund-nav 周日全量 3504.3s(58min)实测;lab 65/65、trade_sim 103/103 全量上传;purge 各通道批次全成功——周日全量兜底成本实证
- 带宽与耗时:云上实测 10MB/19s=4.2Mbps(利用率 84%,来源 research-r2-accel 调研存档 /tmp/agent-progress-research-r2-accel.md)

## 六、二期可选项(需用户拍板,本方案不做)

1. **fund-nav 按日分片产品重构**:历史序列冻结 + 每日增量表(2.6 万只当日净值打包 ~2-5MB/天),省 470MB/天→~5MB/天。代价:动前端合并逻辑(已上线功能,§23.7 冻结契约需用户确认),且逐基金日增 key 方案请求数爆炸(PUT 2.6 万次/天≈54min)不可行,必须打包表。**这是上传层无法解决的剩余大头(15min/天)**。
2. accum_nav_map 19MB 同思路拆分「历史冻结+近 N 天」(省 ~17MB/天),动 common.js 消费端。
3. S3 multipart 并行:5M 带宽封顶时无增益(调研已实锤),升带宽后再启用。
4. 云上带宽再升档(5M→更高):直接压缩全部通道时长,但花钱,用户拍板。

## 七、验收口径(派 implementer/reviewer 时附)

- 引擎+12 通道接入+verify-r2 子命令+deploy.sh 超时与调用改动,全部 commit feat 分支走 main-merge
- 自验清单:①引擎 dry-run 模式(--dry-run 打印「将传 N/M」不 PUT,本方案顺带设计)②all-data ∩ data-large = ∅ 断言 ③etf-hist/fund-nav 迁移前后日志模式行一致对账(reviewer)④层2 ETag 对账实测(手工改坏一个 R2 对象→verify-r2 补传修复)⑤周日全量路径实测一次(全通道)
- 上线后监测:deploy 链各通道耗时日志(预期:平日上传段从 ~56min 降至 ~43min,非交易日秒级)
