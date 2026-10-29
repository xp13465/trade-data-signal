# 备份恢复演练补齐：public_fund 周频 + stock_daily 日频（#324 / #338）

2026-10-28（2026-10-29 评审续改：必修 1 + 建议 1/2/4）。改动面：**`scripts/verify_backup.sh`**（新增 `scripts/tests/test_255_backup_drill_20261028.py` 与本文件）+ `docs/backup-restore.md` 两处措辞同步。
`backup_db.sh`、`docs/scripts/restore_r2_db_backup.py`、保留期 / 桶名 / 凭据**零改动**。

## 1. 依据（云上只读实测，2026-10-28 22:44–22:58 CST）

调研全文见 `/tmp/backup-drill-plan-20261028.md`（只读调研，逐处 `文件:行`）。关键实测：

| 项 | 实测值 |
|---|---|
| R2 `backup/public_fund_` | 4 个对象：20261025=793,925,267 / 20261026=797,321,122 / 20261027=800,782,941 / **20261028=804,241,131 B** |
| R2 `weekly/public_fund_` + `monthly/public_fund_` | 2 + 1 个对象，1,587,971,839 + 790,650,717 B |
| public_fund 三前缀合计 | **5,574,893,017 B（5.19 GiB）** |
| 云上磁盘 `df -B1 /` | 63,290,032,128 总 / 47,632,244,736 用 / **12,957,040,640 可用（79%）**；`/tmp` 同文件系统 |
| `data/backups/` 占用 | 3.6 G |
| public_fund 库本体 | **2,965,819,392 B（2.76 GiB）**，page_count 724,077 / page_size 4096 / 19 表 / WAL |
| 最新 gz | 804,241,131 B（767 MiB，压缩比 27.1%）⇒ 演练峰值 **3.51 GiB**（gz 0.75 + 解压 2.76） |
| 出网费 | **0 元**（Cloudflare R2 不计 egress；一次演练 ≈ 30 个 Class B 操作） |
| 耗时（唯一实测点） | 6 线程 Range：790MB ≈ **2 分钟**；含参考快照全链 8.5 分钟（`docs/ops/pfdb-r2-backup-20261025.md:87`） |
| stock_daily | R2 三前缀 **0 对象**；库 185,421,824 B；3 表 364,742 / 249,956 / 565,700 行；代码已含 `backup_db.sh:82` ⇒ **第一份备份 2026-10-29 21:00** |
| 关键结构缺口 | `download-db` = 整对象 GET 进内存 + `gzip.decompress`（`upload_r2.py:3468,3476`）⇒ 2.76 GiB 在 3719MB RAM 上必 OOM ⇒ 大库必须走流式还原脚本 |

## 2. 改动逐条（改前 → 改后 + 行号）

以下行号均指改动后的 `scripts/verify_backup.sh`（**519 行**；评审续改后整体下移，已按现文件重核）。

