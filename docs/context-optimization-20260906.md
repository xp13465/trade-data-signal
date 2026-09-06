# 上下文/效率优化分析 2026-09-06（任务二，核心）

> 调研 agent 落档。用户点名："开新会话也会超 40k"。本文给量化 + 精简清单 + 优先级。
> 只读产出方案，主控拍板后另派实施。

---

## 1. 现状量化（改前基线）

### 1.1 新会话基础注入构成（主会话启动时）

| 项 | 大小 | 折 token 估算（中文 ~1 token/字） | 说明 |
|---|---|---|---|
| 根 CLAUDE.md | **80.8KB** | ~40-50k tokens | 全量注入每会话 |
| MEMORY.md 索引 | **31.2KB** | ~20-30k tokens | 全量注入每会话（194 条链接，150 索引行） |
| 角色 skill（如 implementer） | 15.6-31.5KB | ~10-20k | 对应角色全量注入 |
| agents 定义（4 个） | ~9.3KB | ~5k | 启动注入 |
| **合计** | **~125-153KB** | **>75-100k tokens** | 已远超 40k 门槛 |

**结论：开新会话基础注入本身（不含任务/系统 prompt）就已 3-4 倍于 40k 目标，必须砍。**

### 1.2 CLAUDE.md 逐节字节（共 80.8KB）

| 节 | 字节 | 占比 | 可减方向 |
|---|---|---|---|
| §23 用户新增铁律（16 小节） | 31.8KB | 39% | 详情迁 governance/skill，索引留指针 |
| §18 防重犯索引表（47 过错锚点行） | 18.7KB | 23% | 每行压短为"锚点|一句话"，删重复 |
| §5 调研后给方案（含 5.1 穷举/5.2 性能/5.3 核心/5.4 基准/5.5 token/5.6 定价） | 13.7KB | 17% | 5.x 细则迁 skill，共享核心只留标题行 |
| §24 前端部署防撕裂 | 3.0KB | 4% | 可迁 skill |
| §22 数据一致性铁律 | 2.0KB | 2% | 保留（核心） |
| §8/8.1 推送+锚点 | 2.8KB | 3% | 保留（核心） |
| §14 生产稳定性 P0 | 1.2KB | 1% | 保留（核心） |
| §0/0.1/0.2/1/6/21/验收/历史引用 | ~8.5KB | 11% | 微调 |

### 1.3 governance 逐节（42.6KB，主控按需读）

| 节 | 字节 | 备注 |
|---|---|---|
| §18.1 主控专属教训 28 条 | 7.4KB | 与 archive 全量重复，可只留锚点索引 |
| §16 agent 角色画像 | 6.1KB | 与 .claude/agents 定义重复 |
| §11 子 agent 卡死/429 | 5.2KB | 核心，保留 |
| §15 回归复查 | 5.3KB | 可压缩 |
| §19 自我成长机制 | 5.0KB | 含周 review 流程 |
| 其余（§1-§20/§18.2/验收/边界） | ~13.6KB | 微调 |

### 1.4 MEMORY.md 索引（31.2KB）+ memory 文件（193 个，共 413KB）

| 类别 | 数量 | 大小 | 处置 |
|---|---|---|---|
| 索引行（链接到 memory 文件） | 150 行 | ~31KB | 每行压短为"标题+触发词+指针" |
| memory 文件 0-2KB | 110 个 | ~150KB | 小文件多，按需读不注入 |
| memory 文件 2-5KB | 79 个 | ~240KB | 按需读 |
| 大文件（test-baseline-v112-anchor 13.9KB 等） | 4 个 | ~27KB | 权威锚点，保留 |
| **孤儿 memory 文件（有文件无索引行）** | **22 个** | — | 补索引或归档 |

孤儿清单：alert-dedup-mechanism / appjs-em-dash-edit / claude-self-daily-backup / daily-metric-date-format / export-output-path-sync / fetchjson-skip-gz / intraday-lunch-pause / intraday-snapshot-schedule / mac-notify-debug / midflight-pivot-stop-old-agent / monitor-log-anomaly-blindspot / notify-email-vs-push / poll-jsonl-use-stat-L / r2-optimize-after-generate / rzhb-dur-1s-t1-normal / source-reliability-needs-stress-test / tasks-state-log-unmanaged-gap / test-baseline-v100-anchor / test-baseline-v110-anchor / test-baseline-v111-anchor / update-all-process-mutex / user-risk-preference-stability-first

### 1.5 role skills（合计 84.5KB）

| skill | 字节 | 节数 |
|---|---|---|
| role-implementer | 31.5KB | 14 |
| role-reviewer | 22.7KB | 13 |
| role-researcher | 15.6KB | 6 |
| role-tester | 14.7KB | 8 |

## 2. 精简方案（§5.3 核心保障三铁律：核心保留+可逆+复查）

### 2.1 CLAUDE.md 精简（80.8KB → 目标 30-35KB，省 ~50KB）

| 动作 | 节 | 省 KB | 核心保留清单 |
|---|---|---|---|
| A1 迁全量到 governance/skill，根只留索引 | §23 各小节（23.1-23.15） | ~25KB | 每节留 1 行标题+触发词+指针到 governance/skill |
| A2 索引表压短 | §18 过错表 47 行+经验 30 行 | ~10KB | 每行保留"锚点id|一句话防重犯|archive行号"，删根因描述（已在 archive） |
| A3 5.x 细则迁 researcher skill | §5.1-5.6 | ~9KB | 共享核心留 §5 标题行+一句话"细则见 researcher skill §3" |
| A4 其他微调 | §24/§22/§8 措辞 | ~2KB | 核心语义不动 |
| A5 新增 | §18 新条（候选-A/B，见 session-review） | +0.3KB | 每会话注入一次 |

