# #11 场外基金净值走势全链 + fund_basic 双 bug 修复 · 实施报告

> 分支 `worktree-agent-ac91bcad82e3eef62`(基于 origin/main 7637959fb,base-fresh 已验)
> commit:**1fd48540e**(批次1 双 bug 修)+ **a4fc234d4**(批次2 净值走势全链)
> 数据截止:2026-08-25(fund_daily_nav 最新净值日 20260824;000001 样本最新有效净值 20260819)

## 一、批次1:fund_basic 双 bug(C 级修 bug,§23.2 三铁律自验)

### bug① fetch_fund_name REPLACE 清扩展列
- **根因**:`app/collector/public_fund.py` 原 L612 用 `INSERT OR REPLACE INTO fund_basic (...6列...)`,SQLite REPLACE=删整行重插,每日日更把 Fetcher N(`fetch_fund_overview`)补的 15 扩展列(fund_company/fund_manager/setup_date/scale/management_fee/custody_fee/purchase_fee/custodian/strategy/benchmark/tracking_target/issue_date/share_scale/service_fee/dividend_total,列名经 PRAGMA table_info 实证)清成 NULL。实测生产库 27624 行中扩展列非空仅 18。
- **修法**:改 `INSERT ... ON CONFLICT(fund_code) DO UPDATE SET`(仅更新基础 6 列),新基金正常插入(扩展列 NULL 待 N 补),老基金扩展列保留。

### bug② stage0 假断点 done=27600 永不补列
- **根因链**(日志实证 `data/logs/stage0-overview.log` 2026-08-23 周日 02:18:`ok=27600 fail=0 耗时=57s`,逐只接口+0.4s throttle 不可能):断点 done 只记「曾尝试成功」,感知不到「数据后来被清」(bug① 每日清列)→ done 全命中跳过 → 假完成标记永不补列。
- **修法三件**:
  1. 加载闸门 `_prune_stage0_done_vs_db`:断点 done 与 DB 实际有值 code 集取交集(`_STAGE0_DB_VALIDITY` 四分区映射:fund_overview/fund_fee_detail/fund_manager/fund_risk_indicator),裁剪打印 WARN,失效部分自动重采;
  2. 收尾一致性自检:`fetch_fund_overview` 结束核对「done 数 vs DB 扩展列有值数」,偏差超阈值打 WARN;
  3. 已删 `/tmp/pf-stage0-collect-progress.json` 的 fund_overview 假分区(备份 `.bak-fake-done-20260825`;其余 fee_detail/risk/manager/nav 分区与 DB 核实一致,保留)。
- **数据恢复路径**:下个周日(2026-08-31)02:17 launchd `com.trade.pf-stage0-overview` 自动真采全量(~6.2h);如需提前可手动 `bash scripts/stage0_overview.sh`(凌晨窗口跑,主控拍板)。

### §23.2① 同类错误面清单(机检+人工核)
| 位置 | 结论 | 依据 |
|---|---|---|
| public_fund.py 全部 16 处 INSERT OR REPLACE | 仅 fund_basic 未覆盖全表列,其余均全列写入无副作用 | 机检脚本比 INSERT 列集 vs PRAGMA table_info |
| compute/futures_position.py:505(REPLACE 5 列 vs 表 12 列) | **排除**:写 variety='综合' 合成行,主键 (date,variety,role) 与 collector 真实品种行不同,不互清 | 读源码 L483-513 |
| sentiment.db 域 score_daily/signal_daily/futures_position/daily_metric/intraday_amount_history 共 6 处 | 排除:单写方 / 普通 INSERT / 全列 / 异主键 | grep 写入方清单+PRAGMA |

### §23.2② 自测结果(monkeypatch 真实代码路径,临时文件库零污染)
| # | 用例 | 结果 |
|---|---|---|
| T1 | 老基金基础 6 列被 UPSERT 更新(name/pinyin/update_date) | PASS |
| T2 | 老基金 15 扩展列保留(company/manager/scale/custodian/dividend_total…) | PASS |
| T3 | 新基金正常插入,扩展列 NULL 待 N 补 | PASS |
| T4 | 闸门裁剪失效 done(done=[A,B假,C] → 只留 DB 真有值 A) | PASS |
| T5 | done 与 DB 一致时闸门不误伤 | PASS |
| T6 | 无映射分区 no-op + 空表全裁剪 | PASS |
| T7 | py_compile + lint_scripts(pre-commit 钩子全绿) | PASS |

