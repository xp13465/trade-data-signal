# ponytail 开源项目蒸馏落地说明（2026-09-01）

> 背景：主控评估开源项目 DietrichGebert/ponytail（~118k star）后，用户拍板**蒸馏而非直接装 plugin**（不引入第二条规则体系、不动业务代码、不装 plugin）。可蒸馏内容分跨 4 个角色，本次按用户拍板建议顺序第 3 步落地（1 根治落档 → 2 Karpathy 复核 → 3 ponytail 蒸馏）。
> 蒸馏原则：把 ponytail 规则「本地化翻译」接进现有 skill 体系，不照抄英文、不新建独立 skill、不建第二套规则；全部「纯新增」，不改已有内容默认行为（§23.7 只增不改）；与现有铁律融合指向而非重复造轮子（§23.3 举一反三）。

## 蒸馏了什么 → 落到哪 4 个文件哪个位置

| 落点 | 文件 | 位置 | 蒸馏内容（一句话） |
|---|---|---|---|
| ① implementer（最核心，优先） | `.claude/skills/role-implementer/SKILL.md` | 新增 `## 6.5 写码前 7 级阶梯 + 根因修复 + 少写抽象`（接 §6 举一反三后、§7 前） | ponytail 主 skill 的「7 级阶梯」（写码前自问，停在第 1 个成立的层）+「根因修复」（修根因非症状，共享函数一个守卫 < 每个 caller 一个守卫）+「少写抽象」（不写单实现 interface/单产品 factory/永不变化 config，删除优先于添加） |
| ② reviewer（两份同内容，§22 三处一致） | `.claude/skills/role-reviewer/SKILL.md` | 新增 `### 10.6 代码类 finding 附「删除清单+量化」维度`（接 §10.5 trace/verifier 后） | ponytail /ponytail-review 的「删除清单」逻辑：每个代码类 finding 加 `over_engineering_findings` 维度（action=delete\|simplify + saves_lines + rationale 指向 7 级阶梯层），把 review 从「发现问题」升级为「给出删除指令+量化省多少行/token」；只对代码类 finding 强制，回测/口径类不强制（§23.13 已有 verifier 降级通道） |
| ②' | `.agents/codex-reviewer/SKILL.md` | 新增「per-finding 附加维度：代码类 finding 的删除清单 + 量化」（接 trace+verifier 段后、多轮对抗复核前） | 与 role-reviewer §10.6 同内容（§22 三处一致：role-reviewer + codex-reviewer + implementer §6.5） |
| ③ tester | `.claude/skills/role-tester/SKILL.md` | 新增 `### 5.4 懒但安全 + 最小充分测试边界`（接 §5.3 测试设计质量后） | ponytail「懒但安全」边界：该验的必须验（输入/安全/数据丢失兜底，接 E16+§22），但避免「冗余/过度测试」；给「最小充分测试」定义=覆盖主路径+关键边界，不追求每行全覆盖 |
| ④ researcher | `.claude/skills/role-researcher/SKILL.md` | 新增 `### 3.2 量化影响 + 别过度建模`（接 §3.1 防前视后） | ponytail「measure impact」：先量化再动手，避免过度建模/堆无谓回测维度；与 §5.1 穷举互补（该穷举的穷举/无谓维度不堆）；建模前四问（必要性/复用/更少/量化增量）+ 结论可量化验证 |

## 为什么这么落（与现有铁律的对应关系）

- **指向现有条款而非重复造轮子**（§23.3 举一反三）：
  - implementer 7 级阶梯 → 指向 L11「不加需求外改动」、§5「默认准则不以工作量为衡量偷懒」；根因修复 → 指向 §23.2 修 bug 三铁律操作化（§5）；少写抽象 → 指向 L11 + §5.3「精简保核心」
  - tester 懒但安全 → 指向 E16「该有的数据在不在」+ §22 一致性（安全底线不省），与 §5.3 测试设计质量互补（反面=不为凑覆盖堆冗余测试）
  - researcher 别过度建模 → 与 §5.1 穷举最大化**互补不矛盾**：§5.1 说「该穷举的维度要全」，ponytail 说「无谓维度是浪费」，分界=该维度是否回答真实待验证问题/是否被使用
- **只做纯新增**：每个 skill 加一节，不改已有内容的默认行为（git diff 确认只增不改，见下方核对命令）
- **§23.8 skill 活资产同步**：每个被改 skill 改动处附近都写了「关联规范源」段（标注来自 CLAUDE.md 哪条 § / 哪个 ponytail 原文 / 哪个 memory）；不改 CLAUDE.md 正文（§5.1 跨角色穷举已由主控补进根文件）

## 复现/核对命令

```bash
# 1. 4 个 skill + codex-reviewer 关键词在位（grep 证据）
grep -n "7 级阶梯\|根因修复\|少写抽象" .claude/skills/role-implementer/SKILL.md
grep -n "over_engineering_findings\|saves_lines" .claude/skills/role-reviewer/SKILL.md .agents/codex-reviewer/SKILL.md
grep -n "最小充分测试\|懒但安全" .claude/skills/role-tester/SKILL.md
grep -n "过度建模\|量化影响" .claude/skills/role-researcher/SKILL.md

# 2. §23.8 关联规范源标注在位（每处蒸馏节都有「关联规范源」字样）
grep -c "关联规范源" .claude/skills/role-implementer/SKILL.md .claude/skills/role-reviewer/SKILL.md .claude/skills/role-tester/SKILL.md .claude/skills/role-researcher/SKILL.md .agents/codex-reviewer/SKILL.md

# 3. 只增不改（git diff 确认无删除/无改动存量行）
git diff origin/main -- .claude/skills/ .agents/codex-reviewer/SKILL.md | grep -E "^-" | grep -v "^---" | head
```

## 关联规范源（§23.8 双向标注）

- 根 CLAUDE.md §5.1「数据回测穷举最大化铁律」——被 researcher §3.2 引用（互补口径）
- 根 CLAUDE.md §23.2「修 bug 三铁律」——被 implementer §6.5 根因修复引用
- 根 CLAUDE.md §22「数据一致性铁律」——被 tester §5.4 / codex-reviewer 删除清单维度引用（§22 三处一致）
- 根 CLAUDE.md L11「不加需求外改动」/§5.3「优化精简核心保障」——被 implementer §6.5 少写抽象引用
- 改了以上源头条款时，顺着本说明反向同步 4 个 skill。
