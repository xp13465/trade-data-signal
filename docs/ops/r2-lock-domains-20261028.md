# R2 上传锁: 按产物域分锁 + 超时梯度(2026-10-28)

任务书 `/tmp/task-r2lock-20261028.md`。台账依据: §22(多展示位一致)+ L55(超时梯度四副本)+ L52(改
`scripts/` 必跑全量 pytest)。机检入口: `python scripts/r2_lock_gradient_audit.py`。

## 0. 一句话

全局单锁 → **按产物域分锁**(域间 key 不重叠 ⇒ 可并行; 同域串行); 未声明域的调用方
**原样回落全局锁**(漏改 = 继续全局串行, 绝不会变成无锁并发); 每个调用方显式给「锁等待上限」,
并保证 **锁等待 < 内层预算 < 外层 systemd 墙**(L55)。

## 1. 改前基线(云上近 30 天, 只读核查日志)

| 指标 | 数值 | 来源 |
|---|---|---|
| 单条「等待 R2 上传锁」最长 | **3990s** | 云上 `data/logs/*` 心跳行, 近 30 天 |
| S06 等锁被杀 | **870s → rc=124** | 10-27 `s06_snapshot` 实况 |
| 锁等待超时(fail-closed)次数 | 1 次 | 同窗口 |
| 归因范围 | 夜间二十多个任务共用一把锁 | `systemctl list-timers` + R2 日志 |

结论: 排队时长由「所有任务串行」决定, 与单任务自身工作量无关 ⇒ 分域是唯一结构解。

## 2. 域划分与对象 key 不重叠证据

| 域 | 写者(命令) | 对象 key 前缀 | 不重叠依据 |
|---|---|---|---|
| `data` | upload-data-large / upload-all-data / upload-intraday / upload-data-files(大载荷) | `data/<顶层文件>` | **大文件通道**取件集合由 `_is_data_large_file` / `_is_all_data_excluded` / 固定 28 文件表互斥 ⇒ 必须同域;**小载荷通道仍跨锁**(8MB 以下的 data-files 走独立小锁, 与 data 域同写 `data/schedule_stats.json`, 既有例外, 见 §2.1) |
| `etf_score` | upload-etf-score | `data/etf_score_list_*.json` | `_DATA_EXCLUDE_PREFIXES` 含 `etf_score_list`, data-large/all-data 共同排除 |
| `kelly_parts` | upload-kelly-parts | `data/signal_kelly_trades_parts/` | `*.json` glob **非递归**, 顶层 data 写者不覆盖子目录 |
| `kelly_sdc` | upload-kelly-parts-sdc | `data/signal_kelly_trades_sdc_parts/` | 同上 |
| `kelly_snapshots` | upload-kelly-snapshots(含 s06 ④b) | `data/signal_kelly_snapshots/` | 同上 |
| `lab` | upload-lab | `lab/` | 专向前缀 |
| `trade_sim` / `trade_sim_data` | upload-trade-sim / -json | `trade_sim/`, `trade_sim_data/` | 专向前缀 |
| `index` | upload-index | `index/` | 专向前缀 |
| `etf` | upload-etf-hist | `etf/` | 专向前缀 |
| `fund_nav` | upload-fund-nav | `nav_bucket/` | 专向前缀 |
| `accum_nav` | upload-accum-nav | `accum_nav/` | 专向前缀 |
| `industry` | upload-industry | `industry/` | 专向前缀 |
| `public_fund` | upload-public-fund | `public_fund/` | 专向前缀 |
| `offshore_fund` | upload-offshore-fund | `offshore_fund/` | 专向前缀 |
| `fund_score` | upload-fund-score | `fund_score/` | 专向前缀(data-large/all-data 排除 `fund_score*`) |
| `backup_db` / `large_json` / `claude_backup` / `decommissioned` | 私有桶备份命令 | `backup/`, `large-json/`, `claude-backup/`, `decommissioned/` | 私有桶前缀, 与公有桶互不相干 |
| `data`(小载荷例外) | upload-data-files 小锁通道 | 命中 `_is_data_large_file` 一律退回全局锁 | 2026-10-23 A 方案既有例外, 本单不改 |

