# R2 上传死循环修复 review 报告(归档件)

> §23.5 四件套归档:① 报告本体(下方全文)② 生成来源(审查 agent + 被审 commit)③ 复现段 ④ 配套 commit。
- **生成来源**:reviewer agent `worktree-agent-a32eca2ef3e40884f`,审查对象 = `9faf92d8e`(R2 上传死循环修复改动面 `scripts/upload_r2.py` + `scripts/r2_upload_async.sh`,162+/43−),该支已 merge main(`4b88a1251`)。
- **审查日**:2026-10-05。方法 = diff 全文逐字复核 + 低速判据管道实测 + 备份桶只读 LIST 实证。
- **后续处置**:本报告 §必办项由 #180 落地(① 40 垃圾 key 清理 ✅ / ② 残余风险落档 ✅ `docs/ops/r2-residual-risks-20261005.md` / ③ 大文件通道兜底 ✅ `_ProgressBody` 打点)。
- **原始副本**:`/tmp/r2fix-review-report.md`(临时,不 track);正式归档 = 本文件。

---

## 报告正文

# R2 上传死循环修复 review 报告(worktree-agent-a32eca2ef3e40884f @ 9faf92d8e)
Reviewer 独立审查,2026-10-05。改动面:scripts/upload_r2.py + scripts/r2_upload_async.sh(162+/43−)。本报告基于 diff 全文逐字复核 + 低速判据管道实测 + 备份桶只读 LIST 实证。

## 总体判定:**有保留 PASS(可 merge 入 main)** —— 3 个必办登记/清理项 + 1 个建议项,无 P0 裸覆盖风险。

---

## ① §25 安全属性(减量判据能否被绕过导致裸覆盖):**PASS(保守安全)** 置信度 95
判据(upload_r2.py:1033,已验证):`bk_st==200 and local_md5 is not None and etag is not None and etag.strip('"')==local_md5`
跳过充要条件=「备份桶已有今天备份 **且** R2 当前 etag == 本地将传 md5」。注意:比对的是 **R2 当前内容 vs 本地将传**,不是备份内容 vs 将传——但这恰是正确安全量:PUT 只覆盖 R2 当前内容,若 R2 当前==将传,覆盖本身字节级无损失,再加备份已存在,双保险。
- 攻击①本地文件变了:local_md5=新、R2 etag=旧 → 不等 → 必备份。无法绕过。
- 攻击②备份桶旧/半成品副本:服务端 COPY 原子(200=完整对象);kill 中断的 COPY 要么无 key(bk_st!=200→重备)要么完整 200。
- 攻击③multipart etag `xxx-N`:永不等于 32-hex md5 → skip 永不触发 → 永远备份。安全方向。
- 攻击④首次上传/备份桶无备份:st!=200→return 0(新 key 无覆盖);bk_st!=200→必 COPY。
- **语义偏差(安全但优化失效)**:etf-hist 用 C 档指纹 `_etf_hist_md5`(剔除 exported_at,upload_r2.py:1449 `fingerprint=_etf_hist_md5`),kelly-parts/sdc 用 `_kelly_parts_md5`(L1626/1642),R2 etag=原始文件 raw md5 → 两量**不可比** → **减量对 B/C 档指纹通道永不触发**(etf-hist 1718 key 全量重备)。accum-nav 等 A 档(raw md5)skip 生效。死循环靠 8 线程并行破,不是减量。

## ② 终止性(死循环真的破了吗):**大幅降低触发概率,非结构性根治;残余风险未登记** 置信度 90
- 具体触发链已破:备份串行 2200s>900s kill 已消除——并行后 etf-hist 备份 ~322-650s,且 900s 总时长判据废弃(ch_timeout 仅剥离不再作 kill 判据,已验证)。
- force_full=(not old_files) or today_weekday==6 or marker_stale(已验证 marker 写于 PUT 前、全成功才删)。
- **残余**:若仍被杀(停滞 300s / 低速 5min / 7200s 硬兜底 / OOM),marker 残留 → 下轮 force_full → 仍可循环。非结构性终止保证,且**未在任何代码注释/文档登记此残余**。

## ③ 多线程正确性:**PASS**,1 个 cosmetic 计数竞态 置信度 85
- 连接:keep_alive 用 `threading.local()`,8 worker 各自独立 HTTPSConnection,不共享不串包。
- 异常:worker `_backup_one` 全程 try/except 包裹永不抛;即便异常也被调用方 try/except 记日志继续(既有 fail-soft 设计)。
- 部分失败语义:记日志、copied 不增、下轮补;「整批备份完→整批 PUT」,§25 语义保持。
- cosmetic:`copied/skipped` nonlocal += 在 worker 线程,CPython GIL 下可丢更新,只影响进度显示与末尾 `if copied:` 打印,无功能影响。

