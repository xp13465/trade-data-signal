# #136 large_json_excludes.py fail-loud 修复 — reviewer 独立审查报告

- 日期:2026-10-01
- 被审 commit:`ed82101fd`(分支 feat/136-150-gitignore-block-20261001)
- 审查者:reviewer(独立于实施 agent 的 fresh context,未看实施侧任何中间过程,只对 commit 产物取证)
- 结论:**PASS with caveat**(2 条 P2/P3 级 caveat,不阻塞 merge,见「发现的问题」)

## 审查方法

- 全部实验在 /tmp 隔离仓(`/tmp/rev136` archive + `/tmp/rev136/repro_self` 自建仓)跑,零接触生产/镜像 staticdata 仓;
- mac 镜像 `/Users/linhuichen/code/trade-data-signal-staticdata` 仅做过只读探测(large_tracked/block_entries_exist/untracked_large_in_data/dir_exclude_files 均为只读函数,未写 .gitignore);
- 没有复用实施侧任何脚本,4 个场景全部独立构造复现。

## 必审项 1:`_parse_gitignore` 返回值契约 — PASS

函数本体(commit 内 `scripts/large_json_excludes.py:186-200`)返回三元素:

```python
return before, after, entries          # 区块内所有非空行(含注释)
return "".join(lines), "", []          # 无区块时
```

第三个元素 = 「区块内所有非空行(含注释)」,不是别的。实测(构造含注释/非 /data/ 条目的 .gitignore):

```
ENTRIES: ['# 注释A', '/data/signal_kelly_trades.json', '/data/nav_bucket/abc.json', '/foo/not_data.json']
block_excludes: ['/data/signal_kelly_trades.json', '/data/nav_bucket/abc.json']
```

- `block_excludes` 过滤条件(非注释 + `/data/` 前缀)与「受管 /data/ 排除条目」语义精确对应,与报告描述一致;
- 空文本 → `('', '', [])`;无区块 → `(全文, '', [])`;仅注释区块 → entries 非空但全为 `#` 行 → block_excludes 空。三种形态均无假绿路径。

## 必审项 2:能拦住该拦的场景 — PASS

自造「区块非空(2 条 /data/ 排除)+ data/ 未 checkout(tracked 文件磁盘删除模拟 sparse)」仓:

- 复现:先 `git add -f` 提交含区块的 .gitignore + data 文件,commit 后 `rm -rf data` 模拟 sparse 未 checkout(此时 `git ls-files` 仍列出 data 文件,与真实 sparse 镜像同构);
- 结果:`default_mode` 触发 `SystemExit`,内容为「✗ 拒绝写回 …原受管区块有 2 个 /data/ 排除条目,但本次 desired 为空…」;
- `.gitignore` 逐字节未变:`cmp` 输出 SAME;`git status` 仅 `D data/...`(删除的文件),无 .gitignore 修改。

保护在写文件之前 sys.exit,写回动作从未发生。PASS。

## 必审项 3:误伤正常场景 — 大部分 PASS,1 条 caveat(P2)

| 场景 | 独立复现结果 | 判定 |
|---|---|---|
| `--check` / `--check-staged` | main() 分派直接走 check_mode/check_staged_mode,不经 default_mode/print_mode(读 `large_json_excludes.py:366-373`),`--check` 实测只读通过 | PASS |
| 首次运行(无 .gitignore / 无区块) | `_parse_gitignore("")` → entries=[] → block_excludes=[] → 放行(实测 exit 0) | PASS |
| 区块只有注释行 | block_excludes 空 → 放行(实测 exit 0,重写为标准注释头,原行为) | PASS |
| 区块非空 + desired 非空(正常) | tracked 21MB 文件场景 → exit 0 正常写回(实测) | PASS |
| 合法变空(大文件真实删除/下架) | desired 空 + 区块非空 → 保护硬拦截,**无任何放行开关** | **P2 caveat** 见下 |

P2(新缺陷候选,置信 75):`block_excludes and not desired` 无法区分「sparse 镜像(异常)」与「业务真实清空 data/ 大文件(合法)」。
若未来某类数据整体下架/迁移导致磁盘文件全部消失,default_mode 永久硬失败 ⇒ 每次备份刷区块置 FAIL(backup/sync 均 fail-loud 到心跳告警)且区块无法写空,只能人工删区块恢复。
触发条件极罕见(生产机只有数据源灾难才会磁盘全空),属设计取舍:保护意图优先。
缓解建议(不阻塞本次):后续加显式放行开关(env `LARGE_JSON_ALLOW_EMPTY=1` 或 `--force-empty`),本次不加。
verifier:上述「sparse 复现仓」即是该分支的触发形态,已实测 exit 1。

## 必审项 4:退出码传播链全链路影响面 — PASS(已澄清关键风险)

