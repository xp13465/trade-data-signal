# W3 数据可信批·第一段(#222 只读定性)报告

- 日期:2026-10-11 | 角色:researcher(只读,未改代码/未 commit)
- 对象:全量 `signal_kelly_trades.json` / `signal_kelly_trades_sdc.json`(走 data-large 通道)的 `generated_at` 每轮变 ⇒ 每轮真上传 ≈175MB(≈1GB/天)
- 关联:#219 parts 治本(`docs/ops/219-parts-metadata-fix-20261006.md`)、#161(背景)、pending-index #222

## 0. 结论速览(三问)

| 问 | 结论 |
|---|---|
| Q1 告警链怎么读它 | 共 5 类消费点(见 §2)。真正"怕动"的只有告警 B2 一处;而 B2 对「撤出」自动安全(回退 mtime)、对「冻结成固定值」才危险(min() 取更旧 → 48h 后每交易日 22:35 恒 SEVERE 误报)。展示链 2 处(首页弹窗/lab)需**改源**,否则日期显示降级为 "-"。 |
| Q2 有无等价替代时点源 | 有,且成本极低:① 文件 mtime —— **B2 已把它作为第一候选**(撤键即自动生效,零改动);② 同批小产物 `signal_kelly_backtest.json` 的 generated_at(563,967B,lab 已在读同文件)——展示链的自然替代;③ R2 对象元数据/内容锚点——不推荐(理由见 §3)。 |
| Q3 动不动/怎么动 | **推荐动,走 #219 同款治本**:全量 trades 主+sdc 双文件撤出「每轮必变」元数据(`generated_at` 必撤,`period_cutoffs` 一并撤)。收益 ≈0.9~1.6GB/天 + 跨境链路 35~45min/天占用(见 §4);代价=§23.7 用户拍板 + 2 处 1 行级改源;**告警代码完全不碰**(B2 自动回 mtime)。**明令禁止**把字段改成"冻结值/日粒度值"(那才触发 B2 误报)。 |

## 1. 机制钉死(为什么每轮必传)

- 生产者:两文件同族 `_build_outputs` 产出,顶层含 `generated_at = datetime.now()`(每轮必变)+ `period_cutoffs`(滚动日期切点,每日变)+ `buy_amount`(常量)+ `fields` + `quadrants`(数据本体)。
  - `scripts/signal_kelly_backtest.py:1686-1692`(主档 trades_output:`1687 "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")`、`1689 period_cutoffs`)
  - `scripts/signal_kelly_backtest.py:1799-1802`(sdc 变体同款 generated_at)
- 上传判据:data-large 通道逐文件**整文件 md5**(A 档)与状态清单比对,md5 不同 ⇒ changed ⇒ 真 PUT。
  - `scripts/upload_r2.py:1375-1379`(`md5 = fingerprint(p)` → `if old[1] is None or old[1] != md5: changed.append(p)`)
  - `scripts/upload_r2.py:1321`(`fingerprint = fingerprint or _file_md5`,默认 A 档整文件;1027 `def _file_md5`)+ `2096-2098`(`cmd_upload_data_large` 调 `_incremental_upload(..., ".r2_data_large_state.json", label="data-large")`,未传 B 档指纹 ⇒ 走 A 档)
- **推论(代码确定性,非推断)**:generated_at 每轮变 ⇒ 整文件 md5 必变 ⇒ 每轮必传 ≈175.4MB(两文件)。这与 #219 的 parts 病灶同源(生成器元数据污染变更判据),但**形状不同**(见 §2 末行,不能照搬 P1 的"只换尺子")。
- 与 #219 parts 的机制对照(#219 注释原文,`signal_kelly_backtest.py:2217-2227`):
  - parts:`上传链按 B 档结构化指纹(剔除这三字段)判「内容没变→跳过」, 而 verify-r2 按整文件 md5 对账 ⇒ 每轮必然全量「对不上」⇒ 每轮补传整目录(~179MB/轮 × 5~7 轮/天 ≈ 0.9~1.2GB/天跨境)`。
  - 全量 trades(**本批**):两把尺子本来就同源(上传判据=整文件 md5;verify-r2 对账=HEAD ETag vs 本地整文件 md5,`upload_r2.py:3705-3721`),浪费发生在**上传侧**(md5 变必传),不在 verify 补传侧。⇒ 若只把上传判据换成 B 档而内容不动,verify 会立刻回到 #219 病态(ETag 与 B 档指纹不等 → 每轮补传);若只改 verify 侧同理。**唯一自洽解 = 让内容(即上传字节)稳定**(§4)。

