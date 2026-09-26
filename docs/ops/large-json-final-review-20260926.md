# reviewer 终审报告: 大 JSON 移出 git 两 feat 分支合并前终审(2026-09-26)

> 审查对象: feat/large-json-r2-core(HEAD 5aa4fc417) + feat/large-json-r2-restore(HEAD 2c815cac9)。
> 红线: 只读审查,测试全部在 /tmp(/tmp/final-verif 复刻 mock),未写生产 staticdata/R2,未碰 .git 写操作。

## 0. 判定: 有条件可 merge

两分支代码整体质量高,整改 4 项全部落实且经独立复验,恢复侧自洽。**无 P0/P1 阻塞项**。
merge 前需处理 2 个非阻塞 P2 条件项(均为 docs 小改,预计 15 分钟内):

| # | 严重度 | 项 | 处理 |
|---|---|---|---|
| B1 | P2 | docs/large-json-backup-manifest.md 骨架(restore 侧)与生成器头部(核心侧)信息差:骨架含「默认还原目标 trade-data/data/」「--target 覆盖」「sha256 比对中止」三要点,生成器固定头部没有 → merge 后首次 upload-large-json 整体重写把这三条从 manifest 冲掉(§22 一致性) | merge 前在 core 分支补生成器头部三条(或主控确认 merge 当天同步) |
| B2 | P2 | docs/ops/large-json-out-of-git-20260925.md 方案文档仍描述旧「deploy.sh 1.2.5 闸门」方案(§3 F 行/§6/§7/复现段),与整改后「async 提交前守卫」矛盾;check_large_json_excluded.py docstring 声称挂 deploy 链但全项目零调用(死代码) | merge 前(或当天)同步文档;merge 后挂 schedule_monitor 或归档时同步 docstring |

## A. 爆炸半径 — 整改成功,覆盖度与原方案有结构性差异(2 个低概率洞)

### A① 闸门是否真从 deploy.sh 删干净 — ✓ 干净
- commit 5aa4fc417 diff: scripts/deploy.sh | 16 ---------(整个 1.2.5 段删除,无替换)。
- git show 两分支 deploy.sh grep "large_json|check_large|excluded|1.2.5" → 零匹配;core 分支对 deploy.sh 无其他改动。
- 全 worktree grep check_large_json_excluded(.sh/.py/.md)→ 零引用,无残留调用/条件。

### A② async 守卫覆盖度 VS 原方案 — ⚠ 不等效(注释「覆盖度完全一样」不准确)
原 deploy 闸门(check_large_json_excluded.py --check)= 每次 deploy 查 staticdata git 全量 tracked >20MB,存在即 FAIL。
整改后 async 守卫(staticdata_backup_async.sh L188-223)= 只查本次待提交变更清单(git diff --cached --name-only)里的单文件:
- 覆盖: 经 async 主链进入 git 的大 JSON(step3 rsync 全量 + step4 add -A 后逐文件 wc -c,>20MB → _OVERSIZE=1 → 跳过 commit + --severe 告警 + 心跳 skip_oversize)。逻辑自洽。
- 不覆盖: 已 tracked 但本次无变更的大 JSON(迁移漏网且内容未变 → 静默占 .git 膨胀,无人查)。
- 原全量机检工具 check_large_json_excluded.py --check 整改后无任何自动化调用点(死代码),docstring 仍写「挂 deploy 链常驻拦截」→ 文档残留。

### A③ 「大 JSON 静默进 staticdata git」的洞 — 2 个,均低概率
- 洞1(相对主要): scripts/staticdata_sync.sh 是 staticdata git 第二个自动 commit 入口(intraday_snapshot.sh L202 盘中调用),add/commit/push 全 2>/dev/null || true **无守卫**(pre-existing,非本次 diff;静默吞错风格与 async 整改方向相反)。
- 洞2: async 守卫只查本次变更,已 tracked 大 JSON 无变更时不查。
- 缓解: 迁移干净后 7+1 文件全在 .gitignore 受管区块;新增大 JSON 需 >20MB 且先于区块更新进 git 才触发,概率低。
- 建议: merge 后把 check_large_json_excluded.py 挂进 schedule_monitor(每周 --check);洞1 的 staticdata_sync 无守卫走 §23.7⑤ 上报主控拍板。

