# 作战地图归库方案(历史挖掘/回测/调研报告整理到一处)

> 产出:researcher 只读盘点+方案(2026-08-22)。**本方案不含任何文件移动**,执行由后续 implementer 派单。
> 约束遵守:二轮挖掘 researcher 正在写 `docs/kelly/analysis/`(method-survey-loss-filter-20260822.md + sim_window_loss_mining_20260822/mine10_*/r2_common.py 等),本方案对该目录零改动。

---

## 一、盘点结论(总数+分类)

全站"作战地图"(含回测数据/挖掘结论/方法论论证的研究报告)分布:

| 区域 | 报告 md | 脚本 | 数据 json | 归位状态 |
|---|---|---|---|---|
| docs/kelly/ 全树(6 子目录) | 84 | 88(py/js) | ~14 | **已归位**(总索引+各子目录 README 齐) |
| docs/market-state/(四档研判专题库) | 12 | 22 | 7 | **已归位**(README 索引完整) |
| docs/trade-sim/(模拟回测) | 2 | 0 | 0 | **已归位**(有 README) |
| docs/qvix-rv/(波动率自算) | 1 | 1 | 2 | **已归位**(有 README) |
| docs/archive/(48 文件) | 回测系列约 30(01-26 编号买卖点回测+walk-forward×5 等) | - | - | 已归档但**无索引 README** |
| docs/ 根散落 | 18 | 配套 scripts 目录×1(11 脚本) | 0 | **散乱待归位**(本方案主体) |
| 仓库根目录 | 1(08-买卖点策略深度回测.md,untracked) | - | - | **散落待归位** |

data/ 下挖掘产物(signal_kelly_backtest.json/.gz、signal_kelly_trades.json/.gz、signal_kelly_etf_freeze.json、signal_stats.db 等)**全部 untracked**(符合 §8「不 add 根目录 data/」;tracked 的仅 index_etf_map.json / stock_codes.json 两个生产配置)。它们是回测输入数据非文档,**不动**。

### 散件 19 个明细(docs/ 根 18 + 根目录 1)

性质分类:A=AI预测验证/方法论 B=daily_brief 调研 C=数据源穷举实测 D=历史回测刷新版

| # | 文件 | 性质 | tracked? | 建议归处 |
|---|---|---|---|---|
| 1 | ai-predict-direction-market-winning-signals-20260820.md | A 方向胜率信号挖掘(8年数据挖掘,README 致敬段引用) | untracked | docs/ai-predict/ |
| 2 | ai-predict-direction-market-winning-signals-20260820/scripts/(11 脚本) | A 配套挖掘脚本 | untracked | 随 #1 |
| 3 | ai-predict-director-industry-method-20260820.md | A 业界方法论调研 | untracked | docs/ai-predict/ |
| 4 | ai-predict-offline-ab-frontvalidate-20260820.md | A 离线 A/B 前验证 | untracked | docs/ai-predict/ |
| 5 | ai-predict-offtrack-rootcause-20260820.md | A 「越错越离谱」根因(AI预测体系转折点证据,非纯线上bug) | untracked | docs/ai-predict/ |
| 6 | ai-predict-shadow-validate-20260820.md | A 影子模式验证契约 | tracked | docs/ai-predict/(需同步引用,见 §四) |
| 7 | ai-predict-reflection-factor-attribution-20260820.md | A 反思因子归因实现说明 | tracked | docs/ai-predict/ |
| 8 | ai-predict-inject-research.md | A 注入面实测调研 | tracked | docs/ai-predict/ |
| 9 | ai-predict-news-macro-research-methodology.md | A 新闻/宏观面方法论 | tracked | docs/ai-predict/ |
| 10 | ai-predict-news-macro-research-sources.md | A 数据源可行性实测 | tracked | docs/ai-predict/ |
| 11 | ai-predict-self-growth.md | A 自成长体系方案 | tracked | docs/ai-predict/ |
| 12 | ai-predict-multiagent-plan.md | A 多角色辩论改造方案 | tracked | docs/ai-predict/ |
| 13 | ai-predict-tts-plan.md | A TTS 落地调研 | tracked | docs/ai-predict/ |
| 14 | daily-brief-research.md | B 每日AI预测最初调研 | tracked | docs/ai-predict/ |
| 15 | daily-brief-optimization.md | B 完善点分析 | tracked | docs/ai-predict/ |
| 16 | qvix-data-sources.md | C QVIX 免费异源穷举(**README L145 QVIX 算法公示位引用**) | tracked | docs/qvix-rv/(算法公示与算法专题库同处) |
| 17 | global-ticker-free-source-research.md | C 全球行情免费源穷举(README L80 引用,该功能唯一数据层文档) | tracked | **留原处**(仅入总索引;无对应专题库,单文件不值得建库) |
| 18 | 08-买卖点策略深度回测.md(仓库根,untracked,454行,数据截止2026-08-21) | D 买卖点回测系列最新刷新版(NOTES L5208:stash 恢复产物) | untracked | docs/archive/(随 01-26 系列;命名 08-...-2026-08-21.md 与旧版区分) |