## ④ 停滞/低速判据判据源:**PASS,但发现 1 个低概率真实回归风险** 置信度 80
- 判据源=tmp_log;upload_r2.py:39 `sys.stdout.reconfigure(line_buffering=True)` → 每行 print 即 flush → mtime 实时,无 Python 块缓冲误杀。
- 备份进度行(每 64)/verify-r2 进度行(每 100)均带 flush → 日志滚动,健康工作不被误杀。
- 低速判据解析:`\([0-9]+B\)` 只匹配 _upload_glob 的 `(sizeB)`;备份进度行刻意无 `(sizeB)` 无 `[N/M]`。**逐字+管道实测验证**:①完整管道 `[3/100] ✓ f (12345B)` → _upb=12345、两行累加=19134(正确);②`[3/100]` → batch_total=100;③备份行 `[upload-etf-hist] 备份 128/1718 已备份 128 跳过 0` 对 `\([0-9]+B\)` 匹配 0 次、对 `\[[0-9]+/[0-9]+\]` 匹配 0 次(不污染)。batch_total>10 才激活低速判据 ⇒ data-large(2 个文件≤10)不激活,只有停滞判据覆盖 → 大文件回归风险只受 300s 静默约束。
- **回归风险**:单个大文件单 PUT 期间**零日志输出**。本地实测最大单文件 signal_kelly_trades.json=86,254,426B(82.3MiB),走 data-large 单 PUT(<100MB multipart 阈值,upload_r2.py:323)。实测吞吐 326-390KB/s(根因文档 L55)⇒ 82.3MiB≈211-253s,恰在 300s 停滞阈值之下但余量仅 ~47-89s;带宽退化 <~287KB/s(≈300s)时静默 → **停滞判据误杀 → data-large 死循环复发可能**。旧字节估算(该场景给 ~1386-2426s)本可覆盖 → 这是新判据对「健康慢大文件」的回归。

## ⑤ R2_KILLED 传递链:**PASS** 置信度 90
链(已逐字验证):r2_upload_async.sh:57 初始化 ""(主 shell)→ 三处 kill 分支 `R2_KILLED="$R2_KILLED $desc"`(停滞/7200s/低速)→ finalize_verify `R2_KILLED="$R2_KILLED" "$PY" ... verify-channels`(env prefix 显式传子进程)→ upload_r2.py:3211 `set((os.environ.get("R2_KILLED") or "").split())`。
- 未设:get→None→or ""→空 set,行为=旧轻量对账。为空:同。未导出:prefix 显式传递不依赖 export。三种情况行为明确且安全。
- verify-r2 被 kill 时 R2_FAIL 含 verify-r2 → L3204 D-1 规则先 exit 1,killed 分支冗余无害。

## ⑥ §23.2 同类错误面(独立复核):**PASS** 置信度 85
- deploy.sh **无第二份** run_r2_upload 定义/调用(仅注释;R2 全部收敛 r2_upload_async.sh,deploy.sh L586/L604/L629 只触发脚本)。✓
- 无通道仍被 900s 总时长判死:ch_timeout 剥离后无 kill 引用。✓
- 同「总耗时 kill」模式残留(域不同,非 R2 数据上传同病):deploy.sh git fetch/push timeout(120s,git 域,有意释放锁);**staticdata_backup_async.sh:407-423 git push 900s**(同模式但后果=下次重试、无数据丢失、有告警);fund_nav_upload_async.sh 无看门狗。staticdata push 900s 值得留意但非本改动范围。

## ⑦ §15 回归影响面:**列清单,无阻塞** 置信度 85
- r2_upload_async.sh:唯一调用方 deploy.sh 3 处触发;改动=看门狗机制(正向)。
- upload_r2.py `_incremental_upload` 16 通道(lab/trade-sim/trade-sim-json/index/etf-hist/fund-nav/accum-nav/industry/public-fund/etf-score/kelly-parts/sdc/kelly-snapshots/data-large/all-data):备份并行+减量+进度,请求数 +1 HEAD/key(微小),正向。
- upload-data-files(fetch_news `--skip-if-locked`)/upload-intraday:走 _upload_glob,不经 _incremental_upload → 不受备份改动影响;fetch_news 直调 upload_r2.py 不经 run_r2_upload → 无看门狗影响。不受影响。
- etf_national_team_backfill.sh:112 直调 upload-etf-hist → 受备份并行影响(正向加速)。
- verify-r2:进度行新增(正向);verify-channels 仅在 async 收尾,不受其他调用方影响。
- check_r2_consistency.py / sync_dev_from_r2.sh:独立脚本/只读版,不受影响。