### A④ 守卫告警可被 schedule_monitor 发现 — ✓ 双重
- 守卫触发: notify.py --severe --alert-issue(写 data/alerts/latest.md + 邮件)+ dedup-key 6h(async L224-233)✓。
- 心跳: 守卫分支写 result=skip_oversize(async L282-283);schedule_monitor L1058 只对 >36h 无 ok/skip_oversize 发 SEVERE,skip_oversize 不算停摆 ✓ 不误报。

## B. 逐项核整改(文件:行号 + 独立判断)

### B1. staticdata_backup_async.sh 单文件守卫(L188-223)— ✓ PASS
- 阈值单一源: _LJE_THRESHOLD=$("$PY" -c '...from large_json_excludes import THRESHOLD...' "$GIT_REPO/scripts")——从 large_json_excludes.py import,无写死数字(该文件 L56 THRESHOLD = 20_000_000)。
- import 失败不静默: 置 STATICDATA_FAIL=1(进心跳 fail + 收尾 --severe)+ echo 明确原因 + _LJE_THRESHOLD=999999999999(守卫跳过,积压字节守卫 _BYTES>500MB 仍兜底)。
- 与既有 _OVERSIZE 分支复用正确: 置 _OVERSIZE=1 + _OVERSIZE_REASON="largejson" → 同一「跳过 commit + --severe 告警 + skip_oversize 心跳」链路,文案区分 largejson(写明须跑 migrate 脚本)✓。
- 边界: >THRESHOLD 严格大于,与冻结接口一致 ✓。

### B2. migrate_large_json_out_of_git.sh(L35-42)— ✓ PASS
- 去掉 2>/dev/null || true: LIST=$(... --print) + _LJE_PRINT_RC=$?(赋值退出码=命令替换退出码,取值正确)→ 非 0 echo 原因 + exit "$_LJE_PRINT_RC" ✓。
- 新静默路径排查: git ls-files --error-unmatch >/dev/null 2>&1 是幂等跳过意图;git rm --cached 失败 → echo + exit 1;echo "$LIST" | while 只打印无状态。无新静默路径 ✓。

### B3. upload_r2.py cmd_upload_large_json(L2193-2224)— ✓ PASS
- PUT 失败(status≠200): 进 stderr,manifest_rows 不加该行 ✓;最终 ok != len(entries) → sys.exit(1) ✓。
- 成功 PUT 分支: ok+=1 + 进 manifest ✓。
- ETag 跳过分支(s3_head 200 且 etag==local_md5): ok+=1 + 进 manifest(「R2 已有同内容副本 = 真实成功」)✓。
- 源不存在: continue(不进 manifest 不进 ok)→ exit 1(不完整=失败,合理)✓。

### B4. _write_large_json_manifest(L2113-2142)— ⚠ PASS(1 个 P2 条件项)
- 固定头部含: 机制一句话 / key 格式+2 例(含 parts 例) / 保留档位(日14+周8+月12) / 恢复命令(restore-large-json.sh 四种用法) / 脚本指向 ✓。
- §22 一致性(与 restore 侧骨架对比): 骨架含生成器头部**没有**的三条——① 默认还原目标=trade-data/data/ ② --target 覆盖 ③ sha256 不匹配即中止(备份旧文件前)。生成器整体重写(.tmp + os.replace,不读原文件)会在 merge 后首次 upload-large-json 把骨架整体覆盖,三条从 manifest 消失(backup-restore.md 第八节有,信息未完全丢,但 manifest 作为恢复第一入口被降级)。
- 结论: 两文件不互相矛盾(骨架标注「自动重写勿手编」,权威=生成器),但生成器头部信息不全 → B1 条件项。

## C. 恢复脚本 restore-large-json.sh — ✓ PASS(4/5 全过,1 项未决见 E)

