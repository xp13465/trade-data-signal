# #188 reviewer 独立审查报告 — s06 链路「同步段」检查侧三层盲区根治

- **审查对象**: `feat/188-s06-sync-blindspot-20261005` @ `09338aa0f`(单 commit,已推远端,未合 main)
- **变更集(diff_range)**: `origin/main(50090c642)..09338aa0f`,5 文件 +630/−13:
  `scripts/upload_r2.py`(+143/−,台账+verify-r2 纳入+文件名落清单) / `scripts/s06_snapshot.sh`(42,trap 驱动告警) / `scripts/check_data_integrity.py`(25,①b R2 coverage_end WARN) / `scripts/test_188_s06_sync_blindspot.py`(新增 194,自验) / `docs/ops/188-s06-sync-blindspot-20261005.md`(新增 239,实施报告)
- **结论: PASS**(P0=0、P1=0;P2×2、P3×2 记录在案,均不阻断合并)
- 审查方式: 只读,未改任何代码;所有结论独立复核(逐条独立复跑、逐行读代码、云上只读核查、只读实证微测试)。独立复跑自验脚本 = ALL_PASS(实测 17/17 断言)。
- 审查 agent: `a4f7bf2bd557a4dfa`;时间: 2026-10-05 21:09

## 零、逐点速览(父级指定 11 点)

| # | 核验点 | 判定 | 等级 |
|---|---|---|---|
| 1 | 登记步骤 fail-open / fail-closed(§14 P0 问) | **fail-open**(失败只 stderr 警告、上传照走)= 方向正确,非 P0 | 通过 |
| 2 | 台账 git 合规(§8)+ 原子写 | 命中 `data/.gitignore` 首行 `*`,未 tracked;tmp+`os.replace` | 通过 |
| 3 | 台账丢失/为空是否=新静默盲区 | **缺失→静默空集(无警告)**;损坏→stderr 警告+空集;**有自愈**;**无**非空校验 | P2-1 |
| 4 | 「只 WARN 不 FAIL」死锁论证 | **成立**(deploy L324 先于 L582+ R2 链,FAIL 即中止=死锁);WARN 消费方=仅 deploy 日志 | 通过(说明) |
| 5 | R2 成本增量 | HEAD=Class B;+约 30~120 HEAD/日;**Class A +0** | 通过 |
| 6 | 链外告警是否真「无进程依赖」 | 相对 s06 链解耦;相对 deploy 链**不独立**(deploy 不跑则同亡;但 deploy 另有监控+③a 不依赖 deploy) | 通过(说明) |
| 7 | 自验 ALL_PASS 真伪 | **真**(独立复跑 17/17 PASS,EXIT=0);trap 三态行为正确;但报告称 18 断言 | 通过 / P3-1 |
| 8 | 回归 | pytest=192 passed/1 skipped(feat 与 main 基线一致);`bash -n` OK | 通过 |
| 9 | §15 影响面(全调用方) | 14 处调用点全部只多「成功时一次本地登记写」,零对外语义变化 | 通过 |
| 10 | §22 四路径一致性/告警轰炸 | 不矛盾;同一事件最多 2 封且信息不同;不轰炸 | 通过 |
| 11 | 两个既有缺口真伪 | **确认真缺口**;且 fund_score 链**活跃**每日上传却不被对账(同族风险活体) | 需新任务 |

## 一、逐点核验证据

### 点 1 — 登记步骤会不会把上传打挂?(非 P0)
- 代码: `_record_standalone_keys`(upload_r2.py L2100-2124)整体包 `try/except OSError`,写失败仅 `print(…, file=sys.stderr)` 后正常返回;注册调用点位于上传成功分支(`if ok != total: sys.exit(1)` **之后**): `cmd_upload_intraday` L2075、`cmd_upload_data_files` L2174 → 上传/失败/退出码语义零变化。
- 实证(只读微测试): REPO 指向只读目录后调 `_record_standalone_keys` + `cmd_upload_data_files` → PermissionError 被 except 吸收、仅 stderr 警告,函数正常返回,无异常、无 exit 非零(TEST1 PASS)。
- 并发写/磁盘满: 同走 OSError 路径 fail-open;并发丢更新见 P3-2(原子写保证不损坏文件)。
- 判定: **通过**。失效方向安全(登记属检查侧辅助,失败=回退旧行为,不会让 17:50 update-all 上传链断)。

