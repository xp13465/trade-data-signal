# #240② 告警方向感知精修 —— 独立审查报告(2026-10-09)

> 审查者:独立 reviewer agent(未采信实施报告,全部自行取证)
> 被审对象:feat 分支 worktree-agent-a63b8cf23bc5379f0,commit 2920d5d11(worktree 只读访问)
> 实施报告:docs/ops/240-direction-aware-fix-20261009.md;依据:docs/ops/alert-system-fullchain-audit-20261009.md §2-D3 / §6-L3a
> 审查期硬约束遵守:static-only 探针(§18 L50)、零外发/零 R2 写/零云上写

---

## 总判定

**可进 merge(8 项全部 PASS)**,附 5 条附注(F1~F5,均为文档/注释级准确性问题与一处已披露的设计取舍,不阻断 merge,建议低成本顺手修正)。未发现新增「同类面」。

---

## 逐项判定

### ① 方向判定正确性 —— PASS

「方向信息在汇总整串下会丢失,判定必须下沉到细粒度成员」的论断实证为真:

- **witness 复现(自写探针,不用它的脚本)**:集合 `{a,b}→{a}`(缩小)在「聚合整串」比较下表现为「旧串消失+新串出现」= 会被判 added/changed(方向判错);而细粒度成员集差集 `_cur - _prev = 空`、`_prev - _cur = {b}` → shrunk ✓。
- **旧代码实证**:git show 2920d5d11~1:scripts/check_failed_units.py(L202-215)写状态只有 {signature(md5), last_alert_date, updated_at} **无成员快照** → 方向在旧数据面上确实不可判,新增 items 是必要改动(最小正确面)。
- **新代码实测**(failed_units_identity = failed unit 名逐个 + watchman 异常逐条,去重保序;直接 import 被审 alert_denoise_rules.py 纯函数探针):
  - `{a,b}→{a}` → `(False,shrunk)` 静默 ✓
  - `{a}→{a,b}` → `(True,added)` 立即报 ✓
  - 聚合串顺序变化(failed 顺序互换)→ 无增无减,不误报方向 ✓


### ② 对照表可复现性 —— PASS(主结论复现)+ 附注 F1

- **真实日志 + HEAD 源码逐时点自判**:今日 data/alerts/latest.md severe 流水实际发送 9 条(04:30/10:45/13:00/16:30/16:45/17:00/18:15/18:30/20:15);用实时日志重建的集合序列(9 次变更)喂新判定 + 复刻 _write_sig_state 状态流转,我独立重放 = **恰好 2 条**(第 1 行 daily-first + 第 3 行 added;16:30 re-add 同集合 → added-jitter 静默;6 条纯缩小静默)。**「9→2」头条结论逐位复现** ✓
- 附注 F1(文档级偏差,不改变结论):
  1. §1.2 结论「9 次变更其中 **7** 次纯缩小」与自身表格/§3「**6** 条纯缩小 + 1 re-add 抖动 + 1 daily-first」不一致(表内纯缩小=08:15/16:15/16:45/18:00/18:15/20:00 共 6)。
  2. 对照表时点比真实发送时刻早约 1 个刻度(日志 header 配对所致;§8 已披露「差 1 个 tick」)。
  3. §8 把 13:00 归因「旧 6h 窗机制」存疑:被审代码 docstring 自载「**12:52 部署后 7 连发**中 4 条假信号」(7 连发=13:00/16:30/16:45/17:00/18:15/18:30/20:15),13:00 应为批次1 对称判定首轮(状态缺失→迁移期 changed)。建议改归因后再落档。

### ③ 真故障判别维度是否全保留 —— PASS + 附注 F2(本次最重点,含实证)

逐维验证(纯函数探针 + 复刻状态机两轮连跑仿真):