### C1. 超时注入 — ✓ PASS(三问全答)
- (a) 只影响恢复脚本自己: import upload_r2 前的 env 修改发生在恢复脚本自己的 python3 子进程内(heredoc),父进程/其他进程 env 不受影响 ✓;upload_r2 模块级常量(L219)在 import 时读 env → 注入时序正确。
- (b) 云上 env=600 clamp 到 10: 独立实测——R2_UPLOAD_HTTP_TIMEOUT=600 RESTORE_TEST_NETFAIL=1 --list → 错误信息「已设 10s 超时」✓;生产上传(staticdata_backup_async.sh 调 upload_r2.py 独立进程、env 未动)不受影响 ✓。
- (c) 非法值: int() ValueError → 回退 10;空串(or "10")→ 10 ✓。
- 语义: 该值=HTTPSConnection socket 超时(连接+每读写块),非整组总时长;慢速大 GET 按块 recv 不会被误砍。

### C2. skipped 非空 → sys.exit(1) — ✓ 合理
- 恢复不完整=失败语义正确: 网络失败/非法路径/sha 不匹配/解压失败汇总打印后 exit 1,调用方可感知。副作用: 单文件失败不中断同批(restore_one 返回错误串,循环继续)✓。
- 注: bad_keys 也计入 skipped → exit 1(桶里有脏对象会报失败,「宁严不宽」,恢复是低频人工操作可接受)。

### C3. 路径穿越 — ✓ PASS(两道校验)
- 第一道 parse_key: rel 非空/不以 / 开头/不含 .. 段/非绝对路径。
- 第二道 restore_one realpath: real_out == real_root 或 startswith(real_root+sep),symlink 逃逸被拦——独立实测: data/foo_parts 换成指向 /tmp/evil-outside 的 symlink 后恢复,报「目标 /private/tmp/evil-outside/t2025.json 不在根目录 /private/tmp/final-verif/data 内,已跳过」,目标外目录空,exit=1 ✓。
- 实测 EVIL_KEY(large-json/2026-09-25/../evil.json.gz): 对象格式非法被排除,正常文件照常恢复,exit=1 ✓。

### C4. 默认恢复目标 = 生产数据目录 — ✓ PASS
- DEFAULT_PRODUCTION_REPO="/Users/linhuichen/code/trade-data",default_root = STATICDATA_REPO env or 默认 + /data → trade-data/data/ ✓(用户 2026-09-25 拍板)。
- 非默认目标: --target/STATICDATA_REPO 覆盖且 ≠ 默认时打印醒目警告 ✓。
- 测试覆盖变量 STATICDATA_REPO 可用,实测全隔离 ✓(注: 覆盖 STATICDATA_REPO 时默认跟着变、警告不触发——测试者有意为之;自审报告已记录曾误写生产目录一次并清理)。

### C5. 整文件 cat 大 JSON 打印点 — ✓ 无
- grep 全部 print: 摘要/进度/sha 前缀(got[:16]),无 print(payload)/cat 大文件点。87MB 不会炸。

## D. 独立复验(自己动手,不信 agent 报告)

全部在 /tmp/final-verif(mock upload_r2 + mock manifest,复刻自主控参考 /tmp/restore-test 且脚本与 git 分支 diff 一致验证):

- D1 超时快速失败: RESTORE_TEST_NETFAIL=1 --list 0.045s 失败 exit=1,报「已设 10s 超时」 PASS
- D2 多日期 sha 不串: --date 2026-09-25 得 sep25 内容 sha fed892cc…;--date 2026-09-24 得 sep24 内容 sha 498d6cef…,各取各日期行,逐字验证 PASS(与主控参考一致)
- D3 路径穿越拒: RESTORE_TEST_EVIL_KEY=1 --all,evil key 报格式/路径非法已跳过,正常 2 文件照常恢复,exit=1 PASS

- D4 symlink 逃逸: foo_parts 换成指向 /tmp/evil-outside 的 symlink 后 --date,realpath 拦截,目标外目录空,exit=1 PASS
- D5 sha 不匹配中止: manifest sha 尾字符改错,该文件报已中止勿覆盖,其他文件照常,exit=1,原文件未被覆盖 PASS
- D6 bash -n 语法: bash -n restore-large-json.sh exit=0 PASS
- D7 deploy.sh 无闸门残留: grep 两分支 deploy.sh large_json/check_large/excluded/1.2.5 零匹配 PASS
- D8 upload_r2 语法+注册: ast.parse PASS;upload-large-json 注册于 __main__ dispatch 与 _A_CLASS PASS
- D9 notify 参数存在: --severe/--alert-issue/--alert-log 均在 PASS

