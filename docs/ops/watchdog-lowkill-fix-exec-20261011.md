# r2_upload_async 低速 kill 判据修复 · 实施报告(a1 窗口参数化 + a2 收尾豁免,2026-10-11)

> 调研依据:`docs/ops/watchdog-tradesim-slowkill-20261011.md`(researcher,已合 main `28380a78f`)。
> 拍板:用户 2026-10-11「直接干」;授权范围 = 仅 a1+a2(+必要的最小重构抽取)。
> 分支:`feat/watchdog-lowkill-fix`(worktree 隔离,只推 feat,不碰 main)。

## 0. 结论速览

- **改了什么(4 个文件)**:新增判据纯函数库 `scripts/lib/upload_watchdog.sh`(4 个无副作用函数);
  `scripts/r2_upload_async.sh` 低速判据接线改造(a1 窗口 + a2 豁免 + 单点常量);
  新增回归测 `scripts/tests/test_watchdog_lowkill_20261011.py`;本报告。
- **三条要求测试全过**:`61 PASS / 0 FAIL`(① a2 豁免 ② 真停滞照杀 ③ a1 护栏,另加解析/接线/负控变异)。
- **保留判据未破(红线)**:停滞判据 900s(> 内层 600)+ 7200s 硬兜底 + 三处 kill 分支 dump 尾部 30 行 +
  `R2_KILLED` 登记,全部逐条断言在位(测 [D])。
- **真正变化面**:低速杀停条件从「连续 5 次 60s 采样增量<1MiB」变为「连续 15 次(900s)」,
  且**接近完成(剩 ≤2 个文件)时不做低速杀**。生产/缺省两种 HTTP 超时取值下窗口均为 900(前提论证见 §2-a1)。
- **一处诚实标注(报告内部矛盾)**:调研报告 §5-a2 称「全历史 3 次 kill 全部命中 N/M ≥ 99%」,但其
  §2.2/§7.2 记 10-09 upload-index kill 尾行为 `[128/158]`(=81%)。本次严格按 a2 规格(N ≥ M-2)实现,
  **该历史案例不被 a2 豁免**(仍由 a1 的 900s 窗口 / 停滞判据覆盖);已把这组数据固化成测试断言(测 [C]),
  供主控/reviewer 判是否需再扩豁免面。

## 1. 现状核实(报告行号 vs 实际代码,改前)

