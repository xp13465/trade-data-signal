# deploy fund_nav 自愈（C1）+ 校验第三口径治假绿（C2）—— 实施报告

- 日期: 2026-10-13
- 分支: `feat/deploy-fundnav-selfheal`（worktree 隔离）
- 根因报告: `docs/ops/stale-navbucket-rootcause-20261013.md`
- 用户拍板: **保留「fund_nav 一项 FAIL 阻断全站 deploy」的语义不变**, 只加自愈让阻断少触发
  （另一条路「按产物隔离/降级为不阻断」被否）。
- 复现/自测脚本: `scripts/tests/repro_fundnav_selfheal_20261013.sh`（人工跑, 端到端, 真 export + 真校验）
  + `scripts/tests/test_fundnav_selfheal_dbday_20261013.py`（进 CI 门禁 ⑧, 全桩化, 16 例）

---

## 1. 改了什么（文件:行号）

### C1 —— 自愈（`scripts/fund_nav_selfheal.sh` 新建 + `scripts/deploy.sh` 接入）
| 位置 | 内容 |
|---|---|
| `scripts/fund_nav_selfheal.sh`（新, ~190 行） | 自愈大脑。退出码: `0`=已重出（调用方须重跑校验）/ `10`=未命中 / `11`=17:50 窗口跳过 / `12`=重出失败或超时 / `13`=dry-run / `2`=探针或环境异常 |
| `scripts/deploy.sh:327-350`（新块, 在 L352 原终止块**之前**） | `if [ "$CHECK_RC" -ne 0 ]` → 调自愈 → 按退出码分支: `0` 则**重跑** `check_data_integrity.py --deploy-mode` 并**复用 `CHECK_RC`**; 其余码原样落回下方的原终止逻辑 |
| `scripts/deploy.sh:352-357`（**未改动**） | 原「终止部署（4 类事故拦截）+ `--severe` 告警（dedup-key `deploy_check_data_integrity_fail`）」一字未动 ⇒ 重跑仍 FAIL 时行为与改动前完全一致 |

自愈内部四步（严格按硬约束）:
1. **窗口闸**（约束②）: `NOW` 落在 `[1725,1835]`（`FUNDNAV_SELFHEAL_SKIP_BEGIN/END`）→ `exit 11`。
   依据: update_all 17:50 链**自己**在 deploy 之前已全量重出产物（`update_all.sh` L101-107 先 export 再
   L152 deploy）, 此刻重出 = 重复全量 + 与链内 export/异步上传撞 IO（§14）; 且若刚重出仍 FAIL,
   属「DB 破损」而非「DB 领先产物」, 重出救不了。窗口宽取 17:25-18:35（链内 export ~2min + deploy +
   异步上传全程 <40min, 留梯度）。
2. **方向探针**（约束④）: 只认「DB 领先产物」（`--fundnav-stale-probe` rc=3）。**反方向绝不重出** ——
   产物比 DB 新（DB 被损坏/回退）时重出 = 用坏数据覆盖好数据, 把真故障洗成 PASS（掩盖而非自愈）。
3. **有界重出**（约束③）: `with_lock.py --block-timeout 300 <lock> export_fund_nav.py`（约束②: 复用
   既有进程互斥）, 单次墙钟超时 `FUNDNAV_SELFHEAL_TIMEOUT`（默认 900s）, **最多 1 次不重试**。
4. **收尾**: 复核探针（仅日志, 不改退出码 —— 真值由调用方重跑完整校验定夺）→ 仅同步/重传
   **nav_bucket**（`rsync` 单子目录 + 复用既有 `fund_nav_upload_async.sh` 异步重传 R2）（约束④: 最小爆炸半径）。

止血开关: `FUNDNAV_SELFHEAL_DISABLE=1` ⇒ 等价「未命中」(`exit 10`), 行为回到改动前, 无需回滚代码。

