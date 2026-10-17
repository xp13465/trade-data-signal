> **落档说明**(2026-10-18,收口批):本文为 #266 行业口径核数报告原文(原在 `/tmp/pf-industry-caliber-compare.md`)。
> 生成者:researcher 子 agent(只读);生成时间:2026-10-17;关联上下文:#266 定源依据 / 方案文档见同目录 `pf-screener-plan-v0-20261017.md`。
> 本报告为**数字权威源**(§4 已实测定源=证监会门类 8201/29.0% vs 申万一级 959/3.4%)。正文以下**逐字原样保留**(历史记录不追改,CLAUDE.md §6④)。

# pf-screener 行业口径核数:申万一级 vs 证监会门类(只读核数)

- 日期: 2026-10-17 | 角色: researcher(只读) | 任务书: /tmp/dispatch-pack2-pfscore.md
- 生产权威源: 云上 /home/ubuntu/code/trade-data/data/public_fund.db(mtime 2026-10-17 16:01)+ 云上 static-site/data 产物(sw JSON mtime 10-17 21:10)

## 0. 结论速览(一屏)

| 项 | 证监会门类(现网) | 申万一级(前端 sw 档,重仓股反查) |
|---|---|---|
| 覆盖基金数(生产实测) | **8201** | **959** |
| 占全市场 28235 | **29.0%** | **3.4%**(959/28235) |
| 占旧分母 27758 | 29.5% | 3.45% |
| 维度数 | 75 个行业名(映射 JSON keys;库内原始披露名 115;图表按 IND_MERGE_MAP 合并) | 31 个申万一级(聚合 JSON 含"未分类"共 32 keys) |
| 数据源 | `fund_industry_alloc`(基金季报**直接披露**全仓位行业配置) | `fund_portfolio_hold`(前 10 大重仓股)**反查** `sw_components.json`(5210 成分股,非基金披露) |
| 更新方式 | quarterly/full 定时任务自动跑(trade-public-fund-quarterly.timer 等) | 手动函数 `collect_portfolio_hold`,**仓内+云上 grep 均无调用方、无定时任务** |
| 时序 | 多期(20260331=8116 只 / 20260630=8201 只) | 仅 1 期(20260630),无历史时序(period_count=1) |
| 覆盖口径 | 全仓位 | 仅前 10 大重仓股 ≈ **42.39% 净值**(coverage_pct) |
| 前端基金级下钻 | 有(映射 JSON 内含每只基金 weight_pct/hold_value) | **无**(app.js:22900 / 22913:sw 档点击直接 return,"不支持基金列表下钻") |
| 维护成本 | 低(已自动化) | 高(每期需手动重采;要达 8201 需先扩采+新挂任务) |

**建议定源:证监会门类(fund_industry_alloc 季报口径)作筛选器行业维度**;申万一级保留为详情/行业卡"风格暴露"补充(现状已有),不作为筛选维度。理由见 §3。

## 1. 两口径定义与出处(方案原文)

- 待拍板原文:`/tmp/pf-screener-plan-v0.md:197`——"行业口径: 用现有证监会门类(73 名, 覆盖 8201 只)还是前端已有的申万一级(sw 档, 需核对覆盖面)? 两者语义不同, 需一次定源(§23.13)。"
- 证监会门类 = 基金季报直接披露 → DB 表 `fund_industry_alloc`(建表 `app/collector/public_fund.py:224`;逐只采集 `fetch_fund_industry_alloc` L1287)。
- 申万一级 = 前端"行业配置"卡第四档 'sw':`static-site/app.js:22225-22229`(fetch `public_fund_sw_industry_alloc.json`)+ `app.js:22498`("基于基金前10大重仓股(fund_portfolio_hold)反查申万一级行业(sw_components.json 5210 成分股),非基金直接披露");计算入口 `app/queries.py:2842` → `_compute_sw_industry_alloc`(`app/collector/public_fund.py:4299`)。

## 2. 覆盖核算(生产实测,云上权威源)

### 2.1 证监会门类
- 云上 DB:`SELECT COUNT(DISTINCT fund_code) FROM fund_industry_alloc WHERE report_date='20260630'` = **8201**(行数 62299;另有 20260331=8116 只/69590 行)
- 云上产物 `public_fund_industry_fund_map.json`:75 个行业 keys / 去重后 **8201 只基金**(与 DB 一致)
- 分母:云上 `fund_basic` = **28235**(20261016 口径,与方案一致)

