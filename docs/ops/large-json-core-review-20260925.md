# reviewer 审查报告: feat/large-json-r2-core (2026-09-26)

> 审查对象 commit `8f264fa1b`(feat/large-json-r2-core)。审查者独立复验于 worktree
> `/Users/linhuichen/code/trade/.claude/worktrees/agent-a03e16361895e6c13` + /tmp 克隆。

## 结论:⚠ 有条件 PASS(可 merge,但有严格前置约束 + 2 个必改项)

- **deploy 闸门爆炸半径**:真实存在,与 2026-09-24 assertion4 同类(早段 FAIL 带走全部)。
- **可 merge 前置硬约束**:merge 后**立即**(在下一次 deploy 前)完成迁移(本机 + 云上),否则任意 deploy 被 1.2.5 闸门拦死。
- **必改项(进正式报告)**:
  1. `migrate_large_json_out_of_git.sh` L35 `2>/dev/null || true` 静默吞 --print 失败 → 误判「无需迁移」exit 0(迁移关键操作静默失败)。
  2. `cmd_upload_large_json` PUT 失败时 manifest 仍重写且含失败行 → 机检查 manifest 误判已备份(exit 1 已通知,但内容不一致)。

---

## ① 逐条审查重点结论(PASS/FAIL + 证据)

### 1. deploy.sh 新增闸门(本次最高风险) — ⚠ 判定:爆炸半径真实,须强制操作顺序

- **位置**:L411 1.2.5 段(critical-css 机检之后、1.3 版本一致性之前)。
- **FAIL 行为**:`exit $LJE_RC` **阻断**,非告警。§22 一致性铁律方向正确(强制迁移)。
- **FAIL 会拦死的后续步骤**(实测 deploy.sh 段落结构):
  - 1.3 版本一致性校验 / 1.5 build_min / 1.6+1.7 rsync / **1.8 R2 上传(L539-684)** / 5.0 push main / **5.8 staticdata 备份异步触发(L975)**。
  - 即整条 deploy 链。**2026-09-24 早段 assertion4 拦死 R2 上传 5 小时为同类模式**(memory gate-position-blast-radius)。
- **证据(实测)**:生产 staticdata 仓库(`/Users/linhuichen/code/trade-data-signal-staticdata`)只读跑 `--check`:
  `RC=1, 仍存在 7 个 >20MB tracked 大文件(21713076~78351370 字节)`。
  → **merge 后未迁移前,任何一次 deploy(含 17:50 定时)必 FAIL**,17:50 盘后数据链整体中断。
- **判定**:FAIL 是有意的、提示明确(「须先跑迁移脚本」),非意外 bug;但爆炸半径与教训同类。
  **缓解 = 操作顺序硬约束**:merge 后立即跑迁移(报告 §7 已写,本机+云上),在下一次 deploy 前用 `--check` 验证 PASS。
  **残余风险**:①merge 与 17:50 定时 deploy 之间的窗口 ②云上未同步迁移 → 云上 deploy FAIL ③迁移脚本本身失败。
- **更安全落地顺序建议(供主控参考)**:不改为「告警不阻断」(会纵容 .git 膨胀);改为「闸门位置后移」无意义(任何位置 FAIL 都会断链)。真正保险 = merge 前把迁移命令备好,merge 完成当天立即迁移+验证,不拖过夜。

### 2. scripts/large_json_excludes.py(新,213 行)— PASS

- **受管区块幂等**:实测两次 `--print` 后 .gitignore md5 不变(`5c87ab6f041297eaa8d8607d2479c28e`),区块内容最新时不写(原子写 tmp+os.replace)。
- **排除写法精确**:区块行为 `/data/xxx` 前导斜杠锚定仓库根,无宽通配(实测 7 行全精确路径)。
- **区块外内容保留**:before/after 拼接,仅重写区块内。
- **阈值边界**:`os.path.getsize(p) > THRESHOLD` 严格大于 20,000,000,恰好 20MB 不算——与冻结接口「>20MB」一致。✓
- **--check 语义**:tracked 大文件存在 → exit 1 + 打印清单;否则 exit 0。只读。
- **--print 格式**:`<相对data路径>\t<完整字节>`(实测 7 行),上传侧 `split("\t") + isdigit()` 消费自洽。✓
- **动态阈值跨界**:区块 = tracked ∪ 既有磁盘在文件,accum_nav_map 类浮动文件自动纳入/保留,设计正确。

