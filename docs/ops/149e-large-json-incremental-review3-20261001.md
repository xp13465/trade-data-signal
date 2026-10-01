# #149e P2-1/P3-1 补修独立复审报告(第三轮)— PASS-with-caveat

commit: `f37b130c6`(feat/149e-large-json-incremental-20261001,44b6679e7 之上第 2 个 commit) | 审查: reviewer(独立复现,未改代码)
复现环境: `git archive f37b130c6` 导出 /tmp/rev149e3 隔离运行;回归脚本指向新代码独立重跑

## 结论: PASS-with-caveat

P2-1(源缺失从静默漂移回可见告警 + 批量/全量升格 fail-loud)方向正确,核心目标(目录级损坏/批量缺失该喊就喊)已实现;阈值边界 10 用例实测与声明一致、升格路径零状态副作用实测闭环、四组回归脚本指向新代码独立重跑无回退、P3-1 六处口径全标注。两个 caveat(非阻塞):①零星缺失告警在生产调用链里被 async `tail -20` 截断,LOG 不可见;②升格置 STATICDATA_FAIL=1 后,结尾 notify 走 #123 R4 分级,单日首次可能被降级 info 不推送(有 LOG/dashboard/心跳兜底)。

---

## 1. [最高优先]「可见」是否真的可见 — 升格异常:是 / 零星缺失:否(caveat)

### 链路逐层查清
- `staticdata_backup_async.sh` L192-194:upload_r2 经 `with_lock.py --nb` 包 `bash -c` 调用,输出 **显式重定向** `>"$_R2_TMP" 2>&1`(mktemp 临时文件)→ stderr **不丢**(不依赖 systemd-run;systemd-run 只负责启动脚本,脚本内部重定向优先)。
- 成功(exit 0)分支(L198-200):`tail -n 20 "$_R2_TMP" | tee -a "$LOG"` → **只取尾部 20 行进 LOG**,临时文件随后 `rm -f`。
- 失败(exit≠0)分支(L202-204):「失败(exit=N)」+ `tail -n 20` + `STATICDATA_FAIL=1`。

### 实测(构造输出走真实 if/grep/tail 逻辑)
- **升格场景(exit≠0)**:LOG 完整可见——「⚠ upload_r2.py upload-large-json 失败(exit=1),不阻塞」+ 逐条缺失告警 + 汇总「缺失 2」+ 「✗ 源文件缺失异常(50/100)」全在(升格在 scan 后立即退出,无上传输出冲尾部)。且 STATICDATA_FAIL=1 → 结尾 notify(L457)。
- **零星缺失场景(缺 1-2,exit 0,changed≥20)**:LOG 尾部 20 行全为上传进度,头部逐条缺失告警 + 汇总「缺失 N」**被 tail 截断丢弃**——用户/LOG 完全看不到。实测坐实(30 行上传输出冲掉头部 3 行缺失信息)。

### 明确结论
升格异常「可见」= **是**(LOG + STATICDATA_FAIL → 告警链);零星缺失「可见」= **否**(逐条告警技术上有,但生产调用链将其截断丢弃)。零星缺失是良性竞态(双进程并发/文件替换窗口),设计上不报警邮件轰炸,其可见性缺失不构成「改动等于没做」;但实施方「逐条告警可见」的表述对零星场景不成立——建议后续把汇总行「缺失 N」在成功分支也固定进 LOG(如 tail 前先 grep 缺失行写 LOG)。

## 2. 升格非零退出下游语义 — 符合 #149②③,不会误判/中断
- ① **不误判锁占**:锁占 = with_lock --nb exit 0 + stderr「已被占用」(async L195 grep 在 **if 分支**);升格 exit≠0 走 **else 分支,不 grep**。三态判定无串味。
- ② **不中断灾备**:else 仅 `STATICDATA_FAIL=1` + 打印,脚本继续 → L210 `exec` 重入 git 段照跑。
- ③ 与 #149②③ 设计一致:STATICDATA_FAIL=1 不阻塞,结尾 L457 notify `staticdata_backup_fail`(--severe,--dedup-key,--dedup-window 3600)。
- **明确结论**:是,符合设计。

## 3. 升格路径状态副作用 — 实测闭环,下轮正常增量
独立实测(真实代码 + s3 mock,非 dry-run):
1. 首跑全量:100 PUT,state 写入,marker 正常删除。
2. 升格(缺 50/100):`SystemExit ✗ 源文件缺失异常(50/100)...`,之后 **marker 不存在(未写)**、**state 保留旧版原文未覆盖**(读到内容与升格前逐字节相同)。
3. 恢复全文件后再跑:内容未变 → 0 新 PUT(增量判定生效),state 仍在。
→ **下轮不会退化全量**(marker_stale=False + state_ok=True),fail-closed 语义成立:升格是干净放弃(无 marker 残迹、不伪装成功),下轮重新 scan,缺失持续存在则每轮都喊。

## 4. 阈值边界实测 — 10 用例全过,无 off-by-one,分母明确
独立构造(真实 cmd_upload_large_json,subprocess 打桩 + 模拟 staticdata 仓,dry-run 路径):

| 场景 | 观测 |
|---|---|
| 全集1000 缺0 | exit 0(不升格) |
| 全集1000 缺50(恰好绝对判据) | 升格(50>=50) |
| 全集1000 缺49 | 不升格(49<50 且 49<5%) |
| 全集1000 缺1000(全量) | 升格 |
| 全集60 缺3(恰好 5%) | 升格(3>=3.0,>= 含边界) |
| 全集60 缺2(3.3%) | 不升格 |
| 全集40 缺3(7.5%,全集<50) | 不升格(5% 判据要求全集>=50,绝对判据 50 远超全集——设计意图:小数据集零星容忍) |
| 全集50 缺3(6%) | 升格 |
| 全集50 缺49(98%) | 升格 |
| 全集1 缺1(全量) | 升格 |

