# AI 预测四项改进实施说明(R1对账挂载/R2板块自适应带/R3方向押注/R4影子down分支,2026-08-24)

> 实施依据:[ai-predict-shadow-vs-default-hitrate-audit-20260824.md](ai-predict-shadow-vs-default-hitrate-audit-20260824.md)(审计发现)+ 用户 2026-08-24 拍板全做。
> 冻结契约(§23.7):既有 range 展示形态/字段一律不动,全部纯新增;hit 键板块层判定口径变更系用户拍板的算法修正。

## R1 影子对账挂定时(修 0819 起 actual 断档)

**根因**:`scripts/aggregate_shadow.py` 无任何调度挂载(run_daily_brief.sh 全文不调、无独立 launchd 槽位),影子记录 actual 自 0819 起全 null。另有一处配套 bug:原 `_reconcile` 在「下一交易日在 index_daily 有行但 pct 未入库」时也写 `actual`(值全 None),被"已回填幂等跳过"拦住永不重试——断档的隐藏放大器。

**改法**:
- `scripts/run_daily_brief.sh` 尾部(gen 之后、exit 0 前)追加 aggregate_shadow 调用,失败不阻塞主流程(与生成同模式);20:40 时点 T-1 及更早收盘已由 17:50 update_all 采入,输入就绪;每日滚动清账不留断档。不改 StartCalendarInterval,不动 plist。
- `scripts/aggregate_shadow.py::_reconcile` 补 `if pct is None: continue`(不写死值,留待下次补)。

## R2 板块层区间波动率自适应带宽

**根因**:AI 原始窄区间宽≤0.5pp(实际多±0.25pp) vs 申万板块单日常见±2~4%,区间命中数学趋零(20260810-0824 板块层 0/10 全脱靶)。

**新口径**:有效判定带 = 以 AI 预测区间中点为中心、宽 `w = max(median(|pct|, 近N=5个交易日含T) × k=2.0, min_w=0.3pp)`。防前视:median 只用 ≤预测日 T 数据(T 收盘 17:50 入库,20:40 已知)。原始窄区间照旧展示不改,每条 sector_hits 保留 `raw_hit`(旧窄口径对照)+ 新增 `eff_lo/eff_hi/hit`。

**参数定稿(N=5/k=2.0/min_w=0.3)**:校准脚本 [scripts/calibrate_sector_band.py](scripts/calibrate_sector_band.py)(方法A自然覆盖率法:近500交易日×全部申万行业,N∈{5,10,20,30}×k∈{0.5..2.0}×min_w∈{0.3,0.5} 全组合):
- 覆盖率 **59.9%**,落在任务目标域 40-65%(既有区分度又不恒错);
- 极端日(|pct|≥3%)兜住率 **8.7%** 为各候选最高(N 短对波动聚集响应最快);
- 带宽中位 1.71pp;k=2.0 即 ±median 与中位数定义吻合。
- 方法B诚实发现:12 条历史板块预测即使自适应也全脱(AI 方向本身错)——**自适应治幅度病不治方向病**,已写入前端公示。
- 中间层/大盘层未同改(报告标注):中间层同参数覆盖率 59-62% 可改,但属"7全押联合事件"稀释难度语义,改动会变整体难度标尺;大盘 sh 近5日|pct| P50≈0.48 与区间上限 0.5 匹配(脱靶主因方向非带宽)。本次只改板块层。

**实现落点**(单一实现防口径分叉):`scripts/gen_daily_brief.py` 新增常量 `SECTOR_BAND_N/K/MIN_W` + `_sector_adaptive_band()` + `_verify_sector_hits()`;`backfill_hits`(增量)与 `reclassify_all_hits(db_path)`(存量重刷)共用。

## R3 prompt 反转提示 + direction_call 强制二选一

- `REVERSAL_HINT_TEXT`:反转风险提示注入两路 prompt(单模型路+多角色主编路,共用文本常量防分叉),引用三次真实反向案例(20260814 实际+1.41%/20260819 实际+0.24%/20260821 实际-0.59%)+ 自问句"这是独立判断,还是只在重复今天?"。
- `DIRECTION_CALL_TEXT`:新增必填 `direction_call`(up/down 二选一,禁 flat、禁省略),与 range 相互独立,横盘按概率大的一侧押注。
- 解析:`parse_ai_output` 读 `direction_call`,仅 up/down 有效否则 None;产物 meta 新增键 `"direction_call"`;rule/minimal 兜底路径补 `None`、mock 版补 "up"。旧产物缺键前端容错(不渲染该行)。

