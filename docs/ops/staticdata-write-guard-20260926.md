# staticdata 写权限守卫 + 只增不覆盖数据闸门(2026-09-26)

> 对应 pending-features-index #114「本机(mac)非权威数据全量覆盖生产 DR 仓库根治」。
> 调研前文:docs/ops/staticdata-mac-write-path-research-20260926.md
> 配套实现:scripts/staticdata_write_guard.py(单一源)+ staticdata_sync.sh / staticdata_backup_async.sh 两写入路径接线。

## 一、根因一句话

mac(本机开发机)曾经也有 `trade-data-signal-staticdata` 仓库,mac 上跑出来的非权威数据若触发 staticdata 同步,
会把生产 DR 仓库(`trade-data-signal-staticdata`,灾备第 2 层差异日志/数据留档)整仓全量覆盖——最危险的是
`git add -A` + push 把 mac 本地旧/缺的数据覆盖掉云上生产数据,而 DR 仓库是复原/对账的依据,一旦被覆盖不可逆。

本机迁移后(本机已不再跑生产定时任务,生产全在云上,见 memory `local-dev-cloud-prod-split`),mac 的
staticdata 仓库路径与云上 `/home/ubuntu/...` 并存,代码里没有"谁是生产机"的显式判定 → 遗留覆盖风险。

## 二、C 方案三件套(结构根治)

1. **结构根治**:新增 `scripts/staticdata_write_guard.py` 作为 staticdata git 写判定的**单一源**。
   - `--check-write-auth --repo <path>`:纯函数判定 `str(path).startswith("/home/ubuntu/")` → rc=0 生产机放行;
     rc=1 非生产机默认拒绝;rc=2 内部错误。云上路径天然命中前缀,行为零变化;非生产机默认 skip git commit/push,
     仅保留 rsync 磁盘 + R2 + 降级通知。
   - `--check-fresh --repo <path>`:数据闸门(配合显式 `STATICDATA_ALLOW_PUSH=1`)。先 `git fetch origin`
     (失败即拒绝),再比对 `git diff --name-status origin/main` + `git ls-files --others --exclude-standard`:
     **A(远端不存在的新路径)放行;D(本地删除远端路径)永远排除;M(修改)要求本地 mtime ≥ 远端该路径最近 commit ts 才放行**。
     只 add 放行清单,**绝不用 `git add -A`**,从机制上杜绝"本地覆盖远端"。
   - rc 契约沿用 `large_json_excludes.py --check-staged` 风格:0=放行(列表走 stdout)、1=拒绝、2=内部错误。
2. **数据闸门**:显式 `STATICDATA_ALLOW_PUSH=1` 才进闸门;无该变量 = 非生产机默认拒绝(rc=1)。
3. **两个写入路径都接守卫**:`staticdata_sync.sh`(git 段约 L119-248)与 `staticdata_backup_async.sh`
   (git 段约 L187-…),共用 `staticdata_write_guard.py` 单一源,不复制逻辑。

## 三、失败显式铁律(§23.11)

- 任何拒绝/跳过都必须非零 rc 或明确日志 + 通知,绝不静默 exit 0:
  - sync(本机默认拒绝 / 闸门拒绝 / 闸门内部错误)→ 输出 ⚠ 行 + `notify.py --alert-issue` 写 latest.md,`SYNC_FAIL=1`(best-effort 契约保留:最终 exit 0 不阻塞调用方)。
  - async(本机默认拒绝 / 闸门拒绝 / 闸门内部错误)→ 心跳写 `skip_nonprod`(只在 mac 本地数据目录,云上 monitor 永远看不到,因为云上守卫必然通过)。
  - 内部错误(rc=2)→ 置 FAIL=1,按生产机降级继续 best-effort,并把问题顶到日志 + 通知,不掩盖。

## 四、云上行为零变化(硬约束)

- 云上 `GIT_REPO=/home/ubuntu/code/trade-data-signal` → `STATICDATA_REPO` 派生 `/home/ubuntu/code/trade-data-signal-staticdata`,
  守卫 `--check-write-auth` 对 `/home/ubuntu/` 前缀返回 rc=0 → git 段原逻辑(刷 .gitignore → `git add -A` →
  `--check-staged` → commit → push)逐字节不动。**云端定时任务(云上 systemd timer)不需任何改动。**
- 判定为纯函数(输入路径字符串 → 结论),可用假路径 `/home/ubuntu/code/...` 直测 rc=0,无需在真机建 `/home/ubuntu`。

## 五、自验实跑证据(全部 /tmp 隔离,不碰生产)

### 5.1 写权限判定(纯函数,guard 级)

| 场景 | 路径 | rc | 结论 |
|---|---|---|---|
| 云上假路径 | `/home/ubuntu/code/trade-data-signal-staticdata` | 0 | 放行,git 段原逻辑 |
| mac 真实路径 | `/Users/linhuichen/code/trade-data-signal-staticdata` | 1 | 默认拒绝 + 明确日志 |
| /tmp 隔离 | `/tmp/sd-guard-test/local` | 1 | 默认拒绝 + 明确日志 |