| 判别维度 | 验证 | 结果 |
|---|---|---|
| 新增立即报 | `{a}→{a,b}` 探针 + e2e test_02f rc3 | ✓ 一字未动 |
| #196③ 连续 3 天升 critical | git diff 中 consecutive_days_escalate 函数体/调用零行改动,独立状态文件 failed_units_patrol_state.json 未触碰 | ✓ 完全未动 |
| 跨日首报 | 仿真 A5:次日 08:00 集合仍在 → daily-first sent=True | ✓ 每日必有 |
| 抖动抑制边界 | 23h59m→静默 / 24h00m→报 / 无基准→报 / last_added_at 坏值→报 / 未来时刻→报 / now=None→报 | ✓ 全部 fail-open,边框精确 |
| 集合清空后重现 | 健康轮落 items=[] 观测(main L397-404)→ 重现=added 报;e2e test_02g rc5(清空后子集重现)断言 reason=added | ✓ 不吞 |
| **同集合 24h 二次 added(静默)** | 仿真 A1→A2(清空)→A3(同日重现,jitter 静默)→A4(same-set-same-day 静默)→A5(次日 daily-first **补报**);B1→B2→B3(跨日重现 jitter 静默)→下一轮 daily-first **补报**(延迟上限 1 轮=15min) | ✓ 见 F2 |

**F2(设计取舍,已实证不是无限吞)**:同集合(组成完全一致)且距上次报告 <24h 的重现,当轮静默;但 ①同日重复在旧代码本就 same-set-same-day 静默(对比基线未变差);②跨日场景**下一轮即 daily-first 补报**(现有状态机下不会被吞到第二天);③**任何成员变化 → 立即 added**;④持续异常第 3 天走 #196③ critical 独立通道。净效果=同组成故障至多 24h 内报 1 次 + 每日首报兜底,与审计 L3a 允许的「静默」口径一致。**判定:真故障判别维度全保留。**


### ④ 改动面边界 —— PASS

- git diff 2920d5d11~1 2920d5d11 --stat = **5 文件**:+208 报告 / +78 rules / +84 check_failed_units / +93 repro / +118 测试。
- **通知冻结面零接触**:notify.py 不在 diff;`--dedup-key adr.FAILED_UNITS_DEDUP_KEY --dedup-window 0`(L271-272)逐字未变;body_lines 告警正文构造零改动。
- 常量:diff 中新增仅 FAILED_UNITS_ADDED_JITTER_WINDOW = timedelta(hours=24);删除行仅旧判定函数体与旧 docstring,阈值/保链常量零改动。

### ⑤ 向后兼容 —— PASS + 附注 F3

- 云上现行状态=**父版(batch1)3 字段 schema**(云上文件 {signature, last_alert_date, updated_at} 与父版 _write_sig_state(path, signature, today_str) 写出的字段逐字段一致;云上 signature=6992d0745f8b == 2 成员集合 md5,自验成立)✓
- 迁移路径实测:同集合→静默(不重复报)✓;增大→changed 报(fail-open)✓;**缩小→changed 报一次(一次性恢复假报)**。
- **F3**:§6 写「不产生额外告警」需限定——上述 legacy 缩小场景会多发 1 条 changed(fail-open 属设计,可接受),建议改为「除迁移期 fail-open 首轮外不产生额外告警」。
- 「首轮迁移返回 changed 致抖动基准从未落盘」的修复**真成立**:_write_sig_state 实物 L232-234 `if sent and reason in (added, changed): new[last_added_signature]=...` 已含 changed ✓(修复前只记 added,已与父版逐字核对)。

### ⑥ 测试真实性 —— PASS + 附注 F4

- **红前绿后我亲自跑**:green(hermetic 副本)= 30 passed;red(父版全量还原)= **7 failed / 23 passed**(含 test_99 因断言计数 52<58 整文件 fail;4 个方向用例 test_02/02b/02f/02g 逐一失败)。**F4**:报告「4 failed, 26 passed」是「外科式还原保留新 API」口径,与全量还原口径(7 failed/23 passed)不同,建议标注口径。
- 断言绑真实形态:test_196 对抗真实云上快照 docs/deploy/systemd-units-cloud-snapshot.txt(实物锚点,规避 L49 假样本教训)✓;test_02f/02g 走 in-process cfu.main() + --repo tmp + ZeroOutboundTrap(**证明零外发**)✓;reason 断言绑代码自身具名输出(reason=shrunk/added/added-jitter),非宽白名单假绿 ✓;`_MIN_ASSERTIONS=58` 守卫红跑实测触发(52<58),非摆设 ✓。
- test_02g 覆盖「清空后重现必须报」(rc5)——正是防「抖动吞真故障」的关键用例 ✓。


