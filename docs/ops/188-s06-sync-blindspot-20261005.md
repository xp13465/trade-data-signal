# #188 s06 链路「同步段」检查侧三层盲区根治

- 任务：`docs/pending-features-index.md` #188（B 级；登记于 2026-10-05，来源＝s06 断供影响面调研）
- 分支：`feat/188-s06-sync-blindspot-20261005`（base `9b98d12b1`）
- 分级：B 级（跨 3 文件 3 处检查侧机制；不动已上线功能的业务行为口径，只补检查覆盖 + 告警路径）
- 关联：#162 / #161 / #175 / #177 / L45 / §22 / §24

## 0. 一句话结论

s06 断的是**同步/传播段**（gen 段每日成功、覆盖到 20260930 零缺行；**用户可见的 R2/CDN 副本停在 09-24 版**），
之所以**静默 6 天**，是**检查侧**的三层盲区——不是生成侧。本次把三处盲区全部根治：
①verify-r2 平日不再只靠周日兜底（新增「独立链产物」登记清单，自动覆盖 s06 及所有同类产物）；
②补传清单落**文件名**；③失败告警改 trap 驱动 + 在 deploy 侧另加一条**与 s06 链解耦**的外围告警。

## 1. 事故链（实测，来自 #188 登记时 researcher 独立实测）

| 段 | 状态 |
|---|---|
| gen（`gen_kelly_mode_s06_state.py`） | **每日成功**，快照覆盖到 20260930 零缺行 |
| check（`check_s06_state.py` A1-A6） | 当日跑过就 PASS（只看本地） |
| R2 上传（`upload_r2.py upload-data-files`，链内第③段） | **09-29/09-30 被 systemd 杀在 R2 段**，R2 副本停在 09-24 版 |
| 定时（云上 systemd `trade-s06-snapshot.timer`） | Mon..Fri 20:35，一直在跑 |

治愈时刻：**10-04 周日**错峰 deploy 的全量 verify-r2 补传（`deploy_20261004_2230.log:774`「自动补传 1 个」）。
云上旁证：`.r2_all_data_state.json` 的 `changed`（n=29）**不含 s06**，但 `files` 里有
`kelly_mode_s06_state.json`（md5 `c67db588b0768f2edfb28ce83c2fdfef`，= 云上本地 09-30 20:35 版）。
⇒ 根因：**s06 走的是 `upload-data-files`（脱离 deploy 通道状态文件的独立上传点），其 key 天然不在
verify-r2 平日对账的 `changed` 集合里**，平日只靠全池均匀抽样 100 撞运气。

## 2. 三层盲区（本次全部根治）

### 盲区① verify-r2 平日只对账 `changed` + 抽样，独立链产物「never 对账直到周日」
- 锚点：`upload_r2.py` `cmd_verify_r2` 平日分支（旧注释自认「存量缺口 never 对账直到周日」）。
- 修法：新增**独立链产物 key 登记清单** `data/.r2_standalone_keys.json`（去重 set，跨天持久、原子写）；
  `upload-data-files` 与 `upload-intraday`（同为走 `_upload_glob` 不写通道状态的独立上传点）每次上传成功后登记；
  verify-r2 平日**无条件**把清单内的 key 纳入对账对象（不受抽样上限截断）。
- 为什么用清单而不是硬编码 pin 列表：**自动覆盖当前 + 将来所有独立上传产物**（s06 / nextday_plan / daily_brief /
  intraday / schedule_stats / feed.xml …），后人新增独立上传点无需再改本处（§23.3 举一反三的机制化落地）。

### 盲区② 补传清单只打计数，查不出是谁
- 修法：`mismatches` 落**文件名串**（`_fmt_name_list`，>50 个截断并标注总数）；收尾行
  `✓ 对账完成, 自动补传 N 个; 涉及文件名: …`。

