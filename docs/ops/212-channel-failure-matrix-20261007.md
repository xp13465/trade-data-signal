# #212 通道 × 失败后果 证据表(只读调研)

- 日期: 2026-10-07 | 任务: #212(派 #204 同族扫描) | 性质: 纯只读调研(未跑任何上传、未触发任何通知、未碰 R2 写)
- 范围: `scripts/upload_r2.py` 全部上传通道 **17 条**(A 类 14 增量引擎通道 + B 类 3 glob/自研通道)
- 判据(两步法, 来源=#212 原话+memory `alert-denoise-keep-fault-discriminator`):
  1. **真故障判别**: 该通道失败会不会让前端展示位读到陈旧/缺失数据?(会 → 候选)
  2. **去重判别**: 该通道**全部调用路径**是否已有 deterministic severe 告警?(全有 → 不挂, 属"已有等价"; 存在无告警路径/仅概率性采样兜底 → 挂)
- 已核实: 云上 `/etc/systemd/system/*.service` **无任何单元直接 ExecStart `upload_r2.py`**(2026-10-07 只读 ssh, grep 空)→ 本表"调用链"栏按仓内 grep 即为完整调用面。

## 0. 地基事实(全表公共证据)

1. **增量引擎 `_incremental_upload`**(L1199):失败唯一分支 = `ok != total`(L1471)→ `print FAILED_FILES`(L1478)→ `on_fail(...)`(L1479-1482)→ `sys.exit(1)`(L1484)。失败时 state 保持旧值不写 + 已成功部分刷 checkpoint(核心理念"宁多传不漏传")→ **下一轮重传自愈**。`on_fail` 扩展点(#204):参数 L1201 / 文档 L1226-1229 / 调用点仅 L1479-1482。
2. **on_fail 触达不到的失败路径**(接线时防误判):① export-guard L1374(`full_upload_blocked_<label>` 已有自身 notify 1800s)② `total == 0` L1466-1467 静默 exit(边界)③ cmd 级前置 `sys.exit("无 xxx json...")`(如 lab L774)。三类非"上传失败"语义。
3. **告警样板 `_notify_channel_upload_fail`**(L1699-1732):`--severe` + dedup `r2_channel_upload_fail_{label}` 窗口 21600s + 文案含失败清单/影响/手动补刷命令。已接线先例: offshore-fund L1735-1753(#193)/ fund-score L1756-1775(#193)/ etf-score L1778-1806(#204)。
4. **deploy 链聚合兜底=概率性**(17:50 `scripts/r2_upload_async.sh`,deploy.sh L582-586 触发):通道段 L201-226(15 个 run_r2_upload)失败进 R2_FAIL → `finalize_verify` L232-247 跑 `verify-channels`。**该轻量对账是"全池均匀抽 20 文件"**(`_LIGHT_CHECK_SAMPLE=20` L3649;`_light_check_channel` L3669-3696)→ 少数文件失败大概率不在样本内 → 判"抽查全一致" → 只落日志不告警; 仅大范围失败才命中 severe(`deploy_r2_upload_fail` 21600)。⇒ **"仅靠该聚合"的通道存在少数-文件失败被静默的窗口**。
5. **双告警属既有形态**(#204 审已认可):通道级即时(on_fail)+ 收尾聚合,键/窗口不同,非本次引入。

## 1. 证据表(17 行)

> A 类 14 条"失败当前行为"共用: 引擎 print `FAILED_FILES` + `sys.exit(1)`(L1478/L1484),命令级无 notify;差异仅在"调用链告警覆盖"。

| # | 通道 | 代码锚点(upload_r2.py 除注明外) | 失败当前行为 | 失败后果(线上) | 消费者证据(grep) | 建议挂 on_fail? | 理由 |
|---|---|---|---|---|---|---|---|
| 1 | lab | `cmd_upload_lab` L761-777(引擎 L776);调用: `update_lab.sh` L293-303(severe `update_lab_r2_upload_fail`)、deploy 链 L201 | 引擎 exit1;update_lab 链响,deploy 链仅采样兜底 | `lab/lab_*.json`(65 件)R2 旧版 → 首页「策略实验室」参数/回测/权重表读旧 | `static-site/lab.js` L1548/1723/1851(`https://ss.fx8.store/r2/lab/lab_backtest.json` 等) | ✅挂 | deploy 链(每日 17:50 刷新)仅 20 文件抽样, 部分失败可静默; update_lab 双告警属既有形态可接受 |
| 2 | trade_sim | `cmd_upload_trade_sim` L1500-1518(引擎 L1517);调用: 仅 deploy 链 L202 | 引擎 exit1;仅采样兜底 | `trade_sim/*.html` 模拟回测详情页读旧版, 用户点开看到旧报告 | `app.js` L8952(sim-btn href → R2 报告页)、L30267(兜底链接) | ✅挂 | 全链唯一兜底=抽样; 用户可点开页, 真静默缺口 |
| 3 | trade_sim_json | `cmd_upload_trade_sim_json` L1521-1546(引擎 L1540);调用: deploy 链 L205、`update_lab.sh` L310-318(severe) | 引擎 exit1;update_lab 链响,deploy 链仅采样 | `trade_sim/*.json`+`trade_sim_indices.json` → 首页模拟回测弹窗走势/统计卡读旧 | `app.js` L29981/29987(`_stats`/`_full`)、L31435 fee_compare、L44-66 trade_sim_indices | ✅挂 | 同 lab 模式: deploy 链为静默面 |
| 4 | index | `cmd_upload_index` L1549-1565(引擎 L1560);调用: deploy 链 L206、`intraday_snapshot.sh` L157-162(severe 含失败文件列表) | 引擎 exit1;intraday 链响,deploy 链仅采样 | `index/*-all.json` 全史 → 首页指数K线/情绪曲线叠图读旧 | `app.js` L1480、L10920(`/r2/index/${id}-all.json`) | ✅挂 | 补 deploy 路径(每日全量刷新面);盘中与 intraday 告警可叠加(既有形态) |
| 5 | etf_hist | `cmd_upload_etf_hist` L1568-1588(引擎 L1585);调用: deploy 链 L210、`etf_national_team_backfill.sh` L112-113(echo-only 静默) | 引擎 exit1;回填链明确静默,deploy 链仅采样 | `etf/{code}-all.json`(1532 只全史) → ETF/标的弹窗长历史K线读旧 | `app.js` L4798 `_SIM_ETF_PIN_URL`、`lab.js` L13664 | ✅挂 | 回填链(20:07)静默 + deploy 链抽样, 双静默面 |
| 6 | fund_nav | `cmd_upload_fund_nav` L1591-1626(引擎 L1623);调用: 唯一 `fund_nav_upload_async.sh` L38-47(severe 精确文案+手动命令) | 引擎 exit1;唯一调用方**已 severe** | `nav_bucket/{xx}.json`(256 桶) → 基金弹窗净值走势懒加载读旧 | `app.js` L27767-27829(`/r2/nav_bucket/...`) | ❌不挂 | 唯一调用方=async 脚本, 失败即 severe+精确影响文案 —— **已有等价**; 挂=同事件双告警零增益。可选"先重构再挂"(把该 notify 收敛到 on_fail)属统一口径的可选项 |
| 7 | accum_nav | `cmd_upload_accum_nav` L1629-1653(引擎 L1650);调用: 仅 deploy 链 L213 | 引擎 exit1;仅采样兜底 | `accum_nav/{code}.json`(G/H/I 真实净值)→ 全站净值走势缺/旧 | `common.js` L1286-1299(懒加载 SS 主源+`./data` 兜底)、`app.js` L5768+ | ✅挂 | 无其他告警路径 |
| 8 | industry | `cmd_upload_industry` L1656-1682(引擎 L1680);调用: 仅 deploy 链 L214 | 引擎 exit1;仅采样兜底 | `industry/*.json`+`industry-all-concepts.json` → 首页行业卡/行业详情读旧 | `app.js` L25088、L25451-25457 | ✅挂 | 无其他告警路径 |
| 9 | public_fund | `cmd_upload_public_fund` L1685-1696(引擎 L1693);调用: 仅 deploy 链 L215 | 引擎 exit1;仅采样兜底 | `public_fund_*.json` → 公募筛选器/持仓分布读旧 | `app.js` L21280-21313 | ✅挂 | 无其他告警路径(#204 审新增 2 条之一) |
| 10 | kelly_parts | `cmd_upload_kelly_parts` L1809-1826(引擎 L1821);调用: 仅 deploy 链 L221(按字节估算超时) | 引擎 exit1;仅采样兜底 | `signal_kelly_trades_parts/*.json` → 首页模拟回测弹窗凯利分片读旧 | `app.js` L3416/3744、`lab.js` L8602/8667 | ✅挂 | 无其他告警路径 |
| 11 | kelly_parts_sdc | `cmd_upload_kelly_parts_sdc` L1827-1842(引擎 L1837);调用: 仅 deploy 链 L222 | 引擎 exit1;仅采样兜底 | `signal_kelly_trades_sdc_parts/*.json` → 弹窗切「当日收盘」口径时读旧 | `app.js` L3743 `_simTradesBaseName`(sdc 分支)、`lab.js` L8601 | ✅挂 | 非默认口径但用户可切, 失败=对比档陈旧; 无告警路径 |
| 12 | kelly_snapshots | `cmd_upload_kelly_snapshots` L1843-1861(引擎 L1857);调用: deploy 链 L224、`s06_snapshot.sh` L161-163(EXIT trap severe `s06_snapshot_fail` 3600) | 引擎 exit1;s06 链响,deploy 链仅采样 | `signal_kelly_snapshots/*` → lab 凯利演进曲线 + 首页 K 档评级 latest_posrating 读旧 | `lab.js` L10537/10313、`app.js` L15864 | ✅挂 | 同 lab 模式: deploy 链为静默面 |
| 13 | data_large | `cmd_upload_data_large` L1911-1946(引擎 L1931);调用: deploy 链 L220、`turnover_backfill.sh` L148-164(聚合 severe)、`gold_night.sh` L62-75(echo-only 静默) | 引擎 exit1;turnover 链聚合响, gold_night 链静默, deploy 链仅采样 | `signal_kelly_trades.json`(86MB 主档)/`overfit_monitor*.json`/大 range `{id}-{all,5y,3y}.json` → 首页走势图大 range/过拟合监控/模拟回测主档读旧 | `app.js` L9654-9662(`_R2_LARGE_RANGE_RE`)、L2287-2304(overfit fetch)、L3781 | ✅挂 | gold_night 链静默面明确; turnover 聚合面; 三面不一 |
| 14 | all_data | `cmd_upload_all_data` L2083-2110(引擎 L2105);调用: 仅 deploy 链 L223 | 引擎 exit1;仅采样兜底 | `board_etf_map`/`daily_brief*`/`signal_stats`/`news_digest` 等兜底全量 → 首页 AI 建议选标的、每日前瞻、信号统计、新闻看板读旧 | `app.js` L28525(daily_brief)、L7651(signal_stats)、L15982(news_digest)、board_etf_map 10+ 处 | ✅挂 | 无其他告警路径 |
| 15 | intraday | `cmd_upload_intraday` L2112-2158(`_upload_glob` L2145;import总 0 只 print 返 0 L2146-2148;失败 `sys.exit(1)` L2149-2150);调用: `intraday_snapshot.sh` L169-173(severe `intraday_upload_intraday_r2_fail` 1800)、`turnover_backfill.sh` L144-161(聚合 severe) | 命令级静默 exit1, 但**两条调用链均 severe** | overview.json/intraday_snapshot/a-stock-* → 首页情绪分/成交额/盘中快照读旧(前端 60s~10min 轮询) | `app.js` L2698(`./data/overview.json` boot)、L7503(注释: 盘中 30min 重算 overview) | ❌不挂 | 全部调用路径已 deterministic severe → **无静默缺口**; 挂=必然双告警零增益。若拍板求"全站单点统一"可选接(样板=fund-score L1756-1775), 非默认 |
| 16 | data_files | `cmd_upload_data_files` L2272-2297(`_upload_glob` L2287;失败 `sys.exit(1)` L2289);调用 fan-out(grep 全量): `r2_upload_async.sh` L226(feed.xml, 聚合采样)、`intraday_snapshot.sh` L179-183(signal_kelly_trades_intraday **echo-only 静默**)、`fapi_bj_width_export.py` L106-113(**print-only 静默**)、`gen_daily_brief.py` L3112-3140(degrade/✗, 经 schedule_monitor 延迟链)、`nextday_plan_generator.py` L1161-1206(severe)、`nextday_gap_check.sh` L64+(severe)、`update_lab.sh` L327-339(severe)、`s06_snapshot.sh` L133-135(trap fire_alert)、`push_schedule_stats.sh` L67-80(severe)、`gold_night.sh` L68-75(severe)、`kelly_intraday_rerun.sh` L126-131(severe) | 命令级静默 exit1;调用方**混合**(多数 severe, 2 处明确静默) | 按调用方文件而异: schedule_stats/全局走势/北交所宽度/盘中凯利/lab_*/s06 状态/nextday_plan/feed.xml 各自前端位 | 见各调用方(如 schedule_stats → 首页执行统计) | ✅挂(等价改造) | 存在无告警路径(fapi_bj_width print-only; intraday 单文件 echo)→ 命令级单点补齐即覆盖全部调用方(#193 设计精神); 挂后对已有 severe 的调用方形成双告警(既有形态); 若侧重降噪的备选="先重构再挂"(收敛 9 个调用方 notify 到命令级), 重构面大不建议并批 |
| 17 | large_json | `cmd_upload_large_json` L2887-3234(**不走 `_upload_glob`/引擎**, 自研并行上传器 ThreadPool L3181-3182);失败路径全为 exit 1: L2929(excludes --print 失败)/ L3168(源文件异常缺失)/ L3209(`ok != len(changed_rels)`)/ L3226(状态原子写失败 fail-loud) | 命令级静默 exit1;唯一调用方 `staticdata_backup_async.sh` L192-210 + L444-466(**已 severe + heartbeat "fail"**, `staticdata_backup_fail` 3600) | 私有桶 `staticdata` 大 JSON 灾备副本缺 → **前端零展示**; 仅恢复链读它 | `scripts/restore-large-json.sh`(离线恢复, `PREFIX="large-json/"` L87); 且 `check_r2_channel_coverage.py` L30-38 将其列为 `_EXEMPT_PREFIXES`("独立校验链") | ❌不挂(不适用) | 非引擎/非 glob 通道, "on_fail" 机制不适用; 唯一调用方已 severe+heartbeat; 灾备私有桶非用户可见; 已有独立 manifest/恢复链。可选改进: severe 文案精确化(现"staticdata备份部分失败"不列失败文件)——另单 |

## 2. 汇总

- **建议挂:14 条** = A 类 13 条(lab / trade_sim / trade_sim_json / index / etf_hist / accum_nav / industry / public_fund / kelly_parts / kelly_parts_sdc / kelly_snapshots / data_large / all_data)+ B 类 data_files(等价改造)。
- **建议不挂:3 条** = fund_nav(已有等价)、intraday(全链已 severe, 无静默缺口)、large_json(机制不适用+已有等价)。
- 决策要点: 14 条中 9 条(trade_sim / etf_hist / accum_nav / industry / public_fund / kelly_parts / kelly_parts_sdc / data_large / all_data)是**完全无 deterministic 告警**的纯静默通道; 其余 4 条(lab / trade_sim_json / index / kelly_snapshots)是"日链已响、deploy 链静默"部分覆盖。

## 3. 派单建议(支撑 #212 实施)

- **批 1(核心, 建议一批)**: A 类 13 条接 on_fail —— 照抄 `_etf_score_on_fail` 样板(L1778-1787)+ 每通道一句 impact_note(直接复用本表"失败后果"栏文案)。机制同源(同一个引擎同一个挂点), 拆批反而重复派单成本; 若要控风险可按 1a=9 条纯静默 / 1b=4 条部分覆盖 两小批。
- **批 2(B 类 data_files)**: 在 L2289 失败处照抄 fund-score 样板(L1756-1775)接 `_notify_channel_upload_fail`("data-files" label)。含双告警评估(既有形态)。
- **批 3(可选/待用户拍板, 建议不做)**: ① fund_nav 若求全站口径统一 → "先重构再挂"(先改 `fund_nav_upload_async.sh` notify 收敛到 on_fail); ② intraday 单点化; ③ large_json severe 文案精确化。
- 实施注意(派单请写进 prompt): ① on_fail 只在 `ok!=total` 触发(§0.2 三类路径不触发, 测试勿错); ② dedup key 用现成 `r2_channel_upload_fail_{label}` 即可(与既有 caller key 不同即无双吞); ③ 自测必须打桩禁真发通知(memory `notify-script-selftest-must-stub`); ④ 回填后每通道 1 条 impact 文案建议同步本表。

## 4. 诚实标注 / 限制

- 本报告全部结论来自静态读码 + grep + 只读 ssh 清单, **未实测任何上传/告警**(纯只读任务约束)。
- "抽样兜底概率性静默"= 按代码口径推演(`_uniform_sample` 全池抽 20)→ 属机制层结论, 非实跑观测。
- 自愈性: 失败通道 state 不写 + 文件留在 changed → **下一轮成功即自愈**; 但用户看到陈旧数据的窗口 = 到下一次成功上传为止(①盘中链 10min 级 ②deploy 链 24h 级)。
- 调用方清单按本仓 `scripts/*.sh|*.py` 全量 grep + 云上 unit 无直调证明, 未含人工手动执行场景。