### 5.2 数据闸门(guard 级,隔离仓库 `.sdtest/remote.git` + `.sdtest/cloud`)

- 仅新增新路径 → 放行 1 项(`data/local_new.json`)。
- 修改文件本地 mtime(2020-01-01)旧于远端该路径 commit ts(1790421891)→ **排除**,判定输出
  `M:本地旧(本地mtime=1577851200 < 远端commit=1790421891), 排除`。
- 本地删除远端路径 → **排除**,输出 `D:不允许非生产机删除远端路径`。
- 0 项允许 → `✗ 数据闸门拒绝(0 项允许): 无远端不存在的新路径...` rc=1。
- `git fetch origin` 失败(远端不可达)→ rc=1。

### 5.3 shell 集成(sync,`/tmp/sd-guard-test/src` 假 REPO + dry-run 通知)

- **Test 1 非生产机默认拒绝**:`bash scripts/staticdata_sync.sh test-a` → 输出
  `⚠ 非生产机(...): staticdata git 写被守卫拦截(rc=1), 跳过 commit/push, 仅 rsync 磁盘 + R2 留档`,
  git log 停在 base 无新 commit,`latest.md` 写入 `非生产机staticdata git写被守卫拦截`。
- **Test 2 闸门放行(只增不覆盖)**:`STATICDATA_ALLOW_PUSH=1` → 输出
  `[数据闸门] 放行 1 项(仅新增/不旧覆盖)` → `[数据闸门 add] 成功暂存 1 项(不用 git add -A...)`,
  只 commit `data/local_new.json`(1 file)并 push;远端 tree 确认 `data/exist.json`(v1)原样未动,
  `data/local_new.json`(mac_new)新增。
- **Test 3 闸门拒绝**:仅「旧 M + D」无新增 → 输出 `⚠ 数据闸门拒绝(...), 跳过 commit/push 仅磁盘留档`,
  git log 无新 commit,`latest.md` 写入数据闸门拒绝告警。

### 5.4 语法自检

- `bash -n scripts/staticdata_sync.sh` PASS。
- `bash -n scripts/staticdata_backup_async.sh` PASS。

## 六、复现命令段(隔离环境,可安全重跑)

> 说明:`.sdtest/*` 为临时测试件(裸远端 + base 提交 + 新增文件),已清理不随 git;复现前先自行重建
> (裸仓库 + `git clone` west tree + 一个 base commit + 一个远端不存在的新文件),以下命令即本次实跑路径。

```bash
# 0) 造隔离仓库(任意 /tmp 路径均可,以下为本次实跑路径)
WT=/Users/linhuichen/code/trade/.claude/worktrees/agent-adcc2b9ce48a8d45f
PY=/Users/linhuichen/code/trade/.venv/bin/python

# 1) 写权限判定纯函数
"$PY" "$WT/scripts/staticdata_write_guard.py" --check-write-auth --repo /home/ubuntu/code/trade-data-signal-staticdata; echo rc=$?   # rc=0
"$PY" "$WT/scripts/staticdata_write_guard.py" --check-write-auth --repo /tmp/sd-guard-test/local; echo rc=$?                      # rc=1

# 2) 数据闸门(在 .sdtest/cloud 嵌套隔离仓库,origin=.sdtest/remote.git)
"$PY" "$WT/scripts/staticdata_write_guard.py" --check-fresh --repo "$WT/.sdtest/cloud"; echo rc=$?

# 3) shell 集成(非生产机默认拒绝;显式放行走闸门)
env REPO=/tmp/sd-guard-test/src GIT_REPO="$WT" STATICDATA_REPO="$WT/.sdtest/cloud" \
    PY="$PY" STATICDATA_SYNC_LOCKED=1 STATICDATA_SYNC_NOTIFY_DRY_RUN=1 \
    bash "$WT/scripts/staticdata_sync.sh" test-x

# 4) 闸门放行
env REPO=/tmp/sd-guard-test/src GIT_REPO="$WT" STATICDATA_REPO="$WT/.sdtest/cloud" \
    PY="$PY" STATICDATA_SYNC_LOCKED=1 STATICDATA_SYNC_NOTIFY_DRY_RUN=1 STATICDATA_ALLOW_PUSH=1 \
    bash "$WT/scripts/staticdata_sync.sh" test-y
```

> 隔离三要素:STATICDATA_REPO 指 /tmp 或 worktree 内测试仓库;notify 走 `--dry-run`(STATICDATA_SYNC_NOTIFY_DRY_RUN=1);
> 生产 staticdata 仓库与生产 R2 `signal-backup` 全程只读未碰。

## 七、结论

- **云上不需要任何额外动作**:路径天然命中 `/home/ubuntu/` 前缀,守卫放行,git 段行为与上线前逐字节一致。
- mac 本机:以后任何 staticdata 同步默认被守卫拦截(仅 rsync 磁盘 + R2 留档 + 通知),彻底消除"mac 非权威数据
  覆盖生产 DR 仓库";确需从 mac 显式推合法新数据 → `STATICDATA_ALLOW_PUSH=1` 走只增不覆盖闸门。
- 配套 commit:feat/staticdata-write-guard(见 §五证据),由主控 main-merge.sh 统一合 main。
