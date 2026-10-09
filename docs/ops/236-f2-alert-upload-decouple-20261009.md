# #236 F2 实施报告:预警数据独立上传 R2 —— 解开 deploy 校验自锁(2026-10-09)

> 实施 agent 落档,2026-10-09(本阶段含独立审查 FAIL-1/FAIL-2 修复)。代码改动仅 1 个文件(`scripts/update_all.sh`);R2 写只在测试期发生(**先备份**、内容逐位未变,幂等);**零告警/邮件/飞书外发**。
> 前置:`docs/ops/deploy-selflock-recon-20261009.md`(只读核查,§5 F2 方向);`docs/ops/236-f2-alert-upload-decouple-review-20261009.md`(独立审查)。

## 0. 一句话结论

在 deploy 主链之外(update_all.sh 两个 export 之后 + `etf_score_list` 块之后,共两处)加了**独立、失败不阻断、留痕不静默**的 `upload_r2.py upload-data-files alert.json alert_analyze_*.json`(**带 `--skip-if-locked`**),使 R2 侧的 alert.json 不再依赖 deploy 自身。**「读 R2 的闸门拦住了它自己输入的唯一运输通道」这一结构死锁被解开**:即使某天 deploy 被 check_alert 拦住,当轮 update_all 已把新 alert.json 推上 R2,闸门下次自然放行 —— **把「永久锁」降级为「下一轮 update_all 自解锁」,典型时延 ≤1 个自然日**。