| 报告引用 | 实际(改前) | 结论 |
|---|---|---|
| `r2_upload_async.sh:102-187` 看门狗函数 | 一致,`run_r2_upload()` 定义在 L102–187 | ✅ |
| `:112-125` 停滞判据防倒置护栏 | 一致(L113–125:读 `_http_to` / `_stall_secs`,≤HTTP 则抬到 HTTP+300) | ✅ |
| `:159-181` 低速判据(60s×5 = 300s) | 一致(L159 `if [ $((_slept % 60)) -eq 0 ]` … L181 `fi`) | ✅ |
| `:149-158` 7200s 硬兜底 | 一致 | ✅ |
| `:87-100` kill tail dump(#217③) | 一致 | ✅ |
| `:118-125` 读 `R2_UPLOAD_HTTP_TIMEOUT`(默认 30,云上 600) | 代码一致:`local _http_to="${R2_UPLOAD_HTTP_TIMEOUT:-30}"` | ✅ 代码层核实 |
| 云上 `.env` `R2_UPLOAD_HTTP_TIMEOUT=600` | **本次未 ssh 核实**(采信调研报告 §0/§1.1 的生产事实 + 用户拍板文字) | ⚠️ 采信,非本机核实 |
| `upload_r2.py:479-481` 低速判据消费的字节来源 | 一致(仅注释,无窗口常量) | ✅ 无需同步 |

**行号位移说明**:改动在 `run_r2_upload()` 内插入 ~12 行注释/取窗口/取 need,故改后低速采样块位于
**L173–205**(原 159–181)。

**同类复制面核查(§23.3)**:`grep -rln "_low_bad\|低速" scripts/ app/` 结果 = `upload_r2.py`(仅注释) +
`r2_upload_async.sh` + 两个测试。**`deploy.sh` 内无 `run_r2_upload` 副本、无低速判据**
(只有 L72 一行注释提及「同 run_r2_upload 模式」)⇒ 本脚本是**唯一落点**,
pending-index #174 所谓「deploy.sh + r2_upload_async.sh 双副本」已随 async 化收口,本次无需双改。

## 2. 改法及依据

### 2.1 最小重构:判据抽成纯函数库 `scripts/lib/upload_watchdog.sh`

为什么抽:宿主 `r2_upload_async.sh` 主体会**真的发起 R2 上传**,而 §18 L50 规定探针一律 static-only、
**绝不 source/exec 业务脚本主体**。把判定抽成无副作用纯函数后,测试经 `bash -s` 的 stdin 管道
`source` 该库即可(同 `lib/repo_paths.sh` pattern)——**覆盖真实代码**,不写第二份实现(免 §5.4⑦ 漂移)。

库内 4 个函数(全部纯、无 IO、无落盘):
- `r2_low_speed_window <http_timeout>` → 窗口秒数(a1)
- `r2_low_speed_need <window>` → 触发 kill 所需连续采样次数(= ⌈窗口/60⌉)
- `r2_parse_progress <[N/M]>` → `"N M"`(a2 取 N 用;非法/空 → `0 0`)
- `r2_tail_near_complete <M> <N>` / `r2_low_speed_should_kill <bad> <win> <M> <N>`(a2 判定)
- 常量 `R2_LOW_SPEED_MIN_BATCH=10`(批量下限,**单点定义**替代脚本内两处 magic number 10)。

### 2.2 a1 低速窗口参数化:300s → `max(900, HTTP超时+300)`

- 写法与停滞判据同款(不硬编码):`_low_win="$(r2_low_speed_window "$_http_to")"`,函数体
  `w = http_to + 300; [ w -lt 900 ] && w = 900`。
- **数学校验(防梯度倒置)**:内层自愈周期上界 ≈ `HTTP超时 + 退避和(≤15s) + 重试后首行打点(≤60s)`
  = `HTTP超时 + 75`。`max(900, HTTP+300)` 恒 > `HTTP+75`(HTTP≤625 时窗口 900 > HTTP+75;HTTP>625 时
  HTTP+300 > HTTP+75)⇒ **只要内层还活着(超时→重试→打点回暖),900s 窗口不可能杀**。
- 生产事实(HTTP=600):窗口 = max(900,900) = **900 > 675** ✅;缺省/非法 .env(回落 30):窗口 = 900 > 105 ✅。
  ⇒ 「生产机 600s」与「默认缺省」两种取值下都成立,且缺省时护栏(900 下限)仍生效。
- 杀停阈值随之 = ⌈900/60⌉ = **15 次采样**(原 5 次)。
- 数学校验另注:内层 5 次重试全败后会走「✗ 失败行 → 通道 fail → 对账告警」正路,不需要外层低速兜底;
  真停滞由**停滞判据 900s(mtime)/ 7200s 硬兜底**继续守。

### 2.3 a2 收尾豁免:接近完成不杀

- 判定:`M(批内总数) > 10` **且** `N(已完成数) ≥ M-2`(只剩最后 ≤2 个文件)⇒ 低速判据**不杀**,
  落一行日志(`… 低速真空达 900s 但处于收尾阶段(完成 N/M), 跳过低速杀(a2 收尾豁免)`)。
- 依据:8 线程池收尾阶段(其余 7 线程空闲、无完成行可产)必然出现零增量真空;杀它 = 100% 触发下轮
  marker 残留 → 全量(200MB 级)。全历史 3 次低速 kill 均属「收尾真空」形态(见 §0 的诚实标注)。
- **只放开「低速」这一路,不是「永不杀」**:`r2_low_speed_should_kill` 仅返回「不杀」,停滞判据/硬兜底不走此函数。

### 2.4 接线后低速采样块(改后 L173-205)逻辑

```
每 60s: 取最后一个 [N/M] → r2_parse_progress 得 N/M(N 每轮更新;M 仅首批 > 10 时固定,与旧行为一致)
        求日志 (NB) 之和 _upb;若 M > R2_LOW_SPEED_MIN_BATCH 且增量 < 1MiB ⇒ _low_bad++
        r2_low_speed_should_kill(_low_bad, _low_win, M, N) ⇒ kill(文案改「近 N 分钟」)
        否则若 达窗口 且 r2_tail_near_complete ⇒ 落豁免日志(每段真空只报一次)
```

## 3. 测试结果(三条要求 + 附加)

跑法 / 命令见 §6。结果:`pytest -q` → **1 passed**;直跑明细 → **PASS=61 FAIL=0 / ALL_PASS**。

- **① a2 收尾豁免**(命中即不杀):
  `M=103,N=102 / 103,101 / 103,103 / 158,156 / 11,9` 达窗口(15 次)均 **不杀**;窗口 1200 时同样生效;
  **边界** `M=103,N=100`(剩 3 个)⇒ **仍杀**(防豁免过宽)。
- **② 真停滞照杀**(红线):`M=103,N=50`(中段真空)、`N=1`(通道开头)、`N=0`(零完成行)、
  `M=158,N=128`(10-09 index 历史形态)**全部仍杀**;未达窗口(`bad=14`)不杀;旧 300s 口径计数(`bad=5`)
  对新窗口不杀(**证明窗口真变长**);非批量通道(`M=10 ≤ 10`)/小通道(`M=5`)不适用低速判据、不杀。
- **③ a1 护栏**:`window(600)=900`、`window()=900`、`window('abc')=900`、`window('')=900`、
  `window(900)=1200`、`window(1200)=1500`,逐个断言 `== max(900, HTTP+300)` **且** `> HTTP+75`;
  生产事实断言 `window(600)=900 > 675`;下限 `≥ 900`;`need(900)=15 / need(1200)=20 / need(300)=5`。
- **附加 [F] 解析**:`[102/103]→"102 103"`、`[1/158]`、`[73/103]`、空串/`abc`/`[x/y]`→`"0 0"`。
- **附加 [D] 接线(防「函数写了没接」)**:source 库 / 取窗口 / 取 need / `should_kill` 调用 /
  `tail_near_complete` 调用 / `parse_progress` 调用 + `read -r` 各断言在位;旧硬编码「近5分钟」
  与 `_low_bad -ge 5` 已消失;停滞 900s、`_http_to + 300` 护栏、7200s 硬兜底、`R2_KILLED`、
  三处 `_dump_kill_tail` 计数 == 3 全部保留。
- **附加 [E] 负控变异**:把库内 `[ "$w" -lt 900 ] && w=900` 替换为空后,`window(30)` 由 900 变 330
  ⇒ 证明下限断言**真在判**(不是恒绿)。
- **回归**:`test_237_check_preupload_backup_pytest.py`(含「备份进度行不撞低速判据形态」)+
  `test_223_timeout_gradient_copy.py` 一并复跑 → 20 passed(本次未改其判据面)。

## 4. §23.2 同类错误面清单(修完整 · 不逐文件打补丁)

| 同类面 | 是否同根因 | 处置 |
|---|---|---|
| 停滞判据(L153-162) | 同为「外层判死 vs 内层超时」梯度问题 | **已修过(#217②, 900s > 600)**,本次核对仍在位,未动 |
| 7200s 硬兜底(L163-172) | 同族(硬上限) | 核对在位,未动 |
| `deploy.sh` 内 R2 看门狗副本 | 历史双副本 | **实查无副本**(已 async 收口)⇒ 无第二处 |
| `fapi_bj_width_export.py` `_r2_upload_timeout`(#223③) | 同族梯度守卫(另一文件) | 已有测试(test_223)守,本次未动 |
| `s06_snapshot.sh` run_to 梯度 | 同族 | 本次未动(不在授权范围) |

## 5. §23.3 举一反三 + §23.4 团队协作

- **同组件还被谁用**:低速判据消费的两条日志格式(`[N/M]`、`(NB)`)由 `upload_r2.py` 产出;
  实查 `upload_r2.py` 侧仅注释提及,无窗口常量 ⇒ 无需同步改。备份进度行(`backup N/M`)刻意不带这些形态
  (由 `test_237` 守),本次改判据解析不改正则 ⇒ 不引入新耦合。
- **同模块待开发项(pending-features-index scan)**:本模块相关在册 = **#174**(判据换代,已落地)、
  **#180**(r2fix 残余:其 ㈠「marker→force_full→再杀」循环机制**仍在**——a1+a2 降低触发概率但
  **不结构性消除**它;其 ㈡「大文件低速误杀」本次正是被修的面)。**本任务未新增 pending 项、未占位冲突**;
  #180 ㈠ 的彻底消除属调研报告 §6-c1(周日 full 推迟,动语义)⇒ **待用户拍板,不在本次授权面**。
- **展示位一致性(§22)/算法公示(§21)**:本改动是运维看门狗判据,**不涉及站点展示数据或前端算法公示** ⇒ 无需公示同步(已确认 `purpose-notes.js`/`app.js`/`lab.js` 无相关文案)。
- **README(§23.1)**:未引用新的外部开源项目/库 ⇒ 无需补 README。

## 6. 命令附录

```bash
# 语法检查(改后)
bash -n scripts/r2_upload_async.sh          # → SYNTAX_OK
bash -n scripts/lib/upload_watchdog.sh      # → SYNTAX_OK

# 新增回归测(CI 门禁 ⑧ 口径)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_watchdog_lowkill_20261011.py
#   → 1 passed
/Users/linhuichen/code/trade/.venv/bin/python scripts/tests/test_watchdog_lowkill_20261011.py
#   → PASS=61 FAIL=0 / ALL_PASS(逐条明细)

# 相关旧测不回归
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  scripts/tests/test_237_check_preupload_backup_pytest.py \
  scripts/tests/test_223_timeout_gradient_copy.py \
  scripts/tests/test_watchdog_lowkill_20261011.py
#   → 20 passed

# 全量 scripts/tests 回归(CI 门禁 ⑧ 本机口径)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/

# 同类错误面扫描
grep -rln "_low_bad\|低速" scripts/ app/     # → upload_r2.py(注释) + r2_upload_async.sh + 2 测试
grep -n "run_r2_upload\|低速" scripts/deploy.sh   # → 仅 L72 一行注释, 无副本
```

**零外发自证(§18 L48 精神)**:新增测试**不 import `notify`、不触任何发送链**;`bash` 子进程只
`source` 纯函数库(`lib/upload_watchdog.sh`,无 IO/无网络);全程零 R2 调用、零落盘到 `data/`。
**禁跑真实上传链路**:本次未执行 `upload_r2.py`、未执行 `r2_upload_async.sh` 主体(§18 L50)。

## 7. 交付与后续

- 分支 `feat/watchdog-lowkill-fix`(base = `origin/main` `28380a78f`,开工 rebase 后提交),
  只推 feat;**merge main / 版本串 bump 不属本 agent**(主控走 `scripts/main-merge.sh`)。
- 本次**未改前端源码**,无版本串变更。
- **建议主控/用户跟进(不在本次授权面)**:
  1. 调研报告 §5-a2 与 §2.2 的 `[128/158]` 数据矛盾 ⇒ 若要让 a2 覆盖该形态,需扩豁免口径(动规格,须拍板);
  2. 报告 §6-c1(周日 full 大批量通道推迟夜间,P2)与 §5-d2(digest 幂等计数补偿)仍待拍板;
  3. #180 ㈠ 的「marker→全量」循环机制未结构性消除,本修复只是使触发概率大降。
- 生产观察点(报告 §6):下一个 204.8MB 级全量窗口验证「17 分钟窗口」是否自然走完;
  `grep '低速' data/logs/r2_upload_async_*.log` 新增计数应趋 0(收尾形态应转为「跳过低速杀」留痕)。