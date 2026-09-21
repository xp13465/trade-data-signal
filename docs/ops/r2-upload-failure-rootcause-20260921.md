# deploy R2 上传失败告警根因调研(2026-09-21)

> 调研 agent 产出,主控验收。范围:纯运维排查,不涉回测基准。任务书见会话 prompt;测试基准无关。

## 结论速览

用户反馈「告警里经常看到 deploy r2上传失败」。**真相 = 看门狗超时 kill,不是上传本身失败**:
- 根因 A(核心):云上→R2 跨境带宽慢且剧烈波动(实测 6KB/s~678KB/s 两数量级)+ 周日强制全量体量 ~1.1GB + 单通道看门狗窗口(900/1800/7200s)结构性不匹配 → kill → deploy.sh 收尾 notify「deploy R2上传失败」
- 根因 B:verify-r2 周日全量对账(≈3万次 HEAD,每次新建 HTTPSConnection+TLS 握手+RTT 222ms)结构性超 1800s,09-20 四轮全超
- 根因 C(已兜底,非告警源):网络瞬时抖动 / R2 瞬时 5xx,`s3_request` 已有 5 次重试(1/2/4/8s 退避)+ HTTP>=500 重试
- **自愈铁证:被 kill 通道数据实际已传完**,下一轮 verify-r2 全对账 0 补传 + 独立 SigV4 HEAD 抽查 md5 全一致 → 告警是噪音

---

## 一、根因分类 + 证据链

### 根因 A:带宽慢 + 周日全量大 + 看门狗窗口不匹配(告警 100% 触发面)

**证据链**:
- 带宽实测(云上 `/home/ubuntu/code/trade-data` 机器,同一时刻):
  - `curl https://ssd.fx8.store/data/overview.json` 下载 678,114 B/s
  - `curl https://ssd.fx8.store/data/signal_kelly_trades_full.json` 下载 6,218 B/s(注意该 key 现 404,见排除项;此处证明带宽两数量级波动)
  - TCP connect 到 `9be954e87f3d28f9c0faaa9e2b3a78b7.r2.cloudflarestorage.com`:207~222ms
- 数据体量(`/home/ubuntu/code/trade-data/static-site/data/`):
  - `etf/` 116MB / 1699 只
  - `fund_nav/` 577MB / 26436 只
  - `accum_nav/` 28MB / 1699 只
  - `trade_sim/` 368MB
  - 合计 ~1.1GB;周日(2026-09-20)所有通道 `force_full` 全量重传
- 慢窗口算术:577MB@30KB/s ≈ 5.5h,远超 fund-nav 看门狗 **7200s(2h)**
- 9 月失败矩阵(逐轮扫描 `/home/ubuntu/code/trade-data/data/logs/deploy_*.log`):
  - 09-20(周日)4 轮 deploy 全部有通道被 kill:
    - 21:05:`upload-etf-hist 超 900s` + `upload-fund-nav 超 7200s` → 收尾 notify
    - 16:41:`upload-fund-nav 超 7200s` + `verify-r2 超 1800s` → notify
    - 05:00 / 02:05:`verify-r2 超 1800s` → notify
  - 09-18 两轮:`upload-etf-hist 超 900s`(23:31)+ `upload-fund-nav 超 7200s`(18:16)
  - 09-17 一轮:`upload-etf-hist 超 900s`(21:57)
  - 09-13/14:默认 300s 时期多通道 kill(更频繁)
  - 合计:9 个 deploy 日志含 `[告警] deploy R2上传失败`
- 反证(同一通道有时能完成):09-20 02:05 `fund-nav ✓ 上传完成 26436/26436, 耗时 5595.7s`(凌晨带宽好);晚间 21:05 同通道 7200s 内未完成被 kill(晚间带宽差)→ 带宽时段差异

### 根因 B:verify-r2 周日全量对账结构性超 1800s

**证据链**:
- verify-r2 周日模式 = 全部 14 通道逐文件 HEAD(仅 fund_nav 就 26436 只),合计 ≈ 3 万次 HEAD
- 每次 `s3_head`(upload_r2.py L335-394)新建 `HTTPSConnection`(TLS 握手跨境 ~1s)+ RTT 222ms,8 线程并发 → 1~2 小时 >> 1800s 窗口
- 09-20 的 02:05 / 05:00 / 16:41 / 17:50 四轮 verify-r2 全部被 kill(日志「⚠ verify-r2 超 1800s 未退出,kill pid=... 释放 deploy.lock」)
- 工作日增量对账(状态文件 `changed` 字段,秒级)从不超时 → 只有周日全量必超

### 根因 C:网络瞬时 / R2 瞬时 5xx(已兜底)

**证据链**:
- `scripts/upload_r2.py` L266-331 `s3_request`:5 次重试(SSL/OSError/HTTPException,退避 1/2/4/8s)+ HTTP>=500 重试(attempt 0-3)
- 7 月底历史 `TimeoutError` 实例(alert_state.json `intraday_snapshot|TimeoutError:` 等)均已重试自愈
- ⚠ 反作用点:云上 `.env` `R2_UPLOAD_HTTP_TIMEOUT=600` + 重试 5 次 = 单文件最坏卡 50 分钟,反而放大看门狗超时
- `r2_unreachable`(schedule_monitor.sh,curl ssd.fx8.store rc=28)是可达性自愈监控,`SELF_HEAL_THRESHOLD=2`(连续 2 次 30min 才通知);2026-09-21 00:30/08:30 两次全自愈、`last_alerted=null` → **不是用户看到的告警来源**