### 盲区③ 失败告警只在 happy path 末尾 ⇒ 链路被杀时「告警与链路同亡」
- 锚点：`s06_snapshot.sh` 旧 `notify` 只在末尾 `FINAL_RC != 0` 时才调，systemd 超时 SIGTERM 杀掉时**根本走不到**。
- 修法 a（链内）：改 **trap 驱动**——`EXIT`（非零）/ `TERM` / `INT` 任一触发都发同一条 `--severe` 告警，
  `_ALERTED` 幂等防双发；注册点在交易日闸门之后，非交易日 `exit 0` 路径保持无 trap 无告警。
- 修法 b（链外，**真正的兜底**）：verify-r2 侧新增独立链产物脱节告警（dedup key `verify_r2_standalone_stale`，
  窗口 6h）。verify-r2 由**与 s06 无进程依赖**的 deploy 链/独立 timer 驱动 ⇒ 即使 s06 链被杀，
  只要 10-09 的 deploy 发现 R2 副本脱节，就会发出「某条排期上传链已连续失败/被截断」的邮件。

### 命名盲区（deploy 的 s06 机检「本地新鲜短路只验本地」）
- 锚点：`check_data_integrity.py` `check_s06_state_snapshot` 分支①——本地快照新鲜就只跑
  `check_s06_state.py` 子进程验本地，**完全不看 R2 是否已同步** ⇒ 09-29~10-04 六天 deploy 全打
  「✓ s06_state PASS」**假绿**。
- 修法①b：本地新鲜时**追加一次 R2 `coverage_end` 比对**，不一致/取回失败 → **WARN（绝不 FAIL）**。
- **为什么只 WARN**：本函数在 `deploy.sh` 先于 R2 上传执行，FAIL 会 abort deploy ⇒ R2 永不上传 ⇒
  **死锁、不能自救**。WARN 让 deploy 输出可见 + 由 verify-r2 外围告警兜底。

## 3. 改动清单（3 文件 + 1 自验脚本）

| 文件 | 改动 |
|---|---|
| `scripts/upload_r2.py` | 新增 `_STANDALONE_KEYS_NAME` / `_LEDGER_*` / `_standalone_keys_path` / `_record_standalone_keys` / `_load_standalone_keys` / `_fmt_name_list` / `_channel_files` / `_channel_key` / `_reconcilable_keys_for`；`cmd_upload_data_files` 与 `cmd_upload_intraday` 上传成功后登记 key（**死键过滤**）；`cmd_verify_r2` 平日分支纳入独立链产物 + 落文件名 + 新增 `verify_r2_standalone_stale` 与 `verify_r2_standalone_ledger_gap` 两条告警 |
| `scripts/s06_snapshot.sh` | 告警改 trap 驱动（`fire_alert` + `EXIT`/`TERM`/`INT`，幂等），删除末尾重复的 notify 块 |
| `scripts/check_data_integrity.py` | `check_s06_state_snapshot` 本地新鲜分支追加 R2 `coverage_end` 比对（WARN 级）+ docstring 同步 |
| `scripts/test_188_s06_sync_blindspot.py` | 自验脚本（打桩，不触网不写生产桶），**30 断言**（含复审修复轮的 P2-2 死键过滤 / P2-1 台账状态 / P3-2 并发写） |

无删除动作（§25 不适用：本次未删任何文件/数据，无需备份与恢复路径）。

## 4. 同类错误面清单（修 bug 三铁律「排查同类」，逐个给结论）

三个模式在仓内穷举 grep：

### 模式 P1「平日只靠周日兜底」
- 命中：`upload_r2.py:cmd_verify_r2`（平日增量 vs 周日全量）→ **本次已修**（独立链产物纳入平日）。
- `_incremental_upload` / `cmd_upload_all_data` 的 `today_weekday == 6 → force_full`：属**上传侧**的周自愈，
  与「检查侧对账」不同层；检查侧唯一对账点（verify-r2）已覆盖 ⇒ **不改**（保留双保险）。
- `r2_upload_async.sh`：只是 verify-r2 的定时外壳 ⇒ 随本改自动受益。
- **结论**：检查层单点已根治，上传层保留周全量自愈（设计内）。

