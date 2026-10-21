> 落档:2026-10-22(源报告由本批执行 agent 产出,原样归档)
> 相关合并:见 `docs/ops/batch-fix-20261022.md` 时间线

# 审查 BLOCK 返修报告(2026-10-22)

残留后台任务:无。本次仅一次 `nohup` 全量 pytest(pid 16559),已自然退出并读回结果,无残留进程。

分支:`feat/fix-alert-blackhole-deploy-20261021`
- 主修复 commit:`42be1d60ff8cf86e1f8c656cd0b5c0a53556cb59`
- 注释同步 commit:`d12821cc6338f584281e8eeda96e8a4ffaca37ff`
- 远端已推:`git ls-remote` 头 = d12821cc6;未 push main,未使用 force。

---

## 一、BLOCK-1:fund_nav 回阻断级 + 自愈门失效(必修,已修)

### 根因确认(实施前已验证,§5.9)
- 用户 2026-10-13 拍板原文:`docs/ops/deploy-fundnav-selfheal-20261013.md:6-7`「保留 fund_nav FAIL 阻断全站 deploy」,「按产物隔离/降级为不阻断」已被否。
- 上一批把 fund_nav 列入 `ALERT_ONLY_CHECKS`,同时把 deploy.sh 自愈门从 `-ne 0` 改成 `-eq 1`;fund_nav 唯一失败 ⇒ rc=3 ⇒ 门为假 ⇒ 自愈永不进入(设计场景内失效)。另 `check_fund_nav` 含 DB↔产物逐位不一致 / DB 整日全 NULL / 覆盖率<98% 等正确性维度,并非「缺文件只让图少段」,且 deploy 有重建能力(`fund_nav_selfheal.sh`)。

### 改法(文件:行)
1. `scripts/check_data_integrity.py:231` `ALERT_ONLY_CHECKS` — fund_nav 与 changelog_current_version 已移除,回到默认阻断(`grade_of` :268 未登记即阻断)。
   - fund_nav 说明注释 :253-258;changelog :259-262;模块 docstring :27-30 补「例外」行(BLOCK-1 要求注释与行为逐字一致)。
2. `scripts/deploy.sh:378` 自愈前置门 `if [ "$CHECK_RC" -ne 0 ]`;注释 :366-377 写明「唯一失败 rc=1、rc=3 也过探针但非 DB 领先即快速返回 10,不重出、无害」;`rc=3 告警级继续` 分支 :396 与阻断出口 :413 未变。
3. 测试 `scripts/tests/test_alert_blackhole_deploy_gate_20261021.py`:
   - `test_b1_grading_exit_codes`(:287):`fund_nav` / `changelog_current_version` 不在告警级清单、`grade_of` = blocking;fund_nav 唯一失败 ⇒ rc=1;与告警级并存 ⇒ 仍 rc=1。
   - `test_b6_block1_fund_nav_blocking_and_selfheal_gate`(:414):源码形状守卫 —— 自愈门串 `-ne 0` 必须在、`-eq 1` 必须不存在、位置在 rc=3 分支与阻断出口之前;并用 `bash -c` 实跑到门分支:rc=1 进入自愈、rc=3 进入、rc=0 不进入。

### 证据用例结果
- 唯一失败项 = fund_nav ⇒ rc=1 ⇒ 自愈分支进入(桩级 `bash -c` 断言 PASS);与告警级项并存 ⇒ 仍阻断 PASS。
- 自愈脚本本体未被执行(§18 L50 禁跑生产脚本),只做静态门控断言 + case 分支逐字核对。

---

## 二、BLOCK-2:域聚合 digested 被误判「未送达」→ 假 SEVERE + 滑窗永不过期(必修,已修)

### 选型:A(独立态 digested),理由
- B(让巡检走关键通道免域聚合)会整体放弃巡检告警的降噪收益,且改动 notify 冻结面(§23.7)更大。
- A 只新增一个结果态 + 消费方判据,语义准确:「已并入当日摘要 buffer,由 23:25 摘要统一交付 = 已处置(不是未送达)」。实测未改变普通路径。

