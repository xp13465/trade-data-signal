# mac staticdata 镜像替换为 blobless clone(#114 B 方案实施报告)

实施人: implementer | 日期: 2026-09-26 | 状态: 已完成并自验 4 项全过

## 一、结论总览
1. **B 方案落地完成**: mac 本地 staticdata 镜像已从 3.4G 全量 .git 换成 blobless(partial clone)镜像,.git 降至 **17M**(含 sparse checkout 拉取的少量 blob,纯 git 对象 13M),根治「3.2G 全量 fetch 老失败 + 副本停在旧版」。
2. **新旧路径**:
   - 新镜像(现役): `/Users/linhuichen/code/trade-data-signal-staticdata`
   - 旧镜像(改名保留,可回退): `/Users/linhuichen/code/trade-data-signal-staticdata-old-20260926`
3. **HEAD 与云上/GitHub 三方逐位一致**: `c8a0a46`(data backup [news-fetch] 2026-09-26_20:45 - 3 files)。
4. **替换前留档已完成并校验**: 独有 commit bundle(20.8MB,bundle verify PASS)+ 旧工作树 tar(4.9GB,31661 文件可读),均落 `~/staticdata-mirror-archive-20260926/`(持久位置,非 /tmp)。
5. **引用方影响**: 全部脚本/文档引用路径不变(镜像仍位于标准路径),无受影响方需停下;仅记录 1 个一次性工具(migrate_large_json_out_of_git.sh)在新镜像 sparse 模式下不适用的注意点,无实际影响。

## 二、任务书手法偏差说明(§23.11 不静默,显式上报)
- 任务书手法:`git clone --filter=blob:none --no-checkout` 后直接改名换位。
- **实测冲突**: 纯 `--no-checkout` 后 `git status --porcelain` 有 **31548 行 D**(index 空、HEAD 有内容,所有 tracked 文件显示 deleted),**不满足自验③「status 干净」**。
- **补一步解决**: clone 后追加 `git sparse-checkout set config docs scripts README.md NOTICE DATA_LICENSE .gitignore fetch_data.sh gen_data_manifest.py manifest.json release_db.sh` + `git checkout`。效果: 顶层文件 + config/docs/scripts 进工作树,status 干净(0 行),.git 仅 17M。data/ 目录不在 sparse 工作树,由 staticdata_sync.sh / staticdata_backup_async.sh 的 rsync 段自动创建填充(守卫只拦 git 段,rsync 段照跑)。
- 该偏差不改方案本质(blobless clone、.git 小、HEAD 一致、可回退),仅是为同时满足验收项补的一步,已在报告显式说明。

## 三、执行步骤(含证据)
### 1. 留档(替换前,顺序不反)
- **① 本地独有 commit → git bundle**:
  - 独有 commit 确认: `git log origin/main..HEAD` = 唯一 1 笔 `a2a57a0a0c data backup [manual-closeout] 2026-09-26_14:52 - 1955 files`(即 9-26 事故决定不推的那笔;base = origin/main `2532538017` 9-13)。
  - 命令: `git bundle create ~/staticdata-mirror-archive-20260926/local-unique-a2a57a0a0c.bundle HEAD ^origin/main`(注: `--not origin/main` 语法在 Apple Git 2.39.3 下误报 empty,caret 语法正常)。
  - 产物: 20.8MB。verify PASS: `local-unique-a2a57a0a0c.bundle is okay`,contains a2a57a0a0c HEAD,requires 2532538017(在 staticdata 仓库上下文验证;在 trade 仓库上下文会误报缺 prerequisite,属验证上下文问题非损坏)。
- **② 旧工作树 → tar**:
  - 命令: `tar -cf ~/staticdata-mirror-archive-20260926/old-worktree-20260926.tar --exclude='.git' .`(工作树 4.9GB 本体,git 对象已由 bundle 覆盖)。
  - 产物: 4.9GB。可读性: `tar -tf` 计数 **31661 文件**,抽查 README.md/manifest.json/data/overview.json/data/daily_brief.json 均可在列。
- 归档位置 `~/staticdata-mirror-archive-20260926/`(home 持久,重启不丢,非 /tmp)。
- **校验通过后才替换**(顺序遵守)。

### 2. 正式 blobless clone(新目录)
- 命令: `git clone --filter=blob:none --sparse --no-checkout --single-branch -b main git@github.com:xp13465/trade-data-signal-staticdata.git /Users/linhuichen/code/trade-data-signal-staticdata-new`
- 结果: .git 传输完成 13M,HEAD=c8a0a46;`extensions.partialClone=true`(promisor 生效,后续 fetch 增量小)。

