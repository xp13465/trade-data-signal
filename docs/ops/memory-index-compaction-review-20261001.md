# MEMORY.md 索引瘦身独立复核报告(2026-10-01)

- **复核对象**:`/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md`(索引层,已瘦身)
- **对照基线**:`/tmp/MEMORY.md.bak-20261001` + `/Users/linhuichen/.claude/backups/memory-index-20261001/MEMORY.md.pre-compact-20261001`
- **复核范围**:只读复核(未改目标文件、未改任何 memory 文件、未执行还原、未 commit)
- **复核依据**:CLAUDE.md §5.3 优化/精简核心保障铁律(①核心保障 ②可逆 ③复查兜底 ④触发词补强)
- **复核者**:reviewer agent(fresh context 独立复核,不复用实施方数字)

---

## 0. 结论

**PASS-with-caveat**

| 必核项 | 结果 |
|---|---|
| 1 双向机检(链接/死链/孤儿) | **PASS** — 207/207,丢失 0 / 新增 0 / 死链 0 / 孤儿 15(未新增) |
| 2 孤儿 15 个是否本次新制造 | **PASS** — 与 2026-09-27 孤儿审计「甲类已升格」15 条**集合完全相同**,按设计不进索引 |
| 3 核心保留(14 条抽样 + 207 条全量 token 审计) | **PASS** — 核心丢失 0 条;机器初判 5 个疑似丢失项逐一人工核实**全部为误报** |
| 4 触发词覆盖 | **PASS(附代价)** — 104 行带 `触发=`,28 行无 `触发=` 但全部有可检索 cue;无一行丢失整个触发尾巴 |
| 5 可逆性 | **PASS** — 两份备份 md5 一致,还原命令可执行(本次未执行) |

**caveat 3 条(§5「瘦身真实代价」,均不构成核心丢失,给主控决策)**:①状态型基准事实(v1.1.7)移出"每会话注入层";②18 行事实型 token 从注入层下移到主题文件(占 132 行 13.5%);③操作型细节(ssh key 路径/备份路径/设计文档路径)需多开一次文件。

---

## 1. 必核 1:双向机检(旧 vs 新)

**原始命令**
```bash
python3 - <<'PY'
import re, os, collections
NEW='/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md'
BAK='/tmp/MEMORY.md.bak-20261001'
DIR='/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory'
pat = re.compile(r'\[[^\]]+\]\(([^)\s]+\.md)\)')
links = lambda p: pat.findall(open(p,encoding='utf-8').read())
so, sn = set(links(BAK)), set(links(NEW))
print(len(links(BAK)), len(so), len(links(NEW)), len(sn))
print("丢失", sorted(so-sn)); print("新增", sorted(sn-so))
files = {f for f in os.listdir(DIR) if f.endswith('.md')}
print("新死链", sorted(x for x in sn if x not in files))
print("新孤儿", sorted(f for f in files if f.endswith('.md') and f!='MEMORY.md' and f not in sn))
PY
```

**实测数字**

| 指标 | 旧(备份) | 新(现文件) |
|---|---|---|
| 链接总数(含重复) | 207 | 207 |
| 唯一链接 | 207 | 207 |
| 重复链接 | 0 | 0 |
| 死链(指向不存在的 .md) | 0 | 0 |
| 孤儿(.md 在盘、索引未收) | 15 | 15 |
| 磁盘主题 md 数(不含 MEMORY.md) | — | 222 |

- **丢失(旧有新无)= 0**;**新增(新有旧无)= 0**;**新制造孤儿 = 0**(旧孤儿集合 − 新孤儿集合 = 空)
- 交叉自洽:222 个主题 md − 207 索引链接 = 15 孤儿,与上面的孤儿数吻合
- 行序未动:`python3` 逐个取「该行首个链接」得 132 项序列,旧新**逐位完全一致**(`== True`);非空行数 133(含标题行)一致;多链接合并分组行 24 组,分组结构未拆