### 改法(文件:行)
- `scripts/notify.py:3384`:域聚合吸收路径 `--result-file` 写 `status=digested`(不再写 `noop`)。
- `scripts/check_failed_units.py:297`:**唯一判据** `sent = _status in ("sent", "digested")`;结果文件缺失/损坏 → `status=missing`(:296)按未送达;未送达打印「告警未发出(不落抑制, 下轮重试)」并 `return 4`(:479-479)。
- 判据唯一化:`notify_sent` 字符串 wrapper/import 已删(见 D7),结构化 status 是唯一判据。
- 注释同步:`check_failed_units.py` docstring 出口码、`scripts/schedule_monitor.sh:1926-1929` rc=4 语义注释(D11)。

### 证据用例逐条(实现前写定,已跑)
1. **同域 2h 内第二条巡检**:`test_d1_domain_absorbed_notify_reports_digested`(:507)—— 真实 `notify.send()` + 渠道函数打桩,域状态 seed 1h 前 ⇒ 结果文件 `status=digested`;email 调用 0 次(不再直发);`alert_digest.jsonl` 含告警正文;域状态 `n_absorbed=1`;零外发 trap hits=[]。PASS。
2. **连续 3 轮(15min 节奏)零假 SEVERE + 落签名**:`test_d2_digested_writes_signature_no_false_severe`(:528)—— 3 轮 rc 全为 1(无 rc=4);签名文件已落、`last_alert_date=今天`;末轮同集合当日重复不再发送(降噪维度保留)。PASS。
3. **真未送达仍 rc=4**:`test_d3_true_delivery_failure_still_rc4`(:549)——`status=failed` ⇒ rc=4、未落签名(下轮重试,不吞真故障);`test_a3` 参数化 6 态(sent/digested True,suppressed/failed/noop/None False)。PASS。
4. **72h 黑洞修复不回归**:`test_a2_upgrade_window_does_not_swallow_new_object_first_report`(:182)、`test_a2b`(:206)仍绿;`test_a4`(:266)锁 rc=4 独立复核项 `check_failed_units|delivery|down` 存在、rc=1 打印不再自证「已发告警」。PASS。

---

## 三、建议项逐条结论

| 项 | 结论 | 落点/证据 |
|---|---|---|
| ad_line 理由失实 | 已改:改为「export 链由 DB/上游生成;上游滞后时 deploy 重跑也修不了源」,保留告警级 | `check_data_integrity.py:244` |
| etf_since_return 理由不精确 | 已改:写明「overview 注入字段;根因混合(上游覆盖率不足 / deploy 注入失败)」 | `check_data_integrity.py:250` |
| changelog_current_version | **已恢复阻断级**(本批不放宽);报告标「**待用户拍板是否放宽**」 | `check_data_integrity.py:259-262`、`test_b1` |
| D3 deploy_consecutive_fail 被域吸收 | 成立,已改:新增 `adr.DOMAIN_AGGREGATE_EXEMPT_KEYS={"deploy_consecutive_fail"}`,`notify.py:1290/1295` 域门放行;`test_d4`(:558)证明该键 2h 窗内仍 `sent` 直发,正控 `r2_upload_fail` 仍 `digested` | `alert_denoise_rules.py:1033` |
| D6 集合配对少计纯丢失 | 已改 `Counter` 一对一多重集(`app/history_audit.py:108-123`);`test_c4_multiset_pairing_pure_loss_not_masked`(:653):2 条同键消失 + 1 条出现 ⇒ critical +「纯丢失 1 条 / 型别变更 1 条」 | 同左 |
| D7 不可达字符串回退 | 已删:`cfu._notify_sent`、import、死分支;`test_a3b`(:251)+`test_241::test_02_cfu_uses_result_file_not_string_parser` 锁「不得回潮」;`notify_sent.py:69-73` 关联说明更新 | 同左 |
| D10 `/tmp` 路径 | 已改指可复现脚本 `scripts/alert_weekly_review.py`(docstring :81 + notice 正文 :313);全仓 `grep alert-week-report` 0 命中 | 同左 |
| D11 注释过时 | 已同步:`schedule_monitor.sh:1926-1929` rc=4 = `status ∉ {sent,digested}`;`check_failed_units.py` 出口码 docstring | 同左 |

