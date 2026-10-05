# R2 上传管道残余风险登记(#180,2026-10-05)

> 来源:reviewer 报告 `docs/ops/r2fix-review-report-20261005.md`(审查 `9faf92d8e`)§必办项 2「[登记] 残余风险落档」。
> 定位:本文件是**残余风险登记件**,不是「已修复」声明——逐条写清「现状 / 是否已处置 / 触发条件 / 影响 / 后续」。
> 涉及代码:`scripts/upload_r2.py`、`scripts/r2_upload_async.sh`、`scripts/deploy.sh`。

---

## ㈠ 死循环「非结构性根治」——marker 残留 → 下轮 force_full(残余,未根除)

- **现状(残余)**:#174 已破**具体触发链**(备份由串行改 8 线程并行,2200s>900s kill 消除;900s 总时长判据**废弃**,ch_timeout 仅从参数剥离不再作 kill 判据)。但终止性**非结构性保证**。
- **触发条件**:任一 kill 类判据命中(停滞 300s / 低速近 5 分钟 / 7200s 硬兜底 / OOM / 进程被外部杀)→ 备份 marker 残留(`force_full=(not old_files) or today_weekday==6 or marker_stale`,`upload_r2.py` marker 写于 PUT 前、全成功才删)**不完整**→ 下一轮 `force_full=True` → 全量重备 → 若再次撞 kill → 再残留 → **仍可循环**。
- **影响**:不丢数据(§25 备份语义保持),但会重复全量备份、拉长窗口、放大告警。
- **为何未根除**:根除=让终止性不依赖「本轮是否被外部杀」——如 marker 分片提交 / 备份进度幂等可续 / 判据与备份阶段解耦。属**上传管道架构层改动**,非本次 #180 范围。
- **后续**:待专项设计(建议并入「上传管道韧性」议题);在此之前,**任何 kill 事件后应人工确认下轮未进入重复全量**。

## ㈡ 82 MiB 大文件单 PUT 300s 静默误杀(✅ 已处置:进度行消除静默窗;残留仅极小概率边界)

