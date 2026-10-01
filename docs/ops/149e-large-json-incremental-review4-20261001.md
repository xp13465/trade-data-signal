# #149e P2 caveat①补修独立复核报告(第四轮)— PASS

commit: `7079148af`(feat/149e-review4-20261001,基线 `f37b130c6`) | 审查: reviewer(独立复现,未改代码)
复现环境: `git archive 7079148af` 导出 `/tmp/149e-r4-src` 隔离运行;全部自测脚本指向导出代码独立重跑

## 结论: PASS(补修正确闭合 caveat①,未引入新缺陷)

第三轮 caveat①(成功分支 `tail -n 20` 冲掉「缺失 N」汇总行,LOG 不可见)→ 本次补修在成功分支 `tail` **之前**增加 `grep -F "/ 缺失 " "$_R2_TMP" | tee -a "$LOG" || true`,固定把汇总行写进 LOG。独立实测:复跑「零星缺失 N=2 + ≥20 行上传输出」用例,LOG 第 2 行即「缺失 2」汇总行,tail -20 输出在其后,汇总行不再被冲掉。升格分支与 upload_r2.py 零改动,前一轮升格回归独立复跑全 PASS,无回退。

## 必查项逐条证据

### 1. diff 是否只有成功分支 else 段 +3 行?
**是,升格分支与其余逻辑一字未动。**
- `git diff f37b130c6 7079148af -- scripts/` = 仅 `staticdata_backup_async.sh` +3 行(注释 2 行 + grep 1 行),全在成功分支 else 段(L199-201),升格分支(L206-207 `⚠ 失败` + `tail -20` + `STATICDATA_FAIL=1`)**一字未动**。
- `scripts/upload_r2.py` 本次 diff **0 行改动**(`git diff ... -- scripts/upload_r2.py | wc -l` = 0)——升格逻辑(abnormal 判定/非零退出)不可能被影响。

### 2. 补修行确实在 tail 之前执行?缺失=0 打印真实 0?
**是,双重确认。**
- 行序:L201 `grep ... | tee -a "$LOG" || true` 在 L202 `tail -n 20 | tee -a "$LOG"` 之前(读脚本 L199-202)。
- 缺失 0 真实值:`upload_r2.py` L2606 汇总行 `print(f"... / 缺失 {missing_n}(...)")` **无条件执行**(非仅缺失时打印),`missing_n = len(missing_rels)`,缺失 0 时打印真实 `/ 缺失 0`。独立复跑自测场景②实测 LOG 含「/ 缺失 0」+ 25 PUT 全成功,无空洞无报错。

### 3. `|| true` 是否只吞 grep 无匹配,不掩盖其他错误?
**行为正确。** `grep -F "/ 缺失 "` 在成功分支**总能匹配**(汇总行 print 无条件执行且格式含 `/ 缺失 `),正常情况 rc=0;无匹配场景(理论上仅极端竞态,防御性处理)rc=1 被 `|| true` 吞,LOG 无空洞行(独立验证场景②b:grep rc=1、LOG 无空串)。
- **精确匹配不串味**:逐条缺失告警走 stderr 格式 `⚠ 源文件缺失(计入缺失计数): data/...`,不含 `/ 缺失 ` 模式(无「斜杠+空格」前缀);`-F` 固定字符串只捞汇总行,不把逐条告警也刷进 LOG(实测 LOG 片段仅 1 条汇总行,无逐条)。
- **轻微措辞不精确(非缺陷)**:报告 §3.4 称「`|| true` 吞 grep 无匹配退出码」,严格说 pipefail 下若 grep 匹配(rc=0)而 `tee` 写 LOG 失败(rc=1),`|| true` 也会吞掉 tee 失败。但 LOG 写失败=磁盘满/日志不可写=脚本整体已处灾难态,且原 `tail | tee` 的 tee 失败同样不阻断(脚本不 set -e),非本次补修引入。意图描述正确,不影响结论。

### 4. 新缺陷排查(与 set -e / pipefail / tee 失败 / $_R2_TMP 缺失 / 非生产机)
- **set -e**:脚本 L44 显式「不 set -e,每步显式判退出码」,`|| true` 无交互风险。
- **pipefail**:脚本 L43 `set -o pipefail`,grep 无匹配 rc=1 正确传播到管道并被 `|| true` 吞(无 pipefail 时管道 rc=tee 恒 0,两种情况都安全——grep 输出为空 LOG 无空洞)。已独立验证。
- **tee 失败**:同上,被 `|| true` 吞,但为同尾行 pre-existing 设计,非新缺陷。
- **`$_R2_TMP` 缺失**:L191 `mktemp` 在成功分支必然先创建。mktemp 失败(极低概率)→ `_R2_TMP` 空串 → grep 报 `No such file` rc=2 被 `|| true` 吞;原代码 `tail -n 20 ""` 同样报错且不阻断。非新缺陷。
- **非生产机**:补修只改成功分支日志输出,不改变上传/锁占/隔离行为;`STATICDATA_BACKUP_SKIP_R2_UPLOAD=1` 测试隔离钩子(L190)一字未动。

