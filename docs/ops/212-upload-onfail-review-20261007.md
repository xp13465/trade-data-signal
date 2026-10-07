# #212 独立审报告 — R2 上传通道接 on_fail 告警

- 日期: 2026-10-07 | 审查者: 独立 reviewer agent(与实施 agent 不同上下文)
- 审查对象: `feat/212-upload-onfail-20261007` tip `843f34106`,base/merge-base `0967fe413`(vs 现 origin/main `010282316` 已前进)
- 方式: **纯只读** —— 分支内容全部经 `git fetch` / `git show` / `git diff main...branch` 读取(**未 checkout 到主树**);动态测试在 `/tmp/rev212-sandbox` 副本环境(分支版 upload_r2.py + 测试 + dummy 凭证 `.env`(端点 invalid.example)+ 网络守卫)跑。**全程未真发通知、未真跑生产上传、未碰 R2 写**(§18 L48)。
- 判定: **8 项 = 7 PASS + 1 FAIL**(第 7 项: 实施报告对 `cmd_upload` 的"无定时调用方"声明不实,详见 F1)

## 逐项判定

### 1. §23.2 挂点全 + 不误挂 — PASS
- 引擎调用点独立枚举 **15 处** = 本批 13(`_channel_on_fail` 接线)+ etf-score(#204 既有)+ fund-nav(唯一调用方已 severe,矩阵判不挂)。与实施报告数一致。
- 三类非触发路径独立复核**均不经 on_fail**: export-guard(自身 notify 1800s,return 更早)/ `total == 0`(在 `ok != total` 判断前 return)/ cmd 级前置 `sys.exit("无 xxx json")`(不进引擎)。分支版中 `on_fail(...)` 唯一调用点仍在 `ok != total` 失败分支(`sys.exit(1)` 之前)。
- PUT 调用点全枚举(9 处): L754 cmd_upload(单文件——见 F1)/ L845 multipart / L964 `_upload_one` / L1173 备份 COPY / L2520/2543 weekly+monthly 私有备份桶 / L2633+ 私有桶 / L3144 `BACKUP_BUCKET` large_json —— **无遗漏的公开数据通道**;私有桶(前端零展示)与矩阵判据一致。
- 14 个 cmd_name 均为真实子命令,`r2_prefix`/`impact_note` 逐通道与通道实际范围相符(静态逐条对过)。

### 2. 精确锁 — PASS(独立复算,不采信实施数字)
- `grep -c "on_fail=_channel_on_fail(" → **13**;`grep -c '"data-files", "upload-data-files"'` → **1**。全文件(分支版 4093 行)逐字符复核,无多余接线。

### 3. §18 L48 零外发 — PASS
- **先证陷阱生效再跑**(probe_trap.py,不动业务逻辑): STEP1 `import notify` 走 Fake、真实对象零触达;STEP2 绕过 Fake 直调真实 `notify.send` 被陷阱拦(AssertionError);STEP3 `check_dedup` 同走 Fake。三步全 OK 后才跑用例。
- 守卫跑法三层: ①notify 的 send/send_email/send_telegram/send_feishu 全封(触达即炸) ②socket 非本机连接一律阻断 ③沙箱 + dummy 凭证。
- 结果: **test_212 43 passed**(13+1+1+13+13+1+1);**test_204 21 PASS/0 FAIL**(其输出自带 "真实 trap 0 次");**test_193 38 PASS/0 FAIL**(1 项"修复前对照"skip: 沙箱无远端 git ref;真 worktree 为 40 PASS 相符)。全程无任何真发/真上传迹象。

### 4. 负控有效性 — PASS
- 改前静默反事实: test_d(13 例)+ test_e 静态(`git show` 改前版本 count 0)证"病灶真存在"。
- 失败路径: 仍 `exit 1`;state 不写(重传自愈语义未被破坏,即部分成功刷 checkpoint 照旧);notify **恰 1 次 severe**(调用计数断言)。
- 成功路径: test_c(13 例)零告警;不误报。

### 5. 回归面 — PASS
- 成功路径纯加 kwarg:`on_fail=None` 默认,引擎签名未改,引擎成功分支 diff 无改动(`main...branch` 逐 diff 复核)。
- 既有测试独立复跑: test_204 21/0、test_193 38/0、`check_r2_channel_coverage.py`(分支版文件) ALL_PASS。

### 6. 双告警形态 — PASS(附披露 nuance)
- 独立比 11 个既有 caller 的 dedup key: `intraday_schedule_stats_r2_fail` / `intraday_upload_index_r2_fail` / `intraday_upload_intraday_r2_fail` / `kelly_intraday_upload_r2_fail` / `schedule_stats_r2_fail` / `deploy_r2_upload_fail` / `gold_night_r2_upload_fail` / `update_lab_r2_upload_fail` / `s06_snapshot_fail` / `nextday_gap_check_fail` / `nextday_plan_gen_fail` —— 与 `r2_channel_upload_fail_data-files`(21600s)**全不同 → 无互吞**。
- nuance(披露,不阻断): 系统性大面积 R2 故障时可最多 14 通道各发 1 次(每通道 6h 窗口);R5 拥堵合并管辖 monitor 侧,不覆盖 notify 直发 severe —— 属既有形态(#204 审已认可),实施报告已披露。

### 7. 报告外静默候选 `cmd_upload` — **FAIL**
- 实施报告(分支内 `docs/ops/212-upload-onfail-impl-20261007.md` L60)声明:「cmd_upload … **人工即时命令(无任何定时/systemd 调用方;全仓 grep 仅用法示例,无 .sh 调用)** ⇒ 判定范围外」。**独立核查该声明不实 → F1**。

### 8. git 纪律 — PASS
- 单 commit `843f34106`;merge-base = `0967fe413` = 分支 base;改动 3 文件 = impl report + test + `scripts/upload_r2.py`,**无 `data/`、`static-site/` 夹带**;origin/main 无该 hash(未违规 push main);无 force 迹象。
- 附注: origin/main 已前进到 `010282316`,分支 base 落后 → merge 时需 rebase,由 main-merge.sh 统一处理(非违规)。

## F1(高置信 95)— 实施报告对 cmd_upload 的范围声明不实

- **定位**: `docs/ops/212-upload-onfail-impl-20261007.md` L60(分支内)。
- **反向证据**: `app/collector/intraday_snapshot.py::_export_affected_json`(L2114)在 L2153-2177 对每个 `EXPORT_RANGES` 起子进程:
  `[sys.executable, <repo>/scripts/upload_r2.py, "upload", <local>, f"data/sentiment-{rng}.json"]`;
  该函数在采集主流程 L2631 被调用(反哺日=交易日每轮);整链由 `scripts/intraday_snapshot.sh` L74(`python -m app.collector.intraday_snapshot`)在云上定时器每 ~10 分钟执行。2026-07-20 引入(修复"盘中 sentiment 不推 R2")。
- **复算**: `grep -n "_export_affected_json\|upload_r2.py" app/collector/intraday_snapshot.py` → L2114/L2156/L2164/L2631。期望="无定时调用方";实测=定时链子进程调用。**子进程 argv 是变量形式**(`str(_script)`, `"upload"` 分离),故字面 grep `"upload_r2.py upload"` 命中不了 —— 典型字面量 grep 漏常量(memory `verify-grep-constant-not-literal`)。
- **影响(按矩阵两判据)**: 判据 2「全部调用路径已有 deterministic severe 告警」→ **否**。失败时 cmd_upload 仅 `print "✗ status=…"` 且 **exit 0**;调用方按 `rc==0 and "✓" in stdout` 判失败 → print + `log_collect(..., "sentiment_r2_upload", "error")` → 仅 collect_health UI 小红点(弱信号)。schedule_monitor 十维**不含**此 metric(ANOMALY_RE 要求 `✗\s*R2 上传`带空格;此处打印 `R2上传失败` 无 ✗ 无空格不命中;时效维度只查 overview/intraday_snapshot)。
- **缓解面(为何不紧急)**: ①链内自愈(下一轮 10 分钟重传) ②同链 `upload-intraday` 覆盖 sentiment-3m/6m/1y(系统性 R2 故障时它会先响 severe `intraday_upload_intraday_r2_fail`)⇒ 残余静默窗 ≈ 仅 3y/5y 大 range 单独失败 ③17:50 日链兜底。
- **建议(主控裁决,二选一)**: ①接受为"披露但不修"—— 须**订正** impl report L60 与矩阵报告限制节的事实错误措辞(§23.11: 不静默) ②另单纳入"全站单点统一"(cmd_upload 失败改非零退出 + 调用方接线),可与矩阵报告 §3 批 3 各可选项合并评估。**不建议**因此拦截 #212 merge(本批范围=矩阵定义 14 通道,机制与测试均正确)。

## 低分滤除(置信 <80,仅列举不展开)

1. data-files 告警文案正文不含失败文件名(仅汇总;实施报告 §8 已披露)。
2. 个别 impact_note 文案比真实调用方面略宽(如 "schedule_stats 等"),不属误导。
3. cmd_upload 人工场景 exit 0 语义本身可接受(只在被自动链调用时成问题,见 F1)。

## 诚实标注 / 限制

- 全程未 checkout 主树;本报告为唯一产出文件(新增未 commit,主控决定是否随分支落档)。
- 沙箱动态证据为副本环境(1 项修复前对照因缺远端 ref skip),非真 worktree 全等价。
- F1 为静态证据链(读码 + grep + 链路还原),非实跑观测;沙箱内未(也不能)复现真实子进程上传场景。
- 未运行任何真实上传/R2 写/通知;守卫三层 + 陷阱先证有效(memory `notify-script-selftest-must-stub` / §18 L48/L50 合规)。
- 进度留痕: `/tmp/agent-progress-212-review.md`。
