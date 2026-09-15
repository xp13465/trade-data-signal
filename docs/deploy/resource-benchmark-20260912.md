# 云服务器部署资源基准实测(2026-09-12)

> 目的:实测 macOS 环境(trade 项目)真实资源占用,为「部署到阿里云/腾讯云轻量服务器」定最小配置。
> 实测环境:Apple M1 / 8 核 / 16G RAM, macOS 23.4.0。数据截止 2026-09-12 16:31(周六,非交易日,无定时任务干扰)。

## 结论速览(配置定档)

| 档位 | CPU | 内存 | 磁盘 | 带宽 | 适用 |
|---|---|---|---|---|---|
| 起步档(可用) | 2 核 | 4G | 40G SSD | 3M | 跑通全链路,备份治理后够用 |
| 推荐档(从容) | 4 核 | 8G | 60G SSD | 5M | 4 条 pipeline 并行 + 备份保留更久 |

**前提治理(不做则磁盘档位全部上调 20G)**:备份策略迁移云上时改「单仓 + 保留 7 天」,现双仓每日备份 604M/天是本地第一大增长源(见 §4)。

## 一、磁盘现状(A 实测)

总占用 **32.1G** = trade 23G + trade-data 9.1G。trade-data 下代码目录为 symlink(同主树 inode),数据产物是双份双写,云上只部署一份可天然省一半。

| 项 | trade | trade-data | 合计 | 占比 |
|---|---|---|---|---|
| backups/(DB 每日备份) | 10G(228 文件,7/18~9/11) | 3.2G | **13.2G** | 41% |
| public_fund.db(场外基金库) | 2.3G | 2.3G | 4.6G | 14% |
| static-site/(上线数据) | 1.9G | 2.1G | 4.0G | 12% |
| .git | 1.8G(pack 1.57G+loose 179M) | - | 1.8G | 6% |
| logs/ | 4.3M | 350M | 354M | 1% |
| etf_national_team.db | 177M | 180M | 357M | 1% |
| sentiment.db | 125M | 132M | 257M | 1% |
| stock_daily.db | 111M | 112M | 223M | 1% |
| stock_top_weights.db | 96M | - | 96M | - |
| release/(public_fund.db.tar.gz 552M 等) | 657M | - | 657M | 2% |
| baostock_logs/ | 9.7M | 9.1M | 19M | - |
| docs+scripts+其余 | ~500M | - | ~500M | - |

**云上单份核心数据(去双仓冗余)= 约 13G**:public_fund.db 2.3G + etf_national_team 180M + sentiment 132M + stock_daily 112M + top_weights 96M + static-site/data 1.9G + .git 1.8G + logs 0.4G + 7 天备份 2.1G + 系统与 Python 依赖 ~3G。

static-site/data 大 JSON(部署同步量参考):signal_kelly_trades.json 75M、industry-all-concepts.json 31M、accum_nav_map.json 19M、etf_score_list.json 18M,共 29874 个文件。

## 二、内存峰值(B 实测)

**实测对象**:`scripts/signal_kelly_backtest.py` 全量回测(生产每日 17:50 全量档同一入口),`/usr/bin/time -l` 记录:

| 指标 | 值 |
|---|---|
| peak RSS(maximum resident set size) | **447,840,256 B ≈ 427 MB** |
| peak memory footprint | 402,049,664 B ≈ 383 MB |
| 耗时 | 11.01s real / 10.01s user / 0.25s sys |
| 处理规模 | 42,079 条买信号、106,237 行 ETF 价格、28,159 个冻结信号事件、输出 trades JSON 81M |
| 退出码 | 0 |

**并发推断(诚实标注:未实测并发,按实测单进程×并行度外推)**:update_all.sh 设计为 4 条并行 pipeline(core/width/futures/stock_daily,各自独立采集→计算),单进程回测峰值 427MB → 4 并行峰值约 1.7G。另有 akshare/baostock 采集进程,预留 8G 内存档可容纳 4 pipeline + 采集 + 系统余量。

**历史 OOM 痕迹**:logs 全量 grep MemoryError/OOM/Killed 无真实内存不足记录(grep 命中的只是 agent_inbox_watcher err 里打印的 Python 源码正则,非实发内存错误)。本机 16G 从未触顶,不代表云上 4G 够——4 pipeline 推断峰值 1.7G + 系统 0.5G ≈ 2.2G,4G 档可用但余量薄,8G 从容。