## 2. Q1 消费清单:谁读 / 读来干嘛 / 撤了或稳定化会怎样

| # | 消费方 | 位置(行号) | 读来干嘛 | 撤出 generated_at | 冻结/固定值 |
|---|---|---|---|---|---|
| 1 | 告警 B2(check_data_gap_alerts) | `scripts/check_data_gap_alerts.py:1319-1327`:`ts_cands = [mtime]` → 有 generated_at 才 append → `fresh_ts = min(ts_cands)`;上限 `KELLY_STALE_MAX_H = 48`(L169);周末按最近交易日放宽(L1334-1335) | 产物「进程停摆」时间轴告警:>48h 未刷新 → SEVERE。云上 timer `trade-check-data-gap.timer` = `OnCalendar=Mon..Fri * *-*-* 22:35:00`(实测) | **安全**:回退 mtime 单源,仍能抓"backtest 连续未跑"(文件每次 export 都被重写,mtime 递进) | **危险**:min() 取更旧者,冻结值 48h 后每交易日 22:35 恒 SEVERE 误报 |
| 2 | 首页 K 档评级弹窗日期 | `scripts/kelly_posrating.py:920` `"generated_at": trades_doc.get("generated_at")` → `latest_posrating.json` → 前端 `static-site/app.js:15863-15868` fetch → `static-site/common.js:577/595` 展示 `s.src.date`(线上实测显示「每日快照·默认 S06 组合(2026-10-11 16:47 · 费率…)」) | 展示"快照数据时间" | 显示降级:577 行条件省略、595 行 `(s.src.date || '-')` → '-' | 需同步改源(见 §3 候选②) |
| 3 | lab K 档评级槽日期 | `static-site/lab.js:9341` `window._AI_POSCAP_RATING_DYNAMIC_LAB = {..., date: (data.generated_at || ""), ...}`(data=lab 凯利区本次载入的 trades 文档;常态走分片 `t{YYYY}.json`——**#219 后分片已无该键,该槽在常态已为空**;仅分片失败回退全量文件 `lab.js:8727/8770/8861` 时才有值) | 同弹窗 lab 侧日期 | 回退路径变 ''(与常态现状一致) | 同前 |
| 4 | overfit_monitor | `scripts/overfit_monitor.py:416` `return by_date, data.get("generated_at","")` → `:1862` 写 `overfit_monitor.json.trades_generated_at` | 仅供追溯的元数据 | 变 "";**全仓 grep 无其它消费方**(唯一命中即 1862 写入点) | 无影响 |
| 5 | 上传/对账链(元消费) | 上传 md5 判据 `upload_r2.py:1375-1379`;verify-r2 `upload_r2.py:3705-3721`(HEAD ETag == 本地整文件 md5,周日全量 / 平日 changed∪抽样100∪独立链台账,`3667-3700`) | 决定传/跳过、补传 | 撤键后两把尺子仍同源且更稳 | — |
| — | `signal_kelly_trades_sdc.json` | `check_data_gap_alerts.py` 全文件 **0 处 sdc 读取**(grep 实测) | — | sdc 的 generated_at **无告警/监控消费方**(仅 lab sdc 模式同 #3 路径) | — |

补充:邮件链 `check_signals.py` 无该字段使用;`check_r2_consistency.py` 指纹对象是 overfit_monitor 等,不含 trades;B1 用内容锚点 `signal_date`(`_scan_trades`,`check_data_gap_alerts.py:947-966`),与 B2 时间轴互补,不可合并替代。

## 3. Q2 等价替代时点源(逐候选)

1. **文件 mtime** —— 可行性高,**已内置**:B2 `ts_cands` 第一项就是 mtime(L1320)。可靠性核:云上文件由本机生产链写(原子写 os.replace),deploy rsync `-a` 保 mtime(`deploy.sh:539-557` 区),`static-site/data/*` gitignored 不受 git 操作触碰;反面案例(mac 开发树 deploy pull 刷新 mtime 误报)不发生在云上生产树。
2. **同批小产物 `signal_kelly_backtest.json` 的 generated_at**(`signal_kelly_backtest.py:1662-1663`)—— 563,967B(云上实测),走 all-data 通道(非 data-large,churn 成本≈0);lab 已在读该文件(`lab.js:9680` `_labKellySummaryName()`)。**展示链的自然替代源**(首页由服务器侧 kelly_posrating 读、lab 前端读)。
3. R2 对象元数据(HEAD LastModified/ETag)—— 可查(verify 链已用 HEAD),但现**无任何消费方**读它做新鲜度;引入=新增跨境依赖+新告警面,不建议。
4. 内容语义锚点(如 max(signal_date))—— B1 已用;若用它替代 B2 则两轴合一,丢失"进程是否在跑"的独立判别力,不建议。
5. 其它小文件时间戳(trades_intraday / snapshots index)—— 语义不同(盘中档/快照档),pass。

## 4. Q3 收益 vs 风险 + 建议(带条件)

### 4.1 收益量化(云上实测)
- 每轮两文件字节 = **175,397,796B**(云上 `.r2_data_large_state.json` 实测:main 87,015,122 + sdc 88,382,674;10-11 记录)。
- 轮次/天(云上日志实测计数,10-05..10-11):5/5/5/9/5/3 轮(deploy_* 与 r2_upload_async_* 一致)。
- ⇒ 估算 **0.9~1.6GB/天**(与派单背景 ≈1GB/天、#219 注释 0.9~1.2GB/天 同量级)。
- 诚实标注:抽样日志显示并非每个 data-large 轮都包含该对文件(多轮仅"待传 4/24"小文件、~21-24s),包含该对的轮 = kelly 回测重跑轮(实测大轮样例:178.2s/8 文件、412.3s/21 文件、417.4s/24 文件、turnover 链 461~657s);故给区间不给单点。**周日=「周日强制全量」**(state `mode=周日强制全量` 实测),两文件无论如何都传——**周日省不到,工作日才是主战场**。
- 额外成本:跨境链路占用。175.4MB 按文档实测 326-390KB/s(`upload_r2.py:470` 注释:82.3MiB 单 PUT 需 211-253s)≈ 7-8min/轮,×5 轮 ≈ 35-45min/天;该链已多次因低速被判 kill(本日 async 日志实测:`⚠ upload-trade-sim 低速(近5分钟字节增量<1MB), kill`),占用越久越挤。

### 4.2 风险
- 告警语义风险可降为 **0**:不碰 B2 代码;撤键后 B2 自动回 mtime(§2 行1)。
- 真风险面:① 展示两处需改源(漏改 → 弹窗日期 "-",可逆、非数据错);② §23.7 冻结契约——该文件是已上线资产(lab 凯利区依赖,`signal_kelly_backtest.py:2205` 注释明确"本体不动"),字段集变更**须用户拍板**。

### 4.3 建议(完整版,不妥协)
**动。按 #219 同款治本路线**:生成端撤出全量 trades 主档+sdc 双文件的「每轮必变」元数据 → 内容本体不变则整文件 md5 稳定 → 上传跳过、verify 0 补传,判别力不降(本体真变/R2 破坏丢失时两处照旧发现)。
- 撤除范围:`generated_at`(必撤)+ `period_cutoffs`(建议一并撤;全仓无消费方已穷举:`scripts/*.py` 仅生产者写入(L1669/1689/1802)、upload B 档指纹剔除函数(L1042-1060)、bond 变体;前端读的都是 `signal_kelly_backtest.json` 的 `config.period_cutoffs`——`lab.js:8971/12959`,app.js 模拟弹窗 cutoff 为客户端自算,无该字段读取)。`buy_amount` 常量可留可撤(不影响 md5 稳定性)。
- 前置条件(缺一不算完成):
  1. §23.7 用户拍板(字段集变更);
  2. 改两处展示源:`kelly_posrating.py:920` 与 `lab.js:9341` → 改读 `signal_kelly_backtest.json.generated_at`(候选②)或 posrating 自身运行时刻(1 行级);
  3. **明令禁止**"冻结值/日粒度值"改法(B2 min() 会踩 48h 误报);
  4. sdc 与主档同改(同族字段,防口径分叉);
  5. 验收:部署后连续 2 个工作日观察 data-large 轮出现"内容未变化跳过" + verify-r2 平日 0 补传;任一展示位口径若变化须同步 §21 公示。
- 次选(仅风险缓释,不推荐作最终态):先只撤 sdc(告警链 0 消费,风险最低)观察一周再撤主档——但两档不对称会引入新口径分叉,违背一步到位准则。

## 5. 附属段(#161 背景 + 顺带发现,不在本批实施)
- #161(verify-r2 平日全通道 key 数/规模指纹)未实施;本轮已核 verify-r2 现行口径(`upload_r2.py:3667-3700`),与本次 pair 的浪费无交集(该 pair 的浪费在上传侧,见 §1),不影响 #161 的价值判断。
- 顺带发现 1:`check_data_gap_alerts.py:172` `KELLY_BACKTEST_FILE = "signal_kelly_backtest.json"` **定义后从未使用**;文档头 L73 "signal_kelly_backtest.json(B2 generated_at 同查)" 与实现不符(实现只查 trades 文件,L1235-1240)——建议顺手订正(供主控定)。
- 顺带发现 2:本日云上 async 日志(20261011_165148)另有与本批无关的运行态告警:trade-sim 通道低速被 kill;verify-channels 补传 2 个(news_digest 2 文件)——登记供主控(可能已在案)。

## 6. 证据附录(命令与出处)
- 生产者字段:`sed -n '1686,1692p' scripts/signal_kelly_backtest.py`;`sed -n '1799,1802p'` 同文件
- 上传判据:`command grep -n "_file_md5\|changed.append\|force_full" scripts/upload_r2.py` → 1027/1375-1379/1385/3310;`sed -n '2094,2102p'`(data-large 命令参数)
- #219 病灶对照原文:`sed -n '2215,2227p' scripts/signal_kelly_backtest.py`
- B2:`sed -n '1319,1344p' scripts/check_data_gap_alerts.py`;`grep -n KELLY_STALE_MAX_H` → 169;云上 `trade-check-data-gap.timer`:`OnCalendar=Mon..Fri * *-*-* 22:35:00`(ssh 实测)
- 展示链:`sed -n '917,924p' scripts/kelly_posrating.py`;`sed -n '15858,15868p' static-site/app.js`;`command grep -n "每日快照\|latest_posrating" static-site/common.js` → 577/595;`sed -n '9341p' static-site/lab.js`
- overfit:`command grep -n "generated_at" scripts/overfit_monitor.py` → 416/1862;`grep -rn trades_generated_at` 全仓唯一命中=1862
- 云上实测(ssh ubuntu@122.51.111.173):`.r2_data_large_state.json`(updated_at 2026-10-11T18:11:32 / mode=周日强制全量 / count=24 / changed 24 项 / 两文件 size+md5);`ls -l static-site/data/signal_kelly_trades*.json`(87,015,122@16:47:41 / 88,382,674@16:48:06);日志计数 `ls r2_upload_async_2026*.log` 按日 5/5/5/9/5/3
- 吞吐与 kill 判据:`scripts/upload_r2.py:462-475` 区注释(326-390KB/s、211-253s);本日 async 日志 L5 "低速…kill"