---

## 2. 必核 2:15 个孤儿是否本来就是孤儿

**原始命令**
```bash
python3 - <<'PY'
import os,re
DIR='/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory'
pat=re.compile(r'\[[^\]]+\]\(([^)\s]+\.md)\)')
new=set(pat.findall(open(os.path.join(DIR,'MEMORY.md'),encoding='utf-8').read()))
files={f for f in os.listdir(DIR) if f.endswith('.md') and f!='MEMORY.md'}
orph=set(files-new)
audit=open(os.path.join(DIR,'memory-orphan-audit-20260927.md'),encoding='utf-8').read()
sec=audit.split('### 甲类')[1].split('### 乙类')[0]
jia=set(re.findall(r'^\| ([\w\-]+\.md) \|', sec, re.M))
print(len(orph), len(jia), orph==jia, sorted(orph^jia))
PY
for f in <15 个孤儿>; do head -6 "$f" | sed -n '3p'; done
```

**实测结果**:`孤儿数: 15 | 审计甲类数: 15 | 集合相等: True | 差集: []`

15 个孤儿与 `memory-orphan-audit-20260927.md` 的**甲类「已升格」15 条逐一对上**,该审计(2026-09-27,逐条读全文定性)已判定它们「内容已成为正式条文(CLAUDE.md 章节 / role skill),文件原地不动、不补索引」。逐条 `description:` 自述佐证:

| 孤儿文件 | 自述/升格去处 |
|---|---|
| optimization-core-preservation.md | 规范已进 CLAUDE.md §5.3,memory 只留触发指针 |
| perf-opt-model-params-first.md | 规范已进 CLAUDE.md §5.2 |
| data-consistency-iron-rule.md | 规范已进 CLAUDE.md §22 |
| version-feature-freeze-contract.md | 规范已进 CLAUDE.md §23.7 |
| reply-colloquial-chinese.md | 规范已进 CLAUDE.md §6 |
| research-archive-immediately-categorize.md | 规范已进 CLAUDE.md §23.5 |
| complex-table-explanation-style.md | 规范已进 CLAUDE.md §23.9 |
| asset-version-cache-busting.md | 规范已进 CLAUDE.md §24 |
| production-stability-p0.md | CLAUDE.md §14 + implementer skill §4 |
| appjs-em-dash-edit.md | implementer skill §7 经验 E06 |
| export-output-path-sync.md | implementer skill §1 |
| feishu-hooks-zero-cost.md | implementer skill §7 经验 E17 |
| reduce-token-waste-behaviors.md | CLAUDE.md §5.5 |
| self-growth-mechanism.md | CLAUDE.md §18/§19 |
| tasks-state-log-unmanaged-gap.md | CLAUDE.md §23.12(已补「状态日志只留最新一坨」) |

**判定:按设计不进索引,非本次瘦身新制造**(旧 15 = 新 15,差集为空;本次瘦身零新增孤儿)→ 不构成 FAIL。

---

## 3. 必核 3:核心保留抽查

### 3.1 派单点名的 7 条(压得最狠,逐条给判定)

原始命令(取旧新两行 + 回主题文件 grep 被砍内容):
```bash
python3 - <<'PY'   # 打印每条 OLD/NEW 行 + 尾巴 chars
import re
def lines(p): return [l.rstrip('\n') for l in open(p,encoding='utf-8') if l.strip()]
...
PY
grep -n "large-json\|SigV4\|rm --cached\|--date\|幂等" r2-large-json-backup-never-complete.md
# 其余 6 条同法(见各条证据行号)
```

