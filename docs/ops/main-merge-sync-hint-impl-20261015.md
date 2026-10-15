# main-merge.sh「发版本时同步通用包」软提醒 — 实施报告(2026-10-15)

- 等级:B 级(单脚本改动,纯新增输出,无控制流变更)
- 分支:`feat/main-merge-sync-hint`(base = `origin/main` @ `632b157f9`,base-fresh PASS)
- 改动文件:`scripts/main-merge.sh`(仅 1 文件,+12 −1,其中 −1 是表头注释行改写)
- 残留后台任务:**无**(本次全程未出现 `moved to the background`)

---

## 1. 任务与背景

把 `work-mode-standard/README.md` §4「维护约定」里的「**发版本时同步**」从「靠记性」变成「机器提醒」:
`scripts/main-merge.sh` 发布流程中,当本次 merge **确实发生版本 bump(发版)**时,输出一行中文提醒。

- 约定原文(`work-mode-standard/README.md:75`,2026-10-15 用户拍板):「发版本时同步:来源项目**每次发版本(打 tag / 发版)时**,把「同步通用包」当作发版清单里的一项执行」。

## 2. 依据(可指认、可复核)

- **唯一运行时 bump 点** = `scripts/main-merge.sh:250`(`"$PY" scripts/bump_asset_version.py`)。全仓 grep 确认:
  - `scripts/deploy.sh` **无** `bump_asset_version` 调用(grep 0 命中);
  - 其余命中(`build_min.py` / `kelly_reports_html.py` / `md_to_html.py` / `build_echarts.sh`)全是**打印提示文案**(告诉使用者手动跑),不是发版入口;
  - 结论:main-merge.sh 是版本串 bump 的**唯一权威入口**(与 §24② / skill §3 机制 C 口径一致)。
- **「本次是否 bump」判定点** = `CHANGED_SRC` 非空(`scripts/main-merge.sh:244` 的 `if [[ -n "$CHANGED_SRC" ]]`):feat 触碰 9 个前端源任一 ⇒ 走统一 build_min + bump。源码内已有注释确认「index.html 改动触发统一 bump」「build_min 无源变更自然产出不变,只跑 bump_asset_version.py」,故 `CHANGED_SRC` 非空是「本次确实 bump」的可靠判定。

## 3. 实现(改了什么)

在 `CHANGED_SRC` 非空的 bump 分支内(第 6 步 `if` 块尾部、`else`(未触碰前端源码)之前)新增 3 行纯输出:

```bash
  echo ""
  echo "⚠ 本次发版(触发版本 bump):记得同步 work-mode-standard/ 通用包(README §4 维护约定:发版本时同步)"
  echo ""
```

并在表头第 6 步文档行追加一句说明(便于后续查脚本的人知道此处有提醒)。附 4 行内联注释说明触发点与设计取舍。

**触发条件 = `CHANGED_SRC` 非空**(与第 6 步 bump 判定同一条件)——即「本次 merge 触发版本 bump」时才打出该行。

## 4. 实现预期(可观测 X→Y)

| 场景 | 期望 stdout | 期望退出码 |
|---|---|---|
| 本次 merge 触发 bump(feat 改前端源) | **多一行** `⚠ 本次发版(触发版本 bump):记得同步 work-mode-standard/ 通用包(...)` | 与改前一致(0) |
| 本次 merge 未触发 bump(feat 未改前端源) | **无该行** | 与改前一致(0) |

对控制流零影响:纯 `echo`,不改退出码、不阻断、不加失败路径。

## 5. 证据用例与结果(自测逐条跑)

沙箱隔离取证,**未真推 main、未推任何远端到真实仓库**(红线遵守):
- 沙箱 = `/tmp/mhint-sandbox`(独立 `git init` 仓库 + 本地 bare remote `/tmp/mhint-sandbox-origin.git`),拷入改动版 `main-merge.sh` 后以 `--dry-run` 跑。
- 为什么用 dry-run:sandbox 的**真实**(非 dry-run)路径会走到第 10 步 `ssh 云上 git pull`(硬编码真实云主机 `122.51.111.173`)与第 11 步 CI 自查,会触及生产/真实系统——故取证限定 dry-run。dry-run 完整跑过第 6 步 bump 判定分支(仅跳过实际执行),足以证明提醒分支可达且条件判定真实生效。

| # | 用例 | 命令 | 观察 | 结果 |
|---|---|---|---|---|
| 1 | 有 bump 场景 | `bash scripts/main-merge.sh feat-bump --dry-run`(feat-bump 改 `static-site/app.js`) | 输出第 19 行含提醒行;`CASE1_EXIT=0` | **PASS** |
| 2 | 无 bump 场景 | `bash scripts/main-merge.sh feat-nosrc --dry-run`(feat-nosrc 只改 `docs/foo.md`) | 输出第 16 行为「未触碰前端源码…跳过统一 bump」,**无**提醒行;`CASE2_EXIT=0` | **PASS** |
| 3 | 退出码与改前一致 | 用**改前版本**(`git show HEAD:scripts/main-merge.sh`,即 origin/main 版)在同一沙箱跑同两用例 | `ORIG_C1_EXIT=0`、`ORIG_C2_EXIT=0`,与改动版一致;改前 case1 同样到达 bump 分支(输出「触碰前端源码: app.js」)但无提醒行 | **PASS**(apples-to-apples) |
| 4 | 判别力自证 | 把提醒行从改动版**故意删掉**生成 mutant,再跑 case1 | `MUT_C1_EXIT=0` 且 `reminder_lines=0` ⇒ 该断言能真正区分「有/无提醒行」,非假绿 | **PASS** |

