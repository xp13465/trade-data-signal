# P1 修复审查报告:staticdata 单文件大 JSON 守卫排除已暂存删除

- 审查对象:commit `0a600cc17`(feat/large-json-guard-fix,base=main@0ee0114eb)
- 审查人:reviewer agent(role-reviewer)
- 审查日期:2026-09-26
- 结论:**可 merge(B 级修复正确,死锁在云上可解开)** + **1 个必办配套项(本机 accum_nav_map 补迁移)** + **2 个建议项(E13/E14-本机)**

## 结论先行

| 维度 | 结论 |
|---|---|
| A 修复正确性 | 通过(3/3) |
| B 守卫有没有改废 | 未改废(3/3 反向回归全过) |
| C 死锁能否解开 | **云上可解开(端到端实测走到 commit);本机不能(存在未迁移 M 大文件,需配套迁移)** |
| D 影响面 | 无第三处同模式隐患;staticdata_sync.sh 不受影响(核实成立);notify/心跳路径完整 |
| E 建议 | 2 条(标题计数口径 / 本机补迁移) |

## A. 修复正确性(3/3 通过)

### A1. `--diff-filter=d` 语义 — 实测确认
/tmp 最小仓库实测(`git init` + 提交 + `rm --cached` + `--diff-filter=d`):
- 纯删除场景:全量输出 `del.txt`,过滤后空(排除)
- 新增+删除并存:全量 `del.txt new.txt`,过滤后仅 `new.txt`(保留 A/M,排除 D)
- 结论:小写 `d` = exclude Deleted,与注释语义完全一致。

### A2. 拆分后引用点核对 — 全部用对
- `_CHANGED_ALL`(L210,全量含 D)→ **仅** L247 `_BODY`(commit body 分类,迁移删除在 body 可见)
- `_CHANGED`(L211,`--diff-filter=d` 排除 D)→ L212 `_N` / L217 `>5000` 短路 / L223-230 `wc -c` 字节循环
- `_N`/`_BYTES`/`_OVERSIZE`/`_OVERSIZE_REASON` 的所有消费点(L233 日志/L235-237 告警文案/L248 commit title/L292-296 心跳)全部落在排除 D 的口径上,一致
- 无一处把 D 混进守卫计算;body 分类用全量是刻意保留(删除也是提交内容)

### A3. `_LJE_THRESHOLD` import 失败兜底 — 实测仍完好
伪造 GIT_REPO=/tmp/git-none(import 必失败)实测:
- 日志出现「⚠ 无法从 large_json_excludes.py 读取单文件大 JSON 阈值(import 失败), 单文件守卫跳过, 置 STATICDATA_FAIL=1」+ `_LJE_THRESHOLD=999999999999` 兜底
- 大文件仍由下一层「积压字节守卫」拦住(501MB 文件 → `超阈值=1 原因=backlog`)
- 两层兜底完整,未被本次 diff 触碰。

## B. 守卫有没有改废(3/3 反向回归全过)

### B4. 新增真实 >20MB 未忽略文件 — 仍拦(实测)
/tmp 仓库放 21MB 未忽略文件 → `文件数=44 字节=22105882 超阈值=1 原因=largejson` → 跳过 commit + (dry-run) severe 告警。✓

### B5. 新增大文件 + 已暂存删除并存 — 仍拦(实测)
/tmp 仓库 = `A data/newbig.json(21MB)` + `D marker.txt` 并存 → `超阈值=1 原因=largejson`,跳过 commit。✓(删除不再误计,D 被排除后字节=2.2MB 仅新增大文件)

### B6. `>5000` 文件短路 / `>500MB` 字节分支 — 拆分后仍生效(实测)
- 5044 个文件(5001 新增 + 43 plist)→ `文件数=5044 字节=0 超阈值=1 原因=backlog`(短路生效,未跑 wc 循环)
- 501MB 单文件 → `字节=525422344 超阈值=1 原因=largejson`(追加字节判定生效)
- 口径合理:删除不增加 push 体积,不计入积压判定是正确的。

## C. 死锁能否真的解开 — 端到端实测

### C7. 模拟云上过渡态(8 个大文件已 rm --cached + .gitignore 含 8 条)→ **真的走到 commit**
/tmp 完整模拟(8×21MB 文件已提交 → rm --cached → .gitignore 排除),跑修复版脚本的关键输出:

```
[变更量] 文件数=44 字节=87915 超阈值=0 原因=无
8fdf4a6 data backup [test] 2026-09-26_13:31 - 44 files
```
(即:守卫放行 → commit 成功 → push 因无远端 rc=128 属预期 best-effort)

同构验证:修复前的旧版脚本(现 main 上)在相同过渡态上运行 → `文件数=51 字节=176246707 超阈值=1 原因=largejson` → **复现 P1 原 bug**(8 个 D 被当大文件误算),新旧对比归因明确。