### C2 —— 第三口径（`scripts/check_data_integrity.py`）
| 位置 | 内容 |
|---|---|
| `check_data_integrity.py:1242-1251` | 阈值常量 + 依据注释: `FUND_NAV_DBDAY_WINDOW_DAYS=30`（≈20 交易日; `PK(date,fund_code)` 使 `WHERE date>=?` 走范围扫描, 实测云上量级 ~1s）/ `FUND_NAV_DBDAY_MIN_ROWS=1000`（整日写入 ~24000 行, 留两个数量级余量）/ `FUND_NAV_DBDAY_RECENT_N=3` |
| `check_data_integrity.py:1254-1301` `_fund_nav_db_day_coverage(db)` | 新函数。SQL: 近 30 日按日 `COUNT(*)` + `SUM(unit_nav IS NOT NULL)`, 只取 `COUNT(*) >= 1000` 的「显著交易日」按日期降序前 3。规则: **最新显著日非空数 == 0 → FAIL**; 非最新显著日全 NULL → **WARN 不阻断**; 窗口内无显著日（长假/空库）→ 不判 |
| `check_data_integrity.py:1545-1550` | 在**同源比对之前**调用第三口径并优先返回 FAIL（顺序关键: 同源比对在 DB 破损时必然 PASS） |
| `check_data_integrity.py:1591-1593` | 尾部: `_dbday_warn` 存在 → `_warn`, 否则 `_ok` |
| `check_data_integrity.py:1202-1239` `_sample_fund_nav_mismatches(...)` | **抽出的同源单实现**, 供第 4 层与探针共用（§5.4⑦ 防「第二份实现」漂移: 前端/校验/自愈三处口径只此一处） |
| `check_data_integrity.py:1304-1342` `probe_fund_nav_db_ahead(data_dir)` | C1 探针: 抽样不一致且方向为 DB 领先（或产物为空）→ `3`; 其余（含 DB 落后方向、产物缺失、DB 找不到）→ `0` |
| `check_data_integrity.py:2456-2458, 2470-2474` | CLI `--fundnav-stale-probe`（三态退出码 `3/0`, 异常 `2`） |

**为什么只判 `unit_nav` 不判 `acc_nav`**: 10-08 `acc_nav` 全 NULL（22,085 行）属「无来源可补」的
已知残留（回填只有 unit/涨跌幅）; 纳入判定 = 永久阻断 deploy, 与「不再频繁触发」相悖。
⇒ **诚实标注: acc 维度仍是盲区**（登记见「遗留」）。

---

## 2. §23.2 修 bug 三铁律 —— 负控证据

自测两路: ①CI 桩化 `test_fundnav_selfheal_dbday_20261013.py`（16 例, 全绿）②端到端沙箱
`repro_fundnav_selfheal_20261013.sh`（真 `export_fund_nav.py` + 真 `check_fund_nav`, `ALLPASS`）。

### 2.1 C1 负控（构造 → 必触发; 不构造 → 必不触发）
| 场景 | 期望 | 实测 |
|---|---|---|
| 正常态（产物与 DB 同源一致） | 校验 `ok` + 探针 `rc=0`, **不重出** | ✅ `ok` / `rc=0`; pytest `C1` 另断言重出桩**未被调用**（`marker` 不存在） |
| 构造「DB 领先产物」（DB 加更近一日, 产物不重出） | 校验 `fail`「DB 领先产物 12 天」+ 探针 `rc=3` | ✅ 复现（`repro` 步骤 [2]） |
| 跑自愈 | `exit 0` → 产物重出 → 重跑校验转 `ok` | ✅ `exit 0` + `check-after: ok`（闭环, `repro` 步骤 [3]） |
| 反方向（DB 落后产物） | 探针 `rc=0`, **绝不重出** | ✅ pytest `B3`（重出=以坏覆盖好, 结构上不会发生） |
| 17:50 窗口内 | `exit 11`, 不探针不重出 | ✅ pytest `C0` |
| 总开关 | `exit 10`, 不重出 | ✅ pytest `C5b` |
| dry-run | `exit 13`, 不重出不上传 | ✅ pytest `C3` |
| 重出命令失败 | `exit 12` 且只尝试 1 次 | ✅ pytest `C4` |