> **为什么 `data` 不能拆细**: **大文件通道** data-large / all-data / intraday 在顶层 `data/*.json`
> 存在真实同 key 重叠, 拆开 = 两个任务同秒写同一 key(last-writer-wins), 比现状更糟 ⇒ 同域串行。
> **小载荷通道(8MB 以下)是例外**: 它走独立小锁、不吃全局屏障, 与 `data` 域仍是**跨锁**写同一个
> `data/schedule_stats.json`(`push_schedule_stats.sh:73`、`intraday_snapshot.sh:232` 的小锁写者
> vs `intraday_snapshot.sh:170` 的 `data` 域 upload-intraday)——**既有问题, 本单只登记不修**, 见 §2.1。

### 2.1 既有「同 key 但不同锁」例外(只登记, 本单不修)

分域只解决「域间 key 不重叠」这一层; 下面两处是**改前就存在**的跨锁同 key 写者, 分域既没新增
也没消除它们。登记在此供后续立项, 不做"顺手修"(任务书明令: 只登记)。

| # | 谁在跨锁写同一个 key | 触发条件 | 风险 | 建议 |
|---|---|---|---|---|
| E-1 | **小载荷通道**: `upload-data-files` 命中「非大文件判据 + 总量 ≤ 8MB」⇒ 走独立小锁 `/tmp/trade_r2_upload_small.lock`(不吃全局 SH 屏障)。写者: `push_schedule_stats.sh:73`、`intraday_snapshot.sh:232`; 同 key 的域锁写者: `intraday_snapshot.sh:170` 的 `R2_UPLOAD_LOCK_DOMAIN=data upload-intraday`(其文件表含 `schedule_stats.json`) | 小锁与小锁之间互斥, **小锁 vs `data` 域锁不互斥**; 8MB 阈值是静态判据, 不感知对手 | 极端时点两者同秒写 `data/schedule_stats.json` ⇒ last-writer-wins(内容都是同一份统计的不同时刻快照, 不会结构损坏, 但可能读到旧一版) | 立项: 给小载荷通道也加一把**与 data 域共享的 SH/EX 关系**(或把小锁并入 data 域的分段); 在合并前维持现状(改动面大于收益) |
| E-2 | **`upload` 子命令是锁豁免写者**: `upload_r2.py:4990` 的取锁门槛 `cmd not in {..., "upload"}` 把 `upload` 排除在锁外。调用方: `app/collector/intraday_snapshot.py:2185` 用它写 `data/sentiment-{rng}.json`, 与 `data` 域 upload-intraday 的文件表同 key | 盘中采集每轮都会跑到; 完全**无锁**并发 | 与 data 域写者同 key 且零互斥; 单文件 PUT 原子, 最坏是"新老两版互相覆盖"(内容同为 sentiment 序列, 不会损坏, 但可能短暂读到上一轮) | 立项: 把 `upload` 子命令并入 data 域(或至少让它持全局 SH 屏障)。**本单不动**: 它属"锁豁免"既有设计, 改动会影响 `--dry-run`/手动补刷语义, 需单独评估 |

> 两处都不是本次分域引入的**, 故 §5 的 E1/E2 观察口径不受影响; 但排障时若看到 `schedule_stats.json`
> 或 `sentiment-*.json` 出现"旧一版", **先怀疑 E-1/E-2**, 不要误判成域锁失效。

## 3. 锁结构(向后兼容模型)

- 声明域: 持 **域锁 EX**(`/tmp/trade_r2_upload_<domain>.lock`)+ **全局锁 SH 屏障**;
- 未声明域: 持 **全局锁 EX**(逐字保持 2026-10-27 行为);
- 全局 EX 与域 SH 互斥 ⇒ 漏改的调用方会挡住全部域写者(安全兜底), 不会与域写者并发;
- 小载荷通道(2026-10-23): 独立小锁, 不吃全局屏障(既有例外; 硬闸门 `_is_data_large_file` 只保证
  它与 **data-large** 同 key 不相交, 与 `data` 域的 upload-intraday **仍同写 `schedule_stats.json`**
  ⇒ 见 §2.1 E-1);