1. **stock_daily 接进日频演练 + 存在性预判**
   - 改前：`download_backups()`（原 :54-67）只下 `sentiment`、`etf_national_team`。
   - 改后：新增 `r2_latest_backup_date()`（:86-114，调 `upload_r2` 库的 `_list_keys(bucket=BACKUP_BUCKET)` 判存在性，返回最新日期 / `NONE` / `ERR`）；`download_backups()`（:120-164）里（:139-161）先判存在性：
     - **踩坑记录（实施中发现，已避开）**：`upload_r2.py list` 子命令的默认桶是 `signal-data`（`upload_r2.py:5007`），拿它查 `backup/<name>_` 会永远"无对象" ⇒ **假 SKIP**；必须走库内 `BACKUP_BUCKET`（`signal-backup2` / 环境 `R2_BACKUP_BUCKET`）。
     - **ERR 判定**：`_list_keys` 在 LIST 失败时返回 `[]` 且只在 stdout 打「失败 status=（`upload_r2.py:2953`）」，所以捕获该打印把"看不见"和"没有"区分开（LIST 失败 ⇒ FAIL+告警，绝不静默 SKIP）。
     - `NONE` ⇒ **按日期分两态**（:147-156，评审必修 1）：`TODAY >= 20261030`（首备日 2026-10-29 21:00 之后）仍无任何 key ⇒ `STOCK_STATUS="FAIL(无 stock_daily 备份,已过首备日)"` + ✗ 日志，**进结论行点名 ⇒ `overall_ok=0` ⇒ severe，退出码 1**；`TODAY < 20261030` ⇒ `STOCK_STATUS="SKIP(尚无 stock_daily 备份)"`，打日志，**不告警不 FAIL**（复刻 `upload_r2.py:3462-3463` 无 key 时 exit 非零的现实，避免误判成"下载失败"发 severe）。
       - 为什么这里**不置 `rc=1`**：`rc≠0` 会走「下载失败 → `sleep 60` 重试 → 通用告警请排查 R2 凭证/网络」，真实原因被盖掉、重试也毫无意义。改走 `=FAIL` 备注路径，退出码与告警等级不变，但告警文案点名真因。
       - 日期用 `TODAY`（:44 `date +%Y%m%d`），单测用假 `date` 注入（L51，禁写死真实 today）；
       - 该闸门堵的洞：DB 若永久缺失，原来会一路 `SKIP` + rc=0，**永久静默**（`backup_db.sh:120-122` 上传失败也不计 RC、只打印「⚠ 不存在，跳过」）。
     - `ERR`（LIST 失败）⇒ 判失败走重试/告警（不许把"看不见"当成"没有"）；
     - 有 key ⇒ `download-db stock_daily`。
   - 分类`stock_daily` 在全链的角色：它是唯一"只有主库一份"的库，最需要每天有恢复证据。

2. **报告段加两行**
   - 改前：原 :97-99 只打印 sentiment / etf 两条路径。
   - 改后：:323-324 新增两行（stock_daily、public_fund 输出路径或 SKIP 原因），合计 4 条（:321-324）。

3. **内嵌 python 入参 4 → 6**
   - 改前：原 :104 传 `备份sent 备份etf 本地sent 本地etf`。
   - 改后：:338 传 **6 个** `备份sent 备份etf 备份stock 备份pf 本地库目录data/ 跳过项说明`；本地路径由 python 用 `dbdir + name + ".db"` 拼（逐字等价于原四条显式路径），跳过项说明形如 `stock_daily=SKIP(...);public_fund=SKIP(...)`。

4. **CHECKS 加两组，并带行数容差字段**
   - 改前：原 :110-116 两个二元组（sentiment 8 表 / etf 4 表），判定只有"备份=0 且本地>0"、"备份>本地"。
   - 改后：:355-370 四个四元组：stock_daily 3 表（`baostock_daily_raw` / `fapi_daily_raw` / `mootdx_daily_raw`）、public_fund 5 表（`fund_daily_nav` / `fund_purchase_status` / `fund_performance` / `fund_rating` / `fund_basic`）；public_fund 额外 `ratio=0.95`（:464 判定：`备份 < 本地×0.95` ⇒ FAIL「备份过旧/被截断」）。sentiment / etf 保持原口径（`ratio=None`）。