### 2.2 C2 负控（整日全 NULL 必 FAIL; 正常态仍 PASS）
| 场景 | 期望 | 实测 |
|---|---|---|
| DB 最新显著日 `unit_nav` 整列 NULL（1200 行 ≥ 阈值 1000） | FAIL（修前为**假绿**） | ✅ `fail 最近显著交易日 20261012 unit_nav 全为 NULL(1200 行/非空 0) …`（`repro` 步骤 [4]） |
| **同一场景下同源侧信号** | `rc=0`（**无**领先信号） | ✅ 正是假绿机理的对照证据: 同源比对/探针都看不出问题, 唯第三口径拦下 |
| 正常态 | 仍 `ok` | ✅ `repro` 步骤 [1] + pytest `A2` |
| 非最新显著日全 NULL | `WARN` 不阻断（防不可恢复历史空洞永久阻断） | ✅ pytest `A3` |
| 零星行（< 阈值 1000, 如新基金无数据） | **不判定**（保住「新基金无数据」真判别维度） | ✅ pytest `A4` |
| DB 缺失分支 | 不得 NameError | ✅ pytest `A2/A3` 走 `db_codes` 分支; 初始化已前置（见 §4 过错 1） |

### 2.3 「本次自测零真实外发」证据（§18 L48）
- 自愈脚本源码**不含任何 notify 调用**（pytest `C5` 静态断言 `"notify" not in sh`）—— 告警仍只由
  `deploy.sh` 原告警链发。
- 自测/复现 env 一律带 `WITH_LOCK_NOTIFY_DRY_RUN=1`（`with_lock.py` 排队超时告警走 `--dry-run`）
  + `FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0`（零 R2）。
- 复现日志全文 grep `notify|feishu|飞书|smtp|resend|邮件` → **零命中**;
  `data/` 下 notify 相关文件 15min 内**无新 mtime**。
- 未跑 `bash scripts/deploy.sh`、未上传任何 R2 对象。

### 2.4 「未误写真树」证据
`repro_*.sh` 步骤 [0] 每跑必先打印并断言 `DB_PATH` / `STATIC_DATA_DIR`
（由真 `app.collector.public_fund` 导出）落在沙箱 `$SB/` 内, 否则 `exit 9`;
实测 `DB_PATH=/tmp/fundnav-repro-b/data/public_fund.db`、`STATIC_DATA_DIR=/tmp/fundnav-repro-b/static-site/data`。

### 2.5 回归
`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/` → **880 passed, 2 skipped**
（含 16 个新例）; `bash -n` 全部改动 shell 通过; `ast.parse` 通过。

---

## 3. §23.3 举一反三 —— 同类清单 + 逐项结论

对 `check_data_integrity.py` 注册表（`run_all_checks`）逐项过「两模式」:
**模式①=同源比对（源自身破损时假绿）**、**模式②=产物一天只重出一次且 deploy 内无自愈分支**。