### 5. caveat①是否闭合?
**是,独立实测三重闭合。**
- 真实 bash 三行 + 真实 `tee -a` 写 LOG 文件(25 文件缺 2 → 23 行上传输出 ≥20):最终 LOG = `[step3.5b 上传] OK` + **汇总行(第 2 行,含「缺失 2」)** + tail -20 上传行 20 行。汇总行位于 tail 输出之前,不再被冲掉。
- 实施自测脚本 `/tmp/149e_async_log.py`(真实 cmd_upload_large_json mock 桶 + subprocess grep/tail 等价复刻)指向导出代码**独立复跑 8/8 PASS**,与报告 §3.4 声称一致。
- 对照:无补修时 LOG 仅 21 行(OK + tail 20),汇总行在输出头部第 1 行被 tail 冲掉——caveat 场景真实存在,补修后可见。

### 6. 升格分支回归(全量缺失 → 非零退出、批量阈值边界)
**独立复跑全 PASS,未被本次补修影响**(upload_r2.py 零改动为底层保证)。
- 全量缺失(10/10):`sys.exit("✗ 源文件缺失异常(10/10)...")` 非零退出,升格提示语随 rc 携带。
- 批量阈值边界(独立构造 100 文件):缺 49(49≥5% of 100)→ 升格非零;缺 4(<5%)→ 不升格正常跑。
- 零星缺失(25 文件缺 2):不升格 + 输出含 `/ 缺失 2` 汇总行(即补修 grep 的目标行)。
- 前一轮回归脚本(T1-T4/T6、T5 周日强制全量)指向导出代码独立重跑:**全 PASS**(T1 清单新文件/T2 gzip 确定性/T3 marker 残留强制全量/T4 源缺失不阻断/T5 周日强制全量 HEAD/T6 dry-run 不写 marker)。
- 说明:升格逻辑(abnormal 判定/退出)在 `upload_r2.py`,本次 diff 零改动;`staticdata_backup_async.sh` 升格分支(else)一字未动。

### 7. 报告 §3.4/§3.5 口径核对
- **§3.4**:自测 8/8 声称与独立复跑一致(场景①缺失 2+≥20 行 LOG 可见、场景②缺失 0 打印真实 0、场景②b 无匹配被吞无空洞)。「30 行上传输出冲掉头部 3 行」为第三轮复验观察值,合理非夸大。
- **§3.5**:交互观察经 `notify.py` L2106-2126 + `alert_denoise_rules.py::r4_staticdata_grade` 验证属实——dedup_key=staticdata_backup_fail 走 21600s 强迫窗 + r4_staticdata_grade 分级;单日未追平→ info(只记 dashboard)、连续 ≥2 天未追平→ SEVERE。报告明确标注「非本补修引入,供主控转述用户知悉;如需首日直达用户另行拍板」,属如实记录非夸大。
- **无未标注采样推算**:§3.4/§3.5 数字均有实测/代码依据,无推断式结论。

## 分支结构提示(给主控 merge 调度)

- review3 报告(e5ad18a19)在 `feat/149e-review3-20261001`,review4 补修+报告更新(7079148af)在 `feat/149e-review4-20261001`,**均基于 f37b130c6**(共同祖先)。
- 两分支改动无文件冲突:review3 分支只加 `149e-large-json-incremental-review3-20261001.md`;review4 分支改 `staticdata_backup_async.sh`(+3)与 `149e-large-json-incremental-20261001.md`(§3.4/3.5)。
- 合并需 **两个分支都合入 main**(review3 有第三轮报告、review4 有补修+第四轮报告+报告更新),顺序无强制,无冲突。

## 新发现缺陷

无实质缺陷。仅 1 项 <80 分低分项已滤(§3.4「|| true 只吞 grep」措辞在 pipefail 下严格意义上也吞 tee 写 LOG 失败——但 LOG 不可写=整体灾难态,非补修引入,且原 tail 同无保护,不影响本次补修正确性)。
