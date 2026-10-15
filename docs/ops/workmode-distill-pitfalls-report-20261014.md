# 任务 #263 · 通用版避坑库(路2)实施报告

- 日期:2026-10-14
- 分支:`feat/263-workmode-pitfalls`
- 交付范围:通用工作模式标准包内的「避坑索引 + 15 个域正文」(共 16 个新建文件)
- 残留后台任务:无(本次执行未出现 `moved to the background (ID:`)

---

## 一、结论

通用版避坑库(路2)**按计划完成**:索引 1 个 + 域正文 15 个,共 **158 条**条目,每条固定五字段(现象 / 根因 / 防再犯 / 反例·代价 / 来源)。
全部正文已去项目化(正文不含原项目的域名/表名/信号名/脚本路径/任务号/记忆名/绝对路径/具体时点),需要项目自己填的值统一用 `<占位符>` 表示;唯一保留原项目标识的是「来源」字段(仅供溯源)。
四项自验(计数对账 / 残留扫描 / 索引↔正文一致 / 五字段完整)全部通过,详见第四节。

---

## 二、交付文件清单(16 个,全部新建)

索引层(1):
- `work-mode-standard/docs/lessons-index.md` —— 按域分节,一行一条 `- <标题> — <一句话钩子>`,共 158 行

正文层(15,均在 `work-mode-standard/docs/pitfalls/`):
- `a-agent-collab.md`(14)/ `b-alert-notify.md`(9)/ `c-test-verification.md`(16)/ `d-git-branch-merge.md`(12)/ `e-data-artifact-consistency.md`(10)/ `f-cost-token.md`(8)/ `g-dispatch-task-scheduling.md`(8)/ `h-research-anti-misjudge.md`(16)/ `i-frontend-deploy-cache.md`(11)/ `j-delete-backup-safety.md`(6)/ `k-prod-ops-stability.md`(12)/ `l-datasource-external.md`(7)/ `m-backtest-caliber.md`(10)/ `n-llm-platform-toolchain.md`(8)/ `o-communication-docs.md`(11)