- 域名白名单(2026-10-28 返工): 合法域名的单一事实源 = `scripts/r2_lock_paths.py::LOCK_DOMAINS`
  (20 个)。`upload_r2.py`、排障探针 `r2_lock_probe.py`、审计脚本三者都 import 它, **不手抄第二份**;
  未登记域名 ⇒ 回落全局锁 + WARN(不是报错): 打错字只会退化成串行, 不会自建一把新锁静默失去互斥;
- fail-open(锁文件打不开)/ 等锁心跳 30s / 超时文案 / `SKIPPED_LOCKED` 哨兵语义 **全部不变**;
- 回滚: 不设 `R2_UPLOAD_LOCK_DOMAIN` 即回到全局单锁(无需回滚代码)。

## 4. 三列梯度表(锁等待 < 内层 < 外层; 由审计脚本机检)

| 调用方 | 域 | 锁等待上限 | 内层预算 | 外层 TimeoutStartSec |
|---|---|---|---|---|
| s06_snapshot.sh | data | 600 | 900(run_to) | 7020 |
| s06_snapshot.sh(④b) | kelly_snapshots | 600 | 900(run_to) | 7020 |
| turnover_backfill.sh(intraday) | data | 1800 | 2760(run_to; 内层工作预算 900) | 0(无界) |
| turnover_backfill.sh(data-large) | data | 1800 | 4980(run_to; 内层工作预算 3120) | 0(无界) |
| intraday_snapshot.sh | index / data | 600 | 无界 | 0 |
| update_lab.sh | lab / trade_sim_data / data | 600 | 无界 | 0 |
| gold_night.sh | data | 900 | 无界 | 2700 |
| etf_national_team_backfill.sh | etf | 900 | 无界 | 0 |
| fund_nav_upload_async.sh | fund_nav | 1800 | 无界 | 0 |
| pf_score_daily.sh | fund_score | 400 | 无界 | 600(云上实测 1800, 快照记 600 ⇒ 取保守值) |
| pf_score_weekly.sh | fund_score | 1800 | 无界 | 4140 |
| backup_db.sh | backup_db | 9000 | 无界 | 12600 |
| staticdata_backup_async.sh / migrate_large_json_out_of_git.sh | large_json | 3000 | 无界 | 0 |
| update_all.sh | data / etf_score / fund_score | 300 / 600 / 600 | 无界 | 0 |
| kelly_intraday_rerun.sh | data | 400 | 无界 | 600 |
| push_schedule_stats.sh | data | 120 | 无界 | 0 |
| backup_claude_self.sh | claude_backup | 900 | 无界 | 0(本机 cron) |
| fetch_news.py | data | 120 | 180(subprocess+skip 重试) | 1080 |
| gen_daily_brief.py | data | 80 | 120 | 1740 |
| nextday_plan_generator.py | data | 320 | 480 | 600 |
| nextday_gap_check.py | data | 200 | 300 | 1800 |
| overfit_monitor.py | data | 240 | 960 | 360(**既有倒置 #223④, 已豁免**) |
| fapi_bj_width_export.py | data | 600 | 900 | 1800 |
| r2_upload_async.sh 全部通道 | 各域 | 600(verify 6000) | 7200(停滞/硬兜底) | - (systemd-run 瞬时) |

> 内层「无界」= 该脚本对 upload_r2 子进程不设 timeout, 由外层/停滞判据兜底; 审计脚本对此类
> 只校验「显式声明了锁等待上限」, 不强行编造内层预算。
>
> **turnover 两行口径不同(2026-10-30 #364 二版注明)**: 这两行的「内层预算」列填的是**外层 shell
> `run_to` 墙字面量**(2760 / 4980), 不是其他行的「upload_r2 进程内工作预算」——该 unit 的
> `TimeoutStartSec=0`(无界), 真正兜底的墙在 shell。真实内层工作预算由脚本常量
> `R2_WORK_BUDGET_INTRADAY=900` / `R2_WORK_BUDGET=3120` 经 env 注入, 写在括号里了。
> 梯度关系: 锁等待 1800 < 工作 900/3120 < 外层 2760/4980, 且外层 = 等锁 + 工作 + 60。
> 脚本运行时另有 `_r2_check_step` 自检真读 `run_to <N>` 字面量比对算式(抽不到/多个/倒挂/不等一律 FATAL),
> 与本表静态审计双保险; 改任一边漏另一边 → 自检红 + 本表对不上。

> **脚注: 小载荷通道的「域」列是名义值 —— 域名根本不生效(2026-10-28 核实, 共 14 处)。**
> `upload_r2.py::_acquire_lock_for_command`(L4942)先让 `_route_upload_lock` 判目标锁: 凡命令是
> `upload-data-files` 且「未命中大文件判据 + 文件总字节 ≤ 8MB」⇒ 返回小锁路径, 再以
> `lock_path_override=小锁` 取锁; 而 `_acquire_r2_upload_lock`(L4830)里 **override 分支优先于域**,
> 所以 env 里写的域名被**整条忽略**, 实际持的是 `/tmp/trade_r2_upload_small.lock`(所有小载荷共用、
> 彼此仍互斥, 但**不吃全局 SH 屏障**)。上表这些行里的 `data` 只是"如果它退回全局路径时会用哪个域",
> 当前实际不生效。涉及清单(实文核实, 每条都是 `upload-data-files`):
> - shell **9 处**: `s06_snapshot.sh:136`(kelly_mode_s06_state.json)、`update_lab.sh:328`(lab_*.json 4 个)、
>   `update_all.sh:220`(alert.json + alert_analyze_*.json)、`intraday_snapshot.sh:180`(signal_kelly_trades_intraday.json)、
>   `intraday_snapshot.sh:232`(schedule_stats.json)、`kelly_intraday_rerun.sh:174`(signal_kelly_trades_intraday.json +
>   signal_kelly_backtest_intraday.json)、`gold_night.sh:69`(global-3m/6m/1y.json)、
>   `push_schedule_stats.sh:73`(schedule_stats.json)、`r2_upload_async.sh:331`(upload-feed → feed.xml);
> - Python **5 处**: `fetch_news.py`、`gen_daily_brief.py`、`nextday_plan_generator.py`、
>   `nextday_gap_check.py`、`fapi_bj_width_export.py`。
>
> **例外(不在这 14 处里)**: `overfit_monitor.py` 用的是 `upload-data-large`(不是 data-files), 域锁照常生效;
> 任何一次 `upload-data-files` 若命中 `_is_data_large_file`(≥1MB / `-all|5y|3y.json` / `overfit_monitor*`
> 前缀)或文件总量 > 8MB, 也会退回全局/域路径 —— 那种情况下表里的域名才真正生效。当前实测这 14 处
> 涉及的文件最大 608KB(`kelly_mode_s06_state.json`), 都远低于 1MB 阈值 ⇒ 现在全部走小锁。
> 判定与阈值实文: `upload_r2.py:4630-4758`(路由) + `:2196-2213`(大文件判据/1MB 阈值)。
> 小锁与 data 域仍同 key 写 `schedule_stats.json` 的既有例外见 §2.1 E-1。

## 5. 验收锚点(E1/E2/E3)与观察口径

| 编号 | 目标 | 本单能自证到哪一步 | 上线后怎么验 |
|---|---|---|---|
| E1 | 等锁单条时长 P100 < 300s | 机制层: 最长锁等待上限从 7300 降到 ≤1800, s06=600; 域间并行已由单测证明 | 上线后 7 天 `grep '等待 R2 上传锁'` 取最大值 |
| E2 | S06 rc=124 不再由等锁引起 | s06 锁等待 600 < run_to 900; 单测钉死字面量 | 观察 s06 退出码与日志等锁秒数 |
| E3 | 锁等待 < 内层 < 外层 | `r2_lock_gradient_audit.py` PASS(**46 PASS / 1 既有豁免, 共 47 行**; 2026-10-30 #364 二版实跑值, 旧记 45/46 已随登记行增长过时) | 每次改调用方重跑审计 |

> **调用点计数口径(2026-10-28 二轮审查后按实文重算; 行数随后续新增登记增长, 2026-10-30 实跑 = 47 行)**:
> 当时审计表 `SITES` = **46 行**, 这是"登记
> 行数", 不等于"取锁调用次数"。按每个 `upload_r2.py` 真实取锁调用逐处展开 = **49 次**; 差额 3 =
> **三行各覆盖 2 处调用**(登记算 1 行, 运行时算 2 次):
> ① `turnover_backfill.sh` 一行写「intraday + data-large」, 实为 `:241` upload-intraday 与
>   `:245` upload-data-large 两次串行调用(同一 `if` 块内, 每次运行都各取一次锁);
> ② `gold_night.sh` 一行, 实为 `:65` upload-data-large + `:69` upload-data-files 两次;
> ③ `intraday_snapshot.sh` 的 data 域一行, 实为 `:170` upload-intraday + `:232`
>   upload-data-files(schedule_stats.json)两次。
> 其余计数方式: `r2_upload_async.sh` 17 行 = 17 个通道各 1 次; Python 6 个调用方各 1 次;
> `intraday_snapshot.sh` 的 index 行(`:157`)与 `:180`(signal_kelly_trades_intraday.json,
> 本次补登记)各 1 次; 其余 shell 行均 1 行 1 次(逐个 `grep -n 'upload_r2.py'` 核实)。
> **改前审计输出的"42 个调用点"是行数**; 二轮审查写的"45 行 / 46 次"只算了 intraday 一处合并行,
> 漏算 ①② 两个合并行 ⇒ 本次按实文逐处重数为 **46 行 / 49 次**。
> 复现方法(只读): 对 `scripts/*.sh` 跳过注释行与含「手动/补刷」的行、合并 `\` 续行后, 数含
> `upload_r2.py <上传子命令>` 的真调用行, 与 `python scripts/r2_lock_gradient_audit.py` 的合计
> 行数对照; 二者差额应等于"合并行覆盖的额外调用次数"(本机 = 3)。

> **观察口径补充(2026-10-28 二轮审查后; 只定口径, 本单不加监控代码)**:
> ① **超时诊断自身的耗时账要写「理论最坏 / 实测」两个数**: 等锁超时后 `r2_lock_probe.py` 会逐把探
> **22 把锁**(全局 + 小锁 + 20 把域锁), 每把 `lsof` 超时上限 5s(查到 pid 再加 `ps` 5s) ⇒ 理论最坏
> **22 × (5+5) = 220s**; 无占用时只跑 lsof ⇒ 上界 **110s**。而 `nextday_plan_generator` 内层 480s /
> 外层 600s 只余 **120s** ⇒ 探针若真按最坏跑, **诊断本身会把外层撞穿**(等于"为了报错把自己杀了")。
> 本机实测(2026-10-28, 22 把锁全部无占用): **0.638s**, 与理论最坏差三个数量级。上线后若出现
> "等锁超时之后外层又被杀", 第一嫌疑是探针吃满 lsof 超时(锁文件所在 fs 卡顿 / 被大量进程打开时
> 可复现), 不是域锁失效。
> ② **除等锁时长外, 还要按通道看墙钟时长 + 失败率**(防"等锁降了, 单通道变慢被看门狗杀"):
> 分域后跨域**真并行**, 多个通道会同时抢跨境带宽 ⇒ 单通道墙钟比改前**变长是设计预期, 不是故障**;
> 上线后 7 天按通道统计 ①`systemd` 运行时长 P50/P95 ②失败率(rc≠0 / rc=124 / `SKIPPED_LOCKED`
> 次数), 与改前 30 天基线逐通道对比。判据 = **等锁 P100 下降 且 无通道失败率显著上升**(尤其
> rc=124); 两者只满足一半时要看是谁在变慢, 不能只报"等锁变快了"就算达标。

## 5.1 审计的静态盲区(读结论前必看: 它不是全量机检)

`r2_lock_gradient_audit.py` 是**按字面量扫源码**的静态检查 —— **审计 PASS ≠ 所有调用方都被核对过**。
下面这些形态会逃过扫描(2026-10-28 用脚本自身的正则/函数逐条实测, 不是照抄审查结论); 新增或改写
调用点时仍要人眼过一遍。

| # | 盲区 | 为什么逃过(实文) | 本次实测 | 现实风险 |
|---|---|---|---|---|
| B-1a | shell 拼接写法 `R2_UPLOAD_LOCK_DOMAIN="etf""_score"` | 字面量正则 `_SHELL_DOMAIN_LITERAL` 要求域名后紧跟空白, 而拼接里域名后面是引号 | 字面量=无匹配、变量形式=否(对照: 正常写法匹配 `etf_score`) | **真实**: 拼接是合法 shell, 进程照样拿到 `etf_score` 域, 审计却看不见 |
| B-1b | `=` 前带空格 `R2_UPLOAD_LOCK_DOMAIN ="etf_score"` | 同一正则要求 `DOMAIN=` 紧邻 | 两条扫描均不匹配 | 仅理论: shell 里这不是赋值语句(会被当成命令名执行并报错), 生产脚本不会这么写(语法规则判定, 本机未实跑) |
| B-1c | 行尾无空白 `export R2_UPLOAD_LOCK_DOMAIN=etf_score` 后直接换行 | 该正则结尾要求 `\s` | 不匹配 | **真实**: 合法赋值, 算漏扫 |
| B-2a | Python 侧变量赋值 `env["R2_UPLOAD_LOCK_DOMAIN"] = domain` | `_PY_DOMAIN_LITERAL` 只认引号字面量 | 匹配=无 | **真实** |
| B-2b | Python 侧 `env.setdefault("R2_UPLOAD_LOCK_DOMAIN", "data")` | 同上(只认 `"] =` 赋值形式) | 匹配=无 | **真实** |
| B-3a | `.sh` 只扫**顶层**, `scripts/子目录/*.sh` 不扫 | `glob("*.sh")` 非递归 | 假 REPO 实测: 顶层命中、`sub/nested.sh` 不出现 | 真实(目前 scripts 下没有子目录 shell 脚本, 属未来风险) |
| B-3b | 含「手动」或「补刷」字样的行**整行跳过** | `_upload_callers()` 的 `if st.startswith("#") or "手动" in line or "补刷" in line: continue` | 假 REPO 实测: 同一行真调用 + 行尾 `# 手动补刷` ⇒ 该脚本不进"待登记"检查 | **真实**: 一条真调用只要同行带这两个词就整行失明 |
| B-4 | `r2_upload_async.sh` 新增通道漏写 `--lock-domain` | 覆盖检查是**脚本级**(脚本登记过任意一行就算覆盖); `--lock-domain` 缺省时 `${_lock_domain:+...}` 展开为空 ⇒ 不注入 env ⇒ 静默回落全局锁 | 假 REPO 实测: 同脚本两处调用(1 带域 1 不带)只返回脚本名一次 ⇒ 第 2 通道无人核对 | **真实**: 语义安全(回落全局=更保守)但**零告警**, 新增通道会悄悄失去并行收益 |

> 实测方式(只读): 用脚本自身的 `_SHELL_DOMAIN_LITERAL` / `_SHELL_DOMAIN_VARIABLE` /
> `_PY_DOMAIN_LITERAL` 对构造字符串跑 `findall/search`; B-3/B-4 用临时目录 + 临时把模块的
> `REPO` 指向假目录调真函数 `_upload_callers()`(用完还原)。结论与上表逐条一致。
> 回归期望: B-1a/B-1c/B-2a/B-2b/B-3b/B-4 属**已知未覆盖项**, 不要据此认为"审计绿就是全绿"。

## 6. 排障探针(超时后「谁占着锁」)

`scripts/r2_lock_probe.py::lock_paths_from_env(include_domains=True)` 返回 22 把锁(全局 + 小锁 +
20 把域锁), `probe_locks` 逐把 `lsof`;**无占用的域锁折叠成一行**(否则 20 行会把日志/告警正文冲垮),
有占用的逐条列出文件名 + 已运行时长。Python 调用方(`nextday_plan_generator` / `nextday_gap_check` /
`gen_daily_brief` / `fapi_bj_width_export`)调诊断时必须带 `include_domains=True`——只探全局/小锁会在
**域锁被占**时指向错误文件(2026-10-28 审查发现, 本单修)。机检: 审计脚本扫 `scripts/*.py` 的
`lock_paths_from_env(` 调用点, 缺 `include_domains=True` ⇒ FAIL。

## 7. 恢复/回滚

- 单任务回滚: 去掉该调用方的 `R2_UPLOAD_LOCK_DOMAIN` ⇒ 该任务回落全局锁(其他任务不受影响);
- 全局回滚: 所有调用方均不设域 ⇒ 等价 2026-10-27 全局单锁;
- 锁文件残留: 内核自动释放, 无需清理; `/tmp` 重启即清。