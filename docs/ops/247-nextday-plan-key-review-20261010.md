# #247 独立审查报告(reviewer, 2026-10-10)

- 审查对象: `feat/247-nextday-plan-key` tip `023d73929`(=远端已 push, 实测吻合), base `cd0abca03`(=origin/main 实测同 hash); worktree `/Users/linhuichen/code/trade/.claude/worktrees/agent-a239974c8cce13bce`
- 权威: 病灶证据链 = #245 批2 审查 §四(`docs/ops/245-batch2-impl-review-20261010.md`); 同类先例 = B4-3(`nextday_gap_check`, commit `5a92e6f81`); 实施报告 = `docs/ops/247-nextday-plan-key-impl-20261010.md`
- 方法: 只读 + 独立复跑(禁改代码/禁 push/禁云上写); 全程 worktree 跑 pytest(主仓有真实凭据 + legacy 套件不隔离 REPO 的既存卫生项); 授权 = 用户 2026-10-10「修吧」(§23.7)

## 结论

**PASS —— 九项审查点全 PASS, 无 ≥80 分 finding, 建议放行 `main-merge.sh`。**

## 一、九项审查点逐项

| # | 项 | 判定 | 证据点 |
|---|---|---|---|
| 1 | 统一方向正确性 | PASS | py `_severe_alert` L121 键 = sh L77 键 = `nextday_plan_fail`(实读); 旧键 `nextday_plan_gen_fail` 全仓 grep 独立复查: **零代码消费**(仅 py docstring L111 历史提及/测试反例常量/带日期历史文档, 均属允许面); 下游锚: monitor `schedule_monitor.sh:725-741` 的 R3 抑制判据是产物 mtime 函数(`r3_nextday_product_generated_today`, `alert_denoise_rules.py:436`)**不消费 dedup key**; `category_of`(adr L731)对两键均返回 None(未映射)⇒ 预算/摘要路由不变; `notify.py` 无 plan 键特判; `wrapper_channel_alerted` 调用方仅 cloud_unit_patrol/r2_consistency/gap_check。方向三源一致(B4-3 先例 / 下游引用 / 245 审查建议 a) |
| 2 | 行为正确性 | PASS | 红先验独立复现(用 `git show cd0abca03` 导出 base 版两文件): **4 failed / 4 passed**, FAILED=test_01/02/04/07, 失败断言语义=「py 键应=nextday_plan_fail 实=gen_fail」「sh 应被同键窗内抑制」「py 后发应被同键抑制」「sh 文案缺新语义」——**全在行为断言非空洞**; 分支单文件 **8 passed**(0.06s); 全量 **735 passed / 2 skipped**(91.56s) 独立复跑; 两分支读码+测试双核: R2 失败三路径(L1204/1214/1223)先 alert 再 r2_rc=1; py 未发路径(L967/976/987 return 2 无 alert、L1264 notify-fail 不调 `_severe_alert`)⇒ sh 无窗记录照发兜底(测试 03 驱动) |
| 3 | sh 段文案 | PASS | 与 B4-3 ngc.sh 句逐句同构(「本条为包装层兜底(py 同 dedup key: py 已发时本条被抑制; py 未发时本条兜底)」+ 增 R2 明细句); R2 失败失真句经「py 先发→sh 被抑制」路径不再出现; py 未发场景文案仍成立(真未生成) |
| 4 | py docstring | PASS | 旧「不同 key 不互吞=双保险」仅以「已废止」历史标注保留(L114-115); 现语义(先发者占窗/兜底不依赖不同键)准确 |
| 5 | 同类排查抽验 | PASS | 独立枚举全仓 py/sh 全部 `--dedup-key` 字面量(两份完整清单); 抽验三行成立: signal_kelly_backtest L338/341(fire-and-forget 不改 rc) vs kelly_intraday_rerun.sh L108/121/131(另一失败面)、detect_intraday_anomaly L288 vs intraday_snapshot.sh R2 三键、gen_daily_brief 0 自身 dedup vs run_daily_brief.sh 单通道; `preupload_backup_fail` py 与 monitor **本已同键**。**无漏报同型** |
| 6 | 零外发(§18 L48) | PASS | 测试双层=渠道 monkeypatch + `ZeroOutboundTrap`(包 urllib/smtplib 底层)+ teardown `hits==[]` 断言, 两次跑均绿即断言通过; 审查自身跑窗口(22:26:45-22:28:17)内主仓 ledger 零新增(mtime 仍 22:22:39) |
| 7 | §23.7 冻结面 | PASS | diff 仅 4 文件(报告/sh/py/新测试); 删除行逐行=py docstring 2 行 + py 键 1 行 + sh 正文 1 行, 全部在授权面; 未动 notify.py/monitor, 无顺手改 |
| 8 | 卫生 | PASS | 主仓 `data/alerts/alert_ledger.jsonl` inode 263108667; 22:22:39 新增行 source=feishu_chat_hook.py subject「🤖 主会话」= 主会话 hook(非本任务); 主仓无 22:2x 的 `__main__.py` 测试来源行; worktree inode 263291923; worktree `git status` clean |
| 9 | 测试质量 | PASS | 负控 test_06(分歧键双发); 红先验证判别力; 断言计数 26≥18(下限 18); tmp 隔离成立(`notify._ledger_path` 读 env REPO 调用时求值 ⇒ fixture setenv 生效; 实测单文件跑未写 worktree 台账); `bash -n` + `py_compile` OK |

## 二、残余风险(非阻断, 单列; ≥80 分 findings=0)

- **R1(pre-existing, 已报备用户)**: py notify-fail 分支(L1264-1279「计划已生成仅通知未送达」)sh 兜底文案仍含「次日买入计划未生成」, 与实况轻微不符; 新 trailer 只覆盖 R2 场景; 改前同句, 属授权面外(§23.7⑤ 报备即可)。
- **R2(pre-existing)**: legacy 全量套件不隔离 REPO 的既存卫生项(worktree 跑写 worktree、主仓跑写主仓); #245 审查已建议后续批加隔离。
- **R3(微口径)**: 测试对真实调用形态是手抄参数(`_py/_sh_severe_args`), test_01 只挡键不挡 window 单侧漂移(§5.4⑦ 精神的小缺口; 当前两处均 3600)。
- **R4(时点)**: 生效待 merge 后云上 pull 才进 22:30 链; 无故障注入复演手段, 首个真实失败即实况观测点。

## 三、主控收尾(补记)

- 本报告落档时已合 main(ff 至 `023d73929`, CI run 790 绿)+ 云上同步 + §0 云上核验 PASS(云上 HEAD 全等 + 两文件 md5 2/2)。
- worktree 已清; 观察项 = 下一自然窗口 nextday_plan 实跑(首个真实失败场景若出现, 应只见单封)。