> **⚠ 前提(2026-10-09 审查 FAIL-2 修订,勿再写「不再需要人工解锁」这类无条件保证)**:自解锁只在**锁未长期被占**时成立。遇到**「长假后首日 fund_nav 全量重传」这类长锁日**,F2 的两次尝试都可能拿不到锁(10-08 实证:fund_nav 异步锁 18:28:38→19:36:48 共 **4089.8s**,而 F2 首次窗口 ≈19:30:50 完全落在锁内 ⇒ 必然 `SKIPPED_LOCKED`;二次窗口在 etf_score_list 之后 ≈19:37 才可能拿到)。**这类日子恰恰就是「最需要自解锁」的日子**,因此**自解锁最多顺延 1 天**(次日锁短、F2 正常落地);顺延期间 deploy 侧 check_alert 的 severe 告警**持续可见**(不会静默),且无数据损坏 —— 影响边界=「自解锁延迟」,非事故级。**根本修复(#237 fund_nav/large-json 分片持锁,把 68 分钟长锁变短)由另一任务负责,F2 不依赖它**;F2 在当前现实下靠「双次尝试」尽力落地(见 §3-b)。

## 1. 改了什么(改动点)

**唯一文件:`scripts/update_all.sh`**(相对 main 本阶段:改 3 处)。

| 位置 | 内容 |
|---|---|
| L174-176(C6 注释) | 口径更新:原「alert.json 本地更新,下次 pipeline deploy 推上线」→ 改为「本地更新 + 随下方 #236 F2 独立上传推 R2(首次/二次尝试)」 |
| L187-237(F2 首次尝试块) | 30+ 行注释(死锁结构/修法/锁竞争口径/失败策略/先例)+ `alert_r2_upload()` 函数 + 3 行调用(窗口 60s) |
| L263-274(F2b 二次尝试块) | 门控调用:仅当首次未成功(`ALERT_R2_TRY1≠0`)时才在 `etf_score_list` 块之后再刷一次(窗口 120s) |

核心逻辑(`scripts/update_all.sh` L216-237,函数 + 首次调用):

```bash
alert_r2_upload() {
  local win="${1:-60}" tag="${2:-}" out rc
  out="$( cd "$REPO/static-site/data" && R2_UPLOAD_SKIP_RETRY_SECS="$win" \
          "$PY" "$REPO/scripts/upload_r2.py" --skip-if-locked \
          upload-data-files alert.json alert_analyze_*.json 2>&1 )"
  rc=$?
  printf '%s\n' "$out" >> "$LOG"   # 原文入日志（留痕，不静默）
  if [ "$rc" -ne 0 ]; then
    echo "⚠ ... ${tag}失败(rc=$rc, 不阻塞主流程) ..." | tee -a "$LOG"; return 1
  fi
  if printf '%s' "$out" | grep -q "SKIPPED_LOCKED"; then
    echo "ℹ ... ${tag}被锁跳过(等锁 ${win}s 未得, 未写入 R2)" | tee -a "$LOG"; return 2
  fi
  echo "✓ ... ${tag}完成（alert.json + alert_analyze_*.json）" | tee -a "$LOG"; return 0
}
echo "-> 预警数据独立上传 R2（首次尝试 ...）..." | tee -a "$LOG"
alert_r2_upload 60 首次
ALERT_R2_TRY1=$?
```

二次尝试(L263-274):

```bash
if [ "${ALERT_R2_TRY1:-1}" -ne 0 ]; then     # 仅首次未成功才跑（无冗余 PUT）
  echo "-> 预警数据独立上传 R2（二次尝试；首次 rc=${ALERT_R2_TRY1}）..." | tee -a "$LOG"
  alert_r2_upload 120 二次
fi
```

**为什么两段、为什么放在这两处**:首次紧跟 C6(`export_alert`)与 C7(`export_alert_analyze`)之后 —— 本地 alert.json / alert_analyze_*.json 刚写完、内容最新那一刻;**二次落在 `etf_score_list` 块之后** —— 该块内的 `upload-etf-score` 不带 `--skip-if-locked` 会**排队等锁**(10-08 实测排队 **222s**,即 3 分 42 秒),它返回时锁刚释放 ⇒ 二次大概率即拿到锁,当夜即可自解(见 §3-b 时序证据)。

**关键实现细节(踩过的坑,勿回退)**:

1. **必须 `cd "$REPO/static-site/data"` 包一层**。`upload_r2.py cmd_upload_data_files` 把每个参数当**相对 data_dir 的 glob**,但先用 `(data_dir/f).exists()` 预过滤 —— 字面量 `alert_analyze_*.json` 传进去会被 `exists()` 判否而**静默丢弃**。所以必须让 **shell** 先展开 glob,再传基名进去。
2. **必须带 `--skip-if-locked`**。默认锁行为是**排队等锁最多 7300s**(会拖住 update_all)。带此 flag 后:拿不到锁就短重试(`R2_UPLOAD_SKIP_RETRY_SECS`,**每次调用读环境变量**,故可逐次设窗口),仍未拿到则打印 `SKIPPED_LOCKED: ...` 到 stderr 并 **exit 0**。本实现:首次窗口 **60s**、二次窗口 **120s**(仅在被锁时计时,拿不到即退,**绝不排队 7300s** ⇒ 不阻塞主链;对照:本链 `upload-etf-score`/`upload-fund-score` 本就排队等锁,10-08 曾等 222s)。选它是为了「既不阻塞主链、又不与主链既有上传打架」(见 §3)。
3. **必须带 `REPO=` 且必须 export**(`update_all.sh` 上方 L37 已有 `export REPO GIT_REPO`,#75 显式导出确保子进程继承)。云上 `upload_r2.py:_find_env()` 候选路径中**唯一存在**的是 `REPO/.env`(=`/home/ubuntu/code/trade-data/.env`);`GIT_REPO/.env`(=`…/trade-data-signal/.env`)**不存在**。故若 `REPO` 只在脚本内赋值而未 export,**子 python 看不到** ⇒ 报「无 .env」exit 1(本阶段测试装置曾踩此坑,生产代码 L37 已正确 export,无需改)。
4. **rc 用命令替换后的 `$?` 捕获**(不是管道 `PIPESTATUS`)——因为输出已 `2>&1` 收进变量,再 `printf` 落日志。

## 2. 死锁为何被解开(结构说明)

**死锁结构(已取证,`deploy-selflock-recon-20261009.md` §2)**:

```
deploy.sh  L323-324  check_data_integrity  ← 读【线上 R2】的 alert.json 判新鲜度
deploy.sh  L326-331  rc≠0 → notify(severe) + exit 1(硬终止)
deploy.sh  L582      触发 r2_upload_async(此时才 upload-all-data,alert.json 的唯一 R2 通道)
```

拦截点(L324)**早于**写入触发点(L582),且 `static-site/data/*` 已全量 gitignore(**无 git 旁路**,`git check-ignore` 已证)→ 一旦 R2 侧 alert.json 滞后 >7 自然日,deploy 永久锁死,且 **deploy 内无 check 跳过开关**(grep 已复核)。

**为什么现在解开**:新步骤把 alert.json 的上传**移出 deploy 主链**。deploy 被拦 ⇒ 本地 alert.json 已是新版 ⇒ 当轮(首次或二次)update_all 跑完,新 alert.json 已上 R2 ⇒ 明/后日 deploy 的 check_alert 读到的是新鲜副本 ⇒ 放行。闸门不再拦自己输入的唯一通道。

**注意(诚实标注,非本任务范围)**:
- F2 **单修**只能把「永久锁」降级为「自解锁(等下一轮 update_all)」;**遇到长锁关键日(§3-b)自解锁可能顺延 1 天**(次日锁短,F2 正常落地),期间 severe 告警持续可见。
- 长假中「本地也旧」的场景(如 10-08 02:06 六项全 20260930)**仍会被拦**,那是 #235 交易历口径的事(F1,另一任务)。
- **两件叠加 = 事件不发生 + 结构死锁消除**(recon §4)。

## 3. 反例核对(不冲突 / 不违反 §22 / 不静默)

- **不双重上传、不竞态**:靠 `--skip-if-locked` 天然互斥 + 二次尝试的**门控**(仅首次未成功才跑)⇒ 同一轮内**不会**两路同时写同一 key,也不会对同一内容做第二次 PUT。
  - **锁竞争口径(2026-10-09 审查 FAIL-2 修订,勿再写「主链一定覆盖同 key」)**:
    - *正常日*:锁主多为主链 R2 上传(`r2_upload_async`)⇒ 本步跳过;其 `upload-all-data` 稍后会写同 key(内容一致)⇒ **本轮无人重复写,且 key 最终是最新**。
    - *长假后首日(如 10-08)*:锁主是 **fund_nav 等长锁任务**,**不是**主链上传;主链 `r2_upload_async` 当天**因 deploy 被拦根本没跑** ⇒ 此时【**本轮无人覆盖同 key**】。F2 二次尝试(落在 etf_score_list 之后,≈19:37 > 锁释放 19:36:48)是当夜唯一的落地机会;若二次也拿不到锁 ⇒ **自解锁顺延到次日更新窗口**(典型 ≤1 天,期间 check_alert 的 severe 告警持续可见)。
    - 结论:**「谁覆盖同 key」取决于锁主是谁**;F2 的价值正是在「锁主非主链上传」的关键日提供第二个落地窗口,而不是依赖主链兜底。
- **§22 多展示位一致**:`alert.json` 与 `alert_analyze_*.json` **同批同源**上传(同一命令),不会出现「alert 新 / analyze 旧」的展示位不一致;deploy 侧 check_alert 与前端读的是同一 R2 副本。
- **§23.11 不静默**:三态分支各自 `tee -a "$LOG"` 留痕(成功✓/被锁ℹ/失败⚠),且失败分支的 upload 全文也 `printf >> "$LOG"`。失败**不阻断** update_all 主链,但**有痕迹**。
- **持续失败的可见性兜底**:不新增告警通道 —— 由 deploy 侧 `check_alert` 对 R2 新鲜度的判定(超阈值 → severe 邮件/飞书)独立兜底。本步只是「供应方」,「质检方」仍是原有闸门。
- **§21 算法公示**:本改动是**上传管道**,不动任何算法/数值/口径/字段,无公示文案需同步。
- **§23.4 同模块冲突**:`docs/pending-features-index.md` #236 行(待拍板)+ 同模块 update_all.sh 的 #212/#207/#201 均不落在我插入的 L187-237 / L263-274 两区间,无覆盖。

### 3-b. 10-08 时间窗重叠证据(FAIL-1 的立论依据,云上日志重建)

> 下表**前 5 行 = 实测**(云上日志/锁文件,数字自洽);**后 2 行(F2/F2b 窗口) = 推演值** —— 基于实测时点 + 代码上线后各段顺序/耗时推算,未见当日实跑日志(当日该代码尚未上线)。

| 事件 | 时点(北京时间) | 证据 / 性质 |
|---|---|---|
| fund_nav 异步长锁 **起** | 18:28:38 | `r2_upload_async_fund_nav` 日志(255/256 桶全量重传)· **实测** |
| C6/C7 alert 导出完 | ≈19:29:45 | update_all 日志 export_alert/export_alert_analyze 行 · **实测** |
| etf_score_list 导出(138.7s) | ≈19:30:47→19:33:06 | 同上 · **实测** |
| **upload-etf-score 排队等锁 222s**(3 分 42 秒) | 19:33:06→≈19:36:48 | 期间无输出 ⇒ 等锁 · **实测** |
| fund_nav 异步长锁 **释放**(4089.8s) | 19:36:48 | 锁文件 + 日志 · **实测** |
| **F2 首次窗口**(60s) | ≈19:30:50 | 完全落在 18:28:38→19:36:48 锁内 ⇒ **必然 SKIPPED_LOCKED** · **推演值** |
| **F2b 二次窗口起点** | ≈19:37(etf_score_list 之后) | **> 19:36:48 释放点** ⇒ 当夜即可自解 · **推演值** |

**结论**:①「最需要自解锁的日子 = 锁最被占的日子」这一结构性事实成立 ⇒ 单次尝试不够,故加二次;②二次位置选在 etf_score_list 之后,正是利用「upload-etf-score 排队等锁(222s)→ 返回时锁刚释放」这一既有节奏 ⇒ 二次大概率命中。

## 4. R2 实测证据(写侧=云上;内容幂等,多次 PUT 内容逐位不变)

写侧环境 = 云上(`/home/ubuntu/code/trade-data`,唯一合法 public R2 写侧;mac dev 树被 export-guard L2 拦,exit 2)。

**A. 首版单次上传(前一阶段,建立基线)**

| 步骤 | 命令/结果 | 证据 |
|---|---|---|
| ① 先备份(§25) | 上传前把现网 alert.json 落 `/home/ubuntu/backup/f2-236-20261009/alert.json.before` | `md5 = 65c60ad5378e4179a40bfacb69c08352` |
| ② 上传前基线 | `ssd HEAD /data/alert.json` | `etag="65c60ad5378e4179a40bfacb69c08352"`,`LM=Thu 08 Oct 2026 17:08:04 GMT` |
| ③ md5 核对(本地==现网==待传) | 备份 md5 == 上传前 R2 etag == 65c60ad5 ⇒ **内容一致** | 三者同值 |
| ④ 真上传 | `cd .../static-site/data && REPO=... upload_r2.py upload-data-files alert.json` | `[1/1] ✓ alert.json (3205B)` + `Cache purge 完成: 全部 1 批成功, 共 purged 1/1 keys` + `EXIT=0` |
| ⑤ 上传后 R2 直连 | `ssd HEAD /data/alert.json` | `LM=Fri 09 Oct 2026 08:26:23 GMT`(**已推进**),`etag=65c60ad5…`(**未变**) ⇒ 真发生过 PUT 且内容逐位未变 |
| ⑥ CF 侧读取 | `ss.fx8.store/data/alert.json` GET | `md5 = 65c60ad5…`(与源一致,缓存已清) |

**B. 两段式针对【真实生产锁】实测(本阶段,FAIL-1 修复后)**

T1 —— **真锁被占(首次跳过)+ 二次拿到锁(当夜落地)**,窗口取生产值 60s/120s:

| 步骤 | 结果 | 证据 |
|---|---|---|
| 真锁状态 | 真生产 `r2_upload_async`(17:08 启动)持锁 | 云上进程在册,锁 `/tmp/trade_r2_upload.lock` 被占 |
| ① 首次尝试(win=60) | `ℹ 预警数据独立上传 R2 首次被锁跳过(等锁 60s 未得, 未写入 R2)` | 返回 **rc=2**;日志含 `SKIPPED_LOCKED` 原文(**留痕不静默**) |
| ② 二次尝试(win=120) | **成功** | `[71/71] ✓` + `Cache purge 完成: 全部 3 批成功, 共 purged 71/71 keys`(**alert.json + 全部 alert_analyze_*.json 同批**) |
| ③ 写后 R2 直连 | `etag="65c60ad5378e4179a40bfacb69c08352"`(**不变**),`LM=Fri, 09 Oct 2026 09:16:23 GMT`(**已推进**) | 真发生过 PUT 且内容逐位未变 |
| ④ CF 侧读取 | `md5 = 65c60ad5…` | 与源本地 md5、备份 md5 **四路一致** |
| ⑤ 门控验证 | 首次成功 ⇒ 不跑二次(stub 计数 1 次调用);首次跳过/失败 ⇒ 二次才运行 | **无冗余 PUT、无双重上传** |

T2 —— **真锁全程被占时两段都跳过(零写)**(窗口缩到 4s 仅为省时间,验证跳过分支;生产值为 60s/120s):

| 步骤 | 结果 | 证据 |
|---|---|---|
| ① 首次尝试(win=4) | `ℹ ... 首次被锁跳过(等锁 4s 未得, 未写入 R2)` | **rc=2**,日志一行 `SKIPPED_LOCKED` |
| ② 二次尝试(win=4) | `ℹ ... 二次被锁跳过(等锁 4s 未得, 未写入 R2)` | **rc=2**,日志两行 `SKIPPED_LOCKED` |
| ③ 零写校验 | `ssd HEAD /data/alert.json` | `LM 仍=Fri, 09 Oct 2026 09:16:23 GMT`(**未变**)、`etag=65c60ad5…` ⇒ **确未写入 R2** |
| ④ 不阻塞验证 | 两段总耗时 ≈8s(仅窗口时长)后立即返回,父脚本继续 | 未排队 7300s ⇒ **不阻塞主链** |

**时点纪律**:T1 上传发生于 **2026-10-09 17:16(北京)**(=09:16 GMT),距当日禁区时点(15:35/16:00/17:50/20:35/22:00)均 >10 min,且所写内容 = 当前权威最新版(内容未变)。

**本地三态 harness 自测**(stub 化 upload_r2.py,非生产):ok/skip/fail 三态分别 → ✓ / ℹ / ⚠ 分支且父脚本**不中止**(fail 分支后继续执行);glob 展开(5 个 alert_analyze 文件)正确传入;字面量未展开时被 `exists()` 丢弃的坑已在 §1-2 用 `cd` 修掉;**门控**(首次未成功才跑二次)+ **逐次窗口**(60 vs 120)已单独验证。

## 5. 未做 / 范围外(诚实标注)

- **未改 deploy.sh / check_data_integrity.py**(F2 无需动,recon §4 已论证)。
- **未修 #235 交易历口径(F1,另一任务)**;未碰 #241 同族(`check_data_gap_alerts.py` / `sensenova-proxy-healthcheck.py` / `overfit_monitor.py`)。
- **未修 #237 fund_nav/large-json 分片持锁(长锁 68min→短)**——那是 FAIL-1 的**根本修复**,本任务**不依赖**它,F2 靠双次尝试在当前现实下自行可用;该修复落地后 F2 首次窗口即大概率命中,二次成为冗余保险(无副作用)。
- **未改 `docs/pending-features-index.md` 状态列**(#236 仍「待拍板」)——状态登记归主控收口。
- 未在 mac 上做 R2 写(被 export-guard L2 拦,属预期)。

## 6. 回滚说明

**代码回滚**(改动仅在 feat 分支的 `scripts/update_all.sh` 一处):

```bash
# 方式 A(推荐,保留历史)
git revert <本 commit hash>
# 方式 B(若尚未 merge main,直接丢弃)
git checkout main -- scripts/update_all.sh
```

回滚后 alert.json 的上传通道回到「仅 deploy 内 upload-all-data」= 死锁结构恢复(即回到修复前状态,不会更坏)。

**数据回滚**:本次 PUT 的 alert.json **内容与上传前逐位相同**(md5 一致,仅 Last-Modified 推进),**无需恢复内容**。若将来确需回到本次备份点:

```bash
# 云上
cp /home/ubuntu/backup/f2-236-20261009/alert.json.before \
   /home/ubuntu/code/trade-data/static-site/data/alert.json
cd /home/ubuntu/code/trade-data/static-site/data && \
  REPO=/home/ubuntu/code/trade-data \
  /home/ubuntu/code/trade-data/.venv/bin/python \
  /home/ubuntu/code/trade-data/scripts/upload_r2.py upload-data-files alert.json
```

## 7. 证据索引(可复核)

- 代码:`scripts/update_all.sh` L174-176(C6 注释)/ L187-237(F2 首次尝试块,含 `alert_r2_upload()` 函数)/ L263-274(F2b 二次尝试块);`scripts/update_all.sh` L37(`export REPO GIT_REPO`);`scripts/upload_r2.py`(cmd_upload_data_files / `_acquire_r2_upload_lock` / `--skip-if-locked` / `R2_UPLOAD_SKIP_RETRY_SECS` / `_record_standalone_keys`);先例 `scripts/s06_snapshot.sh` L133。
- 云上:备份 `/home/ubuntu/backup/f2-236-20261009/alert.json.before`(md5 65c60ad5…);T1 上传后 `ssd HEAD /data/alert.json` `LM=Fri, 09 Oct 2026 09:16:23 GMT`/`etag=65c60ad5…`;T2 后再验 `LM` 未变(=零写)。
- 线上:`ss.fx8.store/data/alert.json` GET md5=65c60ad5…。
- 结构:`docs/ops/deploy-selflock-recon-20261009.md` §2(死锁行号)/§4(F1+F2 互补)/§5(F2 方向);`docs/ops/236-f2-alert-upload-decouple-review-20261009.md`(独立审查:7 PASS/2 FAIL,本阶段修复 FAIL-1 双次尝试 + FAIL-2 过度宣称)。

## 8. 复审追加观察(2026-10-09 二次独立审 reviewer 提供,如实登记)

> 来源:二次独立审查(`236-f2-review2-20261009.md`)。代码 6 项全 PASS;以下 3 条为审查观察,不属本任务修复范围,**如实登记不擅自处置**。

1. **update_all 新入 SKIPPED_LOCKED 监测面(#181 冻结面牵动)**:F2 的 `SKIPPED_LOCKED` 输出进了 update_all 日志 ⇒ 落进「上传缺口」监测口径。计数按**轮**去重不放大(同轮多次尝试只计一轮);但「**try1 跳过 + try2 成功**」之夜**仍留一行计数** —— 连续 3 夜出现窄窗竞争会触发「上传缺口持续」**误报**。**处置:记录不动**(不改监测口径、不为 F2 加特例;若日后真误报,再按 #181 冻结面流程评估)。
2. **§22 瞬态错位(F2 成功形态的伴生,非缺陷)**:F2 于 ≈19:30 起把 R2 的 alert.json 更新为 T 日;而**首页预警条读的是 `boot.alert`**,要等 **20:07 backfill 链的 deploy 重生成 ≈20:10** 才跟上 ⇒ 中间**约 40 分钟**「R2 alert.json(T)vs 首页 boot.alert(旧)」两个展示位不一致。这是 F2 落地后新引入的瞬态窗口。**处置:记录 + 上报主控待拍板,不擅自改行为**(§23.7 已上线功能冻结:动展示位时序须用户确认)。
3. **理论边界(仅登记)**:若本地 `alert.json` / `alert_analyze_*.json` **全部缺失**,`cmd_upload_data_files` 会打 `⚠ 无文件` 但 **rc=0** ⇒ F2 会打一个**假的 ✓**(「完成」)而实际零上传。当前不会发生(上游 C6/C7 export 已生成文件);仅登记该理论边界,未改行为。

---
*实施 agent 落档;只 commit + push feat 分支,不 push main;merge 由主控走 `scripts/main-merge.sh`。*