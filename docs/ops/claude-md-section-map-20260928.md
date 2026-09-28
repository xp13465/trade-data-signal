# 根 CLAUDE.md 节号对照表 + 悬空引用施工图（2026-09-28）

> 归属任务：`docs/pending-features-index.md` **#121**（节号引用可达性审计 + 悬空清理）。
> 上游：#120（§8.1 错引,已 merge `6342b981e`）—— 同一类病:**门牌换了住户、通讯录没改**。
> 本文件双职责:①**对照表详细版**（根 CLAUDE.md 只留一行精简版指向此处）②**阶段 2 施工图**。

---

## 一、为什么需要对照表

根 CLAUDE.md 经多轮瘦身,「瘦身=移动不=删除」——原文章节下沉到了
`docs/main-governance.md` / `.claude/skills/<role>/SKILL.md` / `docs/archive/`。
但**全仓引用仍按老节号写「CLAUDE.md §N」**,读者翻根文件翻不到。

关键认知:**下沉不是"编号全变",而是"去哪找"**——`docs/main-governance.md` 里
§2/§3/§4/§7/§11/§15/§16/§19/§20 **节号同名保留**,只是换了文件。

---

## 二、对照表（老节号 → 现址）★ 权威

| 老节号 | 现址 | 备注 |
|---|---|---|
| `§2` | `docs/main-governance.md` §2 | 同名节（监管+loop,主控只派发） |
| `§7` | `docs/main-governance.md` §7 | 同名节（memory 读优化 + 落档写保障） |
| `§11` | `docs/main-governance.md` §11 | 同名节（子 agent 卡死/429 处理） |
| `§15` | `docs/main-governance.md` §15（主控侧）+ `.claude/skills/role-reviewer` §1（操作层） | **两处**;reviewer skill 标题自带「原 §15 操作层」 |
| `§9` | `.claude/skills/role-implementer` **§1** | ⚠️ **节号已变**:「单版前端铁律(原 §9 全文)」 |
| `§6.5` | `.claude/skills/role-implementer` §6.5 | 「写码前 7 级阶梯」,本就非根文件节 |
| `§10` | `docs/archive/CLAUDE-history.md` | 切分支保护 DB |
| `§17` | `docs/archive/CLAUDE-history.md` | 火山方舟高峰（已作废） |
| `§12` / `§13` | **本仓无全文留存** | ⚠️ 见第四节「死指针」 |

**根文件仍在、无需对照**：`§0 §0.1 §0.2 §1 §5(含 5.1~5.6) §6 §8 §8.1 §14 §18 §21 §22 §23(含 23.1~23.15) §24`

---

## 三、可达性核实（每个映射逐项验证,不凭猜）

核实命令与结果（2026-09-28 实跑）：

```bash
cd /Users/linhuichen/code/trade

# 1. governance 同名节
grep -n "^## \(2\|7\|11\|15\)\." docs/main-governance.md
#  → L22 §2 监管+loop / L44 §7 memory 读优化 / L54 §11 子agent卡死 / L72 §15 主功能回归复查  ✅

# 2. reviewer skill §1
grep -n "^## 1\." .claude/skills/role-reviewer/SKILL.md
#  → L10 「## 1. 主功能回归复查(原 §15 操作层,2026-08-06 计入)」  ✅

# 3. implementer skill §1 / §6.5
grep -n "^## \(1\|6\.5\)" .claude/skills/role-implementer/SKILL.md
#  → L33 「## 1. 单版前端铁律(原 §9 全文)」/ L121 「## 6.5 写码前 7 级阶梯」  ✅

# 4. archive 各节
grep -o "§1[0-9]*" docs/archive/CLAUDE-history.md | sort -u
#  → §10 §14 §17   ⚠️ 无 §12/§13（见第四节）
```

> ⚠️ 踩坑记录:`grep "^## 6\.5\."` 匹配不到,因标题是 `## 6.5 `（**空格**非点）。
> 核实文档节号时正则不要把分隔符写死。

---

## 四、❗死指针发现（pre-existing,非本轮引入）

根 CLAUDE.md「历史/约束归档引用」段的 §12 / §13 两条,原文写「原文见 `docs/archive/CLAUDE-history.md`」,
**但该文件根本没有这两节**——它的标题即写明「CLAUDE.md 历史章节归档(**§17/§10**,2026-08-12)」,
全仓 `grep` 也搜不到 §12/§13 全文。

| 条文 | 现指针 | 实际情况 |
|---|---|---|
| `§12 superpowers 融合规则` | → archive/CLAUDE-history.md | 该文件无此节 |
| `§13 模型能力约束` | → archive/CLAUDE-history.md | 该文件无此节 |

**唯一留存**：根文件那两行**单行摘要本身**（核心信息已在:§12 的"跳过 HARD-GATE + continuous-execution"、
§13 的"仅文本/禁图片/撞 400/ASCII 示意图"）;另在**外部同步仓** `claude-work-mode/CLAUDE.md`
（老快照 L164/L484）还留有较详版本。

**是否算"丢核心"**：按 §5.3（核心保障）判定 **否**——核心约束在摘要里一句话说全了,未丢。
定性 = **指针指空**（读者按指针翻不到,会误以为文档缺失）,不是内容丢失。

**处置建议（待用户拍板）**：两个选项,成本都极低——
- **甲**（推荐）：把两条的「原文见 docs/archive/CLAUDE-history.md」改成准确表述
  （如「本仓已无全文归档,本节摘要即权威」）。**改 2 行,零风险,消灭死链。**
