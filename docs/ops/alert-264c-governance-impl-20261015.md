# #264 告警降噪 · 包3「治理」(件F)实施报告 — 2026-10-15

> 分支:`feat/264c-alert-governance`(worktree 隔离)。
> 范围:件 F = 把「告警面扩张」纳入预算(防复发)。依据 `docs/ops/alert-noise-rca-20261015.md` §2.2③(复发结构④:新 checker / 新故障域扩张快于降噪)+ §4.1 F。
> 交付物:①四元组登记表 `docs/ops/alert-checker-registry-20261015.md` ②review 强制落点 ③周 review 工具 `scripts/alert_weekly_review.py`。

## ① 盘点口径与范围

- **口径**:「告警产生点」= 仓内 `scripts/` 下**实际调 `scripts/notify.py` 发外发告警**的脚本(checker / 告警包装层 / 兜底通知 / 锁跳过通知)。读源码逐点取参,非文档推断。
- **方法(可复现)**:静态扫 `python3 scripts/alert_weekly_review.py --check-four-tuple --scripts-dir scripts` —— 本轮实产 **49 候选 / 14 缺项**;剔除 2 假阳性(`check_ds_resilience.py` 仅模块 load 非调用、`cloud_unit_patrol_selftest.sh` 自测桩注入 notify)→ **47 个真实产生点**,逐一登表。
  - 扫描器只用「调用形态提示」正则排除散文/docstring 提及(教训:初版无该过滤,24 处散文误报;已修 + 自测断言)。
- **范围**:仓内全部产生点 + 云上 `122.51.111.173` systemd timer 清单(只读 `systemctl list-timers --all`,**56 timers** 含 42 个 `trade-*`)。
- **诚实标注**:云上 timer 是「触发链」权威;本机 mac 纯开发不跑定时(launchd 已废弃,memory `local-dev-cloud-prod-split`),故脚本头注释里的「launchd」字样不代表现网触发,已按云上是否真有 timer 落「触发方式」列。

## ② 四元组矩阵 + 缺项