| 项 | 模式① 同源假绿 | 模式② 无自愈窗口 | 结论 |
|---|---|---|---|
| `check_fund_nav`（点名项） | **有**（本次病因） | **有**（17:50 唯一重出） | **本次已修**（C1+C2） |
| `check_accum_nav_split_consistency` | 形式上同源（split vs 全量=同一次生成） | 无 | **不同类, 不动**: 该产物由 `deploy.sh:303` **每次 deploy 重出**（模式②不成立）; 且已知脏源（批量同价污染）另有独立口径 `check_accum_nav_map_price_sane` + `check_accum_nav_map_fresh` 兜（模式①已被异口径覆盖） |
| `check_track_score_map_vs_index` / `..._overview_vs_map` | 形式同源（map/快照/overview 同源导出） | 无 | **不同类, 不动**: 三者都由每次 deploy 的 `export.py` 重出; 且这是**跨文件一致性**设计（#29 本体正是「map 刷新、index 停旧」的合法分歧检测）, 源级破损由 `check_board_etf_map` 等异口径兜 |
| `check_boot`（boot.overview.date == overview.date） | 形式同源（boot 内嵌 overview） | 无 | **不同类, 不动**: `check_overview` 自带**独立**「date vs 今日」新鲜度口径, 陈旧必被它拦 |
| `check_etf_hist`（etf/ 全史日K） | **无**（docstring: 只查目录/文件数/抽样 date/结构, 无 DB 口径） | **有**（`export_etf_hist.py` 只在 20:07 `etf_national_team_backfill.sh` 跑, 一天一次） | **同类②但缺①** ⇒ 本次 fund_nav 的「校验 FAIL 阻断 deploy」不会在此发生; 其残余风险是**静默陈旧**（产物陈旧也 PASS）。**登记为遗留**（见下）, 本轮不动: 新增「DB↔产物日期」断言 = 新增一条阻断闸门（§23.7 冻结范畴 + 变爆炸半径）, 且与本任务「只碰 nav_bucket」约束冲突 |
| `check_fund_score` | **无**（只查 date/count/新鲜度） | **有**（`export_fund_score.py` 在 update_all 17:50） | **不同类**: 无 DB 同源口径 ⇒ 不会因「DB 领先」阻断; 陈旧由自身 date 新鲜度口径覆盖。不动 |
| `check_signal_kelly_backtest` / `_sdc` / `check_signal_kelly_day_snapshot` | **无** | — | 纯结构/产物完整性断言（含 schema/象限完整性）, 无 DB 同源比对。不同类, 不动 |
| `check_a_fund_north_quarterly` | **无** | — | 读 `sentiment.db` 直接判「最新季度行存在」, 是**单侧 DB 内容**校验（非产物↔DB 同源）。不同类, 不动 |
| `check_signal_accum_nav_lag` / `check_fapi_mutex` | **无**（相反: 是**跨源**互证） | — | 异源互证 = 天然免疫假绿（本次教训的正解形态）。不同类, 不动 |
| `check_overview` / `check_board_etf_map` / `check_export_manifest` / `check_nextday_plan` / `check_etf_since_return` / `check_trade_sim_indices` / `check_ad_line` / `check_notifications` / `check_alert` / `check_intraday_fresh` / `check_schedule_stats` / `check_sentiment_card_date` / `check_key_files` / `check_etf_index_map` / `check_kelly_loss_features` / `check_s06_state_snapshot` / `check_changelog_current_version` / `check_accum_nav_map_fresh` / `..._price_sane` | **无**（新鲜度/结构/存在性/异源, 无 DB↔产物同源比对） | 大多由每次 deploy 的 `export.py` 重出 | 均**不同类**, 逐项不动 |
| `check_data_gap_alerts.py`（占位残留闸门, deploy 另挂） | — | — | 独立脚本, 兼治「10-08 全 NULL」类破损（当晚即抓到）; 与 C2 互补而非重复。不动 |

**结论**: `check_fund_nav` 是**唯一**同时具备①②的项, 已修; 其余逐项给出「为何不同类」的理由,
无一项需在本轮同步改动。**唯一登记为遗留的是 `check_etf_hist`**（同②缺①, 风险=静默陈旧非误阻断）。

---

## 4. 本轮自测抓到的自身过错（诚实标注）

1. **作用域 bug（自查发现并修）**: `_dbday_warn` 原在 `if db_codes:` 块内赋值、却在函数尾部引用 ⇒
   DB 缺失分支会 `NameError`。修法: 在 `db = _find_public_fund_db()` 旁**前置** `_dbday_warn = None`。
2. **macOS bash 3.2 多字节吞变量名（真 bug, 被 pytest `C4` 逮到）**: `"rc=$REGEN_RC，上界…"` 里
   `，`（全角逗号）紧跟 `$VAR` ⇒ bash 3.2 把多字节尾巴吞进变量名, `set -u` 下报
   `REGEN_RC?: unbound variable`（`exit 12` 变成 `exit 1`）。修法: 4 处全改 `${VAR}`。
   同族机器检查: `grep -nP '\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]'` 已对自愈脚本/repro 脚本清零;
   `deploy.sh` 命中项全在**注释**中（代码路径零命中）。
