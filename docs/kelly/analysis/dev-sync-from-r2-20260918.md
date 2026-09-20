# dev 数据同步 R2 结果(2026-09-18)

## 一、交付物
| 项 | 内容 |
|---|---|
| 脚本 | `scripts/sync_dev_from_r2.sh`(已按协调者修正①收窄 TARGET_LABELS={index,industry,data-large}) |
| 自测 | `bash -n scripts/sync_dev_from_r2.sh` 通过;完整运行日志 `trade-data/data/logs/sync_dev_from_r2-20260918-091353.log` |
| 报告 | `docs/kelly/analysis/dev-sync-from-r2-20260918.md`(归置) |

## 二、① DB 同步日期
- signal_daily MAX(date)=**20260917** ✅
- etf_daily latest **20260917**(部分 ETF 只到 9-16,见下"遗留")
- index_daily latest **20260917** ✅
- 两处权威路径均刷新:trade-data/data/ + trade/data/(独立 inode 双写)
- 旧 DB 留底:`/tmp/r2sync/old_backup/20260918-*/*.db.pre-sync`

## 三、② export 产物新鲜度
- 357 个 JSON,387.9 MB,latest mtime **2026-09-18 08:07**(08:06 全量跑)
- board_etf_map.json 已随新 DB 重新 build,且与 R2 上 map **逐字节一致**(md5 `292f7f85...`,652784 B);本地 export 产物与本地 map 完全自洽

## 四、③ verify-r2 对账结果(收窄版 {index, industry, data-large})
- checked=331,OK=71,**DIFF=260**(index=153,industry=84,data-large=23)
- **结论:不能"全绿"。对账红不是本地错,根因在 R2 生产侧自身内部不一致。**

### 三次重跑结论
| 版本 | checked | OK | DIFF | 根因 |
|---|---|---|---|---|
| 初版(含 all-data) | 455 | 119 | 336 | ①缺少 build_board_etf_map(已修) ②all-data 混入独立生成器产物(已修) |
| 收窄后(撇 all-data) | 331 | 71 | 260 | R2 生产侧 map(63)与产物(76)不一致 |

### 差异字段分解
- **index**(153 个文件):差异 99% 在 `etfs[].track_score/track_tier/track_n/max_err/similarity`(R2 产物 use 76 口径,本地 use 63 口径)+ `etf_since_return/etf_price_diff`(R2 侧部分 etf 行情日期差一天)。非 etfs 字段(ohlc/stable_top1/stats/signals)数量级 10–40,为附带。
- **industry**(84):同一根因,差异集中在 `etfs[].track_score/track_tier/track_n/max_err/similarity`,另有 `$.data`、`$.width`、`$.signals/stats`(随日期推进、R2 生产产物为更早时点)。
- **data-large**(23):15 个 >2MB 只 HEAD 未下载(可能含时间戳差异);其余 8 个差异在 `extras` 现货金银油汇率(实时行情浮动,生产产物时点不同属正常)+ 少量 etf_since_return/etf_price_diff。

### 根因定位(实据)
- R2 上 `board_etf_map.json`(**63 版**)= 本地 build 版 md5 一致(`292f7f85...`)
- R2 上 `data/overview.json` 独立文件 top1 `510300 ts=76.2 strong`(**76 版**旧口径)
- R2 上 `data/index/*.json` top1 `510570 ts=77.0 strong`(**76 版**旧口径)
- 本地 build map(63)= R2 map(63)一致;本地 export 跟随 63→自洽
- **R2 生产侧 map 已是 63,但 index/industry/data-large 产物仍是 76 旧口径 = 生产侧产物未用新 map 重算。**这是生产侧的上线动作(重跑生产 export),不在本次"纯本地刷新"任务内,本机不应代跑(danger: 用 dev 环境产物覆盖生产 R2 会污染线上)。

## 五、遗留/风险
1. R2 生产侧需要以 63 map 为主重跑一次 index/industry/data-large(kelly-dev-sync 后续:主控拍板是否走 `deploy.sh` 或生产侧 export)。
2. etf_daily 部分 ETF 最新只到 9-16(R2 备份本身如此,非本地问题;若需 9-17 完整口径需等生产下一次 etf_daily 采集)。
3. summary.json 等盘中实时产物不纳入本次验收(协调者明示)。

## 复现段
1. `bash scripts/sync_dev_from_r2.sh`(完整流程;带 build_board_etf_map)
2. `python scripts/upload_r2.py download-db sentiment /tmp/r2sync`
3. 对账见脚本 step4 内 python heredoc(TARGET_LABELS={index,industry,data-large}、META_KEYS 归一化、8 线程)