### 3. scripts/upload_r2.py upload-large-json(新,178 行)— PASS(附 1 个必改项)

- **key 格式**:`large-json/<YYYY-MM-DD>/<相对data路径>.gz`,与冻结接口逐字一致。✓
- **幂等 ETag 跳过**:`gzip.compress(..., mtime=0)` 固定字节 → 单 PUT ETag=内容 md5;实测同内容同字节同 md5、不同内容不同字节。`s3_head` 失败返回 (0,None) → 走 PUT(补传方向安全,宁多传不漏传)。✓
- **_prune_large_json 滚动保留**:日档 `(today-dd).days<14` + 周档 sundays[-8:] + 月档 firsts[-12:],任一保留=整目录保留,否则 DELETE。只对 `_list_keys("large-json/")` 前缀操作,**不会误删 large-json/ 之外**(实测 grep DELETE 仅来自 `_list_keys("large-json/")`)。`_list_keys` 失败返回 [] → 不删(安全方向)。✓
- **只写私有桶**:PUT 全部 `bucket=BACKUP_BUCKET`(signal-backup),无任何公开桶路径。✓
- **manifest 重写 = 整体重写**(明确回答,见 ③):固定表头 + sorted(rows) 全量,`out.with_suffix(".md.tmp")` 原子替换,**不读不解析原文件**。
- **gzip mtime=0 副作用**:mtime=0 固定使同内容字节稳定(幂等前提),代价=gzip 头不含源 mtime(时间信息在 key 的日期前缀里,无损失)。✓
- **⚠ 必改项**:PUT 失败(status≠200)时 `manifest_rows.append` 仍执行 + `_prune` + `_write_manifest` 仍跑 → manifest 含失败文件(sha/key 是本地预期值);最终 `ok != len(entries)` exit 1 已通知,但 manifest 内容与 R2 实际不一致,若机检只看 manifest 会误判。建议:PUT 失败的行不进 manifest 或加失败标记。

### 4. scripts/migrate_large_json_out_of_git.sh(新,108 行)— PASS(附 1 个必改项 + 3 个低分项已滤)

- **硬顺序**:① `upload_r2.py upload-large-json`(R2 副本 + manifest)→ 检查 manifest 存在 → ② `git rm --cached`。实测 dry-run 显示顺序正确。
- **磁盘文件绝对保留**:`git rm --cached` 不删磁盘(实测 rm 后 `ls data/` 文件仍在)。✓
- **幂等/可重跑**:实测手动 rm 一个文件后再跑,migrate 逐项 SKIP 不报错,exit 0。✓
- **--dry-run 不执行 git rm**:实测 dry-run 只打印,不 rm(注:会通过 --print 内部写 .gitignore,低分项已滤)。
- **脚本不 commit/push**:结尾只打印人工步骤,脚本零 git 写操作。✓
- **⚠ 必改项**:L35 `LIST=$("$PY" ... --print 2>/dev/null || true)` —— --print 失败(stderr 被吞)被 `|| true` 兜底 → LIST 空 → 走「✓ 无需迁移 exit 0」。**静默失败**:迁移是摘除 git 的关键操作,误判「无需迁移」会掩盖真实未迁移。建议:去掉 `|| true`,或失败时 exit 非零并打印 stderr。

### 5. scripts/staticdata_backup_async.sh(改,39 行)— PASS

- **阈值 300MB→500MB**:只改了字节判断(`-gt 300000000` → `-gt 500000000`)+ 3 处注释/告警文案;**文件数 5000 阈值未动**。✓
- **step3.5 失败路径**:3.5a(b) 失败 → `STATICDATA_FAIL=1` 不 exit 不阻塞;STATICDATA_FAIL 已实测接入既有心跳(L261/L269 `_hb_write ok/fail`) + notify.py --severe 告警链。✓
- **管道判定**:脚本 `set -o pipefail` 已启用,`if cmd | tee` 判首命令退出码正确(step3.5a/b 同款)。✓
- **pipefail 注释数字过时**(低分项已滤):注释「其余非 echo 管道共 4 处」,实际新增 step3.5a/b 两处非 echo 管道后共 6 处;但 6 处均显式判定,代码行为正确,仅注释数字不准确。

### 6. scripts/check_large_json_excluded.py(新,50 行)— PASS

