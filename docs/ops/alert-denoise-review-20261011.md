# 告警降噪三项 独立审查报告(2026-10-11 夜, reviewer 独立上下文)

- 审查对象: 分支 `worktree-agent-a56e10357ddd5bda5`, commit `a7f6413ec`(代码)+ `f275698a1`(报告订正); 实施报告 `docs/ops/alert-denoise-exec-20261011.md`
- 拍板来源: 2026-10-11 用户「直接干」; 范围=盘点报告 `docs/ops/alert-triage-20261011.md` §3-3 三项
- 审查方式: 全程只读(本报告除外); **不采信自述, 全部关键判据独立复算**; 零真实外发(见 §四)
- **结论: PASS(无阻断项)**。1 条 pre-existing 文案问题走 §23.7⑤ 上报通道(§七, 非本改动引入); 另 2 个低分项(<80)已滤(§八)

## 一、保留判据独立复算(自己构造「应报」场景, 独立跑)

自写独立 harness(真源码导入/抽取 + 假 subprocess + 假 notify + ZeroOutboundTrap 全程在位, 与实施方测试零共享), 共 **34 项断言全 PASS、0 FAIL**:

| # | 场景(我独立构造) | 结果 |
|---|---|---|
| ①-1 | 同一 (date,index) 但 signal 不同 → 必须照报(精确键语义) | PASS(报) |
| ①-2 | 7 个已接受 + 1 个新缺键 → 只报 1 个 | PASS |
| ①-3 | n≥10 → `--severe`; n<10 → WARN + dedup 86400 | PASS |
| ①-4 | 表缺失 / JSON 损坏 / 无 accepted 键 / 空列表 / accepted 类型异常(字符串) 5 态 | 全部退「全量告警」且不崩(fail-safe) |
| ②-1 | 单轮 3 文件脱节(== 阈值) → 告警 | PASS |
| ②-2 | 单轮 1 文件但 ≥1MiB → 告警; 1MiB-1 字节 → 静默 | PASS |
| ②-3 | 连续 3 轮(24h 窗内) → 第 3 轮告警 | PASS |
| ②-4 | 中间清零轮 → 重计; 相邻轮间隔 >24h → 重置 | PASS |
| ②-5 | 状态文件损坏/缺失 → 退化不崩(退规模判据) | PASS |
| ③-1 | warning 档恢复 → `--tier info` 且无 `--alert-issue`(仅 dashboard) | PASS |
| ③-2 | severe / `self_heal`(生产实况值) / 无 tier → 双通道不误降 | PASS |
| ③-3 | warning+severe 混合 → 拆 2 批各自正确 | PASS |
| ③-4 | pending 桶保留 tier; info 批失败入 pending | PASS |

**① 前提独立取证(云上只读复跑枚举)**: MISSING n=8, 与 `accepted` 8 键逐位一致(`latest_signal_date=20261009`、`buy_rows=42168`、`freeze_keys=28284`)。接受清单 8 键 = `20260922|sz_div|buy`、`20260929|gz_399395|buy_aux`、`20261002|cac40|buy`、`20261002|dax|buy_aux`、`20261005|hscei|buy_aux`、`20261005|hstech|buy`、`20261006|cac40|buy`、`20261006|hsi|buy_aux`。

**② 阈值合理性(生产节奏实证, 排除「连续判据永不触发」猜想)**: 云上 `r2_upload_async` 日志实读 verify-r2 每天 3~7 轮(10-09 21:11/21:42; 10-10 02:20/05:10/16:52/18:00/21:16; 10-11 02:16/05:11/16:51/21:16), 相邻轮间隔 3~12h ⊂ 24h 窗 ⇒ 「连续 ≥3 轮」在生产节奏下第 3 轮可达; `a-stock-all.json`=7.4MB ⇒ 单文件脱节即过 ≥1MiB 判据。

**③ 作用域**: `"tier": "warning"` 全仓唯一赋值点 = `schedule_monitor.sh:1236`(`{task}|r2_skip_alert` 未升级档); severe 在 L1252、self_heal 在 L1617/L2291、`monitor_72h.sh`(severe/self_heal)均不等于 warning ⇒ **作用域确实只影响 r2_skip 恢复侧**, 与拍板范围一致。