### C8. commit 后再跑一次 — 幂等确认
第二次运行:`✓ staticdata 无新变更,跳过 commit`,commit 数不变。✓

### C9. commit 内容 — 删除与 .gitignore 均已记录
`git show --stat` 实测:8 个 `Bin 22020096 -> 0 bytes`(删除)+ .gitignore/config/plist 新增,记录完整。✓

## D. 影响面 / 同类错误面(§23.2)

### D10. 全项目 grep `diff --cached --name-only` — 无第三处同模式隐患
| 位置 | 用途 | 是否受影响 |
|---|---|---|
| staticdata_backup_async.sh L211 | 守卫(本次修复对象) | 已修 |
| staticdata_sync.sh L114 | 仅 commit title 文件计数 | **核实成立:无尺寸判定/无短路/无跳过 commit 逻辑,只影响标题数字,不拦提交** |
| scripts/pre-commit L14 | `--diff-filter=ACMR` | 本就排除 D,无碍 |

### D11. notify + 心跳 skip_oversize 路径 — 完整
守卫置 `_OVERSIZE=1` → L234-243 notify(--severe + --alert-issue + dedup 6h)→ L291-297 心跳写 `skip_oversize`(`_N`/`_BYTES` 均带 `${:-0}` 兜底)。拆分未漏改任何消费变量。

### D12. set -u 未定义风险 — 无新增
新增变量仅 `_CHANGED_ALL`(L210 定义 L247 使用),顺序正确;其余引用点均有兜底。

## E. 遗留观察(不改)

### E13. commit title `${_N} files` 不含删除(已实测)
迁移提交标题显示 "44 files",而实际提交含 8 个删除(共 52 个变更)。若某次提交仅有删除,_N=0 标题会显示 "0 files"。**判定:不影响功能,仅复盘误导;建议标题改 `${_N} 文件(含 N 个删除)` 或直接用 _CHANGED_ALL 计数,但不属本次必须。**

### E14. 下一次 deploy 触发 async 的行为预测
- **云上(生产实际执行 async):8 个 D 已全部 rm --cached(实测 `git diff --cached --name-only --diff-filter=D` = 8,ls-files 无 accum_nav_map)→ merge 后首次 deploy 的 async 走新逻辑 → 守卫放行 → commit(8 删除 + .gitignore + 当日 JSON)→ push → 死锁解开,severe 告警停止。** 无其他拦路条件(notify/push 依赖均在位)。
- **本机(不跑定时任务,仅手动 deploy 触发):存在 `data/accum_nav_map.json` 26MB 仍是 M 状态(迁移时 <20MB 未列入,现在数据长大到 26MB)→ 守卫会正确拦截(它是真实的未迁移大 JSON)→ 本机死锁不解除 + severe 告警。** 必办配套:本机再跑一次 `bash scripts/migrate_large_json_out_of_git.sh`(幂等,现在会列出 accum_nav_map)→ 或手动 `git rm --cached data/accum_nav_map.json`(磁盘保留)。

## 审查中发现并需上报的事故(诚实标注)

**审查过程中我在本机生产 staticdata 仓库上误跑了一次真实 async 流程**(原版脚本路径后未带全 env,缺 REPO/STATICDATA_REPO 覆盖 → 落到默认生产路径)。影响与处置:

| 项 | 实际影响 | 处置建议 |
|---|---|---|
| R2 大 JSON 备份(large-json/2026-09-26/ 8 文件) | 提前完成了今天的常规备份(幂等,内容同源) | 无需处理 |
| 生产 .gitignore | large_json_excludes.py 幂等重写(8 条不变) | 无需处理 |
| 生产 staticdata git index | 暂存了 rsync 新拷入的 ~1900 个 JSON(下次 async 本来也会 add,行为=常规备份) | 无需处理 |
| 生产心跳文件 staticdata_backup_heartbeat.json | 被覆盖为 `skip_oversize 13:26:56`(此前应为 ok/无文件) | 云上今晚 17:50 deploy 的 async 会重写;本机如担心可手动重跑一次 async(需先做 E14 本机迁移) |
| 生产日志 | 新增一份 20260926_132526.log | 无需处理 |

**根因教训**:审查任务要求「一切测试在 /tmp」,但我第一步跑脚本命令时忘记带全部 env 前缀,默认值落到生产路径。后续每步(step+8~+18)均显式带全 env,未再发生。本事项已如实记录,不逃避。

## 审查批次说明
- 改动范围:仅 `scripts/staticdata_backup_async.sh`(15+/6-),不涉算法/数据产物/公示文案,§21/§22/§5.1 防线无需触发。
- 全部测试在 /tmp 完成,生产 staticdata 仓库除上述误跑事件外无其他写操作。