- **原风险(reviewer §④,置信度 80)**:`data-large` 通道含 `signal_kelly_trades.json` = **86,254,426 B(82.3 MiB)**,走单 PUT(<100MB multipart 阈值,`upload_r2.py` `_MULTIPART_THRESHOLD`)。实测吞吐 326-390KB/s ⇒ 该文件 **≈211-253s**,恰在 300s 停滞阈之下但**余量仅 ~47-89s**;带宽退化 **<~287KB/s** 时单 PUT 全程**零日志输出** → 停滞判据误杀 → `data-large` 死循环复发可能。且 §④ 已证 `data-large` 属 `batch_total<=10`,**低速判据不激活**,只有停滞判据覆盖 → 该风险只受 300s 静默窗约束。
- **处置(本 #180 实施)**:给大文件 PUT 体挂「字节流进度打点」(`scripts/upload_r2.py`):
  - 新增 `_ProgressBody`(`upload_r2.py:425`)——包装 `io.BytesIO`,在 `read()` 里累计已发字节,**每累计 `_PROGRESS_PUT_STEP`=4MiB 或每 `_PROGRESS_PUT_MAX_INTERVAL`=60s 至少打一行** flush 日志(`[{label}] ↑ 上传中 {已发}/{总} MiB ({增量}B)`)。阈值门 `_PROGRESS_PUT_MIN`=8MiB(`upload_r2.py:420`),小文件不打(秒级完成,免噪音)。
  - `s3_request` 增 `progress_label` 形参(`upload_r2.py:461`);命中时①显式设 `content-length`(否则 http.client 回落 chunked 破坏 SigV4)②用 `_ProgressBody` 作 body(`upload_r2.py:506-540`,每次重试重建)。
  - 接线:`_upload_glob._upload_one`(`upload_r2.py:909`)与 `_upload_multipart._put_part`(`upload_r2.py:791`,>=100MB 分片)均传 `progress_label`。
- **关键性质(为何不掩盖真故障)**:进度行**绑真实字节流**——`http.client` 以 `read(8192)`→`sendall` 循环推数据,**socket 真停滞时 `read()` 不再被调用 → 不再打点 → 停滞判据照常 kill**(真故障检测保留);仅「健康但慢」的传输因持续打点而免遭误杀。低速判据侧:进度行含 `(NB)` 增量能被 `\([0-9]+B\)` 累计(实测字节和增长),且不含 `[N/M]` 不污染 batch 解析。
- **处置后仍存的最小残留(登记)**:
  - 门限 **8MiB 以下**的单 PUT 不打点;理论上「7MiB 文件 + <~23KB/s 极慢链路」可 >300s 静默被杀。概率极低(该尺寸通常秒级),**当前不单独处理**,列此备查。
  - 打点间隔上限 60s,远小于 300s 阈值,余量充足;除非「socket 半死(可写但极慢)到 60s 内一次 `read` 都不返回」,否则不打点间隔不会逼近 300s。
- **自测证据**(见文末复现段):看门狗仿真「修复前静默被误杀 / 修复后放行」对照 PASS;单元三场景(快/慢/停滞)PASS;R2 端到端(隔离桶)SigV4+Content-Length+md5 一致 PASS。

## ㈢ 减量(dedup)判据对 B/C 档指纹通道永不触发(残余,未处置)

- **现状(残余)**:`_incremental_upload` 三档指纹:A 档=整文件 raw md5;B 档=`_kelly_parts_md5`;C 档=`_etf_hist_md5`。减量跳过判据比对 **R2 当前 etag(=原始文件 raw md5)** vs **本地将传 md5**。B/C 档指纹**剔除/变换了字段**(如 C 档剔 `exported_at`,`upload_r2.py` etf-hist `fingerprint=_etf_hist_md5`;kelly-parts/sdc 用 `_kelly_parts_md5`),两量**不可比** → **`skip` 对这些通道永不成立** → 每轮全量重备(etf-hist 1718 key)。
- **影响**:减量优化实际**只对 A 档生效**;B/C 档通道每轮全量重备(靠 8 线程并行把耗时压到可接受,**不是靠减量**)。
- **为何未处置**:修复需统一「指纹口径 ↔ etag 口径」——要么让 B/C 档的比对基准也落到「能在 R2 端读到的量」,要么为 B/C 档引入可存取的指纹 sidecar 对象。属**指纹设计层改动**,有 §25 安全语义牵连(比对量换错会致漏备份/裸覆盖),须专项设计+review,**非本次 #180 范围**。
- **安全提示**:当前偏差方向**保守安全**(比对不等 ⇒ 只多备不少备),无裸覆盖风险;但**不得**为「省流量」草率把 B/C 档比对量改成剔除字段后的哈希——会引入「本地变了但比对相等 ⇒ 跳过备份」的裸覆盖漏洞。

---

## 同类错误面 / 举一反三(§23.2 / §23.3:静默误杀还波及谁)

- **同模式(单 PUT 静默)的判定域 = 谁受 #174 看门狗管辖**。#174 停滞/低速判据只存在于 `scripts/r2_upload_async.sh:run_r2_upload`(deploy.sh 无第二份,reviewer §⑥ 已证)。故「单大文件静默 >300s 被误杀」**只可能发生在其管辖通道**:`upload-lab / upload-trade-sim / upload-trade-sim-json / upload-index / upload-etf-hist / upload-accum-nav / upload-industry / upload-public-fund / upload-etf-score / upload-data-large / upload-kelly-parts / upload-kelly-parts-sdc / upload-all-data / upload-kelly-snapshots / upload-feed / verify-r2 / purge-low-freq`。
- **这些通道的数据上传全部经 `_upload_glob`(单 PUT ≤100MB / multipart >100MB)或 `_incremental_upload`(内部同样调 `_upload_glob`)** → 本次 `progress_label` 已在 `_upload_glob._upload_one`(`upload_r2.py:908`)与 `_upload_multipart._put_part`(`:789`)统一接线 → **同模式全覆盖**,无遗漏旁路。
- **不受影响的旁路 PUT(已逐个核对,均不在看门狗管辖)**:
  - `cmd_upload`(`:703`,CLI `upload`,手动/非看门狗通道);
  - `cmd_upload_db`(`:2283`,由 `backup_db.sh` 调用)、`cmd_upload_decommissioned`(`:2324`)、`cmd_upload_claude_backup`(`:2357`,由 `backup_claude_self.sh` 调用)、`_maybe_upload_weekly/_monthly`(`:2170/:2193`)、`cmd_upload_large_json`(`:2792`)—— 这些**不经 `run_r2_upload`**,无 300s 停滞判据 ⇒ 无此回归。
- **结论**:㈡ 的修复面 = 全部看门狗通道的大文件单 PUT,已完整覆盖;**残余仅为门限 8MiB 以下的极小文件**(见 ㈡ 末「最小残留」)。

---

## 附:相关判据/常量锚点(便于反查)
- 看门狗主判据(停滞 300s `R2_UPLOAD_STALL_SECS`)/ 辅判据(低速:batch>10 且近 5 采样增量<1MB)/ 7200s 硬兜底:`scripts/r2_upload_async.sh:run_r2_upload`(L78-151)。deploy.sh 无第二份定义(仅触发)。
- 单 PUT / multipart 阈值:`scripts/upload_r2.py` `_MULTIPART_THRESHOLD`=100MB。
- 打点常量:`upload_r2.py:420-422`(`_PROGRESS_PUT_MIN/STEP/MAX_INTERVAL`)。

## §23.5 复现段(如何复核本登记)
1. **㈠**:`grep -n "force_full\|marker" scripts/upload_r2.py | head`(marker 语义)+ `grep -n "R2_KILLED\|停滞\|低速\|7200" scripts/r2_upload_async.sh`(kill 分支)。
2. **㈡**:`ls -l static-site/data/signal_kelly_trades.json`(=86,254,426);`grep -n "_PROGRESS_PUT_MIN\|class _ProgressBody\|progress_label" scripts/upload_r2.py`;三项自测见文末命令。
3. **㈢**:`grep -n "_etf_hist_md5\|_kelly_parts_md5\|fingerprint=" scripts/upload_r2.py`(etf-hist=C 档、kelly-parts/sdc=B 档)。
4. **自测复现命令**(#180 验收口径):
   - 看门狗仿真对照:`bash /tmp/test_watchdog_180.sh` → 期望 `PASS: 修复前静默被误杀, 修复后有进度行放行`。
   - 单元三场景:`/Users/linhuichen/code/trade/.venv/bin/python /tmp/test_progress_body.py` → `单元自测 PASS`。
   - R2 端到端(隔离桶 `signal-backup2`,测后自清):`bash /tmp/run_e2e_180.sh` → `端到端自测 PASS`。

## 配套 commit
本登记件 + 归档件 + `upload_r2.py` 打点改动同落 #180 的 feat 分支(commit 见分支 HEAD)。