### 模式 P2「本地新鲜短路掩盖远端用户可见副本」
- 命中：`check_data_integrity.check_s06_state_snapshot` → **本次已修（①b）**。
- `check_s06_freshness.py`（云上 15min monitor）：只比**本地** `coverage_end` vs `index/csi1000-all.json`，
  同样看不见 R2 ⇒ **同类残留**；但其定位是「本地新鲜度 monitor」不是「用户可见副本校验」，
  且其缺口已被 ①b + verify-r2 外围告警覆盖 ⇒ **本次不改**（避免扩大改动面），**列入同面待办上报**。
- 其余 `check_data_integrity` 检查项（overview/alert/notifications/fund_score…）读本地但走 deploy 通道状态，
  R2 侧由 verify-r2 `changed` 覆盖；`nextday_plan`/`auto_trade_steps`/`signal_kelly_day_snapshot`
  本就 `_fetch_r2_json` 查线上 ⇒ **无同面缺口**。

### 模式 P3「单点告警与链路同亡（notify 只在 happy path，无 trap）」
- 全仓扫描：**带 `notify.py` 的 .sh 共 29 个，只有 2 个有 trap**（`s06_snapshot.sh` 本次新增、`verify_backup.sh` 原有）。
- 收窄到「**真被杀面**＝链内有 `timeout`/`run_to`/alarm 包装（可能被杀）且 notify 无 trap」：
  `backfill_metrics.sh` / `check_data_gap_alerts.sh` / `check_r2_consistency.sh` / `kelly_intraday_rerun.sh` /
  `schedule_monitor.sh` / `staticdata_backup_async.sh` / `staticdata_sync.sh` / `turnover_backfill.sh`。
- **逐个结论**：以上 8 个均**注册在 `schedule_monitor.sh` 的漏跑/时长双通道**（`DUR_THRESHOLDS` +
  in-progress/missed-run）或自带 watchdog ⇒ 有外层兜底，**风险显著低于 s06**（s06 是「长链 + 独立上传 +
  外层只看本地」三重叠加才成灾）。**本次不改**（避免在无证据下批量扩面），**列入同面待办上报主控**
  （建议：日后任一链的 notify 路径改动时，顺手加 trap，或统一抽一个 `alert_on_kill` 公共包装）。
- **结论**：s06 三处全修；其余同面项已穷举、逐条判风险、留待办，不在本任务静默扩面。

## 5. 举一反三（§23.3）

### 5.1 同模式 / 同组件还被谁用
- **`upload-data-files` 的调用点**（本改动的登记半边覆盖**其中「产物落在 `data/` 顶层且能被
  `all-data`/`data-large` 非递归 glob 扫到」的部分**）：
  `s06_snapshot.sh`（s06 快照）/ `nextday_plan_generator.py`（次日买入计划）/ `gen_daily_brief.py`
  与 `fetch_news.py`（AI 预测 + 新闻顶层 `news_digest.json`）/ `intraday_snapshot.sh`
  （`schedule_stats.json` + `signal_kelly_trades_intraday.json`）/ `kelly_intraday_rerun.sh` /
  `push_schedule_stats.sh`。
  ⚠️ **不再声称「覆盖全部调用点/产物」**——按实测收窄，例外见 §12.4「已知边界」
  （`feed.xml`、`news_digest/<YYYY>/<date>.json`、`news_digest/_index.json` 属登记侧不可对账，
  已由死键过滤排除，不由本清单覆盖）。
- **`upload-intraday`**（同为 stateless 直传 `data/` 前缀）→ 已在本改中一并登记。
- **不在覆盖内的同面（同机制但不同前缀，verify-r2 无对应通道）**：
  `upload-offshore_fund`（`offshore_fund/` 前缀，定时链已停用）/ `upload-fund-score`（`fund_score/` 前缀）
  ——这两个 r2 前缀**根本没进 `_R2_CHANNELS`**，即**连周日全量都不对账**（既有设计缺口，非本次引入）⇒
  **列入同面待办上报**（登记它们进清单当前无效，需另开任务补通道）。