## 二、测试真伪抽验(防「抄副本」+ 防「改断言迁就实现」)

1. **ast 抽真源码块机制成立(逐字对账)**: 用实施方自己的 `_upload_src()`/`_recovery_block_src()`, 与「按文件行区间同法抽取」的原文逐字比对 → `their==mine = True`; ②块 = `upload_r2.py` **L3882-L3929** 原文(含 `_compute_stale_consecutive_rounds`/`_oversized`), ③块原文逐字在 `schedule_monitor.sh` = True(含 `_send_recovery_batch`/`"--tier", "info"`)。
   - 备注: 我先前脚本里 `blk.strip() in src = False` 系 **dedent 缩进假阴性**(我脚本口径问题), 已澄清排除抄副本。
2. **3 个既有测试适配逐一看, 无「改断言迁就实现」**:
   - `scripts/test_188_s06_sync_blindspot.py`: 正例由「1 文件脱节」改「3 文件(规模超常)」驱动 —— 系授权行为变更(②降噪)后的**等价正例**, 断言语义(真脱节→外围告警)保留, 非削弱。
   - `scripts/tests/test_verify_r2_full_standalone_20261011.py`: 2 处正例同上改超常驱动; **新增反向用例** `test_weekday_small_stale_only_logs_no_alert`(单文件 → 零外发通知 + 「仅日志」留痕断言)。
   - `scripts/tests/test_223_timeout_gradient_copy.py`: 仅渲染 env 补 7 个新字段(`_stale_count` 等), **全部断言原文未动**。
3. **全量回归独立重跑**: `pytest -q scripts/tests/` → **780 passed / 2 skipped / 0 failed(93.07s)**, 与实施方报告数字逐位一致。

## 三、授权范围核对(对照 §3-3 拍板原文)

| 项 | §3-3 授权 | 实现 | 判定 |
|---|---|---|---|
| ① | 须保留真漂移判别维度=错误类型区分, 不可一刀切静音 | 精确键过滤(同 date/index 异 signal 照报)+ 表外新事件照报 + 表坏 fail-safe 全量 | 合规且更彻底(治根方向: 接受清单落数据层) |
| ② | 可降日志级 | 小规模仅日志 + 双级判据(规模≥3 文件/≥1MiB, 连续≥3 轮)超常照报 | 合规, 比「降日志级」更保守(保留应报面) |
| ③ | severe 降 warning/聚合 | 只动恢复侧 warning→info; severe 档不动; 实施报告已标注「严重级降级 L3c 已上线, 残留只是恢复通知」现状核实 | 偏离有据、范围更窄非更宽, 报告已如实标注 |

## 四、零外发 / 零污染复核

- 我的独立 harness 全程 `ZeroOutboundTrap`(包 urlopen/SMTP): `trap.hits == []`; 假 notify 就位断言通过; 假 subprocess 记录并核对调用参数(如 `--tier info` 确在 warning 批)。
- 污染对账: worktree `data/` 跑前/跑后 **mtime+size 逐位一致**(diff 为空); `data/.r2_standalone_stale_state.json` 未生成(我的场景全在 tempdir `STATIC_DIR`)。
- 全量 pytest 抽验: 188 薄包装自带 `trap_hits == []` 断言语义; 各用例 `monkeypatch.setitem(sys.modules, "notify", fake)` 打桩。跑期间无真实外发迹象。
- ⚠️ 诚实标注: 全量命令 = CI 门禁⑧ 同款(CI 每 push 跑), 我未对全部 780 例做逐例 stub 审计 —— 已做的是「我的核心区域独立 harness 全程 trap + 188 包装断言 + 目标文件 24 例打桩抽查」。

## 五、同类面 sweep(告警发出点全仓)

- ① `_alert_frozen_missing` 全仓引用仅 `signal_kelly_backtest.py`(定义 :341, 调用 :1966); `hold_days_sweep.py:55` 为研究档覆写(仅打印不通知) ⇒ 无第二发出点。
- ② 「独立上传链产物」文案全仓仅 `upload_r2.py`(+其测试) ⇒ 单发出点。
- ③ `tier="warning"` 全仓唯一赋值 L1236 ⇒ 见 §一③。
- 接受清单 `config/signal_kelly_frozen_missing_accepted.json` 全仓**唯一读取方** = `signal_kelly_backtest.py`(单事实源, 无第二副本)。

