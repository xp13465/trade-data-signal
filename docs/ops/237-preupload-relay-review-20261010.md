# #237 覆盖前备份护栏(客户端中转 A + D① fail-loud + D③ 巡检)独立审查报告

- 角色: reviewer(独立于实施方,全部结论基于读码 + 独立 harness 复算,不采信自述)
- 审查对象: feat 分支 `feat/237-preupload-relay`(worktree `agent-a09bf0a302d26cc09`,HEAD `de0617600`,基点 `64946a079`)
- 依据: 设计文 `docs/ops/237-r2-overwrite-backup-guard-design-20261009.md`(§4.2/§4.4/§4.5/§5.1/§5.2)/ 根因文 `docs/ops/preupload-copy-rootcause-20261008.md` / 实施报告 `docs/ops/237-preupload-relay-impl-20261010.md`
- 日期: 2026-10-10(周六休市,无生产上传窗口)

## 0. 结论

**PASS(可进 merge 流程)**。11 个审查点全部 PASS;发现 1 项 P2 + 4 项 P3 + 2 项未覆盖声明,无 A 级阻断项。
改动面收敛(仅 `scripts/upload_r2.py` / `check_preupload_backup.py` / `schedule_monitor.sh` + 3 个测试文件 + 1 文档),
主上传链(PUT 批/checkpoint/verify-etag/15 处 `_incremental_upload` 调用方)零触碰,§22 一致性对象无变化。

## 1. 审查点逐项结论与独立证据