### §23.2③ 断点机制同类排查
- `/tmp/pf-hold-collect-progress.json`:有 total 变化保留交集逻辑(L1445),语义=采集面非补全面,无本病灶。
- `/tmp/pf-score-progress.json`:score_date 按日断点,重算粒度按天,无脱钩风险。
- `/tmp/fund-collect-progress.json`(_load_progress L3389):fail 记录为主,重跑跳过已采——同构风险低,但若未来出现"数据被清需重采"场景需同款闸门(报告留档,不动)。
- stage0 nav 分区(done=27579 vs 表 26118 distinct):差值为源接口无净值的基金(货币型/清盘),属正常跳过非假断点,未纳入闸门(其判据=表内存在行,nav 表有 26118 行<done,闸门会误裁有效跳过记录)。

## 二、批次2:#11 净值走势全量切片(复刻 fa1ca6e3b ETF 全史机制)

### 数据层
| 组件 | 说明 |
|---|---|
| `scripts/export_fund_nav.py` | fund_daily_nav(21,768,110 行/26,118 只/20210705~20260824)逐只导出 `fund_nav/{code}.json`(date/unit_nav/acc_nav);idx_daily_nav_code 索引查询,**全量实测 41 秒/514MB**(26,118 只,空数据 136 只);不放 exported_at→内容只在序列真变时变 |
| `upload_r2.py upload-fund-nav` | R2 fund_nav/ 前缀增量指纹上传:整文件 md5 状态清单 `data/.r2_fund_nav_state.json`,首跑/周日强制全量防漂移,原子写状态,失败宁多传不漏传(复刻 upload-etf-hist,简化点=无 exported_at 无需 json 解析指纹) |
| `check_data_integrity.py check_fund_nav` | 目录/结构抽样 + 覆盖率(<90% FAIL,<95% WARN)+ 抽样 5 只 DB↔产物尾 3 点逐位一致;挂 run_all_checks 随 deploy 校验链生效 |
| update_all.sh / deploy.sh | 17:50 盘后链 fund_score 段后挂 export+rsync(--delete 对齐 etf-hist)+upload;deploy run_r2_upload 加 upload-fund-nav(1800s 超时,失败不阻塞) |
| .gitignore | `static-site/data/fund_nav/` 收录(仿 etf/,R2+CF 双通道,不进 git) |
| worker | 零改动:/r2/ 为通用 key 代理(headers.js L116 decode 后直接 R2_BUCKET.get),fund_nav/ 新前缀天然可用(upload-data-large 为顶层非递归 glob,无双副本风险,L809 已核) |

### 前端(static-site/app.js)
- `openFundScoreDetailModal` 五区块→六区块:riskHTML 后插入 `<div id="fundNavTrendSection">`,header 复刻 #10 period tab(30日/3月/6月/1年/3年/5年/全部,`.signal-chart-periods` 同款 UI);
- 新增 `_renderFundNavSection`:`https://ss.fx8.store/r2/fund_nav/{code}.json` 点开才拉(per-code 缓存 `_fundNavCache`,竞态防护 navReqId,过期响应丢弃);30d=末 30 点,3m~5y 复用 `_signalModalCutoff` 回推过滤,all 不过滤;轻量 SVG(charts.lightweight 默认)/echarts 双版本随皮肤 withTheme;
- `_etfTrendLiteBind(svg, ohlc, opts)` 加向后兼容可选参数 valueLabel/valueDecimals:**缺省「收盘」+3 位=ETF 既有行为逐字不变(§23.7)**;基金侧传「单位净值」+4 位(净值 4 位小数口径);单位净值映射伪 OHLC `[date,v,v,v,v]` 复用既有 SVG 几何 helper 零复制;
- `closeFundScoreDetailModal` 补 dispose 兜底(对齐 closeEtfScoreDetailModal,防 echarts 实例泄漏)。

### 自测证据
- 单只产物逐位核对(DB 尾 6 行 vs 000001.json):DB 8/24、8/21、8/20 unit_nav=NULL(披露滞后占位行)被正确过滤,产物 date=20260819 与 DB 最新有效值一致;首行 `["20210705",1.406,null]` 与 DB 逐位一致。
- check_fund_nav 单测:`fund_nav ok | 26118 只基金全史净值，抽样 5 只结构+DB逐位一致，覆盖率 ≥95%`。
- node --check app.js/app.min.js PASS;build_min 构建成功且 min 含 fund_nav/净值走势 字符串(产物验证后已还原工作区,min+bump 归主控 merge 链统一做,机制 C)。
- period 过滤/伪 OHLC 映射纯逻辑单测 4 项 PASS。
- 浏览器实操冒烟未做(worktree 无浏览器环境):交互模式为 #10 ETF 弹窗同构复刻,建议 merge 上线后用户点验一只基金弹窗(如 000001 华夏成长混合)确认走势区渲染。

