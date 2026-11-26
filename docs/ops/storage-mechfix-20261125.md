# 存储治理三机制修复 实施报告(2026-11-25)

- 任务书:/tmp/task-storage-mechfix-20261125.md
- 方案:/tmp/codex-reports/claude-storage-cleanup-20261124-execution-plan.md §3/§6
- 复核:/tmp/storage-recheck-20261125.md + GC 反例夹具 /tmp/codex-reports/storage-cleanup-20261124-gc-fixture.json
- base commit:1128f8073c96f070c0536e3b356459e59b816364(origin/main)
- 分支/提交:`feat/storage-mechfix-20261125` @ **91dbec834ecaadad9f4b558063970b71272b7e86**(三机制)
  + **40a2da02f**(审查返工 P1-1/P1-2,见 §6);均已 push origin 同分支
- worktree:/tmp/wt-storage-mechfix-20261125(原 .claude/worktrees 会话被 429 清掉后,在 /tmp 新建隔离 worktree,同分支同 base)
- 版本串:本次未改前端源码,无 bump(版本串统一归主控 main-merge.sh)

## 1. 三块改动(diff 要点 + 行号)

### 块1 deploy.sh:RSYNC 精确排除 .r2-protected/(方案 §3.1)
- 改动点:`scripts/deploy.sh:749-761`(REPO/data -> GIT_REPO/data 那一条 rsync)。
- 只加 `--exclude=.r2-protected/` 一条;**未加** `--delete`(测试断言无该参数)、未取消任何现有
  logs/告警状态/4 个 clone 种子/*.db 排除;JSON/parquet 镜像照旧。
- 依据:11-25 复核 §5(每天 05:00 轮把 D 根 protected 抄进 C 根且不删,C 根 9286 文件/10.68GB)。

### 块2 r2_safe_write.py:GC 保守 hold 全部 nonconfirmed(方案 §3.2)
- 改动点:`scripts/r2_safe_write.py:153-160`(原 144-153)。
- 旧:仅保留 `state == unknown` / `pending_purge` / 非 confirmed pair;55 条 plain preparing
  历史及其 old_sha256 payload(103 个/0.29GiB)落在可删集合。
- 新:`row.get('state') != 'confirmed' or row.get('pending_purge')` 一律保留(覆盖 preparing/
  prepared/plain/failed/unknown 等);其 sha256/old_sha256 payload 与 pair manifest.objects 由
  既有引用闭包递归保住;**未改** HISTORY_KEEP 语义(默认 1、上限 0..16)、**未**改写任何状态。

### 块3 r2_safe_write.py:GC 回收预算与新增写入配额拆开(方案 §3.3)
- 改动点:`scripts/r2_safe_write.py:200-249`(gc 回收准入 + 清单后复核)、`232-246`
  (_file_identity/_revalidate_gc_plan)、`263`(check_capacity 仍用同一文件预算)。
- 旧:gc 在 unlink 前用 `check_capacity(全部旧文件)`;C 根 9286>8192 且 10.68GB>2GiB cap
  ⇒ 必抛 UnsafeWrite ⇒ 永远清不动。
- 新:回收准入 = ①引用已证明(上文 journal/payload/pair 全量校验,坏 JSON/缺引用/非法身份
  提前 raise)②同锁域(生产唯一调用方 store_many 在 storage_lock 内)③清单 durable 先落盘;
  并新增「清单落盘后、unlink 前」整批复核:文件集变化(计划后新引用)或待删文件身份变化
  ⇒ 整批零删除。新增写入仍由 store_many 对「保留集 + 新 writes」跑原 cap/8192/reserve;
  8192 抽为模块常量 `PROTECTED_FILE_BUDGET`(生产值不变,单测可缩值)。
- 未调大 cap、未降 reserve、未绕 CAS/purge 守卫。

## 2. 测试(scripts/tests,全本地打桩零外发)

新增:
- `scripts/tests/test_storage_deploy_protected_exclude_20261125.py`(块1)
  - 从 deploy.sh 抽同一条 rsync 逻辑命令,断言含 .r2-protected 排除、无 --delete、原排除未删;
  - /tmp 夹具先 `-n -i` dry-run 断言 protected 不被列出、normal.json/hist.parquet/nested/x.json
    被列出;再真跑断言 protected 源子树未复制、目标旧副本因无 --delete 保留、正常镜像逐字节到位。
- `scripts/tests/test_storage_protected_hold_20261125.py`(块2)
  - preparing/plain/unknown(pending_purge)/failed 历史 + new/old payload 全保留;非 confirmed
    pair 两件 + pair manifest 保留;被取代的 confirmed 历史与 payload 仍按 HISTORY_KEEP 回收;
  - HISTORY_KEEP=0 时 nonconfirmed 仍保留、状态未被改写;HISTORY_KEEP=17 越界仍拒。
- `scripts/tests/test_storage_gc_budget_split_20261125.py`(块3,方案 §6 反例对)
  - 超 cap(1B)+ 超文件预算(5)的 10 条无引用历史/payload **能回收**,日志含 reclaim-over-write-budget;
  - 回收后新增写入仍被原 cap 拦、仍被原文件预算拦(目标文件零落盘);
  - 坏 JSON 整批停;非法 payload 引用整批停;身份变化整批停;计划后新引用文件整批停;
    锁冲突不进入 GC;清单落盘失败零删除;
- 返工补:`confirmed` 行 payload 缺失整批停(缺引用反例)、nonconfirmed 行 payload 缺失只告警
    照常回收(口径锁)、树内 symlink 整批停(见 §6)。
- 共用夹具 `scripts/tests/_storage_mechfix_fixture_20261125.py`(下划线,非测试文件)。

同步登记面:
- `scripts/tests/test_253_disk_reclaim_20261028.py`:同一条 data rsync 的排除守卫补
  `--exclude=.r2-protected/` 断言(§22 同事实多登记点)。

验证结果:
- 首轮(91dbec834):新增 14 用例全过;受影响的既有 `test_r2_protected_writes_20261111`(含
  gc/容量/锁/恢复)/ `test_nav_autorecover_20261114` / `test_upload_retry_capture_fix_20261117` /
  `test_253_disk_reclaim_20261028` 共 126 用例全过;全量 `5584 passed, 6 skipped, 176 subtests
  passed in 724.83s`。
- 返工后(40a2da02f)定向:块1/块2/块3 + test_253 + test_r2_protected_writes +
  test_nav_autorecover + test_upload_retry_capture_fix + test_345_backup_followups +
  test_codex_r2_pending_handoff 共 9 文件 `173 passed, 13 subtests passed`(返工新增 1 条后
  块2+块3 单跑 15 passed)。
- 返工后全量(因改了 r2_safe_write.py 生产代码,按要求重跑):
  **`5587 passed, 6 skipped, 176 subtests passed in 736.02s (0:12:16)`,0 failed**。
- 时敏:所有夹具 mtime 用固定历史 epoch 1700000000,未写死「今天」(L51)。

## 3. 同类错误面 / 举一反三清单(§23.2③ / §23.3)
- protected 跨树复制入口:全仓 grep `rsync|cp|tar` + `/data/` → 只有 deploy.sh:749 这条宽镜像;
  staticdata_backup_async.sh 只搬 `*.db`(不涉 .r2-protected);etf/fund_score/nav_bucket 只搬
  static-site/data 子目录。block1 覆盖完整。
- GC 语义登记面:全仓 grep `R2_PROTECTED_HISTORY_KEEP|R2_PROTECTED_MAX_BYTES|capacity budget`
  → 生产实现仅 r2_safe_write.py(单一事实源);upload_r2.py 只经 SafeWriter 调用,无第二份容量逻辑;
  源码形状守卫(test_345/test_codex_r2_pending_handoff/test_release_ci_gate)不盯 gc 内容。
- 文档:docs/codex-reviews/ops-backlog-20261111/r2.md:41 描述写入路径容量语义,本改动后仍成立
  (写入仍预检并拒写);属历史 review 记录,不追溯改写(§6④)。

## 4. 边界维度清单(七轴,§5.8① / tester skill §5.3.1)
| 维度 | 测/不测 | 覆盖与理由(来源) |
|---|---|---|
| 输入域 | 测 | journal 状态值域(preparing/prepared/plain/unknown/failed/confirmed/pending_purge/pair)+ rsync 源含 protected 子树/正常 JSON/parquet/嵌套/目标旧副本。来源=块1/块2 需求点。真实 9286 文件规模不测(本机不碰生产树,用常量缩小预算等价覆盖) |
| 状态组合 | 部分测 | 测:keep+garbage 混合、非 confirmed 全状态、空 garbage 隐含于 HISTORY_KEEP=0 用例;不测:完全空树(无 journal)——无引用闭包时 garbage=全部文件,逻辑同现有用例,收益低 |
| 时序 | 测 | 清单落盘后身份变化、计划后新引用文件、清单落盘失败;并发真实多进程不测(同锁域由 flock 保证,锁冲突用例覆盖拒绝路径) |
| 上下游依赖 | 测 | deploy.sh 被 update_all/deploy 链调用 → 抽同一条 rsync 夹具执行,不真跑 deploy;store_many 写入路径 → 既有 126 用例全绿;云上 systemd 时点不测(部署归主控) |
| 极端值 | 测 | cap=1 字节、文件预算=5、HISTORY_KEEP=0/17、10 条被取代历史;8k 文件真实规模不测(理由同上,常量等价) |
| 回退路径 | 测 | durable ENOSPC 零删除、坏 JSON 零删除、锁超时零删除;代码回退 = revert 本 commit(不涉数据迁移) |
| 并发与重入 | 部分测 | store_many 内「先回收再写」路径经既有上传用例反复跑通;锁冲突用例证明拿不到锁不删;跨进程真锁竞争不测 |

## 6. 审查返工(P1-1 缺引用反例 / P1-2 symlink 反例,commit 40a2da02f)

### P1-1 缺引用整批停(兑现承诺,附口径细化依据)
- 改动:`scripts/r2_safe_write.py` gc() 在引用闭包(journal/payload/pair)构建完成、任何
  unlink 之前新增 payload 存在性校验(位于容错早退分支之后、garbage 计算之前)。
- **口径按 row 状态区分**(依据=本文件写入协议,代码注释已写):
  - `confirmed` 行:state 由 `confirm()` 在 payload 落盘并回读校验之后才置 confirmed ⇒ 其
    sha256/old_sha256 payload 必然在盘;缺失 = 缓存损坏/被外部删除 ⇒ 引用集不可信 ⇒
    `UnsafeWrite('protected payload reference missing: ...')` 整批零删除。
  - `nonconfirmed` 行(preparing/prepared/failed/unknown/plain):块2 保留的恢复锚点,
    协议本身允许「先写引用(state=preparing 落盘)→ 后存 bytes」的窗口及崩溃残留,
    payload 缺失是合法瞬态。若同样硬失败,一条崩溃残留会让此后**每次**写入
    (store_many→gc)都 raise = 生产写入整体停摆;且缺的文件本不在盘上,不回收任何现存
    引用。故只打可观测告警 `R2_PROTECTED_GC: {missing_nonconfirmed_payload..., action:
    unresolved-anchor-payload-absent-reclaim-unreferenced-only}` 并照常回收无引用文件。
- 首版曾用 `_pending_payloads` 瞬态豁免集兼容 prepare 窗口,会误伤「其它调用方 save() 后
  再 store(payload)」的同类合法序列(nav_autorecover 3 条既有用例红),故按状态口径重做并
  删除该豁免集(更少代码、覆盖全部写入方,非只 prepare)。
- 新增用例:`test_missing_referenced_payload_stops_whole_batch`(confirmed 当前 journal
  payload 缺失 ⇒ raise + 全部历史/payload 在 + 无 gc-manifest)、
  `test_missing_nonconfirmed_payload_only_warns`(nonconfirmed 缺失 ⇒ 锚点保留、无引用文件
  照常回收、stderr 有 missing_nonconfirmed_payload)。
- **如实声明**:审查建议原文是「对 kept 引用 payload 做存在性校验」;本次对 confirmed 行
  全兑现,对 nonconfirmed 行改为告警放行,理由如上(生产可用性)。此细化需 reviewer 复审确认。

### P1-2 symlink 反例用例
- 复用既有守卫(`r2_safe_write.py:130` 树内任一 symlink ⇒ UnsafeWrite),新增
  `test_symlink_in_tree_refuses_gc_with_zero_deletion`:payloads 下放 symlink ⇒ raise、
  symlink 与全部历史/payload 在、无 gc-manifest。

### 边界清单补(七轴对应)
- 输入域:补「树内 symlink」;状态组合:补「confirmed 缺 payload(硬失败)vs nonconfirmed
  缺 payload(告警放行,口径锁)」。

## 5. 残留声明
- 无后台任务残留:两轮全量 pytest 均以 `nohup ... &` 起(首轮 pid 57290 / 返工轮 pid 76613),
  都在跑完后自然退出,`pgrep` 已查无该进程;返工轮日志 `/tmp/storage-mechfix-fulltest2.log`
  (11-25 09:58 写完,0 行 FAILED/ERROR,末行 5587 passed)。无其它 nohup/harness 后台任务。
- 未动生产/本地 data/、未上云、零外发。
- 云上部署与 A 阶段 protected 清理不在本次范围(归主控);本次只阻断回涨源头 + 让 GC 生产首跑
  可在同锁域内自行回收。代码仓(GIT_REPO)里既有的 protected 旧副本不会因本改动被删(无 --delete),
  仍需 A 阶段人工清单治理。