### 3. sparse checkout
- `git sparse-checkout set ...`(见第二节清单)+ `git checkout` → status 0 行,工作树含顶层 + config/docs/scripts。

### 4. 改名换位(旧目录不删,改名保留)
- `mv trade-data-signal-staticdata trade-data-signal-staticdata-old-20260926`
- `mv trade-data-signal-staticdata-new trade-data-signal-staticdata`
- 旧目录完整保留(含 .git 3.4G + 全量工作树),**可随时回退**(改名回来即可)。

## 四、自验四项(全部 PASS)
| 项 | 要求 | 实测 | 结果 |
|---|---|---|---|
| ① .git 体积 | 对比原来 3.2G | 新镜像 **17M** vs 旧镜像 3.4G(缩小约 200 倍) | PASS |
| ② HEAD 逐位一致 | 与云上一致 | 新镜像 `c8a0a46` vs 云上 `c8a0a46a9`(同一 commit,三方 GitHub main 亦同) | PASS |
| ③ status 干净 | --porcelain 无输出 | **0 行** | PASS |
| ④ 归档在位可读 | bundle verify + tar 数文件 | bundle verify PASS(staticdata 上下文)+ tar 31661 文件可读 | PASS |

## 五、引用该路径的其它方清单(§23.3 举一反三)
替换前 `grep -rn "trade-data-signal-staticdata"` 全仓扫描。替换后**路径不变**(新镜像仍位于标准路径),以下均不受影响:

| 引用方 | 类型 | 替换后影响 |
|---|---|---|
| `scripts/staticdata_sync.sh`(L4/32 默认路径) | rsync + git commit/push | 守卫(staticdata_write_guard.py)拦 mac 非生产机 git 段,只 rsync 磁盘 + R2;data/ 目录 rsync 自动创建填充。无影响 |
| `scripts/staticdata_backup_async.sh`(L48 默认路径) | rsync + R2 + git | 同上。无影响 |
| `scripts/staticdata_write_guard.py`(L48 默认仓库) | 守卫判定路径 | 路径不变,守卫照常。无影响 |
| `scripts/large_json_excludes.py`(L57 默认) | 写 staticdata/.gitignore 受管区块 | .gitignore 在 sparse 工作树可写。无影响 |
| `scripts/check_large_json_excluded.py`(L36 默认) | 机检读 .gitignore | 无影响 |
| `scripts/upload_r2.py`(L2049 默认) | 读 staticdata 文件传 R2 | data/ 由 rsync 填充后即可读。无影响 |
| `scripts/gen_daily_brief.py`(L3103 注释+同步 daily_brief*.json) | rsync 类同步到 data/ | data/ 存在即可。无影响 |
| `scripts/migrate_large_json_out_of_git.sh`(L19 默认) | git rm --cached 一次性迁移工具 | **注意点**: 新镜像 sparse 模式下大 JSON 不在 index,若未来在 mac 跑会报 pathspec 不匹配。但该脚本是一次性迁移工具,大 JSON 已迁移完成,mac 不再需要 → 无实际影响(仅记录) |
| `README.md` + `docs/r2-deployment.md:49/299` + `docs/site-deployment.md:104/914` + `docs/r2-migration-implementation-report.md:29` | 文档(URL/本地路径描述) | 路径不变,无影响 |

**结论**: 无脚本依赖旧镜像的「完整工作树内容」或「本地 git 历史」特性;无受影响方需停下。

## 六、替换后运营注意
1. **日常 mac 跟进远端**: `git fetch --filter=blob:none`(blobless 增量,小),不再全量 3.2G。不要全量 `git fetch`(回老路)。
2. **data/ 数据层**: 由 staticdata_sync.sh / staticdata_backup_async.sh 的 rsync 段填充(守卫已确保 mac 不 push)。git 层面 data/ 为 sparse 外路径(untracked 不展示),属预期。
3. **云上/生产零改动**: 云上 `/home/ubuntu/code/trade-data-signal-staticdata` 与 GitHub DR 仓库全程只读(clone/fetch 之外零写),未 push 任何内容。
4. **可回退**: 旧目录改名保留,改名回 `trade-data-signal-staticdata` 即复原;归档另有 bundle + tar 双保险。