| # | 条目 | 索引行 chars 旧→新 | 被砍内容在主题文件的证据 | 判定 |
|---|---|---|---|---|
| 1 | r2-large-json-backup-never-complete.md | 273→105 | `key = f"large-json/{today}/..."` L16;无 `--date`/跨天零复用 L17-18;9 目录+「绝不能 `git rm --cached`」L32;`s3_request` 缺 SigV4 排序→多参数 list 403 L38 | **✓ 核心仍在** |
| 2 | non-isolated-agent-switches-main-branch.md | 215→105 | 「一句话」checkout -b 致主仓 HEAD 被切走 L13;收尾切回 main + merge 前必 `git branch --show-current` L18-19 | **✓ 核心仍在** |
| 3 | main-merge-fail-leaves-half-merged-main.md | 201→102 | FAIL 不回滚/本地 main 已前进远端不动 L13;「说清在哪个分支/commit/是否已进 main」L27;恢复=再跑一次 main-merge L28 | **✓ 核心仍在** |
| 4 | git-output-needs-quotepath-false.md | 188→97 | 八进制转义+双引号 L11;`endswith(".md")` 静默 False 实例 L20;`-c core.quotepath=false` 或 `-z` L25 | **✓ 核心仍在** |
| 5 | test-baseline-v112-anchor.md | 154→55 | description L3 含 `v1.1.7`/`tag@384005e222`/S06 动态 a9·new15 按日切/快照单源禁自算/NEW14·15·8 键须声明非基准/§5.4⑥;基准定义与派单话术 L10-14 | **✓ 核心仍在**(代价见 §5①) |
| 6 | kill-residual-verify-ppid-chain.md | 163→87 | 「判据是 PPID 属主链不是命令名」L13;误杀生产定时任务→中断备份+**假告警**实例 L20;L22「命令名不是身份,调用链才是」 | **✓ 核心仍在** |
| 7 | staticdata-old-mirror-keep-decision.md | 194→95 | 路径 `~/code/trade-data-signal-staticdata-old-20260926`+8.3G L19;用户 2026-09-30 拍板再留 30 天/到期 10-30 L22;「不得擅自删除」L25(**索引标题行亦保留「(2026-10-30 到期)」**) | **✓ 核心仍在** |

### 3.2 追加 7 条(覆盖分组行/状态型/教训型/口径型)

| # | 条目(类型) | chars 旧→新 | 被砍内容的主题文件证据 | 判定 |
|---|---|---|---|---|
| 8 | task-wrapup-summary-report.md(分组行) | 462→375 | 被砍触发词「从 todolist 挑活」→ pending-index-drift-verify-before-recommend.md L17;「汇报面板状态」→ L21;「禁行号一刀切」→ archive-dispatch-by-block-type.md L13,L16 | **✓** |
| 9 | sensenova-linear-cool-cooldown-overkill.md(分组行,本组降幅最大 137) | 697→560 | 「implementer/tester 一启动 400」→ claude-code-output-config-effort-400.md L3 description;「WebSearch 被拒·401」→ openrouter-config-websearch-effort-keychain.md L3 description | **✓** |
| 10 | concurrent-implementers-worktree-isolation.md(分组行) | 505→397 | 「hook 读 tool_input 机检」→ L30;`git worktree list` 占用 → resume-same-task-reuse-branch.md L11,L16;commit hash 验收 → worktree-implementer-commit-verification.md L3,L16;cherry-pick 漂移 → resume-same-task-reuse-branch.md L3 | **✓** |
| 11 | kelly-backtest-caliber-authority.md(口径型) | 149→76 | 锚点 all A=161.63% L20;±0.1% 对账闸 L24;口径四要件 L15;被砍的 K=155.42% 主题文件已标「**已作废,仅存档对照**」L22 | **✓**(删掉的恰是过时数字,正向) |
| 12 | monitor-blindspot-exit0-syntax-error.md(分组行) | 392→316 | 「扫语法错」→ 其自身 L3 description/L16;「latest.md 沉默≠无告警」→ alert-triage-event-driven-scan.md L3,L17;「24h stale 降级」→ alert-dedup-mechanism.md | **✓** |
| 13 | gate-verify-in-prod-tree-not-clean-worktree.md | 185→80 | 主仓实跑 FAIL 1663 处+根因(扫进 `.claude/worktrees/` 副本)L15-16;「扫描清单优先 git ls-files」L24;「两条对照命令」L25 | **✓** |
| 14 | small-fix-no-agent-shell.md(分组行,本组降幅最大 192) | 607→415 | 「agent 半途停=主控接盘」→ 其自身 L15 ③;「先 TaskStop + pgrep 确认」→ user-takeover-stop-inflight-agent.md L15 ①②;「用户说你自己来/直接改」→ 同 L15(接管信号) | **✓** |