## E. 未决项裁决

### E1. 加 time.monotonic 整组总时长硬上限 — 建议不加
- 现状: 10s 连接超时 × 5 次重试(1/2/4/8s 退避),单文件最坏 ~1 分钟;多文件全不可达(7 文件)累计 ~7 分钟。
- 不加理由: ① 恢复是低频人工操作,1-7 分钟可接受;用户核心诉求「快速报错不吞分钟级」已被 10s 连接超时满足(默认 30s 最坏 155s+);② 5 次重试是 upload_r2 全局特性(2026-07-30 防 R2 偶发 500 告警轰炸),硬上限牺牲偶发断连自愈;③ 复杂度不值。
- 折中可选: 恢复脚本结束打印总耗时行(不阻塞)。

### E2. 「成功/失败各 N」汇总计数 — 建议加(低成本增强)
- 现状: 失败明细 stderr 汇总,成功无计数;多文件时缺一目了然成败对照。
- 实现约 5 行: restore_one 成功计数,末尾打印「成功 N / 跳过 M」。恢复=数据安全关键操作,数字汇总值得。非阻塞,可 merge 后随 B1/B2 同步做或排期。

## F. 文档与遗留

### F1. docs/ops/large-json-out-of-git-20260925.md 需同步 — 需要(merge 前或 merge 当天)
- 现状: §3 交付物 F 行「挂 deploy.sh 1.2.5 段 FAIL 阻断上线」、§6 回滚「deploy.sh 1.2.5 闸门」、§7 操作序列第 3 条「下一次 deploy 前完成迁移,否则闸门 FAIL 阻断上线」+ 复现段,全部是旧方案。
- 新现状: 闸门不在 deploy;迁移延后不拦上线,靠 async 守卫(跳过 commit + 告警)兜底;全量机检 check_large_json_excluded 无自动化调用。
- 同步范围: 3 处段落(L45/L128/L141-142)——F 行改「async 提交前单文件守卫」;§7 第 3 条改「迁移延后 = .git 继续膨胀 + async 守卫跳过 commit 告警,无硬拦」;复现段去掉 deploy.sh 闸门命令。
- 谁改: 建议 merge 前核心侧 implementer 在 feat/large-json-r2-core 补 docs-only commit(与 B1 同批),或主控 merge 当天安排——merge 后文档必须与实际一致(§23.5 口径)。

### F2. merge 后必做操作步骤清单(按顺序)
1. main-merge.sh 合并两分支入 main(避盘后时点,安全窗口 23:00 后)。
2. 本机跑迁移: bash scripts/migrate_large_json_out_of_git.sh(硬顺序先 R2 上传确认副本+manifest,再 rm --cached;结尾人工 commit+push staticdata 仓库)。
3. 云上跑迁移: ssh 云上(带 -i ~/tdsignal.pem),先 git pull trade 仓库拿新脚本,再同款迁移(云上 ${GIT_REPO}-staticdata 仓库 rm --cached + commit + push)。
4. 机检验证迁移干净: python scripts/check_large_json_excluded.py --repo <trade仓库> 或 large_json_excludes.py --check --repo <staticdata仓库> → 期望「无 >20MB tracked 大文件」exit 0。
5. 云上确认 async 代码到位: 下次部署或手动跑 staticdata_backup_async.sh manual 验证 step3.5 区块+R2 上传输出、心跳 skip_oversize 不再出现。
6. R2 首验(恢复侧): bash scripts/restore-large-json.sh --list 应见 large-json/今日 7+ 快照(只读无风险)。
7. 死代码清理(可选): check_large_json_excluded.py 挂 schedule_monitor 或归档时同步 docstring。

## 附: 低分项(<80)已滤清单
- pipefail 注释数字过时(注释 4 处 vs 实际 6 处管道)——行为正确,上轮已滤。
- restore-side 交付报告写 .bak 用 shutil.move,实际代码 copy2——早期交付报告残留,权威文档 backup-restore.md/自审报告已为 copy2。
- 生成器写 trade 仓库 docs/ tracked 文件 → async 每跑一次 trade 仓库出现未 commit 的 manifest 改动(云上 deploy 不 commit trade docs,无并发冲突风险,可接受;merge 后观察一次)。
