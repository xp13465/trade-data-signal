# claude-work-mode 瘦身+占位符化 v2 — 复审报告归档(2026-09-29)

> **归档说明**:本文归档 reviewer agent 于 2026-09-28 产出的两份**临时报告**(`/tmp/cwmode-review.md`、`/tmp/cwmode-review2.md`)。按 §23.5「新产物当场落档」补做归档——`/tmp` 产物随时会被清理,报告含该线审查全过程,丢了就无法反查。
>
> **归档时状态核对(2026-09-29,主控逐项 grep 实测)**:两份报告列出的 FAIL 项**均已于后续 commit 闭合**(详见 §3)。落档目的是**保留过程可追溯**,不是遗留待办——**无需用户拍板**。

## 1. 背景

`claude-work-mode/` 是主仓的**对外可移植规范包**(供他人按此模式跑 Claude Code)。2026-09-28 对该包做「瘦身 + 占位符化」v2:

- 根 CLAUDE.md **513 → 274 行**,老节号全部保留为「对照行」(防读者按老节号找不到现址)
- 4 个 role skill 加厚(对齐主仓 collab 基座逐节搬运)
- 包内 docs 引用统一 `<docs/...>` 占位符化(明示包不含 docs/)

分支 `feat/claude-work-mode-slim-v2-20260928`,base `e9a592903`,第一轮审查 tip = `ed6ea762b`(4 commit),第二轮复审 tip = `9a229de43`(修复 commit)。

## 2. 两轮复审报告原文

### 2.1 第一轮(原文照录)

```
# claude-work-mode 瘦身+占位符化 review 报告(4 笔 commit)
审查者:reviewer agent(独立,fresh context)
分支:feat/claude-work-mode-slim-v2-20260928 tip=ed6ea762b,base=e9a592903

## 判级:FAIL(2 处悬空 skill 引用 + 3 处漏搬,均需修)

## 必查逐项结论
1. §23 标题vs正文:PASS(标题23.1-23.15,正文16条含23.12-1全在)
2. 节号可达性:FAIL——CLAUDE.md:34「role-implementer skill §3(续跑延续分支)」与 CLAUDE.md:262「§3 机制 C」指向包内 implementer skill §3(上线操作细节)无对应内容=悬空
3. 占位符化:PASS(未闭合0/双尖括号0/反引号裸docs残留0/命令示例未误改;80出现次数vs声称75=单行多占位符合法)
4. 误伤硬项:PASS(token-cache/config-snapshots零改动,5处token-cache字样全在方案文档;原话/锚点id全在;test-baseline-v112缺失见标注项2)
5. 搬运:FAIL——impl漏搬机制C(08-19)+续跑延续分支(09-23);tester漏搬「简洁输出·结论优先」(09-17);rev/res内容基本完整
6. 拓扑图:PASS(4行显示宽度逐位一致66/67/66/66)
7. 自洽性:PASS-nits(README:73明确docs自备;:35轻微模糊有映射表兜底)
8. 方案vs交付:方案机检7项核心保留/可逆/token_cache全过;F2目标章节全部交付;但方案未覆盖08-19/09-23/09-17新增→交付引入悬空

## FAIL 明细(每项:文件:行号+证据)
- F1 CLAUDE.md:262「(兼看 §3 机制 C)」→ 包内 implementer §3 无机制 C;且包内 implementer §0(行27)/§1.1② 要求 agent「必同 commit bump」与主仓机制 C(不自行bump,main-merge统一)语义相反
- F2 CLAUDE.md:34「implementer 侧操作见 role-implementer skill §3」→ 包内 skill §3 无续跑延续分支操作细节(主仓 skill §3 有)
- F3 包内 implementer §3 无机制C/push main 统一入口(主仓08-19用户定);§3 无续跑延续分支(主仓09-23用户定)
- F4 包内 tester 无「简洁输出·结论优先(2026-09-17用户定)」(主仓 tester:18有)
- F5 包内 implementer §4 生产时点=launchd(launchctl list),主仓已改云上systemd(launchd废弃);PROJECT-SPECIFIC §6 同

## 标注项(两处说法不同,不自行选边,交主控)
- M1 §9 语义矛盾:CLAUDE.md:113(§9=新功能先隔离,已下沉→历史归档)vs CLAUDE.md:252(§9→impl §1前端铁律)
- M2 memory锚点过时:PROJECT-SPECIFIC:90 只有 test-baseline-v110/v111-anchor,无主仓 v112;派单要求v112仍在,未达
- M3 PROJECT-SPECIFIC §6+impl§4 的 launchd 定时任务与主仓「云上systemd/launchd废弃」冲突(状态型过时)

## nit
- README:156 映射表「§5(含5.1-5.5)」漏实际§5.6(base pre-existing)
- README:35 已归档对照行与通用可移植章节混述
```

### 2.2 第二轮复审(原文照录)