### 2.2 申万一级(反查)
- 云上 DB:`fund_portfolio_hold` 仅 `report_date='20260630'` 一期,`COUNT(DISTINCT fund_code)` = **959**(9557 行)
- 逐只反查命中:用项目自身 `_load_stock_industry_map`(sw_components 5210 码)复算 = **959/959 只均有 ≥1 个申万一级行业**("未分类"仅为未命中股票的残差桶)
- 云上产物 `public_fund_sw_industry_alloc.json`:report_date=20260630 / fund_count=**959** / coverage_pct=**42.39** / period_count=**1** / industries=32(31 行业+未分类)——与 DB 逐位一致
- 旁证(制造业子行业口径,同源):`public_fund_manuf_subind_fund_map.json` = 19 keys / 944 只(云上)

### 2.3 口径差
- 8201 / 959 = **8.55 倍**;两口径基金集合关系:959 只全部来自"有季报行业披露"的 8201 只的子集(重仓股采集清单源= `SELECT DISTINCT fund_code FROM fund_industry_alloc`,public_fund.py:1479-1481)
- 无行业数据基金(证监会口径外):28235-8201 = 20034 只(债基/货基/指数等)——筛选器须显式标注,不隐藏(与方案 §一 一致)

## 3. 建议定源 + 理由

**选证监会门类**:
1. **覆盖广 8.55 倍**:8201 vs 959;申万反查当前只覆盖 3.4% 全市场。
2. **与现有前端一致**:行业卡现有"点行业→基金列表"下钻(每只带 weight_pct/hold_value)就是证监会口径产物,可直接支撑方案二期"第一大配置行业 + 权重阈值"筛选;申万档前端**明确不支持基金下钻**(app.js:22900/22913),要用它得先新造一套基金级映射。
3. **维护轻**:季报口径已挂定时任务自动更新(quarterly/full);申万反查的 `collect_portfolio_hold` 无任何调用方/定时,每期要人工重采。
4. **申万反查固有缺陷**(代码自述 3 硬限制,public_fund.py:4304-4308):反查非披露 / 仅 42.39% 仓位 / 无时序——只适合当"风格暴露"信息差补充,不适合当筛选主口径。
- 附带:若未来要把申万升为筛选维度,前置=扩采(采集清单支持全 8201 只,但需手动跑;限速 0.5s/只 L1457,实跑时长无日志证据,标"取不到")+ 新挂定时任务。

## 4. 方案文档与镜像核对(供反馈主控)

- 方案 §六②表内 "覆盖 8201 只" 与云上一致;但同段"前端行业映射 JSON 覆盖 **8183** 只"与"证监会门类 **73** 名"是**本机镜像旧数**(本机 public_fund.db 9-13: alloc=8183 / 映射 73 keys / 8183 只);云上现网 = **8201 只 / 75 keys**。定源按云上口径写。
- 本机 static-site/data 三个产物同样为旧版(sw JSON 9-13 但数值与云上一致:959/42.39/1)。

## 5. 局限与诚实标注

- 云上 R2 故障(NotEntitled,方案 §六6)期间用户可见 R2/CF 版本可能滞后;本核数按云上 DB + 云上 static-site 源文件口径。
- 20260930(Q3)季报两口径均未入库(alloc max=20260630)——两口径当前都是半年报期数据。
- 959 = 现状实值;扩采后覆盖率未实测(未做,不做断言)。
- 本机镜像数字仅作对照,不作为证据。

## 6. 证据命令(可复核)

- 云上 DB(只读):`python3 -c "sqlite3.connect('file:/home/ubuntu/code/trade-data/data/public_fund.db?mode=ro',uri=True)"` 三查基本=28235 / alloc@20260630=8201 / hold@20260630=959
- 云上产物:读 `~/code/trade-data/static-site/data/public_fund_sw_industry_alloc.json`(959/42.39/1/32)与 `public_fund_industry_fund_map.json`(75 keys/8201 只)
- 反查命中复算:`_load_stock_industry_map()`(sw_map 5210 码)+ hold 逐行 → 959/959
- 调用方核查:`grep -rn collect_portfolio_hold`(仓内仅 def 行+NOTES;云上 trade-data 树 0 命中;crontab 0 命中;systemd timers 无对应 unit)
- 前端约束:`app.js:22225-22229`(sw 档 fetch)、`app.js:22900`/`app.js:22913`(sw 档无下钻)