- 矩阵落 `docs/ops/alert-checker-registry-20261015.md`:§2.1 故障告警 checker **44 行** / §2.2 业务订阅 **3 行**。
- **缺项汇总(§3)**:
  - **A. dedup window 未声明(12 处)**:check_s06_freshness、self_heal、backup_db、verify_backup、on_skip_notify、turnover_backfill_skip_notify、r2_upload_skip_notify、pick_repo、uptime_check、monitor_72h、sensenova-proxy-healthcheck、signal_kelly_backtest
  - **B. window=0 关死抑制(1 处,违规)**:check_failed_units.py(RCA §2.2④.a 病灶 → A 包修)
  - **C. 默认 tier 未声明(走 send() 旧行为,7 处)**:r2_upload_skip_notify、staticdata_backup_async、staticdata_sync、sensenova-proxy-healthcheck、signal_kelly_backtest、run_daily_brief、gen_daily_brief
  - **D. 聚合域未声明(全表)**:当前无域概念,全表标「建议·待对齐」,待 264b 定稿
  - **E. 首报策略未声明(隐式)**:多数靠 dedup 语义隐式满足,未显式声明
  - **F. 孤儿 checker 无触发链(2 处)**:uptime_check.sh、monitor_72h.sh(有告警能力但云上无 timer;已登记 #210)⇒ **观察盲区**,须 264c 后续收口
- **本轮盘点相较初版的增量**:初版矩阵 27+4 行**漏了 17 个真产生点**(uptime_check、monitor_72h、with_lock、deploy、gold_night、kelly_intraday_rerun、turnover_backfill、update_lab、push_schedule_stats、staticdata_backup_async、staticdata_sync、fund_nav_upload_async、r2_upload_async、brief_push_wrapper、nextday_gap_check.sh、agent_inbox_watcher、feishu_missed_fetch)。**根因**:初版靠人工回忆清单而非扫描器全量口径 —— 本次以「扫描器 + 逐点读源码」双口径重盘,补齐(F-① 的正确做法)。

## ③ review 强制落点选择理由 + diff

### 落点选择
- **现状核查**:全仓**无**专门的「新增脚本/checker 上线检查」活规范文件;现有上线检查分散在 `role-implementer` §0 清单、`role-reviewer` 各审查节、`docs/pre-release-quality-flow.md`(§5.8 六关)。
- **选择**:把「四元组缺失不上线」落在**两个角色 skill**:
  1. `.claude/skills/role-reviewer/SKILL.md` 新增 **§11**(审查关硬门槛)—— 对应 RCA §4.1 F 原话「review 清单强制」;
  2. `.claude/skills/role-implementer/SKILL.md` **§0 清单新增第 9 条**(实施侧前置声明),「8 条硬勾选」→「9 条硬勾选」。
- **理由**:①生产方(implementer 声明)+ 门禁方(reviewer 把关)**成对覆盖**,不留单侧漏洞(§23.3 举一反三);②两 skill 每会话启动全文注入,确定性生效,不依赖主动读;③role skill 是「活规范」,符合 §23.8 skill 维护同步铁律。
- **`待 264b` 例外**:聚合域在 264b 定稿前可标 `建议·待对齐`(不阻断),但 **tier / dedup window / 首报策略三项不得缺**。

### diff(摘要)
- `role-reviewer/SKILL.md`:文件 213 → **229 行**,§11 起于 L215;含「必查四项 + 怎么核(源码行 grep / 登记表 / 扫描器)+ §10.4 静默失败联动 + §10.8 边界独立复核联动 + 验收口径」。
- `role-implementer/SKILL.md`:§0 清单 L32 新增第 9 条;L22「8 条」→「9 条」。
- 两文件均在 `.claude/` 下 ⇒ 按纪律走 **/tmp 暂存 → Bash `cp` 就位 → `cat`/`grep` 验证落地**(禁 Write/Edit 直写 `.claude/` 路径);已 grep 验证 §11 标题在位(L215)、§0 第 9 条在位(L32)。

## ④ 周 review 机制(件F 的第二半:top-talkers + 被吞条目找回)

- 交付 `scripts/alert_weekly_review.py`(轻量,只读 + 打印,**零外发**,不碰通知链路 —— §18 L48 精神)。四件事:
  1. **top-talkers**:近 N 天(默认 7)实发告警按 source / subject 排序(谁在刷屏);
  2. **tier 分布 + 完全同主题重复率**(重复下限口径,对齐 RCA §1.3);
  3. **被吞条目找回核对**:读 `alert_daily.json` 的 `merged_in_digest`,提示到当日摘要正文核对(降噪不变式 4:被合并条目必须出现在摘要);
  4. **四元组缺失扫描**(`--check-four-tuple`):静态扫产生点,列缺 tier / 缺 dedup-key / `--dedup-window 0`。
- **数据源**:云上权威机台账 `data/alerts/alert_ledger.jsonl`(**跨两树聚合**,双树分裂是结构性根因,RCA §1.1;不跨树会「又变成两个数字」违反 §22)+ `alert_daily.json`。
- **自测**:`--selftest` 用合成台账 + 合成脚本(含 good/bad/zero/散文四种),断言「OK / 缺 / 违规」三态判对 + 散文提及被过滤;**零外发**(全程只读内存/临时目录)。
- **首周基线**:本脚本首次真跑须在云上(本机无台账,缺省 exit 2 提示从云上取);本轮先落**机制 + 静态扫描基线**(49 候选 / 14 缺项),台账型 top-talkers 待云上首跑产出。

## ⑤ 三验证清单(选项一前置)

1. **问题真实**:RCA §2.2③ 实测「新 checker 扩张快于降噪」——产生点从「无登记」到本轮盘出 **47 个**;其中 `check_failed_units.py` `--dedup-window 0`(RCA 已立案)在源码 L277 实测在位 ⇒ 告警面无预算、会随新增 checker 继续膨胀,是真问题。
2. **根因定位**:每个产生点的四元组取值**逐点读源码**(非文档推断),缺项按「未声明 / 违规 / 隐式」三类标注;`uptime_check`/`monitor_72h` 无触发链与云上 timer 清单交叉核实(#210)⇒ 根因 = **新增 checker 无准入约束 + 无域概念**,与 RCA §1.4/§4.1 C 一致。
3. **修复可行**:①登记表把「存量缺口」一次盘清(供 264b 收口聚合域);②review/implementer 两 skill 成对落点已 grep 验证在位,新 checker 从今起「缺一不上线」;③周 review 工具自测 ALLPASS、可一键复跑 ⇒ 三项均可落地、可验证。

## 复现命令(只读)

```bash
# 四元组静态扫描(不执行任何脚本)
python3 scripts/alert_weekly_review.py --check-four-tuple --scripts-dir scripts
# 周 review 自测(合成数据,零外发)
python3 scripts/alert_weekly_review.py --selftest
# 云上 timer 清单
ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173 'systemctl list-timers --all --no-pager'
```

## 待办/移交

- **264b(aggregate-budget 包)**:定稿「聚合域」口径,回填登记表 §1/§2.1 域列(把「建议·待对齐」转正)。
- **264c 后续**:孤儿 checker(uptime_check/monitor_72h)补触发链或显式声明「无触发不适用」(#210)。
- **首周 review**:云上首跑 `alert_weekly_review.py`(带 `--ledger` 两树),产 top-talkers 基线。

---
(报告完;随 #264 包3 落档。生成:2026-10-15。)