```
# 第二轮复审报告:claude-work-mode 瘦身+占位符化(commit 9a229de43,base ed6ea762b)

## 判定:**FAIL**(1 项核心未闭合 + 1 项编排不自洽待拍板;修复量小,修完可 PASS)

## 逐项结论
| 项 | 结论 | 证据 |
|---|---|---|
| F5 launchctl→systemd timer | 闭合 | implementer §4 L88 = 主仓 L92 逐字一致;机制 D 避时点行 = 主仓 L95 逐字一致 |
| M3 PROJECT-SPECIFIC §6 同族 | 全拉平 | L103 systemd 表述=主仓一致;L107 机制 D;§6.1 标题改;L203 引用改;仅剩历史背景 L67(uvicorn cwd)与主仓逐字同 |
| F1/F3 skill §3 新增5条 | **未完全闭合** | 五条与主仓基本一致(细微精简可接受);但全包 grep 残留「agent 自行 push main」2 处:CLAUDE.md:132、PROJECT-SPECIFIC.md:108 |
| F2 CLAUDE.md:34 指向 | 闭合 | §3 第五条含续跑延续完整操作细节,指向确切 |
| F4 tester 简洁输出 | 闭合 | 包内 L28 = 主仓 L18 逐字一致(含证据点/不裁失败原文) |
| M2 memory 锚点 | 闭合(暴露 pre-existing) | L90 引用 v110/v111→v112,只改引用未动 §4.2 定义;死引用已清;但 §4.2 正文「当前基准=v1.1.1」 vs 引用 v112(v1.1.7/S06动态a9)自相矛盾=整节过时,pre-existing 应上报 |
| 检查项7 新引入问题 | 无 | 未碰用户原话/锚点id/token-cache/占位符形态;27+/21- 逐行核对无错改 |
| 检查项8 M1 两行 | 原样未动 | CLAUDE.md 本轮只改 §8 L101-104,§9/对照行未动 |
| 检查项9 reviewer skill:98 判断 | 部分成立 | 主仓 reviewer skill:93 逐字同(launchctl list/grep plist),主仓确实未改,包内保持一致=判断成立;但主仓该处已与根 §14(launchd 废弃)矛盾,应上报修主仓,非「不改就完事」 |
| 追加项9 §9/§10 对照行 | 主仓没写反;包内 §9 双义 | 瘦身前(6e0908d5e^)§9=单版前端铁律、§10=切分支保护DB,主仓 L223 对照行是正确老节号映射(主仓正文无 §9/§10);包内正文自编 §9=新功能先隔离/§10=破缓存,与对照行共用「§9」标签双义,读者误读「写反了」——包内独有编排不自洽,待用户拍板 |

## 残留 2 处详情(判定 FAIL 的直接依据)
1. **claude-work-mode/CLAUDE.md:132**(§14 摘要):「**agent 自己 push feat:main 也要避开**盘后定时任务时点(尤其 <update-all 时点> deploy 推 main non-ff 竞争)」——主仓根 CLAUDE.md §14 已改为「push main 要避开...main-merge.sh 内含检查...agent 只 push feat 不 push main(机制 D)」,包内未跟上,与机制 D 直接冲突
2. **claude-work-mode/PROJECT-SPECIFIC.md:108**(§6):「**盘中 push 前端代码 main 也避开 intraday-snapshot 每10分钟时点**...agent 改 app.js/style.css 后 push feat:main 虽改不同文件 rebase 能合并...盘中 push main 选 :00/:10/...安全分钟」——主体仍是 agent push feat:main 指导(带 2026-08-10 修正注),且与包内 implementer §4「盘中 push 代码 main 不避 intraday」自相矛盾

## pre-existing 上报(不走 FAIL,按 §23.7⑤ 通道)
- 包内 PROJECT-SPECIFIC.md §4.2 基准定义整节停留在 v1.1.0/v1.1.1(v1.1.1「当前基准」),memory 权威 v112 = v1.1.7/S06动态a9/new15按日切;本轮把引用行改 v112 后矛盾显性化 ⇒ 建议更新 §4.2 正文口径或加「trade 项目 v1.1.1 时代示例,权威=memory test-baseline-v112-anchor,移植按自身基准替换」注
- 主仓 .claude/skills/role-reviewer/SKILL.md:93「定时挂载真实存在(launchctl list/grep plist/update_all)」与主仓根 CLAUDE.md §14「launchd 已废弃,查 launchctl 是错的」矛盾,主仓本体过时,应修主仓(§23.8)

## 追加项9 完整查证
- 瘦身前老版(commit 6e0908d5e^):`## 9. 单版前端铁律(2026-07-15 web/ 弃用)`(L90)、`## 10. 切分支保护 DB(2026-07-14 已根治)`(L99)
- 主仓根 CLAUDE.md:223:「`§9`→.claude/skills/role-implementer **§1**(单版前端铁律,**节号已变**)」= 老节号映射正确,**没写反**(主仓根正文无 §9/§10,无撞号)
- 包内 CLAUDE.md:252 同句,但包内正文 L113 `## 9. 新功能先隔离`/L116 `## 10. 破缓存/SW/min验证` 是包内自编节号 → 「§9」在包内双义(正文=新功能先隔离→历史归档;对照行=瘦身前老节号单版前端铁律→implementer §1)
- **结论:不是主仓本体写反;包内正文节号与对照行老节号撞号导致不自洽**。正确修法三选一(等拍板):①包内对照行按包内正文语义改(§9→历史归档/memory new-feature-isolated-tab-first;§10→implementer §1) ②对照行标注「§9 指瘦身前老节号,非包内正文 §9」 ③包内正文 §9/§10 换号
```

## 3. 归档时状态核对(2026-09-29,主控逐项 grep 实测)

**结论:两份报告的全部 FAIL 项均已闭合,无遗留待办、无需拍板。**

| 报告项 | 报告结论 | 归档时实测状态 | 实测证据 |
|---|---|---|---|
| F1/F3 残留「agent 自行 push main」2 处 | FAIL(CLAUDE.md:132、PROJECT-SPECIFIC.md:108) | **已闭合** | 现 `claude-work-mode/CLAUDE.md:132`=「agent 只 push feat 不 push main(机制 D)」;`PROJECT-SPECIFIC.md:112/113` 同口径 |
| F2 CLAUDE.md:34 指向悬空 | FAIL | **已闭合** | 包内 implementer skill §3 第五条已含续跑延续分支完整操作细节 |
| F3 漏搬机制 D + 续跑延续分支 | FAIL | **已补** | 包内 implementer skill **L62**(机制 D 统一入口)/**L66**(续跑延续原分支)/**L67**(只 push feat)均在 |
| F4 漏搬 tester 简洁输出 | FAIL | **已补** | 包内 role-tester skill **L28**「简洁输出·结论优先(2026-09-17 用户定)」已在(含「结论后必须带证据点」) |
| F5 launchd 口径 | FAIL | **已闭合** | 包内 implementer §4 + PROJECT-SPECIFIC §6 均已改云上 systemd timer |
| M1/追加项9 §9 双义 | 待用户拍板(三选一) | **已消歧,无需拍板** | 包内 CLAUDE.md **L113** 正文已显式标注「泛化新增节,**无老 §9 对应**;老版 §9=单版前端铁律」;**L116** 标注「内容对应老 §9 单版前端铁律,**非老 §10 切分支保护DB**」——双义已就地消歧 |
| M2 包内 §4.2 基准口径过时 | pre-existing 待修 | **已更新** | 包内 PROJECT-SPECIFIC.md **L85** 现为「当前基准 = **v1.1.7**(2026-08-27,git tag @384005e222)…」,L93 附完整版本链对照,L94 明确「包内旧 v110/v111 锚点已过时」 |
| 主仓 reviewer skill:93 launchd 过时(pre-existing 上报) | 应修主仓 | **已由 B 线第 5 轮覆盖** | commit `199b99695`「role-reviewer 定时任务口径对齐主仓§14(launchd→云上systemd timer)」;待该轮 reviewer 确认后销账(见 pending-index #127) |

## 4. 分支状态

两个 cwmode 分支相对 `origin/main` 均 **0 独有 commit**(已全部 merge 入 main),可清理:

```
feat/claude-work-mode-slim-20260928     相对 origin/main 独有 0 commit
feat/claude-work-mode-slim-v2-20260928  相对 origin/main 独有 0 commit
```

- 本地分支:已删
- 远端分支:待用户点名授权后删(`git push origin --delete` 需用户显式点名分支名)

## 5. 复现

```bash
R=/Users/linhuichen/code/trade
# 状态核对:包内实现是否已含机制D/续跑延续分支
grep -n "机制 D\|续跑" $R/claude-work-mode/.claude/skills/role-implementer/SKILL.md | head
# tester 简洁输出条款
grep -n "简洁输出" $R/claude-work-mode/.claude/skills/role-tester/SKILL.md
# 包内基准口径
grep -n "当前基准" $R/claude-work-mode/PROJECT-SPECIFIC.md | head -3
# §9 双义是否已消歧
grep -n "^## 9\.\|^## 10\." $R/claude-work-mode/CLAUDE.md
# 分支是否已全 merge
for b in feat/claude-work-mode-slim-20260928 feat/claude-work-mode-slim-v2-20260928; do
  echo "$b: $(git -C $R rev-list --count $(git -C $R merge-base origin/main $b)..$b) commit"
done
```

## 6. 诚实标注

- 本归档**只做了状态核对**(grep 实测现文),未重新独立复现两份报告的全部逐项判断;报告里提到的 nit(README:156 映射表漏 §5.6、README:35 混述)未复核,如需处理另派。
- 「FAIL 项已闭合」的判定口径 = 报告点名的位置/内容在当前 main 上已不存在或已改正,证据即 §3 表所列 grep 结果。