## ⑧ §23.7 / §5.4⑥:**不触达用户功能默认行为,不需要发版本** 置信度 85
改动=上传管道内部机制(备份并行/看门狗判据/告警),上传数据内容/口径/前端展示零变化;verify-channels 解静音=运维告警维度(memory alert-denoise-keep-fault-discriminator 匹配)。不涉及 AI 推荐/降亏过滤默认组合/算法。§5.4⑥「动默认组合/算法才发版本」不触发。

## ⑨ 自验可信度:**数字可信;但留测试垃圾 + 减量自测与生产行为脱节** 置信度 85
- bench 数字(串行47.7s→并行9.1s@40key):RTT 0.4-0.65s 推算吻合,可信。1718 外推 34min→6.5min 与任务背景一致。
- 看门狗测试(/tmp/test_watchdog.sh+log):假命令验证停滞 kill 生效,R2_KILLED 记录正确,无生产影响。可信。
- **测试垃圾(实测只读 LIST 确认)**:备份桶 `pre-upload/20261005/bench-serial/etf/*.json` = **40 个 key**(bench 串行组写入),**待清**;并行组另刷新 40 个 etf 备份 key(同内容幂等,无害)。
- 减量 40/40 跳过自测:无脚本留存,无法复核;**且若用 etf key + 原始 md5 测,结果与生产(etf-hist C 档指纹 → skip 永不触发)不符** → 自测口径可能与生产行为脱节。

---

## 必办项清单(merge 前/随 merge 完成)
1. **[清理] 备份桶 40 个测试垃圾 key**:删除 `pre-upload/20261005/bench-serial/`(原数据在 R2 主桶仍在,删除可逆,§25 满足)。
2. **[登记] 残余风险落档**(代码注释或 TASKS/文档):
   a) kill 后 marker→force_full 死循环**非结构性根治**(停滞/低速/7200s/OOM 触发仍循环,非确定性);
   b) 单大文件 >300s 静默 PUT 在带宽 <~287KB/s 时被停滞判据误杀 → data-large 死循环复发可能(旧字节估算本可覆盖);
   c) 减量判据对 B/C 档指纹通道(etf-hist/kelly-parts)永不触发,减量优化实际只对 A 档生效。
3. **[建议] 大文件通道兜底**:对 data-large 等含大文件通道,上传阶段每文件开始/完成打一行 flush 进度(一行 print 即消除 300s 静默窗口),或对含 >100MB 单文件的通道保留字节估算下限。

## 置信度过滤说明
进报告的 finding 均 ≥80。另滤掉 <80 的低分项(计数竞态 cosmetic、低速判据首采样边界、purge-low-freq 静默、bdata 错误体污染等),不构成阻塞。

---

## §23.5 复现段(如何复现本报告结论)
只读,不写 R2(除标注外):
1. **改动面 diff**:`git show 9faf92d8e -- scripts/upload_r2.py scripts/r2_upload_async.sh`(162+/43−)。
2. **§④ 大文件实测**:`ls -l static-site/data/signal_kelly_trades.json` → 应为 86,254,426 B(82.3MiB);`grep -n _MULTIPART_THRESHOLD scripts/upload_r2.py`(100MB 阈值)→ 该文件走单 PUT。
3. **§④ 吞吐口径**:见 `docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md` L55 实测 326-390KB/s → 82.3MiB≈211-253s。
4. **§① 减量指纹口径**:`grep -n "_etf_hist_md5\|_kelly_parts_md5\|fingerprint=" scripts/upload_r2.py`(L1449 etf-hist=C 档、L1626/1642 kelly-parts/sdc=B 档)。
5. **§⑥ 无第二份看门狗**:`grep -rn "run_r2_upload" scripts/`(应只在 r2_upload_async.sh 定义 + deploy.sh 触发)。
6. **§⑨ 垃圾 key(只读 LIST)**:`python /tmp/verify_bench_gone.py`(桶 `signal-backup` 前缀 `pre-upload/20261005/bench-serial/etf/`,该前缀现已清空=0,详见 #180 ①)。

## 配套 commit
本归档件随 #180 修复提交一同落 feat 分支(见 `docs/ops/r2-residual-risks-20261005.md` 引用同一 commit)。