### 5.2 相关展示位（§22 多展示位一致性）
- 用户可见 s06 副本的**所有出口**：R2 `data/kelly_mode_s06_state.json`（CF Workers 反代）
  → `ss.fx8.store` / `sss.sugas.site` / `s.sugas.site`；以及 git/CF Pages 渠道（随次日 17:50 deploy 追上）。
- 本次修的是「**R2 出口与本地脱节无人知**」；修后：s06 链自己传（+登记）、平日 verify-r2 对账、
  deploy 机检 ①b 提示、脱节时外围告警 —— **四条独立路径同时指向同一事实**（§22「一旦更新 N 处一起同步」）。
- 首页 K 档评级 `latest_posrating.json`（同链④段，走 `upload-kelly-snapshots`，**有**通道状态 ⇒ 本就在平日对账内）：
  该段无缺口，无需改。

## 6. 规范逐条自检

| 条 | 结论 |
|---|---|
| §21 算法公示同步 | **N/A**：未改任何算法/评分/权重/分段/匹配逻辑（`track_score`/TE/R²/IR/百分位等均未动），不需同步 `purpose-notes.js`/`app.js`/`lab.js` 公示 |
| §23.1 README | **N/A**：未引用外部开源项目、无重大功能发布（纯检查侧 bug 修复） |
| §5.4 测试基准 | **N/A**：非回测/测试口径改动，未动 AI 推荐/降亏过滤默认组合 |
| §23.7 版本冻结 | 只**新增**检查覆盖面与告警路径，不改已上线功能的业务行为/口径/数字；①b 刻意用 WARN 以免改 deploy 成败语义 |
| §23.4 同模块冲突 | 已查：全仓仅 `feat/191-cloud-unit-patrol-20261005` 在跑（改 unit 文档，不碰本任务 3 文件）；无同模块并发 |
| §23.5 四件套 | 本体（本文）+ 自验脚本（`scripts/test_188_s06_sync_blindspot.py`）+ 复现段（§8）+ 配套 commit |
| §25 备份后删 | 无删除动作 |
| §11 进度文件 | `/tmp/agent-progress-188.md` |
| 云上改动 | **无**（本次未 ssh 云上改文件；云上 `s06_snapshot.sh` 待 merge 后 git pull 生效） |

## 7. 自验结果（逐条，`python3 scripts/test_188_s06_sync_blindspot.py` → ALL_PASS，共 **30** 条 PASS）

```
[A] 独立链产物 key 台账
  PASS  台账路径 = REPO/data/.r2_standalone_keys.json
  PASS  缺失台账 → 空集 + state=missing
  PASS  去重合并(二次登记不重复) + state=ok
  PASS  落盘 = 排序后的去重集合
  PASS  损坏台账 → 空集 + state=corrupt(不抛)
  PASS  空 list 台账 → 空集 + state=missing
  PASS  flock 锁文件已创建(P3-2)
  PASS  原子写无 .tmp 残留
  PASS  6 进程并发登记 30 键无丢更新(实际 33 键)
[A/B] verify-r2 平日选中独立链产物 + 落文件名 + 外围告警
  PASS  changed 为空时, 台账内 key 仍被平日对账选中
  PASS  台账内全部键均被平日对账逐个 HEAD(零遗漏 — 无「永远对不上」的死键)
  PASS  正例: 脱节 → 补传该文件
  PASS  正例: 脱节 → 发外围告警(verify_r2_standalone_stale)
  PASS  (反例轮)changed 为空时, 台账内 key 仍被平日对账选中
  PASS  (反例轮)台账内全部键均被平日对账逐个 HEAD
  PASS  反例: R2 一致 → 无补传、无告警
[C] s06_snapshot.sh trap 驱动告警
  PASS  EXIT 非零 → 告警恰好 1 次(reason=EXIT rc=1)
  PASS  SIGTERM → 告警恰好 1 次(幂等, 不双发)且 exit 143
  PASS  happy path → 无告警, exit 0
[D] check_data_integrity ①b 本地新鲜时追 R2 coverage_end 比对(只 WARN)
  PASS  R2 coverage_end 一致 → OK
  PASS  R2 落后 → WARN(不 FAIL, 防 deploy 死锁)
  PASS  R2 取回失败 → WARN
  PASS  R2 结构异常 → WARN
[E] P2-2 死键过滤
  PASS  全死键登记 → 台账仍为空(零死键)
  PASS  混合登记 → 只留可对账键(实际=['data/overview.json'])
  PASS  混合登记后 state=ok
  PASS  死键确为扫描不可达(过滤非空转)
  PASS  台账内每个键都在扫描可达集内(零死键)
[F] P2-1 台账缺失/损坏 → verify-r2 显式告警(不静默绿)
  PASS  台账缺失 → 发 dedup 告警(verify_r2_standalone_ledger_gap)
  PASS  台账损坏 → 同样发告警
```

