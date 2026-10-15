# main-merge.sh「发版本时同步通用包」软提醒 — 独立审查报告(2026-10-15)

- 审查对象:`feat/main-merge-sync-hint` @ `83728f23d`(base = `origin/main` @ `632b157f9`)
- 改动:`scripts/main-merge.sh`(+12 −1,其中 −1 为表头注释行改写)+ 新增 `docs/ops/main-merge-sync-hint-impl-20261015.md`
- 审查角色:reviewer(独立 fresh context);本单 = ④审查关 与 ⑤测试关 合并执行(单脚本纯输出改动)
- **结论:PASS(阻断项 0 / 必修 0)**;§10.8 差集 2 条已逐条处置(均为低危,建议不阻断合并);观察项 1 条
- 纪律声明:**残留后台任务:无**(全程未出现 `moved to the background`);未在真仓做任何 checkout/switch/add/commit/push;未写任何 `.claude/` 路径

---

## 0. 取证环境与安全(红线遵守)

- reviewer **自建独立沙箱**(不复用实施方 `/tmp/mhint-sandbox`):`/tmp/mhint-sbr/`,内含 3 个独立 repo(old / new / mut)+ 3 个**本地 bare origin**,`origin` 指向 `/tmp` 内路径 ⇒ 脚本内 `git fetch origin` 只走本地,零真实网络。
- **网络命令正面白名单守卫**:`ssh/curl/wget/rclone/node/scp/rsync/nc/telnet` 全部 shim 成「记日志 + exit 127」并置于 PATH 最前;跑完 `guard.log` = **0 行**(= 全程零外部动作**尝试**)。另设 `http(s)_proxy=127.0.0.1:1`(死端口)兜底、`GIT_CONFIG_GLOBAL=/dev/null` 屏蔽全局 config/hooks。
- **先读短路口再跑**(§18 L50 例外条件):`scripts/main-merge.sh` L489-492 `if DRY_RUN==1 → exit 0`,其后的 commit(L496+)/ push(L531)/ ssh 云上(L581)/ CI 自查(L591)全部不可达 ⇒ 仅以 `--dry-run` 取证。实测确认:5 用例输出末行均为 `=== dry-run 演练完成(未实际 merge/push) ===`。
- 沙箱适配(与验证目标正交,old/new 两版**同等**改造):`app/calendar.py` 桩为「非交易日」以跳过 §14 盘后时点闸(避免依赖运行时刻,且避免真实 calendar 拉 akshare 网络);另拷入 `scripts/lib/ci_selfcheck.sh`(顶层仅变量赋值,无副作用)。

---

## 1. 必查 1 — diff 逐行核

`git show 83728f23d -- scripts/main-merge.sh` 逐行读毕,变更 = ①表头第 6 步文档注释 +1 行;②挂点处注释 5 行 + `echo "" / echo "⚠ 本次发版…" / echo ""` 3 行。

判定:**无 if/for/case、无变量赋值、无 exit、无重定向、无 `||`/`&&` 新增**;新增字符串内无 `$`、无反引号(无命令替换/变量展开面);`bash -n` 新旧两版均 SYNTAX-OK。**纯输出改动结论成立。**

## 2. 必查 2 — 挂点正确性

- 判定点 `CHANGED_SRC` 非空 = L244 `if [[ -n "$CHANGED_SRC" ]]`;内层 `DRY_RUN` 分叉 L246-253;提醒 L262-264 位于**内层 `fi` 之后、外层 `else` 之前** ⇒ 真实模式(bump 成功后)与 dry-run 均打印,未触碰前端源时不打印。
- **唯一运行时 bump 入口复核**(独立 grep,全仓):真正 `"$PY" scripts/bump_asset_version.py` 调用**只有 `scripts/main-merge.sh:250` 一处**;`scripts/deploy.sh` 仅调 `build_min.py`(安全网,**无** bump 调用);其余命中(`build_min.py:238` / `kelly_reports_html.py:88` / `md_to_html.py:73` / `build_echarts.sh:54`)全是**打印给使用者看的提示文案**,非运行入口。**实施方「全仓唯一运行时 bump 点」自报成立。**
- 静态补证:e 提醒位于 bump 子shell(L249-250)**之后**,`set -euo pipefail`(L40)下 bump 失败即中止 ⇒ 提醒不会在 bump 失败时打出。纯 bash 语义探针:`bash -c 'set -euo pipefail; if true; then echo A; ( exit 1 ); echo B_unreachable; else echo C; fi; echo D_after'` ⇒ 输出仅 `A`,rc=1(B/D 均不可达)。

## 3. 必查 3 — 独立复现证据用例(不采信自述)