### ⑦ §23.3 举一反三穷举 —— PASS(抽查 6 处,全部实证)

| 报告声称 | 我的实证 |
|---|---|
| check_data_gap_alerts.py 早已方向感知 | ✓ 实证:accum_nav「当日新增缺价 diff」三分支(本次清单−上版快照;历史回归/当日新缺分开;真消失才发 [恢复] 并清 key;F1 返修防「未真恢复误报恢复」) |
| cloud_unit_patrol.sh 对称=设计 | ✓ 实证:漂移两向都属人工决策类(回滚 unit 或刷新快照走 merge),对称正确,且有 dump/巡检双模式 |
| check_fade_keys_alignment.py / check_loss_rules_vs_mining.py | ✓ 实证:均为 CI/部署阻断型一致性闸门(七项断言 / 三层逐位校验,任一 FAIL 阻断上线),非用户告警 |
| overfit_monitor.py risk_climbing | ✓ 实证:「风险分连续 5 日攀升」= 本身就是方向定义 |
| gen_daily_brief.py 转向 | ✓ 实证:转向日检测按 net_chg 符号序列(转空/转多/均线多空),方向即语义本体 |
| signal_kelly_snapshot._polluted_ratio | ✓ 实证:abs(tr-prev)/abs(prev),方向无关是语义要求 |

**结论:全仓无第二处「方向盲的集合变更→用户可见告警」同类病灶,与报告一致。**

### ⑧ §22 一致性 —— PASS + 附注 F5

- 状态字段**纯新增**:7 字段=旧 3 字段语义保留+4 新增;全仓 grep 消费者仅 check_failed_units.py 自身(+测试),无第二读者 → 多展示位一致性问题不存在 ✓。
- 告警正文/两状态文件/notify.py #196③ 接线语义**均未改变**:正文构造零 diff;dedup-key/window 逐字未变;#196③ 状态文件独立未动;rc 语义父/新同为 0(健康)/1(异常)/3(内部故障)✓。
- **F5(trivia)**:健康轮「集合已空」观测的注释称「仅在曾观测到非空集合时**写一次**,免每轮空写」,实际因 signature 字段永不置空,写条件 (items or prev_signature or signature) 恒真 → 每个健康轮都会重写小 JSON + 打 1 行 stderr。无害(微写+日志),但注释与实态不符,建议顺手改注释或加「已空则不再写」判据。

---

## 是否有新增「同类面」

**无。** §23.3 抽查 6 处兄弟点均确非同类;本修复面即唯一病灶点。merge 后无需追加同类改造。

## F 编号汇总(全部不阻断 merge,建议顺手修正)

- **F1** §1.2「7 次纯缩小」应为 6;对照表时点早 1 刻度(§8 已披露);§8 的 13:00 归因与代码自载「12:52 部署后 7 连发」矛盾 → 应改「迁移期首轮 changed」。
- **F2** 抖动静默边界行为(同日不重发、跨日延迟上限 1 轮即补报)建议在 §0/§2.1 显式写全,防后续误读为「无限吞」。
- **F3** §6「不产生额外告警」需限定(legacy 缩小 → 1 条 fail-open changed)。
- **F4** 红前数字「4 failed, 26 passed」建议标注口径(全量还原实测 7 failed/23 passed)。
- **F5** 健康轮空观测「写一次」注释与实态不符(每轮重写)。

---
审查复现命令(全部 static-only/离线,本报告所有数字可由这些命令重跑):
- 探针:python3 -c import 被审 scripts/alert_denoise_rules.py → failed_units_daily_judge / failed_units_signature / failed_units_identity
- 状态机两轮仿真:复刻 _write_sig_state(实物 L206-244 + main L380-455)
- 红前绿后:hermetic 副本 + 父版 git show 2920d5d11~1:...
- 改动面:git diff 2920d5d11~1 2920d5d11 --stat

(本报告由 reviewer 独立取证产出;被审 worktree 内未做任何 checkout/commit,业务文件零改动,本次审查零外发。)