> 断言数订正（§23.5 诚实标注）：首轮报告写「18 断言」为笔误，reviewer 实测 **17**，本轮补 13 条 → **30**。
> 首轮 17 条的明细见 §12.5 修复链（旧数保留可反查）。

外加：`bash -n scripts/s06_snapshot.sh scripts/deploy.sh` OK；`py_compile upload_r2.py / check_data_integrity.py / test_188…py` OK；
`pytest scripts/tests -q` = **192 passed / 1 skipped**（与基线一致，无回归）。

## 8. 复现段

```bash
# 自验脚本(从仓库根跑; 打桩, 不触网/不写生产桶/R2) → 期望末行 ALL_PASS(30 条 PASS)
python3 scripts/test_188_s06_sync_blindspot.py
# 语法
bash -n scripts/s06_snapshot.sh && bash -n scripts/deploy.sh
python3 -m py_compile scripts/upload_r2.py scripts/check_data_integrity.py scripts/test_188_s06_sync_blindspot.py
# 回归基线(pytest 需 trade-data venv)
/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest scripts/tests -q   # 192 passed / 1 skipped
# 死键过滤实测(只读; 仓库根跑, REPO 未设 → STATIC_DIR=<仓>/static-site, 用真实数据树验证)
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
import upload_r2 as u
cand = {"data/kelly_mode_s06_state.json", "data/overview.json",
        "data/news_digest/2026/2026-10-05.json", "data/news_digest/_index.json", "data/feed.xml"}
print("可对账(进台账):", sorted(u._reconcilable_keys_for(cand)))
print("死键(被过滤):", sorted(cand - u._reconcilable_keys_for(cand)))
PY
# 期望(2026-10-05 实测): 可对账=[s06, overview]; 死键=[feed.xml, news_digest/2026/…, news_digest/_index.json]
git diff --stat
```

### 8.1 复现段修复链（§5.4⑦ 精神）

- 首轮本段只写 3 条命令，**未含 pytest 回归与死键实测**；本轮补上（本段 8 行 4 类）。
- 首轮报告 §7 断言数 18 → 实测 17 → 本轮 30。旧数保留在本段与 §12.5，可反查。

## 12. 复审修复轮（2026-10-05，reviewer PASS 后 4 项先修再合）

> 触发：reviewer 独立复审（对象 `09338aa0f`）给 P0=0/P1=0、4 项须先修。以下为逐项处置 + 实测证据。

### 12.1 P2-2（🔴 死登记 + 潜在每日误报）— 修法①「登记语义与对账扫描语义对齐」

- **病**：旧 `_record_standalone_keys` 收所有上传过的 key，其中 `data/news_digest/<YYYY>/<date>.json`
  （子目录）与 `data/feed.xml`（非 `.json`）**永远不会出现在 verify-r2 的非递归 `*.json` glob 结果里**
  ⇒ 台账内成「死键」，平日**每天恒判缺失** → 重复补传 + `verify_r2_standalone_stale` 告警噪音 + 白涨 R2 调用。
  与本任务所修的「假信号」同族。