3. **§18 L48 风险点（自测期规避）**: `with_lock.py --block-timeout` 超时会**真发** `notify.py`
   （`warning` 级）。自测全部 env 带 `WITH_LOCK_NOTIFY_DRY_RUN=1`, 且测试锁空闲不触发超时;
   生产路径保留真告警（正确行为）。

---

## 5. 最坏增量估算（约束③「不做无界 deploy 延长」）

只在**校验已 FAIL** 的路径上发生（常见 PASS 路径**零开销**）:

| 步 | 上界 | 依据 |
|---|---|---|
| 探针 | ~10s | 30 桶 × ~2MB json 解析 + 几条 SQLite 查询（近 30 日范围扫描） |
| 等锁 | ≤300s | `with_lock.py --block-timeout 300`（界内拿到则远小于此） |
| 重出 nav_bucket | ≤900s | `FUNDNAV_SELFHEAL_TIMEOUT`（真实现网实测: 10-12 17:50 全量重出 **~2min**） |
| 重跑完整校验 | ~60s | 256 桶全量 json.load ≈8s（docstring 实测）+ 其余项 |
| **合计上界** | **≈21min** | 且**只在 FAIL 分支**; 典型命中场景（锁空闲 + 重出 2min）≈ **+3~4min** |

无重试（上界 1 次）、无递归（自愈不触发自愈）、无新增定时任务、不改任何其它产物。

---

## 6. 恢复路径（怎么回到改动前）

1. **不改代码止血**（首选, 秒级）: 云上/本机给 deploy 的执行环境加 `FUNDNAV_SELFHEAL_DISABLE=1`
   ⇒ 自愈直接 `exit 10`, deploy 行为回到改动前（原终止 + 告警链一字未动）。
   适用: 怀疑自愈本身惹事、要立刻回到旧行为。
2. **改代码回滚**: `git revert <本 feat 的 merge commit>` 走 `scripts/main-merge.sh` 常规流程
   （禁 force）; 或只 revert `scripts/deploy.sh` 的 327-350 块（自愈脚本留着无副作用 —— 它只能被
   deploy 块调用, 不再是调用方即为死代码）。
3. **只关 R2 重传**: `FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0`（自愈照跑, 只是不重传 R2 —— 产物已在磁盘,
   `deploy.sh` 后续 rsync/上传会带上）。
4. **产物本身回滚**: 产物在磁盘 `static-site/data/nav_bucket/`, 重出是幂等重建（数据只增不减）;
   线上陈旧可直接重跑 `python scripts/export_fund_nav.py` + `bash scripts/fund_nav_upload_async.sh`
   （根因报告「修复方向 1」的手工法, 现已被自愈自动化）。

---

## 7. 遗留（本轮登记, 未动）

1. **`check_etf_hist` 缺「DB↔产物」口径**（同②缺①）⇒ 产物陈旧会静默 PASS。建议另立任务评估是否加
   「`etf_daily` 最新交易 vs 产物最大 date」断言（**新增阻断闸门, 须走 §23.7 冻结/拍板**, 不属本任务）。
2. **`acc_nav` 维度仍是盲区**（10-08 全 NULL 22,085 行无来源可补）—— 第三口径只判 `unit_nav`,
   纳入 acc 会永久阻断 deploy。
3. **payload 停在 09-28/09-29 的 995/748 只**（更早全 NULL 波的未复原者）。
4. **探针/自愈复用同一抽样函数** ⇒ 若并发实例在自愈重出**同时**写桶, 复核探针可能读到中间态;
   已用 `with_lock` 串行化 + 「复核只记日志, 生死由调用方完整校验定夺」兜住, 但**多实例并发 deploy**
   下的边界仍未做专项压测（登记, 观察）。
5. **本任务在 `docs/pending-features-index.md` 未查见对应编号条目**（`nav_bucket`/`fund_nav` 相关条目
   仅 #111 旧前缀清理 / #122 / #126, 均他事）—— 请主控按 §23.12-1 补编号 + 状态列。