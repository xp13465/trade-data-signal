> 落档:2026-10-22(源报告由本批执行 agent 产出,原样归档)
> 相关合并:见 `docs/ops/batch-fix-20261022.md` 时间线

# BLOCK 返修独立复审报告(2026-10-22)

残留后台任务:无。上一轮一次 `-rs` 全量 pytest(后台 ID byon0y23l)已自然退出(exit 0),本次审查无新后台任务。

- 对象:`feat/fix-alert-blackhole-deploy-20261021` @ `d12821cc6`(主修 `42be1d60f` + 注释 `d12821cc6`),基线 `431b10818`
- diff:`11 files changed, +386/−87`,零前端/零数据产物(无 static-site、无 purpose-notes/app.js/lab.js)
- 方式:只读静态核 + `/tmp/rv2/branch`(git archive 分支头)跑测试与变异;零外发、零生产写
- **最终结论:PASS**

## 一、BLOCK-1 fund_nav 回阻断级 + 自愈门 —— PASS

1. 清单:`check_data_integrity.py:231-262` 中 `ALERT_ONLY_CHECKS` 已不含 `fund_nav` / `changelog_current_version`,且 :253-262 注释写明「刻意不在此清单」及用户拍板依据;`grade_of` :270-272 未登记即 `blocking`,`determine_exit_code` :2709-2730 阻断失败先于告警级判定 ⇒ fund_nav 唯一失败 = rc=1。
2. 自愈门:`deploy.sh:378` 已恢复 `if [ "$CHECK_RC" -ne 0 ]`(基线为 `-eq 1`);位置在 :396 `rc=3 告警级继续` 与 :413 阻断出口之前;注释 :366-377 说明 rc=3 也过探针但 fund_nav 正常时探针 rc=0 → 自愈 exit 10 快速返回、不重出。
3. 两种唯一失败场景:rc=1(阻断项失败)与 rc=3(仅告警级失败)都能进门 ∵ `-ne 0`;rc=0 不进。`fund_nav_selfheal.sh:103-108` 三态映射(probe rc=0→exit10、rc=3→继续、其他→exit2)未被改动,与门语义配套。
4. 用户拍板:`docs/ops/deploy-fundnav-selfheal-20261013.md:6-7` 原文「保留「fund_nav 一项 FAIL 阻断全站 deploy」的语义不变」逐字遵守;正确性维度(DB↔产物逐位不一致 / 整日全 NULL / 覆盖率<98%)见 `check_fund_nav:1600-1665`。
5. 自做变异:把 `deploy.sh:378` 改回 `-eq 1` → `test_b6` 真红;还原后绿。分支副本 `grep -c MUTANT`=0;md5:check_failed_units=`9ecdc2b25410ae50fdfd7e3e1cb755f9`、check_data_integrity(d12821cc6)=`08fc30d8…`(42be1d60f 版=`4ba5415b41d0a99d7660eff53935f47c`,与实施方声明一致)。

## 二、BLOCK-2 域聚合 digested —— PASS(硬红线满足)

1. 独立态:`notify.py:3386-3388` 对 `results.digested` 落 `status=digested`(不再借用 noop);域门 :1293-1295 新增豁免键匹配,:1300-1316 吸收成功即返回 `digested=True`;L2 预算/notice 路径同理。
2. 判据:`check_failed_units.py:297` `sent = _status in ("sent","digested")` 为唯一判据;sent → `_write_sig_state(sent=True)` :470 + return 1;`failed` / 结果缺失(`:296 status=missing`)→ :478-479 打印「告警未发出」并 `return 4`、不落签 ⇒ 下轮重试。
3. 硬红线(真失败仍 rc=4):`test_d3`(status=failed→rc4 无签名)、`test_a3` 六态参数化(sent/digested=True;suppressed/failed/noop/None=False)、`test_a3b`(文件缺失/损坏)全绿。
4. 滑窗:`test_d2` 连续 3 轮 rc=[1,1,1] 且签名落盘;签名落盘后后续轮不再调 notify ⇒ 不再刷 `last_ts`,滑窗不会永不过期(修法 A 彻底)。
5. 摘要不吞:`flush_digest` `notify.py:2924-2930` 只在任一渠道成功后清理条目,未发出则「条目保留」下轮按 stale 重试;23:25 后被并入的条目次日首轮 stale 补发(:2772-2843)⇒ digested=「摘要必达」成立,最坏延迟 <1 小时,不是黑洞。
6. 72h 升级档不回归:`test_a2/a2b/a4` 绿(critical 升级档 `budget_exempt` 直发,不受域门影响)。
7. 自做变异:cfu 判据改回 `("sent",)` → `test_a3[digested]`、`test_240::test_02d`、`test_241::test_02` 三条真红;还原绿。

## 三、建议项