分母 = `len(entries)`(large_json_excludes.py --print 清单全集),非磁盘存在数——实现与声明一致,`>=` 含边界无 off-by-one。

## 5. 回归不回退 — 四组脚本指向新代码独立重跑全 PASS
- /tmp/149e_t5.py → PASS(周日 weekday=6 强制全量 HEAD,内容未变 0 PUT)
- /tmp/149e_t_envfull.py → PASS(R2_LARGE_JSON_FORCE_FULL=1 强制全量)
- /tmp/149e_t_deg.py → PASS(状态损坏 JSON/结构不认/状态缺失 → 全量,不静默空跑)
- /tmp/149e_review_extra.py → T3 PASS(marker 残留→强制全量 HEAD + 正常结束 marker 删除)、T4 PASS(源缺失零星 2缺1 → 不 sys.exit、a 仍上传、b 从状态 files 抹除——新语义下缺 1 不升格,一致)。**T5 段脚本自身报 `TypeError: cannot set 'now' attribute of immutable type 'datetime.datetime'`**——是脚本直接给 datetime 类赋值所致,旧代码同样报错,与本次改动无关(同场景 t5.py 用 mock.patch 正解,PASS)。
- 五条不变量(周日强制全量 / env 强制全量 / 状态损坏退化全量 / marker fail-closed / 内容未变 0 HEAD 0 PUT)全部保持 PASS,无回退。

## 6. P3-1 — 到位
grep 当前报告 docs/ops/149e-large-json-incremental-20261001.md:含 36.5/37.x 的 4 处(L27 表格「36.5s 为采样 2000 文件推算(非全量实测;真实全量实测 37.4s…)」/ L37 结论「≈37.5s(36.5s 为采样推算,真实全量实测 37.4s/37.9s)」/ L92 复现「37.9s…审查方独立复现 37.4s,抖动一致」/ L137 复现段「36.5s(采样 2000 推算;全量实测 ≈37.5s)」)+ 另 2 处已改「~37s(实测)」无裸 36.5 残留。36.5s 采样推算 + 37.4~37.9s 全量实测口径清晰,不再误导。全量 3 万文件实测数字无法在本机独立复现(需生产 staticdata 仓),但口径标注完整,不构成问题。

## 7. 新问题排查 — 无串味、无刷爆;一个新交互(caveat)
- **上万文件缺失刷爆日志**:逐条告警进 $_R2_TMP(mktemp,随后 rm),LOG 只 tail -20 → **不刷爆 LOG**;升格时上万行缺失在 LOG 只留尾部 20 条 + ✗ 消息,可接受。
- **sys.exit 消息与 grep「已被占用」串味**:升格 exit≠0 走 else 分支(不执行 grep),消息「✗ 源文件缺失异常(...)」不含「已被占用」→ **无串味**。
- **新交互(caveat ②)**:升格 → STATICDATA_FAIL=1 → 结尾 notify(`staticdata_backup_fail`)→ notify.py R4 分支(21600s 强制窗 + r4_staticdata_grade 分级):连续≥2 天未追平 → severe 直发;**单日首次(迁移期一次性)→ info 只记 dashboard 不推送**——升格首日用户可能无邮件(LOG/Dashboard/心跳 fail 兜底,次日未追平即 severe)。属既有 #123 R4 降噪与 fail-loud 的交互,非本补修直接引入;建议主控知悉,如需首日直达可后续拍板。

## 发现的问题清单(分级)
| 级 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P2 | 零星缺失告警在生产调用链 LOG 不可见(tail -20 截断,汇总行也被冲掉) | 模拟 async 段1 实测:30 行上传输出冲掉头部缺失告警+汇总 | 成功分支在 tail 前先把「缺失 N」汇总行固定写 LOG |
| P3 | 升格首日可能被 #123 R4 降级 info 不推送(有 LOG/dashboard 兜底) | 读码 staticdata_backup_async.sh L457 → notify.py R4 分支 | 主控知悉;如需首日直达用户,另行拍板 |

低分项(<80)已滤:1 项(25 分:逐条告警 print 在 scan 循环内拖慢扫描——每行 I/O 微秒级,万行秒级,可忽略)。

## 给主控的一句话结论
P2-1 补修核心目标(批量/全量源缺失 fail-loud 升格,该喊就喊)已实现且实测闭环(边界/状态副作用/回归/口径标注全过,**可合 main**);两个 caveat 非阻塞:①零星缺失(缺1-2 良性竞态)的逐条告警和汇总行在真实 async 链路里被 `tail -20` 截断、LOG 不可见,如要排查可见需补「汇总行固定写 LOG」;②升格置 STATICDATA_FAIL 后首日通知可能被 #123 R4 分级降成 info 不推送(次日未追平即 severe,有 LOG/dashboard/心跳兜底)。

## 复现清单
1. 阈值边界:/tmp/rev149e3/_t_boundary.py(10 用例,subprocess 打桩 + dry-run)
2. 升格状态副作用:/tmp/rev149e3/_t_marker.py(真实代码 + s3 mock:升格不写 marker/state 未覆盖/恢复后 0 新 PUT)
3. async 链路模拟:升格 /tmp/rev149e3/_t_async.sh(LOG 全可见)、零星 /tmp/rev149e3/_t_async2.sh(缺失信息被 tail 冲掉)
4. 回归四组(指向新代码):/tmp/rev149e3/_regression/{149e_review_extra,149e_t5,149e_t_envfull,149e_t_deg}.py