5. **新增 `run_public_fund_drill()`（:199-316）**
   - 门控 `VERIFY_PUBLIC_FUND=auto|1|0`（:202-219）：默认 `auto` = `date +%u` == 7（周日）；`1` 供删库前手动强制；`0` 关闭；非法值 warn 后按 `auto`。
   - 空间门（:221-237）：`df -Pk "$TMPDIR"` 可用 < `PF_MIN_KB`（默认 **4,718,592 KiB = 4.5 GiB**，:51；非法非整数回落默认，见下条）⇒ `SKIP(空间不足)` + **`notify.py --severe`**（安全网被关掉要人处理，与"非周日"这种设计内跳过区分开）。
   - 调 `restore_r2_db_backup.py`（:240-241）：`--name public_fund --out-dir "$PF_DIR" --threads 6`，**显式前置 `REPO=` / `GIT_REPO=`**（`repo_paths.sh:34` 只 assign 不 export，不传会被 `setdefault` 指到 git 仓，找不到 `.env`）。
   - trap 清理（:71）：`trap 'rm -rf "$PF_DIR" "$TMPDIR"' EXIT`，且校验完立刻 `rm -rf "$PF_DIR"`（:502）——该脚本不自动清理输出，10-25 留过 6.2G /tmp 致当晚备份"空间不足"放弃（`docs/ops/pfdb-r2-backup-20261025.md` §7⑤）。
   - `result.json` 落档（:243-246）到 `data/logs/verify_backup_pf_result_<STAMP>.json`。
   - 不走 `download-db`（整对象进内存 ⇒ 2.76 GiB 必 OOM）。

6. **断言④ 台账 ↔ HEAD 长度对账（:259-315，新）**
   - 读 `data/.r2_db_backup_state.json` 的 `public_fund.db` 记录（`upload_r2.py:3304-3310` 写入 `{size,mtime_ns,date,key,gz_size}`）；
   - **仅当台账日期 == 最新 daily key 日期**才 HEAD 该 key（`s3_head(..., with_len=True)`，不下载 body）比对 `Content-Length == gz_size`，不一致 ⇒ FAIL（对象被截断/换过）；
   - 无台账 / 记录不全 / 日期不一致 ⇒ **SKIP 并点名**（对账前提不成立，不是备份坏了）；HEAD 非 200 ⇒ FAIL（看不见 ≠ 通过）。

7. **三态结论行（PASS / FAIL / SKIP）**
   - 改前：原 :183-187 只有"✓ 通过（integrity 全 ok + 关键表行数正常）" / "✗ 失败"两态，跳过的库会假绿。
   - 改后：:474-493 先单列「跳过/失败项」逐条，再出结论行：`=== 结论：✓ 通过（integrity 逐库 ok + 关键表行数正常；已覆盖: …；跳过: stock_daily=SKIP(...);public_fund=SKIP(...)）===`；SKIP 不置 `VERIFY_OK=0`，但**必在结论行点名**；`FAIL(...)` 项把 `overall_ok` 置 0。
   - 首行 `VERIFY_OK=0/1`（:496）语义**不变**（bash `:499` 解析、`backup_db.sh` 只看退出码）。

8. **新鲜度门（:410-433，新）**：stock_daily / public_fund 的最新备份日期必须 ≥ 今天−1，否则 FAIL「备份过旧」（覆盖 #312「台账在、R2 对象没了」）；基准日 `TODAY`（:44）来自 `date +%Y%m%d`，单测用 PATH 注入假 `date` 冻结，不写死日期（L51）。

9. **`VERIFY_PUBLIC_FUND_MIN_KB` 非法值校验（:51-59，评审建议 2）**
   - 改前：`PF_MIN_KB` 若被设成非整数（如 `abc`），`[ "$avail_kb" -lt "$PF_MIN_KB" ]` 会打 `integer expression expected` 后判 false ⇒ **空间门直接放行（fail-open）**，等于把 4.5 GiB 安全网静默关掉。
   - 改后：`case "$PF_MIN_KB" in *[!0-9]*)` ⇒ stderr 告警「非法(需整数 KiB)，回落默认 4718592」+ 回落默认，门照常生效。
   - 依据：3.51 GiB 峰值是实测（§1），门被静默关掉会让云上（3719MB RAM / 12.9GB 可用盘）在空间不足时硬跑 ⇒ 下载/解压中途 ENOSPC，且日志只有一句 `integer expression expected` 极易漏看。

### 0.95 容差的实测依据（任务书要求"先实测再定"）
禁止真跑演练（本单禁真下载），所以用**两份真实库的行数差 ÷ 天数**估算日增比（本地 mac 库 2026-09-12 vs 云上 10-28 实测行数，45 天）：