## R4 影子 _shadow_lean 补 down 分支(公平对照)

重写为对称逻辑:双向因子并存打架→flat;转多无压制→up(L3 压制→flat);**转空→down(L3 同向印证不打折)**;均线多头→弱 up / 均线空头→弱 down;数据缺失→flat。历史已落 up 记录不改写("新记录起生效"边界,0824 及以前如实保留)。

## 配套展示与统计

- stats 每窗口新增子键 `stats["30d"/"90d"].direction = {n, hit, hit_rate}`(只统计 direction_call_hit 非 None 条目);回填链 `backfill_hits` 写 `hit["direction_call_hit"] = (dc == ad)`(ad='flat' 判未中——押方向本就该难;任一缺失 None 不硬判)。
- 前端 app.js:详情块新增「方向押注」行(dc 为 up/down 才渲染);sectorBlock 有 eff 键时显示判定带;统计区新增「方向押注 近30日/近90日」条目;db-stats-how 公示文案同步(§21,唯一公示点,purpose-notes.js/lab.js 经查无此域键)。

## 存量迁移(一次性)

[scripts/migrate_sector_band_reclass.py](scripts/migrate_sector_band_reclass.py):调 `reclassify_all_hits(items, db_path)` 按 R2 新口径重刷历史 sector_hits 并重算 stats,先备份 `.bak-bandreclass-<ts>` 再写回。2026-08-24 已跑 git 树+生产树(trade-data)各一份,两树 md5 一致(`84a2118d...`)。

⚠️ **覆盖源警示(§23.11 排查记录)**:deploy.sh L256 `rsync -a $REPO/static-site/data/ → $GIT_REPO/static-site/data/`(生产树→git 树,保留 mtime)会把 git 树数据产物反覆盖回生产树版;update_all 链内含 deploy 段。故必须**两树同步刷**(本次已做,rsync --checksum 内容一致不再覆盖);R2 线上生效由主控 upload/deploy 链完成(§22 三步之缓存步)。

## 复现

```bash
# 校准(参数 N/k/min_w 依据)
REPO=/Users/linhuichen/code/trade-data python3 docs/ai-predict/scripts/calibrate_sector_band.py
# 存量迁移(git 树 / 生产树)
python3 docs/ai-predict/scripts/migrate_sector_band_reclass.py --tree git
python3 docs/ai-predict/scripts/migrate_sector_band_reclass.py --tree data
# 手动对账验证(R1)
cd /Users/linhuichen/code/trade && REPO=/Users/linhuichen/code/trade-data python3 scripts/aggregate_shadow.py
# 端到端真跑验证(闲时;--notify-dry-run 不发通知不占 dedup)
python3 scripts/gen_daily_brief.py --notify-dry-run --no-upload --no-tts
```

输入依赖:`trade-data/data/sentiment.db`(index_daily sh/sw_* 序列)、`static-site/data/daily_brief_history.json`(两树)、`data/brief_shadow.json`(生产树)。
数据截止:2026-08-24。关键口径一句话:板块判定带=max(median(|日收益|,5日含T)×2, 0.3pp) 以预测中点为中心;direction_call∈{up,down} 与实际方向(|pct|>0.5 才算 up/down)相等判中。

## 自测五项结果(2026-08-24)

1. **对账手动跑回填**:✅ trade-data 树 0820(flat,+0.04)/0821(down,-0.59)回填成功,0824 如实待明日(T+1 未到)。
2. **影子转空 case 出 down**:✅ 八组构造 case 8/8 PASS(纯转空→down/双向打架→flat/L3印证不打折等)。
3. **direction_call 进新产物**:✅ 21 点后真跑端到端(DeepSeek 多角色6角色链),产物 meta.direction_call="down"、history 最新条目同、stats.direction 结构合法(n=0 待积累);老条目无键前端容错。测试后已从备份恢复三份生产产物(保今晚正式版+0824 影子旧记录)。
4. **check_data_integrity**:✅ 33 ok / 0 warn / 0 fail。
5. **node --check**:✅ app.js 四文件语法通过(min 构建+bump 由主控 merge 统一做)。
