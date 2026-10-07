# #219 §0 上线观察报告(云上只读) —— parts 元数据三字段撤出后首个生产轮

- 执行角色: tester agent(独立执行,未采信任何转述;全程只读)
- 观察窗口: 2026-10-07 02:16 ~ 21:29(CST),共 5 个生产轮(合并后)
- 被观察对象: #219 治本(合 main `00229a9b2`,2026-10-06 22:2x);云上代码库 `/home/ubuntu/code/trade-data-signal` 已含该提交(merge-base --is-ancestor PASS)
- 结论: **三项验(PASS/PASS/PASS)**,发现 1 个已知范围外残留(recent2.json,已登记 #221)与 2 条诚实缺口
- 硬约束遵守: 只读 ssh;未启停任何 unit;未跑任何业务脚本主体(仅 `cat/grep/ls/stat/git log/systemctl list-timers` + 只读 R2 LIST/HEAD + python 纯读取片段);零真实外发;R2 仅 LIST/HEAD/GET(公开 CDN);所有 ssh 带 ConnectTimeout=10/BatchMode,工具侧 timeout 全覆盖

---

## 一、验 1:parts 新格式已生效(线上实测字段清单)—— PASS

### 1.1 云上本地(生成源,10-07 21:12 重新生成)
```
NDO t2011 顶层键   = ['fields', 'quadrants']            ← 无 generated_at/period_cutoffs/buy_amount
NDO recent 顶层键  = ['fields', 'quadrants']
SDC t2011 顶层键   = ['fields', 'quadrants']
对照 全量 signal_kelly_trades.json 顶层键 = ['buy_amount','fields','generated_at','period_cutoffs','quadrants'](三键仍在,全量未动=设计)
```

### 1.2 R2 侧(逐文件 HEAD 对账,34/34)
- 34 个 parts 文件: R2 etag == 云上本地文件 md5,**一致 34 / 不一致 0**
- R2 LIST(只读)键集: `data/signal_kelly_trades_parts/` 18 key = 17 现行 + `recent2.json`;`data/signal_kelly_trades_sdc_parts/` 17 key
- 因此 R2 在册 34 片内容 == 本地新格式字节(顶层键清单即 1.1,无三键)

### 1.3 线上 CF(公网展示位)
```
curl https://ss.fx8.store/data/signal_kelly_trades_parts/t2011.json     → 顶层键 ['fields','quadrants'] md5=92ae0d7c1c73816e035ed89525a9d9da
curl https://ss.fx8.store/data/signal_kelly_trades_sdc_parts/t2011.json → 顶层键 ['fields','quadrants'] md5=7c01db1eb016b2af908cce5d4c5d9b0c
curl https://ss.fx8.store/data/signal_kelly_trades_parts/recent.json    → 顶层键 ['fields','quadrants'] md5=4f4b5f6e76d3cfd41cf295596c0f7bb6
三个 md5 均 == 云上本地 md5 == R2 etag(ssd.fx8.store HEAD 同值)
```

### 1.4 合流实锤(旧格式 B 档指纹 == 新文件整文件 md5)
```
本地镜像旧格式 t2011(含三键) 的 B 档指纹(剔除三键后 sort_keys 序列化 md5) = 92ae0d7c1c73816e035ed89525a9d9da
== 线上新格式 t2011 整文件 md5 = 92ae0d7c1c73816e035ed89525a9d9da   → 两把尺子合流成立,数据本体零变化
```

### 1.5 旧格式残留
- 在册 34 片: 旧格式残留 **0**(全部为新格式字节)
- 已知范围外残留 **1 个**: `data/signal_kelly_trades_parts/recent2.json`(R2 200,17,881,308 B,LastModified 2026-09-22;本地副本顶层含三键=旧格式;站点前端/脚本零引用;已登记待办 **#221**,属 §25 清理,不在 #219 范围)

---

## 二、验 2:verify-r2 补传计数(逐轮 + 归零判定)—— PASS

### 2.1 逐轮清单(数据源: `data/logs/r2_upload_async_*.log` 的 verify-r2 结果行;今日含「自动补传」的日志共 5 个,无第二对账链)

| 轮次开始(CST) | 补传数 | 内容 | 判定 |
|---|---|---|---|
| 10-05 21:16(基线,合并前) | 34 | 全 parts | 旧格式每轮必然 |
| 10-06 18:00(基线,合并前) | 35 | 34 parts + schedule_stats.json | 同上 |
| 10-06 21:16(基线,合并前) | 49 | 34 parts + 15 其他 | 同上 |
| **10-07 02:16(合并后首轮)** | **34** | **全部 parts(t2011..t2026+recent × 2 族)** | **首轮一次性回填(上限 ≤34 恰好全中)** |
| 10-07 05:11 | 0 | — | parts 归零 |
| 10-07 16:52 | 2 | news_digest/_index.json, news_digest/2026/2026-10-07.json | 无 parts |
| 10-07 18:00 | 2 | news_digest 同两件 | 无 parts |
| 10-07 21:16 | 2 | news_digest 同两件 | 无 parts |

### 2.2 归零判定
- **首轮 34 = 预期一次性回填**: 合流后新文件 body 未变 ⇒ 上传链按 B 档指纹判「未变化」跳过 ⇒ R2 仍是旧格式字节 ⇒ verify(整文件 md5 vs etag)全不匹配 ⇒ 补传 34。此后 4 轮 **parts 补传 0**,且其中 16:52/21:16 轮含 parts 重新生成(mtime 21:12)仍 0 ⇒ **已归零,永久收敛**
- 佐证一: 两族通道 state `.r2_kelly_parts_state.json` / `.r2_kelly_sdc_state.json`(10-07 21:27 更新)均 count=17 / changed=0
- 佐证二: R2 各 parts 对象 LastModified 全部落在 10-07 02:29:38~02:34:33(=首轮回填时刻),此后 19 小时无新写入
- 保留项: 每轮 2 个 news_digest 属既有「真兜底」类(独立链滞后,10-06 前即存在;告警状态 `fetch_news|r2_skip_rounds` 在用),**与 #219 parts 无关**,不得一刀切豁免

---

## 三、验 3:线上数据本体无异常(结构/config 一致)—— PASS

### 3.1 结构 / JSON 合法(线上文件实测)
```
NDO t2011 : fields 27 列 / 6 个 qk / 1144 行 / 行宽异常 0 / signal_date 年份集合 ['2011']
NDO recent: 7876 行 / 行宽异常 0 / 日期范围 20260731~20260929(60 天窗口)
SDC t2011 : 解析正常,顶层 [fields,quadrants]
```

### 3.2 条数一致性(parts 年度分片 vs 全量 trades 逐片对账;镜像同源档)
```
NDO: 全量 335,456 行 → 分片 t2011..t2026 逐片行数 == 全量该年行数(全部一致);recent 10472 行 == 全量 60 天窗口行数;fields 逐片 == 全量 fields
SDC: 全量 341,352 行 → 同上全部一致;recent 11440 行 == 全量 60 天窗口行数
镜像 B 档指纹 == 线上文件 md5 的片数: 24/34(其余 10 片 = recent+t2023..t2026×2 族,属上游数据修订导致的跨轮 body 漂移,非本改动引入)
```

### 3.3 与配套 config 一致(前端回退路径等值;云上实测)
```
NDO: signal_kelly_backtest.json     config.buy_amount=10000 == 全量 trades 顶层 buy_amount=10000
     config.period_cutoffs == 全量 trades 顶层 period_cutoffs (y1/y3/y5/y10/all 逐键相等)
SDC: signal_kelly_backtest_sdc.json 同上,config 与 sdc trades 顶层逐键相等
```
(parts 撤出三键后,lab.js/app.js 回退读的正是 config 这两键 ⇒ 回退值 == 撤出值,行为零变)

### 3.4 端到端 UI(线上真实站点,Playwright 无痕)
- `https://ss.fx8.store/` 打开首页「模拟回测」弹窗: parts 请求全部 **HTTP 200**(recent + t2011/t2012/t2016/t2017/t2021/t2026 等年片)
- 渲染出真实结果: 「筛选结果: 27 笔(模式 A · 降亏开 · K=1)」+ 累积收益率口径行 + 逐笔表(含 7 笔持仓中)+ 84 点走势(20260709~20260930)
- 控制台错误仅为东财行情接口 `push2delay.eastmoney.com` ERR_EMPTY_RESPONSE(第三方,与 parts 无关);**无 parts 解析类错误**

### 3.5 尺子先验(§5.2)
- etag 对账尺子: 正常比对 PASS;喂错 1 位 md5 → MISMATCH(尺子有效,不会假绿)

---

## 四、诚实缺口(未跑 / 未覆盖)

1. **首个观察窗为假日**(`update_all_20261007_1750.log`: 「非交易日,跳过采集」)⇒ 未观测到「交易日 body 真变」轮次。该路径按脚本顺序(kelly-parts 通道先于 verify-r2 运行,`r2_upload_async.sh` L221 vs L254)应在同轮内收敛,但**待交易日复验**
2. UI 端到端仅覆盖首页弹窗默认档(模式 A/K1/次日开盘);**实验室凯利区 + SDC 口径切换** 的 UI 未跑(数据层 SDC 已验)
3. 34 片内容中仅 3 片经 CF 逐字节校验(t2011 × 2 族 + NDO recent),其余 31 片靠「R2 etag == 本地 md5」链(34/34 全过,非逐片过 CF)
4. 未跑 grep 级「全站无 recent2 消费方」的机检脚本(引用面已由文档 + 本轮 grep 复核,残留清理仍归 #221)

## 五、复现命令(只读,照抄可重跑)

```bash
# 1) 云上本地顶层键
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/static-site/data; \
  python3 -c "import json;print(sorted(json.load(open(\"signal_kelly_trades_parts/t2011.json\")).keys()))"'
# 2) 逐轮补传计数(全部轮次)
ssh ... 'grep -E "开始|自动补传" /home/ubuntu/code/trade-data/data/logs/r2_upload_async_2026100*.log'
# 3) R2 逐片 etag 对账(本机)
#    先取云上 md5: ssh ... 'cd .../static-site/data; md5sum signal_kelly_trades_parts/*.json signal_kelly_trades_sdc_parts/*.json'
#    再逐片: curl -sI -A "<浏览器UA>" https://ssd.fx8.store/data/<path> | grep -i etag
# 4) R2 键集只读列举
/Users/linhuichen/code/trade-data/.venv/bin/python3 -c "import sys;sys.path.insert(0,'scripts');import upload_r2 as ur;print(sorted(ur._list_keys('data/signal_kelly_trades_parts/')))"
# 5) 线上 UI(无痕)
#    scripts/playwright-accept/ 依赖下的 headless chromium → ss.fx8.store → window._openSimBacktestModal()
```

(落档说明: 本报告由 tester agent 写档,未 commit/未 push;证据原始输出留存: 云上日志 `/home/ubuntu/code/trade-data/data/logs/r2_upload_async_2026100*.log`、本机 `/tmp/219-prod-observe/{cloud-md5.txt,etag-compare.txt,online_ndo_t2011.json,online_sdc_t2011.json,online_ndo_recent.json,live_sim_check.mjs,live_sim_modal.png}`;进度文件 `/tmp/agent-progress-219-prod-observe.md`)