### (1) P1~P6 与设计 §4.2 逐项符合性 —— PASS(3 处小偏差,见 F2/备注)
以 `git diff 64946a079..HEAD -- scripts/upload_r2.py` 全文 hunk 审计(仅 7 个改动区),逐条对码:
- P1 源 HEAD with_len: `st != 200 → return`(跳过,不计失败),与设计一致 ✓
- P2 减量: `bk_st==200 and local_md5 is not None and etag_s.strip('"')==local_md5` → skipped ✓(#176 语义保留)
- P3 GET: 异常/非 200/非 bytes/短读(`len(body)!=int(size_s)`)→ failed,样本 stage="GET" ✓
- P4 源校验: multipart 源(ETag 含 `-`)只比长度;单 PUT 源比 `md5(body)==ETag` ✓(边界: `etag_s is None` 时跳过校验不判失败——R2 st=200 无 ETag 属极边缘,备注)
- P5 目标 PUT: `<100MiB` 单 PUT;`>=100MiB` `_upload_multipart(..., bucket=BACKUP_BUCKET)` ✓
- P6 回读: with_len HEAD;单 PUT 比 `ETag==md5(body)`;任一侧 multipart 比 `Content-Length==len(body)` ✓
- `copied += 1` 仅在 P6 全过后执行 ✓;失败样本上限 50 + `_samples_lock` ✓
- 小偏差 1: 备份桶 HEAD 异常 → failed + 该 key 不再尝试备份(F2,旧码为 bk_st=0 继续;旧续行路径本身是坏 COPY → 无可操作回归)
- 小偏差 2: 源 HEAD 异常计 failed(旧码静默跳过)——fail-closed 可见性提升,与设计意图同向

### (2) 第一阶段零阻断(failed>0 不得阻断;C 字面量缺失) —— PASS
- 静态: `grep "failed > 0|failed>0" scripts/upload_r2.py` = **零命中**;调用点 try/except 内无 raise/sys.exit;注释明示 C 级待用户拍板(L1532-1534)
- 动态(独立 failpath harness): 打桩 `_backup_overwritten_keys` 抛 RuntimeError → 日志出现 `⚠ 覆盖前备份异常(不阻断)` + `备份完成 copied=0 skipped=0 failed=-1` 结构化行,**上传照常 3/3**(`RET=(3,3)`, `上传完成 3/3`)

### (3) D① fail-loud 回归面 —— PASS(衍生发现 F1)
独立 d1 harness 两态:
- 凭据缺失态(仅 3 个 BACKUP2_* 置空,**保持桶名 signal-backup2**): 主桶 / legacy / 不存在桶 → 老凭据且不抛错 ✓;对真实主桶只读 HEAD → st=200(无误炸)✓;backup2 → `RuntimeError(拒绝静默回退老账号)` ✓;BACKUP_LIST 路径 → RuntimeError ✓
- 凭据在位态: backup2 → 新账号主机,真实 LIST n=0 ✓
- 旧账号桶回退语义原样保留(`_route_bucket(SRC_BKT)==(HOST,AK,SK)`)✓

### (4) `_upload_multipart bucket=` 透传与主桶零回归 —— PASS(F6 声明)
- diff 确认 5 处 `s3_request` 全部透传 `bucket=bucket`(create / part PUT / abort×2 / complete),签名新增参数 `bucket=None` 默认
- 既有调用方 `_upload_glob`(L977)不传 → 默认 None → 主桶,**行为与改动前一致**;`git diff` 中 `_upload_glob` 无任何 hunk
- ≥100MB 备份写备份桶分支: 静态全链验证;真实动态未演练(当前上传集最大文件 ~87.6MB < 阈值 104.9MB,分支休眠)→ 见 F6

### (5) §5.2-7 独立复算(不许只看日志自证) —— PASS
- **真实中转 40 key**(取 data/ 最小 40 个真实 key,真 R2 双账号): `copied=40 skipped=0 failed=0`;R2 只读 LIST `landed=40`;**SET_EQUAL=True(missing=0 extra=0)**;逐 key Size 对账 **bad=0**(首跑对账脚本自家 KeyError 修复后单独复算)
- **真实引擎 e2e**(REPO 重定向 /tmp,预置状态强制增量,`_upload_glob` 打桩): 真跑 `_incremental_upload` 备份段 → 真结构化行 `[rev237e2e] 备份完成 copied=3 skipped=0 failed=0`;R2 LIST landed=3 set_equal=True size_ok=True;`NO_L3_NOTIFY=True`(未触 export-guard 告警路径)
- **真跑 checker 两态**: 日志自称 3 / R2 实见 3 → `PREUPLOAD_OK rc=0`;日志自称 3 / R2 实见 0 → `PREUPLOAD_FAIL rc=1`
- **自清**: 所有测试对象终态归零,收工前全前缀 LIST `pre-upload/` = **n=0(无截断)**;测试对象全落今日(周六休市)前缀,无生产语义污染

### (6) §5.2-2 控制矩阵独立重跑 —— PASS 9/9
自有 harness(未复用实施方测试): normal_copied / source_missing_not_failed / GET 短读 failed / PUT 403 failed / **200-but-not-landed 被 P6 兜住** / 源 md5 不匹配「源校验」failed / 减量跳过零 IO / 源 HEAD 异常 failed / 备份桶 HEAD 异常 no-backup——**TOTAL_PASS=9/9**。4 个必测场景全含且独立复现。

### (7) D③ 检查器 + 监控挂载 —— PASS(外观发现 F4)
- **零真实外发证明(§18 L48)**: 自有沙箱 harness 在检查器命名空间打桩 `subprocess.run`——T1(--dump FAIL + --notify): 拦截命中 n_calls=1,argv 与预期逐项一致(`notify.py` + subject + detail + `--tier warning --from-prefix [告警·聚合] --dedup-key preupload_backup_fail --dedup-window 21600`),notify_sent(fake enqueue 形态)→True → 打 `告警已入聚合队列`;**正向对照 T2**: 桩翻转为抛 sentinel → 被 do_notify 捕获(证明该调用就是被拦截的那次,非绕过);T3 无 --notify → **n_calls=0**;T4 `notify_sent` 真函数: enqueue→True / dedup suppress→False;T5 notify 输出失败 → do_notify=False(下轮重试)
- **判据正确(矛盾才报)**: 真 CLI `--dump` 负控: `failed=-1`→FAIL rc1;`failed=1`→FAIL rc1;`runs==0`→NO_RUN rc0(不告警);新 key 轮(claimed=0 landed=0)→OK rc0(防每周首次全量假 FAIL,设计与实现自洽);256 claimed/7 landed→OK rc0;坏 JSON→rc2
- 真跑两态(§5 已列);probe 失败→RuntimeError→rc2(独立桩验证,不静默返回 0 造「空转」假告警)
- **挂载**: `schedule_monitor.sh` L2917-2934 每 15min 块 `timeout=120` 子进程调用、**恒带 --notify**、rc 0/1/else 三分支打印;尾部 L2955 `--flush-warnings` 批发器在位;`test_wired_into_schedule_monitor` 静态锚点存在
- **r2_upload_async.sh 未联动**(未改动,也无需:检查器是独立审计通道,不参与看门狗判据)

### (8) pytest 独立重跑 —— PASS(669 passed / 2 skipped 属实)
- 命令: `/.venv/bin/python -m pytest -q <worktree>/scripts/tests/`,两种环境各跑一次(普通 + CI 垫片 env 四键),结果一致 **669 passed / 2 skipped**
- 2 skip = `test_212::test_e_pre_change_source_static`(已提交态 skip,设计内)+ macOS 平台 df 测试(存量预skip)
- stub 改动判合理性: `test_204` / `test_212` 两处 diff **仅为打桩 lambda 返回值 `None → (0,0,0,[])` + 注释**,无断言削弱;旧 None 在新调用点会被 except 兜成伪 `failed=-1` 行,改 4 元组=跟随契约,非放水

### (9) §22/§15 影响面 —— PASS
- diff hunk 全集仅 7 区: env 注释 / `_route_bucket` / `s3_request` docstring / `_upload_multipart` 签名+透传 / `_backup_overwritten_keys` 重写 / 调用点 / `_parse_upload_id` 区无实改。`_upload_glob`、PUT 批循环、verify-etag、checkpoint、marker、sigs 计算、15 处 `_incremental_upload` 调用方全部零 hunk
- 顺序不变: 备份段整体仍在 `_upload_glob` 真 PUT 批之前(静态锚 + e2e 日志序 备份→上传)
- §22: 无数据产物/展示位变化(检查器纯读);static-site/R2 主桶/CF 三处同值性无涉及;retention prune 逻辑零 hunk

### (10) retention 未动 / C 未开 / r2_upload_async.sh 零 diff —— PASS
- `_PREUPLOAD_RETENTION_DAYS = 7`: 改前 `git show 64946a079:` L1070=7 vs 改后 L1088=7,**同值**
- C 字面量零命中(见点2);`r2_upload_async.sh`: `git diff --name-only` 8 个改动文件中**不含**该文件
- `extra_headers`/`x-amz-copy-source`: 全库 grep 仅剩注释提及,无真实调用方(COPY 已从链路移除)

### (11) §9 交接 5 项核对 —— 逐项验证
1. C 第二阶段待用户拍板 —— 属实 ✓(代码注释与报告一致)
2. 容量拍板(retention 7→3~5 / lifecycle)—— 本期未动,交接准确 ✓
3. escalate 登记(alert_denoise_rules)—— 本期首报+6h 去重,未登记,交接准确 ✓
4. `test_212::test_e_pre_change_source_static` 脆弱前提 —— **复验属实**: 该测试在 `git show HEAD:`(即已提交版)上断言「改前无 `_channel_on_fail`」;#212 提交后任何 upload_r2.py 脏工作区(含本分支未提交态)都会令断言对已含新代码的 HEAD 版本执行 → 误红;干净态则 skip。仅影响开发流程,无生产影响。建议按交接所述改锚固定 rev
5. 云上落点首日观察 —— 本机已验真链路可用;云上 timer/.env 生效留待上线首日(声明 F7)

## 2. 发现清单(分级)

| # | 级别 | 内容 | 建议 |
|---|---|---|---|
| F1 | P2 | `restore-r2-backup.sh` 候选桶循环无 try/except: BACKUP2 凭据缺失环境下,候选 1(signal-backup2)经新 `_route_bucket` 直接 **RuntimeError traceback 崩溃**,而不是旧行为的「404 → 回退 legacy 桶」。触发=灾备恢复(restore) × 备份凭据缺失组合,DR 路径低概率 | 循环内对单候选异常降级为「记一行 + 继续下一候选」,或在脚本内显式捕获 RuntimeError 提示改设 `R2_BACKUP_BUCKET`;可留作后续小修,不阻本分支 |
| F2 | P3 | 备份桶 HEAD 异常 → 该 key failed 且**不再尝试备份**(旧码 bk_st=0 继续走 COPY;因旧 COPY 跨账号本就恒败,实际无可操作回归;新行为可见性更好、与 relay 各阶段失败语义自洽) | 接受现状;若要更强,可将备份桶 HEAD 异常视为「无今日备份」继续 P3-P6 中转 |
| F3 | P3 | `copied/skipped/failed` 跨 8 线程 `+=` 无锁(_fail 内 failed 同风格)。理论可丢计数;把 failed>0 全丢至 0 的概率≈0,但极端下可能少计 | 既有 #176 模式延续,影响可忽略;如需洁癖可集中计数 |
| F4 | P3 | dedup 窗口抑制时(notify.py 按设计 suppress 并 rc=0),检查器打印「notify.py 未真发出(rc=0), 下轮重试」——把「去重生效」误述为「发送失败」,误导排查 | 解析 suppress 形态,改打「6h 去重内,预期抑制」 |
| F5 | P3 | 设计文 §4.5 称看门狗为「900s 总时长硬闸」——实为 **#174 已换代**(停滞判据 900s 主 + 低速辅 + 7200s 硬兜底,`r2_upload_async.sh` L70-74);实施报告已按实际机制披露并实测真实规模 186.0s(0.727s/key),远小于停滞窗 | 以代码为准;设计文措辞可顺手更新(不在本分支) |
| F6 | 声明 | ≥100MB 备份中转分支(`_upload_multipart → BACKUP_BUCKET`)无动态演练(当前上传集最大 87.6MB,阈值 104.9MB);P6 对 multipart 目标仅比 Content-Length(不比内容) | 文件长大超阈值前后,建议补一次真·大文件备份中转演练 |
| F7 | 声明 | 云上落点未验证(PREUPLOAD_OK landed>0 首日观察点);另:日志尾窗 2MiB 若被同文件后续输出冲刷,边界是「NO_RUN 漏判」而非误报,方向安全 | 上线首日按 §9⑤ 核对 |

## 3. 关键独立重跑数字(汇总)

- 真实 40 key 中转: copied=40 / landed=40 / SET_EQUAL(missing=0 extra=0) / Size bad=0 / 耗时 12.5s
- 真引擎 e2e: RET=(3,3) / 真结构化行 copied=3 / landed=3 / upload 3/3 / 未触 L3
- failpath: 备份段 raise → upload 仍 3/3 + `failed=-1` 行
- checker: 真跑 OK rc=0(claimed=3 landed=3);FAIL rc=1(claimed=3 landed=0);负控 -1/1→rc1,runs=0→rc0,新 key→rc0
- notify 沙箱: 拦截 n=1 + argv 全对 + dry n=0 + sent 签名 enqueue=True/suppress=False + 正向对照 boom 被捕获
- pytest ×2 环境: 669 passed / 2 skipped(一致)
- 终态残留: `pre-upload/` 全前缀 n=0

## 4. 未覆盖声明

- 未做: 云上实跑检查器 / ≥100MB 真大文件中转 / restore 脚本 F1 的真实触发演练(仅代码路径推演+静态);均已在 F6/F7 标注,不伪装为已验证
- 本审查零真实外发: 所有 notify 调用链均打桩(T1-T5);真跑 checker 均无 --notify(其 dry 语义另经 T3 证明);全程未产生任何告警/邮件/飞书
- 本审查零 git 写操作(仅 `git show`/`git diff` 只读);未切分支;残留后台任务 = 无

## 5. 附:分支身份

- 审查对象 HEAD `de0617600`(feat/237-preupload-relay);注:实施报告 §9④ 与 F5 的两处「说清但不动」项均已核对为诚实披露,非隐瞒