| 项 | 结论 | 证据 |
|---|---|---|
| D3 免域聚合 | 成立 | `alert_denoise_rules.py:1033` 常量;`notify.py:1295` 精确匹配;`test_d4` 正控 deploy_consecutive_fail 直发 + r2_upload_fail 仍 digested |
| D6 Counter 多重集 | 成立 | `app/history_audit.py` 一对一配对;`test_c4`(2 消失+1 出现 ⇒ 纯丢失 1) |
| D7 字符串回退删除 | 安全 | 全仓无第二消费方;`test_a3b` + `test_241::test_02` 锁不回潮 |
| D10 引用路径 | 成立 | `scripts/alert_weekly_review.py` 存在(14KB),`--selftest` ALLPASS;全仓 `alert-week-report` 0 命中 |
| D11 注释同步 | 成立 | `schedule_monitor.sh` rc=4 = `status ∉ {sent,digested}` |
| changelog 恢复阻断 | 确为恢复原策略(原 docstring 强制改码补条目),非新策略;实施报告 §11 已标「待用户拍板」,需主控转呈 | `check_data_integrity.py:259-262` |
| 文档漂移(低于报告线) | 非阻断两处 | `notify.py:3101-3103` argparse help 仍列 5 态缺 digested;`docs/ops/alert-checker-registry-20261015.md` 第 1 行判据仍写 `status=sent` |

## 四、回归 / 冻结契约(§23.7)

- 全量 pytest(`/tmp` 副本,无 .git):4 failed / 1142 passed / 3 skipped(142s);与实施方 1F/1146P/2S 总数同为 1149,差异已归因环境:3 条治理类在无 `.git` 的 archive 必失败(主工作树 4/4 绿)。
- test_224 红与本 diff 无关(独立确认):①`git diff --name-only 431b10818..d12821cc6 | grep test_224` = 0;②main `7b4e4d876` 仅改 `test_224_zombie_cron_gate.py` 一个文件;③主工作树(main `2b2841454`)该文件 20/20 绿。
- 正常路径不变:`--result-file` 可选,未传参调用方行为不变(既有用例);`_finish` 仅记录 outcome;异常路径标 failed 后 re-raise。
- 零外发:26 条新用例全在 `ZeroOutboundTrap` 内,且先自证 trap 真 raise;d1/d4 用真实 `notify.send` + 渠道打桩,末尾断言 hits=[]。本次审查零外发。
- §21:无算法改动(零前端文件);§22:无数据产物/多展示位改动,数据校验归 tester;冒烟 P0(影响面视角)= 闸门语义由 b1/b2/b6 桩级覆盖,未跑生产 deploy(只读纪律)。

## 五、§10.8 边界独立复核(先自推,后对账)

一致项(双方都有):输入缺失/损坏、status 六态、自愈 rc=1/rc=3、跨日域窗、连续 3 轮、升级档 72h、local-first、rc 映射。
实施方独有:七轴极端值/同键多行、history pure_lost 三态。
我独有差集:

| # | 边界 | 处置 |
|---|---|---|
| E1 | `ALERT_DIGEST_DISABLE=1` **单独**置位:吸收仍发生 → digested → 落签名,但 flush 被停 → 告警静默积压(`notify.py:309-310` 已写明完整回滚须置 master) | 非阻断建议:回滚 SOP 明确「必须置 ALERT_BUDGET_DISABLE=1」;或吸收条件同时判 DIGEST_DISABLE 走 fail-open 直发(小改,建议下批) |
| E2 | notify 发送成功、写 result 前进程被杀 → status=missing → rc=4 重试 → 重复告警 | 安全方向(宁重不吞),接受 |
| E3 | 同域跨午夜(23:55 直发,次日 00:05 再来)→ first 直发 | 安全方向,无黑洞 |
| E4 | 渠道部分成功 status=sent → 落签不重试 | 既有口径,非本次改动 |
| E5 | adr 与 notify 版本不同步(旧 adr 无豁免常量)→ AttributeError → failed → rc=4 | 同 commit 部署保证;失败方向安全 |
| E6 | deploy.sh `CHECK_RC` 空值 → `[ "" -ne 0 ]` 误判跳过自愈 | 不可达(PIPESTATUS 恒整数),仅记录 |

E1 是唯一有实质意义的差集:本批把「rc=4 可见性兜底」换成「已处置」后,极端误配置下少一层显式告警;正常配置不触发,不构成本批阻断。

## 六、§10.0 尺子自验 / §10.2 过滤

- 零外发尺子先证:`ZeroOutboundTrap` 对 `urllib.request.urlopen` 真 raise 且有 hits 计数,再信 hits=[] 结论。
- §10.2:低于 80 分未报 3 项(help 文案、registry 判据行、history notice 引用精确度),已在第三节列出不重复计入。

## 七、结论

**PASS**。两条 BLOCK 均按用户拍板/硬红线正确修复,变异有判别力,回归差异已归因环境。非阻断建议 3 条:E1 回滚 SOP、两处文档漂移、changelog 放宽待用户拍板(主控转呈)。