### 活文档例外(留原处,仅入总索引,不搬)

| 文件 | 不搬理由(证据) |
|---|---|
| ai-predict-self-upgrade-roadmap.md | 活路线图(主控迭代驱动文档,AI预测自升级轮次持续更新中) |
| ai-predict-shadow-track.md | **自动生成活产物**:scripts/shadow_track_md.py L24 `TRACK_MD = "docs/ai-predict-shadow-track.md"` 硬编码写目标;影子验证期进行中(当前 git M 状态);aggregate_shadow.py L33/L205、gen_daily_brief.py L3839 三处活代码引用 |
| daily-brief-range-prediction-spec.md | 唯一实施规格(gen_daily_brief.py 引用,news-macro-methodology 反向引用它),实施验收依据 |

---

## 二、目标结构推荐

### 候选对比
- **候选 A(升级 docs/kelly/analysis/ 为总库)= 否决**:①analysis/ 是 kelly 的一个主题子目录("凯利分析类"),升总库则 mining/combo/position/toggle/backtest-ai 兄弟目录层级倒挂;②二轮挖掘 researcher 正在该目录写文件,执行期物理冲突;③kelly 树内 15 处硬编码路径(kelly_reports_html.py 10 处/md_to_html.py 5 处)全部指向 kelly 内部现有位置,塞外部报告进去反而破坏内聚。
- **候选 B(新建专用目录)= 采纳,改良为"专题库自治 + 单一总索引"形态**:
  - kelly/market-state/trade-sim/qvix-rv/archive 五个已归位专题库**原地不动**(§23.5 已归类不折腾;移动风险最小:kelly_reports_html.py/md_to_html.py/app.js L2252 注释/queries.py L489,L766 注释/memory 11 处引用全不用改);
  - 新建 `docs/ai-predict/` 专题库收容 AI 预测体系研究 15 个(#1-#15,含 daily_brief 调研 2 个——同一主题),建 README 索引;
  - qvix-data-sources.md 归位 docs/qvix-rv/;
  - 08-买卖点刷新版归位 docs/archive/;
  - **新建 `docs/research-index.md` 作战地图总索引**,以链接段收录全部 6 库+独立报告,达成用户"一处存放"诉求(单一入口),物理上不破坏已有咬合。

一句话理由:散件归位到对应专题库(塞入即归类)+ 一张总索引串全站(一处可查),比物理合并大树少动 ~180 个文件、少断 ~40 处引用,风险最小且完全满足"避免散乱"的原始痛点。

### 目标结构图
```
docs/
├── research-index.md          ★新建:作战地图总索引(唯一入口速查表)
├── ai-predict/                ★新建:AI预测体系研究库(15 md + scripts/)
│   ├── README.md              (索引)
│   ├── *.md ×15               (自 docs/ 根 git mv/add)
│   └── direction-market-winning-scripts/ (11 挖掘脚本,自同名目录 mv)
├── qvix-rv/                   (+qvix-data-sources.md 归入)
├── kelly/                     (不动)
├── market-state/              (不动)
├── trade-sim/                 (不动)
└── archive/                   (+08-买卖点...-2026-08-21.md 入库)
```

---

## 三、总索引设计(docs/research-index.md)

速查表字段:**主题 | 性质(一轮挖掘/历史回测/AI预测验证/方法论/数据源穷举) | 结论一句话 | 日期 | 报告路径 | 脚本路径 | 复现锚点**

分段结构(每段一张表):
1. 凯利仓位与降亏(docs/kelly/:mining/combo/position/analysis/backtest-ai/toggle 六段或按子目录小节,链接到各子目录 README,总索引只收"里程碑级"条目:v1.0.0→v1.1.4 版本链对应的定版报告)
2. 大盘四档研判(docs/market-state/,7 报告+复现脚本)
3. AI 预测体系(docs/ai-predict/,新库)
4. 模拟回测(docs/trade-sim/)与波动率(docs/qvix-rv/)
5. 历史买卖点回测系列(docs/archive/ 01-26 编号+walk-forward×5,补一段轻量列表)
6. 数据源穷举调研(global-ticker-free-source-research.md 等)
7. 独立活文档段(shadow-track/self-upgrade-roadmap/range-spec,标注"活文档勿搬")

索引头部注明维护规则(§23.5:新增作战地图即追加一行,不攒)。

---

## 四、执行清单(供 implementer 用)

### 4.1 git 操作(git mv 保历史;untracked 直接 add)
```
# 新建目录
mkdir docs/ai-predict

# untracked 直接入库(git add,mv 由 add 后删除原位完成;无历史可保)
git add docs/ai-predict-direction-market-winning-signals-20260820.md   → 移至 docs/ai-predict/
git add "docs/ai-predict-direction-market-winning-signals-20260820/scripts" → 移至 docs/ai-predict/direction-market-winning-scripts/
git add docs/ai-predict-director-industry-method-20260820.md           → docs/ai-predict/
git add docs/ai-predict-offline-ab-frontvalidate-20260820.md           → docs/ai-predict/
git add docs/ai-predict-offtrack-rootcause-20260820.md                 → docs/ai-predict/

# tracked 用 git mv(保历史)
git mv docs/ai-predict-shadow-validate-20260820.md            docs/ai-predict/
git mv docs/ai-predict-reflection-factor-attribution-20260820.md docs/ai-predict/
git mv docs/ai-predict-inject-research.md                     docs/ai-predict/
git mv docs/ai-predict-news-macro-research-methodology.md     docs/ai-predict/
git mv docs/ai-predict-news-macro-research-sources.md         docs/ai-predict/
git mv docs/ai-predict-self-growth.md                         docs/ai-predict/
git mv docs/ai-predict-multiagent-plan.md                     docs/ai-predict/
git mv docs/ai-predict-tts-plan.md                            docs/ai-predict/
git mv docs/daily-brief-research.md                           docs/ai-predict/
git mv docs/daily-brief-optimization.md                       docs/ai-predict/
git mv docs/qvix-data-sources.md                              docs/qvix-rv/

# 根目录回测刷新版入库(带数据截止日期后缀,与 archive 既有同名旧版<07-10 数据>区分)
git add "08-买卖点策略深度回测.md" → 移至 "docs/archive/08-买卖点策略深度回测-2026-08-21.md"
```
共 **16 个 mv/add 条目**(13 md tracked mv + 3 untracked md add + 1 scripts 目录 add + 1 根目录报告改名入库;其中 scripts 目录算 1 条)。

### 4.2 同步建索引(2 新 1 补)
- 新建 `docs/ai-predict/README.md`(15 行条目表,格式仿 docs/kelly/backtest-ai/README.md)
- 新建 `docs/research-index.md`(§三设计)
- 补 `docs/archive/README.md` 轻量索引(可选增强:01-26 系列+walk-forward 一句话清单;archive 现 48 文件无索引)
- 更新 `docs/qvix-rv/README.md`(+qvix-data-sources.md 一行)
- kelly 各 README 不动(kelly 树零改动)

### 4.3 引用同步(grep 已核实,逐处 sed 改指向)
**活代码注释/字符串(不改不断功能,但断追溯):**
| 位置 | 引用目标 | 动作 |
|---|---|---|
| scripts/gen_daily_brief.py L218 | docs/ai-predict-direction-market-winning-signals-20260820.md | 注释路径更新 |
| scripts/gen_daily_brief.py L579/L1192 | ai-predict-inject-research.md | 同上 |
| scripts/gen_daily_brief.py L1810 | docs/ai-predict-multiagent-plan.md | 同上 |
| scripts/gen_daily_brief.py L2135 | docs/ai-predict-self-growth.md | 同上 |
| scripts/gen_daily_brief.py L2743 | docs/ai-predict-tts-plan.md | 同上 |
| scripts/shadow_track_md.py L31(渲染文本) | docs/ai-predict-shadow-validate-20260820.md | 字符串更新(注意:此文本会渲染进 shadow-track.md 表头,改后下次聚合自动刷新) |

**README 展示链接(不改=在线 README 断链,P0 必改):**
| README.md 行 | 引用目标 |
|---|---|
| L80 | docs/global-ticker-free-source-research.md(留原处,无需改) |
| L91 | docs/daily-brief-research.md + docs/ai-predict-self-growth.md + docs/ai-predict-inject-research.md(3 链接改 docs/ai-predict/) |
| L145 | docs/qvix-data-sources.md(QVIX 公示位,改 docs/qvix-rv/qvix-data-sources.md) |
| L226 | docs/ai-predict-direction-market-winning-signals-20260820.md |
| L235 | docs/ai-predict-shadow-validate-20260820.md |
| L239 | docs/ai-predict-tts-plan.md |

**文档索引类(低优先但建议同步):**
- docs/tasks-done-list.md L131(direction-market-winning)/L134(shadow-validate)等历史完成记录中的相对链接
- TASKS.md 中 grep `docs/ai-predict|daily-brief-research|qvix-data-sources` 命中处(执行时现场 grep 全量核对)
- memory 侧 MEMORY.md 无 ai-predict 散件路径引用(已核,11 处均为 docs/kelly|market-state,不受影响)

### 4.4 风险标注
1. **严禁触碰 docs/kelly/analysis/**:二轮挖掘 researcher 在写(method-survey-loss-filter-20260822.md/sim_window_loss_mining_20260822/mine10_features.py/progress_round2.md/r2_common.py 均为本日新增)。本方案 kelly 树零改动,天然规避。
2. **ai-predict-shadow-track.md 不搬**(硬编码活产物,见 §一例外表);若未来坚持要搬,必须同步 scripts/shadow_track_md.py L24 TRACK_MD 常量+验证一次聚合运行,建议留原处。
3. **self-upgrade-roadmap.md / range-prediction-spec.md 留原处**(活路线图/活规格,主控与 gen_daily_brief 实施依据在用)。
4. untracked 文件无 git 历史,add 即可不存在"丢历史"问题;tracked 全部走 git mv,`git log --follow` 可溯。
5. README L145 是 §21 公示位(QVIX 算法公示),mv 后必须当轮同步改链接并 curl 线上验(若同轮上线),防公示断链。
6. 执行窗口避开盘后定时任务时点(§14);纯 docs 移动+README 改,无前端源码变更,**不需要 bump 版本串/重建 min**(不触发 §24;README.md 非 App Shell 成员)。
7. archive 里已有 `08-买卖点策略深度回测.md`(454 行,07-10 数据)与 `-2026-08-14.md`(462 行)两个版本,新版入库必须带日期后缀三者并存,不得覆盖(NOTES L2385 记录了旧版归档史)。

---

## 五、明确排除项(不算作战地图,留原处)

判定标准:含回测数据/挖掘结论/方法论论证的才算;以下各类排除+理由:

| 类别 | 文件 | 排除理由 |
|---|---|---|
| 纯 bug 根因/事故复盘 | conflict-overwrite-rootcause/triggers-2026-08-18、rootcause-home-news-fade-20260819、rootcause-marquee-min-missing-20260819、homepage-sentiment-anchor-rootfix、build-news-rootfix-20260820、nt-date-semantic-fix、trade-sim-negative-cagr-fix、feishu-hook-stall-diagnosis、ab-refactor-bug-reflection、lite-svg-corner-vertex-a320-final/investigation、lite-svg-grad-calibration、lite-svg-grad-id-collision、overfit-monitor-roll-sample-investigation | 工程故障排查非交易研究,任务明确排除;留 docs/ 根与其修复 commit 天然咬合 |
| reviewer 审查报告 | home-svg-fix-review/-fix2、home-svg-lite-fidelity-check、anti-conflict-mech-ab-e-review、overfit-multirock-review、review/ 目录 | 验收记录非研究报告 |
| 会话移交/状态 | session-handoff-20260814/16、session-state-20260815、closeout-20260818-v112 | 会话恢复用,时效性产物 |
| 任务治理 | tasks-* 5 个、todolist-cleanup-20260822、tasks-done-list(活索引)、tasks-archive-maintain | TASKS 治理链路文档(§23.12) |
| 操作手册/规范/部署 | main-governance、agent-quickstart、smoke-checklist、data-deploy-quickstart、site-deployment、r2-deployment、backup-restore、restore-db、data-dictionary、data-sources、PARAMS、PRD、LICENSE-data、api-data-query、data-pack、理财专员使用指南、72h-monitor-plan、monitor/、ops/ | 运维手册非研究 |
| 功能方案/实施报告 | chart-refactor-config-plan、chart-p2p3-data-source-research、p2-11-dapan-lazy-plan、perf-p1-plan、industry-grid-lazy-20260822、home-helpbtn-independent、readme-naming-ogplan、feishu-bot-integration-plan、bak-active-domain-strategy、staticdata-daily-brief-sync、subscribe-push-gap-research-20260822、intraday-self-heal-plan、alert-design、explain-1to1-inventory、claude-md-slim-a1-5point4-plan、optimization-closeout-list/blueprint/decision-checklist/followup-inspection、uumit 系列 4 个、uumit-knowledge/、feedxml-architecture-review、role-based-context-research、daily-brief-range-prediction-spec(活规格)、r2-track-score-consistency-audit、r2-upload-repo-guard-plan-20260822、scripts/(SVG 几何验证脚本)、thinking-off-opencodego-research-20260821 | 产品/工程功能方案与工程效能研究(parallel-cost-benefit、context-optimization、thinking-off-optimization、token-cache-hit-stats、update-all-88min-analysis 同此类),非交易作战地图;如用户认为工程效能调研也要归库,可二期另议(本方案只定交易研究范围) |
| 边界说明 | signal-finalize-time.md(README L86 公示引用,事实查证)、global-ticker-free-source-research.md(C 类但作功能数据层公示文档) | 前者非研究;后者是作战地图性质但被 README 在线体验段作为该功能唯一数据层文档引用,搬动收益<断链成本,留原处入总索引 |

---

## 复现

- 盘点命令(全量复核):
  - `ls docs/*.md | wc -l`(106)
  - `find docs/kelly -name "*.md" | wc -l`(84)/ `find docs/kelly \( -name "*.py" -o -name "*.js" \) ! -path "*__pycache__*" | wc -l`(88)
  - `ls docs/archive/ | wc -l`(48,无 README)
  - `git status --porcelain | grep '^??'`(散件 untracked 清单)
  - `git ls-files data/`(仅 index_etf_map.json/stock_codes.json tracked)
- 引用核实命令:`grep -rn "docs/ai-predict\|daily-brief-research\|qvix-data-sources\|08-买卖点" scripts/ README.md TASKS.md docs/tasks-done-list.md CLAUDE.md`;`grep -rn "docs/kelly" scripts/*.py static-site/app.js app/queries.py`(kelly 树不动的依据)
- 数据截止:2026-08-22;关键口径:作战地图=含回测数据/挖掘结论/方法论论证的交易研究报告;工程效能/bug复盘/操作手册不在范围内
