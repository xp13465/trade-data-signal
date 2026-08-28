# #11 场外基金净值走势全链 · reviewer 审查报告(2026-08-25)

> 分支 `worktree-agent-ac91bcad82e3eef62`(4 commit:1fd48540e 双bug修 / a4fc234d4 全链 / 7eef0b40e 报告 / fa860f2ae README)
> 方法:role-reviewer §10 四视角独立审(B级③广涉及面)+ §10.2 置信度过滤(<80 滤掉)
> 结论:**PASS-with-fixes**(1 必修项 + 1 强烈建议 + 1 运营决策项,均不推翻功能主体)

## 一、必修项(merge 前修)

### F1(90)check_fund_nav 把「合法空数据基金」判 FAIL → deploy 随机阻断
- **证据**:产物目录实测存在 **136 个 count=0 空文件**(如 028614/027559.json;export 对全 NULL 净值 code 仍产出空 JSON,报告自述"空数据 136 只");`scripts/check_data_integrity.py` check_fund_nav 结构抽验 `if not d.get("date") or not d.get("count") or not d.get("nav"): bad→_fail`。
- **已复现**:强制抽样含 027559.json → `fail: 027559.json: date/count/nav 有空值`(--deploy-mode 下 exit 1 阻断部署)。自然命中率 = 1-(25982/26118)^5 ≈ **2.6%/次 deploy**,即每次上线掷骰子,且 FAIL 文案"有空值"会误导排障方向(以为数据损坏,实为合法空数据)。
- **建议修法**(:check_fund_nav 结构抽验处):`count==0` 视为合法空数据基金放行(可改为仅校验 count>0 的文件结构),或文案区分「空数据基金 N 只属正常披露缺失」。一行逻辑修,派 implementer。
- 注:实施 agent 自测那次 PASS 属 97.4% 幸运侧,不代表稳定 PASS。

## 二、强烈建议(可与 F1 同 commit)

### F2(80)跨弹窗竞态串门:navReqId 随 open 重置 + close 不失效
- **路径**:`app.js _renderFundNavSection` reqId 存于 `modal._ctx.navReqId`,而 `openFundScoreDetailModal` 每次 open 执行 `modal._ctx = { code }` 重置计数;`closeFundScoreDetailModal` 不失效序号。
- **场景**:A 基金 fetch in-flight 中关闭弹窗并打开 B → A/B 两请求 reqId 同为 1,A 后到则通过校验,**B 弹窗走势区渲染 A 的净值与名称**(数据正确性问题,弱网/慢速可触发;同弹窗内切 tab 防护本身正确)。
- **同源既有**:ETF 弹窗 `_renderEtfTrendSection` trendReqId 同构(app.js L23274/L23409),属 #10 引入的 pre-existing 模式,本次复刻带入 fund 版——按 §23.2③ 举一反三两处一起修。
- **修法**:reqId 改模块级全局单调计数器(不复位),或 close 时 bump 失效。一行改动×2 处。

## 三、运营决策项(主控拍板,不阻塞 merge)

### F3(82)upload-fund-nav purge 预算不足:日增量 ≈2.4 万 keys,非注释所称"1-2 万"
- **实测**:8/24 有新净值行的 distinct fund_code = **23,897 只**(8/21=23,836),占 26118 的 91.5%——「清盘冻结跳过」只省 8.5%,每日增量上传 ~2.4 万文件(~620MB)+ purge ~800 批(30 keys/批,批 sleep 0.5s + Worker 串行 delete)估 ~27min,加 8 线程上传 ~10-15min,**deploy 链 1800s 大概率超时被 kill**(kill 点多在 purge 阶段:_save_state 已落、数据已在 R2,仅 edge cache 未清,/r2/ TTL=3600s → 最坏滞后 1h 自然过期自愈);update_all 链(shell 直调无 timeout)能跑完,17:50 链尾拖长至 ~19:00,距 20:40 daily-brief 安全,**无撞车**(首跑今晚发生,R2 无旧对象,purge 失败实际无害)。
- **后果**:手动 deploy 天天 --severe 告警(deploy_r2_upload_fail,dedup 仅 1800s)=狼来了;耗时为估算,建议今晚首跑后看 update_all 日志实测校准。
- **可选方案**(任一,主控拍板):① worker 对 fund_nav/ 前缀走 NO_CACHE(ttl=0) 不查不写 edge cache(懒加载低频访问回源成本可接受,先例 headers.js L158),purge 环节整个省掉,upload 回到 ~15min 内;② upload-fund-nav 不调 purge_cache(edge 1h 自愈);③ 接受现状+容忍告警噪音。
- **附带提示**:merge 后首次手动 deploy 时 trade 树 fund_nav 目录尚空(rsync 未跑过,已验证 0 文件)→ upload-fund-nav 会 sys.exit「无 fund_nav json」+ 一封预期告警;先跑一次 update_all 或手动 rsync+upload 可避免。双树双状态文件(.r2_fund_nav_state.json 各一份)与 etf-hist 同架构。

## 四、合规确认(逐条核过,PASS)