- **乙**：从 `claude-work-mode/CLAUDE.md` 老快照把两节全文捞回补进 archive,再把指针修对。
  **更完整**（§5.3 可逆性更好）,但注意 claude-work-mode 是**持续被每日自动任务写的外部仓**,取值前得先确认那份快照是"本仓下沉时的状态"而非被后续改过;且会略增 archive 体积。

---

## 五、悬空引用全量分布（阶段 2 施工图）

**口径**：全仓 `CLAUDE.md §N` 字面引用,`N` ∈ 根文件已无的 8 个节号
（`§2 §6.5 §7 §9 §10 §11 §12 §15`）。**不含**根文件仍在的节号（那 329 处正常）。

字面命中 **57 处**,分四类：

| 类 | 处数 | 落点 | 处置 |
|---|---|---|---|
| **A 该改** | **~17** | `docs/smoke-checklist.md`(5)、`docs/backup-restore.md`(2)、`docs/agent-quickstart.md`(1)、`docs/data-deploy-quickstart.md`(1)、`docs/feishu-bot-integration-plan.md`(1)、`docs/r2-migration-implementation-report.md`(1)、`docs/kelly/position/kelly-fade-filter-interaction.md`(1)、`.claude/skills/role-reviewer/SKILL.md`(1)、代码注释 4 处（`scripts/upload_r2.py`·`scripts/lhb_history_backfill.py`·`scripts/gold_night.sh`·`app/collector/gold_night.py` 各 1） | 阶段 2 按第二节对照表逐个替换 |
| **B 不改** | 10 | `NOTES.md`(8)、`docs/archive/TASKS-done.md`(2) | **历史陈述**（"已落档/已 push/commit xxx"）,同 `staticdata-daily-brief-sync.md:97` 口径——**改历史=篡改记录**,反查链断 |
| **C 不改** | 25 | `.claude/worktrees/codex-reviewer/**` | 隔离区**镜像副本**,非主树;改了也会被覆盖,随 codex 分支自身演进 |
| **D 阶段 3** | 1 | `collab-standard-claude/.claude/skills/role-implementer/SKILL.md` | 外部同步仓,与 #120 ④批 3 仓同批处理 |

> **修正说明**:早前口头报过「真悬空 ~53 处」——那是**含 B/C 类的字面数**。
> 剔除历史陈述与镜像副本后,**阶段 2 主树实际只需改约 17 处**。
> （另 `docs/pending-features-index.md` 1 处是 #121 任务描述文字本身,非引用,不计。）

**阶段 2 施工注意**：
- `.claude/skills/role-reviewer/SKILL.md` 那处自身已写明「`§15`(review 分级)…governance §15 派单段有一行指针」——**它其实已区分对了**,改前先读原文,避免把对的改错（同 #120 §9 悬空教训:改动引入新错）。
- 代码注释 4 处（`.py`/`.sh`）改后须 `py_compile` / `bash -n` 自验。

---

## 六、复现段

```bash
cd /Users/linhuichen/code/trade

# ① 全仓引用分布
grep -rhoE "CLAUDE\.md §[0-9]+(\.[0-9]+)*" \
  --include="*.md" --include="*.py" --include="*.sh" --include="*.js" --include="*.mjs" --include="*.json" . \
  | sort | uniq -c | sort -rn

# ② 悬空节号逐处落点（8 个已下沉节号）
grep -rnE "CLAUDE\.md §(9|15|7|2|11|10|6\.5|12)([^0-9.]|$)" \
  --include="*.md" --include="*.py" --include="*.sh" --include="*.js" --include="*.mjs" --include="*.json" . \
  | grep -v "^./.git/"

# ③ 主树 A 类（剔镜像/历史）
#    … | grep -v "worktrees/" | grep -vE "NOTES\.md|archive/TASKS-done\.md"

# ④ 映射可达性核实 → 见第三节命令块
```

**生成方式**：本文件为人工核查产物,无独立生成脚本;上列命令即完整复现路径。

---

## 七、执行状态

- **阶段 1（对照表）** ✅ 2026-09-28：根 CLAUDE.md「历史/约束归档引用」段首加一行精简对照,末尾详情指向本文件。
- **阶段 2（清 17 处）** ✅ 2026-09-28（feat/section-ref-cleanup-20260928）：按第二节对照表逐处替换主树 A 类 17 处（smoke-checklist 5 / backup-restore 2 / agent-quickstart 1 / data-deploy-quickstart 1 / feishu 1 / r2-report 1 / kelly-fade 1 / reviewer skill 1 / 代码注释 4）,全部带「原 §N」溯源标注。B 类（NOTES 历史陈述 8）/C 类（worktrees 镜像 25）/D 类（外部同步仓 1）不改,处置理由见第五节。
- **阶段 3（外部同步仓）** ⏸ 与 #120 ④批 3 仓合并处理。⚠️ `claude-work-mode` 每日被 token-cache-stats 自动任务写,需避撞车。
- **死指针（第四节）** ✅ 2026-09-28（走乙案）:§12/§13 全文已从框架仓 claude-work-mode 对应节还原补进 `docs/archive/CLAUDE-history.md`（顶部标题已更新含 §12/§13;每节首行标注「非本仓下沉前原文逐字留存,核心约束一致,细节可能有出入」）。根 CLAUDE.md 两行「原文见 docs/archive/CLAUDE-history.md」指针现真实可达,不再指空。