| 表 | 09-12 本地 | 10-28 云上 | 差值/45 天 | 日增比 |
|---|---|---|---|---|
| fund_daily_nav | 22,162,244 | 22,818,021 | 14,573 | **0.064%** |
| fund_purchase_status | 846,307 | 1,594,380 | 16,624 | **1.043%** |
| fund_performance | 625,312 | 1,175,336 | 12,223 | **1.040%** |
| fund_rating | 560,322 | 1,052,521 | 10,938 | **1.039%** |
| fund_basic | 27,758 | 28,346 | 13 | **0.046%** |

最大 1.04%/天 ⇒ **5% ≈ 4.8 天天增**；而周频 + 新鲜度门（≤今天−1）最多只落后 1 天 ≈ 1.04% ⇒ 0.95 容差**留了约 4.8 倍余量**，不会因正常日增假红。
诚实标注：本地库是 mac 镜像（可能滞后/口径差异），这是**估算**而非演练实测；真值以第一次真实 PASS 的 result.json 为准。

## 3. 实现预期 X → Y（可观测）

| 维度 | 改前 X | 改后 Y | 观测点 |
|---|---|---|---|
| public_fund 可恢复证据 | **从未验证**（大库唯一副本，从未拉回校验） | **每周日**跑一次流式还原 + integrity + 5 表行数 + 新鲜度，有 PASS/FAIL 结论与 `result.json` | 周日日志 `verify_backup_*.log` + `data/logs/verify_backup_pf_result_*.json` |
| stock_daily 备份/恢复 | 零备份（R2 0 对象）、零演练 | 日频备份（10-29 21:00 起）+ 日频演练；首份出现前干净 SKIP；**过了 2026-10-30 仍无任何 key ⇒ FAIL+severe（不再是永久静默 SKIP）** | 日志 `stock_daily:` 行 / `备份=… 本地=…` 区块 / 结论行 `stock_daily=FAIL(无 stock_daily 备份,已过首备日)` |
| 空间门配置错误 | `VERIFY_PUBLIC_FUND_MIN_KB=abc` 时 `-lt` 报错后**门开**（安全网静默失效） | 非法值 ⇒ 告警 + 回落 4718592，门照常生效 | stderr「非法(需整数 KiB)，回落默认 4718592」 |
| 结论行 | 两态，跳过的库写成"全 ok"（L49 假绿风险） | 三态，跳过项**点名** | 结论行 `跳过: …` |
| 台账 ↔ R2 一致性 | 无（台账只用于"源未变跳传"） | 每周日对账 `Content-Length == gz_size`（前提成立时强制断言，不成立则点名 SKIP） | 日志 `台账 HEAD 对账:` 行 |
| `VERIFY_OK` 语义 | 首行 0/1 | **不变**（SKIP 不置 0；FAIL 置 0） | 首行 `VERIFY_OK=` |
| 退出码 | 0 通过 / 1 失败 | 不变（设计内 SKIP 仍 0） | `exit $RC` |

## 4. 证据用例清单（同 `scripts/tests/test_255_backup_drill_20261028.py`，**28 条** = 原 23 + 必修/建议新增 5 条）