提醒行计数汇总:

```
mhint-case1.out(改动版 / 有bump)  reminder_lines=1   exit 0
mhint-case2.out(改动版 / 无bump)  reminder_lines=0   exit 0
mhint-orig-c1.out(改前 / 有bump)  reminder_lines=0   exit 0
mhint-orig-c2.out(改前 / 无bump)  reminder_lines=0   exit 0
mhint-mut-c1.out (mutant/有bump)  reminder_lines=0   exit 0
```

### 5.1 原始输出摘录(case1,有 bump)

```
--- feat 触碰前端源码: app.js, 统一 build_min + bump(版本串唯一权威入口) ---
  [dry-run] 跳过 build_min/bump

⚠ 本次发版(触发版本 bump):记得同步 work-mode-standard/ 通用包(README §4 维护约定:发版本时同步)

  [dry-run] 跳过 changelog 补登
...
=== dry-run 演练完成(未实际 merge/push) ===
```

### 5.2 原始输出摘录(case2,无 bump —— 该处**无**提醒行)

```
--- merge feat-nosrc into main ---
  checkout main
  [dry-run] 跳过实际 merge
  feat 未触碰前端源码(9 源: app/lab/common/style/lab.css/purpose-notes/kelly-review-notes/kelly-reports-content/index.html), 跳过统一 bump
  [dry-run] 跳过 changelog 补登
```

## 6. 设计取舍(诚实标注)

- **dry-run 也打印提醒**:dry-run 是演练,「触发 bump」的判定(`CHANGED_SRC` 非空)与真实路径一致,故提醒同样出现(作为发版预览)。这样做的好处是**本地可确定复现本提醒分支**(不依赖触及云上/远端的真实 merge)。若希望真实发版才打,需把提醒移入非 dry-run 子分支,但那样只能靠触及真实链路的沙箱取证,风险更高——故保留当前设计,并在代码注释中写明。
- 提醒为**纯输出**,与脚本内既有的「pending-index 销账软提醒」同风格(只提醒不阻断不自动改)。

## 7. 举一反三 / 同类错误面(§23.2 §23.3)

- **同类 bump 消费点清单**:已全仓 grep `bump_asset_version` 调用点(deploy.sh / build_min.py / kelly_reports_html.py / md_to_html.py / build_echarts.sh)——确认**无第二个运行时发版入口**,提醒挂在唯一入口即全覆盖(不存在「另有发版点漏提醒」)。
- **同数据源/同组件**:`work-mode-standard/` 同步约定的触发点是「发版本」,而发版本只发生在 main-merge.sh,故单点即闭环。
- **pending-features-index 对账(§23.4)**:scan `docs/pending-features-index.md`,与 main-merge.sh / 通用包同模块的条目 **#263(规范蒸馏通用版)已 ✅ 完成上线**(main `0af1e6586`);无在跑的冲突任务,无预留位置需求。
- **§21 算法公示**:本次不改算法/数值,不涉公示。
- **§22 数据一致性**:本次不改数据产物,不涉。**未 add 任何根 `data/` 文件**。

## 8. 写码前 7 级阶梯(§6.5)

- 第 1 层(需要存在吗):需要——用户拍板要把「发版本时同步」变成机器提醒。
- 第 2 层(库里已有吗):**复用**现有 `CHANGED_SRC` bump 判定点,不新造版本对比逻辑。
- 第 6 层(一行能搞定吗):核心即 1 行 `echo`(+ 表头注释),无新增函数/变量。

## 9. CI / 上线

- 本改动为 `.sh` 脚本,**未新增测试文件**;`.github/workflows/` 内**无** shellcheck / `bash -n` 步骤(grep 0 命中)⇒ 无 CI-only 风险(不存在跨环境假绿面)。
- `bash -n scripts/main-merge.sh` ⇒ SYNTAX-OK。
- 本 agent 只 commit + push **feat 分支**;merge + push main 由主控走 `scripts/main-merge.sh`(机制 D),并由其统一 bump。

## 10. 交付物 / 复现

- 代码:`scripts/main-merge.sh`(feat 分支)。
- 沙箱取证脚本:`/tmp/mhint_test.sh`(建仓 + 两用例)、`/tmp/mhint_verify.sh`(基线 + mutant),原始输出 `/tmp/mhint-case1.out` / `mhint-case2.out` / `mhint-orig-c*.out` / `mhint-mut-c1.out`。
- 复现:三步 —— ①`git show HEAD:scripts/main-merge.sh > /tmp/main-merge-orig.sh`(改前版)②`bash /tmp/mhint_test.sh`(建沙箱+跑两用例)③`bash /tmp/mhint_verify.sh`(基线+判别力)。