> 边界遵守:只新建上述 16 个文件,未触碰包内任何其它文件(README / CLAUDE.md / docs/main-governance.md / docs/quality-flow.md / docs/role-based-context-design.md / .claude/** / templates/**),未触碰 `collab-standard-*/`,与并行 agent(负责「正文包/其它包内文件」)零重叠。

---

## 三、口径说明:157 vs 158(源数据 off-by-one)

- 任务描述与蓝图 `docs/ops/workmode-distill-experience-20261014.md` §四**标题行**写的是「通用候选 157 条(15 域)」。
- 但 §四**正文实际逐条枚举 + 每个域标题括号内的条数**机器数出来是 **158**:
  A=14 B=9 C=16 D=12 E=10 F=8 G=8 H=16 I=11 J=6 K=12 L=7 M=10 N=8 O=11,合计 **158**。
- 处置:按 §5.1「数据说话」原则,**以 §四正文实际内容为准(=158)**,不硬凑标题里的 157。本报告如实登记该 off-by-one 为源数据笔误,供上游修订蓝图时对齐。

---

## 四、自验输出(逐条)

### 4.1 计数对账:索引条数 == 正文条数(逐域)

命令:
```
grep -c '^- ' lessons-index.md
grep -H -c '^## ' pitfalls/*.md
```
输出:
```
158
---body---
a-agent-collab.md:14      b-alert-notify.md:9       c-test-verification.md:16
d-git-branch-merge.md:12  e-data-artifact-consistency.md:10  f-cost-token.md:8
g-dispatch-task-scheduling.md:8  h-research-anti-misjudge.md:16  i-frontend-deploy-cache.md:11
j-delete-backup-safety.md:6  k-prod-ops-stability.md:12  l-datasource-external.md:7
m-backtest-caliber.md:10  n-llm-platform-toolchain.md:8  o-communication-docs.md:11
```
逐域合计 = 14+9+16+12+10+8+8+16+11+6+12+7+10+8+11 = **158**;索引 158 == 正文 158 → **PASS**。

### 4.2 残留扫描(recon §5.1 九条命令集)

| 编号 | 扫描目标 | 结果 | 判定 |
|---|---|---|---|
| ① | 域名/URL | 空(0) | PASS |
| ② | 内部目录路径(`.claude`/`scripts`/`static-site`/`trade-data`) | 空(0) | PASS |
| ③ | 任务号 `#NNN` | 空(0) | PASS |
| ④ | 记忆引用(`memory \`x\`` / `[[x]]`) | 空(0) | PASS |
| ⑤ | 业务词(kelly/凯利/baostock/deepseek/feishu/飞书/board_etf_map/sentiment.db/overview.json/nav_bucket/signal_kelly/intraday/域名) | **命中 2 处,均为「来源」字段的记忆名**(`mem:kelly-etf-freeze-lookahead`、`mem:kelly-operability-20x-principal`) | PASS(来源字段为白名单例外) |
| ⑥ | 具体时点 `HH:MM` | 空(0) | PASS |
| ⑦ | 绝对路径 `/Users/<user>/` | 空(0) | PASS |
| ⑧ | 数据文件名 `.json/.db/.parquet` | 空(0) | PASS |
| ⑨ | 占位符命名一致性 | `<占位符>`×15(每个正文文件头部各 1,表述统一);索引层用 `<标题>`/`<一句话钩子>`/`<域文件>`;正文用 `<临时目录>`/`<任务名>` 等 | PASS(命名风格一致,均为「尖括号+中文」) |

⑤ 的两处补充说明:命中位置为 `m-backtest-caliber.md` 第 23 行与第 39 行的**「来源」字段**,内容是两个记忆名 `kelly-etf-freeze-lookahead` / `kelly-operability-20x-principal`。按任务约定「来源字段保留原项目编号/记忆名,仅供溯源」为**唯一白名单例外**,故判 PASS;正文叙述层零业务词残留。

### 4.3 索引 ↔ 正文一致(标题可 grep 对上)

命令:
```
grep '^- ' lessons-index.md | sed 's/^- //; s/ — .*$//' | sort   # 索引标题
grep -h '^## ' pitfalls/*.md | sed 's/^## //' | sort             # 正文标题
comm -3 索引 正文
```
输出:
```
index_titles=     158   body_titles=     158
=== diff (only-in-index / only-in-body) ===
(空 —— 无差集)
```
即:158 个索引标题与 158 个正文 `##` 标题**逐字一致、双向零差集** → **PASS**。任意索引行标题可直接 grep 命中对应正文条目。

### 4.4 五字段完整性(等效「5 抽样」升级为全量)

命令:
```
grep -rho '**现象**'      pitfalls/*.md | wc -l
grep -rho '**根因**'      pitfalls/*.md | wc -l
grep -rho '**防再犯'      pitfalls/*.md | wc -l
grep -rho '**反例/代价**' pitfalls/*.md | wc -l
grep -rho '**来源**'      pitfalls/*.md | wc -l
```
输出:
```
现象=158  根因=158  防再犯=158  反例代价=158  来源=158
```
五个字段各出现 **158 次**,与条目数一致 → 「每条五字段齐全」对**全量 158 条**成立(强于「抽 5 条」的要求) → **PASS**。

> 注:`防再犯` 个别条目写作 `**防再犯:**`(冒号在加粗内),计数用前缀匹配同样为 158,无遗漏。

---

## 五、未决 / 需上游确认

1. **157 vs 158**:见第三节。建议蓝图 §四标题与「15 域」摘要行改为 158,或明确「157 条为最初候选、158 为最终落地」。
2. 索引层小节标题用「A/B/…/O」+ 中文域名的形式(如「A 多 agent 协作与角色纪律(14 条 → `a-agent-collab.md`)」);若包内其它文档对域名有既定中文命名,需与之对齐(当前与我域正文文件头一致)。

---

## 六、恢复路径(可逆性)

- 本报告与 16 个交付文件均在 feat 分支 `feat/263-workmode-pitfalls` 上,未推 main;需要回退直接删除分支即可,仓库主线不受影响。
- 若需重跑:源清单在 `docs/ops/workmode-distill-experience-20261014.md` §四,残留判据在 `docs/ops/workmode-distill-recon-20261014.md` §5.1。