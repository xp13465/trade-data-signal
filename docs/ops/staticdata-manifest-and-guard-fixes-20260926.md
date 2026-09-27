# staticdata 收尾三项修复:manifest 归属 + --dry-run 契约 + 守卫遗留(#115/#116/#117, 2026-09-27)

> §23.5 四件套: 本报告本体 + 配套脚本(改动即上文提及的 8 个文件) + 复现段(见文末) + 配套 commit(feat 分支)。

## 1. 一句话总结

同一批文件一个分支 `feat/staticdata-manifest-and-guard-fixes` 收掉三件:
- **#115**: large-json 清单 manifest 从 trade 仓库迁至 staticdata 备份仓库(归属 = `git add -A` 提交对象),
  恢复侧双路径兼容, trade 侧改指针说明, STATICDATA_REPO 不可用报错退出不静默。
- **#116**: `--dry-run` 对不消费它的私有桶写命令硬报错非零退出, 并把「唯一隔离手段 =
  R2_BACKUP_BUCKET=<不存在的桶名>」写进 upload_r2.py 头部 + 运维文档。
- **#117**: 守卫 reviewer 遗留 M1(数据闸门 rc=2 心跳写 fail 而非 skip_nonprod——心跳字段语义正确化,
  非告警行为变化)/ M2(顶层守卫 rc=2 补 notify)/ M3(逐路径 git log -1 → 批量 pathspec, 主理由
  fail-closed 语义更保守 + 只起一次 git 进程, **非提速**——tester 定论: 生产候选集=当日变更集(实测
  ≤94 条), 生产规模批量 vs 逐路径耗时相当、逐路径略快, 「批量快 30 倍」仅同目录集中清单成立不适用生产)/
  L2-L3(有意识取舍文档化)。

## 2. 改了什么(逐文件)