### 3.3 全量 token 级审计(207 条全覆盖,超出抽样要求)

**方法**:用 `difflib.SequenceMatcher` 逐行取「被删除/替换掉的原文」→ 正则抽**事实型 token**(`v1.1.x` / 百分数 / `§x.y` / 反引号串 / 路径 / 含数字标识符)→ 逐个回该行对应主题文件全文 grep,找不到的才人工核实。

**原始命令**
```bash
python3 - <<'PY'
import re, os, difflib
tok_pat=re.compile(r'v?\d+(?:\.\d+)+|\d+(?:\.\d+)?%|`[^`]+`|[A-Za-z_][A-Za-z0-9_]{2,}\d[A-Za-z0-9_]*|§\d+(?:\.\d+)?|~/[\w\-./]+|[\w\-]+/[\w\-./]+\.\w+')
# 逐行 diff 取 removed → 抽 token → 回主题文件 grep
PY
```

**实测结果**:**18 行有事实型 token 从注入层移出**;机器初判 5 个 token「主题文件里找不到」,**逐个人工核实全部为误报**:

| 机器疑点 | 人工核实 |
|---|---|
| `large-json/{今天}` | 主题文件 L16 为 `large-json/{today}` — 中英写法差异,同物 |
| `~/.claude/backups/daily/保留30天` | claude-self-daily-backup.md L3,L10 有完整路径+「保留 30 天滚动」 |
| `设计见docs/kelly/analysis/kelly-overfit-monitor-design.md` | overfit-monitor-design.md L3,L11 原文即有该路径;目标文件在盘(18473 B) |
| `.agents/zcode-standin/SKILL.md` | zcode-standin-handoff.md L3 有 `.agents/zcode-standin/` + SKILL.md §2 引用;目标文件在盘(15764 B) |
| `docs/codex-reviews/codegraph-eval-20260901.md` | codegraph-eval-conclusions.md L11 原文即有;目标文件在盘(8188 B) |

**结论:核心丢失 = 0 条**(14 条抽样与 207 条全量两条路径互证)。

---

## 4. 必核 4:触发词覆盖

**原始命令**
```bash
python3 - <<'PY'   # 逐行判定:是否有 '触发='、尾巴 chars、行内可检索信息
...
PY
```

**实测数字**(索引行 132 行 / 链接 207 条):
- 带 `触发=` 尾巴:**104 行**;无 `触发=`:**28 行**(旧 29 行;「旧有触发新没有」= 空集 → **没有一行整体丢掉触发尾巴**)
- 无 `触发=` 的 28 行**全部**带可检索 cue(例 `夜间数据更新时点 — 美指5点/欧洲2点/黄金9:25`、`主功能回归复查 — 新功能不可影响老功能,大阶段必回归`)
- 「既无尾巴又无标题信息」的行:**0**;单链接且完全无信息行:**0**
- 4 行无 `—` 尾巴(公募/ETF弹窗/通知面板/§0三件),但**每条链接自带括号 cue**(如 `(采集前查report_date)`),可判断相关性

**砍过头清单(如实报,3 条,不美化)**
1. `test-baseline-v112-anchor.md`(55 chars):触发词够把文件打开,但**状态型事实(当前基准=v1.1.7 + tag)不在注入层了** → §5①
2. `kelly-backtest-caliber-authority.md`(76 chars):锚点数字(161.63%/K 档/±0.1% 闸)从注入层下移;主题文件在,且 CLAUDE.md §5.4③ 本就要求「派单钉基准」,影响可控
3. 操作型细节下移:ssh 用 `-i ~/tdsignal.pem`、自备份路径、设计文档路径等,以前看索引就能直接用,现在需多开一次文件(可接受,但属真实代价)

---

## 5. 瘦身真实代价(不美化)

### ① 状态型事实从「每会话注入层」下移(最值得主控关注)
- `test-baseline-v112-anchor` 移出的 token:`v1.1.7`、`new15`、`NEW14`、`§5.4`、`e222`(tag 片段)
- MEMORY.md 是**唯一 recall 入口(每次会话开头注入)**,故「注入层不含版本号」的实际含义是:**主控/各 agent 每会话默认看不到当前基准是哪一版**,必须主动打开主题文件
- 与 CLAUDE.md §5.4 措辞的漂移:§5.4 ②原文「权威 = memory `test-baseline-v112-anchor`(**每会话注入**,含 v1.1.2 版本链对照/四档口径/复现数字)」——现在每会话注入的只是**指针**,事实在主题文件里
- 风险指向 §5.4④「认知偏离/派单遗漏」病灶(教训 L39:用非基准口径测且未声明)
- **建议(二选一,交主控决策,非本次 FAIL)**:A. 把 `v1.1.7(tag@384005e222)` 塞回索引行(成本约 20 字符);B. 改 CLAUDE.md §5.4 措辞,写明「注入的是指针,派单前必须 Read 主题文件」

### ② 事实型 token 移出注入层的规模
- 降幅 ≥40% 的行:**22 / 132**(16.7%);完全未变的行:24
- 移出事实型 token 的行:**18 行(13.5%)**,含:test-baseline、kelly-backtest-caliber、claude-self-daily-backup、overfit-monitor-design、zcode-standin-handoff、codegraph-eval-conclusions、ssh-cloud-uses-tdsignal-pem、staticdata-old-mirror、r2-large-json-backup、non-isolated-agent-switches-main-branch、backtest-sell-price-source-residual、session-intraday-trade90、daily-brief-deepseek、has-track-caliber-p0-reflection、codex-review-mandatory-post-v116、ai-predict-self-growth-research、main-controller-no-edit、memory-weekly-review
- 全部 18 行的 token 都已在主题文件中找到(§3.3)→ 是「多一跳」而非「丢失」

### ③ 正向副作用(如实报,但确实是收益)
- 被删的 `K=155.42%` 在主题文件里标着「**已作废,仅存档对照**」——删掉反而降低「引用过时锚点数字」的风险
- 被删文本中相当一部分是标题同义复述(如「已加标记」「按直连实测定,不拍固定档」),属 §5.3 界定的冗余外层
- 索引总量:20276 chars → 15623 chars(−22.9%);非空行文本 20139 → 15489 chars(−23.1%);行数、行序、分组结构零变化

### ④ 召回结构未动(§5.3 ②可逆的前提)
- 主题文件**一个未动**(只改索引层)
- 行序逐位一致、24 组多链接分组未拆、链接集合完全相同 → 纯「同一结构下的文字压缩」,不是重构

---

## 6. 必核 5:可逆性

**原始命令**
```bash
md5 <新> <备份1> <备份2>
python3 -c "..."   # bytes/chars/lines
```

**实测数字**

| 文件 | bytes | chars | 行数 | md5 |
|---|---|---|---|---|
| 新(现 MEMORY.md) | 23506 | 15623 | 135 | `b099793e1c4a4074de6734832e1ea493` |
| `/tmp/MEMORY.md.bak-20261001` | 32444 | 20276 | 138 | `b2f4727bbf66ea83e21af27918a1c736` |
| `…/backups/memory-index-20261001/MEMORY.md.pre-compact-20261001` | 32444 | 20276 | 138 | `b2f4727bbf66ea83e21af27918a1c736` |

- **两份备份内容一致**(md5 相同)→ 备份可信
- 备注:派单里写的「15.26KB」实为 **chars 数**(15623),按字节是 23506 B = 22.96 KiB;同理旧文件 20276 chars = 32444 B = 31.68 KiB。数字口径差异不影响结论

**还原命令(给出但本次未执行)**
```bash
cp /Users/linhuichen/.claude/backups/memory-index-20261001/MEMORY.md.pre-compact-20261001 \
   /Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md
# 校验:md5 应 == b2f4727bbf66ea83e21af27918a1c736;chars 应 == 20276
# 临时备份同样可用:cp /tmp/MEMORY.md.bak-20261001 <同上目标路径>
```
本次复核**全程只读**:未改 MEMORY.md、未改任何 memory 目录文件、未执行还原、未 commit。

---

## 7. 复现段(一键复跑)

```bash
MEM=/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md
BAK=/tmp/MEMORY.md.bak-20261001
BK2=/Users/linhuichen/.claude/backups/memory-index-20261001/MEMORY.md.pre-compact-20261001

md5 "$MEM" "$BAK" "$BK2"; wc -c "$MEM" "$BAK" "$BK2"

python3 - <<'PY'
import re, os
MEM='/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md'
BAK='/tmp/MEMORY.md.bak-20261001'
DIR=os.path.dirname(MEM)
pat=re.compile(r'\[[^\]]+\]\(([^)\s]+\.md)\)')
L=lambda p: pat.findall(open(p,encoding='utf-8').read())
so,sn=set(L(BAK)),set(L(MEM))
files={f for f in os.listdir(DIR) if f.endswith('.md')}
print("old/new 链接:",len(L(BAK)),len(L(MEM)),"| 丢失",sorted(so-sn),"| 新增",sorted(sn-so))
print("新死链",sorted(x for x in sn if x not in files))
orph=sorted(f for f in files if f!='MEMORY.md' and f not in sn)
print("孤儿数",len(orph),orph)
PY
```
预期输出:两备份 md5 相同;`old/new 链接: 207 207 | 丢失 [] | 新增 []`;`新死链 []`;`孤儿数 15`(即 2026-09-27 审计的甲类 15 条)。

---

## 8. 低分项说明(§10.2 口径)

进正式报告的 finding:`caveat 3 条`(§5)。**<80 分低分项已滤:0 条**——本次为文件级机检 + 逐条人工核实,所有结论均带命令与实测数字,无「未验证的猜测」类条目。

---

## 9. 复核后处置(主控 2026-10-01 11:2x 补记)

**caveat ① 已采纳处置方案的「a」——把关键常数塞回注入层**,不做 CLAUDE.md §5.4 措辞修改(改动面更小、无跨文件影响)。共补 3 行,`+143 chars`:

| 索引行 | 补回内容 |
|---|---|
| `test-baseline-v112-anchor` | `基准=v1.1.7(tag@384005e222,默认S06动态a9/new15按日切,快照单源禁自算),测静态须声明非基准` |
| `kelly-backtest-caliber-authority` | `锚点all A=161.63%/K=155.42%,复刻必先复现锚点±0.1%` |
| `kelly-return-caliber-peak-holding` | `权威口径=return_pct_max_holding(总盈亏/峰值占用资金)` |

选这三条的理由:都是 §5.4/§5.5 明文要求「每会话注入」的**基准/口径常数**,属「派单前不 Read 主题文件也必须看得见」的信息;其余 caveat ② 的 15 行事实型下移(ssh `-i`、文档路径等)触发词清晰、多一跳可接受,维持下移不动。

**处置后复检(2026-10-01 11:24 实测)**:`15766 chars / 15.40KB`,链接 `207/207`,丢失 0 / 新增 0 / 死链 0 / 孤儿 15 —— 与处置前一致,仍在 17.1KB 线下(余量 1744 字符)。

**caveat ② ③ 处置**:② 接受(多一跳非丢失);③ 正向副作用(清掉一个已作废数字)无需动作。