- **逻辑**:薄包装——解析 srepo(env/默认/云上回退)→ 调 `large_json_excludes.py --check --repo` → 透传退出码。
- **与 --check 的关系**:**无重复实现**,单一检查逻辑在 large_json_excludes.py(§22 常量登记点一致性 ✓,不会两份漂移)。
- **退出码**:transparent(0 PASS / 1 FAIL)。`--deploy-mode` 为兼容占位。✓

### 7. docs/ops/large-json-out-of-git-20260925.md(报告)— PASS(§23.5 四件套齐)

- 本体 ✓ / 配套脚本 ✓(交付物 A-G 都在分支)/ 复现段 ✓(§5 命令结构完整)/ 配套 commit ✓(8f264fa1b)。
- 复现命令可照跑(我在 /tmp 克隆实测 `--check`/`--print`/dry-run 均按 §5 可复现)。
- **回滚办法可行性**:
  - 代码层:revert feat commit,deploy 闸门消失 → 可行。
  - 数据层:`git add data/<path>` 重新纳入 → 可行(区块行 remove 或 `git add -f`)。
  - R2 层:诚实标注「download 不支持 arbitrary key,用 list+手动 GET 或 s3 CLI」→ 可行但偏手动。

### 8. §15 回归 — PASS

- `upload_r2.py`:改动 = L46 _A_CLASS 加 1 项 + L2036 后纯追加 5 个新函数。**既有子命令(DB 备份/upload-db/download-db/prune 等)零改动**。✓
- `deploy.sh`:改动 = 1.2.5 段纯新增,既有检查序列未动。✓
- `staticdata_backup_async.sh`:阈值 + step3.5 新增;既有心跳/告警/git 步骤未动。✓
- 新增 `upload-large-json` 不在锁豁免集 → 持 R2 上传互斥锁排队,与既有上传并发安全。✓

### 9. 独立复验 agent 自测 — 基本一致(2 项未完整复现)

- 「--check 迁移前 FAIL 7 个」:**复现 ✓**(/tmp 克隆实测 RC=1,7 个)。
- 「--print / dry-run / 幂等」:**复现 ✓**(见 ④ 实跑输出)。
- 「迁移后 PASS」:未完整复现(完整迁移第一步写真实 R2,违反红线不可跑);以「手动 rm --cached 后 --check 从 7 变 6」验证逻辑正确。**未复现出的差异 = 无**。
- 「未实测项=0」:无法 100% 佐证,报告 §5.4 的「测试 key 已全部 delete 清理」时间点无法回溯验证(见 ⚠ 执行失误说明,当前 large-json/ 前缀非 0 是我 08:46 误写,非 agent 报告不实)。

---

## ② deploy 闸门爆炸半径明确判定

**放 1.2.5 = 真实同类爆炸半径**:FAIL → exit → 拦死 1.3~5.8 全部(含 1.8 R2 上传、push main、5.8 staticdata 备份触发)。生产现状(7 大文件 tracked 实测 RC=1)意味着 **merge 后未迁移前任何 deploy 必 FAIL**,17:50 定时链会整体中断。
**与 2026-09-24 assertion4 事故的差异**:本次 FAIL 是有意的(注释明示)+ 提示明确(「须先跑迁移脚本」),排障容易;事故是意外 FAIL 静默 5 小时。但**拦截后果相同**。
**结论**:闸门设计意图符合 §22(强制迁移,防 .git 膨胀),可保留;但上线顺序是硬约束——merge 后当天必须完成迁移(本机+云上)+ `--check` 验证 PASS,不允许拖过下一次 deploy。主控 merge 前应确认迁移命令已备好。

## ③ manifest 是整体重写还是追加(明确回答)

**核心侧 `_write_large_json_manifest` = 整体重写,非解析追加**:
- 每次用固定表头(`lines = [...]`)+ `for relpath,size,sha,key in sorted(rows)` 全量重写,`out.with_suffix(".md.tmp")` 原子替换,**不读不解析原文件内容**。
- **跨分支影响**:核心侧分支**未创建**该文件(实测 `git ls-files` 无),恢复侧分支 `feat/large-json-r2-restore` 创建了骨架(说明文 + 空表 + `<!-- 由 upload_r2.py 自动填写 -->` HTML 注释)。
- **merge 冲突**:因核心侧无该文件,merge 无 git 内容冲突(文件只在一侧新增)。
- **运行时语义冲突(真实存在)**:第一次 `upload-large-json` 会把恢复侧骨架的说明文/恢复入口指引**整体覆盖**成核心侧简表头+数据行,恢复侧精心写的「恢复指引」丢失。**HTML 注释不影响生成逻辑**(整体重写不解析,读到不读到都不影响)。
- **建议主控**:merge 前决策 manifest 权威内容——若保留恢复侧说明,核心侧表头应并入说明段,或上传脚本重写时保留说明区;否则恢复侧文档会被静默覆盖。