| # | 用例 | 断言 |
|---|---|---|
| 1 | `test_source_shape_declares_stock_daily_and_public_fund_drill` | 源码含 `download-db stock_daily`、`r2_latest_backup_date stock_daily`、`restore_r2_db_backup.py --name public_fund --threads 6`、显式 `REPO=/GIT_REPO=`、trap 清理 `$PF_DIR`、结论含「跳过:」、`VERIFY_OK` 首行 print；**源码形状守卫另断言** `"$TODAY" -ge 20261030`、`FAIL(无 stock_daily 备份,已过首备日)`、`*[!0-9]*`、`回落默认 4718592` |
| 2 | `test_stock_daily_absent_skips_without_severe` | 注入运行日 `20261029`（首备日当天）、R2 零对象 ⇒ rc=0、`SKIP(尚无 stock_daily 备份)`、notify 替身零调用 |
| 2b | `test_stock_daily_absent_after_deadline_fails_with_severe`（必修 1） | 注入运行日 `20261030`、R2 零对象 ⇒ **rc=1**、`FAIL(无 stock_daily 备份,已过首备日)`、结论行 `✗ 失败`、notify 收到 `--severe`（点名真因，不是"R2 下载失败"） |
| 2c | `test_stock_daily_date_gate_is_not_today_hardcoded`（必修 1，L51） | 有 key 时把运行日推到明天 ⇒ 闸门不误伤、rc=0、无 FAIL、`stock_daily: 最新备份`（证明判定用注入日，不写死真实 today） |
| 3 | `test_pf_space_insufficient_skips_and_notifies_severe` | 门限 1e12KiB ⇒ `SKIP(空间不足`、**未启动还原**、notify 收到 `--severe` |
| 3a | `test_invalid_min_kb_falls_back_to_default`（建议 2） | `VERIFY_PUBLIC_FUND_MIN_KB=abc` ⇒ stderr 告警"非法…回落默认 4718592"、门照常放行（不是 fail-open 静默）、rc=0 |
| 3b | `test_stock_daily_list_failure_is_fail_not_skip` | LIST 失败（非 200）⇒ **FAIL + severe**，不静默 SKIP（防桶写错/凭据失效时的假绿） |
| 3c | `test_restore_failure_is_fail_with_severe` | restore 非 0 ⇒ `✗ public_fund: restore_… 失败`、`public_fund=FAIL(restore rc=1)`、severe |
| 4 | `test_sunday_gate_enters_drill` / `test_non_sunday_gate_skips_drill` / `test_public_fund_gate_can_be_disabled` | 注入 `date +%u`=7 进入、=5 跳过、=0 关闭 |
| 5 | `test_rowcount_backup_empty_fails` / `test_rowcount_backup_gt_local_fails` / `test_public_fund_below_ratio_fails` / `test_public_fund_within_ratio_passes` / `test_public_fund_ratio_boundary_exactly_095_passes` | 备份=0、备份>本地、备份<本地×0.95 各红一次；96/100 通过；**95/100 恰好边界通过**（判定是 `<` 非 `<=`） |
| 5b | `test_ledger_head_length_matches_passes` / `test_ledger_head_length_mismatch_fails` / `test_ledger_date_mismatch_skips_and_names_it` / `test_ledger_head_http_error_fails` | 台账==key 日期时 HEAD 长度一致 ⇒ OK；长度不一致 ⇒ FAIL+severe；日期不一致 ⇒ SKIP 且结论行点名 `public_fund_ledger=`；HEAD=500 ⇒ FAIL（看不见≠通过） |
| 6 | `test_conclusion_names_skips_and_keeps_verify_ok` | `VERIFY_OK=1` 不被 SKIP 误置 0；结论行点名 `stock_daily=` / `public_fund=`，不含"全 ok" |
| 7 | `test_stale_backup_date_fails` | 备份落后 3 天 ⇒ FAIL + severe |
| 8 | `test_freshness_day_shift_still_green` | 运行日推到明天、备份落后 1 天 ⇒ PASS；落后 2 天 ⇒ FAIL（隔天仍绿 + 边界非恒绿，L51） |
| 9 | `test_mutation_without_presence_check_turns_case2_red` | 变异①去掉存在性预判 ⇒ 用例 2 不成立（判别力证明） |
| 10 | `test_mutation_space_gate_disabled_turns_case3_red` | 变异②空间门改成永不触发 ⇒ 用例 3 不成立（判别力证明） |
| 10b | `test_mutation_stock_gate_removed_turns_deadline_case_red`（必修 1 变异③） | 把 `if [ "$TODAY" -ge 20261030 ]` 改成 `if false` ⇒ 过首备日仍无备份只剩 SKIP、rc=0、无 severe ⇒ 用例 2b 红（判别力证明） |
| 10c | `test_mutation_stock_gate_inverted_turns_before_case_red`（必修 1 变异④） | 把 `-ge` 改成 `-lt` ⇒ 首备日之前就 FAIL+severe ⇒ 用例 2 红（判别力证明，方向写反必被抓） |
| 11 | `test_no_real_network_or_notify_by_construction` | 沙箱自证：替身全部拦截、无未知调用、无 notify |

