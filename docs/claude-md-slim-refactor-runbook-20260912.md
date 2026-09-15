# CLAUDE.md 精简改造回滚手册(2026-09-12)

> 用途:本次对根 CLAUDE.md 做精简(42.7k→~30k)后,未来若发现"铁律丢了/过度精简/指针断链"等问题,靠本手册快速定位、回滚、根治。
> 配套:盘点报告 `docs/claude-md-slim-audit-20260912.md`(数据+建议)。

## 一、这次改了什么(5 阶段)

| 阶段 | 动作 | 风险 |
|---|---|---|
| P0 安全网 | 新建 `docs/active-rules-archive.md` 全文归档 9 条铁律 + 补 23.11 用户原话进 conflict-overwrite 文档 | 零(只增不改) |
| P1 止血 | 6 条铁律(23.2/3/4/13/14/15)+23.11 指针化 + 历史引用压缩 | 低 |
| P2 下沉 | 9 条铁律(23.1/5/6/7/8/9/10/12/12-1)根文件改极简摘要 | 中 |
| P3 滚动窗口 | §18 索引表只留最近 15 过错+10 经验,更老锚点回 archive | 中(动用户点名表) |
| P4 机制 | §19 周 review 加"下沉检查"一步 + memory 落地 | 机制层 |

## 二、改动文件清单(定位范围)

- `CLAUDE.md` —— 核心,所有阶段都动它
- `docs/active-rules-archive.md` —— 新建,9 条铁律全文归档(唯一事实源转移地)
- `docs/conflict-overwrite-rootcause-2026-08-18.md` —— 补 23.11 用户原话
- `.claude/skills/role-implementer/SKILL.md` / `role-reviewer/SKILL.md` —— description 同步
- `/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/` + `MEMORY.md` —— P4 机制 memory

## 三、回滚方法(三层保险)

1. **git 层(最硬)**:每阶段独立 commit,回滚单阶段 = `git revert <阶段commit>`;整体回滚到改造前 = `git checkout ed98a928c -- CLAUDE.md docs/ .claude/skills/ memory/ MEMORY.md`(基线 ed98a928c 为改造前最后一个 commit)。
2. **归档层**:9 条铁律全文在 `docs/active-rules-archive.md`,6 条+23.11 全文在对应 skill,任何时点都有一份完整全文可捞回。
3. **顺序层**:全程"先建后删",不存在"根文件删了但归档没建"的裸奔态。

## 四、未来定位锚点(发现问题怎么查)

| 现象 | 排查路径 |
|---|---|
| 某条铁律"不见了/被过度精简" | 先看根文件指针指向哪 → `grep` 归档/skill 全文确认是否真丢 |
| 9 条铁律(23.1/5/6/7/8/9/10/12/12-1)全文 | `docs/active-rules-archive.md` |
| 6 条(23.2/3/4/13/14/15)+23.11 全文 | 对应 `.claude/skills/role-*/SKILL.md` 段落 |
| §18 全量锚点(47 过错+30 经验) | `docs/archive/CLAUDE-errors-2026-08.md` 锚点索引块 |
| 字数是否又超 40k | `python3 -c "print(len(open('CLAUDE.md').read()))"` |

## 五、commit 链(implementer 完成后补)

- 基线:ed98a928c
- P0:待补
- P1:待补
- P2:待补
- P3:待补
- P4:待补

## 六、根治指引(发现问题后怎么修)

- **指针断链**(根文件指针指向的 skill 段落被后续改动删了)→ `git log --oneline -- CLAUDE.md` 找删除点 + `git blame` 找责任人 + 恢复指针或回退该 commit。
- **下沉过度**(摘要太简、触发词不够)→ 从 `docs/active-rules-archive.md` 全文补回触发词,不动归档。
- **未来再超限** → 优先走方向 3 定期下沉机制(每周 review 顺带下沉稳定铁律),而非临时砍。
- **定期自查** → §19 周 review 已加"下沉检查"一步(P4),发现负向漂移立即回滚对应阶段。