## 六、§21 公示 / 前端联动(确认无)

- commit 只动后端监控/告警链(`schedule_monitor.sh`/`upload_r2.py`/`signal_kelly_backtest.py` 告警段/测试/新 config/docs), **未动算法/评分/权重/track_score** ⇒ §21 公示无需联动。
- 「dashboard」= 云上内部 `data/alerts/info_log.jsonl`(`notify.py:242`); 全仓 grep `info_log` 在 `static-site/` 零命中 ⇒ **不进前端展示层**, 无 §22 多展示位一致性问题。

## 七、pre-existing 项(走 §23.7⑤ 上报通道, 不作本改动 finding)

- ② 脱节告警正文写「台账实有池(本条对账对象): a-stock-{...} + overview.json + news_digest 家族 + schedule_stats.json」, 但云上台账 `.r2_standalone_keys.json` **实读 146 key / 62 家族**(含 `alert_analyze_*` 等大量未列家族; 本次 ssh 只读复核)。
- 归因: 本 commit 对该行**仅重排缩进, 文案逐字未改**(`git diff a7f6413ec^ a7f6413ec` 证实), 系 #217④(2026-10-06)引入的旧文案。
- 处置建议: 主控带上报用户, 决定是否修文案(不影响本条判据与行为)。

## 八、低分滤除登记(置信度 <80, 未进 findings, 备查)

1. ② 状态文件写失败(OSError)⇒ 连续判据静默退化到仅规模判据 —— 有界(规模维度不受影响、写失败打 stderr 非静默), 概率低。
2. ③ 混批失败边缘: 非 warning 批被吞/失败时本批 recoveries 全量入 pending; 尾部摘要补列(L3193-3207)**不读 tier** ⇒ 该 warning 恢复可能出现在 23:25 摘要(进群/邮件)。概率低(需同轮混档恢复+批失败), 且比改动前范围窄(改动前本就双通道)。

> 另 2 个低分项(<80)已滤, 见上表(§10.2 口径)。

## 九、可复现证据(关键命令)

1. 云上 ① 前提: `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` 只读复跑枚举脚本 → `MISSING n=8` 与 accepted 逐位一致。
2. 云上 ② 节奏: 只读 `r2_upload_async_*.log` verify-r2 行时间戳(见 §一)。
3. 抽取对账: `ast` 抽 `upload_r2.py` `if stale_standalone_names:` 节点(L3882-L3929) + `textwrap.dedent` 后与实施方 `_upload_src()` 输出逐字比 → True。
4. 全量回归: `python -m pytest -q scripts/tests/`(nohup 落盘 `/tmp/rev_full_pytest.log`, 已跑完, 无残留进程) → `780 passed, 2 skipped in 93.07s`。
5. 独立 harness(我的, 在 `/tmp/review_denoise_indep.py`, 不入库): 真源码 + 假 subprocess/notify + ZeroOutboundTrap, 34 断言 → 全 PASS; 零污染对账见 §四。
6. sweep: `grep -rn "_alert_frozen_missing\|冻结表缺失\|独立上传链产物\|\"tier\"\|signal_kelly_frozen_missing_accepted" scripts static-site`(输出见 §五)。
7. 文案 diff: `git diff a7f6413ec^ a7f6413ec -- scripts/upload_r2.py`(「台账实有池」行仅缩进重排)。

## 十、给主控的复查建议(merge 后观察点)

1. 云上生效首日核: ① 21:12 冻结表缺失报告应消失(如再现=新缺键, 属预期照报); ② verify-r2 日志出现「仅日志」形态且无 notice 外发; ③ r2_skip 恢复不再进群/邮件(仅 dashboard)。
2. 若首日出现「新缺键事件」告警, 属保留判据正常工作, 按流程评估是否追加 accepted。
3. §七 文案问题建议一并上报用户。

—— 审查者: reviewer 独立上下文; 全程只读(本报告除外), **未 commit**