全部用例的 `REPO` 指向临时目录、`PY` 是替身（只有内嵌校验 python 块转交真解释器），`VERIFY_NOTIFY_DRY_RUN=1` 双保险 ⇒ **零真实下载、零真实外发**。

## 5. 删除前置判据（针对 `docs/ops/disk-reclaim-20261028.md` 的重复副本回收）

**不是「脚本能跑」，而是「真跑过一次且 PASS，且该 PASS 在最近 7 天内」**（daily 只留 7 天，更早的 PASS 证明不了现存对象）：

1. public_fund：至少 1 次 `RESTORE PASS` + integrity ok + 5 表行数 PASS + 新鲜度 PASS，`result.json` 落档；
2. stock_daily：第一份备份（**2026-10-29 21:00** 才产生）出现后跑 1 次 PASS；
3. 两者齐 ⇒ 才允许执行 `disk-reclaim-20261028.md §5` 的删除（删的是云上**重复副本**：代码仓 3.63GB + staticdata 3.38GB + 僵尸 `data/backups` 2.88GB + `*.bak` 0.14GB ≈ **10.03GB**；任务书说"约12G"，按实文口径记 10.03GB，差异诚实标注）；
4. **主库 `trade-data/data/*.db` 不动** ⇒ 演练证明的是"盘毁后能从 R2 重建"，不是"主库可删"。

恢复路径（万一误删）：副本来源为 git 远端（代码仓 / staticdata 仓）+ R2 `backup/`、`weekly/`、`monthly/` 三前缀；取回命令与 10-25 首次演练一致，见 `docs/ops/pfdb-r2-backup-20261025.md`。

- **public_fund 周日新鲜度的隐性依赖（评审建议 1，只记录不改码）**：周日演练的新鲜度门要求备份日期 ≥ 今天−1，而 public_fund 上传是「源库 size+mtime 未变则整条跳过」（`upload_r2.py:3276-3281`：`size`+`mtime_ns` 与台账相同即"未变更, 跳过"；台账字段写入见 `:3303-3311`）⇒ **周日的"新 key"实际靠周日 03:17 `trade-pf-score-weekly` 往 `public_fund.db` 写 `fund_score`**（`scripts/pf_score_weekly.sh:41` 调 `compute_all_scores(top_n=None)` → `:43` `export_fund_score.py`；对应实现 `app/collector/public_fund.py:3603` `compute_all_scores` 批量写 `fund_score` 表）。也就是说：若某个周日 03:17 评分失败/未跑，public_fund.db 无写入 ⇒ 当晚 21:00 备份不生成新 key ⇒ 周日演练的新鲜度门会 FAIL 告警。**这是"评分停摆会被备份演练顺带抓到"的正面副作用，但根因在评分链路**，排障时先查 pf-score-weekly，不要先去怀疑 R2 备份链。

## 6. 回退

- 大库分支出问题（空间/耗时/R2 抖动）：`VERIFY_PUBLIC_FUND=0` 一行关掉，其余三库照常演练；
- 其余改动均为单行可回退：stock_daily 三元组（`download_backups` 的 case 块 + CHECKS 一行）、报告两行、结论行文案；
- 无需回退 `backup_db.sh` / `restore_r2_db_backup.py`（本单零改动）。

## 7. 未做 / 诚实标注

