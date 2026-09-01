# ai-predict/ AI 预测体系研究库索引

> AI 预测(每日 AI 速递)体系全部研究档案:挖掘/方法论/方案/验证/调研。2026-08-22 作战地图归库从 docs/ 根收容而来(见 [docs/research-index.md](../research-index.md) 总索引)。
> **如何新增**:报告放本目录,配套脚本放对应报告同名目录或 `direction-market-winning-scripts/`,同步更新本索引 + 总索引。

## 报告清单

| 文档 | 说明 | 日期 |
|---|---|---|
| [ai-predict-direction-market-winning-signals-20260820.md](ai-predict-direction-market-winning-signals-20260820.md) | 方向胜率信号挖掘报告——自研 8 年数据挖掘,方向锚信号胜率来源(README 致敬段引用) | 2026-08-20 |
| [ai-predict-director-industry-method-20260820.md](ai-predict-director-industry-method-20260820.md) | 投顾式多因子方向研判:业界方法论调研 | 2026-08-20 |
| [ai-predict-offline-ab-frontvalidate-20260820.md](ai-predict-offline-ab-frontvalidate-20260820.md) | 「方向锚改造」离线回放 A/B 可行性调研(零侵入前验证) | 2026-08-20 |
| [ai-predict-offtrack-rootcause-20260820.md](ai-predict-offtrack-rootcause-20260820.md) | 「越错越离谱」根因调研(AI 预测体系转折点证据) | 2026-08-20 |
| [ai-predict-shadow-validate-20260820.md](ai-predict-shadow-validate-20260820.md) | 影子模式验证契约:方向锚/反思归因 7 天 A/B(用户拍板数据决定开/不开/改) | 2026-08-20 |
| [ai-predict-shadow-vs-default-hitrate-audit-20260824.md](ai-predict-shadow-vs-default-hitrate-audit-20260824.md) | 影子 vs 默认命中率审计(影子0/3结构只出up/flat、默认方向40%严格三层0%、对账断档发现) | 2026-08-24 |
| [ai-predict-four-improvements-20260824.md](ai-predict-four-improvements-20260824.md) | 四项改进实施说明(R1对账挂定时/R2板块自适应带N5k2/R3方向押注direction_call/R4影子down分支)+校准与迁移复现段 | 2026-08-24 |
| [ai-predict-reflection-factor-attribution-20260820.md](ai-predict-reflection-factor-attribution-20260820.md) | 「反思=因子归因回灌」实现说明(TA Reflector 内核) | 2026-08-20 |
| [ai-predict-inject-research.md](ai-predict-inject-research.md) | 注入面调研:已有数据逐项实测 + 注入设计 | 2026-08-16 |
| [ai-predict-news-macro-research-methodology.md](ai-predict-news-macro-research-methodology.md) | 新闻面/宏观事件日历/其他变量面全景调研方法论 | 2026-08 |
| [ai-predict-news-macro-research-sources.md](ai-predict-news-macro-research-sources.md) | 新闻面/宏观事件日历数据源可行性实测 | 2026-08 |
| [ai-predict-self-growth.md](ai-predict-self-growth.md) | 自成长(反思总结)体系方案 | 2026-08-17 实施 |
| [ai-predict-multiagent-plan.md](ai-predict-multiagent-plan.md) | 多角色协作式(辩论)改造方案(TradingAgents 启发) | 2026-08-11 |
| [ai-predict-tts-plan.md](ai-predict-tts-plan.md) | 语音播报(edge-tts)落地调研方案 | 2026-08-16 |
| [daily-brief-research.md](daily-brief-research.md) | 每日专业金融预测总结最初调研(daily_brief 起点) | 2026-08 上旬 |
| [daily-brief-optimization.md](daily-brief-optimization.md) | daily_brief 完善点分析报告 | 2026-08 |
| [ai-predict-backtest-feasibility-20260831.md](ai-predict-backtest-feasibility-20260831.md) | AI 预测回测可行性报告(方向锚全历史回测 5.1 + 穷举子群 5.2;结论:现版对称规则整体无显著方向优势,所有子群无一显著) | 2026-08-31 |

## 配套脚本

- [direction-market-winning-scripts/](direction-market-winning-scripts/) — 方向胜率信号挖掘全套脚本(11 个:`mine_direction_signals.py`/`mine_turnpoint_combo.py`/`mine_combo_matrix.py`/`mine_final_rules.py`/`mine_final_combo.py` 等 + `out/` 挖掘产物 json),复现入口见同目录各脚本头部 docstring。
- [scripts/calibrate_sector_band.py](scripts/calibrate_sector_band.py) — 板块层自适应判定带参数校准(N/k/min_w 全组合自然覆盖率法+历史反事实法,2026-08-24 R2 依据,N=5/k=2.0/min_w=0.3 定稿),复现命令见脚本头。
- [scripts/backtest_direction_anchor.py](scripts/backtest_direction_anchor.py) — 方向锚全历史回测(重放现版 `_compute_direction_anchor`+`_shadow_lean`,支持 `--threshold` 覆盖做敏感度),输出 `scripts/out/direction_anchor_backtest_results*.json`(642 样本),复现见脚本头。
- [scripts/analyze_direction_anchor_52.py](scripts/analyze_direction_anchor_52.py) — 方向锚穷举子群分析(T/role/strength/L 因子/按年分半/阈值敏感度/前向样本外/三方在线对照,读 detail JSON 轻量重分析),输出 `scripts/out/direction_anchor_backtest_52.json`,复现见脚本头。
- [scripts/migrate_sector_band_reclass.py](scripts/migrate_sector_band_reclass.py) — R2 存量迁移:按新口径重刷 history 历史条目 sector_hits(--tree git/data 两树,备份后写回)。
- [scripts/dbbrief_interaction_smoke.sh](scripts/dbbrief_interaction_smoke.sh) — AI 预测板块交互冒烟三件套(+同目录 `dbbrief_interaction_smoke.js` 断言脚本 / `dbbrief_smoke_harness.html` 离线 harness):方向红涨绿跌分色、点击区域收敛、反思校准连坐修复的 playwright chromium 20 断言自测(2026-08-27 fix(dbbrief) 配套),复现:`bash docs/ai-predict/scripts/dbbrief_interaction_smoke.sh <static-site目录> <主仓data目录>`。

## 活文档例外(留 docs/ 根,勿搬)

- `docs/ai-predict-shadow-track.md` — 影子追踪总表,**自动生成活产物**(`scripts/shadow_track_md.py` L24 TRACK_MD 硬编码写目标),手改会被覆盖。
- `docs/ai-predict-self-upgrade-roadmap.md` — 自升级路线图,主控迭代驱动持续更新中的活文档。
- `docs/daily-brief-range-prediction-spec.md` — 区间预测实施规格(`gen_daily_brief.py` 实施验收依据的活规格)。

> 关联:`scripts/gen_daily_brief.py`(生产代码)注释中 6 处指向本库文档;影子验证链路 `scripts/aggregate_shadow.py` + `scripts/shadow_track_md.py`;README「每日 AI 速递」展示链接 L91/L226/L235/L239 已同步本库路径。