- **硬失败不会中断整个备份流程**:`staticdata_backup_async.sh:176-181`(step3.5a)与 `staticdata_sync.sh:195-196` 都是 best-effort——失败置 STATICDATA_FAIL/SYNC_FAIL 后继续,rsync/git 段照跑;`upload_r2.py upload-large-json`(`upload_r2.py:2374-2378`)失败会 sys.exit(硬失败)且只中断 R2 上传段,backup_async.sh step3.5b else 分支(L209-217)捕获后置 FAIL 继续 git 段。
- **本改动的真实保护效果 = 拒绝写空区块本身**(sys.exit 发生在写文件前):即使上层吞掉退出码继续 `git add -A`,区块未被清空 → fund_nav 等仍被 ignore → 不回流 git。#136 事故本体被消除,不依赖退出码传播。
- **生产机不会命中**:生产机 staticdata 仓是 full checkout 且每次备份先 rsync 填充 data/(backup_async.sh L159 rsync → L176 刷区块 → L329 add -A),desired 非空 → 保护不触发。只有数据源灾难(data/ 全空)才触发——那正是保护目的。
- **实测佐证(mac 镜像只读探测)**:当前 mac 镜像 `desired total = 30396`(existing 4 + direx 30393),block_excludes 8 → 不触发。仅真 sparse(四路全空)才触发。即:修复上线后,没有任何现役路径会「每次备份都硬失败」。

## 必审项 5:#150 三问独立复核 — 三条全 PASS(与报告一致)

- 问 1(每次重生成):`default_mode` L252 `desired = set(tracked) | set(existing) | set(untracked) | set(direx)`,四路全部依赖磁盘文件存在性(逐一读过函数体:L133/L215-216/L182/L146-150)。PASS。
- 问 2(add 形态):`staticdata_backup_async.sh:329 git add -A` + L314 精准 add 分支;`staticdata_sync.sh:227 add -A` + L208 精准 add 分支;生产机判定 = `staticdata_write_guard.py --check-write-auth`(`/home/ubuntu/` 前缀,已读 L17 注释)。行号与报告完全对上。PASS。
- 问 3(侵蚀非普适):判据「刷区块在 add -A 前失效才成立」成立——正常链每次备份先刷区块再 add,新文件会被后续备份纳入 ignore,不渐进侵蚀。PASS。

## 必审项 6:同类错误面 — PASS

grep 全仓:`large-json auto-generated` 字符串 + `_render_block`/`default_mode(` 唯一写入口 = `large_json_excludes.py` 自身;
scripts/*.sh 无其他直接写区块的路径,全部经 CLI(默认模式 / `--print` / `--check` / `--check-staged`)进入,后两个只读;
`notify.py`/`backup_db.sh`/`deploy.sh` 只处理 trade 主仓 data/backups 等,不碰 staticdata 受管区块。无绕过保护的写路径。

## 必审项 7:冻结契约(§23.7) — 结论:不违规,需主控知悉 1 点

行为变更(静默写空 → 拒绝写 + 非零退出)只在「区块非空 + 磁盘大文件全消失」异常数据源场景生效,生产正常路径零变化;属于修复 2026-09-30 已实测发生的 #136 事故(fail-loud 化),非「动已上线功能默认行为」,报告已落档说明,不构成需用户另行拍板的冻结资产改动。
**需知悉点**:mac 本机若手动跑 backup_async.sh/sync.sh/upload-large-json,且镜像处于真 sparse(四路全空),现在会置 FAIL/硬失败(此前是静默写空或静默 0 文件上传)——这是修复意图,但属 mac 手动操作行为变化。

## 必审项 8:自测真实性 — PASS(独立重跑 4 场景,非复用实施侧脚本)

实施报告称 4/4 PASS。reviewer 独立构造 4 场景逐一重跑,全部与报告一致:

| 独立场景 | 复现命令(节选) | 真实输出 | 判定 |
|---|---|---|---|
| A: 区块非空+desired 空 | `python3 large_json_excludes.py --repo /tmp/rev136/repro_self/sA` | exit=1,stderr「✗ 拒绝写回…」,`cmp` = SAME | 与报告①一致 |
| B: 区块仅注释+desired 空 | 同上 sB | exit=0,区块重写为 0 排除项注释头 | 与报告②一致 |
| C: 区块非空+desired 非空(21MB tracked) | 同上 sC | exit=0,写回 1 条目(`/data/fund_nav/000002.json`) | 与报告③一致 |
| D: `--print` 失败形态(同 upload_r2.py:2374) | `python3 large_json_excludes.py --print --repo sA` | exit=1,stdout 空,stderr 含完整原因 | 与报告④一致 |

## 发现的问题(分级)

1. **P2 — 「合法变空」无放行开关**(新引入缺陷候选):保护无法区分 sparse 异常与业务真实清空,真实清空场景会被永久硬拦截(每次备份 FAIL + 人工删区块才能恢复)。触发极罕见,属设计取舍;建议后续加显式放行开关。不阻塞本次。
2. **P3 — migrate 在真 sparse 镜像上会中止**(边缘):`migrate_large_json_out_of_git.sh:37` 调 `--print`,真 sparse 时 `--print` 失败 → 中止迁移。但已确认 migrate 已一次性完成、production/mac 均不再需要(报告 L64 佐证),无实际影响。

## 低分项(<80)过滤记录

另 1 个低分项已滤:区块内非标准条目(如无前导斜杠的 `data/...`)不被 block_excludes 捕获 → 该形态下保护不触发。属 pre-existing 且非脚本产物,概率≈0,不进正式报告。

## 结论

**PASS with caveat**。核心保护逻辑正确(`_parse_gitignore` 契约相符、拦截实测有效、4 自测独立复跑全真)、影响面干净(生产正常路径不命中、best-effort 不中断备份、同类错误面无绕过)、#150 三问与报告逐条对上。2 条 caveat(P2 合法变空无开关 / P3 migrate 边缘)均不阻塞 merge。可提请主控 merge 上线;上线后建议抽查下一轮云上备份心跳,确认刷区块环节不再静默(报告「后续-遗留」同向)。
