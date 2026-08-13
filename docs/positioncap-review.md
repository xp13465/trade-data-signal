# positionCap 仓位控制过滤 + 每日资金池等分 — 独立 reviewer 回归验收报告

- 验收对象: commit `f9d06186c` (feat/daily-brief-backend 分支)
- Reviewer: 独立 reviewer agent (只读批判性查问题, 不改代码)
- 基线: `f9d06186c^`
- 日期: 2026-08-12
- 结论: **FAIL** — 2 个 P1 需修后方可 merge main (见下)

## 已验证 OK 项

| # | 项 | 证据 |
|---|---|---|
| 1 | 0\|\|3 陷阱修复完整 | lab.js:7529-7536 + app.js:1805-1810 均用 hasOwnProperty 判定; 全库无残留 `\|\|3`/`\|\|9` rank 兜底 |
| 2 | 资金池等分计算正确 | node 隔离测试 6 用例全 PASS(单信号=10000/2信号各5000/K 档取舍/跨日分组/rank0 优先/去重) |
| 3 | 9 模式共享基笔池+跨模式去重 | `_kellyCollectBasePool` baseKey 去重, quadsAll=rating_high+mid+low 并集与池口径一致, countByDate 全局一致(卡间 §22) |
| 4 | 金额加权统计(fixed 退化旧行为) | `_kellyComputeStats`/`_kellyMaxDrawdown`/`holdingCapital` 均 `(amount\|\|buyAmount)`; fixed 时 amount=buyAmount 逐位退化 |
| 5 | 费率重算缓存按 amt 失效 | lab.js:7763/7791 `c.amt !== amt` 正确覆盖 countByDate 变化 |
| 6 | 交易记录弹窗 refactor | fIdx 从扩展字段重建, amount 列/排序正确; 分页/筛选逻辑未破坏; 唯一遗漏=空态 colspan |
| 7 | 交易页联动 | `_posCapKeptSet.has(it)` 同引用(Set 存 windowedItems 内对象), 排序口径与回测一致(评分源同 signal_stats 10d score, 阈值 0.75/0.55 同后端) |
| 8 | localStorage tds_poscap 双页读写 schema 一致 | lab 写 `{on,k}` / app 读 `{on,k}` 同 key |
| 9 | 默认态 | K=2 默认、资金池等分默认、renderSigKellyLab 从共享设置覆盖, 均生效 |
| 10 | 语法/构建 | node --check lab.js/app.js/purpose-notes.js 全过; min 产物含新字符串; sw.js CACHE_VERSION a145; index.html 版本号已换; README §23.1 已补 |

## 问题清单

### P1-1 [lab.js:7746] 逐桶缓存复用未校验 amountMode —— "每笔固定1万"显示资金池等分结果
- **现象**: `_kellyBucketStatsCache` 缓存写入了 `amountMode` 字段(7776)但复用条件(7746)从不比较它。默认=pool 模式先跑一遍 → 各桶缓存被 pool 结果覆盖; 用户点「1:每笔固定1万」→ 外层 cacheKey(feeSig|fixed|F ≠ feeSig|pool|F)触发全量重算, 但逐桶 `amountMode==="fixed" && feeSig 同 && toggled 同` → **直接复用 pool 模式的 stats**。
- **触发路径**: 任何用户在默认 pool 态下点「每笔固定1万」即命中(几乎必现)。`_kellyOnFilterChange`/`_kellyRunRecompute` 不清 `_kellyBucketStatsCache`(仅在 trades.json 重载时清), 无可抵减因素。
- **影响**: 「每笔固定1万(旧口径对比)」按钮显示的是资金池等分数据 → A/B 口径对比功能核心失效且误导(用户以为看到旧口径数据)。且同屏不一致: 16 卡显示 pool stats(错), 「最后结果」按年表走独立重算路径显示正确 fixed stats。
- **修法**: 复用条件加 `&& cachedBucket.amountMode === amountMode`(字段已存未用, 典型 dead-field)。