**未实测项(诚实标注)**:export.py 全量导出、public_fund 采集等有写 static-site/DB 副作用的脚本未跑,按回测单进程峰值 1.5 倍余量估(≈ 650MB/进程)留配置缓冲。M1 单核性能高于云 vCPU,回测 11s 在云 2 核机上预计 40-90s(4 pipeline 并发争抢时更久),建议保留耐心阈值。

## 三、日志增长(C 实测)

logs 目录(6005 个文件)最老 2026-07-18 → 最新 2026-09-12,约 8 周(56 天)积 **350M**:

- 基线周增 ≈ 44M/周(总均)
- 近 7 天实际 **227M/周**(热点放大:sensenova-rotate.log 58M、agent_inbox_watcher_launchd.err 43M、intraday_snapshot_launchd.log 27M、update_lab_launchd.log 19M、sensenova-rotate-req.log 17M)
- 云上月增长预估:0.2G(基线)~ 1G(异常热点持续),按 1G/月留日志余量

## 四、磁盘增长预估(云上)

| 增长源 | 速率 | 治理后 |
|---|---|---|
| DB 备份(现双仓×每日 etf 185M+sentiment 131M) | 604M/天(本地) | 单仓 7 天保留 = 2.1G 稳态;30 天 = 9G |
| public_fund.db(场外基金阶段采集) | 季度大更新 | 2.3G 起,按采集阶段增长 |
| logs | 44-227M/周 | 轮转后 ≤ 1G/月 |
| static-site 数据 | 每日更新,总体稳定 | ~2G 稳态 |
| .git | 随 commit 增长 | 云上可浅克隆省 1.6G |

**结论:40G SSD 在「单仓备份 + 保留 7 天」治理下可用约 2-3 个月才需扩容;不治理(双仓 604M/天备份),40G 一个月内打满。60G 档配 30 天备份保留更省心。**

## 五、定档依据小结

- **CPU 2 核起步**:回测 10s user(M1);4 pipeline 并行下 2 核串行争抢,4 核明显提速 update_all 全链路(本地 M1 8 核为对比基准,云 2 核实测可能 4-8 倍慢)。
- **内存 4G 起步 / 8G 推荐**:实测单进程峰值 427MB,4 pipeline 推断 1.7G;4G 可跑但无缓冲,8G 允许采集+回测+系统同峰。
- **磁盘 40G 起步 / 60G 推荐**:见 §4 治理前提。
- **带宽 3M 起步**:主要上行是每日向 R2/CF 推 static-site 产物(302M 备份 + JSON 更新),3Mbps≈375KB/s 传 302M 约 13 分钟,落在盘后窗口可接受;5M 档(≈21 分钟传 1G)应对 public_fund 大更新更从容。采集侧是外呼 API,按量计费,3M 足够。

## 复现

- **数据截止**:2026-09-12 16:31(周六)。
- **磁盘**:`du -sh /Users/linhuichen/code/trade /Users/linhuichen/code/trade-data`;`find <dir>/data -type f -print0 | xargs -0 du -h | sort -rh | head -15`;`du -sh <dir>/data/*/`;DB 逐个 `ls -lh data/*.db`;`.git` 用 `git -C <repo> count-objects -vH`。
- **内存**:
  ```
  /usr/bin/time -l /Users/linhuichen/code/trade/.venv/bin/python3 \
    /Users/linhuichen/code/trade/scripts/signal_kelly_backtest.py \
    --output /tmp/rb_backtest.json --trades-output /tmp/rb_trades.json --skip-parts \
    > /tmp/rb_run.log 2>&1
  # 读 maximum resident set size / peak memory footprint 两行
  ```
  跑前/后 `md5 data/sentiment.db data/signal_kelly_etf_freeze.json` 比对一致(f77d2fb8.../6587da87...),确认零副作用;无 /tmp 残留依赖(输出已落 /tmp)。
- **日志增长**:`ls -lt/-ltr trade-data/data/logs` 看跨度;`find ... -mtime -7 | xargs du -ch` 算周增。
- **口径**:peak RSS=maximum resident set size;footprint=macOS time -l 的 peak memory footprint。4 pipeline 并发峰值=单进程实测×4 外推(标注推断)。
- 无新增自定义脚本(纯 du/time 命令可复跑),无 DB/产物写入。