- **为什么选①不选②（让扫描递归）**：`all-data`/`data-large` 的 `local_dir = STATIC_DIR/data`，
  改成递归 `**/*.json` 会**吞掉** `nav_bucket`（2.6 万）、`etf`、`index`、`lab`、`trade_sim`、
  `accum_nav`、`signal_kelly_*` 等**所有**子目录 —— 与各专属通道**双传**、并把平日对账 key 数放大数万，
  爆炸半径远大于收益；且这些归档有独立的「下一轮 `fetch_news` 30min 自愈」兜底。故保持扫描侧非递归不变，
  在**登记侧**对齐语义。
- **实现**：抽出 `_channel_files()`（verify-r2 与登记**共用同一份** glob/exclude 语义；`cmd_verify_r2`
  内联收集已改调它，杜绝「两份口径各写一遍再分叉」）+ `_channel_key()` + `_reconcilable_keys_for(keys)`
  （只对前缀可能覆盖的通道做 glob，避免每 10min 登记都扫 fund-nav 2.6 万项）；
  `_record_standalone_keys` 登记前 `keys &= reconcilable`，被剔除的键打 stderr 显式清单（不静默）。
- **实测证据（E 用例 + 真实数据树）**：

| 候选 key | 类型 | 进台账? |
|---|---|---|
| `data/kelly_mode_s06_state.json` | 顶层 .json，all-data 可扫 | ✅ 进 |
| `data/overview.json` / `data/schedule_stats.json` | 顶层 .json | ✅ 进 |
| `data/news_digest/2026/2026-10-05.json` | 子目录键（非递归 glob 扫不到） | ❌ 过滤 |
| `data/news_digest/_index.json` | 子目录键 | ❌ 过滤 |
| `data/feed.xml` | 非 `.json`（另有 `cmd_verify_channels` 的 `upload-feed` 轻量校验覆盖，见 §12.4） | ❌ 过滤 |

  真实数据树实测（主检出 `trade/static-site/data`，只读探针）：顶层 `*.json` = **178** 个、
  `news_digest/` 下实际 **31** 个 json（含 1 个迁移期扁平键）、`feed.xml` 存在；
  探针输出 `可对账(进台账): [s06, overview, schedule_stats]` / `死键(被过滤): [feed.xml, news_digest/2026/…, news_digest/_index.json]`。
  ⇒ **修复后台账内零死键**，且 E 用例断言「台账内每个键都在 `_reconcilable_keys_for` 可达集内」+
  「反证：死键集与可达集交集为空（过滤非空转）」；verify-r2 侧另断言「台账内全部键均被平日对账逐个 HEAD（零遗漏）」。

### 12.2 P2-1（台账缺失/为空 = 静默退化为空集）— 显式处置三件

- `_load_standalone_keys()` 改为返回 `(keys, state)`，`state ∈ {ok, missing, corrupt}`；**非 ok 一律打
  stderr 显式告警**（含路径与后果说明），不再静默返回空集。
- `cmd_verify_r2` 平日侧新增 dedup 告警 `verify_r2_standalone_ledger_gap`（窗口 **86400s/24h**），
  正文写明「本次对账退回旧行为（仅抽样 + 周日全量）」「数小时内自愈」「若为首次冷启动可忽略」。
- 空 `list` 与文件缺失同归 `missing`（均为「无可对账对象」）；损坏/结构异常归 `corrupt`。
- 实测：F 用例断言缺失→告警、损坏→告警；A 用例断言 `missing`/`corrupt`/空 list 三种状态均正确上报（且不抛）。
- 边界（**已接受**）：冷启动当天会命中一次该告警（正文已注明可忽略）；周日全量模式不读台账故不发此告警（周日本就全量覆盖，无需它）。

### 12.3 P3-2（台账无锁，极端 merge 窗口丢更新）— 加锁（成本低，直接加）

- `_record_standalone_keys` 的读-改-写用 `fcntl.flock(LOCK_EX)`（锁文件 `….json.lock`）串行化跨进程写
  （intraday 每 10min / deploy / s06 主链都会写同一份台账）。原子写 `os.replace` 保留。
- 实测：A 用例真起 **6 个进程 × 5 个互异键** 并发登记 → 台账得 **33** 键无丢更新（3 原有 + 30 并发）。

### 12.4 已知边界（本轮新增；收窄首轮「覆盖全部调用点/产物」的过宽表述）

