# W1(L1 度量层)独立审查报告 —— reviewer(2026-10-10)

## 0. 审查元信息
- 审查对象:分支 `feat/alert-l1-meter-1010` @ `23f3304a06520c773b8a2963e8bcb6c09bfd251c`(worktree:`/Users/linhuichen/code/trade/.claude/worktrees/agent-a34bf0abba0b5dde7`),基线 `main 6ad3c742e`;实施报告 `docs/ops/alert-l1-meter-20261010.md`(下称"报告")。
- 审查纪律:**只审不改**——未 Edit/Write 仓库文件、未 checkout/switch、未 commit/push;全部实验在 /tmp 沙箱(REPO 指向 /tmp 沙盒树);报告本文件写 /tmp(主控落档)。
- 残留后台任务:无(唯一长任务 pytest 以 nohup 自起、已正常退出 RC=0,进程已回收)。
- **总结论:12 项必查全部 PASS,0 阻断性 FAIL;3 个非阻断 finding(F1/F2/F3)+1 文档小误差 +1 观察项。可否合并:建议可 merge(F1/F2 为报告文字订正项,建议随手带上,不强制)。**

## 1. 逐条结果(每条=PASS/FAIL + 证据命令 + 观测值)

### ① 冻结面纯新增验证 —— PASS
- 证据:`git diff main...feat/alert-l1-meter-1010 -- scripts/notify.py` 提取删除行逐行分类。
- 观测值:删除行实 **18 行**(报告 §5.4 称 15 行,小误差)。18 行全为:签名加参(2 处 send/send_tiered)、send/send_to 内三渠道调用**重缩进进 try**(8 行纯缩进位移)、调用点加 `ledger_*` 关键字(8 行)。**无一行含 print/文案/判定**。
- 关键守护行逐字保留:`"dedup 窗口内 suppress"` print 在 main L2183 → branch L2361(仅行号位移);`scripts/retry_failed_metrics.py:130` 的 `if "dedup 窗口内 suppress" in stderr:` 子串匹配不受新 `[notify][ledger]` 行干扰(stderr 文本与匹配因子串正交)。

### ② 行为零变更 —— PASS
- 证据:差分 harness(main/branch 两份 notify.py 各配 stub 三 core,归一化时间戳/路径后逐字比对)14 场景。
- 观测值:返回值/异常传播/退出码/去重窗口刷新时机**逐位一致**;try/finally 不吞异常、depth 异常路径复原;branch 恰多 7 条台账行(=设计预期),其余输出零差异。

### ③ dry-run 不写台账 —— PASS
- 证据:沙箱 4 入口(send / send_feishu / _send_email / send_telegram)逐一 dry_run=True 实跑。
- 观测值:台账文件**不存在**(零写);先跑非 dry-run 正控证打桩/沙箱生效(正控后才计数)。

### ④ 零外发 —— PASS
- 观测值:沙箱正控 hit=true→ret=false(哨兵先证生效);dry-run 外发 hit=[];审查全程**零真实外发**(全部 stub/patch core)。

### ⑤ 防漏记(最小覆盖集是否真覆盖全部外发)—— PASS(附 F2)
- notify 内原语自核(`grep -n "urlopen(\|SMTP_SSL\|_feishu_http_post_json(" notify.py`):urlopen L538=send_telegram 体内;`_feishu_http_post_json` 定义 L628/639,调用点 L663(取 tenant token,鉴权非消息)/L716(`_send_feishu_api`)/L773(`_send_feishu_webhook`)——两条消息路径**均在 send_feishu 之下**;SMTP_SSL L1037=`_send_email` 体内。与 `_zero_outbound.py` 的"三原语"声明一致。
- 直调实测(重点项):`brief_push.py` 直 import 路径实测——`push_email`→1 行(email=true)、`push_feishu`→1 行(feishu=true,group=report),source=brief_push.py,**两次独立外发=2 行不双记**。grep 复核 12+ 脚本直调点(brief_push/agent_inbox_watcher/codex_notify_bridge/feishu_chat_hook/feishu_ws_listener/check_signals/check_nt_signals/gen_daily_brief/signal_kelly_snapshot/upload_r2/nextday_plan_generator/check_ds_resilience)均为被包名,无漏网。
- **F2(非阻断)**:报告"最小集覆盖全部真实外发"措辞过宽——**3 处非 notify 直发出口**未列进"已知剩余旁路":(a) `daily_summary_email.py` 自建 smtplib(每日实际 2 封:main 17:50 由 update_all 调、supplement 20:30);(b) `brief_push.py` 订阅者 webhook POST(L165-179);(c) `feishu_missed_fetch.py` import ws_listener 的 send_receipt(与已声明回执旁路同族、第二个出处)。根因=报告枚举口径只覆盖 notify 家族。影响=口径描述,不影响代码行为。建议措辞收窄为"覆盖 notify 家族全部外发"+补列。