| 条款 | 结论 |
|---|---|
| §23.7 冻结契约 | `_etfTrendLiteBind(svg,ohlc,opts)` 缺省路径逐字不变:全仓唯一既有调用方 app.js L23326 不传 opts ✓;五区块→六区块属用户点名 #11 范围 ✓ |
| §21 公示 | purpose-notes.js offshore + README 区块清单/T+1 口径两处已同步,算法零变化,grep 全站无第三处用户可见登记点 ✓ |
| §22 一致性 | R2 fund_nav/ + CF /r2/ 双通道同 etf/ 架构(worker 零改动 /r2/ 通用代理+ACAO:* 已开),rsync 双树 --delete --checksum 与 etf-hist 同款 ✓ |
| §14 时点 | 17:50 update_all 链尾挂载,结束 ~19:00,距 20:40 daily-brief 安全 ✓(拖长度见 F3) |
| §23.5 报告 | docs/chart-fund-nav-implement-report.md 含 ## 复现段(脚本/依赖/命令/截止 20260824/口径一句话)四件套齐 ✓ |
| UPSERT 语法 | fund_basic.fund_code TEXT PRIMARY KEY 实测建表 L181,ON CONFLICT(fund_code) 合法;扩展列系 ALTER 追加(fetch_fund_overview UPDATE 写入),UPSERT 保列正确 ✓ |
| 断点闸门覆盖面 | `_load_stage0_progress` 全仓恰 4 处调用方(fund_overview/fee_detail/manager/risk_indicator)与 `_STAGE0_DB_VALIDITY` 4 键一一对应,无漏 ✓ |
| 历史意图 | INSERT OR REPLACE 自初版 10454371c 即存在(当时 6 列无副作用),无人依赖清列副作用,UPSERT 为根修非翻案 ✓;实施报告 16 处 REPLACE 同类排查表到位 |
| min+bump | 分支未做,归主控 main-merge.sh 统一 build_min+bump(机制 C),符合 §24② |

## 五、pre-existing 上报(§23.7⑤,不算 finding,待用户决定是否修)

1. **P1**:ETF 弹窗 trendReqId 同源竞态(F2 同根因,#10 已上线行为)——修复 F2 时顺带覆盖,需用户点头(动已发布交互)。
2. **P2**:upload_r2 双树双状态文件(etf-hist 既有):deploy 链与 update_all 链各维护一份指纹,deploy 首跑重复全量一次。影响小,留意即可。
3. **P3**:update_all 链 R2 上传失败只 echo 日志无主动告警(etf-hist 既有模式;deploy 链有 notify)。

## 六、低分滤掉项(§10.2,<80,共 6 条)

L1(50)app.js L24418 代码注释仍写「5 区块」未同步;L2(50)lite SVG aria-label 写死「近30日走势」;L3(50)check_fund_nav DB 定位失败时静默降级仅结构校验(双树路径本机必在);L4(50)30d=末 30 净值点≈6 自然周与「30日」文案微差;L5(25)data/.r2_fund_nav_state.json 未进 .gitignore(etf 同款噪音);L6(25)acc_nav 导出但前端暂未消费(未来扩展位)。

## 复现

```bash
# 0. diff 总览
git diff main...worktree-agent-ac91bcad82e3eef62 --stat

# 1. F1 空数据基金文件数(输入: trade-data/static-site/data/fund_nav/)
python3 -c "
import json, glob
print(sum(1 for f in glob.glob('/Users/linhuichen/code/trade-data/static-site/data/fund_nav/*.json')
          if not json.load(open(f)).get('count')))   # -> 136"

# 2. F1 check 误报复现(强制抽样含空文件;分支版脚本导出到 /tmp)
mkdir -p /tmp/fnreview && git show worktree-agent-ac91bcad82e3eef62:scripts/check_data_integrity.py > /tmp/fnreview/check_data_integrity.py
python3 -c "
import importlib.util, pathlib, random
spec = importlib.util.spec_from_file_location('cdi', '/tmp/fnreview/check_data_integrity.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data_dir = pathlib.Path('/Users/linhuichen/code/trade-data/static-site/data')
files = sorted((data_dir/'fund_nav').glob('*.json'))
target = next(f for f in files if f.name in ('028614.json','027559.json'))
orig = random.sample
random.sample = lambda pop, k: [target] + orig([p for p in pop if p != target], k-1)
print(m.check_fund_nav(data_dir))   # -> fail: 027559.json: date/count/nav 有空值"

# 3. 日增量口径(F3 依据)
sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db \
  "SELECT COUNT(DISTINCT fund_code) FROM fund_daily_nav WHERE date='20260824';"  # -> 23897

# 4. 数据层抽查(DB↔产物逐位)
diff <(sqlite3 /Users/linhuichen/code/trade-data/data/public_fund.db "SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='000001' AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 3;") \
     <(python3 -c "
import json
d=json.load(open('/Users/linhuichen/code/trade-data/static-site/data/fund_nav/000001.json'))
[print('|'.join(map(str,r))) for r in reversed(d['nav'][-3:])]")

# 5. 关键日期/数据截止:fund_daily_nav 最新 20260824;26118 只/2177 万行(2026-08-25 实测)
```