1. **`data/feed.xml`**：不经 `all-data` glob（非 `.json`），**不在本清单覆盖内**；其覆盖由
   `cmd_verify_channels` 的 `upload-feed` 特例（`_light_check_single_file("data/feed.xml", …)`）承担，
   deploy 链上有既有校验 ⇒ **无覆盖缺口**。
2. **`data/news_digest/<YYYY>/<date>.json`（31 个）+ `data/news_digest/_index.json`**：非递归 glob 扫不到，
   **当前无任何 verify-r2 通道覆盖**（既有设计缺口，被本清单明确排除以免制造假信号）；其缺口靠
   `fetch_news.py` 的「下一轮 30min 重试」自愈。若要纳入 verify-r2，需**另开一个专属通道**
   （`local_dir=STATIC_DIR/data/news_digest`、`patterns=["*.json","*/*.json"]`、`r2_prefix="data/news_digest"`）
   —— 属新增行为面，列入 §10 同面待办。
3. **登记侧的「可对账」判定是快照式**：以登记那一刻的文件集为准。若某产物**当天上传成功后即被删除**，
   它会留在台账里但下次登记不再被复核 —— 由于 verify-r2 侧只对**本地实际存在**的文件做匹配
   （`standalone_files` 从 `files` 里筛），不存在的清单键不会造成「恒判缺失」假信号（最多是台账略胖）。
4. **`data/.r2_standalone_keys.json` 的存放**：位于 `REPO/data/`（与 `.r2_*_state.json` 同目录，untracked）；
   `deploy.sh` 段1 的 `rsync -a`（**无 `--delete`**，排除列表仅 `logs/ notify_dedup.json alert_state.json`）
   会把它在两棵树间传递，**不会随部署被清**。

### 12.5 首轮 17 条断言 → 本轮 30 条的对应

- 首轮 17 = A 5 + A/B 正例 3 + A/B 反例 2 + C 3 + D 4（旧报告「18」为笔误，见 §7 订正块）。
- 本轮新增 13 = A 台账状态 3（missing/corrupt/空 list）+ A P3-2 3（锁文件/无 tmp/并发）+ A/B 零死键 2
  （全部键被 HEAD，正/反例各 1）+ E 5（死键过滤）。首轮 17 条**全部保留且仍 PASS**。

## 9. 真考验点：2026-10-08（首个交易日）验证步骤

> 10-05~10-07 为国庆非交易日，链会被交易日闸门跳过（不产生新数据），故真考验点在 **2026-10-08 20:35 首跑**。

**正向（期望「正常跑 + 新机制可见」）** —— 10-08 21:05 之后，云上：

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 '
  echo "== 1) 链是否跑完、有无告警 =="
  tail -25 ~/code/trade-data/data/logs/s06_snapshot_launchd.log | grep -E "开始|结束|✗|⚠|异常"
  echo "== 2) 独立链产物清单是否登记了 s06 =="
  cat ~/code/trade-data/data/.r2_standalone_keys.json
  echo "== 3) R2 副本 coverage_end 是否 = 本地(用户可见副本是否跟上) =="
  ls -l --time-style=+%F_%T ~/code/trade-data/static-site/data/kelly_mode_s06_state.json
  curl -s https://ss.fx8.store/data/kelly_mode_s06_state.json | head -c 200