- 未真跑一次演练（本单明确禁止真下载），所以"2 分钟 / 3.51GiB 峰值"仍来自 10-25 那唯一实测点；首次真实 PASS 前不能当"已验证"；
- stock_daily 的 gz 大小（50–68MB/份）是 40MB 样本外推（`upload_r2.py:3208` 注释"约30MB"偏低），首份备份出现后应回填实测；
- public_fund 行数容差 0.95 的依据是按 45 天行数差推算（见 §2），首次真实 PASS 后应回填 result.json 里的真实行数；
- `restore_r2_db_backup.py` 仓内零测试（#314），本单不改它=不引入新回归面。
- 台账 HEAD 对账的**前提**是 `upload_r2.py` 在源库未变时写入台账（`:3304-3310`）；若某次备份期间源库被写入，台账不更新 ⇒ 日期与最新 key 不一致 ⇒ 按设计 SKIP 并点名，不会假红也不会假绿。
- **新增告警点四元组声明**（`docs/ops/alert-checker-registry-20261015.md` 行 23 已登记本脚本）：新路径「public_fund 演练空间不足被跳过」= **tier** `critical`（`--severe`）/ **dedup window** 未声明（沿用本脚本既有通道，与登记表 #23 的存量口径一致，本单不改去重策略）/ **聚合域** `backup` / **首报策略** 首报必达（`--alert-issue` + `--alert-log` 写 `data/alerts/latest.md`）。登记表无需新增行（同一脚本同一域）。
- **超时预算（L55）**：`trade-backup-db.service` 外层 `TimeoutStartSec=12600`（3.5h，见 `docs/ops/pfdb-r2-backup-20261025.md:52`），10-28 实测当日运行 76 分钟（21:00:01→22:16:46）；周日多一段 public_fund 演练（预计 +5~8 分钟，最坏按 6 线程 2~10 分钟估）仍有大量余量。**本单没有改任何超时值** ⇒ 不存在"内外层成对 + 四副本同步"的改动面；内层唯一等待是既有「下载失败 60s 重试 1 次」，未改。
## 8. 补记（2026-10-29）：导入路径缺陷（P0）与根治

> 本节是**事后补记**：10-28 上线的这套演练，在云上**一次都没真跑过**就差点带着故障进入首个执行夜。事实与证据如下，供后来人反查。

### 8.1 事实（实测，不是推断）

- 10-28 21:00 那次 `trade-backup-db.service` 跑的还是**老版** `verify_backup.sh`（云上脚本 mtime = 2026-10-29 08:49，今早 deploy 才更新），那份日志 1849 字节、无 stock_daily 段，结论 `✓ 通过 退出码=0`；10-24～10-28 五份日志同为老格式。
- 也就是说：**新代码在云上零次真实执行**，告警台账里也没有任何新命中（唯一 `verify_backup` 记录仍是 2026-10-23 22:21:34 的旧文案）。
- 若未修复，**今晚 21:00 首次执行**会这样走：sentiment/etf 下载成功 → `r2_latest_backup_date stock_daily` 恒 `ERR` → `rc=1` → 睡 60s 重试一次（再下 ~130MB 白跑）→ `exit 1`，发出**通用** severe「R2 备份下载失败…请排查 R2 凭证/网络」（指向错误方向），且 **integrity/行数/新鲜度/public_fund 全部不跑**——演练形同关掉，每晚重复。

### 8.2 根因

`python -` 的 `sys.path[0]` 是 **cwd**；生产 unit `WorkingDirectory=/home/ubuntu/code/trade-data`。而 `scripts/upload_r2.py:51` 有模块级 `import r2_lock_paths`（同目录），2026-10-28 的 R2 锁域改造（#320）加进来之后，所有用 `importlib` 加载 `upload_r2.py` 的调用方在「cwd=REPO 根」下都会 `ModuleNotFoundError: No module named 'r2_lock_paths'`。以脚本方式跑（`python <REPO>/scripts/upload_r2.py`）不受影响，因为那时 `sys.path[0]` 是脚本所在目录。

### 8.3 影响面（逐个核过）