| 用例 | 脚本版本 | 场景 | exit | reminder_lines |
|---|---|---|---|---|
| new-bump | 改动版 `83728f23d` | `feat-bump`(改 `static-site/app.js`) | **0** | **1** |
| new-nosrc | 改动版 | `feat-nosrc`(只改 `docs/readme.md`) | **0** | **0** |
| old-bump | 改前版 `632b157f9`(同一沙箱构造) | `feat-bump` | **0** | 0 |
| old-nosrc | 改前版 | `feat-nosrc` | **0** | 0 |
| mut-bump | 变异版(删掉提醒 echo 行) | `feat-bump` | **0** | 0 |

**归一化 stdout diff**(剔除沙箱路径/短 hash 噪声后逐行比):
- 有 bump:`old vs new` ⇒ 唯一差异 = **新增 3 行**(空行 + 提醒行 + 空行),`17a18,20`,无其它任何行差异;
- 无 bump:`old vs new` ⇒ **diff 完全为空(diff_rc=0,逐字节相同)**;
- 判别力:`new-bump vs mut-bump` ⇒ 差异恰为提醒行缺失(`19d18`),证明「数提醒行」这一断言非假绿;
- **exit 码:old 与 new 在两种场景下全为 0(一致)**。

⇒ 与实施方 §5 的四条自报**逐条独立复现成功**(有 bump 有提醒 / 无 bump 无提醒 / 退出码与改前一致 / 删行有判别力),且我额外给出「无 bump 场景逐字节相同」这一更强证据。

## 4. 必查 4 — §10.8 边界完整性独立复核

先自推(不看实施方清单),再对账:

| # | 我自推的边界维度 | 判定/证据 | 实施方是否覆盖 |
|---|---|---|---|
| a | dry-run × 有/无 bump、真实 × 有/无 bump 四象限 | 沙箱实测前两象限(a 见 §3);真实两象限受红线限制不可跑 ⇒ 静态论证(§2) | 覆盖(dry-run 也打=其 §6 显式声明) |
| b | exit 码不变 | 实测 old/new 全 0 | 覆盖 |
| c | stdout 被管道/重定向消费是否干扰解析 | 全仓 grep `main-merge` 可执行调用点:除自身外**零调用方**,无脚本抓取其 stdout ⇒ 无解析面 | 未提(实测已排除) |
| d | 重复运行 / 幂等 / 重入 | 纯 echo,无状态无文件写入;同一 repo 连跑 new-bump→new-nosrc 互不影响(均 exit 0) | 未提(已排除) |
| e | 中文/符号编码 | 提醒行 `⚠` 与脚本既有 `✓/✗/⚠️` 同族,写 stdout 无编码面 | 未提(已排除) |
| f | 是否覆盖所有 bump 触发来源 | bump 触发源=9 前端源(L232-234),提醒与其同条件 ⇒ 对齐 | 覆盖(其 §7) |
| g | **手动「打 tag」发版路径**(README §4 原文含「打 tag / 发版」) | 仓内无 tag 自动化(全仓 `git tag` 仅 1 处文档引用,`.github/workflows/` 无 tag 触发);main-merge.sh 不建 tag ⇒ 纯 tag 发版**不触发**提醒 | **未覆盖 = 差集 1** |
| h | 提醒 emit 时点 vs「发版成功」 | 提醒在 push(L531)/ssh(L581)/CI(L591)**之前** emit ⇒ 「看到提醒 ≠ 已 push 成功」;方向 = 过度提醒(fail-safe) | **未覆盖 = 差集 2** |
| i | 新增 docs 文件是否会触发既有 7.6 `check_doc_staleness` 闸门(该闸门曾自锁拦死 merge) | 副本树实测(216 文件=基线,加入新文档后**仍 216**,输出逐字节一致 rc=0)+ 源码核实 `DATE_SUFFIX_RE`(`check_doc_staleness.py:119`)对 `-20261015.md` **整文件路径豁免** ⇒ 零风险 | 未提(已排除) |
| j | 与 §14 时点闸门/其它闸门交互 | 新增行在 §14 闸门(L158)之后,无交互 | 未提(已排除) |
| k | SIGPIPE / `pipefail` 下被下游 `head` 截断 | 脚本首行起已有数十条 echo 同族,新增 1 条不改变该类风险(要出事会在更早 echo 先出) | 未提(已排除) |
| l | 多源 CHANGED_SRC(`app.js lab.js index.html`) | 新增 echo 不引用 `$CHANGED_SRC`,无 quoting/展开面 | 未提(已排除) |

**差集处置(2 条,均为低危「提醒覆盖度」而非功能缺陷):**
- **差集 1(手动打 tag 发版不提醒)**:处置 = **上报主控+显式声明不覆盖**,理由:①仓内无 tag 自动化入口(grep 实测),tag 由主控手动打;②本项目 tag 与版本串紧贴(v1.1.x),版本串 bump 时提醒已发出,时机基本等价。**建议(可选、非阻断)**:在未来「打 tag 流程」文档补一行人工提醒,或另立小任务。
- **差集 2(提醒早于 push/CI 成功)**:处置 = **上报主控作观察项**,理由:方向为 over-remind(fail-safe),不会漏同步;若日后要精化,可把提醒移到第 9 步 push 成功之后(代价:dry-run 将无法本地复现该分支)。**建议维持现状。**