---

## 四、全量 pytest(§18 L52)

命令:`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`
结果:**1 failed, 1146 passed, 2 skipped in 141.44s**(日志 `/tmp/pytest_full_block2.log`;注释同步 commit 后重跑,与首轮 146.93s 同结论)。

唯一失败:`scripts/tests/test_224_zombie_cron_gate.py::test_real_jobs_no_false_zombie_when_pending`(:277 `真实 job b0741f7c ready_at=1792602780 在将来, 不应被误判僵尸`)。
- 与本 diff 无关的证据:①该用例读**本机实时** `/Users/linhuichen/code/trade/.claude/scheduled_tasks.json`(非仓库文件),CI 无此文件自动 skip;②本分支 diff 文件清单不含 `check_task_state.py` / `test_224*`;③首轮(改动前同一工作树)即为同一条失败,失败随本机实时任务状态变化。判为**既有环境依赖失败**,非本次回归。已在报告中如实标注,未掩盖。

关键用例套件:test_alert_blackhole_deploy_gate 26 passed;test_240 / test_241 全绿。

## 五、变异测试(判别力,2 组真红→还原绿)

1. `check_failed_units.py` 判据改回 `_status in ("sent",) # MUTANT` ⇒ **3 条真红**(test_a3[digested]、test_d2、test_241 结果态守卫),还原后绿。
2. `check_data_integrity.py` 把 `"fund_nav": "MUTANT"` 塞回 `ALERT_ONLY_CHECKS` ⇒ **2 条真红**(test_b1、test_b6),还原后绿。
还原校验:`grep -c MUTANT` = 0;md5 = `9ecdc2b25410ae50fdfd7e3e1cb755f9`(check_failed_units.py)/ `4ba5415b41d0a99d7660eff53935f47c`(check_data_integrity.py)与变异前备份一致。

## 六、零通知外发(§18 L48)

- 全部用例在 `ZeroOutboundTrap` 内,且先跑 trap 武装自证(test_00:真触达出口必 raise + 计数)。
- d1/d4 用真实 `notify.send()`,但 `_send_email` / `send_telegram` / `send_feishu` 全打桩;每条用例末断言 `trap.hits == []`。
- 本次自测未产生任何真实外发(邮件/飞书/Telegram 均 0 次)。

## 七、§23.2 修 bug 三铁律:同类错误面清单

| 同类面 | 排查结果 |
|---|---|
| 其他 `--result-file` 消费方是否也把 digested/noop 当未送达 | 全仓仅 check_failed_units 消费结构化结果(notify 写入 + 测试);无第二消费方 |
| 其他"分级 vs 阻断"硬编码副本 | `ALERT_ONLY_CHECKS` 仅 check_data_integrity 内定义,消费点 = `grade_of` / summary 导出 / deploy.sh rc 处理;无第二份清单 |
| 其他域聚合会吸收「停摆级」告警 | 已列候选:deploy_consecutive_fail 已豁免;r2 上传失败保留聚合(非停摆级,可迟到摘要) |
| 其他 history 配对处 | `signal_daily` 配对只此一处;`index_daily` 走 critical 分支不受影响(test_c3) |
| 其他 `/tmp` 报告路径引用 | 全仓 grep 0 命中 |
| 其他自愈门/rc 语义注释 | deploy.sh 门注释、schedule_monitor rc 映射、cfu 出口码 docstring 已同步 |

## 八、§23.3 举一反三:同模式/同数据源/同组件还被谁用

- 同模式(结构化状态判据):`check_s06_freshness` 仍用文本判据 `notify_sent`,但它不传 `--result-file`、本次未改其输入形态 ⇒ 不跟随改动,已在 `notify_sent.py:69-73` 写明边界,测试未回归(全量绿)。
- 同数据源(域聚合状态文件):`alert_domains.json` 写入点 = notify 域门;读取点 = 同文件 + 测试 seed;无其他展示位消费。
- 同组件(分级):check_data_integrity 的 `--summary-file` 会把 `alert_only_grade_rules` 落 JSON,已由 `test_b2_summary_written_with_grade_split` 覆盖。
- 展示位一致性(§22):本次不动任何前端 JSON / R2 产物,无 N 文件+N 缓存同步面。