| 位置 | 状态 |
|---|---|
| `scripts/verify_backup.sh` `r2_latest_backup_date()`（`stock_daily` 存在性 + `public_fund` 台账日期） | 受影响，恒 `ERR` |
| `scripts/verify_backup.sh` 台账 HEAD 对账内嵌块 | 受影响，恒 `FAIL(HEAD … status=)` |
| `docs/scripts/restore_r2_db_backup.py`（public_fund 流式还原；`docs/backup-restore.md` 教人从 REPO 根手工跑的也是它） | 受影响，`--help` 都跑不起来 |
| `download-db sentiment / etf_national_team / stock_daily`、`notify.py`、报告块、台账 JSON 块 | 不受影响（脚本方式运行 / 不 import upload_r2） |
| 其余 10 处 `import upload_r2` 的调用方 | 不受影响（各自早已把 `scripts/` 塞进 sys.path） |

### 8.4 为什么 28 条用例没抓到（假绿的真正来源）

`test_255_backup_drill_20261028.py` 的替身 python（`:57-82`）把 `$PY - …/upload_r2.py` **整段拦截**，内嵌块从不执行；假 REPO 里的 `upload_r2.py` 只是一行注释（`:179`）。再加上 `scripts/tests/conftest.py` 把 `scripts/` 塞进 pytest 进程的 `sys.path`，进程内 import 永远绿。⇒ 桩把"能不能加载起来"这一层整个替掉了。

### 8.5 根治（主控 2026-10-29 拍板：载荷侧一处，不做无条件 insert）

`scripts/upload_r2.py` 的锁模块导入改成「先试后补」：

```python
try:
    import r2_lock_paths as _rlp
except ModuleNotFoundError:
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.realpath(__file__)))
    import r2_lock_paths as _rlp
```

- 只在**已经坏掉**的分支里动 `sys.path`：不做无条件 insert，避免把 `scripts/` 顶到搜索路径最前（将来 `scripts/` 里若出现与标准库同名的文件会把全仓 import 打歪）。
- 一处根治 ⇒ 上述三处全好，且未来任何新加载方不再踩。
- **不改** `verify_backup.sh` 的 loader 侧（明确不加 `sys.path.insert`，由 `test_345_…::test_D1` 守着）。

### 8.6 证据用例（真执行，不经替身 python）

新增 `scripts/tests/test_importpath_p0_20261029.py`（3 条，全部子进程 + `cwd=REPO 根` + 去掉 `PYTHONPATH`）：

1. `test_T_REAL_1_import_upload_r2_from_repo_root`：REPO 根 cwd 下 importlib 加载 `upload_r2.py` ⇒ 退出码 0（**改前实测红：`ModuleNotFoundError`；改后绿**）。
2. `test_T_REAL_2_restore_script_help_from_repo_root`：`python docs/scripts/restore_r2_db_backup.py --help` ⇒ 退出码 0（改前红、改后绿）。
3. `test_T_REAL_3_upload_r2_guards_lock_paths_import`：源码形状守卫，防兜底被"顺手简化"回去。

另用生产同形态（`python -` 内嵌块、cwd=假 REPO 根、无 `PYTHONPATH`）真跑只读验证：

- LIST 块 ⇒ `sentiment` 取到 `20261028`（与 10-28 日志一致）、`stock_daily` = `NONE`（与"今晚 21:00 才首备"一致）；
- HEAD 对账块 ⇒ `200|804241131`，与云上 `data/.r2_db_backup_state.json` 里 `public_fund.db.gz_size` **逐位相同**；
- `restore_r2_db_backup.py --help` ⇒ 退出码 0。

### 8.7 上线后观察锚点（首个执行夜）

今晚 21:00 后的 `data/logs/verify_backup_*.log` 应满足：
1. 出现 `stock_daily: SKIP(尚无 stock_daily 备份)`（首备 21:00 之前无 key 属设计内），且**不含** `stock_daily=ERR`；
2. 不再出现「R2 备份下载失败(60s 重试后仍失败)」；
3. 结论行回到 `✓ 通过`（public_fund 非周日 SKIP）。
若仍是 `ERR`，说明修复没生效或云上拉的不是新 commit —— 先核云上 `scripts/upload_r2.py` 是否含 `except ModuleNotFoundError`。