> 核心保障：标题/触发词/结论/指针全保留，全量原文在 docs/archive/CLAUDE-errors-2026-08.md + governance + skill 可反向追（§18 已归档一次，§23 详情迁 governance 后可逆）。

### 2.2 MEMORY.md 索引精简（31.2KB → 目标 15KB，省 ~16KB）

| 动作 | 内容 | 省 KB |
|---|---|---|
| B1 索引行压短 | 150 行每行去掉触发=后的重复描述，只留"标题+触发词+指针" | ~8KB |
| B2 合并同主题行 | 已有多行合并（如 3 个 test-baseline 锚点行、5 个数据源兜底行） | ~3KB |
| B3 清理孤儿文件索引 | 22 个孤儿：7 个补索引，15 个过时/被覆盖的归档 | ~2KB |
| B4 过时文件标注 | 标 ⛔已停用/✅已上线/已被规范取代（约 30 个） | ~3KB |

> 核心保障：触发词前缀全保留（recall 不漏检）；文件名/链接全保留；状态型不删只标注。

### 2.3 role skills 精简（84.5KB 总量，单 skill 注入 15-31KB）

| 动作 | 内容 | 省 KB |
|---|---|---|
| C1 implementer 压短 | 14 节中冗余的重复教训（与 CLAUDE.md §18/§23 双份）改指针 | ~10KB |
| C2 reviewer 压短 | 13 节压缩 | ~5KB |
| C3 共用模板抽取 | 三 skill 重复的"验收口径/防重犯"模板抽共用 | ~3KB |

> 核心保障：角色专属操作化步骤保留，只砍与共享核心重复的教训全文（指向 archive）。

## 3. 40k 门槛破法：砍什么省多少（按优先级）

| 优先级 | 动作 | 省 KB | 累计后估算 |
|---|---|---|---|
| **P0（先做）** | A1 §23 迁 governance + A2 §18 索引压短 | 35KB | CLAUDE.md 80.8→46KB |
| **P0（先做）** | B1+B2 MEMORY 索引压短 | 11KB | MEMORY 31→20KB |
| **P1** | A3 §5 迁 skill | 9KB | CLAUDE.md 46→37KB |
| **P1** | B3+B4 孤儿/过时清理 | 5KB | MEMORY 20→15KB |
| **P2** | C1-C3 skill 精简 | 18KB | 单 skill 注入减半 |
| **合计** | — | **~78KB** | 基础注入 153→~75KB（≈40k tokens） |

**达标判定：新会话基础注入 ≤ ~40k tokens。** P0 两刀做完即降 46%（153→84KB），P0+P1 完可到 ~75KB（接近 40k）。P2 属锦上添花。

## 4. 效率方法优化（对照 governance §16 + §5.5）

| 观察（本会话） | 问题 | 沉淀 step |
|---|---|---|
| 482/820 Bash 是盯进度轮询 | 主控手查=最大 token 浪费 | §11 OPT-1 ③批量 cron 兜底：一 cron 一次查全部，门控零输出；主控只在收到 cron system message 时处理 |
| TaskOutput 轮询返回 MB 级 | 每次 block=False 拉全文 | 轮询改读进度文件尾部 grep DONE/关键词；block 一次等完成 |
| reviewer FAIL 三分法 F1/F2/F3 | 好范式但未固化 | 沉淀为 reviewer skill 标准输出模板（阻断分三类+并行派修） |
| rebase 后同分支续改 | 省 force push 链路 | 沉淀：私有 feat 分支 rebase 后本地合，不 push rebase 结果 |
| 重复读 TASKS.md/app.js | 大文件整读 | §8.1 锚点已给时 Read 带 offset/limit |
| agent 白跑（accum-nav-d 前两派） | 派单未钉验收物 | 派单 prompt 加"产出物验收清单"，reviewer/tester 视角先行 |

## 5. 先做哪 3 件事（推荐顺序）

1. **P0-1：§23 详情迁 governance/skill，根 CLAUDE.md 只留一行索引**（省 25KB，最大单刀）
2. **P0-2：§18 索引表压短为"锚点|一句话|archive行号"**（省 10KB，与 P0-1 同批实施）
3. **P0-3：MEMORY.md 索引行压短 + 22 孤儿文件清理**（省 11-16KB，防 recall 漏检）

> 三刀做完 CLAUDE.md 80.8→46KB、MEMORY 31→15-20KB，基础注入降 ~50%。实施派 implementer，reviewer 回归（§5.3 核心保留+可逆）。

## 6. 复现段

- 统计命令：
  - CLAUDE.md 各节：`python3` 逐节字节脚本（分析本任务落档过程）
  - governance 各节：同上
  - MEMORY 索引行数：`grep -c "^- \[" MEMORY.md` = 150
  - memory 文件数：`ls memory/*.md | grep -v MEMORY.md | wc -l` = 193
  - 孤儿文件：`comm -23` 对比 memory 文件名 vs MEMORY.md 链接 = 22
- 数据源：`/Users/linhuichen/code/trade/CLAUDE.md` / `docs/main-governance.md` / `~/.claude/projects/-Users-linhuichen-code-trade/memory/`
- 数据截止：2026-09-06
- 口径说明：字节按 UTF-8 实测；token 估算按中文 ~1 token/字、英文 ~1 token/4 字符 粗估；"40k"指用户口述新会话门槛。

---
*落档：2026-09-06，researcher agent*