---

## 二、排除项(诚实标注)

- 09-15 期间日志「超 120s 未退出」为 `git fetch origin main`(deploy_20260915_1930.log L3),非 R2,不算本根因
- R2 上 `signal_kelly_trades_full.json` 404:前端 app.js/lab.js 零引用、数据已改分片(recent.json + t{YYYY}.json)+ 独立文件 `signal_kelly_trades.json`(已对账 md5 一致),404 非漏传

---

## 三、自愈铁证:看门狗 kill ≠ 数据丢失

- 09-20 21:05 被 kill 的 etf-hist / fund-nav,09-21 05:00 下一轮 deploy 全部通道「内容未变化无需上传」+ verify-r2 **全对账 0 补传**
- 独立 SigV4 HEAD 抽查(调研时另写脚本,不经项目 verify-r2):
  - `data/signal_kelly_trades.json` R2 ETag == 本地 md5(084cad7d...)
  - `data/signal_kelly_trades_sdc.json` 一致(a8da6d66...)
  - `data/overview.json` 一致(79b74a0e...)
- 状态文件 `/home/ubuntu/code/trade-data/data/.r2_fund_nav_state.json`:`count=26436 mode=增量 updated=2026-09-21T05:09:32`(全量成功写盘)
- 结论:被 kill 时数据大多已传完,只差进程收尾/状态写盘 → 告警是噪音(与 deploy.sh L555-557 注释记录的 09-10 事故同类:单文件 PUT 超时触发告警,实际上传与 purge 全成功)

---

## 四、落地建议(按优先级)

1. **verify-r2 首选根治**:
   - `scripts/deploy.sh` L554 verify-r2 窗口 1800→7200(与 fund-nav 同档);或周日拆两轮跑
   - `scripts/upload_r2.py` `s3_head` / `s3_request` 每次新建 HTTPSConnection → 改连接复用(同一连接连续 HEAD),对账时间可省 60%+(TLS 握手是最大开销)
2. **大文件 multipart**:`upload_r2.py` `_upload_glob`(L526-576)对 >XX MB 单文件走 create-multipart-upload → 并行 upload-part → complete(R2 支持,上限 4.995TiB);消除「单 PUT 卡 600s 超时 → 重试 5 次 → 单文件最坏 50min」的放大器
3. **告警降噪(立即可做,零风险)**:deploy.sh 收尾段(L929-936)notify 前对 R2_FAIL 通道做轻量对账(HEAD 抽查),数据完整则不告警/降级普通日志 → 90% 告警消失
4. **周日错峰**:实测凌晨全量成功、晚间失败 → 周日大通道(fund-nav/etf-hist/trade-sim-json)前移到带宽低谷段
5. **兜底保留**:`R2_UPLOAD_HTTP_TIMEOUT=600` + 5 次重试保留,但配合 multipart 缩短单次超时最坏值

**对用户一句话**:能根治到「基本不再看到」。根子是云上到 R2 的跨境带宽(实测 6KB/s~678KB/s 随机波动)撞上周日 ~1.1GB 全量 + verify-r2 周日全量对账必超窗口;三处代码改动(verify-r2 窗口/拆分+连接复用、大文件 multipart、告警前对账降噪)可消掉绝大部分;跨境物理带宽本身只能错峰 + 并行压平,没法靠代码变快。

---

## 五、社区/官方依据

- Cloudflare R2 官方 limits(云上已抓全文): https://developers.cloudflare.com/r2/platform/limits/
  - 单 PUT 上限 5GiB / multipart 上限 4.995TiB / 最多 10000 parts
  - 同 key 并发写 1/s(本项目不同 key,不受限)
  - r2.dev 端点速率限制(数百请求/s)+ **带宽(throughput)可能被限流** → 生产建议自定义域名
- R2 S3 API 兼容文档: https://developers.cloudflare.com/r2/api/s3/api/
- ⚠ 本轮 WebSearch / 社区论坛抓取被网络阻断(WebSearch 空返回、r.jina.ai 不通),社区讨论依据以官方文档为主

---

## 复现段

- deploy 日志位置:`/home/ubuntu/code/trade-data/data/logs/deploy_*.log`(云上 ssh `-i ~/tdsignal.pem ubuntu@122.51.111.173`)
- 失败扫描命令:`for f in $(ls -t .../deploy_*.log | head -40); do grep -n "超 .*s 未退出\|R2_FAIL\|告警] deploy R2上传失败" $f; done`
- 带宽实测:`curl -so /dev/null -w "%{speed_download}" https://ssd.fx8.store/data/overview.json`
- 对账验证:调研时另写 SigV4 HEAD 脚本(独立于项目 verify-r2),抽查 3 个关键文件 md5 全一致
- 数据口径:本报告所有「被 kill 通道数据无损」结论基于 2026-09-21 05:00 快照(verify-r2 全对账 0 补传 + state 文件),不代表被 kill 轮次绝对无损(极小概率 kill 恰在 PUT 中途),但 05:00 对账是最强实证