### ⑥ 防双记(threading.local 深度守卫)—— PASS
- 观测值:8 线程×2=16 条不重不漏;嵌套场景 2 条;depth 恒归零;test_H1/H2 锁死 1 条/2 条。

### ⑦ 跨树聚合(§22 单一数字)—— PASS
- 观测值:默认 resolve 自动发现兄弟树(trade-data / trade-data-signal,resolve 去重);聚合单数字;云上双树实测存在。

### ⑧ 幂等 —— PASS
- 观测值:自建样本 recount 连跑两次,两树 md5 全同 `217ef8c3a5362b79a205c0dcf71a0c7b`(我独立复跑);按报告原路径复现实施者 md5 `785f172ce0c6a91d6152741d2c3f6fd6` 逐位一致。

### ⑨ 真样本重放(20 条对照)—— PASS(事件级;附 F1)
- 证据:`ssh 云上 grep '^## \[severe\] 2026-10-09' 双树 latest.md` × 审计 §4 逐条定性表 × REAL_20。
- 观测值:20/20 事件成立(运行树 19 + 信号树 1 = 20);22:35 数据缺口×3、23:30 unit 巡检=审计截点后新增,**正确排除**;抽样 04:30/09:45/16:42/22:00 与报告吻合。
- **F1(非阻断)**:REAL_20 部分字段为"人工重建语义标签",与生产台账实际值不同——(a) subject:unit 巡检族生产模板=`[告警] 云上 unit 巡检发现异常(N 项) MM-DD HH:MM`,测试写`云上 failed unit 巡检: N 个未清`;(b) key:`schedule_monitor_alert` **全库唯一出处=本次 report+test**(生产 monitor 告警 CLI 不带 --dedup-key,实键=sha1(subject)[:12]);(c) source:**23 处云上 latest.md「来源」字段实测全为 `notify.py`**(CLI 家族 sys.argv[0] 解析链),即生产 by_source 对该批会塌缩到 notify.py,报告 §5.1 演示的脚本分解**生产不可复现**;且 REAL_20 #1 标 source=upload_r2.py 与真实发射者 deploy.sh(L611/621,key r2_upload_trigger_fail 也在 deploy.sh)不符(F3,同族)。影响:不改被审代码行为、不影响台账生产数据;影响的是报告 §5.1「§18 L49 真样本,非人工构造」标注准确性与演示数字可复现性(正文"人工重建 20 条"表述与标题自相矛盾)。建议:报告补 1-2 行口径说明;若 W2 要 by_source 维度有效,另开小任务给 CLI 家族注入 NOTIFY_SOURCE(勿扩本次冻结面)。

### ⑩ 回滚开关 ALERT_LEDGER_DISABLE=1 —— PASS
- 观测值:双向实测——写入后开开关→不再增行;关掉→恢复增;dry_run 同短路;keys 无残留。

### ⑪ schedule_monitor.sh +30 行 —— PASS
- 观测值:`bash -n` OK;内嵌 python **全量 compile OK**(2902 行);NOW/REPO/sys/subprocess 均在作用域;解释器=`$REPO/.venv/bin/python`(与既有 --flush-warnings 块同款既有模式);失败只打 stderr `[warn]`、**新块零 notify 调用**(机制自身绝不告警);`deploy.sh L558 --exclude=alerts/` 证明 alert_daily.json 不参与部署上传(无 15min 上传抖动)。
- 观察项(非缺陷):15min 网格与 guard 五时点±2min 实际相交仅 2 轮(16:00/22:00),过度保守但无害。

### ⑫ pytest 全量回归 —— PASS
- 证据:worktree 内 `nohup … .venv/bin/python -m pytest -q -p no:cacheprovider scripts/tests/`(禁 /usr/local/bin/python3、未用 tail 吞码)。
- 观测值:**RC=0,623 passed, 2 skipped in 92.77s**(实施者 93.69s,数字一致);跑后 worktree `git status --porcelain` 干净、HEAD=23f3304a0 未动。

## 2. 低分已滤(<80 未列)
- `sent = any(results.values())` 疑似重复行:main 已有(pre-existing,不算本次 finding)。
- pytest 耗时 92.77 vs 93.69:机器抖动,无意义。
- 其余若干措辞/风格项,均 <80 已滤。

## 3. 合并建议
- **无阻断性 FAIL,建议主控走 main-merge.sh 合并**。
- 非阻断订正项(建议随手带上):F1(§5.1 补"key/subject/source 为语义重建标签"口径行)、F2("覆盖 notify 家族外发"收窄+补 3 旁路)、文档小误差(§5.4 删除行 15→18)。
- W2 备选输入(独立小任务,不扩本次冻结面):CLI 家族注入 NOTIFY_SOURCE,使 by_source 维度在生产可用。