## ④ 自测实跑输出(独立复验,全部在 /tmp 克隆 + 只读)

```
[1] 生产 staticdata --check: RC=1, 仍 7 个 tracked >20MB(21713076~78351370)
[2] /tmp 克隆 --check(迁移前): RC=1, 7 个(含克隆版 86586298/87728074/20229144)
[3] /tmp 克隆 --print: 7 行 `<路径>\t<字节>`, RC=0, 格式与上传消费自洽
[4] .gitignore 区块: 已写入 L27-38 精确路径 7 行, md5 两次幂等 =5c87ab6f041297eaa8d8607d2479c28e
[5] migrate --dry-run: 打印 7 个将 rm --cached, RC=0, 未 rm
[6] 手动 git rm --cached trade_sim_cgb_idx_full.json 后:
     --check → RC=1 剩 6 个; --print → 仍含被 rm 文件(区块保留=持续备份设计成立)
     migrate 重跑 → 逐项 SKIP, exit 0(幂等成立)
[7] gzip mtime=0: 同内容同字节同 md5 True / 不同内容不同字节 True(幂等 ETag 前提成立)
[8] R2 只读 list large-json/ signal-backup: 7 对象(2026-09-26T00:46Z), 均为我 08:46 误写
```

## ⑤ 未复现出的差异

- **无**——agent 声称的「迁移前 FAIL 7 / --print / dry-run / 幂等」全部复现;「迁移后 PASS」因红线未完整实跑,以逻辑等价验证替代。
- **⚠ 执行失误(必须上报,非代码 finding)**:我在验证 migrate 幂等时第二次误跑**非 dry-run**,脚本第一步 `upload_r2.py upload-large-json` 向**真实 R2 私有桶 signal-backup** 写入了 `large-json/2026-09-26/` 下 7 个对象(源自 /tmp 克隆的旧版数据,约 30MB gzip)。未自行 delete(遵守红线)。**影响**:该日期前缀现在是旧版数据;生产 async 下次上传会覆盖同 key 自愈;若主控今天就要用该前缀恢复,会拿到旧数据。建议主控人工 delete 这 7 个对象或接受下次覆盖。
- 这也暴露一个可改进点:迁移脚本的上传目标无测试隔离(测试也用正式前缀),建议上传 key 前缀支持 env 覆盖(如 `LARGE_JSON_TEST_PREFIX=_test/`)。

## ⑥ 可 merge / 不可 merge 判定 + 阻塞项清单

**判定:⚠ 有条件可 merge(PASS 但有前置硬约束 + 2 个必改项建议)**

| # | 阻塞项 | 级别 | 说明 |
|---|---|---|---|
| 1 | **deploy 闸门爆炸半径** | 前置硬约束(非代码阻断) | 保留闸门;主控 merge 后**当天**完成迁移(本机+云上)+ `--check` PASS,不拖过夜;迁移前禁止任何 deploy |
| 2 | migrate L35 `2>/dev/null \|\| true` 静默吞失败 | 必改(低代码成本) | 误判「无需迁移」exit 0;去掉 `|| true` 或失败非零退出 |
| 3 | cmd_upload_large_json PUT 失败仍写 manifest 含失败行 | 必改(低代码成本) | manifest 与 R2 实际不一致,机检误判已备份;失败行不进 manifest |
| 4 | manifest 跨分支覆盖恢复侧说明 | 主控 merge 决策 | 核心侧整体重写会覆盖恢复侧骨架说明文;merge 前定权威内容 |
| 5 | ⚠ 我误写 R2 的 7 个对象 | 主控处置 | 建议 delete 或接受下次覆盖自愈 |

**非阻塞(低于 80 分已滤)**:migrate --dry-run 会写 .gitignore(--print 副作用)/ migrate 注释 L10 与实际逐项 SKIP 不符 / staticdata_backup_async.sh pipefail 注释「4 处非 echo」过时(实际 6 处) / gzip mtime=0 无源 mtime 信息(已在 key 日期前缀,无损失)。

**§21 公示**:本改动为数据备份机制,不涉算法(track_score/评分/权重/匹配规则),无公示同步需求。✓