| 文件 | 改动 |
|---|---|
| `scripts/upload_r2.py` | 头部 docstring 增 `--dry-run` 契约段; 新增 `_DRY_RUN_CONSUMERS` 白名单; `__main__` 对白名单外命令传 `--dry-run` 硬报错非零退出; `_write_large_json_manifest` 目标改为 staticdata 仓库(经 `_large_json_staticdata_repo()`, .git 缺失非零退出不静默); dry-run print 文案同步(#115/#116) |
| `scripts/restore-large-json.sh` | 新增 `_manifest_candidates()`(新路径优先 staticdata 仓库, 回退 trade 旧路径); 顺序=STATICDATA_REPO → GIT_REPO-staticdata → trade 旧路径(与写侧 `_large_json_staticdata_repo` 一致, reviewer P2-②); `load_manifest_sha` 遍历 cell 时 `.strip("`")` 兼容生成器带反引号 key(修复了原静默解析 0 条 → sha256 校验失效的潜在缺陷) |
| `docs/large-json-backup-manifest.md`(trade) | 整文件替换为指针说明(声明已迁 staticdata 仓库 + 双路径兼容 + 恢复入口不变) |
| `docs/backup-restore.md` | 第八节三处更新(索引/校验依据注明迁至 staticdata 仓库 + 双路径 + sha256 比对位置) |
| `scripts/migrate_large_json_out_of_git.sh` | MANIFEST 路径改指向 `$STATICDATA_REPO/docs/large-json-backup-manifest.md` |
| `scripts/staticdata_backup_async.sh` | M1: 数据闸门 rc=2 分支去掉 `_SKIP_NONPROD=1`(心跳改写 fail, 心跳字段语义正确化非告警行为变化, reviewer P2-④ 注释同步改准); M2: 顶层守卫 rc=2 分支补降级 notify(此前无即时通知) |
| `scripts/staticdata_sync.sh` | M2 同类补强: 顶层守卫 rc=2 分支补降级 notify(与 async 同模式遗漏, §23.3 举一反三); P2-③: 新增 LOG 变量 + notify 输出改 `2>&1 \| tee -a "$LOG"`(原 `2>/dev/null \|\| true` 静默, notify 自身失败也要留痕 §23.11) |
| `scripts/staticdata_write_guard.py` | M3: 新增 `_remote_last_commit_map()`(一次 git log + `--literal-pathspecs` 批量建路径→时间映射); `check_fresh` 改用它替代逐路径 git log -1; 头部与分支注释文档化 L2(D 永远排除)/L3(fail-open best-effort)有意识取舍 |
| `docs/ops/large-json-out-of-git-20260925.md` | 追加「私有桶写命令唯一隔离手段 = R2_BACKUP_BUCKET=<不存在的桶名>」文档化段(#116) |

## 3. 关键决策与理由

### #115 第 4 点: STATICDATA_REPO 不可用时 —— 报错退出, 不回退旧路径
- 任务书要求"行为必须明确(报错退出 or 回退, 不许静默不写)"。
- **决定 = 报错退出**。理由: 回退旧路径 = 复发原 bug(trade 仓库孤儿脏文件 + 没有任何环节提交它)。
  恢复侧本来就双路径兼容, 旧路径回退只在"读"侧有意义; "写"侧回退到旧位置只会重新制造 M 脏文件。
  已实测 `STATICDATA_REPO=/tmp/不存在/.git` → `_large_json_staticdata_repo()` 非零退出带明确文案。

### #117 M3: 批量 git log + pathspec(不是逐路径 git log -1)
- **核心一句(tester 定论, 2026-09-27)**: 批量 vs 逐路径在**生产候选集(当日变更集, 实测历史 ≤94 条)**
  上耗时相当、逐路径略快(0.02~0.97s vs 批量 0.12~1.11s), guard 现行逐路径实现**无性能问题**;
  「批量快 30 倍」仅在 `data/accum_nav` 类**同目录集中清单**上成立, **不适用于生产**
  (若明文写「30 倍」必须限定清单范围)。
- **采用批量的主理由 = fail-closed 语义更保守 + 只起一次 git 进程, 不是提速**(tester 定论推翻的
  不只是数字, 是 M3 立项前提「逐路径太慢」——生产候选集是当日变更集非全仓, 现行逐路径从来不是瓶颈)。
  - **fail-closed**: 本实现一次 git log 整体失败 → 返回 None → 调用方按内部错误 rc=2 拒绝本轮提交;
    旧逐路径实现单条失败是放行跳过该路径, 语义更松。
  - **只起一次 git 进程**: 逐路径实现每个候选路径起一次 git, 失败面/日志噪音大; 本实现单次调用
    拿到全部映射。
- **性能矩阵(tester 2026-09-27 实测, 同仓 /Users/linhuichen/code/trade-data-signal-staticdata, 同 git
  版本, warm 态 3 轮取最小; 只读操作未写仓库)**:
  | 清单 | 路径数 | 批量 min | 逐路径 min | 批量:逐路径 |
  |---|---|---|---|---|
  | A seed7 全仓随机(复刻 reviewer) | 200 | 3.869s | 3.540s(全测) | 0.92x 逐路径略快 |
  | B astock6+accum_nav194(复刻我第一轮) | 200 | 0.127s | 1.781s(全测) | 14.0x 批量完胜 |
  | C 全仓随机 | 2000 | 40.06s | 32.6s(外推, 基于 100 条实测) | 0.81x 逐路径快 |
  | **典型 94(历史真实大 commit 的变更文件)** | 94 | 1.108s | 0.784s(全测) | 0.70x **逐路径快** |
  | 极端 fund_nav 同目录 | 2000 | 6.86s | 34.4s(外推) | 5.0x 批量快 |
  | 小 3(news_digest 高频文件) | 3 | 0.118s | 0.023s(全测) | 0.17x 逐路径快 |
  | **混合 50(40 真实 M + 10 远端不存在 A)** | 50 | 0.484s | 0.970s(全测) | 2.0x 批量快 |
  对照: 空 pathspec 全仓库 walk 骨架=0.375s; git 进程启动=7.0ms/次(逐路径单条耗时下限)。
  A/B 复刻: reviewer 3.898s → tester 3.869s; 我 0.129s → tester 0.127s,**两边实测都真实**。
  → **30 倍差异 100% 来自清单特征**(pathspec 条数 × 目录分散度 × 路径变动频率), 不是实现、不是冷热
  (决定性量不是输出字节——B 输出 136KB 比 A 的 104KB 还大却快 30 倍, 真正决定批量耗时的是
  rev-walk + tree-diff pathspec 匹配成本)。凡写倍数必须限定清单范围, 裸写「快 N 倍」不成立。
- **reviewer 0.8x 结论定性(tester §4)**: 样本对但代表性错 + 方法糙。A 在 A 清单上方向没错
  (全仓随机清单批量确实不占优 0.92x), 但把「全仓随机清单」推广为「批量不值得做」是代表性错——
  生产候选集是当日变更的 data 目录文件, 不是全仓随机; 真实候选规模上批量无优势, 假设极端档才有
  5 倍优势, 都不是 30 倍。
- **生产候选集规模依据**: guard `--check-fresh` 候选 = 当日变更集(`git diff --name-status origin/main`
  的 M/D + `git ls-files --others` 的 A), 不是全仓。历史: 近 30 commit 中位 **3 个文件**、最大 **94 个**;
  近 60 commit **无 >100 文件推送**。→ 生产真实规模上批量没有优势, 仅「同目录上千条」极端场景(现实无此
  候选)批量快约 5 倍。M3 诚实定位 = fail-closed 语义 + 极端假设场景的稳健性, 不是日常提速。
- `--literal-pathspecs` 防 glob 通配符(路径含 `*`/`[` 等不会被 git 当 pattern 展开)。

### #117 M1 根因: 心跳字段语义正确化(不是告警行为变化)
- 现象: 原 rc=2 分支同时设 `STATICDATA_FAIL=1` 和 `_SKIP_NONPROD=1`, 收口心跳 `_SKIP_NONPROD` 排最前
  → 心跳写 `skip_nonprod` 盖住 `fail`(故障场景的心跳被标成 skip_nonprod, 语义污染)。
- 修法: rc=2 分支不设 `_SKIP_NONPROD`, 心跳写 `fail`(已实跑验证心跳 result=fail)。
- **真实效果注记(reviewer P2-④ 核实, 修正初版描述)**: 云上 schedule_monitor C3 白名单 =
  ("ok", "skip_oversize"), `skip_nonprod` 与 `fail` 恰都不在白名单, 且 rc=2 分支改前就置
  STATICDATA_FAIL=1 → 收口 severe notify(staticdata_backup_gate_error)本来就有, 所以**改前改后
  monitor 告警行为完全不变**。本修复 = 心跳字段语义正确化(fail 场景不再被标成 skip_nonprod),
  **不是告警行为变化**(初版报告写「云上 monitor 语义混淆 → 看不到故障, 只能靠 36h 停摆兜底」
  不成立, 已按 reviewer 结论修正)。

### L2/L3: 有意识取舍, 显式文档化(防误当 bug)
- **L2**: 非生产机 D(本地删除远端路径)永远排除 → DR 仓库只增不缩。灾备差异留档之目的, 宁可多留不删;
  远端有权删除时由生产机原逻辑 `git add -A` 处理。
- **L3**: 守卫脚本 crash(Python rc=2)或 PY 缺失(rc=127)时 fail-open 按生产机继续 best-effort, 宁留日志+告警
  不停灾备, 代价=本轮只增不覆盖判定不成立, 风险自知。若要 fail-closed 需改 rc=2 分支直接拒 git 段。
- 两处均已写入 staticdata_write_guard.py 头部 + check_fresh 分支内注释。

## 4. 自验(实跑证据, 全部 /tmp 隔离)

### #115
1. **manifest 落 staticdata 仓 + git add -A 可提交**: 在 `/tmp/sdtest-lj-116`(带 .git 隔离仓)调
   `_write_large_json_manifest(rows, "2026-09-27")` → 生成 `docs/large-json-backup-manifest.md`; `git add -A`
   成功, `git status` 见 `A docs/large-json-backup-manifest.md`, commit 成功。
2. **幂等**: 同内容重跑, md5 一致(`7916b1f0b28b080a`, 表体含 key 行数 5)。
3. **trade 仓不被写**: 生成器跑完 trade 侧 docs/ 无生成器头部(旧路径文件未被动)。
4. **STATICDATA_REPO 缺失报错**: 指向无 .git 路径 → SystemExit "✗ staticdata 仓库不存在(.git 缺失): …"。
5. **恢复侧双路径能读(两条实测)**:
   - 场景 A 新路径优先: STATICDATA_REPO=/tmp/sdtest-mf-115/staticdata → 候选顺序新路径在前, 解析 2 条
     key(带反引号格式), 含 `large-json/2026-09-27/signal_kelly_trades.json.gz`。
   - 场景 B 旧路径回退: 移走新路径 manifest → 回退 trade 仓旧路径, 解析 2 条(旧格式无反引号)。
   - 双缺失 → 返回空映射(良性回退不报错)。

### #116
1. `upload_r2.py --dry-run upload-db` → exit=1, 文案: "✗ 该命令不支持 --dry-run(upload-db 不消费该 flag)…
   请改用 R2_BACKUP_BUCKET=<不存在的桶名>"。
2. 消费方 `--dry-run upload-large-json` → exit=0, 打印 `[dry-run] 将上传 …` + `[dry-run] 将重写
   staticdata仓库/docs/large-json-backup-manifest.md(#115, N 行)`, **全程零 R2 写 + 零 manifest 落盘**
   (dry-run 后 /tmp/sdtest-lj-116/docs/ 不存在, 桶 = demo-nowhere 不存在 = 404 零污染)。

### #117 M1/M2(M1/M2 harness, 逐字抽取 async 守卫段+心跳段代码)
| 场景 | 结果 |
|---|---|
| M1: FAKE_RC_AUTH=1(非生产机) + FAKE_RC_FRESH=2(数据闸门内部错误) + STATICDATA_ALLOW_PUSH=1 | 心跳 result=`fail`(非 skip_nonprod)✓; notify dedup=`staticdata_backup_gate_error` ✓; exit 1 ✓ |
| M2: FAKE_RC_AUTH=2(顶层守卫内部错误) | notify dedup=`staticdata_backup_guard_error` ✓; 心跳 result=`fail` ✓; exit 1 ✓ |
| sync.sh 同模式(§23.3 举一反三) | 已补顶层 rc=2 降级 notify(staticdata_sync_guard_error) |

### #117 M3
- **性能自验(tester 对照表关键行, 同仓 warm 3 轮取最小, 完整 7 行表见 §3)**: 生产候选集的真实写照——
  「典型 94(历史真实大 commit 变更文件)」批量 1.108s vs 逐路径 0.784s(0.70x 逐路径快);
  「混合 50(40 真实 M + 10 远端不存在 A)」批量 0.484s vs 逐路径 0.970s(2.0x 批量快);
  「小 3(news_digest 高频文件)」批量 0.118s vs 逐路径 0.023s(0.17x 逐路径快);极端同目录 2000 才
  批量 5x。→ 真实档(≤94 条)**批量 0.48~1.11s vs 逐路径(现状)0.02~0.97s, 逐路径略快或打平,
  现行逐路径实现无性能瓶颈**。「批量快 30 倍」(指批量耗时在不同清单间的 30x 差)仅在我第一轮 bench
  的 `data/accum_nav` 类同目录集中清单上成立, 不适用于生产。
- **生产候选集规模依据**: guard `--check-fresh` 候选 = 当日变更集(`git diff --name-status origin/main`
  的 M/D + `git ls-files --others` 的 A)。历史统计: 近 30 commit 中位 **3 个文件**、最大 **94 个**;
  近 60 commit **无 >100 文件推送**。
- `_remote_last_commit_map()` 单测: 200 路径 → map 条目与候选数一致(重复路径去重), 时间戳合理
  (如 data/a-stock-1y.json -> 1790372707)。

## 5. reviewer P2 四条修复(2026-09-27 追加 commit,证据见下)

| # | 修复 | 证据 |
|---|---|---|
| P2-①(必改) | 报告「12x 加速」假数字删除(原=批量纯解析时间 vs 逐路径完整耗时,口径不一致)。**第二轮(tester 定论 2026-09-27)进一步推翻 M3 立项前提**: 批量 vs 逐路径耗时差距 100% 来自清单特征(pathspec 条数 × 目录分散度 × 路径变动频率), 生产候选集 = 当日变更集(实测 ≤94 条)非全仓, 生产真实规模(≤94 条)批量 0.48~1.11s vs 逐路径 0.02~0.97s = **逐路径略快或打平, 批量无提速优势**;「批量快 30 倍」仅 `data/accum_nav` 类同目录集中清单成立, 不适用生产(完整 7 行对照表见 §3 M3, A/B 数字已被 tester 复刻都真实, A 定性=样本对但代表性错)。M3 诚实定位 = **fail-closed 语义更保守**(整体 git log 失败→rc=2 拒绝, 旧逐路径失败是放行)+ **只起一次 git 进程** + 极端假设场景(同目录上千条)约 5x, **不是日常提速**。代码注释(staticdata_write_guard.py `_remote_last_commit_map` docstring + check_fresh 调用处)同步改准(只改文字不动逻辑) | tester 对照表(§3 M3 表 7 行) + 生产候选集规模依据(近 30 commit 中位 3/最大 94, 近 60 commit 无 >100); tester 复现材料 `/tmp/m3_bench_final.py`(正式矩阵)/`/tmp/m3_ctrl.py`(进程开销)/`/tmp/m3_check_candidates.py`(历史 commit 规模)/清单 `/tmp/m3_paths_{A,txt,2000,typical94,extreme_fn,small3,mix50}.txt` + 全仓 `/tmp/m3_lsfiles.txt` |
| P2-② | restore 侧 `_manifest_candidates` 顺序对齐写侧: STATICDATA_REPO → GIT_REPO-staticdata → trade 旧路径(原实现读侧写反成 GIT_REPO-staticdata 优先)。注释注明: 两个实际环境(mac 只设 STATICDATA_REPO / 云上只设 GIT_REPO 相邻)各自只有一条路径可达,所以方向反了没暴露;统一防未来双环境同设时读写错位 | 文本断言(STATICDATA_REPO 分支在 GIT_REPO-staticdata 之前)PASS + 双路径并存执行级测试(两路径都在时选中 STATICDATA_REPO)PASS |
| P2-③ | sync.sh 顶层 rc=2 notify 从 `2>/dev/null || true` 改 `2>&1 \| tee -a "$LOG" || true`(对齐 async 风格, notify 自身失败也要留痕 §23.11)。新增 LOG 变量(放持锁 exec 之后, exec 以 bash "$0" 重跑会重置顶部变量,此时定义才在最终执行体生效),去向=$REPO/data/logs/staticdata_sync_*.log 同 async | /tmp/sdtest-syncp2 隔离 harness(假守卫 exit 2 + notify stub): rc=2 分支跑通, notify stdout+stderr(含 notify 自身报错)均 tee 进 LOG 落盘, 不阻塞(exit 0) |
| P2-④ | 报告 M1 根因描述改准: 「云上 monitor 语义混淆→看不到故障,靠 36h 兜底」不成立。核实(schedule_monitor.sh C3 白名单=("ok","skip_oversize"), skip_nonprod 与 fail 都不在白名单; rc=2 分支改前就置 STATICDATA_FAIL=1 → 收口 severe notify 本来就有)→ 改前改后 monitor 行为完全相同。真实效果=**心跳字段语义正确化**(fail 场景不再被标 skip_nonprod), **非告警行为变化**。async.sh M1 注释同步改准 | 读 schedule_monitor.sh L1050-1080(白名单逻辑)+ async.sh 收口心跳段(改前已置 STATICDATA_FAIL=1) |

> 第 5 条你没改的理由: 无——4 条全部整改完毕, 无遗漏或有意不改项。

## 复现段

复现 #115/#116/#117 全部自验 = 按上文 §4 各条在 /tmp 隔离目录重跑(需: 一个带 .git 的临时 staticdata 仓
+/ 一个临时 trade 仓 + demo-nowhere 桶 + 假守卫 rc 环境变量)。**P2 四条复现**:
- P2-①: 重跑 tester 材料(`/tmp/m3_bench_final.py` 正式矩阵 + `/tmp/m3_ctrl.py` 进程开销对照 +
  `/tmp/m3_check_candidates.py` 历史 commit 规模; 清单 `/tmp/m3_paths_{A,txt,2000,typical94,extreme_fn,small3,mix50}.txt`
  + 全仓 `/tmp/m3_lsfiles.txt`; 只读 staticdata 仓, 3 轮取最小)。我第一轮的 `/tmp/m3_bench_fair/cold/2000.py`
  仍可复跑, 但数字只对各自清单成立、不作生产结论(引用时须限定清单)。
- P2-②: 见 §5 的双路径并存测试(临时 staticdataA + staticdataB 各带 .git 与 manifest)。
- P2-③: 见 §5 的 /tmp/sdtest-syncp2 harness(STATICDATA_SYNC_LOCKED=1 跳过持锁 + 假守卫 exit 2 + notify stub)。
- P2-④: 读 schedule_monitor.sh C3 白名单与 async.sh 收口心跳段即可核实(无需实跑)。

改动全部在本 feat 分支 `feat/staticdata-manifest-and-guard-fixes`, merge 由主控走 main-merge.sh。
前端零改动 → 不 bump 版本串、不 build_min。