### 点 2 — §8 git 合规 + 原子写(通过)
- `git ls-files data/.r2_standalone_keys.json` → 空(实测);`git check-ignore -v …` → 命中 `data/.gitignore:1:*`。
- 云上: `~/code/trade-data` 非 git 仓(scripts/config 为指向 `trade-data-signal` 的 symlink)→ 云上该文件同样不进任何 git 状态。
- 原子写: tmp + `os.replace`(L2119-2123);实测写后无残留 `.tmp`(与 memory `atomic-write-data-artifacts` 口径一致)。
- 分支 `git diff --stat` 不含任何根 `data/` 文件。

### 点 3 — 台账自身是否新静默盲区(P2-1)
- **缺失 → 静默空集(无警告)**: `_load_standalone_keys`(L2127-2144)对 `not p.exists()` 直接 `return set()`。**损坏 → stderr 警告 + 空集**(同函数)。**格式异常 → stderr 警告 + 空集**。
- 空集效果: 平日 verify-r2 少一类「确定对象」,退回「全池抽样 100 撞运气」旧行为,末尾照打「全部一致 ✓」→ **静默绿**(不报警)。
- **无**非空/数量下限校验;自愈**有**: 每次成功上传都会 merge 重登记(去重 set 跨天持久,失败上传不登记),丢失后当日盘中链(10min 间隔)/s06 20:35/daily-brief 20:40 即回填大头;周日全量完全不依赖台账。
- 净风险低的依据: ①b 与 ③a/③b 均不依赖台账 → 台账丢 ≠ 全盲,只是平日对账覆盖临时退化。
- 结论(直答): **清单缺=静默绿;清单坏=警告后退化为绿;无报警、无下限校验、有自愈**。等级 P2(可选改进: 缺失时打一行 stderr 便于反查;非必须)。

### 点 4 — WARN 死锁论证(成立;WARN 消费方死结论)
- 行号证据(deploy.sh): **L324** 运行 `check_data_integrity --deploy-mode`;L326-331 非零 → severe notify + `exit`(中止 deploy);R2 异步上传链在 **L582+**(systemd-run `r2_upload_async.sh`,其 L218 调 verify-r2)。故 ①b 若 FAIL → deploy 中止 → R2 永不上传 → 无任何自愈 → **死锁成立**,WARN-only 是正确取舍(且符合 `--deploy-mode` 语义: 只有 warn 时 exit 0,L2283-2340 / L2353-2362)。
- 反向问题「改成只 WARN 后谁消费这条 WARN」死结论: **没有任何通知渠道消费它** —— WARN 只进 deploy 日志(`--deploy-mode` 下 WARN 不发通知);真正的邮件消费者是 verify-r2 的 `verify_r2_standalone_stale` 外围告警(③b,依赖台账在位)。
- 即 ①b 的职责 = 「本地新鲜时」的日志级旁证;它不构成独立告警通道,但也不构成「盲区搬家」——通知职责由 ③b 独立路径承担,s06 自身故障由 ③a 承担(不依赖 deploy)。
- 判定: **通过(说明级)**。