## 5. 必查 5 — §23.3 举一反三 / 文案三源核对

- 我独立扫「其它发版入口」:除 `main-merge.sh` 外,`scripts/token_cache_stats.py` 有**绕开统一入口直推 main** 的特例(用户 2026-08-19 拍板,仅追加 `claude-work-mode/README.md` 文档块)——**非发版(无 bump)**,不在本约定触发面上;`git tag` 无自动化(见差集 1)。
- 文案三源核对:提醒文案「README §4 维护约定:发版本时同步」↔ `work-mode-standard/README.md` §4 标题(实测 = 「## 4. 维护约定(写死,防"镜像又没同步")」,正文 = 「来源项目每次发版本(打 tag / 发版)时,把「同步通用包」当作发版清单里的一项执行」)↔ 拍板记录(`docs/pending-features-index.md` #263 条目「同步触发点改为『发版本时同步』」+ `docs/ops/workmode-distill-plan-20261014.md` 拍板行)。**三源一致,指向的 §4 节号与标题均正确,无过时/误导文案。**

## 6. 必查 6 — §14 核验(origin/main 未被推进)

`git rev-parse origin/main main` ⇒ 两者均 `632b157f9e8529e9018a49ae9bbf5eaba5406786`;`git ls-remote origin` ⇒ `refs/heads/main=632b157f9…`、`refs/heads/feat/main-merge-sync-hint=83728f23d…`。**实施方未碰 main,只推 feat 分支,符合机制 D。**

## 7. 其它规范条款逐条核查

| 条款 | 判定 | 依据 |
|---|---|---|
| §21 算法公示同步 | **N/A** | 不改算法/评分/权重/匹配规则;仅脚本输出 |
| §22 数据一致性 | **N/A** | 不产数据产物,不涉 static-site/R2/CF 三处同值 |
| §24 前端部署防撕裂四查 | **N/A** | 不改 `app.js/lab.js/common.js/style.css/index.html/sw.js`,不 bump 版本串,不重建 min |
| §10.4 静默失败专查 | **通过** | diff 无 `except/catch/fallback/`\|\|` 兜底;新增行不可能静默失败(纯 stdout) |
| §9.6 上线残缺项 | **N/A** | 非数据/算法驱动功能上线 |
| §9.5 数据供给闭环 | **N/A** | 非动态/定时数据产物功能;本机制不依赖任何定时更新 |
| §23.11 冲突绝不静默 | **通过** | 本次审查未发现版本倒退/覆盖;feat 分支 base 新鲜(沙箱实测「落后 0 commit」) |
| §23.7 冻结契约 | **通过** | 只新增输出,未改既有行为/数字/交互;dry-run 打印已显式声明为设计取舍 |
| §5.7 方案可证伪性 | **通过** | 实施报告含①可指认依据(文件:行号)→②可观测预期(表:X→Y)→③证据用例(4 条),且我独立复现 4/4 达成(见 §3);用例是否「事先写定」无法核时序,但用例与预期表同构、独立复现一致 |
| 沙箱/取证纪律(§18 L50) | **通过** | 未 exec 生产脚本主体,唯一例外 = 已读短路口证实的 dry-run;探针 static-only 部分仅读文件 |

## 8. 低分项已滤(<80,共 2 条)

1. 提醒文案「记得同步 work-mode-standard/ 通用包」的**同步方向**字面略歧义(是把本仓状态写进包,还是从包取)——文案引用「README §4」可解歧,且 §4 原文写明方向。判 50 分(nitpick)已滤。
2. 提醒行 `⚠` 未带变体选择符(U+FE0F),脚本其余处多写 `⚠️` ——外观级,判 25 分已滤。

## 9. 复现命令(供审计反查)

```bash
bash /tmp/mhint-review-sb.sh            # 建 3 沙箱 + 跑 5 用例 + 归一化 diff + guard.log 检查
SB=/tmp/mhint-sbr; cat $SB/*.exit       # 退出码对照
python3 scripts/check_doc_staleness.py --root /tmp/mhint-gate   # 7.6 闸门副本模拟(含/不含新文档)
```

审查用关键命令(均带工具级 timeout,未在真仓做任何写操作):
`git show 83728f23d -- scripts/main-merge.sh` / `git show <ref>:scripts/main-merge.sh` / `git rev-parse origin/main main` / `git ls-remote origin` / `bash -n` / `grep -rn bump_asset_version`
