# feat/ci-selfcheck-20261007 独立审报告(reviewer agent,2026-10-07)

**审对象**: `feat/ci-selfcheck-20261007` @ `0fe60d2aa`(+222/-4/5 文件:`scripts/lib/ci_selfcheck.sh` 新增 186 行、`scripts/main-merge.sh` +32/-1、role-implementer SKILL §3 / docs/main-governance.md / 根 CLAUDE.md §8 各 +1/-1)
**基线**: merge-base = `659900705`(= 本机 main tip)。**注意**: 审时 origin/main 已前进到 `f4a406a63`(#228 调研报告单 commit,与本 diff 零交集)——merge 前主控留意 base 落后 1 commit(main-merge.sh 第 4 步会提示;纯 doc 提交,低风险)。
**方式**: 全只读。①GitHub API 只读 GET(免鉴权、禁 -v/-i)②stub 替换 curl 独立复算(零真实外发)③只 source 目标 lib,未执行任何业务脚本主体(§18 L50)④云上仅只读 `systemctl list-timers`。本次审查自身对外的真实调用 = GitHub API 约 13 次只读 GET + 线上站点 3 次 curl(见 §5 披露)。

## 一、结论(merge 资格)

**PASS(可 merge)**。7 问逐条独立复算通过(证据见 §2)。另列 2 项**建议修**(同分支 1 个小 commit 即可;不修直接合的风险边界已在 F2 注明,由主控拍板):

| # | 级别 | 问题 | 阻断? |
|---|---|---|---|
| F1 | 建议修 | 轮询等待行 run 编号错位:TAB 空字段被 `read` 折叠,打出 `CI run #https://...`(应 `#661`) | 否。纯显示;**最终判定不受影响**(completed 时 conclusion 非空即恢复对齐,success/failure 两路实测输出正确) |
| F2 | 建议修 | **bash 3.2(本机唯一 bash)下「lib 缺失降级桩」失效且静默**:set -e + if 条件里 source 失败 → 整个 main-merge.sh 在第 48 行静默退出(2>/dev/null 连 bash 报错都吞),桩与提示永不执行——与代码自述契约「lib 缺失不阻断 merge + 不静默」三句全反;给 main-merge 全流程新增一个静默失败向量(§15/§23.11) | 否。触发前提=lib 缺失或语法坏(**当前仓库态不存在**,已验 lib 在位+bash -n OK+harness 全绿);建议合前修,修法已实测(§F2) |

低分项(<80)共 6 条已滤,列于 §4(防黑箱)。处置建议 3 条见 §7。

## 二、逐问回答(全部独立复算)

### 1. 匹配逻辑正确性(head_sha + workflow 名)——成立,且有实测误报方向证据
- **workflow 名/路径实测**(仓内 3 个 workflow):`ci.yml` → name=**CI Quality Gate** / `deploy-pages.yml` → Deploy to GitHub Pages / `deploy-cf.yml` → Deploy to Cloudflare Workers。脚本默认 `CI_WORKFLOW_NAME="CI Quality Gate"`、`CI_WORKFLOW_PATH=".github/workflows/ci.yml"` 与真实 run 的 `name`/`path` 字段全等命中;`pth.endswith("/ci.yml")` 兜底无其它 workflow 撞尾。
- **「同一 push 并发触发 CI/Pages/CF 三 workflow 共享 head_sha」= 属实(实测)**:
  - `head_sha=1501d6aa…`(10-04 bump commit,main)→ **3 个 run 同 sha 同秒**(Pages + Cloudflare Workers + CI,created_at 均为 2026-10-04T13:24:11Z)。
  - `659900705` → 2 run(deploy-cf 因 path filter 未触发):Pages(success)+ CI(**failure**,run id 37497679707/run#659)。
  - `f4a406a63`(当前 main tip)→ 2 run:Pages success + CI **failure**(run#660)。
- **「漏 workflow 过滤会误取 deploy run」判据成立,且实测误报方向=漏报 FAIL(更危险方向)**:
  - runs 列表默认序中,`659900705` 与 `f4a406a63` 的 deploy-pages run **都排在 CI run 之前**;对该 sha 取"第一个 sha 命中"= `Deploy to GitHub Pages | success`,而真 CI = `failure` ⇒ 只按 head_sha 匹配会把 CI FAIL 报成 success。
  - 脚本自身逻辑复算(把真实 42KB API 样本喂进 `_ci_pick_run`):按 CI 名过滤 → `37497679707  completed  failure  659  <html_url>`;按 Deploy 名过滤(env 覆盖重跑)→ deploy run。⇒ workflow 过滤必要且有效。
- sha 兜底(全等/前 8 位)在真实数据下全部为全等命中,无副作用。

### 2. 三路语义(rc 0/1/2 + exit 9 门槛)——全测通过
stub 复算(`CI_CURL_BIN` 注入,运行日志为证;六例结果与实施 harness 复跑一致):

| 场景 | 实测输出要点 | rc |
|---|---|---|
| completed success | `✓ CI 结论 success(run #660)` | 0 |
| completed failure | 醒目横幅 + `run #660 结论=failure` + `失败 job: quality-gate-static(failure)` + run URL | 1 |
| in_progress→completed(轮询) | 先 `未完成` 等一轮,后 `success` | 0 |
| 无匹配(NORUN)超时 | `未匹配到目标 commit … 的 'CI Quality Gate' run`→超时后 `⚠️ 未取得结论…本次 push main 已成功…请务必手动复核` | 2 |
| 网络失败(stub exit 7) | 同上 warn | 2 |
| `CI_SELFCHECK_SKIP=1` | `⏭ 已跳过(逃生门)` + 手动核对指引;**stub 零调用** | 2 |

- **exit 9 只在 rc1(真非 success 结论;含 cancelled/timed_out,属 lib 契约内)触发**;dry-run 在第 9 步 `exit 0`(line 479)永不到第 11 步;rc2 四类(超时/网络/无匹配/逃生门)走「完成(⚠️ 未取得结论)」分支不 exit 9。rc∉{0,1,2} 的 else 兜底会误标 success——实际不可达(lib 全部路径显式 return 0/1/2),列入低分项。
- 「拿不到结论既不静默也不把 push 说成失败」✓:输出原文=「本次 push main 已成功, 但 CI 结论未验证(不判 push 失败, 但请务必手动复核)」。
- FAIL 的 jobs 明细断言输入=照抄真实 API 结构(`jobs[].name/conclusion`);用**真实 jobs JSON**(run 37497679707)复算输出 `quality-gate-static(failure)`,与真实响应(static job failure 于第 ⑧ 步 pytest、data job success)吻合。

### 3. 不阻塞风险——无,但留 1 条主控实操注意
- **§14 安全窗口**: 检查在第 2 步(push 前);第 11 步在 **push+云上 pull 之后**(step10 `sync_cloud_pull || exit 6` 在 568 行,step11 在 570 行起)⇒ ①最坏等待 ≈8~9min(480s 上限+单次 fetch≤20s+末次 sleep≤15s 的过冲)不影响任何 push 时点决策 ②云上 pull 不被等待拖延(「§14 生产同步优先」的顺序设计正确)。
- main-merge.sh **无任何定时/自动化调用方**: 仓内 grep 仅文档引用;云上 `systemctl list-timers`(只读实测)无 main-merge 单元(`trade-update-all.timer`=17:50,与 deploy 时段前提吻合)⇒ exit 9 只回到交互主控,无自动化重试/告警环。
- **逃生口真有效** ✓(T5 实测;用法=调用时带 env,lib 在 source 时读入)。
- ⚠️ **主控实操注意(非缺陷)**: 本工具在 Bash 工具里跑时默认 timeout=120s,而 CI 轮询最长 ~9min ⇒ **调用须显式 timeout≥600000ms**,否则命令被 harness 杀掉、exit 9/结论拿不到。建议补进用法注释/派单口径。

### 4. 现有步骤零改动——append-only 实证
- `git diff --numstat`: main-merge.sh **+32/-1**;共 3 个 hunk;**唯一删除行=原末尾完成 echo**(被新三态 if/else echo 替换);其余两 hunk=头注释新增+顶部 source 块新增。
- §14 检查(154)/merge(205)/build_min+bump(221+)/§24⑤(323)/7.5-7.8 机检(336-433)/8.5 销账(440)/push(475-524)/云上 pull(526-568)**逐段对照零改动**。
- source 块插在 `PY="python3"` 后、DRY_RUN 解析前:lib 顶层仅变量默认值+函数定义,source 无副作用;lib 不依赖 BASH_SOURCE;`set -euo pipefail` 在其前已生效。
- `bash -n` 两文件 OK(本机 bash 3.2.57);feat 树 `lint_scripts.sh` 全通过;feat 树 `check_doc_staleness.py` **PASS**(232 文件 rc0,diff 无 launchd/15:33 等 stale 模式)⇒ merge 第 7.6 步不会被本改动拦下。

### 5. §18 L48/L49/L50——合规(含 1 条边界说明)
- **L48 零真实外发** ✓: 机制无任何通知/写外通道,唯一 HTTP=只读 GET(唯一调用点 `"$CI_CURL_BIN" -s --max-time …`);实施自测(`/private/tmp/ci_test/stub_curl.sh`+6 fixture)全回放、stub 只 cat 本地文件/exit7——我**复跑 harness 六例全 PASS(8.6s)**,自测期零真实出网;唯一真实调用 `live.sh`=只读 GET 真实 main commit(74d3e56e),不改任何状态。
- **L50 static-only** ✓: harness 只 source lib(注释明确「不 source/exec main-merge.sh 业务主体」),门控=正面白名单(CI_CURL_BIN 指向声明文件);我本次审同样未执行任何业务脚本。
- **L49 输入真实性** ✓-边界: fixture = **真实 API 捕获**(与我的独立捕获逐条全等:74d3e56e CI=id 37496745085/run#657/failure;6fe16ad8 CI=id 37497132698/run#658;6fe16ad8 Pages=id 37497132654/run#3997)+ 顶部插入 1 条合成目标 run(sha=deadbeefcafe…,id=11111111111;字段为真实邻近条目的 schema 拷贝)。关键字段存在性我用 **100% 真实样本**复核(head_sha/name/path/status/conclusion/id/run_number/html_url/jobs[].name/conclusion 在真实对象上均存在且复算一致)⇒ 不构成 L49 病灶;边界=合成目标 run 非真实捕获,建议后续终检保留真实 sha 样本(live.sh 模式)。
- 自测覆盖缺口: harness 六例未覆盖 in_progress 等待行(故 F1 未被发现),建议补 1 例。
- 附披露: 本次审查自身真实外发=GitHub API 只读 GET ~13 次(含 rate_limit 查询)+线上 3 次 curl(overview.json/app.min.js/index.html);无任何写操作。

### 6. §23.8 同步完整性——三处全补、口径一致
- role-implementer SKILL §3(新增条目)/ main-governance §15 区(步骤链补「云上 pull → push 后自动自查 CI 结论(FAIL 醒目告警+exit 9)」)/ 根 CLAUDE.md §8(统一入口条目补「push 后自动自查 CI 结论」)三处齐;与 §8 既有条目(6fe16ad83 已入 main 的「push main 后必自查 CI」,含「机制已内建…细节见 implementer skill §3」)并存无冲突——本 feat 正兑现该句。三处对机制描述(FAIL 告警内容/exit 9/未取得结论 warn/逃生门)与实现逐项一致。
- 小口径差(低分项): CLAUDE.md 手动复核 hint 用 `per_page=3`,lib 提示文本用 `per_page=5`(均为示意值,不影响结论)。

### 7. 两点上报的处置建议(主控拍板)
**① deploy.sh 不建议挂阻塞式轮询**:
- 事实(代码+云上只读): deploy.sh git 写段(段2)持 `/tmp/trade_deploy.lock`,该锁「串行全部 git 写」(staticdata sync/async 同锁,L51-53/653);历史上有「git-upload-pack 卡 51min 死拽 deploy.lock 连锁卡 staticdata_sync」(L70)⇒ 锁内加最长 ~9min 轮询=已知事故类的同类风险。
- deploy 的 push(`git push origin main:main`,L121,带超时保护)仍触发 CI,存在同类漏报面;若需覆盖,两个低风险选项: (a) **独立 CI watchdog**(云上 systemd timer,如 17:55 后拉 main 最新 run 结论,FAIL 告警)——与 deploy 锁解耦,**推荐**; (b) deploy.sh 锁释放后再做非阻塞检查。二者均属新改动(动生产关键脚本,L121 时点 17:50=`trade-update-all.timer` 实测在档),建议按 §23.7 + 用户拍板另行派单。
**② 新 lib 未被 pre-commit lint 覆盖——建议扩 glob(低风险)**:
- 现状(实证): `lint_scripts.sh` 三项(bash -n / `$VAR`+非ASCII 扫描 / py_compile)全用 `scripts/*.sh`、`scripts/*.py` 非递归 glob ⇒ `scripts/lib/ci_selfcheck.sh` 与既有 `scripts/lib/repo_paths.sh` 均不被覆盖;CI(ci.yml)也不 lint shell ⇒ lib 语法无任何机检。
- 与 F2 联动: lib 若被改出语法错,lint 拦不住 → bash 3.2 下 main-merge 静默死。建议 glob 扩为含 `scripts/lib/*.sh`(等);**已实测两文件在扩展后可通过**(`bash -n` OK + 逐字复用 lint 自带扫描器 = 0 命中)。
- 改 lint_scripts.sh 会动到既有工具,建议独立小改动或随 F1/F2 小修一并(主控定)。
**③(附)API 配额提醒(非阻断)**: 未鉴权 60 次/小时/IP(实测余量 47/60,已含本次消耗);最坏一次轮询(480s/15s)≈33 次 runs + ≤1 次 jobs ⇒ CI 慢时连续多次 main-merge 可能触 403,届时 rc2 优雅降级为「请手动复核」(但同时手动复核也可能 403 到配额重置)。建议: 间隔放宽至 30s、或失败后自适应加倍、或加 ETag 条件请求(304 不计配额)。

## 三、Findings(trace/verifier,§10.5)

**F1 轮询等待行字段错位(run 编号位置打印 html_url)**
- trace: `scripts/lib/ci_selfcheck.sh:135`(`IFS=$'\t' read -r run_id status conclusion run_number run_html <<< "$pick"`)+ `:140`(echo `$run_number`);未完成 run 的 `conclusion` 为 null→空字段,TAB 属 IFS 空白,`read` 折叠连续分隔符 ⇒ 字段左移一格,`run_number` 拿到 html_url。linkage=满足(user_request=N/A,"origin":"reviewer_own",本次新增代码内的缺陷)。
- verifier: command=`env CI_CURL_BIN=/tmp/ci_stub_curl2.sh CI_POLL_INTERVAL=0 CI_POLL_MAX_WAIT=10 bash -c 'source scripts/lib/ci_selfcheck.sh; ci_selfcheck deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'`(stub 首轮 in_progress)→ expected=`· CI run #661(status=in_progress, 未完成)`;observed=`· CI run #https://github.com/xp13465/trade-data-signal/actions/runs/444(status=in_progress, 未完成)`。最终结论行不受影响(实测 success/failure 输出正确)。
- over_engineering: action=simplify;saves_lines=0;rationale=不用 IFS 折叠的 `read`:换 `cut -fN`(保留空字段)或让 python 对空值输出 `-` 占位;1-3 行。
- 附带理由: completed 且 conclusion 为空的 run(理论上不存在)会因同一错位被误判 FAIL——修掉消除潜类。

**F2 bash 3.2 下 lib 缺失/损坏时降级桩失效 + 静默退出**
- trace: `scripts/main-merge.sh:48-50`(`if ! source "$REPO/scripts/lib/ci_selfcheck.sh" 2>/dev/null; then ci_selfcheck(){…return 2;}; fi`);bash 3.2.57 已知行为: set -e 下 source 打不开/解析失败会在条件上下文里直接退出(`!`/`||` 均不抑制)。linkage=满足(user_request=N/A,"origin":"reviewer_own",本次新增代码);§15=main-merge 全流程新增启动期依赖(旧功能新失败向量)+§23.11。
- verifier: command=`/bin/bash -c 'set -e; if ! source /nonexistent/x 2>/dev/null; then echo STUB; fi; echo AFTER'`;expected(bash≥4 设计意图)=`STUB`+`AFTER`;observed=**(无任何输出) rc=1**——桩/提示/AFTER 全不执行;语法坏文件同(rc=2 无输出);`source x || stub` 形式同样死(已排查)。对照: 普通命令/函数失败在条件上下文正常(V3 实测)。正常路径(lib 在位)三变体实测正常(V4)。
- 影响面: 仅当 lib 缺失或语法坏时触发(当前不存在);一旦触发=main-merge **在任何步骤前静默中止**(2>/dev/null 吞掉 bash 报错),与自述契约全反;与 §7② lint 缺口叠加可致「语法错过关入库 → 下次 main-merge 静默死」。
- over_engineering: action=simplify;saves_lines=0;rationale=改 1 行即消灭:`eval ". \"$REPO/scripts/lib/ci_selfcheck.sh\"" 2>/dev/null || ci_selfcheck(){…;}`——bash 3.2.57 实测三态全通: ①文件缺失→桩生效+继续 ②文件存在正常→函数在父 shell 定义 ③语法坏→桩生效+继续。**勿用 `(source …)` 子壳形式**(成功路径函数会留在子壳,父 shell 无定义→rc=127 会被 else 误标 success)。替代: 显式 `set +e; source …; rc=$?; set -e` 两行式(亦实测通过)。

## 四、低分项(<80,已滤,防黑箱)

1. (50) lib 末尾无换行(`tail -c2`=`\n}`,每行数 185/186 的差异即此)
2. (35) 第 11 步 `else` 把 rc∉{1,2} 当 success 打印——当前不可达;建议顺手改 `elif [[ "$CI_RC" -eq 0 ]]`+else 走 warn
3. (30) `_ci_pick_run` 形参 `$2/$3` 未用(实际读全局 CI_WORKFLOW_NAME/PATH);签名与文档不符,不影响行为(我复算时踩到,故列出)
4. (25) CLAUDE.md 手动复核 hint `per_page=3` vs lib hint `per_page=5`(示意值)
5. (25) harness 未覆盖 in_progress 等待行用例(与 F1 相关,补例即可)
6. (20) 头注释「不被最长 8 分钟的 CI 轮询阻塞」的"8 分钟"为标称值(实际含过冲 ≈9min),措辞级

## 五、影响面清单(grep/实测实证)

- 新 lib **唯一引用方 = `scripts/main-merge.sh`**(7 处,含注释;唯一函数调用点 578 行);无其它 sh/py/yml/js 引用。
- §15 老功能面: main-merge 既有 10 步零改动(§4);无自动化调用方(仓内 grep+云上 timer 清单双证)⇒ 无定时/连锁影响;不改任何数据产物/生成脚本/前端/静态站点文件 ⇒ 站点 P0 smoke 按影响面**不适用**(§9 圈定原则);兜底实测(证明线上正常,与改动无关): `ss.fx8.store/data/overview.json` date=20261006(10-07 凌晨,最近交易日=正确)+scores 11 key;`ss.fx8.store/app.min.js` HTTP 200 1.04MB(memory min-verify-root-path,根路径)。
- 文档口径机检: feat 树 `check_doc_staleness.py` PASS(见 §4)。
- §22 数据一致性: 无数据产物改动,不适用。

## 六、复现命令(独立可重跑)

```
R1 匹配逻辑(全真实样本):
  curl -s --max-time 20 "https://api.github.com/repos/xp13465/trade-data-signal/actions/runs?per_page=12" > /tmp/ci_runs_sample.json
  bash -c 'source /tmp/ci_selfcheck_reviewed.sh; _ci_pick_run 659900705519ec65cba8b12685ad83f5b6a0d41e' < /tmp/ci_runs_sample.json
  期望: 37497679707	completed	failure	659	https://github.com/xp13465/trade-data-signal/actions/runs/37497679707
R2 同 sha 三 workflow 实证: curl -s ".../actions/runs?head_sha=1501d6aa07f9443477dc4cd39610150270cc1f1f&per_page=10"  → 期望 3 run(Pages/CF/CI)
R3 F1: 见 Findings F1 verifier(stub 见 /private/tmp/ci_test/ 或本次审查临时文件)
R4 F2: 见 Findings F2 verifier
R5 实施 harness 原样复跑: bash /private/tmp/ci_test/harness.sh → 期望六例 [[VERDICT]] PASS(0/1/2/2/2/2)
R6 文档机检: python3 scripts/check_doc_staleness.py --root <feat worktree> → 期望 rc=0
```

## 七、附: 当前 main CI 状态(主控须知)

- 最新 main(`f4a406a63`)CI run#660 = **failure**(job `quality-gate-static` 第 ⑧ 步 pytest;`quality-gate-data` success)⇒ #223④ 的 CI 修复尚未使 main 转绿。
- ⇒ 本 feat 合并后第 11 步会**正确地** exit 9(并打印 run 链接/job 名)。**该结果=机制工作正常,不是 merge 失败**(main 已 push+云上已同步);同时按 §8「FAIL ⇒ 立即派修」推动 #223④ 收尾。若 #223④ 修复先合 main,则本 feat 合并时 CI 可能已绿(exit 0)。

---
(reviewer agent 只读审查,未改动任何代码;本报告 untracked,交主控 commit)

## 八、F1/F2 复核(2026-10-07,新 tip `b110f17ee`,就地复核不作废前文)

主控报 F1/F2 已修,就地只读复核(未重头再审)。**复核结论:PASS(6/6 全过);新 tip 仍满足 merge 资格(可 merge)。**

- **范围/零夹带** ✓:新 tip 父=`0fe60d2aa`(纯追加 ff,非 force,已验);`git diff --numstat 0fe60d2aa b110f17ee` = **2 文件 +10/−5**(lib +5/−2、main-merge +5/−3);`rev-list --count` = 1 commit。远端 `origin/feat/ci-selfcheck-20261007` = `b110f17ee`(已 push)。
- **F1 修对** ✓(纯显示、判定零改动,双向实证):
  - v1→v2 lib 全文 diff = 仅 F1 区域(1 行 `read` → 4 行 `cut -f1..5` 赋值 + 2 行注释)+ 末行换行补齐,零其它改动;
  - in_progress 复算:等待行从 `CI run #https://...`(v1 错位)→ **`CI run #661(status=in_progress, 未完成)`**(v2 正确),随后 `✓ CI 结论 success(run #661)` rc=0;
  - **判定不变机检**:同一真实样本 rc=1(`runs_fail.json`,输出含 run#999/URL/失败 job)与 rc=0(`runs_pass.json`)的输出,**v1==v2 逐字一致**(`diff` 空);`cut` 保留空字段,completed 路径(conclusion 非空)切分与 `read` 同结果。
- **F2 修对** ✓(bash 3.2.57 三态独立复算,sed 逐字复刻 main-merge_v2.sh L51-52,set -euo pipefail 上下文,**只跑 source 块不跑主体**):
  - 在位 → 函数定义于**父 shell**(declare -f 匹配 lib 体,非子壳陷阱)且脚本继续,exit=0;
  - 语法坏(`if true; then\n(echo unbalanced`)→ 桩生效 + stderr 文案 `⚠️ 缺 scripts/lib/ci_selfcheck.sh…` 可见 + 调用 rc=2 + 脚本继续,**不静默退出**;
  - 缺失 → 同语法坏态;
  - **对照(证明修复对象真实)**:旧形式 `if ! source …; then …; fi` 在语法坏/缺失两态仍静默死(零输出,exit=2/1)。
- **harness 六例复跑** ✓:指向 v2 lib 复跑 PASS/FAIL/NORUN/WRONG_WF/NET_FAIL/SKIP 六例 → rc 0/1/2/2/2/2 全 PASS(与 v1 轮一致)。
- **零真实外发(§18 L48/L50)** ✓:复算全程 `CI_CURL_BIN` 走 stub(调用日志为证,零网络);v2 lib 唯一 HTTP 调用点=L45 `"$CI_CURL_BIN" -s --max-time`(其余 curl/URL 命中均为提示文案/URL 构造);main-merge_v2 无任何 curl 调用。
- **lint/语法** ✓:两文件 `bash -n` OK;**lint_scripts.sh 同款扫描器**(逐字复用其 python 正则+纯注释行 skip)对两文件复扫 0 命中(L534 `$CLOUD_GIT_REPO。` 为纯注释行且 pre-existing,非本次改动,lint 规则本就 skip 注释行)。
- **merge 场景更新**:
  - origin/main 已前进到 `39ca8b96a`(feat base 落后 3 commit:659900705→e6dcea3ac→39ca8b96a);**交集核查空**——origin/main 侧 659900705..39ca8b96a 共 11 文件(4 docs/ops 报告+TASKS+pending-index+nextday_plan_generator.py/overfit_monitor.py+3 tests),**零碰 `scripts/main-merge.sh` 与 `scripts/lib/`** ⇒ 合并零冲突风险;
  - origin/main CI 已绿(独立 API 实测:`39ca8b96` success run#664、`e6dcea3a` success #663、`cf85add0` success #662;`ec3ea11c` failure #661 为修前)⇒ **§7「主控须知」更新:合并本 feat 后首跑 main-merge 第 11 步预期 `CI success(exit 0)`**(不再预期 exit 9);若仍 exit 9 则按横幅告警核对应 run 结论再派修。
- 复现命令:见 §6 R1-R6 之外追加:
```
R7 F1(v2 复算): 重建 in_progress/完成两轮 payload(真实 API 字段结构),stub 计数器注入:
   env CI_CURL_BIN=<计数器 stub> CI_POLL_INTERVAL=0 CI_POLL_MAX_WAIT=10 bash -c 'source <v2 lib>; ci_selfcheck deadbeefcafe1234567890abcdef0123456789a'
   期望: 等待行 "CI run #661(status=in_progress, 未完成)" + "✓ CI 结论 success(run #661)" rc=0
R8 F2 三态: /bin/bash /tmp/f2_three_state_v2.sh /tmp/f2_review/{ok,bad,missing}
   期望三态均输出 AFTER-CONTINUED;ok=FUNC=real;bad/missing=FUNC=stub+rc=2
   对照(旧形式必死): /bin/bash -c "set -euo pipefail; if ! source /tmp/f2_review/bad/scripts/lib/ci_selfcheck.sh 2>/dev/null; then echo STUB; fi; echo AFTER" → 期望无输出(静默死)
```