'
```
期望：①出现 `=== s06_snapshot.sh 结束 … 退出码=0 ===` 且无 `[S06] … 异常` 告警；②JSON 数组含
`"data/kelly_mode_s06_state.json"`（及 `overview.json` 等 intraday 产物），且**不含**任何
`data/news_digest/…` / `data/feed.xml` 死键（P2-2 过滤生效的现场判据）；③**线上 `coverage_end` = 本地最新**
（**关键判据是"两者一致"，不是某个绝对值**；按链内 `--allow-lag-days 1` 口径，10-08 生成的 coverage_end
通常为 T-1=20261007）。

**保单日（P2-1）现场判据** —— 10-08 21:05 的 s06 日志/deploy 日志中**不应**出现
`独立链产物 key 台账不存在/损坏/为空`；若出现且次日仍出现，说明台账被清/权限异常（本体告警见下条）。

**反向（期望「若同步段再被杀，这次一定有人知道」）** —— 两条，任选：

```bash
# 反向 A(推荐, 只读式, 直接跑自验脚本的"脱节→补传+外围告警"路径)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'cd ~/code/trade-data-signal && git pull -q && python3 scripts/test_188_s06_sync_blindspot.py'
#   期望末行 ALL_PASS(30 条 PASS) —— 其中"正例: 脱节 → 补传该文件 + 发外围告警"即反向路径的行为证明;
#   "[E] 死键过滤 / [F] 台账缺失告警"两组即 P2-2/P2-1 的行为证明

# 反向 B(真实故障下的观测点, 无需注入):
#   若 10-08 的 s06 链**再次**被 systemd 杀在 R2 段, 则
#   (a) 你应收到 reason 含 "SIGTERM(被 systemd 超时/stop 杀)" 的 [S06] 告警(修法③a);
#   (b) 10-09 17:50 deploy 的 verify-r2 平日日志会出现:
#       grep -nE "独立链产物|verify_r2_standalone_stale|对账完成" <10-09 deploy 日志>
#       且邮件收到 "[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)" (修法③b 的外围兜底)
#   —— 若 (a)(b) 都没出现而 R2 又停了, 说明本设计仍漏, 立即回报。
```

**对照（本次修复的"旧行为"长什么样，供 reviewer 反查）**：修复前 09-29~10-04 六天里，
s06 链日报「退出码=143」但**无任何 [S06] 告警**（走不到末尾 notify），
deploy 全部打印 `✓ s06_state PASS`（本地新鲜短路），R2 副本停在 09-24 版直到 10-04 周日全量补。

## 10. 同面待办（上报主控，不阻塞本次 merge）

1. **`check_s06_freshness.py` 只看本地**（模式 P2 残留）：建议后续加 R2 `coverage_end` 比对或直接复用
   `check_data_integrity` ①b；当前缺口已由 ①b + verify-r2 外围告警覆盖，故未改。
2. **`upload-offshore_fund` / `upload-fund-score` 两个 r2 前缀未进 `_R2_CHANNELS`**：
   verify-r2 **连周日全量都不对账**这两个前缀（既有设计缺口）；登记进独立链产物清单当前无效（无对应通道），
   需另开任务补 `_R2_CHANNELS` 条目。
3. **模式 P3 的 8 个「真被杀面」脚本**（见 §4）：均有 `schedule_monitor` 外层或自带 watchdog，
   风险低于 s06；建议日后统一抽 `alert_on_kill` 公共包装（或任一链 notify 改动时顺手加 trap）。
4. **#188 索引行状态列**待 merge 后由主控改为「已合 main + merge hash」（本任务在 worktree 内，
   未改 `docs/pending-features-index.md` 以免与 #191 支线并发编辑冲突）。
5. **`data/news_digest/` 归档（31 个 key + `_index.json`）无任何 verify-r2 通道覆盖**（§12.4 边界 2）：
   本轮为消除死键误报，把登记侧与扫描侧对齐（不收不可对账键）；若要**真正**把该归档纳入平日对账，
   需新开一个专属通道（`local_dir=STATIC_DIR/data/news_digest`、`patterns=["*.json","*/*.json"]`、
   `r2_prefix="data/news_digest"`）—— 属新增行为面（平日对账 key 数 +32、新增一个通道条目），
   建议独立评估后做，不夹带进本次修复。缺口当前由 `fetch_news.py` 30min 自愈兜。

## 11. 落档四件套（§23.5）

| 件 | 位置 |
|---|---|
| 报告本体 | 本文 `docs/ops/188-s06-sync-blindspot-20261005.md` |
| 生成/自验脚本 | `scripts/test_188_s06_sync_blindspot.py` |
| 复现段 | §8 |
| 配套 commit | 见本分支末次 commit（`feat/188-s06-sync-blindspot-20261005`） |