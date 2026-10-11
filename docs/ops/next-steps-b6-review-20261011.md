# B6 独立审查报告:verify-r2 周日 full 模式 UnboundLocalError 热修(reviewer)

- 日期:2026-10-11(周日) / 审查人:reviewer agent(fresh context,未参与实施)
- 审查对象:分支 `fix/verify-r2-full-standalone` @ `a6154e2dd`(修复 `525a226c9` + 证据补提交 `a6154e2dd`;base `11776c31b`,merge-base 复核一致)
- 方式:独立复跑关键证据(不采信实施报告)+ static-only 探针;未真跑生产 verify-r2(红线,留今晚 22:30 #220 force_full 窗口);全程零真实 R2 写 / 零真实外发
- **总判定:PASS — 0 条 must-fix;观察 2 条(不阻塞);低分已滤 4 条(<80,见 §9)**
- 残留后台任务(本报告作者执行侧):**无**(本次审查全程无 `moved to the background` 事件;另见他 agent 在跑 pytest 进程,§8 观察①,非本分支产物)

## 0. 影响面清单(改动文件被谁引用)

| 改动符号 | 引用方(实查) | 影响判定 |
|---|---|---|
| `cmd_verify_r2()` | `scripts/r2_upload_async.sh:254`(`run_r2_upload "verify-r2" 7200`)→ 云上 deploy 链;失败 → `R2_FAIL` → deploy 收尾 notify | 调用契约(exit 码/stdout 格式)不变;仅解锁 full 崩溃路径 |
| `_load_standalone_keys()` | 全仓唯一业务调用方 = `cmd_verify_r2`(fix@L3638);`scripts/test_188_s06_sync_blindspot.py:112` 调缺省形参 | 新形参默认 `True` = 旧行为逐字不变 |
| `standalone_files` | 全仓仅 `upload_r2.py` 5 处 + 新单测;无其它文件/函数同名(grep 实查) | 无跨模块读者 |

旁证:`scripts/sync_dev_from_r2.sh` 的「verify-r2 只读版」为自实现归一化对账,不调用本函数(L143-150 读证);`check_r2_channel_coverage.py` 仅引用 `_R2_CHANNELS` 口径,不引用本函数。

## 1. 平日路径行为等价(最重要)— PASS

静态读证(对 origin/main 版逐行对照,main@3640-3690 vs fix@3638-3700):

- `standalone_files` 计算搬位:旧 `else` 分支内 `standalone_files=[]; if standalone_keys: [comprehension]` → 新 `if full/else` 之前裸 comprehension。空台账两者结果同为 `[]`;非空为同一表达式;两位置之间无对 `files`/`standalone_keys`/`r2_prefix`/`local_dir` 的写;唯一读者(print@L3694 / merge@L3699-3700 / `_std_set`@L3747)均在新赋值点之后。full 分支 `to_check = files` 未变(未把 standalone 并入,无重复计数)。
- 台账加载:旧「非 full 才调 `_load_standalone_keys()`」vs 新「恒调 + `ledger_state = None if full else _ledger_state`」→ 平日两值完全相同;加载位置均在通道循环前。
- `warn=not full` 平日 = `True` = 旧缺省(旧函数无该形参、4 条 stderr 文案恒打,等价)。
- `ledger_state` 仅平日:full 置 None 使收尾「台账退化」告警分支(L3827)跳过——旧 full 从不加载、也从不进该分支,等价;平日进入条件与取值不变。

差分复跑证据:

- 同一 weekday 场景(mismatch + 台账含 1 key + 抽样空)在 **main 树(origin/main 全树抽出)与 fix 树**分别跑,stdout 全部 `[verify-r2]` 行 `diff` 为空;测试断言(对账对象集合、层4 告警 subject)两树均绿。
- 两条平日回归单测(`test_weekday_standalone_still_selected_and_alert` / `test_ledger_missing_weekday_alert_unchanged`)在两树均 pass。

→ 结论:平日路径零行为变化(唯一差异面全部落在 full)。

## 2. full 分支新语义正确性 — PASS

- full+mismatch:不再崩;`standalone_files` = 本通道文件 ∩ 台账 → `_std_set` → `stale_here` → 累计 → 收尾层4「独立链产物与 R2 脱节」告警(与 #188 告警文本语义一致:「某排期上传链连续失败…靠我这次全池兜底才补上」正是周日全量场景)。
- 亲跑观察:fix 树 full 场景 stdout 出现 `[verify-r2] ⚠ 独立链产物与 R2 脱节: data/kelly_mode_s06_state.json`;新单测断言该告警 subject 发出(pass)。
- 修法方向选择(full 保留记名 vs B4a 备选「full 补 `[]` 静默」):已在实施报告 §2 显式记录选择理由,信息对主控可见;保留 #188 设计语义,判定合理(§23.7 层面:属修复崩溃 + 恢复原设计,已披露)。
- 边界:full+台账缺失 → `warn=False`(无 stderr 误导文案)+ 不发「平日退化」告警(周日覆盖面不受台账影响);周一自然恢复告警 → 无误报、无持久盲区。
- 代价:full 模式现无条件计算一次 comprehension(每通道 O(n) 小常数,内存级,可忽略)。

## 3. 负控 / 变异独立复跑(全部亲跑,不采信原报告)— PASS

| 项 | 复跑方式 | 观察(实测) |
|---|---|---|
| ① main 版跑新单测 | origin/main 全树抽到 /tmp 后跑新单测 | **2 failed / 4 passed**;核心用例失败栈 = `UnboundLocalError … upload_r2.py:3730`(与生产同栈);另一失败 = `warn` 形参 TypeError |
| ② fix 版 | 工作树跑新单测 | **6 passed**(0.10s) |
| ③ test_188 | 两树同跑 | fix 树 **1 passed**(11.11s);**main 树 1 failed**(同 L3730 UnboundLocalError)→「修复前必挂」亲验成立 |
| ④ 关联既有测试 | test_193 + test_212 同跑 | 43 passed / 1 skipped(与实施证据一致);skip 亲验 =「已提交态自动 skip」设计(test_e_pre_change_source_static) |
| ⑤ 全量 pytest 3 failed 归因 | test_245 两树同跑 | 两树同 **2 failed / 36 passed** → 确认 pre-existing(日期敏感,属 B7 任务),非本改动引入 |

## 4. 同类错误面抽查(§23.2③)— PASS(delta 亲验 + 6 候选抽判)

- 独立复跑 AST 近似流扫描(`/tmp/b6_ast_scan.py`,static-only 读文件):main 61 条 → fix 60 条;**归一化行号后:main 独有 =(`cmd_verify_r2`,`standalone_files`)恰 1 条,fix 独有 0 条** → delta=1 指向病灶、未引入新候选,与实施报告一致。
- 抽 6 候选判假阳(逐一到源码核赋值序):`_upload_multipart.etag`(fix@L867 赋→L868/869 读,同块)/ `.err`(L870 赋→L871 读)/ `cmd_upload_large_json.{relpath,raw,size,st,payload,e}`(全在嵌套 `_upload_one` 内,赋值先于读)/ `_upload_glob.{rel,key,size}`(嵌套 `_upload_one`)/ `_incremental_upload.{changed_rels,done_map,rel}`(嵌套函数参数读)/ `cmd_verify_r2.ok`(嵌套 `_check` 的 if/else 两臂均赋值)→ **全部假阳成立**,归因合理(扫描器把嵌套函数体内的读按外层 bound 判 = 主假阳类)。

## 5. 零外发自证复核 — PASS(附覆盖范围诚实标注)

- 陷阱生效亲证:ZeroOutboundTrap 对 `urllib.request.urlopen` / `smtplib.SMTP` 均在真实连接前 raise + 记账(先证打桩生效,§18 L48)→ 实测 TRAP-EFFECTIVE-OK。
- 6 条新单测在陷阱内运行且 `trap.hits==[]` 断言全绿(亲跑);test_188 同带该类断言。
- 诚实标注(复核实情):该陷阱**不覆盖 `http.client`**,而 upload_r2 的真实 R2 出口走 `http.client.HTTPSConnection`(L337/603/691… 读证)——本测试「零 R2 接触」的真实依据 = 显式打桩,非陷阱。静态枚举 `cmd_verify_r2` 全部出口调用点仅 4 类:`s3_head`×2 / `_upload_glob` / `notify.*`(3 组) / `_uniform_sample`;测试中对 `s3_head`/`_upload_glob`/`_uniform_sample`/`notify` 全被替换 → 无 R2 出口可达。加载侧亦证:测试环境 `REPO`/tempdir 下 `STATIC_DIR`(L51 import 时取 REPO)与台账路径全落 tempdir,未触真实 `data/`。
- (与陷阱自身 docstring 的「R2 写入由各脚本自身打桩承担,不在本工具范围」一致;实施报告措辞可再显式,属低分项已滤。)

## 6. diff 面核对 — PASS

- `git diff --name-only origin/main...HEAD` = 恰 3 文件:`scripts/upload_r2.py` / `scripts/tests/test_verify_r2_full_standalone_20261011.py`(新)/ `docs/ops/next-steps-b6-verify-r2-hotfix-20261011.md`。无根 `data/`、无意外文件。
- 分支组成 = base `11776c31b` + 2 commits(`525a226c9` 修复 / `a6154e2dd` 证据);commit message 均带 Co-Authored-By 尾行。
- 新单测挂链确认:`.github/workflows/ci.yml` 门禁⑧ `python3 -m pytest -q scripts/tests/`(L123)→ 新文件必被 CI 收集。
- 审查时 origin/main 已前进至 `6cd81e3db`(仅 TASKS.md + 1 docs),不碰 upload_r2/测试 → merge 无代码冲突面;并行分支:B7 仅 test_245 + 其报告;`feat/b3-fundnav-cleanup` 仅 `r2_delete_prefix.py`(与 upload_r2 无互引,grep 实查)→ 无「后覆盖前」风险。

## 7. 报告质量 — PASS

- 交付面齐:病灶/根因/修法/复现/变异/单测清单/全量 pytest 归因/同类错误面/举一反三/复现命令/红线/上报(§8)。
- 「未真跑生产 verify-r2(留 22:30 自然窗口)」留白合理 = 红线要求,且纸面证据链闭合(生产 02:16/05:11 证据有 B4a 云上独立取证佐证:`docs/ops/next-steps-b4a-cloud-20261011.md` §附)。
- 「残留后台任务」首行声明格式合规(声明无残留 + 说明唯一后台 ID 已退出)。

## 8. 观察与上报(不构成 finding)

①(供主控知悉)存在他 agent 在跑的全量 pytest 进程:PID 65450,`-m pytest -q scripts/tests/`,10:15:57 启动,cwd = worktree `agent-a8ea4e5bafe3eb0da`,PPID=1(孤儿化)。**非本分支产物**(本分支实施方全量 pytest = ID `bm5b9wuxx` 已退出),疑似另一在跑任务;B6-review 未动它(kill 需 PPID 属主链核实,非本审查范围)。

②(merge 时点提示)今晚 22:30 #220 force_full 是自然真验证窗口;若届时云上未同步本修复,周日 full 将再次崩(生产已两打)。建议主控把 merge + 云上同步排在 22:30 前,或相应调整 #220 时点。

## 9. 低分已滤(<80,共 4 条;列出供主控追问)

1. 实施报告 §5「假阳类别」表述与扫描器最终版输出不完全对应(如「try 惰性 import 的模块名」类在复跑输出中不存在;实际主类 = 嵌套函数体读)——归因结论(残余全假阳)不受影响。
2. 报告/测试 docstring 中 ZeroOutboundTrap 与「零 R2 接触」的表述可按 §5 精确化(陷阱不覆盖 http.client)。
3. 复现脚本放 /tmp(非持久)——持久复现已由提交的 CI 单测承担,无实质影响。
4. 报告 §7 复现命令依赖本机 venv 绝对路径与仓库根 cwd,换机需调整(可读性)。

## 10. §23.7 / §23.11 专项

- §23.7(冻结契约):改动 = 修崩溃 + 恢复 #188 原设计语义;方向选择已在实施报告 §2 显式记录(主控可见),无未上报的默认行为变更。
- §23.11(绝不静默):全程 git 无冲突/覆盖/倒退事件(merge-base、diff 面 3 文件、并行分支清单均核)。

## 11. §21 公示 / §22 一致性 / C 级数据校验 — 适用性判定:不适用

本次无前端算法/公示文案(purpose-notes.js/app.js/lab.js)改动面(§21 不适用);不产出任何数据产物、不改展示位数据(§22 不适用;C 级数据完整性校验因「零数据产物」不适用)。按影响面圈定的 smoke = 新单测 + test_188 + 平日差分(均已跑);首页/信号等 P0 主功能数据层不受本改动影响。真弹性验证 = 今晚 22:30 生产窗口。(docs/smoke-checklist.md 实查未列 verify-r2/upload_r2 — 不适用判定有据)

## 12. 总判定与 merge 建议

- **PASS,可 merge**(0 must-fix;平日等价 / full 新语义 / 负控变异 / 同类面 / 零外发 / diff 面 / 报告质量 七项全过)。
- merge 由主控执行;建议纳入 22:30 #220 时点约束(§8②)。