## 九、§5.8① 七轴边界维度清单(逐维:测/不测 + 理由 + 来源)

| 轴 | 判定 | 理由与证据 | 来源 |
|---|---|---|---|
| ① 输入域(空/缺 key/null/非法值/超阈值/边界值) | 测 | 结果文件缺失/损坏 → `status=missing` 不落签(test_a3b);status 六态参数化(test_a3 / test_240 参数化);域时间 seed 1h(窗内)/空窗(test_d4 正控);未登记项 `grade_of` 默认阻断(test_b1) | BLOCK-1/2、D7 |
| ② 状态组合(盘中/盘后/非交易日/首日/兜底态) | 不测 | 本次改动链路(notify 交付状态 / 巡检签名 / 分级闸门)无交易日或盘中分支;域窗只按同日+时长判定,已单独在③覆盖跨日 | BLOCK-2、D6;排除理由=改动点无该分支 |
| ③ 时序(重复触发/幂等/乱序/跨日翻滚) | 测 | 连续 3 轮幂等 + 签名抑制(test_d2);域窗跨日行为:`domain_inhibit_judge` 只在同日 absorb,测试 seed 钳到今日 00:00:01 防午夜抖动(test 已实跑);乱序不适用(巡检单实例串行) | BLOCK-2、D6 |
| ④ 上下游依赖(源失败→备源/展示位读死字段) | 测 | cfu↔notify 契约由源码形状守卫锁(test_02/test_a3);cfu rc → schedule_monitor 分支守卫(test_a4);ck 校验 rc → deploy.sh 门控(test_b6) | BLOCK-1/2、D11 |
| ⑤ 极端值(全空/全满/巨大/负值) | 测 | 全渠道失败 / append_failed → 不算已发(test_240 参数化);同键多行 2 消失 vs 1 出现(test_c4);"3 轮零假 SEVERE"= 极端重复 | BLOCK-2、D6 |
| ⑥ 回退路径(降级/fallback/关开关/逃生门) | 测 | 字符串回退已删除=显式失败路径(test_a3b);deploy rc=3 告警级继续(b1/a4);自愈 case 10/11/13 静态核对(b6) | D7、BLOCK-1 |
| ⑦ 并发与重入(多进程/多轮/锁争用) | 部分测 | 多轮重入:test_d2(3 轮)+ 域状态 `n_absorbed` 累加(test_d1);**不测多进程同跑**:调度为云上 systemd timer 单实例,本次未改调度/锁;并发无新入口 | BLOCK-2、D3 |

§5.4 被省冗余测试说明:未给 notify 每个 tier 分支补端到端(已有 #196/#264 既有用例覆盖);未真跑 `fund_nav_selfheal.sh`(生产动作,§18 L50),只做门控静态断言。

## 十、时敏用例与 CI(§5.3.1 硬约束①②③)

- 无「本机有/无某命令」写死:runs on mac 的 `bash -c` 用例只用 POSIX shell 内建;巡检用例通过 monkeypatch 注入样本(`--unit-show-json`),不依赖 systemctl。
- 时敏:`test_d2` 用 `datetime.date.today()` 比对签名落盘日期,被测代码同样取 today,同源同日 ⇒ 不写死日期字面量(L51 家族);域 seed 已钳制跨日。
- CI 依赖面:全部用 pytest + 标准库 + 项目内模块,无新第三方依赖。

## 十一、边界与遗留(诚实标注)

- changelog_current_version 恢复阻断后,若线上当前确实缺条目,下一次 deploy 会被阻断 —— 这是用户原策略(强制改码补条目),本批按任务书恢复;是否放宽待用户拍板。
- rc=3 时也会跑一次自愈探针(快速返回 10),属刻意的宽松门(注释已写明无害性);若审查认为应只在 rc=1 跑,可后续收紧,不影响本批正确性。