### 点 5 — R2 成本量化(通过)
- `s3_head`(L627)用 HTTP **HEAD**(canonical_request 第一行 "HEAD")→ CF 计费 **Class B**(Class A=PUT/LIST,Class B=GET/HEAD;与 #186 账单口径一致)。
- 增量估算: 台账全量登记 ≈ 70~100 键(28 盘中 + s06/nextday/daily-brief/global/gold/feed 等);其中能进通道池(顶层 `*.json`、<1MB、非排除前缀)≈ 30~60 键 → 每工作日 verify-r2 每 run 约 +30~60 HEAD;verify-r2 每部署日 1~2 run → **+约 30~120 HEAD/日(月 +1k~4k)**,对比 Class B 免费额度 10M/月可忽略。
- **Class A 新增 = 0**(不新增 LIST/PUT;补传 PUT 只在真的发现脱节时发生=既有行为)。9 月 Class A 1.22M 超额的病灶不在此路径。

### 点 6 — 链外告警独立性(半独立;说明)
- verify-r2 位于 `r2_upload_async.sh` L218;r2_upload_async 由 deploy.sh L582+ 触发;deploy 由 update_all 每日调用(云上 `trade-update-all.timer` = Mon..Sat 17:50 + Sun 22:30,非交易日也 deploy: update_all.sh L68-69)。
- 即「链外」= 相对 **s06 链**解耦(正确达成了事故教训的目标);相对 **deploy 链不独立** —— 若某天 deploy 未跑/提前中止,verify-r2 同静默。缓解: ① deploy 中止本身有 severe 告警、update_all 漏跑有 schedule 监控(另一通道);② ③a trap 不依赖 deploy。理论双盲(deploy 未跑且 s06 静默死)概率低且被 update_all 监控覆盖。
- 初验状态(云上只读实测): R2 的 s06 副本 vs 云上本地**已一致**(coverage_end=20260930、行数 4047)→ 09-24 起的存量缺口已由 10-04 周日全量 verify-r2 补传治愈,与任务描述相符。

### 点 7 — 自验脚本真伪(ALL_PASS 为真;P3-1 文档差)
- 独立复跑 `python3 scripts/test_188_s06_sync_blindspot.py` → 逐条 **17 PASS、EXIT=0**(macOS 无 `timeout` 命令,用 `perl -e 'alarm …'` 包装;MATCH 未设/已设两分支各计 17)。
- trap 三态行为实测: EXIT rc=1 → 恰 1 告警;SIGTERM → 恰 1 告警 + `exit 143`(经 `_ALERTED` 幂等,EXIT 与 TERM 双触发不双发);happy path → 0 告警、exit 0。
- ①b 四分支(一致→OK / 落后→WARN / 取回失败→WARN / 结构异常→WARN)均**不 FAIL**,防 deploy 死锁的意图被测试钉住。
- 差异: 实施报告(L67)称「18 断言」,实测执行 **17** 条(构成: ledger 5 + verify-r2 正/反 5 + trap 3 + ①b 4)。等级 **P3-1(文档数字)**。

### 点 8 — 回归(通过)
- feat worktree: `.venv/bin/python -m pytest scripts/tests -q` → **192 passed / 1 skipped**;main 基线(未改代码的干净树)同 = **192 passed / 1 skipped** → 一致,与 #190 基线相符,无新增破坏。
- `bash -n scripts/s06_snapshot.sh` → 语法 OK。

### 点 9 — §15 影响面(逐调用方)
| 调用方 | 触发链 | 受影响点 | 判定 |
|---|---|---|---|
| `upload-data-files` ×12: s06_snapshot.sh L131 / nextday_plan_generator.py L1172 / nextday_gap_check.py L350 / gen_daily_brief.py L3114 / fetch_news.py L721(新闻归档,子目录键) / intraday_snapshot.sh L180,L232 / kelly_intraday_rerun.sh L127 / push_schedule_stats.sh L67 / gold_night.sh L69 / fapi_daily_syn.sh / r2_upload_async.sh L190(feed.xml) / gen_kelly_loss_features.py(手动链) | 各自定时链 | 仅成功时一次本地台账 merge 写(无变化早退,不写盘);失败路径零变化 | 无影响 |
| `upload-intraday` ×2: intraday_snapshot.sh L170(盘中 10min) / turnover_backfill.sh L143(21:10) | 盘中/延后链 | 同上(28 键) | 无影响 |
| `verify-r2`: r2_upload_async.sh L218 | deploy 链 | 增: standalone 并入(不受 sample 上限截断)+ 补传清单落文件名 + 新外围告警(dedup 6h);周日 full 分支逻辑未改 | 语义只增不改 |
| `check_data_integrity`: deploy.sh L324 / 手动机检 | deploy | ①b 仅「本地新鲜」分支新增 1 次 CDN fetch(超时 ≤30s);WARN 不改 exit code | 无影响 |
| `s06_snapshot.sh` | 交易日 20:35 | trap 注册在交易日闸门之后(非交易日 exit 0 保持无 trap 无告警);失败告警条数=1(不重复);FINAL_RC/日志格式不变 | 语义只增不改 |
- 未发现改动外溢: 上传语义 / purge / 退出码 / 既有告警全零删改。

### 点 10 — §22 一致性 / 告警轰炸(通过)
- 四路径同指一事实且不矛盾: ① s06 自传+登记(治) ② 平日 verify-r2 对账+自动补传(治+报) ③ deploy ①b(日志) ④ 脱节外围告警(报)。
- 同一缺口最多触达 **2 封且信息不同**: ③a(s06 当晚,链路失败/被杀;dedup 1h)+ ③b(次日 verify-r2,含「已自动补传 N 个」;dedup 6h)。SIGKILL 场景 ③a 不能发(trap 不捕获)→ ③b 兜。不构成 4 连轰炸,保留真故障判别维度(与 memory `alert-denoise-keep-fault-discriminator` 口径一致)。
- 展示位一致性: 修复后 R2=本地(云上实测一致)。

### 点 11 — 两个既有缺口真伪(确认真;需新任务)
- `_R2_CHANNELS`(L3145-3178)**确无** `offshore_fund` / `fund_score` 前缀;且 `_DATA_EXCLUDE_PREFIXES`(含 "offshore_fund","fund_score")使 data-large/all-data 池也排除 → **连周日全量都不对账**,两缺口属实。
- 现场活性更正: `upload-fund-score` 由 update_all.sh **L237 每日活跃调用**(fund_score 链非休眠);且其上传失败仅 `echo` 不 severe(update_all 只记 export rc)→ fund_score 前缀若脱节 = **同族静默风险活体存在**。#188 的台账机制**不会**自动覆盖它(该前缀不经 upload-data-files 登记)。offshore_fund 定时链已停用(仅手动)。
- 处置建议(写报告,不自行开任务): 登记新任务「fund_score R2 对账补齐(纳入 verify-r2 通道并复用台账思想)+ 上传失败升级 severe 告警」,优先级中;可与本报告的 P2 项一并处理。

## 二、发现清单

| 编号 | 等级 | 发现 | 影响 | 建议 |
|---|---|---|---|---|
| P2-1 | P2 | 台账缺失时静默回退(无警告、无下限校验;损坏才有 stderr) | 平日对账覆盖临时退化,不误报;自愈快(当日链回填) | 可选: 缺失时打一行 stderr |
| P2-2 | P2 | `fetch_news` 子目录键(`data/news_digest/...`,实测 31 个 json)+ `data/feed.xml` 登记后**永远无法被对账**(通道 glob 为非递归 `*.json`)→ 死登记;实施报告「覆盖全部独立上传产物」表述过宽 | 无功能影响;台账含噪音键;覆盖声明不准确 | 报告表述订正;或未来将子目录/非 json 纳入 |
| P3-1 | P3 | 实施报告称自验 18 断言,实测执行 17 | 文档数字准确性 | 报告订正 |
| P3-2 | P3 | 台账为无锁读-合并-写: 两个进程并发登记极端窗口可丢更新 | 个别 key 漏登记,后续链/次日链回填;`os.replace` 保证不损坏 | 可不改 |

说明级结论(不算缺陷,记录备查): 点 4 的「WARN 无通知消费者」、点 6 的「外围告警相对 deploy 不独立」——两者均已在设计内被 ③a/③b/其他监控补位。

## 三、上线后观察点(建议主控设一次性核查)
1. 下一交易日 20:35 链跑完后: 云上 `~/code/trade-data/data/.r2_standalone_keys.json` 应**存在**且含 `data/kelly_mode_s06_state.json`(首次回填),否则 §8/台账机制未生效。
2. 次日 deploy 的 verify-r2 日志应出现「独立链产物 N 个」字样;无 `verify_r2_standalone_stale` 告警为常态。
3. 节假日后的下个交易日(任务描述提及 10-08): s06 链恢复正产出且 trap 无告警。

## 四、复现(全部命令,可原样重跑)
```bash
# 1) 自验脚本独立复跑(macOS 无 timeout,用 perl alarm 包装；venv python 带 pytest)
cd <feat worktree> && python3 scripts/test_188_s06_sync_blindspot.py        # → ALL_PASS, EXIT=0, 17/17
# 2) 回归
<repo>/.venv/bin/python -m pytest scripts/tests -q                         # → 192 passed, 1 skipped
bash -n scripts/s06_snapshot.sh                                            # → OK
# 3) git 合规
git ls-files data/.r2_standalone_keys.json                                 # → 空
git check-ignore -v data/.r2_standalone_keys.json                          # → data/.gitignore:1:* 命中
# 4) 关键行号锚点
grep -n "_record_standalone_keys\|_load_standalone_keys\|stale_standalone" scripts/upload_r2.py
grep -n "check_data_integrity\|r2_upload_async" scripts/deploy.sh          # → L324 / L582+
# 5) 云上只读(需 ~/tdsignal.pem)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'python3 -c "import json;d=json.load(open(\"/home/ubuntu/code/trade-data/static-site/data/kelly_mode_s06_state.json\"));print(d[\"coverage_end\"])"'
# 6) fail-open 实证(只读目录注册)见审查记录 TEST1/2/3(临时目录打桩,不写生产)
```

## 五、总结
**PASS,建议合并**(P0/P1=0)。三处修法均达成事故教训目标(告警与链路同亡→trap 兜底;存量缺口平日不着→台账确定性纳入;盲区静默→双通道告警),且未发现对外语义回退。P2 两项(台账缺失静默、死登记/表述过宽)与点 11 的 fund_score 活体缺口建议合并登记为一个后续任务统一处理;P3 两项可不改。

---

## 复审第二轮 — 增量 `143289653`(2026-10-05)

**复审对象**:`143289653`(delta = `09338aa0f..143289653`,3 文件:`scripts/upload_r2.py` +174 / `scripts/test_188_s06_sync_blindspot.py` +133 / `docs/ops/188-s06-sync-blindspot-20261005.md` +166;与 #191/#194/systemd unit 文件**零重叠**)。上轮 PASS 未沿用——代码改过即全面独立复核,以下结论全部来自 reviewer 自写探针 + 独立第三实现,不采信实现者自述。

**复审结论:PASS(P0=0 / P1=0 / P2=0;P3 观察 ×2,不阻断)** —— merge 资格成立。

### 逐项核(4 项修复)

1. **P2-2 修法①(登记语义 = 对账扫描语义)** — ✅ 成立。
   - 代码原文核:`cmd_verify_r2` 的收集即 `files = _channel_files(ch, local_dir)`(L3327),平日 `to_check ⊆ files`、`standalone_files` 从同一 `files` 筛、补传 `only_files=mismatches`(同为这些 file 对象)⇒ **决定 missing 的判定路径完全由 `_channel_files()` 覆盖**(不是只覆盖一半)。
   - 自证循环排查:两边共用 helper 属「构造性同源」,风险在 helper 本身与真实上传通道分叉。用**独立第三实现**(自写段感知 glob,`*` 不跨 `/`;不调用其任何 helper)对 44 个候选键(28 intraday + s06 + nextday/brief/news/kelly 等)逐位比对:`kept` 集与 `_reconcilable_keys_for` **完全一致**(36/36)。
   - 真实数据树探针(主检出 `trade/static-site/data`,只读):顶层 `*.json`=178、`news_digest/` 下 31 个 json、`feed.xml` 存在;期望三键 `kelly_mode_s06_state.json`/`overview.json`/`schedule_stats.json` 全部保留;`news_digest` 全部子目录键(31 个,含迁移期扁平键)+ `feed.xml` 全部剔除(与报告 §12.1 表逐行一致)。
   - **反证(防互掩)**:monkeypatch `s3_head` 对台账内 `data/overview.json` 返回 404 → 实测走完「判缺失 → `_upload_glob(only_files=[该文件])` 补传 → 层4 `verify_r2_standalone_stale` 告警」全链 ⇒ 台账键的缺口真会被独立检测,非自证空转。
   - 不选修法②(递归 glob)的理由与代码事实一致:`all-data`/`data-large` 的 local_dir=STATIC_DIR/data,递归会吞 nav_bucket/etf/index/lab/trade_sim/accum_nav/signal_kelly_* 全部子目录(与专属通道双传)。
2. **P2-1(台账缺失/损坏显式告警)** — ✅ 成立。五场景实测:平日+缺失 → **恰 1 发**,dedup key `verify_r2_standalone_ledger_gap` 窗口实测 **86400s**,stderr 有显式提示;损坏(非法 JSON)→ 1 发;正常 → 0 发;周日 → **不读台账不发**(monkeypatch load 抛异常证明未被调用);去重生效 → 0 发。
3. **P3-2(fcntl.flock 串行化)** — ✅ 成立,**不会卡住 17:50 上传链**(死结论 + 实测):
   - 阻塞性:**是阻塞式、无超时**(持锁 3s 的对照进程下,活键登记实测等待 3.01s)——语义确认。
   - 但对 17:50 链**结构性不触锁**:deploy 链唯一 `upload-data-files` 调用是 `upload-feed`(r2_upload_async.sh L190,文件=feed.xml),feed.xml 已属死键 ⇒ `keys &= reconcilable` 后为空、**在取锁前 return**。实测:另一进程持锁 3s 期间跑 feed.xml-only 登记 = **0.04s 秒回**(对照:活键登记同场景 3.01s)。
   - 临界区尺度:无竞争单次登记实测 **1-2ms**(36 键台账读改写);8 进程 × 5 互异键并发 = 40 键**零丢更新**,总耗时 0.09s(SIGKILL 持锁者后 0.08s 接管,**无陈旧锁**;锁文件持久存在=flock inode 语义正常,不构成陈旧锁)。只读目录(锁文件创建失败)→ **exit 0 + stderr 告警,fail-open 不阻断上传**。
   - 残余风险(可忽略级):仅「持锁进程被冻结在临界区」一种——临界区内无网络/阻塞 IO(本地读+原子写,毫秒级),概率可忽略;建议日后顺手加超时或注释(见 P3-A)。
4. **报告订正** — ✅ 数字与表述现与实测一致:断言 **30 条 = 实测 30 PASS**(逐条计数);§8 复现段**原文照跑**,输出与所写期望逐字一致(`可对账=[s06, overview]` / `死键=[feed.xml, news_digest/2026/2026-10-05.json, news_digest/_index.json]`);§12.4 边界复核:feed.xml 的轻量校验通路真实存在(`cmd_verify_channels` L3600 `upload-feed` 特例 `_light_check_single_file("data/feed.xml", …)`)——「无覆盖缺口」成立;news_digest 缺口**如实标注不掩盖**;§12.5 17→30 对应链一致。

### ledger_gap 冷启动死结论:不是「每日噪音」,是**有界且自愈**

台账缺失/损坏时才发,dedup 24h ⇒ **每个平日 verify-r2 至多 1 条,且只在「台账尚不存在」窗口内**;首个独立链产物上传成功登记落盘即**永久静默**(intraday 交易日盘中每 10min 登记 / s06 20:35 / nextday 22:30 / brief 20:40 任一先行即自愈)。周日全量不读台账、不发(实测)。正常交易日冷启动窗口通常为 0(盘中链 09:35 先登记,17:50 deploy 链 verify 时台账已在)。代码无首次/宽限处理,但告警正文已注明「首次冷启动可忽略」;假期连排(如本 10-05~10-07)最多连续数日各 1 条,属可接受边界(已写入 §12.2)。

### 独立复跑(全部与实现者声称一致)

| 项 | 实测 |
|---|---|
| `python3 scripts/test_188_s06_sync_blindspot.py` | **30 PASS / ALL_PASS**(worktree HEAD=143289653,工作区干净) |
| `pytest scripts/tests -q` | **192 passed, 1 skipped** |
| `bash -n s06_snapshot.sh` / `deploy.sh` | 双双 OK |
| `(keys,state)` 三态异常路径 | 全有定论无未捕获:000 权限→corrupt / 目录冒充→corrupt / dict→corrupt / 空 list→missing / 非串元素→ok 容错 |
| 台账键零遗漏 HEAD | 真实树平日跑 **36/36 全 HEAD**(总 HEAD 663);人工把 all-data `sample=1` 仍不截断(独立块在抽样上限之后并入) |

### 新观察(不阻断)

- **P3-A**:`flock` 阻塞式无超时(设计取舍成立:临界区毫秒级 + 主链回退不触锁 + SIGKILL 自释放;仅冻结持锁者理论场景)。建议日后任一链动到该函数时顺手注明或加 `LOCK_NB`+重试,不构成本次阻断。
- **P3-B**:台账 list 内非字符串元素(如 `null`)→ state=ok 吞入 `"None"` 串,无害(不匹配任何真实 key),cosmetic。
- 附(正向):死键过滤附带治愈同类假缺失——`data/signal_kelly_trades_intraday.json`(2.2KB,被 all-data 前缀排除且未达 data-large,旧代码登记即死键)现被剔除;其上传失败由 `kelly_intraday_rerun.sh` L127-130 链内告警兜底,无新增缺口。上轮记录的既存缺口(offshore_fund/fund_score 前缀无 verify-r2 通道)本次未动,不受影响。

**上轮 4 项须先修全部验证通过;无新增 P0/P1/P2。复审 PASS,可 merge(经主控 `main-merge.sh` 统一入口)。**