### P1-2 [lab.js:8507 静态组合建议 vs 新默认口径] §22 同屏数据不一致
- **现象**: `_kellyComboAdviceHtml` 为静态面板, 数字(4 组合全开 净+10,867,390 元 / 峰值收益率 30.74% / 按年 2026 +1,087万)来自 docs/kelly-combo-usage-advice.md 的 Python 管线, **在旧「每笔固定1万」口径下计算**。本次 commit 将默认口径改为「每日资金池等分」后, 同屏实时「全信号表/16 卡」按 pool 口径(绝对净利量级小一个数量级, 如 commit 自报 K=1 净利仅 +78.7 万)。
- **影响**: 用户在同一屏看到「组合使用建议 净+1,087万」与「全信号表 pool 口径 净利 ~+几百万」两个量级矛盾的数字; 且建议面板自称"下方「最后结果」全信号表即按总建议口径实时计算"(8535), 默认 pool 下已不成立 → §22 数据一致性铁律违反。
- **修法**: 建议面板标注「口径=每笔固定1万(旧口径, 静态)」, 或在 pool 默认下重算/联动; 至少消除"实时同口径"的误导性表述。

### P2-1 [purpose-notes.js 费率口径] §21 公示残留旧口径文案
- 「费率口径: 买入 1 万元/笔, 默认含券商佣金...」仍按旧每笔1万表述, 与新默认「每日资金池等分」矛盾(下方新增「金额口径」段已澄清, 但两段并列自相矛盾)。建议把费率口径改为「买入金额=每日资金池等分(默认), 切换'每笔固定1万'时每笔 1 万」。

### P2-2 [lab.js:9135 `_pcFadePasses`] 弹窗谓词重复且缺 v4 toggle(基线遗留, 本次金额列新暴露)
- `_pcFadePasses` 与共享 `_kellyPassesFadeFilters` 逐条复制的谓词, **漏 v4 组 12 个 toggle**(greedy7/10/15, v4c/v4b/v4d/v4j/v4i/v4f/v4g/v4m/v4k)。基线弹窗本就不含 v4(非本次回归), 但本次新增「每笔金额」列由弹窗 basePool 的 countByDate 派生 → v4 开启 + pool 口径下, 弹窗金额与卡统计分歧; 且复制粘贴谓词有漂移风险。建议改调共享谓词。

### P2-3 [lab.js:9310] 交易记录弹窗空态 colspan=14, 列数现为 15
- 新增 amount 列后「无符合条件的交易记录」行只跨 14/15 列。纯视觉。

### P2-4 [app.js:1798-1814] 交易页 top-K 与回测基笔池粒度差异(展示近似, 非错误)
- app.js 按 (index, signal) 用 top1 ETF 的 track_score 选前 K; 回测池按 (index, etf, signal) 每 etf 各自 track_score。多 ETF 指数或同分场景下两页「建议执行」集合可能不同; 且 buy_special_filtered 预览项 rank=9 不入 K(合理但需知晓)。属展示层近似, 建议在 tooltip 注明"按指数级 top-K 展示"。

## 回归老功能
- 凯利回测 27 toggle/4 组合宏/卖出模式: 过滤谓词未改(降亏逻辑零改动), 仅金额口径/统计加权变化; 默认 pool 属本次有意变更。**注意**: 默认值变更本身会改变用户看到的默认数字(fixed→pool), 需在发布说明中提示。
- 交易记录弹窗: 分页/筛选/排序/字段完整(新增 amount 列), colspan 小瑕疵见 P2-3。
- 交易页信号列表: 未开启 positionCap 时零改动(`_posCapKeptSet` 为 null, 不注入 class/badge)。

## 验收口径总结
- 修 P1-1 与 P1-2 后即可 merge main。P2 建议同批或下批修复, 均不阻塞。