### §22/§21/§23.1 同步
- §22:产物走 static-site/data(R2 上传)+rsync trade 树(deploy git 渠道外,该目录 gitignore 不进 git,R2+CF Static Assets 双通道与 etf/ 同架构)。
- §21:purpose-notes.js "offshore" 公示更新两处(弹窗区块列举加「净值走势」+数据源口径句),grep 核实全站唯一副本;算法/数值无变化,无其他公示点。
- §23.1:README 功能亮点段补「基金全史净值走势(#11)」条目+评分排行行区块数同步 5→6;参考与致敬段 akshare 条目已存在(本任务复用自家机制,无新增外部依赖)。

### 批次3(renderOffshoreFund 列表 sparkline)= 未做,原因与建议
列表行 sparkline 需要每 item 内置近 30 日净值序列;API 模式列表来自 CF Worker+D1(`/api/fund_score`),注入序列须改 D1 表结构或 worker 聚合逻辑——触及已上线 #79 接口(版本功能冻结契约 §23.7),不是前端顺手小改。Top100 fallback JSON 可由 export_fund_score.py 注入但会造成 API/静态两模式行为分叉。建议:确需列表 sparkline 时独立派单设计(D1 加聚合列或独立批量 spark 接口),不在本任务夹带。

## 三、遗留与提示
1. **fund_basic 扩展列恢复**:等周日 stage0-overview 自动真采(或主控拍板手动提前跑);bug① 修好后每日日更不再清列,N 的成果可持续。
2. **首次线上触发**:merge 后首个交易日 17:50 update_all 会跑 export(41s)+rsync(首启 26118 文件较慢,~分钟级)+upload-fund-nav(状态清单空=全量 ~514MB,1800s 超时应能承接;若间歇超时,告警不阻塞,次日增量自然收敛)。R2 上传成功前,前端走势区显示「加载失败,请稍后重试」优雅降级,不影响弹窗其余区块。
3. 本地验证期间在 trade-data/static-site/data/fund_nav/ 已生成全量产物(566MB,untracked),merge 后首次 update_all 即增量模式,无需再等首跑全量。

## 复现

```bash
# 1. 导出全量净值切片(输入: /Users/linhuichen/code/trade-data/data/public_fund.db fund_daily_nav 表;
#    输出: $REPO/static-site/data/fund_nav/{code}.json; 从 trade-data 树跑读实时库)
REPO=/Users/linhuichen/code/trade-data /Users/linhuichen/code/trade/.venv/bin/python scripts/export_fund_nav.py
# 小样: REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/export_fund_nav.py --codes 000001,110011,161725

# 2. R2 增量上传(update_all/deploy 链自动跑; 手动:)
REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/upload_r2.py upload-fund-nav

# 3. 完整性校验(含 check_fund_nav: 结构抽样+覆盖率+DB↔产物尾3点逐位一致)
.venv/bin/python scripts/check_data_integrity.py

# 4. DB 抽查核对基准(任取一只):
sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db \
  "SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='000001' AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 3;"
diff <(sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db "SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='000001' AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 3;") \
     <(/Users/linhuichen/code/trade/.venv/bin/python -c "
import json
d = json.load(open('/Users/linhuichen/code/trade-data/static-site/data/fund_nav/000001.json'))
for r in reversed(d['nav'][-3:]): print('|'.join(map(str, r)))")
# 实测:diff 无输出(逐位一致)。尾3点=20260819|1.319|3.892 / 20260818|1.409|3.982 / 20260813|1.343|3.916

# 5. 批次1 修复自测脚本(monkeypatch 临时库, 不碰生产):
/Users/linhuichen/code/trade/.venv/bin/python /tmp/test_fundfix_ac91.py
```

关键口径一句话:fund_nav/{code}.json = 该基金 fund_daily_nav 表全史 [date, unit_nav, acc_nav] 升序序列(unit_nav 非空行),T 日净值次日晚间入图(T+1);数据截止 2026-08-24 采集批(样本 000001 最新有效净值 20260819 属该基金披露滞后,DB 与产物一致)。
